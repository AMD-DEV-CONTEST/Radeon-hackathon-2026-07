#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_dir"

python_bin="${ACCIDENT_RIGHTS_PYTHON:-$repo_dir/.venv/bin/python}"
if [[ ! -x "$python_bin" ]]; then
  echo "Python environment not found: $python_bin"
  echo "Create .venv and install requirements.lock first."
  exit 1
fi

exec "$python_bin" -m app.ui.doctor "$@"
