#!/bin/bash
set -e
cd "$(dirname "$0")"
trap 'status=$?; if [ "$status" -ne 0 ]; then echo "Lacuna could not start. Read the error above. Press Enter to close."; read -r; fi' EXIT
bash start-terminal.command "$@"
