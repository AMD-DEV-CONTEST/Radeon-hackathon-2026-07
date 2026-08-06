#!/usr/bin/env bash
# One-shot launch for the Clipster submission on an AMD Radeon (ROCm) instance.
# The platform clones this repo from the GitHub Repo URL in your template; then:
#   bash bootstrap.sh                  # provision everything (idempotent)
#   bash Clipster/scripts/services.sh start
#   bash Clipster/scripts/services.sh tunnel   # public URL for the web UI + API
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
git submodule update --init --recursive
exec Clipster/scripts/provision_radeon.sh "$@"
