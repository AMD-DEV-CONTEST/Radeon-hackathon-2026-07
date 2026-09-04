#!/usr/bin/env bash
set -Eeuo pipefail

readonly REQUIRED_PYTHON="$(<.python-version)"
[[ "$(python -c 'import platform; print(platform.python_version())')" == "$REQUIRED_PYTHON" ]] || {
  echo "Python $REQUIRED_PYTHON is required" >&2
  exit 2
}
TEMP_ROOT=$(mktemp -d)
trap 'rm -rf "$TEMP_ROOT"' EXIT
python -m venv "$TEMP_ROOT/venv"
"$TEMP_ROOT/venv/bin/python" -m pip install \
  --disable-pip-version-check --no-input --only-binary=:all: --require-hashes \
  -r requirements/lock-bootstrap.txt
CUSTOM_COMPILE_COMMAND='scripts/update_ci_lock.sh' \
  "$TEMP_ROOT/venv/bin/pip-compile" \
  --allow-unsafe \
  --generate-hashes \
  --resolver=backtracking \
  --strip-extras \
  --output-file=requirements/ci.txt \
  requirements/ci.in
if [[ "${1:-}" == '--check' ]]; then
  git diff --exit-code -- requirements/ci.txt
elif [[ $# -ne 0 ]]; then
  echo 'usage: scripts/update_ci_lock.sh [--check]' >&2
  exit 2
fi
