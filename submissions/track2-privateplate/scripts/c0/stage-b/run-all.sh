#!/usr/bin/env bash
# One-shot C0-B collection on a live Radeon GPU Notebook.
# Requires explicit user approval, model profile, and unique run id.
# No default 7B. No auto-fallback. Does not touch existing privateplate-v2 evidence.
# R0-5: executable install, always-stop vLLM, unified failure summary, evidence inventory.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "${ROOT}"
export PRIVATEPLATE_PROFILE_URL="${PRIVATEPLATE_PROFILE_URL:-https://radeon-global.anruicloud.com/}"

if [[ "${PRIVATEPLATE_I_CONFIRM_RADEON_RUN:-}" != "yes" ]]; then
  cat <<'EOF' >&2
Refusing to run C0-B collection without explicit confirmation.

On the GPU instance, re-run with:
  export PRIVATEPLATE_I_CONFIRM_RADEON_RUN=yes
  export PRIVATEPLATE_ACCOUNT_CHANNEL=GLOBAL
  export PRIVATEPLATE_STORAGE_MODE=PERSISTENT_PVC
  export PRIVATEPLATE_MODEL_DIRECTORY=none
  export PRIVATEPLATE_INSTANCE_ID=<instance id>
  export PRIVATEPLATE_IMAGE_DIGEST=sha256:<64 lowercase hex>
  export PRIVATEPLATE_IMAGE_METADATA_RECEIPT=<raw image metadata path>
  export PRIVATEPLATE_MODEL_PROFILE=gemma4-12b-qat-w4a16-ct|gemma4|qwen14
  export PRIVATEPLATE_RUN_ID=privateplate-<profile>-<utc>
  bash scripts/c0/stage-b/run-all.sh
EOF
  exit 1
fi

if [[ -z "${PRIVATEPLATE_MODEL_PROFILE:-}" ]]; then
  echo "PRIVATEPLATE_MODEL_PROFILE is required (gemma4-12b-qat-w4a16-ct|gemma4|qwen14)." >&2
  exit 1
fi

PRIVATEPLATE_COLLECTION_MODE="${PRIVATEPLATE_COLLECTION_MODE:-formal}"
case "${PRIVATEPLATE_COLLECTION_MODE}" in
  formal|agent_diagnostic) ;;
  *)
    echo "PRIVATEPLATE_COLLECTION_MODE must be formal or agent_diagnostic." >&2
    exit 1
    ;;
esac
export PRIVATEPLATE_COLLECTION_MODE

for required_name in \
  PRIVATEPLATE_ACCOUNT_CHANNEL \
  PRIVATEPLATE_STORAGE_MODE \
  PRIVATEPLATE_MODEL_DIRECTORY \
  PRIVATEPLATE_INSTANCE_ID \
  PRIVATEPLATE_IMAGE_DIGEST \
  PRIVATEPLATE_IMAGE_METADATA_RECEIPT; do
  if [[ -z "${!required_name:-}" ]]; then
    echo "${required_name} is required before a formal Radeon run." >&2
    exit 1
  fi
done
if [[ "${PRIVATEPLATE_ACCOUNT_CHANNEL}" != "GLOBAL" ]]; then
  echo "New formal runs require PRIVATEPLATE_ACCOUNT_CHANNEL=GLOBAL." >&2
  exit 1
fi
case "${PRIVATEPLATE_STORAGE_MODE}" in
  PERSISTENT_PVC|EPHEMERAL) ;;
  *)
    echo "PRIVATEPLATE_STORAGE_MODE must be PERSISTENT_PVC or EPHEMERAL." >&2
    exit 1
    ;;
esac
if [[ "${PRIVATEPLATE_MODEL_DIRECTORY}" != "none" ]]; then
  echo "PRIVATEPLATE_MODEL_DIRECTORY must be none." >&2
  exit 1
fi
if [[ ! "${PRIVATEPLATE_IMAGE_DIGEST}" =~ ^sha256:[0-9a-f]{64}$ ]]; then
  echo "PRIVATEPLATE_IMAGE_DIGEST must be sha256:<64 lowercase hex characters>." >&2
  exit 1
fi
for receipt_path in "${PRIVATEPLATE_IMAGE_METADATA_RECEIPT}"; do
  if [[ ! -s "${receipt_path}" ]]; then
    echo "Required pre-start receipt is missing or empty: ${receipt_path}" >&2
    exit 1
  fi
done

if [[ -z "${PRIVATEPLATE_RUN_ID:-}" ]]; then
  stamp="$(date -u +"%Y%m%dT%H%M%SZ")"
  export PRIVATEPLATE_RUN_ID="privateplate-${PRIVATEPLATE_MODEL_PROFILE}-${stamp}"
  echo "PRIVATEPLATE_RUN_ID defaulted to ${PRIVATEPLATE_RUN_ID}"
fi

# Never write into the frozen successful Qwen2.5-7B evidence tree.
if [[ "${PRIVATEPLATE_RUN_ID}" == "privateplate-v2" || "${PRIVATEPLATE_RUN_ID}" == "privateplate-v2.attempt1-arg-fail" ]]; then
  echo "Refusing to use protected evidence directory name: ${PRIVATEPLATE_RUN_ID}" >&2
  exit 1
fi

OUT_DIR="${ROOT}/benchmarks/c0/stage-b/${PRIVATEPLATE_RUN_ID}"
export PRIVATEPLATE_C0B_OUT_DIR="${OUT_DIR}"

if [[ -d "${OUT_DIR}" ]] &&
  [[ -n "$(find "${OUT_DIR}" -mindepth 1 -print -quit)" ]]; then
  cat <<EOF >&2
Refusing to mix C0-B collection rounds.

The evidence directory already contains files:
  ${OUT_DIR}

Move the whole directory aside and start from a fresh source checkout or archive.
EOF
  exit 1
fi

mkdir -p "${OUT_DIR}/raw"
run_log_active=0
run_log_pid=""
exec 3>&1 4>&2
exec > >(tee "${OUT_DIR}/raw/run-all.log") 2>&1
run_log_pid=$!
run_log_active=1

export PRIVATEPLATE_SESSION_STARTED_AT="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
export PRIVATEPLATE_VLLM_PORT="${PRIVATEPLATE_VLLM_PORT:-8000}"
export PRIVATEPLATE_VLLM_BASE_URL="${PRIVATEPLATE_VLLM_BASE_URL:-http://127.0.0.1:${PRIVATEPLATE_VLLM_PORT}/v1}"
export PRIVATEPLATE_VLLM_READY_TIMEOUT_SEC="${PRIVATEPLATE_VLLM_READY_TIMEOUT_SEC:-3600}"
# Explicitly clear legacy fallback env so nothing silently reintroduces 7B.
unset PRIVATEPLATE_FALLBACK_MODEL || true

# Prefer the ROCm image venv for torch/vLLM.
if [[ -f /opt/venv/bin/activate ]]; then
  # shellcheck disable=SC1091
  source /opt/venv/bin/activate
fi
export PATH="/opt/venv/bin:${PATH}"

export PRIVATEPLATE_TOOL_STEP_STATUS="${PRIVATEPLATE_TOOL_STEP_STATUS:-}"
export PRIVATEPLATE_PRODUCT_AGENT_STEP_STATUS="${PRIVATEPLATE_PRODUCT_AGENT_STEP_STATUS:-}"
export PRIVATEPLATE_PUBLIC_GOLDEN_STEP_STATUS="${PRIVATEPLATE_PUBLIC_GOLDEN_STEP_STATUS:-}"
export PRIVATEPLATE_BASELINE_STEP_STATUS="${PRIVATEPLATE_BASELINE_STEP_STATUS:-}"
export PRIVATEPLATE_SESSION_STEP_STATUS="${PRIVATEPLATE_SESSION_STEP_STATUS:-}"
export PRIVATEPLATE_ARTIFACT_STEP_STATUS="${PRIVATEPLATE_ARTIFACT_STEP_STATUS:-}"
export PRIVATEPLATE_OVERALL_EXIT=1
export PRIVATEPLATE_FAILURE_REASON="${PRIVATEPLATE_FAILURE_REASON:-}"

overall_status=1
cleanup_done=0

close_run_log() {
  if ((run_log_active == 0)); then
    return 0
  fi
  exec 1>&3 2>&4
  if ! wait "${run_log_pid}"; then
    echo "run-all.log writer did not close cleanly." >&2
  fi
  exec 3>&- 4>&-
  run_log_active=0
}

finalize_run() {
  local exit_code="${1:-1}"
  if ((cleanup_done == 1)); then
    return 0
  fi
  cleanup_done=1

  echo "== C0-B teardown: stop vLLM (success and failure paths) =="
  set +e
  bash scripts/c0/stage-b/00-stop-vllm.sh
  local stop_status=$?
  set -e
  if ((stop_status != 0)); then
    echo "vLLM stop returned ${stop_status} (recorded in raw/vllm-stop.json if possible)." >&2
  fi

  export PRIVATEPLATE_OVERALL_EXIT="${exit_code}"
  echo "== C0-B teardown: unified failure/completion summary =="
  set +e
  node scripts/c0/stage-b/write-failure-summary.mjs
  set -e

  cat <<EOF

C0-B automated collection finished for run ${PRIVATEPLATE_RUN_ID}.
overall_exit=${exit_code} (non-zero means FAIL closed)
failure_reason=${PRIVATEPLATE_FAILURE_REASON:-none}
EOF

  # Stop writing the transcript before hashing it. Any transport-side log
  # belongs outside the evidence directory so the sealed inventory stays exact.
  close_run_log

  echo "== C0-B teardown: evidence inventory (SHA-256) =="
  set +e
  node scripts/c0/stage-b/write-evidence-inventory.mjs
  set -e

  cat <<EOF

Next (owner only):
1. Copy ${OUT_DIR}/ back to the local repo
2. Review collection-summary.json and raw/failure-summary.json
3. Only EVIDENCE_COMPLETE means the evidence package is complete
4. Keep any scp/ssh wrapper log beside the run directory, not inside it
5. Historical benchmarks/c0/stage-b/privateplate-v2/ remains protected legacy evidence only
EOF
}

on_exit() {
  local code=$?
  # If finalize already ran with an explicit status, do not re-enter.
  if ((cleanup_done == 1)); then
    return 0
  fi
  if [[ -z "${PRIVATEPLATE_FAILURE_REASON:-}" && "${code}" -ne 0 ]]; then
    export PRIVATEPLATE_FAILURE_REASON="run_all_exit_${code}"
  fi
  finalize_run "${code}"
}
trap on_exit EXIT

finish_and_exit() {
  local code="${1:-1}"
  finalize_run "${code}"
  trap - EXIT
  exit "${code}"
}

echo "== C0-B step 0.05: ensure Node >=22.13 BEFORE any node scripts =="
bash scripts/c0/stage-b/00-install-node22.sh
export PATH="${NVM_DIR:-$HOME/.nvm}/versions/node/$(node -v 2>/dev/null || true)/bin:/opt/node22/bin:${PATH}"
# shellcheck disable=SC1091
if [[ -s "${NVM_DIR:-$HOME/.nvm}/nvm.sh" ]]; then
  . "${NVM_DIR:-$HOME/.nvm}/nvm.sh"
  nvm use default >/dev/null 2>&1 || true
fi
echo "== C0-B step 0.1: verify Global account profile =="
node scripts/c0/stage-b/00-verify-account.mjs

echo "== C0-B step 0: collect environment =="
bash scripts/c0/stage-b/00-collect-env.sh

echo "== C0-B step 0.25: verify evidence preflight =="
node scripts/c0/stage-b/00-verify-preflight.mjs

echo "== C0-B step 0.3: verify pinned local model artifacts =="
node scripts/c0/stage-b/validate-model-profile.mjs >/dev/null

echo "== C0-B step 0.35: executable runtime install (fail closed before model download) =="
bash scripts/c0/stage-b/00-install-runtime.sh

echo "== C0-B step 0.4: verify pinned runtime before model download/start =="
node scripts/c0/stage-b/00-verify-runtime.mjs
if [[ ! -f "${OUT_DIR}/raw/runtime-pin-verification.json" ]]; then
  export PRIVATEPLATE_FAILURE_REASON="runtime_pin_verification_missing"
  echo "Runtime pin verification produced no result file; stopping before model download." >&2
  overall_status=2
  finish_and_exit "${overall_status}"
fi
node -e '
  const v = JSON.parse(require("node:fs").readFileSync(process.argv[1], "utf8"));
  if (v.status !== "PASS") process.exit(2);
' "${OUT_DIR}/raw/runtime-pin-verification.json" || {
  export PRIVATEPLATE_FAILURE_REASON="runtime_pin_verification_failed"
  echo "Runtime pin verification FAILED; stopping before model download." >&2
  overall_status=2
  finish_and_exit "${overall_status}"
}
echo "== C0-B step 0.5: build the product provider =="
bash scripts/c0/stage-b/00-prepare-product-provider.sh

echo "== C0-B step 1: start vLLM (profile=${PRIVATEPLATE_MODEL_PROFILE}) =="
if ! bash scripts/c0/stage-b/01-start-vllm.sh; then
  export PRIVATEPLATE_FAILURE_REASON="vllm_start_failed"
  echo "vLLM start FAILED; no fallback. Recording evidence and stopping." >&2
  overall_status=2
  finish_and_exit "${overall_status}"
fi
if [[ -f "${OUT_DIR}/raw/active-model.txt" ]]; then
  export PRIVATEPLATE_MODEL_ACTIVE="$(cat "${OUT_DIR}/raw/active-model.txt")"
fi
echo "== C0-B step 1.5: verify active model + every declared model file =="
artifact_step_status=0
set +e
node scripts/c0/stage-b/06-verify-model-artifacts.mjs
artifact_step_status=$?
set -e
export PRIVATEPLATE_ARTIFACT_STEP_STATUS="${artifact_step_status}"
if [[ ! -f "${OUT_DIR}/raw/model-artifact-verification.json" ]]; then
  export PRIVATEPLATE_FAILURE_REASON="model_artifact_verification_missing"
  echo "Model artifact verification produced no result file; stopping." >&2
  overall_status=2
  finish_and_exit "${overall_status}"
fi
if ((artifact_step_status != 0)); then
  export PRIVATEPLATE_FAILURE_REASON="model_artifact_verification_failed"
  echo "Model artifact verification FAILED; stopping before baselines/tools to avoid false PASS." >&2
  export PRIVATEPLATE_TOOL_STEP_STATUS=2
  export PRIVATEPLATE_BASELINE_STEP_STATUS=2
  export PRIVATEPLATE_SESSION_STEP_STATUS=1
  set +e
  node scripts/c0/stage-b/05-write-collection-summary.mjs
  set -e
  overall_status=2
  finish_and_exit "${overall_status}"
fi
echo "== C0-B step 2: baseline latency/throughput =="
baseline_step_status=0
set +e
node scripts/c0/stage-b/03-measure-baseline.mjs
baseline_step_status=$?
set -e
export PRIVATEPLATE_BASELINE_STEP_STATUS="${baseline_step_status}"
if [[ ! -f "${OUT_DIR}/baseline-results.json" ]]; then
  export PRIVATEPLATE_FAILURE_REASON="baseline_results_missing"
  echo "Baseline collection produced no result file; stopping to avoid mixed evidence." >&2
  overall_status=2
  finish_and_exit "${overall_status}"
fi
if ((baseline_step_status != 0)); then
  export PRIVATEPLATE_FAILURE_REASON="baseline_failed"
  echo "Baseline collection returned ${baseline_step_status}; stopping (fail closed)." >&2
  export PRIVATEPLATE_TOOL_STEP_STATUS=2
  export PRIVATEPLATE_SESSION_STEP_STATUS=1
  set +e
  node scripts/c0/stage-b/05-write-collection-summary.mjs
  set -e
  overall_status=2
  finish_and_exit "${overall_status}"
fi
# Historical five-tool / Public Golden collectors retired from this submission.
# Current nine-tool product evidence uses layered-product-diag + sealed diagnostic trees.
echo "== C0-B: skipping retired five-tool / Public Golden collectors =="
tool_step_status=0
product_agent_status=0
public_golden_status=0
export PRIVATEPLATE_TOOL_STEP_STATUS="${tool_step_status}"
export PRIVATEPLATE_PRODUCT_AGENT_STEP_STATUS="${product_agent_status}"
export PRIVATEPLATE_PUBLIC_GOLDEN_STEP_STATUS="${public_golden_status}"

echo "== C0-B step 4: session metadata =="
session_step_status=0
set +e
node scripts/c0/stage-b/04-write-session.mjs
session_step_status=$?
set -e
export PRIVATEPLATE_SESSION_STEP_STATUS="${session_step_status}"
if [[ ! -f "${OUT_DIR}/cloud-session.json" ]]; then
  export PRIVATEPLATE_FAILURE_REASON="session_metadata_missing"
  echo "Session collection produced no result file; stopping to avoid mixed evidence." >&2
  overall_status=2
  finish_and_exit "${overall_status}"
fi
if ((session_step_status != 0)); then
  echo "Session metadata returned ${session_step_status}." >&2
fi
echo "== C0-B step 5: collection summary =="
summary_step_status=0
set +e
node scripts/c0/stage-b/05-write-collection-summary.mjs
summary_step_status=$?
set -e

overall_status=0
if ((baseline_step_status != 0 || session_step_status != 0 || artifact_step_status != 0 || summary_step_status != 0)); then
  overall_status=2
  export PRIVATEPLATE_FAILURE_REASON="${PRIVATEPLATE_FAILURE_REASON:-gate_or_step_failed}"
fi

finish_and_exit "${overall_status}"