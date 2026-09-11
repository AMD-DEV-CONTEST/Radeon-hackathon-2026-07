#!/usr/bin/env bash
# Internal worker: keep PI0.5 resident while one sequential campaign executes.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CHECKPOINT="${1:?usage: $0 CHECKPOINT OUTPUT DESIGN}"
OUTPUT="${2:?usage: $0 CHECKPOINT OUTPUT DESIGN}"
DESIGN="${3:?usage: $0 CHECKPOINT OUTPUT DESIGN}"
PROTOCOL="${PI05_CHUNK_PROTOCOL:-first-action-hold-v1}"
STEPS="${PI05_CHUNK_STEPS:-1}"
STAGE_STEPS="${PI05_STAGE_CHUNK_STEPS:-}"
SERVICE_ROOT="${OUTPUT}/policy-service"
SOCKET="${SERVICE_ROOT}/pi05.sock"
READY="${SERVICE_ROOT}/ready.json"
SERVER_LOG="${SERVICE_ROOT}/server.log"

if [[ ! -f "${CHECKPOINT}/config.json" || ! -f "${DESIGN}" ]]; then
  echo "ERROR: checkpoint or design is missing" >&2
  exit 2
fi
if [[ -e "${OUTPUT}/rollouts" || -e "${OUTPUT}/campaign-audit.json" ]]; then
  echo "ERROR: persistent campaign output is not new" >&2
  exit 3
fi
mkdir -p "${SERVICE_ROOT}"

server_command=(
  python "${ROOT_DIR}/scripts/serve_mobile_pi05_policy_rocm.py"
  --checkpoint "${CHECKPOINT}"
  --socket "${SOCKET}"
  --ready "${READY}"
  --chunk-execution-protocol "${PROTOCOL}"
  --chunk-execution-steps "${STEPS}"
)
if [[ -n "${STAGE_STEPS}" ]]; then
  server_command+=(--stage-chunk-execution-steps "${STAGE_STEPS}")
fi
"${server_command[@]}" >"${SERVER_LOG}" 2>&1 &
server_pid=$!

cleanup() {
  if kill -0 "${server_pid}" 2>/dev/null; then
    if [[ -f "${READY}" ]]; then
      python "${ROOT_DIR}/scripts/stop_mobile_pi05_policy_service.py" \
        --ready "${READY}" >/dev/null 2>&1 || kill "${server_pid}" 2>/dev/null || true
    else
      kill "${server_pid}" 2>/dev/null || true
    fi
    wait "${server_pid}" 2>/dev/null || true
  fi
}
trap cleanup EXIT

for _ in $(seq 1 600); do
  [[ -f "${READY}" ]] && break
  if ! kill -0 "${server_pid}" 2>/dev/null; then
    echo "ERROR: persistent policy service exited before readiness" >&2
    tail -100 "${SERVER_LOG}" >&2 || true
    exit 4
  fi
  sleep 1
done
if [[ ! -f "${READY}" ]]; then
  echo "ERROR: persistent policy service did not become ready in 600 seconds" >&2
  exit 5
fi

collect_command=(
  python "${ROOT_DIR}/scripts/collect_mobile_suction_dataset_rocm.py"
  --config "${DESIGN}"
  --output "${OUTPUT}/rollouts"
  --backend rocm
  --audit-only
  --smolvla-checkpoint "${CHECKPOINT}"
  --vla-policy-service-ready "${READY}"
  --policy-mode pi05_absolute
  --policy-hz 3
  --pi05-chunk-execution-protocol "${PROTOCOL}"
  --pi05-chunk-execution-steps "${STEPS}"
  --require-vla-goal-verdict
  --require-vla-grasp-mode
  --workers 1
)
if [[ -n "${STAGE_STEPS}" ]]; then
  collect_command+=(--pi05-stage-chunk-execution-steps "${STAGE_STEPS}")
fi
"${collect_command[@]}"

python "${ROOT_DIR}/scripts/summarize_mobile_vla_campaign.py" \
  --collection-summary "${OUTPUT}/rollouts/collection-summary.json" \
  --output "${OUTPUT}/campaign-audit.json"

python "${ROOT_DIR}/scripts/stop_mobile_pi05_policy_service.py" --ready "${READY}"
wait "${server_pid}"
trap - EXIT
