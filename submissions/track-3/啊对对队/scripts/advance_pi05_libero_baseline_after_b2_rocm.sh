#!/usr/bin/env bash
# Wait for B2's complete parcel pipeline, then run staged official PI0.5 LIBERO evaluation.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
B2_AUTO_PID="${1:?usage: $0 B2_AUTO_PID}"
CHECKPOINT="/root/pi05-assets/pi05-libero-finetuned-local"
MANIFEST="${ROOT_DIR}/configs/pi05_libero_public_benchmark_v2.json"
PREFLIGHT="${ROOT_DIR}/outputs/pi05-libero-preflight-egl-v4.json"
WIRING_ONE="${ROOT_DIR}/outputs/pi05-libero-baseline-wiring-1-v2"
WIRING_THREE="${ROOT_DIR}/outputs/pi05-libero-baseline-wiring-3-v2"
CONFIRMATION="${ROOT_DIR}/outputs/pi05-libero-baseline-confirmation-400-v2"
STATUS="${ROOT_DIR}/outputs/pi05-libero-baseline-after-b2-status-v2.json"

if [[ ! "${B2_AUTO_PID}" =~ ^[1-9][0-9]*$ ]]; then
  echo "ERROR: B2_AUTO_PID must be a positive integer" >&2
  exit 2
fi
for path in "${PREFLIGHT}" "${WIRING_ONE}" "${WIRING_THREE}" "${CONFIRMATION}" "${STATUS}"; do
  if [[ -e "${path}" ]]; then
    echo "ERROR: staged LIBERO output already exists: ${path}" >&2
    exit 3
  fi
done

while kill -0 "${B2_AUTO_PID}" 2>/dev/null; do
  sleep 60
done

export PYTHONPATH="/workspace/libero-overlay:/workspace/parcel-sorter-rocm/third_party/lerobot/src:${ROOT_DIR}/src${PYTHONPATH:+:${PYTHONPATH}}"
export MUJOCO_GL=egl
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export TOKENIZERS_PARALLELISM=false
export WANDB_DISABLED=true

/workspace/rdna/bin/python "${ROOT_DIR}/scripts/prepare_pi05_libero_assets_overlay.py"
timeout 600s /workspace/rdna/bin/python "${ROOT_DIR}/scripts/preflight_pi05_libero_rocm.py" \
  --suite libero_spatial --task-id 0 --init-state-id 10 --seed 20260728 \
  --output "${PREFLIGHT}"

timeout 7200s /workspace/rdna/bin/python "${ROOT_DIR}/scripts/run_pi05_libero_eval_rocm.py" \
  --checkpoint "${CHECKPOINT}" --manifest "${MANIFEST}" --output "${WIRING_ONE}" \
  --phase wiring --episodes 1 --wiring-suite libero_spatial --wiring-task-id 0 \
  --compile false
/workspace/rdna/bin/python "${ROOT_DIR}/scripts/gate_pi05_libero_wiring.py" \
  --run-root "${WIRING_ONE}" --expected-episodes 1 --minimum-successes 0 \
  --output "${WIRING_ONE}/WIRING_GATE.json"

timeout 7200s /workspace/rdna/bin/python "${ROOT_DIR}/scripts/run_pi05_libero_eval_rocm.py" \
  --checkpoint "${CHECKPOINT}" --manifest "${MANIFEST}" --output "${WIRING_THREE}" \
  --phase wiring --episodes 3 --wiring-suite libero_spatial --wiring-task-id 0 \
  --compile false
/workspace/rdna/bin/python "${ROOT_DIR}/scripts/gate_pi05_libero_wiring.py" \
  --run-root "${WIRING_THREE}" --expected-episodes 3 --minimum-successes 2 \
  --output "${WIRING_THREE}/WIRING_GATE.json"

timeout 86400s /workspace/rdna/bin/python "${ROOT_DIR}/scripts/run_pi05_libero_eval_rocm.py" \
  --checkpoint "${CHECKPOINT}" --manifest "${MANIFEST}" --output "${CONFIRMATION}" \
  --phase confirmation --compile false
/workspace/rdna/bin/python "${ROOT_DIR}/scripts/summarize_pi05_libero_benchmark.py" \
  --candidate "${CONFIRMATION}/eval" \
  --output "${CONFIRMATION}/benchmark-summary.json"

printf '{"schema_version":1,"status":"complete","manifest":"%s","checkpoint":"%s","wiring_one":"%s","wiring_three":"%s","confirmation":"%s"}\n' \
  "${MANIFEST}" "${CHECKPOINT}" "${WIRING_ONE}" "${WIRING_THREE}" "${CONFIRMATION}" \
  >"${STATUS}"
cat "${STATUS}"
