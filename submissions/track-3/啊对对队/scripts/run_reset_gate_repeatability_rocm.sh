#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG_PATH="${1:-${ROOT_DIR}/configs/catalog_v2.toml}"
CAMPAIGN_PATH="${2:-${ROOT_DIR}/configs/campaign_reset_gate_repeatability_v1.toml}"
OUTPUT_ROOT="${3:-${ROOT_DIR}/outputs/radeon-reset-gate-repeatability-v1}"

export HIP_VISIBLE_DEVICES="${HIP_VISIBLE_DEVICES:-0}"
export PYTHONPATH="${ROOT_DIR}/src${PYTHONPATH:+:${PYTHONPATH}}"

cd "${ROOT_DIR}"
source scripts/activate_radeon_env.sh
bash scripts/preflight_radeon.sh
if [[ -e "${OUTPUT_ROOT}" ]]; then
  echo "ERROR: output root already exists: ${OUTPUT_ROOT}" >&2
  exit 2
fi
mkdir -p "${OUTPUT_ROOT}/runs"
cp "${CAMPAIGN_PATH}" "${OUTPUT_ROOT}/campaign.toml"

python - "${CAMPAIGN_PATH}" "${OUTPUT_ROOT}/schedule.json" <<'PY'
import json
import random
from pathlib import Path
import sys
import tomllib

with open(sys.argv[1], "rb") as handle:
    campaign = tomllib.load(handle)
design = campaign["design"]
conditions = list(design["conditions"])
repeats = int(design["repeats_per_episode_condition"])
seed = int(design["schedule_seed"])
blocks = [
    {
        "repeat_index": repeat_index,
        "episode_id": int(case["episode_id"]),
        "local_episode_id": int(case["local_episode_id"]),
        "profile_id": str(case["profile_id"]),
        "selection_reason": str(case["selection_reason"]),
    }
    for case in campaign["cases"]
    for repeat_index in range(1, repeats + 1)
]
rng = random.Random(seed)
rng.shuffle(blocks)
first_conditions = [conditions[0]] * (len(blocks) // 2)
first_conditions += [conditions[1]] * (len(blocks) - len(first_conditions))
rng.shuffle(first_conditions)
for run_index, (block, first) in enumerate(zip(blocks, first_conditions, strict=True), 1):
    second = conditions[1] if first == conditions[0] else conditions[0]
    block["run_index"] = run_index
    block["condition_order"] = [first, second]
payload = {
    "schema_version": 1,
    "campaign_id": campaign["metadata"]["campaign_id"],
    "schedule_seed": seed,
    "repeats_per_episode_condition": repeats,
    "conditions": conditions,
    "blocks": blocks,
}
Path(sys.argv[2]).write_text(
    json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)
PY

python -u scripts/run_repeatability_batch.py \
  --config "${CONFIG_PATH}" \
  --schedule "${OUTPUT_ROOT}/schedule.json" \
  --runs-root "${OUTPUT_ROOT}/runs" \
  --event-log "${OUTPUT_ROOT}/execution-events.jsonl" \
  --backend rocm

python scripts/analyze_repeatability_campaign.py \
  --schedule "${OUTPUT_ROOT}/schedule.json" \
  --runs-root "${OUTPUT_ROOT}/runs" \
  --output "${OUTPUT_ROOT}/repeatability-analysis.json"
find "${OUTPUT_ROOT}/runs" -type f -path '*/expert/summary.json' -print0 \
  | sort -z | xargs -0 sha256sum > "${OUTPUT_ROOT}/REMOTE-SUMMARY-SHA256SUMS"
sha256sum \
  "${OUTPUT_ROOT}/campaign.toml" \
  "${OUTPUT_ROOT}/schedule.json" \
  "${OUTPUT_ROOT}/execution-events.jsonl" \
  "${OUTPUT_ROOT}/repeatability-analysis.json" \
  "${OUTPUT_ROOT}/REMOTE-SUMMARY-SHA256SUMS" \
  > "${OUTPUT_ROOT}/SHA256SUMS"
echo "Reset-gate repeatability campaign completed: ${OUTPUT_ROOT}"
