#!/usr/bin/env bash
# One command: generate synthetic data, run all lenses + fusion + harness (fresh ledger), launch the app.
set -euo pipefail
cd "$(dirname "$0")"
PY="${PYTHON:-.venv/bin/python}"
[ -x "$PY" ] || PY=python3
"$PY" -m data.gen.synth
"$PY" -m core.pipeline --reset-ledger
exec "$PY" -m streamlit run ui/app.py
