from __future__ import annotations
import re
import unicodedata
from .models import ResearchProfile


def normalize(text: str) -> str:
    text = text.replace("\u0130", "i").replace("\u0131", "i").casefold()
    text = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    return " ".join(re.findall(r"\w+", text))


def contains(text: str, term: str) -> bool:
    # Phrase boundaries prevent e.g. "AI" matching "training".
    n, t = normalize(text), normalize(term)
    return bool(t and re.search(r"(?<!\w)" + re.escape(t) + r"(?!\w)", n))


def normalize_doi(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", value)
    return value.rstrip(" .;,") if value.startswith("10.") else ""


def _broad_queries(profile: ResearchProfile, limit: int) -> list[dict]:
    groups = profile.concept_groups
    def quote(t):
        return '"' + t.replace('"', " ").strip() + '"'
    def clause(g):
        return "(" + " OR ".join(quote(t) for t in g) + ")"
    queries = []
    def add(selected, label):
        boolean = " AND ".join(clause(g) for g in selected)
        # Crossref uses relevance text, not OpenAlex Boolean grammar.
        plain = " ".join(g[0] for g in selected)
        if not any(q["boolean"] == boolean for q in queries):
            queries.append({"boolean": boolean, "plain": plain, "label": label})
    add(groups, "All concept groups")
    if len(groups) > 1:
        for i in range(len(groups)):
            for j in range(i + 1, len(groups)):
                add([groups[i], groups[j]], "Pairwise concept search")
    for g in groups:
        add([g], "Broad concept search")
    # An English/alternative query gives non-Boolean sources synonym coverage too.
    for index in range(1, min(4, max(map(len, groups)))):
        selected = [[g[min(index, len(g) - 1)]] for g in groups]
        add(selected, "Alternative terminology search")
    # Reserve one slot for alternate terminology if a long pair list fills the cap.
    if len(queries) > limit and limit > 1:
        alternate = next((q for q in queries if q["label"] == "Alternative terminology search"), None)
        return queries[:limit - 1] + [alternate or queries[limit - 1]]
    return queries[:limit]



def extract_mechanism_phrases(profile, limit=6):
    """Deterministic phrase suggestions, not inferred scientific mechanisms."""
    from collections import Counter
    from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS
    stops = set(ENGLISH_STOP_WORDS) | {'research', 'study', 'results', 'current', 'proposed', 'using', 'based', 'compared', 'versus', 'achieved', 'reported', 'mean', 'training', 'test', 'samples'}
    text = profile.title + '. ' + profile.description
    words = re.findall(r"[A-Za-z][A-Za-z-]*|[.!?;,:]", text.lower())
    candidates = Counter()
    for size in (2, 3):
        for i in range(len(words)-size+1):
            group = words[i:i+size]
            if any(w in stops or len(w)<3 or not w[0].isalpha() for w in group):
                continue
            phrase = ' '.join(group)
            if any(normalize(phrase)==normalize(t) for g in profile.concept_groups for t in g):
                continue
            candidates[phrase] += 1 + int(phrase in profile.title.lower())
    chosen=[]
    for phrase, _ in sorted(candidates.items(), key=lambda pair:(-pair[1], -len(pair[0].split()), pair[0])):
        if not any(phrase in previous or previous in phrase for previous in chosen):
            chosen.append(phrase)
        if len(chosen)>=limit:break
    return chosen


def build_queries(profile: ResearchProfile, limit: int) -> list[dict]:
    """Round-robin query families prevent broad searches consuming every slot."""
    def phrase(term):
        return '"' + term.replace('"',' ').strip() + '"'
    def group(terms):
        return '(' + ' OR '.join(phrase(t) for t in terms) + ')'
    families={"seed_title":[], "targeted":[], "mechanism":[], "broad":_broad_queries(profile, max(limit,30)), "derived_phrase":[]}
    for title in profile.seed_titles:
        families['seed_title'].append({'boolean':phrase(title),'plain':title,'label':'Named comparator','family':'seed_title'})
    for query in profile.targeted_queries:
        families['targeted'].append({'boolean':query,'plain':re.sub(r'\b(?:AND|OR|NOT)\b|[()"]',' ',query),'label':'Explicit targeted query','family':'targeted'})
    for mechanisms in profile.mechanism_groups:
        boolean=group(mechanisms)
        families['mechanism'].append({'boolean':boolean,'plain':mechanisms[0],'label':'Architectural mechanism','family':'mechanism'})
        for concept in profile.concept_groups[:2]:
            families['mechanism'].append({'boolean':boolean+' AND '+group(concept),'plain':mechanisms[0]+' '+concept[0],'label':'Mechanism + topic','family':'mechanism'})
    if not profile.mechanism_groups:
        for term in extract_mechanism_phrases(profile):
            families['derived_phrase'].append({'boolean':phrase(term),'plain':term,'label':'Heuristic phrase from title/description','family':'derived_phrase'})
    for query in families['broad']:query['family']='broad'
    output=[];seen=set()
    # Always retain a topic anchor; use remaining slots across independent families.
    if families['broad']:
        anchor=families['broad'].pop(0);output.append(anchor);seen.add(anchor['boolean'])
    while len(output)<limit:
        advanced=False
        for family in ('seed_title','targeted','mechanism','derived_phrase','broad'):
            while families[family]:
                query=families[family].pop(0)
                if query['boolean'] not in seen:
                    output.append(query);seen.add(query['boolean']);advanced=True;break
            if len(output)>=limit:break
        if not advanced:break
    return output
