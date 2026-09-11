#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
THIRD_PARTY_DIR="${ROOT_DIR}/third_party"
VENV_DIR="${ROOT_DIR}/.venv"
GENESIS_SHA="ec0efcc0daf9b9932920e6b73f5f810961330997"
LEROBOT_SHA="73dbb6f43a5088583706c91fb73c6957bca5f806"

export HIP_VISIBLE_DEVICES="${HIP_VISIBLE_DEVICES:-0}"
mkdir -p "${THIRD_PARTY_DIR}"

PIP_INDEX_ARGS=()
if [[ -n "${ROCM_PIP_INDEX_URL:-}" ]]; then
  PIP_INDEX_ARGS+=(--index-url "${ROCM_PIP_INDEX_URL}")
fi

if ! source "${ROOT_DIR}/scripts/activate_radeon_env.sh"; then
  python3 -m venv --system-site-packages "${VENV_DIR}"
  source "${VENV_DIR}/bin/activate"
  export PARCEL_SORTER_VENV="${VENV_DIR}"
fi

bash "${ROOT_DIR}/scripts/preflight_radeon.sh"
python "${ROOT_DIR}/scripts/smoke_rocm.py"

prepare_source() {
  local name="$1"
  local url="$2"
  local revision="$3"
  local directory="${THIRD_PARTY_DIR}/${name}"

  case "${directory}" in
    "${THIRD_PARTY_DIR}"/*) ;;
    *) echo "Refusing to manage a source outside third_party" >&2; exit 1 ;;
  esac

  if [[ -f "${directory}/.upstream-sha" ]] && \
     [[ "$(cat "${directory}/.upstream-sha")" == "${revision}" ]]; then
    echo "Using downloaded ${name} at ${revision}"
    return
  fi

  if [[ ! -d "${directory}/.git" ]]; then
    rm -rf "${directory}"
    git clone "${url}" "${directory}"
  fi
  git -C "${directory}" fetch --depth 1 origin "${revision}"
  git -C "${directory}" checkout --detach "${revision}"
}

prepare_source \
  "genesis-world" \
  "https://github.com/Genesis-Embodied-AI/genesis-world.git" \
  "${GENESIS_SHA}"

python -m pip install "${PIP_INDEX_ARGS[@]}" --upgrade pip setuptools wheel
python -m pip install "${PIP_INDEX_ARGS[@]}" -e "${THIRD_PARTY_DIR}/genesis-world"
python -m pip install "${PIP_INDEX_ARGS[@]}" -e "${ROOT_DIR}"
python "${ROOT_DIR}/scripts/smoke_genesis.py" --steps 80

if [[ "${INSTALL_LEROBOT:-0}" == "1" ]]; then
  prepare_source \
    "lerobot" \
    "https://github.com/huggingface/lerobot.git" \
    "${LEROBOT_SHA}"
  # Install every policy used by the documented reproduction path. These are
  # LeRobot's own pinned extras, not separately floating dependency lists.
  python -m pip install "${PIP_INDEX_ARGS[@]}" -e "${THIRD_PARTY_DIR}/lerobot[training,diffusion,smolvla]"
fi

python "${ROOT_DIR}/scripts/smoke_rocm.py"
python -m unittest discover -s "${ROOT_DIR}/tests" -v

echo "Radeon bootstrap completed. Run: bash scripts/run_pipeline_radeon.sh"
