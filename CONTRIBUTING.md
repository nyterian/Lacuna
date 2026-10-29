# Contributing

Use Python 3.10+ and a virtual environment, then install an editable checkout:

```sh
python -m pip install -e '.[dev]'
python -m pytest -q
python -m lacuna --help
```

Core code lives in lacuna/. app.py is the local Streamlit entry point. specs/ contains generated input contracts and prompts; tests/ contains fixtures and mocked source integrations. See FLOW.md for the processing contract.

Prefer regression tests for source taxonomy, retrieval limits, evidence provenance, terminal input, and portable export changes. Keep CI independent of external academic APIs and credentials. Report algorithmic accuracy separately from software correctness.

Before opening a pull request, inspect changed files for private research data, absolute local paths and credentials. Include the problem, changed behavior, test results and remaining limits in the description.
