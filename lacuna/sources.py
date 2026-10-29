from __future__ import annotations
import csv
import hashlib
import io
import json
import re
from html import unescape
from defusedxml import ElementTree as ET
from .models import Study, ResearchProfile, RunConfig
from .query import normalize_doi, contains


def clean_html(text) -> str:
    return unescape(re.sub(r"<[^>]+>", " ", str(text or ""))).strip()


def abstract_from_index(index: dict | None) -> str:
    if not index:
        return ""
    positions = [(p, word) for word, ps in index.items() for p in ps if isinstance(p, int) and 0 <= p < 100000]
    return " ".join(word for _, word in sorted(positions))


def canonical_type(value: str) -> str:
    aliases = {"journal-article":"article", "proceedings-article":"conference-paper", "conference-paper":"conference-paper", "posted-content":"preprint", "preprint":"preprint", "review":"review", "dissertation":"dissertation", "article":"article", "unknown":"unknown"}
    return aliases.get(value, "other")


def from_openalex(item: dict, query="") -> Study:
    locations = [item.get("best_oa_location"), item.get("primary_location"), *(item.get("locations") or [])]
    pdf = next((loc.get("pdf_url") for loc in locations if loc and loc.get("is_oa") and loc.get("pdf_url")), "")
    title = item.get("display_name") or item.get("title") or "Untitled record"
    return Study(title=title, abstract=abstract_from_index(item.get("abstract_inverted_index")),
                 authors=[a.get("author", {}).get("display_name", "") for a in item.get("authorships", [])],
                 year=item.get("publication_year"), doi=normalize_doi(item.get("doi") or ""),
                 url=(item.get("primary_location") or {}).get("landing_page_url") or item.get("id", ""),
                 pdf_url=pdf, pdf_urls=list(dict.fromkeys(loc["pdf_url"] for loc in locations if loc and loc.get("is_oa") and loc.get("pdf_url"))), source_ids={"openalex": item.get("id", "")}, sources=["openalex"],
                 source_queries=[query] if query else [], type=canonical_type(item.get("type", "unknown")),
                 language=item.get("language") or "", references=item.get("referenced_works") or [],
                 cited_by_count=item.get("cited_by_count"))


def from_crossref(item: dict, query="") -> Study:
    date = item.get("published", item.get("issued", {})).get("date-parts", [[]])
    year = date[0][0] if date and date[0] else None
    return Study(title=clean_html((item.get("title") or ["Untitled record"])[0]),
                 abstract=clean_html(item.get("abstract", "")), year=year,
                 authors=[" ".join(filter(None, [a.get("given"), a.get("family")])) or a.get("name", "") for a in item.get("author", [])],
                 doi=normalize_doi(item.get("DOI", "")), url=item.get("URL", ""),
                 source_ids={"crossref": item.get("DOI", "")}, sources=["crossref"],
                 source_queries=[query] if query else [], type=canonical_type(item.get("type", "unknown")),
                 language=item.get("language", ""), cited_by_count=item.get("is-referenced-by-count"))


def search_openalex(client, profile: ResearchProfile, config: RunConfig, queries, key="") -> list[Study]:
    collected = []
    seen = set()
    filters = [f"to_publication_date:{profile.year_to}-12-31"]
    if profile.year_from is not None:
        filters.append(f"from_publication_date:{profile.year_from}-01-01")
    # Type vocabularies evolve; normalize and filter locally to retain conference papers.
    if profile.types == ["dissertation"]:
        filters.append("type:dissertation")
    if profile.languages:
        filters.append("language:" + "|".join(profile.languages))
    # Fair allocation keeps broad query one from consuming the whole source cap.
    quota = max(1, config.per_source // max(1, len(queries)))
    for query in queries:
        cursor, count = "*", 0
        while count < quota and len(collected) < config.per_source:
            params = {"search": query["boolean"], "filter": ",".join(filters), "per_page": min(100, quota-count), "cursor": cursor}
            if key:
                params["api_key"] = key
            try:
                data = client.json("https://api.openalex.org/works", params=params, source="openalex", label=query["boolean"])
            except RuntimeError:
                break
            items = data.get("results", [])
            client.log[-1].update(returned_records=len(items), total_available=data.get("meta", {}).get("count"),
                                  query_record_limit=quota, page_record_limit=params["per_page"])
            for item in items:
                if item.get("id") not in seen:
                    collected.append(from_openalex(item, query["boolean"]))
                    seen.add(item.get("id"))
            count += len(items)
            cursor = data.get("meta", {}).get("next_cursor")
            if not items or not cursor:
                break
    return collected


def search_crossref(client, profile, config, queries) -> list[Study]:
    collected, seen = [], set()
    quota = max(1, config.per_source // max(1, len(queries)))
    for query in queries:
        cursor, count = "*", 0
        while count < quota and len(collected) < config.per_source:
            filters = f"until-pub-date:{profile.year_to}-12-31"
            if profile.year_from is not None:
                filters += f",from-pub-date:{profile.year_from}-01-01"
            if profile.types == ["dissertation"]:
                filters += ",type:dissertation"
            elif profile.types == ["article"]:
                filters += ",type:journal-article"
            elif profile.types == ["conference-paper"]:
                filters += ",type:proceedings-article"
            try:
                data = client.json("https://api.crossref.org/works", params={"query.bibliographic": query["plain"],
                                   "filter": filters, "rows": min(100, quota-count), "cursor": cursor},
                                   source="crossref", label=query["plain"])
            except RuntimeError:
                break
            message = data.get("message", {})
            items = message.get("items", [])
            client.log[-1].update(returned_records=len(items), total_available=message.get("total-results"), query_record_limit=quota)
            for item in items:
                if item.get("DOI") not in seen:
                    collected.append(from_crossref(item, query["plain"]))
                    seen.add(item.get("DOI"))
            count += len(items)
            next_cursor = message.get("next-cursor")
            if not items or not next_cursor or next_cursor == cursor:
                break
            cursor = next_cursor
    return collected


def search_core(client, profile, config, queries, key) -> list[Study]:
    collected, seen = [], set()
    if not key:
        return []
    quota = max(1, config.per_source // max(1, len(queries)))
    for q in queries:
        offset = 0
        while offset < quota and len(collected) < config.per_source:
            try:
                data = client.json("https://api.core.ac.uk/v3/search/works", params={"q": q["boolean"], "limit": min(100, quota-offset), "offset": offset},
                                   headers={"Authorization": f"Bearer {key}"}, source="core", label=q["boolean"])
            except RuntimeError:
                break
            items = data.get("results", [])
            client.log[-1].update(returned_records=len(items), total_available=data.get("totalHits"), query_record_limit=quota)
            for it in items:
                if it.get("id") in seen:
                    continue
                seen.add(it.get("id"))
                types = " ".join(str(t) for t in it.get("documentType", []) if t) if isinstance(it.get("documentType"), list) else str(it.get("documentType", ""))
                dtype = "dissertation" if re.search("thesis|dissertation", types, re.I) else "article" if re.search("article", types, re.I) else "unknown"
                collected.append(Study(title=it.get("title") or "Untitled record", abstract=it.get("abstract") or "",
                    authors=[a.get("name", "") if isinstance(a, dict) else str(a) for a in it.get("authors", [])],
                    year=int(it["yearPublished"]) if str(it.get("yearPublished", "")).isdigit() else None,
                    doi=normalize_doi(it.get("doi") or ""), url=next(iter(it.get("sourceFulltextUrls") or []), ""),
                    sources=["core"], source_ids={"core": str(it.get("id", ""))}, source_queries=[q["boolean"]], type=dtype))
            offset += len(items)
            if len(items) < min(100, quota):
                break
    return collected


def parse_oai(content: bytes) -> tuple[list[Study], str]:
    root = ET.fromstring(content)
    ns = {"o": "http://www.openarchives.org/OAI/2.0/", "dc": "http://purl.org/dc/elements/1.1/"}
    err = root.find("o:error", ns)
    if err is not None:
        if err.attrib.get("code") == "noRecordsMatch":
            return [], ""
        raise ValueError("OAI-PMH: " + (err.attrib.get("code") or "provider error"))
    studies = []
    for record in root.findall(".//o:record", ns):
        header = record.find("o:header", ns)
        if header is None or header.attrib.get("status") == "deleted":
            continue
        metadata = record.find("o:metadata", ns)
        if metadata is None:
            continue
        def texts(field):
            return [" ".join(el.itertext()).strip() for el in metadata.findall(".//dc:" + field, ns) if " ".join(el.itertext()).strip()]
        titles = texts("title")
        if not titles:
            continue
        identifiers = texts("identifier")
        url = next((u for u in identifiers if u.startswith(("https://", "http://"))), "")
        doi = next((d for d in map(normalize_doi, identifiers) if d), "")
        yearmatch = re.search(r"\b(1[5-9]\d{2}|20\d{2})\b", " ".join(texts("date")))
        dtype = " ".join(texts("type"))
        kind = "dissertation" if re.search(r"thesis|dissertation|doctoral|master|tez", dtype, re.I) else "article" if re.search("article", dtype, re.I) else "unknown"
        studies.append(Study(title=" / ".join(titles), abstract="\n".join(texts("description")), authors=texts("creator"),
            year=int(yearmatch.group()) if yearmatch else None, doi=doi, url=url, sources=["oai"],
            source_ids={"oai": header.findtext("o:identifier", default="", namespaces=ns)}, type=kind,
            language=next(iter(texts("language")), "")))
    return studies, root.findtext(".//o:resumptionToken", default="", namespaces=ns) or ""


def harvest_oai(client, config) -> list[Study]:
    collected, token, seen_tokens = [], "", set()
    while len(collected) < config.per_source:
        params = {"verb": "ListRecords", "resumptionToken": token} if token else {"verb": "ListRecords", "metadataPrefix": "oai_dc"}
        if not token and config.oai_set:
            params["set"] = config.oai_set
        try:
            body = client.request(config.oai_url, params=params, source="oai", label="ListRecords; " + ("continuation page" if token else "oai_dc"))
            studies, token = parse_oai(body)
            client.log[-1].update(returned_records=len(studies), has_next_page=bool(token))
            collected.extend(studies[:config.per_source-len(collected)])
        except (RuntimeError, ValueError) as exc:
            client.log.append({"source": "oai", "status": "error", "error": str(exc)})
            break
        if not token or token in seen_tokens:
            break
        seen_tokens.add(token)
    return collected


def load_records(filename: str, body: bytes) -> list[Study]:
    """Portable JSON/CSV imports, including manually exported YOK records."""
    text = body.decode("utf-8-sig")
    if filename.lower().endswith(".csv"):
        reader = csv.DictReader(io.StringIO(text))
        records = list(reader)
    else:
        data = json.loads(text)
        records = data.get("studies", data.get("results", [])) if isinstance(data, dict) else data
    if not isinstance(records, list):
        raise ValueError("Record input must be a JSON array or CSV table.")
    if len(records) > 10000:
        raise ValueError("A single file may contain at most 10,000 records.")
    out = []
    for index, record in enumerate(records):
        # Accept a few explicit Turkish names, rather than silently guessing schema.
        title = record.get("title") or record.get("ba\u015fl\u0131k") or record.get("tez_ad\u0131")
        if not title:
            raise ValueError(f"Record {index+1} is missing its title field.")
        if record.get("source_ids") and isinstance(record.get("source_ids"), dict):
            study = Study.model_validate(record)
            study.sources = list(dict.fromkeys(study.sources + ["import"]))
            study.pages = []
            # Previous run scores/evidence are not trusted as new evidence.
            study.evidence, study.score = [], 0
            study.full_text_attempts = []
            study.pages_read, study.pages_total = 0, 0
            study.full_text_status = "not_requested"
            study.full_text_note = "Imported metadata; the source PDF was not re-read in this run."
        else:
            year = record.get("year") or record.get("y\u0131l")
            authors = record.get("authors") or record.get("yazar") or []
            if isinstance(authors, str):
                authors = [a.strip() for a in authors.split(";") if a.strip()]
            dtype = record.get("type") or record.get("t\u00fcr") or "unknown"
            if re.search("thesis|tez|dissertation|doktora|y\u00fcksek lisans", dtype, re.I):
                dtype = "dissertation"
            study = Study(title=str(title), abstract=clean_html(record.get("abstract") or record.get("\u00f6zet") or ""),
                authors=authors, year=int(year) if year and str(year).isdigit() else None,
                doi=normalize_doi(record.get("doi") or ""), url=record.get("url") or "", pdf_url=record.get("pdf_url") or "",
                type=dtype, language=record.get("language") or "", sources=["import"],
                source_ids={"import": hashlib.sha256(f"{filename}:{index}:{title}".encode()).hexdigest()[:16]})
        out.append(study)
    return out
