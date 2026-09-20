#!/usr/bin/env bash
# Backward-compatible entry point. The submitted project uses the domestic-
# market verification path only.
set -euo pipefail
exec "$(cd "$(dirname "$0")" && pwd)/verify_submission.sh" "$@"
