#!/usr/bin/env bash
# Helper snippets for a formal C0-B run. No Qwen2.5-7B defaults. No auto-fallback.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage (on the Radeon instance, repo root):

  export PRIVATEPLATE_I_CONFIRM_RADEON_RUN=yes
  export PRIVATEPLATE_ACCOUNT_CHANNEL=GLOBAL
  export PRIVATEPLATE_STORAGE_MODE=PERSISTENT_PVC
  export PRIVATEPLATE_MODEL_DIRECTORY=none
  export PRIVATEPLATE_INSTANCE_ID="REPLACE_WITH_INSTANCE_ID"
  export PRIVATEPLATE_IMAGE_DIGEST="sha256:REPLACE_WITH_64_LOWERCASE_HEX"
  export PRIVATEPLATE_IMAGE_METADATA_RECEIPT=/root/receipts/image-metadata.json
  export PRIVATEPLATE_MODEL_PROFILE=gemma4-12b-qat-w4a16-ct   # or qwen14
  export PRIVATEPLATE_RUN_ID=privateplate-gemma4-$(date -u +%Y%m%dT%H%M%SZ)
  export PATH=/opt/node22/bin:/opt/venv/bin:$PATH
  bash scripts/c0/stage-b/run-all.sh

Notes:
  - New formal runs use the Global account profile; China evidence remains historical and unchanged.
  - Do not write into privateplate-v2 (protected legacy Qwen7 evidence).
  - Every declared model file is always size- and SHA-256-verified.
  - run-all.sh always stops vLLM, records raw/run-all.log, writes every failed step to raw/failure-summary.json, then seals raw/evidence-inventory.json.
  - Copy the run directory unchanged. Keep SSH/scp wrapper logs beside it, not inside it.
  - The current Global instance is owner-confirmed free; Destroy/credit receipts are optional metadata.
  - Local offline checks: node scripts/c0/stage-b/verify-install-plan.mjs
  - This helper is not permission to start an instance; each run needs fresh owner approval.
  - Radeon status remains NOT_RUN until the owner explicitly approves a live session.
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" || "${1:-}" == "" ]]; then
  usage
  exit 0
fi

usage
