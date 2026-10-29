# Changelog

## 0.6.0

- Make a self-contained assistant Markdown brief the primary export, with embedded instructions, provenance, evidence and coverage.
- Add web save-folder selection, copy preview, concise/extended briefs and non-overwriting saves.
- Keep terminal technical exports in a separate subfolder; retain machine-readable artifact paths and optional ZIPs.

## 0.5.0

- Add source-backed topic branching with alternative taxonomy placements and neighboring topics.
- Add a web Topic branches tab, terminal menu option 7, and `branches` command.
- Share one tree between web SVG and terminal rendering; export JSON, Markdown, SVG and text with publication evidence and retrieval limits.
- Keep search-based placement separate from provider taxonomy edges and handle incomplete/failed access explicitly.

## 0.4.0

- Added thesis-based field-gap mode with a topic-only web form, terminal menu entry, and `lacuna gaps` command.
- Extracted attributed future-work, limitation, and open-question passages with exact offsets and physical PDF page evidence.
- Distinguished abstracts, partial full text, provider thesis metadata, and user-identified thesis PDFs.
- Sampled thesis head/tail pages within the configured page budget to preserve end-of-thesis sections.
- Added bounded follow-up retrieval for possible later counterevidence, with no automatic open/closed verdict.
- Exported gap reports, JSON/CSV evidence, coverage, and related-work records.

## 0.3.0

- Added architectural mechanism groups, named comparator seeds, explicit targeted queries, and labeled deterministic phrase suggestions.
- Interleaved query families within request limits.
- Removed the default lower year bound; retained explicit user filters with coverage warnings.
- Normalized conference/preprint publication types and included conference papers, preprints and reviews in new profiles.
- Replaced score-only compact selection with an explained evidence portfolio and an all-record metadata catalogue.
- Added PDF location fallback and separate retrieval/parsing diagnostics.
- Added PDF font-decoding and encryption dependencies and regression tests for alternate locations and source failures.
- Kept raw-mode long terminal paste support and the shared English web/CLI schema.
- Added public-repository hygiene and cross-platform CI configuration.
