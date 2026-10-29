# Field specific lacuna identifier

A local, code-oriented research workbench with matching terminal and web interfaces. Define a research specification, retrieve bounded literature records, compare textual proximity, inspect evidence, and export a portable package for your own AI assistant.

The application makes no LLM calls. It does not download a generative model. Proximity is a heuristic ranking score, not a novelty probability. All authored UI, diagnostics, documentation, and prompts are in English. Original research terms and source text are preserved.

## Install

Python 3.10+ is required; Python 3.12 is the validated environment.

```bash
git clone https://github.com/nyterian/Lacuna.git
cd Lacuna
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

On Windows, activate with `.venv\Scripts\activate` instead. Editable installation registers `lacuna` while keeping the source checkout available for the web entry point. You can also run every command as `python -m lacuna` from the project directory without installing the command alias.

Launchers install missing dependencies into a project-local `.venv`:

| Platform | Terminal | Local web |
|---|---|---|
| macOS | `start-terminal.command` | `start-web.command` |
| Windows | `start-terminal.bat` | `start-web.bat` |
| Linux | `bash setup.sh`, then `.venv/bin/python -m lacuna` | `.venv/bin/python -m lacuna web` |

First-time setup needs network access to the Python package registry. Launchers honor `LACUNA_PYTHON` on macOS/Linux if a specific interpreter is needed.

## Terminal workflow

```bash
lacuna
```

The interactive menu provides:

1. Paste an assistant-prepared request JSON.
2. Enter the specification field by field.
3. Print the preparation prompt, then wait for the assistant's completed JSON.
4. Run a saved request file.
5. Start the local web interface.
6. Find author-reported field-gap candidates in theses.
7. Map a specific topic to its research branches.

Input is parsed as JSON, never executed as shell code. The interactive paste editor uses raw terminal input and bracketed paste, bypassing the operating system's per-line input buffer. Paste the entire JSON, then press Enter to submit. Enter adds a line while JSON is incomplete. Ctrl+D submits for validation; Ctrl+C cancels and restores the terminal. Markdown JSON fences are tolerated. Piped input retains its line-based automatic acceptance behavior. The request still has a 1 MB total size limit and schema field limits.

### Ask your assistant to prepare the input

```bash
lacuna init --dir specs
lacuna template --prompt
```

Send `specs/INPUT_PROMPT.md` to your assistant with your research requirements. It asks for missing details and returns the shared request JSON. Then either:

```bash
lacuna paste --out request.json
lacuna run request.json
```

or paste and execute in one step:

```bash
lacuna paste --run
```

Manual entry:

```bash
lacuna wizard --out request.json
lacuna wizard --run
```

### Files and pipes

```bash
lacuna template --example > request.json
lacuna validate request.json
lacuna run request.json --out data/packages
cat request.json | lacuna run - --quiet > result-summary.json
```

`run` writes a JSON summary to stdout. Rich terminal presentation and progress use stderr. `--quiet` suppresses progress entirely. Validation errors are JSON with exit code 2; cancellation uses exit code 130. A completed run can have partial-source warnings: inspect `status`, `warnings`, and `coverage.source_status`.

Each run writes one primary attachment into the chosen save folder. Optional files are grouped separately:

```text
<save-folder>/
  lacuna_<id>.assistant.md        # send this ONE file to your assistant
  technical/<id>/
    lacuna_<id>.json              # full structured run result
    lacuna_<id>.request.json      # replayable request
    lacuna_<id>.zip               # optional full archive
    lacuna_<id>_compact.zip       # optional compact archive
```

Choose the folder at the terminal prompt, or pass `--out "~/Downloads/Lacuna"` to `run`, `gaps` or `branches`. User-home notation is expanded. The JSON summary identifies the primary attachment as `artifacts.assistant_document` and reports its absolute path.

Paths in a loaded request are resolved relative to the request file. Paths supplied with `--pdf` or `--records`, interactive entry, or stdin are resolved relative to the working directory. The standalone replay request contains absolute local input paths; ZIP exports intentionally omit those paths and original PDFs.

### Offline inputs

```bash
lacuna run specs/request.example.json --offline --pdf paper.pdf --records studies.csv
```

For a software-only smoke test with explicitly synthetic records:

```bash
lacuna run examples/profile.json --offline --records examples/synthetic_records.json --quiet
```

Synthetic fixtures are not real publications or evidence of research accuracy. `--config examples/config.json` can override retrieval limits. The original standalone profile JSON format remains accepted.

## Local web

```bash
lacuna web
lacuna web --port 8502
```

Default URL: http://127.0.0.1:8501. The server binds to localhost.

The near-black interface exposes actual schema field names and six work areas:

- **Specification:** form or JSON editor, request validation, template/schema/input-prompt downloads, local uploads, and explicit limits.
- **Results:** score-first table, filters, evidence excerpts, source identity, dimensions, coverage, and request logs.
- **Field gaps:** attributed thesis limitations and future-work candidates.
- **Topic branches:** taxonomy placement and neighboring topics.
- **Artifacts:** single-file assistant brief, local save folder, download/copy preview, and optional technical exports.
- **Runs:** local SQLite history with package regeneration.

The form's **Build request JSON** action creates a terminal-compatible request. The JSON editor accepts pasted assistant output or an uploaded request file. File paths in `inputs` are CLI-only; web users upload the files and leave those lists empty.

## Shared request contract

`specs/request.schema.json` is generated from the Pydantic models used by both interfaces. Unknown fields are rejected. Credentials are deliberately absent.

```json
{
  "schema_version": "1.0",
  "profile": {
    "title": "Research title",
    "description": "Research scope, constructs, and context.",
    "concept_groups": [["first concept", "synonym"], ["second concept"]],
    "mechanism_groups": [["architectural mechanism", "synonym"]],
    "seed_titles": [],
    "targeted_queries": [],
    "questions": [],
    "population": [],
    "methods": [],
    "geography": [],
    "excluded_terms": [],
    "year_from": null,
    "year_to": 2026,
    "types": ["article", "conference-paper", "preprint", "review", "dissertation"],
    "languages": [],
    "seed_dois": []
  },
  "config": {
    "sources": ["openalex", "crossref"],
    "per_source": 150,
    "max_queries": 16,
    "request_budget": 60,
    "citation_rounds": 1,
    "max_downloads": 5
  },
  "inputs": {"pdfs": [], "records": []}
}
```

Missing optional config keys use the schema defaults. Required research inputs are title, description, and nonempty concept groups. Each concept group contains synonyms of one concept. Different groups represent distinct concepts. Population, method, and geography terms are comparison dimensions, not mandatory source filters. Dates, types, language, and exclusions control filtering where metadata exists; unknown metadata is retained and counted.

An unfilled `request.template.json` intentionally fails validation until the required fields are completed. The example is ready to validate. See [specs/INPUT_PROMPT.md](specs/INPUT_PROMPT.md).

## Sources and credentials

| Source | Implementation | Scope |
|---|---|---|
| OpenAlex | Boolean retrieval, filters, seed DOI lookup, bounded incoming/outgoing citation expansion | Service quotas and metadata coverage apply |
| Crossref | Bibliographic relevance search, date/type filters | Abstract and dissertation availability varies |
| CORE | Optional authenticated v3 metadata search | `CORE_API_KEY` required |
| OAI-PMH | `oai_dc`, set, and resumption-token harvesting | Bounded repository sample; not keyword search |
| Local PDF | Physical-page text extraction and relevant excerpts | No OCR; unreadable/encrypted files are reported |
| Local CSV/JSON | Standard record imports | User supplies actual source records |
| YOK | Local record/PDF imports | No automatic bulk YOK crawler |

Set `OPENALEX_API_KEY` and/or `CORE_API_KEY` in the environment, or enter them in the web Runtime panel. They are not serialized to request JSON, logs, or ZIPs. Network retrieval is subject to each provider's access conditions and budgets.

## Record import

Use UTF-8 CSV or a JSON array with `title`, `abstract`, `year`, `authors`, `doi`, `type`, `url`, `language`, and optional `pdf_url`. Only `title` is required. CSV author names are separated with `;`. Use `article`, `dissertation`, `other`, or `unknown` for type. Existing non-English field aliases remain supported for backward-compatible data import; application-generated labels remain English.

DOIs, source IDs, and file hashes identify exact duplicates. Exact long titles with matching years may merge when known DOIs do not conflict. Fuzzy title matches are flagged for manual review rather than silently deleted.

## Ranking and evidence

```text
proximity = 100 × (0.70 × word TF-IDF cosine + 0.30 × character TF-IDF cosine)
```

Ranking uses title plus available abstract. Local PDFs use extracted titles; full text supplies evidence excerpts and dimension matches. Missing abstracts can affect ranking. The model is lexical, not semantic: supply alternate terminology explicitly. Scores depend on the candidate corpus and are not calibrated across runs.

A matching method phrase does not prove method use. A missing phrase does not prove that a topic has never been studied. Sparse concept combinations are search observations, not established lacunae. Expert-labeled retrieval/novelty accuracy has not been evaluated.

## Portable package

ZIPs contain `request.json`, `research_profile.json`, `report.md`, `studies.csv`, `studies.json`, `comparison_matrix.csv`, selected `evidence/` files, `references.bib`, `search_log.json`, `coverage.json`, `warnings.json`, `citations.json`, `excluded_records.json`, `omitted_studies.json`, and a hashed `manifest.json`.

Two English prompts serve different jobs:

- **INPUT_PROMPT.md:** have your assistant prepare the research request.
- **ASSISTANT_PROMPT.md:** have your assistant interpret the output and assess possible lacunae with counterevidence.

Upload only `lacuna_<id>.assistant.md` to your assistant, or paste its contents. The interpretation prompt, research profile, coverage, sources and supplied evidence are embedded in this single document. ZIPs also include `SEND_TO_ASSISTANT.md`; the other archive files are optional technical exports. The compact package includes a balanced evidence portfolio of N records; catalogue.csv lists every discovered record and selection.json explains the choices; its coverage file still describes the full run. All full-package records retain selected evidence in `studies.json`; only the configured evidence portfolio gets separate Markdown files. Page numbers are physical PDF page positions.

## Local data and constraints

`data/research.sqlite` contains the 24-hour metadata cache and saved run history. Request budgets, bounded retries, size/page limits, public-URL checks, CSV formula neutralization, and escaped source excerpts are implemented. Source failures preserve useful records and are reported explicitly.

This is a personal local application, not an authenticated public service. Research profiles, excerpts, and local filenames may appear in exports. Third-party records and documents retain their own license/access terms. Code is MIT licensed.

## Validation and development

```bash
python -m pytest -q
python -m compileall -q lacuna app.py
```

Tests cover core retrieval plumbing, ranking, deduplication, PDF evidence, provider failures, cache/budgets, package integrity, strict shared JSON validation, terminal paste/wizard/pipe workflows, replayable input paths, and web form/JSON modes. See [FLOW.md](FLOW.md) and [VALIDATION.md](VALIDATION.md).

## Version 0.3 discovery improvements

- `profile.mechanism_groups` searches architectural components separately from broad topic groups. `seed_titles` retrieves named prior methods/papers; `targeted_queries` accepts explicit Boolean searches. Query slots are interleaved across families. Without explicit mechanisms, deterministic title/description phrase suggestions are labeled as heuristic.
- `year_from: null` is the historical default. Explicit lower bounds are respected and produce an omitted-history warning. Conference papers, reviews and preprints are included by default; provider types are normalized before local filtering.
- Compact evidence is selected across proximity, comparator searches, mechanisms, historical topic matches, publication types, and readable full text. It is a selection heuristic, not a validated recall guarantee. `catalogue.csv` preserves all discovered metadata, even for omitted compact records.
- Up to three available OA PDF locations per selected document are tried. Retrieval failures, parsing failures, unreadable text, and successful reading are distinct; all attempts are exported. The crypto extra supports AES-encrypted PDFs where the document permits access. Password protection is not bypassed.
- Existing explicit research profiles retain their year/type limits. Review warnings and update them if broader historical or conference coverage is intended.

## Thesis-based field-gap discovery (0.4)

Use this mode when you have a field/topic rather than an existing proposed architecture:

```bash
lacuna gaps "online clustering"
lacuna gaps "online clustering" --concept "stream clustering | online clustering" --pdf my-thesis.pdf
lacuna gaps "online clustering" --offline --records theses.csv --quiet
```

Terminal menu option **6** collects a topic and optional thesis file paths. In the web interface, open **Field gaps**, enter a topic, and optionally add keyword groups or upload thesis PDFs/records. The full JSON contract also accepts `config.analysis_mode: "field_gaps"`; see `specs/field-gaps.example.json`. Existing related-study mode remains the default.

This mode enforces a thesis-only publication filter. Provider/imported thesis metadata identifies records. Unknown-type local PDFs require the web checkbox **I identify the uploaded PDFs as theses**; the CLI `gaps --pdf` option explicitly identifies a supplied thesis. This user assertion is recorded separately from provider metadata. Original source text may be in another language; authored controls and output labels stay English.

The extraction engine looks for explicit limitation, future-work, and unresolved-question cues in accessible full text or abstracts. It does not invent missing topics from low publication counts. Each candidate records the original quote, source title/ID/year/URL/DOI, evidence kind, section when identified, exact character offsets, and physical PDF page when available. Abstract-only evidence never receives a page number. Bibliographies, table-of-contents entries, and common negated cues are excluded. Matching remains heuristic; review context in the original thesis.

For long theses exceeding the page budget, gap mode reads a head/tail sample rather than only the beginning. Unread middle pages remain explicitly unexamined, and physical page positions are preserved. OCR-required pages are not analyzed.

A bounded follow-up pass searches for same-or-later-year related works for the first few candidates, using the shared request budget. Matches are possible counterevidence for review, not proof that a gap has closed. No match is proof only of the bounded search result, never proof that the gap remains open. Offline use, unsupported sources, failed requests, and unchecked candidates are distinguished. OAI-PMH harvesting is still bounded repository sampling.

Outputs add `field_gaps.md`, `field_gaps.json`, `field_gaps.csv`, `gap_analysis.json`, and `gap_related_studies.json` to both ZIP packages. The CLI also writes standalone gap Markdown/JSON files and includes candidate statements in its JSON summary. Source-reported candidates are always marked `author_reported_unverified`.

Limits can be controlled through `gap_max_candidates`, `gap_per_study`, and `gap_follow_up_queries`; CLI equivalents are `--max-candidates`, `--per-thesis`, and `--follow-up-queries`. Default follow-up provider is OpenAlex, then Crossref when selected. Full-text access and publication metadata bound what can be reported. Zero extracted statements does not mean a field is complete.

Software-only synthetic demo (not scientific evidence):

```bash
lacuna gaps "online clustering" --offline --records examples/synthetic_theses.json --quiet
```

## Topic branching (0.5.0)

Enter a specific research topic to see its suggested place within **domain → field → subfield → topic → your input**, alongside neighboring topics in that subfield. The same tree is available in the web **Topic branches** tab and terminal menu option **7**.

```sh
python -m lacuna branches "online clustering with prototype memory"
python -m lacuna branches "graph neural networks for drug discovery" --matches 3 --neighbors 4 --sample 20
python -m lacuna run specs/topic-branches.example.json
```

Both interfaces use `config.analysis_mode="topic_branches"` and the shared request schema. OpenAlex is required; no local model or new dependency is needed. `OPENALEX_API_KEY` remains optional in configuration, but the provider may require one or restrict unauthenticated access. This mode does not consume PDF/record inputs, thesis-only filters, publication date filters or citation expansion settings.

The engine searches a bounded sample of publications and groups their primary topics. Placements are ordered by the number of sampled publications supporting them; ties preserve search order. Up to five supporting publications are retained per placement. If publication metadata provides no topics, a direct taxonomy search supplies explicitly labeled fallback candidates. Each topic's parents and siblings are fetched from [OpenAlex Topics](https://help.openalex.org/data/topics/). Neighbor display is bounded and ordered by lexical label similarity; it is not semantic distance.

Solid diagram edges are source taxonomy relationships. The dashed input edge is a suggested placement, not a definitive scientific classification. Topics may have multiple plausible placements. Sample counts are not confidence probabilities. Missing levels, failed requests and empty searches stay explicit; no hierarchy is invented.

CLI trees are printed to stderr and JSON remains on stdout. `--quiet` suppresses presentation. Exported ZIPs and standalone CLI artifacts include `topic_branches.json`, `.md`, `.svg` and `.txt`. JSON and Markdown retain all candidate placements and source evidence; SVG and text default to the first placement. The web selector switches the displayed placement and its SVG download. The portable package includes a matching assistant interpretation prompt.

## Single-file assistant handoff and save folders (0.6.0)

The Artifacts tab defaults to a concise self-contained Markdown brief. Choose Extended brief for a larger detailed evidence portfolio. Both retain all field-gap candidates or topic placements, source references and coverage limitations. The source catalogue lists all discovered records; unselected study abstracts and excerpts are explicitly excluded from the brief. Original PDFs are never embedded. No extra model is required.

Use **Save folder → Save to folder** to write the single brief to a folder on the computer running the local web app. Enter an absolute path or `~/Downloads/Lacuna`; missing folders are created, and repeated saves receive a suffix instead of overwriting earlier exports. Browser downloads follow browser save settings independently. The complete brief is also available in the copyable preview.

Attachment/context limits vary between assistants. The interface shows document size; concise mode reduces the detailed study portfolio but does not silently truncate gap evidence. Long field-gap/source catalogues can still exceed an assistant's context. Technical JSON and ZIP downloads remain optional under their expander.
