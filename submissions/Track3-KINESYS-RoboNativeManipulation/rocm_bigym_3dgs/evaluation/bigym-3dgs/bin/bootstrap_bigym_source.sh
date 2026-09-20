#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/common.sh"

require_command git
clone_pinned "$BIGYM_REPOSITORY" "$BIGYM_COMMIT" "$BIGYM_DIR"

printf 'BIGYM_SOURCE_BOOTSTRAPPED bigym=%s\n' \
  "$(git -C "$BIGYM_DIR" rev-parse HEAD)"
