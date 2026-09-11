#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="${ROOT_DIR}/src"
export PYTHONDONTWRITEBYTECODE=1

cd "${ROOT_DIR}"
python3 -m unittest discover -s tests -v
python3 -m parcel_sorter --config configs/baseline.toml
