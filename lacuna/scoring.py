from __future__ import annotations
import hashlib
import re
from rapidfuzz.fuzz import ratio
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from .models import Study, Evidence
from .query import normalize, normalize_doi, contains


def merge_into(target: Study, incoming: Study):
    for field in ("sources", "source_queries", "references", "duplicate_candidates", "pdf_urls"):
        setattr(target, field, list(dict.fromkeys(getattr(target, field) + getattr(incoming, field))))
    target.source_ids.update(incoming.source_ids)
    if len(incoming.abstract) > len(target.abstract):
        target.abstract = incoming.abstract
    for field in ("doi", "url", "pdf_url", "year", "language", "authors", "file_sha256", "local_filename"):
        if not getattr(target, field):
            setattr(target, field, getattr(incoming, field))
    if target.type == "other" and incoming.type != "other":
        target.type = incoming.type
    if incoming.pages:
        target.pages = incoming.pages
        target.pages_read, target.pages_total = incoming.pages_read, incoming.pages_total
        target.full_text_status, target.full_text_note = incoming.full_text_status, incoming.full_text_note


def deduplicate(studies: list[Study]) -> list[Study]:
    out = []
    for study in studies:
        study.doi = normalize_doi(study.doi)
        title = normalize(study.title)
        match = None
        for previous in out:
            shared_ids = any(previous.source_ids.get(k) == v for k, v in study.source_ids.items() if v)
            same_file = bool(study.file_sha256 and study.file_sha256 == previous.file_sha256)
            same_doi = bool(study.doi and study.doi == previous.doi)
            conflicting_doi = bool(study.doi and previous.doi and study.doi != previous.doi)
            same_title = len(title) >= 20 and title == normalize(previous.title) and study.year == previous.year
            # Different known DOIs stay distinct even when titles match.
            if shared_ids or same_file or same_doi or (same_title and not conflicting_doi):
                match = previous
                break
        if match:
            merge_into(match, study)
        else:
            identity = study.doi or next((f"{k}:{v}" for k, v in study.source_ids.items() if v), title + str(study.year))
            study.id = "s_" + hashlib.sha256(identity.encode()).hexdigest()[:12]
            out.append(study)
    # Fuzzy similarity is disclosed for manual checking; it never silently deletes records.
    for i, a in enumerate(out):
        for b in out[i+1:]:
            if a.year == b.year and len(a.title) > 20 and ratio(normalize(a.title), normalize(b.title)) >= 94:
                a.duplicate_candidates = list(dict.fromkeys(a.duplicate_candidates + [b.id]))
                b.duplicate_candidates = list(dict.fromkeys(b.duplicate_candidates + [a.id]))
    return out


def tfidf_scores(query: str, documents: list[str], analyzer="word") -> list[float]:
    if not documents:
        return []
    try:
        vectorizer = TfidfVectorizer(analyzer=analyzer, ngram_range=(1, 2) if analyzer == "word" else (3, 5),
                                     preprocessor=normalize, max_features=60000, sublinear_tf=True)
        matrix = vectorizer.fit_transform([query, *documents])
        return cosine_similarity(matrix[0:1], matrix[1:]).ravel().tolist()
    except ValueError:  # Empty vocabulary from punctuation-only/scanned documents.
        return [0.0] * len(documents)


def rank_studies(studies, profile):
    # All records use the same title/abstract fields. Full text enriches evidence,
    # not the ranking, so access status does not create an opaque score advantage.
    texts = [s.title + "\n" + s.abstract for s in studies]
    words = tfidf_scores(profile.query_text(), texts)
    chars = tfidf_scores(profile.query_text(), texts, "char_wb")
    for s, w, c in zip(studies, words, chars):
        s.word_score, s.character_score = round(w*100, 2), round(c*100, 2)
        s.score = round(100*(.7*w + .3*c), 2)
        evidence_text = "\n".join([s.title, s.abstract, *s.pages])
        s.concept_matches = [[t for t in g if contains(evidence_text, t)] for g in profile.concept_groups]
        s.mechanism_matches = [[t for t in g if contains(evidence_text, t)] for g in profile.mechanism_groups]
        s.dimension_matches = {name: [t for t in getattr(profile, name) if contains(evidence_text, t)]
                               for name in ("population", "methods", "geography")}
    return sorted(studies, key=lambda s: (-s.score, s.id))


def make_evidence(study, profile, limit):
    candidates = [("title", None, study.title)]
    if study.abstract:
        candidates.append(("abstract", None, study.abstract))
    for page, text in enumerate(study.pages, 1):
        # Bounded excerpts, with overlap, preserve context and exact PDF page.
        for offset in range(0, len(text), 900):
            chunk = text[max(0, offset-100):offset+1100].strip()
            if len(chunk) > 30:
                candidates.append(("full_text", page, chunk))
    scores = tfidf_scores(profile.query_text(), [c[2] for c in candidates])
    terms = [t for g in profile.concept_groups + profile.mechanism_groups for t in g] + profile.population + profile.methods + profile.geography
    evidence = []
    seen = set()
    for index in sorted(range(len(candidates)), key=lambda i: -scores[i]):
        kind, page, text = candidates[index]
        fingerprint = normalize(text)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        evidence.append(Evidence(text=text, kind=kind, page=page, score=round(scores[index]*100, 2),
                                 matched_terms=[t for t in terms if contains(text, t)]))
        if len(evidence) >= limit:
            break
    study.evidence = evidence
    return study
