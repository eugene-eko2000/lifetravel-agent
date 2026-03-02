#!/usr/bin/env bash
set -euo pipefail

export PORT="${PORT:-8080}"

python3 -m uvicorn main:app --host 0.0.0.0 --port "${PORT}" --app-dir "$(dirname "$0")/src"
