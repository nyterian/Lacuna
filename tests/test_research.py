from __future__ import annotations
import hashlib
import io
import json
import zipfile
from pathlib import Path
import httpx
import pytest
from pydantic import ValidationError
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
from lacuna.models import ResearchProfile, RunConfig, Study
from lacuna.query import contains, build_queries
from lacuna.net import WebClient, public_url
from lacuna.sources import parse_oai, load_records, abstract_from_index, search_core, harvest_oai
from lacuna.scoring import deduplicate, rank_studies, make_evidence
from lacuna.documents import read_pdf
from lacuna.pipeline import run_research, expand_citations
from lacuna.export import build_package, csv_bytes


@pytest.fixture
def profile():
    return ResearchProfile(title="Generative AI and critical thinking", description="Research on generative AI and critical thinking in students.",
                           concept_groups=[["generative AI", "\u00fcretken yapay zek\u00e2"], ["critical thinking", "ele\u015ftirel d\u00fc\u015f\u00fcnme"]],
                           population=["students"], methods=["experiment"], year_from=2020, year_to=2026)


def pdf_bytes():
    writer = PdfWriter()
    writer.add_metadata({"/Title": "Generative AI and critical thinking"})
    for text in ("An introduction to generative AI in schools. " * 4,
                 "Students practice critical thinking in an experiment. " * 4):
        page = writer.add_blank_page(width=612, height=792)
        font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
        page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
        stream = DecodedStreamObject()
        stream.set_data(f"BT /F1 12 Tf 30 700 Td ({text}) Tj ET".encode())
        page[NameObject("/Contents")] = writer._add_object(stream)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def test_profile_rejects_empty_and_reverse_dates(profile):
    with pytest.raises(ValidationError):
        ResearchProfile(**{**profile.model_dump(), "year_from": 2026, "year_to": 2020})
    with pytest.raises(ValidationError):
        ResearchProfile(**{**profile.model_dump(), "concept_groups": [[" "]]})


def test_phrase_boundaries_and_turkish():
    assert contains("T\u00dcRK\u0130YE'de ele\u015ftirel d\u00fc\u015f\u00fcnme", "T\u00fcrkiye")
    assert contains("\u00fcretken yapay zek\u00e2", "ure tken") is False
    assert not contains("training", "AI")
    assert contains("Use AI in schools", "AI")


def test_query_dialects_and_synonyms(profile):
    queries = build_queries(profile, 4)
    assert " OR " in queries[0]["boolean"]
    assert " AND " in queries[0]["boolean"]
    assert " OR " not in queries[0]["plain"]
    assert len(queries) <= 4


def test_dedup_doi_but_keep_conflicting_identifiers():
    a = Study(title="A long shared publication title", year=2025, doi="https://doi.org/10.1234/a", sources=["a"])
    b = Study(title="A long shared publication title", year=2025, doi="10.1234/a", sources=["b"], abstract="Evidence")
    c = Study(title="A long shared publication title", year=2025, doi="10.1234/b", sources=["c"])
    merged = deduplicate([a, b, c])
    assert len(merged) == 2
    assert merged[0].sources == ["a", "b"]
    assert merged[0].abstract == "Evidence"
    assert merged[0].duplicate_candidates == [merged[1].id]


def test_fuzzy_titles_flagged_not_deleted():
    studies = deduplicate([Study(title="Critical thinking and student education in schools", year=2024),
                           Study(title="Critical thinking and student education in school", year=2024)])
    assert len(studies) == 2
    assert studies[0].duplicate_candidates


def test_relevant_above_unrelated(profile):
    studies = deduplicate([Study(title="Ocean sediment geology", abstract="Marine sediment composition", type="article"),
                           Study(title=profile.title, abstract=profile.description, type="article")])
    ranked = rank_studies(studies, profile)
    assert ranked[0].title == profile.title
    assert ranked[0].score > ranked[1].score
    assert all(0 <= s.score <= 100 for s in ranked)
    assert sum(bool(g) for g in ranked[0].concept_matches) == 2


def test_pdf_pages_and_evidence(profile):
    pdf = read_pdf(pdf_bytes(), "paper.pdf")
    assert pdf.pages_total == pdf.pages_read == 2
    make_evidence(pdf, profile, 5)
    evidence = [e for e in pdf.evidence if e.page == 2]
    assert evidence and "critical thinking" in evidence[0].text
    assert pdf.full_text_status == "read"
    partial = read_pdf(pdf_bytes(), "paper.pdf", max_pages=1)
    assert partial.full_text_status == "partial"
    assert partial.pages_total == 2


def test_blank_and_invalid_pdf():
    writer = PdfWriter()
    writer.add_blank_page(width=600, height=800)
    body = io.BytesIO()
    writer.write(body)
    assert read_pdf(body.getvalue(), "scan.pdf").full_text_status == "ocr_required"
    with pytest.raises(ValueError):
        read_pdf(b"not a PDF", "bad.pdf")


def test_abstract_index():
    assert abstract_from_index({"world": [1], "Hello": [0]}) == "Hello world"


def test_oai_token_and_thesis():
    body = b'''<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/" xmlns:dc="http://purl.org/dc/elements/1.1/"><ListRecords>
    <record><header><identifier>oai:test:1</identifier></header><metadata><dc:dc><dc:title>A thesis</dc:title><dc:type>doctoralThesis</dc:type><dc:date>2024-05-01</dc:date><dc:identifier>https://example.org/1</dc:identifier></dc:dc></metadata></record>
    <record><header status="deleted"><identifier>gone</identifier></header></record><resumptionToken>next-token</resumptionToken></ListRecords></OAI-PMH>'''
    studies, token = parse_oai(body)
    assert token == "next-token" and len(studies) == 1
    assert studies[0].type == "dissertation" and studies[0].year == 2024


def test_import_turkish_columns():
    rows = [{"tez_ad\u0131": "Imported thesis record for testing", "\u00f6zet": "An abstract", "y\u0131l": "2024", "yazar": "A;B", "t\u00fcr": "tez"}]
    study = load_records("yok.json", json.dumps(rows).encode())[0]
    assert study.type == "dissertation" and study.authors == ["A", "B"]


def test_cache_budget_and_secret_redaction(tmp_path):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"results": []})
    client = WebClient(tmp_path / "db", budget=1, transport=httpx.MockTransport(handler))
    try:
        client.json("https://example.org/works", params={"api_key": "TOPSECRET"}, source="test", label="topic")
        client.json("https://example.org/works", params={"api_key": "TOPSECRET"}, source="test", label="topic")
        assert len(calls) == 1 and client.log[-1]["cached"]
        with pytest.raises(RuntimeError):
            client.json("https://example.org/other", source="test")
        assert "TOPSECRET" not in json.dumps(client.log)
    finally:
        client.close()


def test_private_address_rejected():
    with pytest.raises(ValueError):
        public_url("http://127.0.0.1/private")
    with pytest.raises(ValueError):
        public_url("file:///etc/passwd")


def test_pipeline_partial_failure_and_export(profile, tmp_path):
    def handler(request):
        if request.url.host == "api.crossref.org":
            return httpx.Response(503)
        return httpx.Response(200, json={"meta": {}, "results": [{"id": "https://openalex.org/W1", "display_name": profile.title,
            "publication_year": 2025, "type": "article", "abstract_inverted_index": {"students": [0], "experiment": [1]},
            "doi": "https://doi.org/10.1234/test", "authorships": [], "language": "en"}]})
    client = WebClient(tmp_path / "db", budget=20, transport=httpx.MockTransport(handler))
    try:
        result = run_research(profile, RunConfig(sources=["openalex", "crossref"], max_queries=1, citation_rounds=0, max_downloads=0), client=client)
        assert len(result.studies) == 1
        assert result.coverage["source_errors"]["crossref"] == 1
        archive = zipfile.ZipFile(io.BytesIO(build_package(result)))
        manifest = json.loads(archive.read("manifest.json"))
        assert "ASSISTANT_PROMPT.md" in archive.namelist()
        for name, info in manifest["files"].items():
            assert hashlib.sha256(archive.read(name)).hexdigest() == info["sha256"]
        assert "pages" not in json.loads(archive.read("studies.json"))[0]
        assert archive.testzip() is None
    finally:
        client.close()


def test_offline_roundtrip_and_compact_omissions(profile, tmp_path):
    records = Path(__file__).parents[1] / "examples/synthetic_records.json"
    config = RunConfig(sources=[], max_downloads=0, citation_rounds=0, compact_studies=1)
    result = run_research(profile, config, imports=[(records.name, records.read_bytes())], pdfs=[("paper.pdf", pdf_bytes()), ("bad.pdf", b"oops")], db_path=tmp_path/"db")
    assert len(result.studies) == 4
    assert any("bad.pdf" in w for w in result.warnings)
    archive = zipfile.ZipFile(io.BytesIO(build_package(result, compact=True)))
    assert len(json.loads(archive.read("studies.json"))) == 1
    assert len(json.loads(archive.read("omitted_studies.json"))["ids"]) == 3
    assert result.coverage["http_requests"] == 0


def test_zero_results_not_gap(profile, tmp_path):
    result = run_research(profile, RunConfig(sources=[], citation_rounds=0, max_downloads=0), db_path=tmp_path/"db")
    assert not result.studies
    assert any("not evidence of a research gap" in w for w in result.warnings)
    assert build_package(result)


def test_csv_formula_neutralized():
    body = csv_bytes([{"title": "=HYPERLINK(\"bad\")"}], ["title"]).decode("utf-8-sig")
    assert "'=HYPERLINK" in body


def test_core_authenticated_metadata_and_secret_redaction(profile, tmp_path):
    def handler(request):
        assert request.headers["Authorization"] == "Bearer TEST_SECRET"
        return httpx.Response(200, json={"totalHits": 1, "results": [{"id": 12, "title": "Critical thinking and generative AI",
            "abstract": "A test abstract", "yearPublished": 2024, "authors": [{"name": "Test Author"}], "documentType": ["doctoral thesis"]}]})
    client = WebClient(tmp_path/"db", transport=httpx.MockTransport(handler))
    try:
        studies = search_core(client, profile, RunConfig(max_queries=1), build_queries(profile, 1), "TEST_SECRET")
        assert len(studies) == 1 and studies[0].type == "dissertation"
        assert studies[0].authors == ["Test Author"]
        assert "TEST_SECRET" not in json.dumps(client.log)
    finally:
        client.close()


def test_oai_harvest_continuation_and_bound(tmp_path):
    calls = []
    def handler(request):
        calls.append(dict(request.url.params))
        first = len(calls) == 1
        token = "next" if first else ""
        body = f'''<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/" xmlns:dc="http://purl.org/dc/elements/1.1/"><ListRecords>
        <record><header><identifier>oai:test:{len(calls)}</identifier></header><metadata><dc:dc><dc:title>Study {len(calls)}</dc:title></dc:dc></metadata></record>
        <resumptionToken>{token}</resumptionToken></ListRecords></OAI-PMH>'''
        return httpx.Response(200, text=body)
    client = WebClient(tmp_path/"db", transport=httpx.MockTransport(handler))
    try:
        studies = harvest_oai(client, RunConfig(oai_url="https://example.org/oai", oai_set="theses", per_source=2))
        assert len(studies) == 2
        assert calls[0]["metadataPrefix"] == "oai_dc" and calls[0]["set"] == "theses"
        assert calls[1] == {"verb": "ListRecords", "resumptionToken": "next"}
    finally:
        client.close()


def test_citation_rounds_visit_new_seeds_and_direction(profile, tmp_path):
    requests = []
    def handler(request):
        requests.append(request.url.params["filter"])
        return httpx.Response(200, json={"meta": {}, "results": [{"id": "https://openalex.org/W9", "title": "Neighbor", "type": "article"}]})
    client = WebClient(tmp_path/"db", transport=httpx.MockTransport(handler))
    studies = [Study(title="Seed one", source_ids={"openalex": "https://openalex.org/W1"}), Study(title="Seed two", source_ids={"openalex": "https://openalex.org/W2"})]
    visited, edges = set(), []
    try:
        config = RunConfig(citation_seeds=1)
        expand_citations(client, studies, profile, config, "", edges, visited)
        expand_citations(client, studies, profile, config, "", edges, visited)
        assert requests == ["cited_by:W1", "cites:W1", "cited_by:W2", "cites:W2"]
        assert edges[0]["from"] == "https://openalex.org/W1" and edges[0]["to"] == "https://openalex.org/W9"
        assert edges[1]["from"] == "https://openalex.org/W9" and edges[1]["to"] == "https://openalex.org/W1"
    finally:
        client.close()
