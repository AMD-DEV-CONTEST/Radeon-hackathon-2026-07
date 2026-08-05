#!/usr/bin/env bash
set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_env.sh"

if [[ $# -lt 1 ]]; then
  echo "usage: $0 PYTHON_SCRIPT [arguments ...]" >&2
  exit 2
fi

run_python "$@"

