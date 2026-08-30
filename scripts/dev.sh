#!/usr/bin/env sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
python3 -m venv "$ROOT/.venv"
"$ROOT/.venv/bin/pip" install -r "$ROOT/apps/api/requirements.txt"
"$ROOT/.venv/bin/python" -m uvicorn tokenscope_api.main:app --app-dir "$ROOT/apps/api" --host 127.0.0.1 --port 8000 &
cd "$ROOT"
npm install
npm run dev -- --host 127.0.0.1 --port 3000
