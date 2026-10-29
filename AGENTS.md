# Contributor and agent conventions

- Keep authored UI, prompts, diagnostics, examples and documentation in English. Preserve original source content.
- Use Times New Roman/serif for ordinary web text and headings, monospace for code and JSON. Keep the near-black theme and compact heading.
- The web and CLI must use the same ResearchRequest schema and processing engine. Preserve profile-only JSON compatibility.
- Keep run stdout machine-readable JSON; terminal presentation belongs on stderr.
- Do not present lexical proximity, sparse matches or portfolio selection as scientific novelty probabilities.
- Keep request limits, source failures, date/type restrictions and evidence levels explicit.
- Do not commit private profiles, benchmark claims, local databases, credentials, source PDFs or generated research packages. Use generic or labeled synthetic test data.
- Run `python -m pytest -q` for relevant behavior changes. Network calls in automated tests must use mocked transports; live verification is a separate opt-in operation.
- Update the generated files in specs/ with `write_specification_files` after changing the shared models or input prompt.
