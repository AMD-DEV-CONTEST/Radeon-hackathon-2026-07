#!/usr/bin/env bash
set -uo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATASET_ROOT="${1:?usage: run_model_sweep_rocm.sh DATASET_ROOT SPLIT_MANIFEST OUTPUT_ROOT}"
SPLIT_MANIFEST="${2:?usage: run_model_sweep_rocm.sh DATASET_ROOT SPLIT_MANIFEST OUTPUT_ROOT}"
OUTPUT_ROOT="${3:?usage: run_model_sweep_rocm.sh DATASET_ROOT SPLIT_MANIFEST OUTPUT_ROOT}"
CAMPAIGN_PATH="${CAMPAIGN_PATH:-${ROOT_DIR}/configs/campaign_v1.toml}"
SEEDS_TEXT="${MODEL_SWEEP_SEEDS:-11,22,33}"
MODELS_TEXT="${MODEL_SWEEP_MODELS:-act}"
ACT_STEPS="${MODEL_SWEEP_ACT_STEPS:-30000}"
DIFFUSION_STEPS="${MODEL_SWEEP_DIFFUSION_STEPS:-30000}"

export HIP_VISIBLE_DEVICES="${HIP_VISIBLE_DEVICES:-0}"
export PYTHONPATH="${ROOT_DIR}/src${PYTHONPATH:+:${PYTHONPATH}}"
cd "${ROOT_DIR}"
source scripts/activate_radeon_env.sh
bash scripts/preflight_radeon.sh

if [[ ! -f "${CAMPAIGN_PATH}" ]]; then
  echo "ERROR: campaign contract not found: ${CAMPAIGN_PATH}" >&2
  exit 4
fi
python scripts/validate_campaign.py "${CAMPAIGN_PATH}"

if [[ ! -f "${SPLIT_MANIFEST}" ]]; then
  echo "ERROR: split manifest not found: ${SPLIT_MANIFEST}" >&2
  exit 2
fi
if [[ ! -f "${DATASET_ROOT}/meta/info.json" ]]; then
  echo "ERROR: dataset not found: ${DATASET_ROOT}" >&2
  exit 3
fi

IFS=',' read -r -a SEEDS <<< "${SEEDS_TEXT}"
IFS=',' read -r -a MODELS <<< "${MODELS_TEXT}"
mkdir -p "${OUTPUT_ROOT}"
printf 'model,modality,seed,status\n' > "${OUTPUT_ROOT}/sweep_status.csv"
overall_status=0

run_one() {
  local model="$1"
  local modality="$2"
  local seed="$3"
  local output_dir="${OUTPUT_ROOT}/${model}-${modality}-seed${seed}"
  local log_path="${OUTPUT_ROOT}/${model}-${modality}-seed${seed}.log"
  mkdir -p "${OUTPUT_ROOT}"
  echo "[$(date -Is)] start ${model} ${modality} seed=${seed}" | tee "${log_path}"
  local status=0
  if [[ "${model}" == "act" ]]; then
    ACT_SEED="${seed}" \
    ACT_STEPS="${ACT_STEPS}" \
    ACT_USE_AMP=true \
    ACT_USE_DEPTH="$([[ "${modality}" == "rgb-d" ]] && echo true || echo false)" \
    DATASET_SPLIT_MANIFEST="${SPLIT_MANIFEST}" \
    bash scripts/train_act_rocm.sh "${DATASET_ROOT}" "${output_dir}" >>"${log_path}" 2>&1 || status=$?
  elif [[ "${model}" == "diffusion" ]]; then
    DIFFUSION_SEED="${seed}" \
    DIFFUSION_STEPS="${DIFFUSION_STEPS}" \
    DIFFUSION_USE_AMP=true \
    DIFFUSION_USE_DEPTH="$([[ "${modality}" == "rgb-d" ]] && echo true || echo false)" \
    DIFFUSION_DOWN_DIMS="${DIFFUSION_DOWN_DIMS:-256,512,1024}" \
    DIFFUSION_HORIZON="${DIFFUSION_HORIZON:-32}" \
    DIFFUSION_N_ACTION_STEPS="${DIFFUSION_N_ACTION_STEPS:-8}" \
    DIFFUSION_INFERENCE_STEPS="${DIFFUSION_INFERENCE_STEPS:-10}" \
    DATASET_SPLIT_MANIFEST="${SPLIT_MANIFEST}" \
    bash scripts/train_diffusion_rocm.sh "${DATASET_ROOT}" "${output_dir}" >>"${log_path}" 2>&1 || status=$?
  else
    echo "unknown model: ${model}" >&2
    return 64
  fi
  echo "[$(date -Is)] finish status=${status}" | tee -a "${log_path}"
  printf '%s,%s,%s,%s\n' "${model}" "${modality}" "${seed}" "${status}" >> "${OUTPUT_ROOT}/sweep_status.csv"
  if (( status != 0 )); then
    overall_status=1
  fi
  return 0
}

for model in "${MODELS[@]}"; do
  for modality in rgb rgb-d; do
    for seed in "${SEEDS[@]}"; do
      run_one "${model}" "${modality}" "${seed}"
    done
  done
done

echo "sweep status: ${OUTPUT_ROOT}/sweep_status.csv"
exit "${overall_status}"
