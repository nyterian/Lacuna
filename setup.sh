#!/bin/bash
set -e
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  runtime=""
  for candidate in "${LACUNA_PYTHON:-}" python3.12 python3.11 python3.10 python3 "$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"; do
    if [ -n "$candidate" ] && "$candidate" -c 'import sys;sys.exit(0 if sys.version_info >= (3,10) else 1)' 2>/dev/null; then
      runtime="$candidate"
      break
    fi
  done
  if [ -z "$runtime" ]; then
    echo "Python 3.10+ is required: https://www.python.org/downloads/"
    exit 1
  fi
  "$runtime" -m venv .venv
fi
if ! .venv/bin/python -c 'import streamlit,httpx,pydantic,pandas,sklearn,rapidfuzz,pypdf,defusedxml,rich,prompt_toolkit,cryptography,fontTools' 2>/dev/null; then
  .venv/bin/python -m pip install -r requirements.txt
fi
