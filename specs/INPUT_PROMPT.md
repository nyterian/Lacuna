# Prepare a research request

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

{
  "schema_version": "1.0",
  "profile": {
    "title": "",
    "description": "",
    "concept_groups": [
      [
        ""
      ]
    ],
    "mechanism_groups": [],
    "seed_titles": [],
    "targeted_queries": [],
    "questions": [],
    "population": [],
    "methods": [],
    "geography": [],
    "excluded_terms": [],
    "year_from": null,
    "year_to": 2026,
    "types": [
      "article",
      "conference-paper",
      "preprint",
      "review",
      "dissertation"
    ],
    "languages": [],
    "seed_dois": []
  },
  "config": {
    "analysis_mode": "related_studies",
    "branch_max_matches": 3,
    "branch_sibling_limit": 4,
    "branch_work_limit": 20,
    "local_documents_are_theses": false,
    "gap_max_candidates": 40,
    "gap_per_study": 6,
    "gap_follow_up_queries": 3,
    "sources": [
      "openalex",
      "crossref"
    ],
    "per_source": 150,
    "max_queries": 16,
    "request_budget": 60,
    "citation_rounds": 1,
    "citation_seeds": 3,
    "max_downloads": 5,
    "max_pdf_mb": 25,
    "max_pages": 300,
    "evidence_per_study": 5,
    "package_studies": 40,
    "compact_studies": 12,
    "oai_url": "",
    "oai_set": "",
    "use_cache": true
  },
  "inputs": {
    "pdfs": [],
    "records": []
  }
}
