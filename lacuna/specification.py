from __future__ import annotations

import json
from pathlib import Path
from .models import ResearchRequest, ResearchProfile, RunConfig


def request_template() -> dict:
    profile = {
        "title": "", "description": "", "concept_groups": [[""]],
        "mechanism_groups": [], "seed_titles": [], "targeted_queries": [],
        "questions": [], "population": [], "methods": [], "geography": [],
        "excluded_terms": [], "year_from": None, "year_to": 2026,
        "types": ["article", "conference-paper", "preprint", "review", "dissertation"], "languages": [], "seed_dois": [],
    }
    return {"schema_version": "1.0", "profile": profile, "config": RunConfig().model_dump(),
            "inputs": {"pdfs": [], "records": []}}


def example_request() -> dict:
    request = request_template()
    request["profile"].update({
        "title": "Generative AI and critical thinking in students",
        "description": "Compare empirical studies on how generative AI tools relate to students' critical thinking skills in educational settings.",
        "concept_groups": [["generative AI", "generative artificial intelligence", "large language model"], ["critical thinking", "critical reasoning"]],
        "questions": ["How does generative AI use relate to students' critical thinking?"],
        "population": ["students", "high school students"], "methods": ["experiment", "longitudinal"],
        "geography": [], "year_from": None,
        "mechanism_groups": [["AI literacy", "metacognition"]],
    })
    return request


def parse_request(text: str) -> ResearchRequest:
    text = text.strip().lstrip("\ufeff")
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3 and lines[-1].strip() == "```":
            text = "\n".join(lines[1:-1])
    if len(text.encode()) > 1_000_000:
        raise ValueError("Request JSON exceeds the 1 MB limit.")
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("Request JSON must be an object.")
    # Continue to accept the original standalone profile format.
    if "profile" not in data:
        return ResearchRequest(profile=ResearchProfile.model_validate(data))
    return ResearchRequest.model_validate(data)


def input_prompt() -> str:
    return """# Prepare a research request

Help me prepare an input specification for Field specific lacuna identifier.
Ask whether I want related-study comparison, thesis-based field-gap discovery, or topic branching.
For topic branching, set config.analysis_mode to "topic_branches", config.sources
to ["openalex"], and leave inputs empty. Use my topic as the title and a concept
group with a factual scope description. This mode returns source-backed taxonomy
paths and suggested placements, not a definitive classification.
For field gaps, set config.analysis_mode to "field_gaps" and profile.types to
["dissertation"]. A topic is sufficient: use it as the title and a concept group,
with a factual scope description. Add synonyms if supplied. Never invent gaps.
The program extracts author-reported limitations and future work; it does not
establish that those gaps remain open today. local_documents_are_theses may be
true only when I explicitly identify my uploaded/local PDFs as theses.
Ask me for missing research details before producing the final JSON. Required:
research title, scope, and at least one concept group. Ask about questions,
population, methods, geography, exclusions, date range, document types, languages,
known seed DOIs, and whether I have local PDF/CSV/JSON files.

Return one JSON object only, using the exact structure below. No shell commands,
Markdown fences, comments, extra fields, invented DOIs, or credentials. Write all
explanations and entered research text in English unless I explicitly supply
search terms in another language. Keep field names unchanged.

Each concept_groups entry is a list of synonyms for ONE concept; different groups
are distinct concepts. Supply useful spelling variants and abbreviations. Do not
claim automatic semantic translation. Leave unknown optional lists empty. Use
explicit keyword groups rather than turning the entire research description
into one keyword. The title must have at least 3 characters and description 10.

Valid publication types: article, conference-paper, preprint, review, dissertation, other.
Keep conference papers and preprints for architectural novelty discovery.
Default year_from is null: no lower year bound, so foundational work is retained.
Use mechanism_groups for architectural components and update rules, separately
from broad topic keywords. Extract explicitly described components and update
rules from my supplied description into mechanism_groups; do not leave them
only in prose. Retain any baselines I explicitly name as comparator seeds.
Ask for named prior methods or paper titles and put
them in seed_titles; never invent comparators. targeted_queries can contain
explicit Boolean searches. These families share the configured query budget. Valid sources: openalex,
crossref, core, oai. CORE needs a separately configured API key. OAI requires a
public oai_url and harvests a bounded repository sample, not a topic search.
For offline use, set config.sources to [], citation_rounds and max_downloads to 0,
and populate inputs with actual user-provided local files. Do not invent paths.
Keep default numeric limits unless I request a change. Dates must be ordered.
Do not place API keys in JSON. File paths are CLI-only; web users upload files.

I will paste your JSON into the terminal or web JSON editor. Template:

""" + json.dumps(request_template(), indent=2, ensure_ascii=False) + "\n"


def write_specification_files(directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "request.template.json").write_text(json.dumps(request_template(), indent=2) + "\n", encoding="utf-8")
    (directory / "request.example.json").write_text(json.dumps(example_request(), indent=2) + "\n", encoding="utf-8")
    (directory / "request.schema.json").write_text(json.dumps(ResearchRequest.model_json_schema(), indent=2) + "\n", encoding="utf-8")
    (directory / "INPUT_PROMPT.md").write_text(input_prompt(), encoding="utf-8")


def field_gap_request(topic: str, concept_groups=None, sources=None) -> ResearchRequest:
    topic = topic.strip()
    profile = ResearchProfile(title=topic, description=f"Find author-reported limitations, future work, and open questions in theses about {topic}.",
                              concept_groups=concept_groups or [[topic]], targeted_queries=[topic], types=["dissertation"])
    config = RunConfig(analysis_mode="field_gaps", sources=["openalex", "crossref"] if sources is None else sources,
                       citation_rounds=0)
    return ResearchRequest(profile=profile, config=config)
