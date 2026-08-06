#!/usr/bin/env bash
set -euo pipefail
export COMMAND_BACKEND=fake
pytest -m "not rocm and not model_integration" -v
uvicorn backend.main:app --host 127.0.0.1 --port 8000
