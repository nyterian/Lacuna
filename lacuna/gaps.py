"""Extract attributed research-gap statements, never infer unstudied topics."""
from __future__ import annotations

import hashlib
import re
from collections import Counter
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS
from .models import GapCandidate, GapEvidence, RunConfig
from .query import contains, normalize


PATTERNS = {
    "open_question": [r"\b(?:remains?|remain)\s+(?:an?\s+)?(?:open|unresolved)\b", r"\b(?:open question|open problem|unanswered question)s?\b", r"\bnot\s+(?:yet\s+)?(?:been\s+)?(?:resolved|investigated|addressed)\b"],
    "future_work": [r"\bfuture (?:works?|research|studies|investigations?|directions?)\b", r"\bfurther (?:work|research|investigation|evaluation)\s+(?:(?:is|are)\s+(?:needed|required|necessary)|should|could|will|would|may|must)\b", r"\bwe (?:plan|intend) to\b", r"\bshould (?:be )?(?:investigated|evaluated|explored|tested|extended)\b", r"\b(?:gelecek|ileriki) \u00e7al\u0131\u015fmalar\b", r"\bgelecekte\b"],
    "limitation": [r"\b(?:a|the|this|our|several|major) limitations?\b", r"\b(?:was|were|is) (?:only )?limited to\b", r"\bbeyond the scope\b", r"\b(?:was|were|has|have) not (?:been )?(?:evaluated|tested|examined|investigated)\b", r"s\u0131n\u0131rl\u0131l\u0131k", r"(?:incelenmemi\u015ftir|ele al\u0131nmam\u0131\u015ft\u0131r)"],
}
HEADINGS = {
    "future_work": r"future (?:works?|research|directions)|recommendations|further (?:work|research)|gelecek \u00e7al\u0131\u015fmalar|\u00f6neriler",
    "limitation": r"limitations?|s\u0131n\u0131rl\u0131l\u0131klar|k\u0131s\u0131tl\u0131l\u0131klar",
    "open_question": r"open (?:problems|questions)|unresolved (?:issues|questions)",
}
NEGATIONS = re.compile(r"\b(?:no limitations?|not a limitation|not limited to|limitations? (?:was|were|has been|have been) (?:resolved|overcome|addressed)|no (?:further|future) work)\b", re.I)
REFERENCE_HEADING = re.compile(r"^(?:\d+[.\s]*)?(?:references|bibliography|works cited|kaynak\u00e7a)\s*$", re.I)


def build_gap_queries(profile, limit):
    """Keep field-topic constraints; never search generic template prose alone."""
    from .query import _broad_queries
    queries=_broad_queries(profile,limit)
    for query in queries:query["family"]="thesis_topic"
    targeted=[{"boolean":q,"plain":re.sub(r'\b(?:AND|OR|NOT)\b|[()"]',' ',q),"label":"Explicit field-topic query","family":"thesis_topic"} for q in profile.targeted_queries]
    if queries:
        targeted.append({"boolean":queries[0]["boolean"]+' AND ("future work" OR "limitations" OR "open question")',
                         "plain":queries[0]["plain"]+' future work limitations',"label":"Field topic with gap-language cues","family":"thesis_gap_cues"})
    ordered=queries[:1]+targeted+queries[1:]
    seen=set();result=[]
    for query in ordered:
        if query["boolean"] not in seen:
            result.append(query);seen.add(query["boolean"])
        if len(result)>=limit:break
    return result


def spans(text):
    """Exact sentence offsets; no rewriting of source evidence."""
    start = 0
    for separator in re.finditer(r"(?<=[.!?])\s+(?=[A-Z\u00c0-\u017f])|\n\s*\n", text):
        end = separator.start()
        left, right = start, end
        while left < right and text[left].isspace():left += 1
        while right > left and text[right-1].isspace():right -= 1
        if right > left:yield left, right
        start = separator.end()
    left, right = start, len(text)
    while left < right and text[left].isspace():left += 1
    while right > left and text[right-1].isspace():right -= 1
    if right > left:yield left, right


def excerpt_spans(text, inherited_section=""):
    # Heading offsets determine attribution, including sections spanning pages.
    headings=[];section=inherited_section;in_references=False
    offset=0
    for line in text.splitlines(keepends=True):
        stripped=line.strip()
        if REFERENCE_HEADING.fullmatch(stripped):
            headings.append((offset,"references"));in_references=True
        elif len(stripped)<100 and not re.search(r"\.{3}|\s\d+\s*$",stripped):
            for kind,pattern in HEADINGS.items():
                if re.fullmatch(r"(?:\d+(?:\.\d+)*[.)]?\s+)?(?:(?:conclusions?|discussion|summary)\s+(?:and|&)\s+)?(?:"+pattern+r")(?:\s+(?:and|&)\s+conclusions?)?\s*:?",stripped,re.I):
                    headings.append((offset,kind));in_references=False;break
            else:
                if re.match(r"^(?:chapter\s+\d+|\d+(?:\.\d+)*[.)]?\s+[A-Z])",stripped,re.I) and not re.search(r"[.!?]\s*$",stripped):
                    headings.append((offset,""));in_references=False
        offset+=len(line)
    for left,right in spans(text):
        active=section
        for position,heading in headings:
            if position<=left:active=heading
        fragment=text[left:right]
        if active=="references" or len(fragment)<35 or NEGATIONS.search(fragment):continue
        if re.search(r"\b(?:chapter|section)\s+\d+\s+(?:presents?|discusses?|contains?|describes?)\b", fragment, re.I):continue
        for kind,patterns in PATTERNS.items():
            match=next((m for pattern in patterns if (m:=re.search(pattern.replace(" ",r"\s+"),fragment,re.I))),None)
            if match:
                cue_line=fragment[:match.start()].rsplit("\n",1)[-1]+fragment[match.start():].split("\n",1)[0]
                if re.search(r"\.{3,}\s*\d+\s*$",cue_line) or (len(cue_line)<100 and re.search(r"\s\d+\s*$",cue_line)):
                    continue
                # Do not label an arbitrary paragraph in a Future Work section as
                # unfinished; every candidate requires an explicit textual cue.
                center=left+match.start()
                begin=max(left,center-250);end=min(right,begin+1400)
                yield kind,begin,end,active if active in HEADINGS else "",match.group(0),begin>left or end<right
                break
    return headings[-1][1] if headings else section


def follow_up_query(candidate, profile):
    words=re.findall(r"[a-z][a-z-]{3,}",candidate.statement.lower())
    stop=set(ENGLISH_STOP_WORDS)|{"future","work","research","study","studies","limited","limitation","limitations","investigated","evaluated","should","further","proposed","remains","open","question"}
    terms=[word for word,_ in Counter(w for w in words if w not in stop).most_common(4)]
    topic=profile.concept_groups[0][0].replace('"',' ')
    return '"'+topic+'"' + (" AND ("+" OR ".join('"'+t+'"' for t in terms)+")" if terms else "")


def extract_field_gaps(studies, profile, config):
    candidates=[];seen={};coverage={"theses_inspected":0,"theses_with_full_text":0,"theses_abstract_only":0,"theses_partial_text":0,"source_reading_notes":{},"unknown_type_skipped":0,"topic_mismatch_skipped":0}
    terms=[term for group in profile.concept_groups for term in group]
    for study in studies:
        if study.type!="dissertation":
            coverage["unknown_type_skipped"]+=int(study.type=="unknown")
            continue
        coverage["theses_inspected"]+=1
        doc="\n".join([study.title,study.abstract,*study.pages])
        def topic_match(term):
            if contains(doc,term):return True
            words=[word for word in normalize(term).split() if word not in ENGLISH_STOP_WORDS and len(word)>2]
            return len(words)>=2 and all(contains(doc,word) for word in words)
        matched=[term for term in terms if topic_match(term)]
        if not matched:
            coverage["topic_mismatch_skipped"]+=1;continue
        has_text=bool(study.pages_read and study.pages)
        coverage["theses_with_full_text"]+=int(has_text)
        coverage["theses_partial_text"]+=int(study.full_text_status=="partial")
        if study.full_text_note:coverage["source_reading_notes"][study.id]=study.full_text_note
        coverage["theses_abstract_only"]+=int(not has_text and bool(study.abstract))
        sources=[("full_text",page,text) for page,text in enumerate(study.pages,1)] if has_text else [("abstract",None,study.abstract)]
        count=0;section=""
        for kind,page,text in sources:
            # Consume the generator's returned section for following pages.
            generator=excerpt_spans(text,section)
            while True:
                try:category,left,right,heading,cue,truncated=next(generator)
                except StopIteration as stop:
                    section=stop.value if stop.value is not None else section;break
                quote=text[left:right]
                key=normalize(quote)
                if not key:continue
                basis="provider_metadata" if any(source in study.sources for source in ("openalex","crossref","core","oai")) else "user_asserted_thesis" if "local_pdf" in study.sources else "imported_record_type"
                evidence=GapEvidence(study_id=study.id,title=study.title,year=study.year,url=study.url,doi=study.doi,kind=kind,page=page,section=heading,quote=quote,cue=cue,start=left,end=right,truncated=truncated,source_type_basis=basis)
                if key in seen:
                    candidate=seen[key]
                    if not any(e.study_id==study.id for e in candidate.evidence):candidate.evidence.append(evidence)
                    candidate.support_count=len({e.study_id for e in candidate.evidence})
                elif len(candidates)<config.gap_max_candidates:
                    candidate=GapCandidate(id="g_"+hashlib.sha256(key.encode()).hexdigest()[:12],category=category,statement=quote,topic_terms=matched,evidence=[evidence])
                    candidate.follow_up_query=follow_up_query(candidate,profile)
                    candidates.append(candidate);seen[key]=candidate
                count+=1
                if count>=config.gap_per_study:break
            if count>=config.gap_per_study:break
    coverage.update(candidate_count=len(candidates),openness_status="unverified",extraction="explicit_cue_rules",topic_matching="phrase_or_all_content_tokens",all_candidates_are_author_reports=True)
    return candidates,coverage


def verify_gap_candidates(candidates, profile, config, client, openalex_key=""):
    """Retrieve possible counterevidence; never declare a gap closed or open."""
    from .sources import search_openalex, search_crossref
    from .scoring import deduplicate
    related=[];attempts=[]
    source="openalex" if "openalex" in config.sources else "crossref" if "crossref" in config.sources else None
    for candidate in candidates:candidate.verification_status="not_checked_limit" if source else "not_checked_no_supported_source"
    if source is None:return [],attempts
    for candidate in candidates[:config.gap_follow_up_queries]:
        years=[e.year for e in candidate.evidence if e.year]
        later=profile.model_copy(update={"year_from":min(years) if years else None,"types":["article","conference-paper","preprint","review","dissertation","other"]})
        cfg=config.model_copy(update={"per_source":5,"max_queries":1})
        query={"boolean":candidate.follow_up_query,"plain":" ".join(re.findall(r'[\w-]+',candidate.follow_up_query.replace('AND','').replace('OR',''))),"label":"Gap counterevidence search","family":"gap_follow_up"}
        start=len(client.log)
        found=search_openalex(client,later,cfg,[query],openalex_key) if source=="openalex" else search_crossref(client,later,cfg,[query])
        for log in client.log[start:]:log.update(purpose="gap_follow_up",gap_id=candidate.id)
        failed=any(log.get("status")=="error" for log in client.log[start:])
        own_ids={e.study_id for e in candidate.evidence};own_dois={e.doi.lower() for e in candidate.evidence if e.doi};own_titles={normalize(e.title) for e in candidate.evidence}
        found=[s for s in deduplicate(found) if s.id not in own_ids and s.doi.lower() not in own_dois and normalize(s.title) not in own_titles and (s.year is None or (not years or s.year>=min(years))) and s.year is not None and s.year<=profile.year_to]
        candidate.related_work_ids=[s.id for s in found]
        candidate.verification_status="search_failed" if failed else "related_work_found_review_required" if found else "no_matches_in_bounded_search"
        related.extend(found)
        attempts.append({"gap_id":candidate.id,"query":candidate.follow_up_query,"source":source,"status":candidate.verification_status,"results":len(found),"date_rule":"same_or_later_publication_year"})
    return deduplicate(related),attempts
