# Release validation — 0.7.0

93 automated tests pass on the development host (Python 3.12). Coverage includes shared request validation, long terminal paste, retrieval and exports, plus thesis-only field-gap extraction, exact quote offsets and physical pages, head/tail sampling, explicit type assertions, abstract provenance, negation and reference filtering, candidate limits, bounded follow-up searches, offline CLI artifacts, and web rendering.

A bounded live topic search retrieved nine thesis records and one readable thesis PDF. That run produced no explicit gap candidates; missing full text and absent cues are reported without inferring field completeness. This verifies retrieval plumbing, not extraction accuracy, comprehensive recall, or current scientific openness. Labeled synthetic fixtures verify positive extraction behavior.

GitHub Actions is configured for macOS, Ubuntu and Windows. Hosted CI results must be checked after publication.

Private research requests, local databases, source PDFs, API credentials and user output packages are excluded from the public repository.

Topic-branch tests cover source hierarchy paths, bounded sample counts, sibling deduplication and relationship direction, alternate placement, incomplete metadata, taxonomy fallback, source failures and budget limits, credential redaction, escaped source labels, JSON roundtrip, both package sizes, shared terminal/SVG labels, stdout/stderr separation, web empty and populated states, and compact SVG rendering.

A live OpenAlex search for “online clustering with prototype memory” sampled 20 publications and produced three candidate placements (the CLI check capped display at two). Paths included Computer Science → Artificial Intelligence → Advanced Clustering Algorithms Research. This validates source integration, not scientific classification accuracy. Desktop and mobile screenshots were inspected, and an independent scoped visual review returned **ship**, with no material findings.

Single-file handoff tests verify embedded quotes/pages and source identity, explicit portfolio omissions, gap and branch findings, Markdown fence isolation, archive parity, chosen folders with spaces, preservation of existing exports, terminal primary/technical layout and web folder saving.

Terminal-workbench tests cover invalid menu choices, saved folder persistence and corrupted preferences, short topic/specification flows, help navigation, cancellation without retrieval, replay request creation and completed-run folder opening. Interactive execution keeps command-subcommand JSON behavior unchanged.
