from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel, Field, model_validator, ConfigDict


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class ResearchProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=3, max_length=500)
    description: str = Field(min_length=10, max_length=12000)
    concept_groups: list[list[str]] = Field(min_length=1, max_length=8)
    mechanism_groups: list[list[str]] = Field(default_factory=list, max_length=12)
    seed_titles: list[str] = Field(default_factory=list, max_length=20)
    targeted_queries: list[str] = Field(default_factory=list, max_length=20)
    questions: list[str] = Field(default_factory=list)
    population: list[str] = Field(default_factory=list)
    methods: list[str] = Field(default_factory=list)
    geography: list[str] = Field(default_factory=list)
    excluded_terms: list[str] = Field(default_factory=list)
    year_from: int | None = Field(default=None, ge=1500, le=2100)
    year_to: int = Field(default=2026, ge=1500, le=2100)
    types: list[Literal["article", "conference-paper", "preprint", "review", "dissertation", "other"]] = Field(default_factory=lambda: ["article", "conference-paper", "preprint", "review", "dissertation"])
    languages: list[str] = Field(default_factory=list)
    seed_dois: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_profile(self):
        self.title = self.title.strip()
        self.description = self.description.strip()
        self.concept_groups = [[t.strip() for t in g if t.strip()] for g in self.concept_groups]
        if not self.title or not self.description or not all(self.concept_groups):
            raise ValueError("Title, description, and concept groups must not be empty.")
        if any(len(g) > 12 or any(len(t) > 160 for t in g) for g in self.concept_groups):
            raise ValueError("Use at most 12 terms per group and 160 characters per term.")
        self.mechanism_groups = [[t.strip() for t in g if t.strip()] for g in self.mechanism_groups]
        if any(not g or len(g)>12 or any(len(t)>160 for t in g) for g in self.mechanism_groups):
            raise ValueError("Mechanism groups need 1–12 nonempty terms, each at most 160 characters.")
        if self.year_from is not None and self.year_to < self.year_from:
            raise ValueError("year_to must be greater than or equal to year_from.")
        if not self.types:
            raise ValueError("Select at least one publication type.")
        return self

    def query_text(self) -> str:
        # Do not append every synonym: repeated translations distort TF-IDF.
        return " ".join([self.title, self.description, *self.questions, *[g[0] for g in self.concept_groups + self.mechanism_groups]])


class RunConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    analysis_mode: Literal["related_studies", "field_gaps", "topic_branches"] = "related_studies"
    branch_max_matches: int = Field(default=3, ge=1, le=5)
    branch_sibling_limit: int = Field(default=4, ge=0, le=12)
    branch_work_limit: int = Field(default=20, ge=1, le=100)
    local_documents_are_theses: bool = False
    gap_max_candidates: int = Field(default=40, ge=1, le=100)
    gap_per_study: int = Field(default=6, ge=1, le=20)
    gap_follow_up_queries: int = Field(default=3, ge=0, le=10)
    sources: list[Literal["openalex", "crossref", "core", "oai"]] = Field(default_factory=lambda: ["openalex", "crossref"])
    per_source: int = Field(default=150, ge=1, le=2000)
    max_queries: int = Field(default=16, ge=1, le=60)
    request_budget: int = Field(default=60, ge=1, le=500)
    citation_rounds: int = Field(default=1, ge=0, le=2)
    citation_seeds: int = Field(default=3, ge=1, le=10)
    max_downloads: int = Field(default=5, ge=0, le=50)
    max_pdf_mb: int = Field(default=25, ge=1, le=100)
    max_pages: int = Field(default=300, ge=1, le=1500)
    evidence_per_study: int = Field(default=5, ge=1, le=20)
    package_studies: int = Field(default=40, ge=1, le=200)
    compact_studies: int = Field(default=12, ge=1, le=50)
    oai_url: str = ""
    oai_set: str = ""
    use_cache: bool = True


class FileInputs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pdfs: list[str] = Field(default_factory=list, max_length=100)
    records: list[str] = Field(default_factory=list, max_length=100)


class ResearchRequest(BaseModel):
    """Shared web/terminal contract. Credentials are deliberately excluded."""
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["1.0"] = "1.0"
    profile: ResearchProfile
    config: RunConfig = Field(default_factory=RunConfig)
    inputs: FileInputs = Field(default_factory=FileInputs)


class Evidence(BaseModel):
    text: str
    kind: Literal["title", "abstract", "full_text", "citation_context"]
    page: int | None = None
    matched_terms: list[str] = Field(default_factory=list)
    score: float = 0


class Study(BaseModel):
    id: str = ""
    title: str
    abstract: str = ""
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    doi: str = ""
    url: str = ""
    pdf_url: str = ""
    source_ids: dict[str, str] = Field(default_factory=dict)
    sources: list[str] = Field(default_factory=list)
    source_queries: list[str] = Field(default_factory=list)
    type: str = "other"
    language: str = ""
    references: list[str] = Field(default_factory=list)
    cited_by_count: int | None = None
    retrieved_at: str = Field(default_factory=utcnow)
    full_text_status: str = "not_requested"
    full_text_note: str = ""
    full_text_attempts: list[dict] = Field(default_factory=list)
    pdf_urls: list[str] = Field(default_factory=list)
    mechanism_matches: list[list[str]] = Field(default_factory=list)
    pages_read: int = 0
    pages_total: int = 0
    local_filename: str = ""
    file_sha256: str = ""
    score: float = 0
    word_score: float = 0
    character_score: float = 0
    concept_matches: list[list[str]] = Field(default_factory=list)
    dimension_matches: dict[str, list[str]] = Field(default_factory=dict)
    evidence: list[Evidence] = Field(default_factory=list)
    duplicate_candidates: list[str] = Field(default_factory=list)
    # Runtime-only full text. Exported JSON contains the selected evidence instead.
    pages: list[str] = Field(default_factory=list, exclude=True)


class GapEvidence(BaseModel):
    study_id: str
    title: str
    year: int | None = None
    url: str = ""
    doi: str = ""
    kind: Literal["full_text", "abstract"]
    page: int | None = None
    section: str = ""
    quote: str
    cue: str
    start: int
    end: int
    truncated: bool = False
    source_type_basis: str = "provider_metadata"


class GapCandidate(BaseModel):
    id: str
    category: Literal["future_work", "limitation", "open_question"]
    statement: str
    topic_terms: list[str] = Field(default_factory=list)
    evidence: list[GapEvidence] = Field(default_factory=list)
    support_count: int = 1
    status: Literal["author_reported_unverified"] = "author_reported_unverified"
    follow_up_query: str = ""
    verification_status: str = "not_checked"
    related_work_ids: list[str] = Field(default_factory=list)


class RunResult(BaseModel):
    run_id: str
    started_at: str
    completed_at: str = ""
    profile: ResearchProfile
    config: RunConfig
    studies: list[Study] = Field(default_factory=list)
    search_log: list[dict] = Field(default_factory=list)
    coverage: dict = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    citation_edges: list[dict] = Field(default_factory=list)
    excluded: list[dict] = Field(default_factory=list)
    gap_candidates: list[GapCandidate] = Field(default_factory=list)
    gap_analysis: dict = Field(default_factory=dict)
    gap_related_studies: list[Study] = Field(default_factory=list)
    topic_branches: dict = Field(default_factory=dict)
