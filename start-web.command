#!/bin/bash
set -e
cd "$(dirname "$0")"
bash setup.sh
exec .venv/bin/python -m lacuna web "$@"
