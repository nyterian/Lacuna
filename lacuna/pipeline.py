from __future__ import annotations
from collections import Counter
from pathlib import Path
import uuid
from .models import ResearchProfile, RunConfig, RunResult, utcnow
from .net import WebClient
from .query import build_queries, contains, normalize_doi
from .sources import search_openalex, search_crossref, search_core, harvest_oai, from_openalex, load_records
from .scoring import deduplicate, rank_studies, make_evidence, merge_into
from .documents import read_pdf, attach_pdf


def apply_filters(studies, profile):
    kept, excluded = [], []
    for study in studies:
        reason = ""
        if study.year is not None and (study.year > profile.year_to or (profile.year_from is not None and study.year < profile.year_from)):
            reason = "date"
        elif study.type not in profile.types and study.type != "unknown":
            reason = "type"
        elif profile.languages and study.language and study.language not in profile.languages:
            reason = "language"
        else:
            text = "\n".join([study.title, study.abstract, *study.pages])
            matches = [term for term in profile.excluded_terms if contains(text, term)]
            if matches:
                reason = "excluded_terms: " + ", ".join(matches)
        if reason:
            excluded.append({"id": study.id, "title": study.title, "reason": reason})
        else:
            kept.append(study)
    return kept, excluded


def expand_citations(client, studies, profile, config, key, edges, visited=None):
    added = []
    visited = visited if visited is not None else set()
    seeds = [s for s in studies if s.source_ids.get("openalex") and s.source_ids["openalex"] not in visited][:config.citation_seeds]
    for seed in seeds:
        visited.add(seed.source_ids["openalex"])
        source_id = seed.source_ids["openalex"].split("/")[-1]
        for direction, field in (("references", "cited_by"), ("citing", "cites")):
            filters = f"{field}:{source_id}"
            params = {"filter": filters, "per_page": min(25, config.per_source)}
            if key:
                params["api_key"] = key
            try:
                data = client.json("https://api.openalex.org/works", params=params, source="openalex_citations",
                                   label=f"{direction}:{source_id}; at most {params['per_page']} records")
                client.log[-1].update(returned_records=len(data.get("results", [])), total_available=data.get("meta", {}).get("count"), page_record_limit=params["per_page"])
                for item in data.get("results", []):
                    added.append(from_openalex(item, f"{direction}:{source_id}"))
                    # Semantic direction: from is always citing work, to is cited work.
                    edges.append({"from": seed.source_ids["openalex"] if direction == "references" else item.get("id"),
                                  "to": item.get("id") if direction == "references" else seed.source_ids["openalex"],
                                  "relation": "cites"})
            except RuntimeError:
                continue
    return added


def run_research(profile: ResearchProfile, config: RunConfig, *, pdfs=None, imports=None,
                 db_path=None, openalex_key="", core_key="", progress=None, client=None) -> RunResult:
    progress = progress or (lambda fraction, message: None)
    if config.analysis_mode == "topic_branches":
        if pdfs or imports:
            raise ValueError("Topic branching uses the OpenAlex taxonomy; local PDF/record inputs are not used. Remove them for this mode.")
        from .branches import run_topic_branches
        return run_topic_branches(profile, config, db_path=db_path, openalex_key=openalex_key, progress=progress, client=client)
    thesis_filter_applied = config.analysis_mode == "field_gaps" and profile.types != ["dissertation"]
    if config.analysis_mode == "field_gaps":
        profile = profile.model_copy(update={"types": ["dissertation"]})
    result = RunResult(run_id=uuid.uuid4().hex[:12], started_at=utcnow(), profile=profile, config=config)
    if thesis_filter_applied:
        result.warnings.append("Field-gap mode applies a thesis-only publication filter; the effective profile is recorded in the result.")
    own_client = client is None
    client = client or WebClient(Path(db_path or "data/research.sqlite"), config.request_budget, config.use_cache)
    if config.analysis_mode=="field_gaps":
        from .gaps import build_gap_queries
        queries=build_gap_queries(profile,config.max_queries)
    else:
        queries = build_queries(profile, config.max_queries)
    studies = []
    raw_counts = {}
    initial_log_index = len(client.log)
    try:
        progress(.04, "Preparing research specification and queries")
        for filename, body in imports or []:
            try:
                loaded = load_records(filename, body)
                studies.extend(loaded)
                raw_counts["import"] = raw_counts.get("import", 0) + len(loaded)
            except Exception as exc:
                result.warnings.append(f"{Path(filename).name}: record import failed ({type(exc).__name__}: {exc}).")
        for filename, body in pdfs or []:
            try:
                if len(body) > config.max_pdf_mb * 1024 * 1024:
                    raise ValueError("PDF exceeds the configured size limit.")
                pdf = read_pdf(body, filename, config.max_pages, include_tail=config.analysis_mode=="field_gaps")
                if config.analysis_mode == "field_gaps" and config.local_documents_are_theses:
                    pdf.type = "dissertation"
                studies.append(pdf)
                raw_counts["local_pdf"] = raw_counts.get("local_pdf", 0) + 1
            except Exception as exc:
                result.warnings.append(f"{Path(filename).name}: PDF could not be processed ({type(exc).__name__}).")
        for index, source in enumerate(config.sources):
            progress(.12 + .3 * index / max(1, len(config.sources)), f"Searching {source}")
            try:
                if source == "openalex":
                    found = search_openalex(client, profile, config, queries, openalex_key)
                elif source == "crossref":
                    found = search_crossref(client, profile, config, queries)
                elif source == "core":
                    if not core_key:
                        result.warnings.append("CORE was selected without an API key; this source was not searched.")
                    found = search_core(client, profile, config, queries, core_key)
                elif source == "oai" and config.oai_url:
                    found = harvest_oai(client, config)
                    result.warnings.append("OAI-PMH does not support topic search: a bounded repository sample was harvested and compared locally; the entire repository was not searched.")
                else:
                    found = []
                    result.warnings.append(f"Source is not configured: {source}.")
                raw_counts[source] = len(found)
                studies.extend(found)
            except Exception as exc:
                result.warnings.append(f"{source} failed ({type(exc).__name__}); processing continued with other sources.")
        # DOI seeds are fetched independently of vocabulary search.
        if profile.seed_dois and "openalex" in config.sources:
            for seed in profile.seed_dois[:20]:
                doi = normalize_doi(seed)
                if not doi:
                    result.warnings.append("An invalid seed DOI was skipped.")
                    continue
                try:
                    params = {"filter": f"doi:https://doi.org/{doi}"}
                    if openalex_key:
                        params["api_key"] = openalex_key
                    data = client.json("https://api.openalex.org/works", params=params, source="openalex_seed", label=doi)
                    studies.extend(from_openalex(item, "seed:" + doi) for item in data.get("results", []))
                except RuntimeError:
                    continue
        progress(.45, "Merging duplicate records and calculating proximity")
        before = len(studies)
        studies = deduplicate(studies)
        duplicate_count = before-len(studies)
        studies, excluded = apply_filters(studies, profile)
        result.excluded.extend(excluded)
        studies = rank_studies(studies, profile)
        expanded_ids = set()
        for round_index in range(config.citation_rounds):
            if "openalex" not in config.sources:
                break
            progress(.50, f"Expanding citation graph: round {round_index+1}")
            added = expand_citations(client, studies, profile, config, openalex_key, result.citation_edges, expanded_ids)
            if not added:
                break
            old_count = len(studies)
            studies = deduplicate(studies + added)
            studies, excluded = apply_filters(studies, profile)
            result.excluded.extend(excluded)
            studies = rank_studies(studies, profile)
            if len(studies) == old_count:
                break
        progress(.63, "Processing open-access documents")
        from .selection import select_portfolio
        eligible = [s for s in studies if s.pdf_url and not s.pages]
        downloadable, _ = select_portfolio(eligible, profile, config.max_downloads)
        pdf_outcomes = []
        for index, study in enumerate(downloadable):
            progress(.63 + .15*(index+1)/max(1, len(downloadable)), f"Reading PDF: {index+1}/{len(downloadable)}")
            urls = list(dict.fromkeys([study.pdf_url, *study.pdf_urls]))[:3]
            for url in urls:
                attempt = {"study_id": study.id, "stage": "retrieval", "status": "pending"}
                try:
                    body = client.request(url, source="pdf", label=study.id, max_bytes=config.max_pdf_mb*1024*1024)
                    attempt["stage"] = "parsing"
                    pdf = read_pdf(body, study.id + ".pdf", config.max_pages, include_tail=config.analysis_mode=="field_gaps")
                    attach_pdf(study, pdf)
                    attempt.update(status=pdf.full_text_status, pages_read=pdf.pages_read)
                    study.full_text_attempts.append(attempt)
                    if study.pages_read:
                        break
                except Exception as exc:
                    attempt.update(status="failed", error_type=type(exc).__name__)
                    study.full_text_attempts.append(attempt)
                    study.full_text_status = "failed"
                    study.full_text_note = f"Full-text {attempt['stage']} failed ({type(exc).__name__}); metadata was retained."
            pdf_outcomes.extend(study.full_text_attempts)
        studies, excluded = apply_filters(studies, profile)
        result.excluded.extend(excluded)
        studies = rank_studies(studies, profile)
        progress(.82, "Preparing evidence excerpts and comparison matrix")
        for study in studies:
            make_evidence(study, profile, config.evidence_per_study)
        result.studies = studies
        if config.analysis_mode == "field_gaps":
            from .gaps import extract_field_gaps, verify_gap_candidates
            progress(.9, "Extracting author-reported limitations and open questions from theses")
            result.gap_candidates, result.gap_analysis = extract_field_gaps(studies, profile, config)
            related, attempts = verify_gap_candidates(result.gap_candidates, profile, config, client, openalex_key)
            result.gap_related_studies = related
            result.gap_analysis.update(follow_up_searches=attempts, candidate_limit=config.gap_max_candidates,
                                       per_thesis_limit=config.gap_per_study, checked_candidate_limit=config.gap_follow_up_queries)
            result.warnings.append("Gap candidates are attributed author statements, not verified current gaps. Later work may have addressed them; related matches require human review.")
            if not result.gap_candidates:
                result.warnings.append("No explicit gap statements were extracted from the accessible thesis text. This does not mean the field is complete; check full-text access and topic terms.")
            if result.gap_analysis["unknown_type_skipped"]:
                result.warnings.append("Documents of unknown type were excluded from thesis gap extraction. Mark uploaded documents as theses only if you know their type.")
        result.citation_edges = list({(e["from"], e["to"]): e for e in result.citation_edges}.values())
        result.completed_at = utcnow()
        result.search_log = client.log[initial_log_index:]
        source_errors = Counter(e.get("source", "unknown") for e in result.search_log if e.get("status") == "error")
        if source_errors:
            result.warnings.append("Some requests failed: " + ", ".join(f"{s} ({n})" for s, n in source_errors.items()) + ". Inspect the request log or search_log.json for details.")
        failed_documents = sum(s.full_text_status == "failed" for s in downloadable)
        if failed_documents:
            retrieval = sum(a["status"] == "failed" and a["stage"] == "retrieval" for a in pdf_outcomes)
            parsing = sum(a["status"] == "failed" and a["stage"] == "parsing" for a in pdf_outcomes)
            result.warnings.append(f"Full-text processing failed for {failed_documents}/{len(downloadable)} documents; failed attempts: retrieval={retrieval}, parsing={parsing}. See full_text_attempts and coverage.pdf_processing.")
        if profile.year_from is not None:
            result.warnings.append(f"Lower publication-year bound {profile.year_from} excludes older prior work. Set year_from to null for historical discovery.")
        if config.analysis_mode != "field_gaps" and "conference-paper" not in profile.types:
            result.warnings.append("Conference papers are excluded by profile.types. Include conference-paper when reviewing architectural prior work.")
        if config.analysis_mode != "field_gaps" and not profile.mechanism_groups:
            result.warnings.append("No explicit mechanism_groups supplied. Derived phrase queries are heuristic; add architectural terms and named comparators for stronger coverage.")
        if client.used >= config.request_budget:
            result.warnings.append("Request limit reached; discovery coverage is partial.")
        if not studies:
            result.warnings.append("No comparable records were found. This is not evidence of a research gap; inspect source status and filters.")
        source_status = {}
        for source in config.sources:
            entries = [e for e in result.search_log if e.get("source") == source]
            successes = sum(e.get("status") == "ok" for e in entries)
            errors = sum(e.get("status") == "error" for e in entries)
            state = "partial" if successes and errors else "failed" if errors else "ok" if successes else "not_requested"
            source_status[source] = {"status": state, "successful_requests": successes, "failed_requests": errors,
                                     "collected_records": raw_counts.get(source, 0)}
        result.coverage = {
            "scope": "bounded_discovery_not_exhaustive", "queries": queries,
            "analysis_mode": config.analysis_mode,
            "query_families": dict(Counter(q["family"] for q in queries)),
            "pdf_processing": {"documents_attempted": len(downloadable), "documents_failed": failed_documents, "attempts": pdf_outcomes},
            "historical_search": profile.year_from is None,
            "raw_records_by_source": raw_counts, "unique_records": len(studies),
            "initial_duplicates_merged": duplicate_count, "excluded_records": len(result.excluded),
            "with_abstract": sum(bool(s.abstract) for s in studies),
            "with_readable_full_text": sum(bool(s.pages_read) for s in studies),
            "metadata_only": sum(not s.pages_read for s in studies),
            "unknown_year": sum(s.year is None for s in studies),
            "unknown_type": sum(s.type == "unknown" for s in studies),
            "full_text_status": dict(Counter(s.full_text_status for s in studies)),
            "source_errors": dict(source_errors), "http_requests": client.used,
            "source_status": source_status,
            "cache_hits": sum(e.get("cached", False) for e in result.search_log),
            "request_budget": config.request_budget, "request_budget_reached": client.used >= config.request_budget,
            "source_record_caps": {s: config.per_source for s in config.sources},
            "citation_rounds_requested": config.citation_rounds, "citation_edges": len(result.citation_edges),
            "ranking_fields": "title + abstract; local PDFs use extracted title only",
            "scoring": {"word_tfidf": .7, "character_tfidf": .3, "calibrated": False},
            "limits": ["Per-source and per-query record limits apply; exhaustive literature coverage is not claimed.",
                       "Automatic translation, semantic models, OCR, and scientific method classification are not applied.",
                       "Proximity scores depend on the candidate set; they cannot be compared across runs as probabilities.",
                       "Records with unknown year, type, or language cannot be conclusively filtered and remain explicitly marked.",
                       "The citation graph contains bounded neighbors of selected OpenAlex records."]}
        client.save_run(result)
        progress(1.0, "Research package ready")
        return result
    finally:
        if own_client:
            client.close()
