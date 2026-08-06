#!/usr/bin/env bash
# Install Pinocchio (pip package `pin`) + reBotArm_control_py for B601 kinematics / gravity compensation.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENDOR="${REPO_ROOT}/vendor/reBotArm_control_py"
SDK_REPO="${B601_SDK_REPO:-https://github.com/vectorBH6/reBotArm_control_py.git}"

PYTHON="${BOTVERSEX_LEROBOT_PYTHON:-}"
if [[ -z "${PYTHON}" ]]; then
  for candidate in \
    "${REPO_ROOT}/apps/realtime/.venv/bin/python3" \
    "${HOME}/venvs/lerobot/bin/python3" \
    "${HOME}/.botversex/venv/bin/python3" \
    "$(command -v python3)"; do
    if [[ -x "${candidate}" ]]; then
      PYTHON="${candidate}"
      break
    fi
  done
fi

if [[ -z "${PYTHON}" || ! -x "${PYTHON}" ]]; then
  echo "No Python found. Set BOTVERSEX_LEROBOT_PYTHON or create ~/venvs/lerobot"
  exit 1
fi

echo "[b601-pinocchio] Using Python: ${PYTHON}"

clone_sdk() {
  local url="$1"
  echo "[b601-pinocchio] git clone ${url}"
  git clone --depth 1 "${url}" "${VENDOR}"
}

if [[ ! -f "${VENDOR}/pyproject.toml" ]]; then
  mkdir -p "$(dirname "${VENDOR}")"
  rm -rf "${VENDOR}"
  if ! clone_sdk "${SDK_REPO}"; then
    echo "[b601-pinocchio] GitHub clone failed — trying ghproxy mirror..."
    rm -rf "${VENDOR}"
    if ! clone_sdk "https://mirror.ghproxy.com/${SDK_REPO}"; then
      echo "[b601-pinocchio] git failed — trying scripts/b601_sdk_fetch.py ..."
      rm -rf "${VENDOR}"
      "${PYTHON}" "${REPO_ROOT}/scripts/b601_sdk_fetch.py" || {
        echo ""
        echo "[b601-pinocchio] 无法从 GitHub 获取 SDK。请手动下载并解压到:"
        echo "  ${VENDOR}"
        exit 1
      }
    fi
  fi
else
  echo "[b601-pinocchio] vendor 已存在 — 增量补全缺失文件"
  "${PYTHON}" "${REPO_ROOT}/scripts/b601_sdk_fetch.py" || true
fi

echo "[b601-pinocchio] pip install pin meshcat  (NOT PyPI pinocchio CLI)"
"${PYTHON}" -m pip install -U pin meshcat

echo "[b601-pinocchio] pip install -e reBotArm_control_py + motorbridge"
"${PYTHON}" -m pip install -e "${VENDOR}" motorbridge

CFG="${VENDOR}/config/rebotarm.yaml"
if [[ -f "${CFG}" ]]; then
  if grep -q 'rebotarm_dm.yaml' "${CFG}" 2>/dev/null; then
    sed -i 's/rebotarm_dm.yaml/rebotarm_rs.yaml/g' "${CFG}" 2>/dev/null || \
      sed -i '' 's/rebotarm_dm.yaml/rebotarm_rs.yaml/g' "${CFG}"
    echo "[b601-pinocchio] Switched hardware_yaml to rebotarm_rs.yaml"
  fi
fi

echo "[b601-pinocchio] Verify imports"
"${PYTHON}" -c "import pinocchio; import reBotArm_control_py; print('pinocchio OK', pinocchio.__version__)"

echo "[b601-pinocchio] Done. Restart Local Agent if it is running."
