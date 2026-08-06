#!/usr/bin/env bash
set -euo pipefail

# Run from repo root so paths resolve no matter where the script is called.
cd "$(dirname "$0")/.."

RUFF_SPEC="ruff==0.14.10"

pipx run --spec "$RUFF_SPEC" ruff format .
pipx run --spec "$RUFF_SPEC" ruff check --select I --fix .
