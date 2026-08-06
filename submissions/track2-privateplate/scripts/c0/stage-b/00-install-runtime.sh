#!/usr/bin/env bash
# Executable install path for the pinned C0-B runtime (R0-5).
# Runs on the Radeon Notebook BEFORE model download when packages mismatch pins.
# Local hosts without ROCm may use --dry-run / PRIVATEPLATE_INSTALL_DRY_RUN=1.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "${ROOT}"

PIN_FILE="${ROOT}/scripts/c0/stage-b/runtime-pin.json"
PLAN_FILE="${ROOT}/scripts/c0/stage-b/install-plan.json"
DRY_RUN=0
FORCE_REINSTALL=0

for arg in "$@"; do
  case "${arg}" in
    --dry-run) DRY_RUN=1 ;;
    --force) FORCE_REINSTALL=1 ;;
    -h|--help)
      cat <<'EOF'
Usage: bash scripts/c0/stage-b/00-install-runtime.sh [--dry-run] [--force]

  --dry-run   Print the planned actions without installing (local safe mode).
  --force     Reinstall pinned pip packages even when versions already match.

On a formal Radeon run, also require:
  export PRIVATEPLATE_I_CONFIRM_RADEON_RUN=yes

This script installs/upgrades Python packages to match runtime-pin.json.
It does NOT start Radeon, download model weights, or claim model quality.
EOF
      exit 0
      ;;
    *)
      echo "Unknown argument: ${arg}" >&2
      exit 1
      ;;
  esac
done

if [[ "${PRIVATEPLATE_INSTALL_DRY_RUN:-}" == "1" ]]; then
  DRY_RUN=1
fi

if [[ "${DRY_RUN}" -eq 0 && "${PRIVATEPLATE_I_CONFIRM_RADEON_RUN:-}" != "yes" ]]; then
  cat <<'EOF' >&2
Refusing live runtime install without confirmation.

Use one of:
  bash scripts/c0/stage-b/00-install-runtime.sh --dry-run
  PRIVATEPLATE_I_CONFIRM_RADEON_RUN=yes bash scripts/c0/stage-b/00-install-runtime.sh
EOF
  exit 1
fi

if [[ -f /opt/venv/bin/activate ]]; then
  # shellcheck disable=SC1091
  source /opt/venv/bin/activate
fi
export PATH="/opt/venv/bin:${PATH}"
PYTHON_BIN="${PRIVATEPLATE_PYTHON:-$(command -v python3)}"
PIP_BIN="${PRIVATEPLATE_PIP:-$(command -v pip3 || command -v pip || true)}"

OUT_DIR=""
if [[ -n "${PRIVATEPLATE_C0B_OUT_DIR:-}" ]]; then
  OUT_DIR="${PRIVATEPLATE_C0B_OUT_DIR}"
elif [[ -n "${PRIVATEPLATE_RUN_ID:-}" ]]; then
  OUT_DIR="${ROOT}/benchmarks/c0/stage-b/${PRIVATEPLATE_RUN_ID}"
fi
if [[ -n "${OUT_DIR}" ]]; then
  mkdir -p "${OUT_DIR}/raw"
  RECEIPT_PATH="${OUT_DIR}/raw/runtime-install-receipt.json"
else
  # BSD/macOS mktemp requires X's at the end of the template.
  _tmp_receipt="$(mktemp "${TMPDIR:-/tmp}/privateplate-runtime-install.XXXXXX")"
  RECEIPT_PATH="${_tmp_receipt}.json"
  mv "${_tmp_receipt}" "${RECEIPT_PATH}"
fi

echo "== C0-B install-runtime: resolve pins =="
INSTALL_JSON="$(
  node -e '
    const fs = require("node:fs");
    const pin = JSON.parse(fs.readFileSync(process.argv[1], "utf8"));
    const plan = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
    const vllm = pin.vllm;
    if (!vllm?.wheel_url || !vllm?.exact_version) {
      console.error("runtime-pin.json missing vllm wheel_url/exact_version");
      process.exit(2);
    }
    const out = {
      python: pin.python,
      vllm_version: vllm.exact_version,
      vllm_wheel_url: vllm.wheel_url,
      vllm_wheel_size_bytes: vllm.wheel_size_bytes ?? null,
      torch_base: pin.torch.exact_base_version,
      torch_local_version: pin.torch.exact_local_version || null,
      torch_wheel_url: pin.torch.wheel_url || null,
      torch_install_spec: pin.torch.install_spec || null,
      torch_index_url: pin.torch.index_url || null,
      torch_companions: pin.torch.companion_wheel_urls || [],
      hip_prefix: pin.torch.hip_version_prefix,
      transformers: pin.transformers.exact_version,
      compressed_tensors: pin.compressed_tensors.exact_version,
      rocm: pin.rocm.exact_version,
      plan_schema: plan.schema_version
    };
    process.stdout.write(JSON.stringify(out));
  ' "${PIN_FILE}" "${PLAN_FILE}"
)"

VLLM_VERSION="$(node -e 'process.stdout.write(JSON.parse(process.argv[1]).vllm_version)' "${INSTALL_JSON}")"
VLLM_WHEEL_URL="$(node -e 'process.stdout.write(JSON.parse(process.argv[1]).vllm_wheel_url)' "${INSTALL_JSON}")"
TORCH_BASE="$(node -e 'process.stdout.write(JSON.parse(process.argv[1]).torch_base)' "${INSTALL_JSON}")"
HIP_PREFIX="$(node -e 'process.stdout.write(JSON.parse(process.argv[1]).hip_prefix)' "${INSTALL_JSON}")"
TORCH_LOCAL="$(node -e 'process.stdout.write(JSON.parse(process.argv[1]).torch_local_version || "")' "${INSTALL_JSON}")"
TORCH_WHEEL_URL="$(node -e 'process.stdout.write(JSON.parse(process.argv[1]).torch_wheel_url || "")' "${INSTALL_JSON}")"
TORCH_INSTALL_SPEC="$(node -e 'process.stdout.write(JSON.parse(process.argv[1]).torch_install_spec || "")' "${INSTALL_JSON}")"
TORCH_INDEX_URL="$(node -e 'process.stdout.write(JSON.parse(process.argv[1]).torch_index_url || "")' "${INSTALL_JSON}")"
TRANSFORMERS_VER="$(node -e 'process.stdout.write(JSON.parse(process.argv[1]).transformers)' "${INSTALL_JSON}")"
CT_VER="$(node -e 'process.stdout.write(JSON.parse(process.argv[1]).compressed_tensors)' "${INSTALL_JSON}")"
ROCM_VER="$(node -e 'process.stdout.write(JSON.parse(process.argv[1]).rocm)' "${INSTALL_JSON}")"

echo "python_bin=${PYTHON_BIN}"
echo "target vllm=${VLLM_VERSION}"
echo "target torch_base=${TORCH_BASE} local=${TORCH_LOCAL:-any} hip_prefix=${HIP_PREFIX}"
echo "target transformers=${TRANSFORMERS_VER}"
echo "target compressed-tensors=${CT_VER}"
echo "target rocm=${ROCM_VER}"
echo "dry_run=${DRY_RUN}"

ACTIONS=()
record_action() {
  ACTIONS+=("$1")
  echo "PLAN: $1"
}

# Step: Node (always available offline script)
record_action "ensure_node_via_00-install-node22.sh"
if [[ "${DRY_RUN}" -eq 0 ]]; then
  bash "${ROOT}/scripts/c0/stage-b/00-install-node22.sh"
fi

if [[ -z "${PIP_BIN}" ]]; then
  echo "pip not found on PATH after venv activation." >&2
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    record_action "WARN: pip missing (expected on non-Radeon dry-run hosts)"
  else
    exit 1
  fi
fi

probe_python() {
  "${PYTHON_BIN}" - <<'PY' || true
import json, sys
info = {"python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"}
try:
  import importlib.metadata as _md
  import vllm
  try:
    info["vllm"] = _md.version("vllm")
  except Exception:
    info["vllm"] = getattr(vllm, "__version__", "unknown")
except Exception as exc:
  info["vllm_error"] = str(exc)
try:
  import torch
  info["torch"] = torch.__version__
  info["hip"] = getattr(torch.version, "hip", None)
except Exception as exc:
  info["torch_error"] = str(exc)
try:
  import transformers
  info["transformers"] = transformers.__version__
except Exception as exc:
  info["transformers_error"] = str(exc)
try:
  import importlib.metadata as metadata
  info["compressed_tensors"] = metadata.version("compressed-tensors")
except Exception as exc:
  info["compressed_tensors_error"] = str(exc)
print(json.dumps(info))
PY
}

BEFORE_PROBE="$(probe_python)"
if [[ -z "${BEFORE_PROBE}" ]]; then
  BEFORE_PROBE='{}'
fi
echo "probe_before=${BEFORE_PROBE}"

NEED_FILE="$(mktemp "${TMPDIR:-/tmp}/privateplate-install-need.XXXXXX")"
node -e '
  const before = JSON.parse(process.argv[1] || "{}");
  const want = JSON.parse(process.argv[2]);
  const force = process.argv[3] === "1";
  const out = { need_vllm: true, need_tf: true, need_ct: true, torch_ok: false, errors: [] };
  if (!force && before.vllm === want.vllm_version) out.need_vllm = false;
  if (!force && before.transformers === want.transformers) out.need_tf = false;
  if (!force && before.compressed_tensors === want.compressed_tensors) out.need_ct = false;
  const torchBase = String(before.torch || "").match(/^(\d+\.\d+\.\d+)/)?.[1] || null;
  const hip = String(before.hip || "");
  const localOk = !want.torch_local_version || before.torch === want.torch_local_version;
  if (torchBase === want.torch_base && hip.startsWith(want.hip_prefix) && localOk) {
    out.torch_ok = true;
  } else if (before.torch) {
    out.errors.push(`torch/hip mismatch: got torch=${before.torch} hip=${before.hip || "null"} want_local=${want.torch_local_version || want.torch_base}`);
  } else {
    out.errors.push("torch not importable");
  }
  process.stdout.write(JSON.stringify(out));
' "${BEFORE_PROBE}" "${INSTALL_JSON}" "${FORCE_REINSTALL}" >"${NEED_FILE}"

NEED_JSON="$(cat "${NEED_FILE}")"
rm -f "${NEED_FILE}"
need_vllm="$(node -e 'process.stdout.write(String(JSON.parse(process.argv[1]).need_vllm))' "${NEED_JSON}")"
need_tf="$(node -e 'process.stdout.write(String(JSON.parse(process.argv[1]).need_tf))' "${NEED_JSON}")"
need_ct="$(node -e 'process.stdout.write(String(JSON.parse(process.argv[1]).need_ct))' "${NEED_JSON}")"
torch_ok="$(node -e 'process.stdout.write(String(JSON.parse(process.argv[1]).torch_ok))' "${NEED_JSON}")"

torch_matches() {
  local probe="$1"
  node -e '
    const after=JSON.parse(process.argv[1]||"{}");
    const want=JSON.parse(process.argv[2]);
    const torchBase=String(after.torch||"").match(/^(\d+\.\d+\.\d+)/)?.[1]||null;
    const hip=String(after.hip||"");
    const localOk=!want.torch_local_version || after.torch===want.torch_local_version;
    process.stdout.write(String(torchBase===want.torch_base && hip.startsWith(want.hip_prefix) && localOk));
  ' "${probe}" "${INSTALL_JSON}"
}

if [[ "${torch_ok}" != "true" ]]; then
  if [[ -n "${TORCH_WHEEL_URL}" ]]; then
    record_action "pip install vLLM-matched torch wheel ${TORCH_WHEEL_URL}"
    if [[ "${DRY_RUN}" -eq 0 && -n "${PIP_BIN}" ]]; then
      # Official pytorch.org +rocm7.2 local tag is rejected by vLLM 0.25.1+rocm723.
      # Also drop CUDA-oriented flash-attn before installing the ROCm companion wheel.
      "${PIP_BIN}" uninstall -y torch triton triton-rocm triton-kernels torchvision torchaudio flash-attn flash_attn amdsmi amd-aiter amd_aiter 2>/dev/null || true
      "${PIP_BIN}" install --upgrade "${TORCH_WHEEL_URL}"
      # Companion ROCm wheels required by the same vLLM build.
      mapfile -t TORCH_COMPANIONS < <(
        node -e '
          const want=JSON.parse(process.argv[1]);
          for (const url of want.torch_companions || []) process.stdout.write(url + "\n");
        ' "${INSTALL_JSON}"
      )
      for companion in "${TORCH_COMPANIONS[@]}"; do
        [[ -z "${companion}" ]] && continue
        record_action "pip install companion ${companion}"
        "${PIP_BIN}" install --upgrade "${companion}"
      done
      AFTER_TORCH="$(probe_python)"
      torch_ok="$(torch_matches "${AFTER_TORCH}")"
      BEFORE_PROBE="${AFTER_TORCH}"
      echo "probe_after_torch=${AFTER_TORCH}"
      echo "torch_ok_after_install=${torch_ok}"
    fi
  elif [[ -n "${TORCH_INSTALL_SPEC}" && -n "${TORCH_INDEX_URL}" ]]; then
    record_action "pip install ${TORCH_INSTALL_SPEC} from ${TORCH_INDEX_URL} (image mismatch)"
    if [[ "${DRY_RUN}" -eq 0 && -n "${PIP_BIN}" ]]; then
      "${PIP_BIN}" install --upgrade "${TORCH_INSTALL_SPEC}" --index-url "${TORCH_INDEX_URL}"
      AFTER_TORCH="$(probe_python)"
      torch_ok="$(torch_matches "${AFTER_TORCH}")"
      BEFORE_PROBE="${AFTER_TORCH}"
      echo "probe_after_torch=${AFTER_TORCH}"
      echo "torch_ok_after_install=${torch_ok}"
    fi
  else
    record_action "FAIL_CLOSED: torch install source is incomplete"
  fi
fi

if [[ "${torch_ok}" != "true" ]]; then
  record_action "FAIL_CLOSED: torch/HIP still mismatch after install attempt"
  echo "Torch/HIP must match pin before model download." >&2
  echo "need_before_install=${NEED_JSON}" >&2
  echo "probe_now=${BEFORE_PROBE}" >&2
  echo "Need Torch ${TORCH_LOCAL:-$TORCH_BASE} with HIP ${HIP_PREFIX}*, preferably the vLLM ROCm companion wheel." >&2
  if [[ "${DRY_RUN}" -eq 0 ]]; then
    node -e '
      const fs = require("node:fs");
      const payload = {
        schema_version: "1.0",
        status: "FAIL",
        phase: "INSTALL",
        reason: "torch_or_hip_mismatch",
        before: JSON.parse(process.argv[1] || "{}"),
        want: JSON.parse(process.argv[2]),
        install_attempted: process.argv[4] === "true",
        lifecycle_note: "Install failed before model download; the model service was not started by this script.",
        written_at_utc: new Date().toISOString()
      };
      fs.writeFileSync(process.argv[3], JSON.stringify(payload, null, 2) + "\n");
    ' "${BEFORE_PROBE}" "${INSTALL_JSON}" "${RECEIPT_PATH}" "$([[ -n "${TORCH_WHEEL_URL}" || ( -n "${TORCH_INSTALL_SPEC}" && -n "${TORCH_INDEX_URL}" ) ]] && echo true || echo false)"
    exit 2
  fi
fi

# flash-attn is installed from the ROCm companion wheel list when present.
# Do not uninstall it here — that would break vLLM 0.25.1+rocm723 Requires-Dist.
if [[ -z "${TORCH_WHEEL_URL}" ]]; then
  record_action "uninstall_cuda_flash_attn (no ROCm companion torch plan)"
  if [[ "${DRY_RUN}" -eq 0 && -n "${PIP_BIN}" ]]; then
    "${PIP_BIN}" uninstall -y flash-attn flash_attn 2>/dev/null || true
  fi
else
  record_action "keep ROCm flash-attn companion wheel"
fi

if [[ "${need_tf}" == "true" ]]; then
  record_action "pip install transformers==${TRANSFORMERS_VER}"
  if [[ "${DRY_RUN}" -eq 0 ]]; then
    "${PIP_BIN}" install --upgrade "transformers==${TRANSFORMERS_VER}"
  fi
else
  record_action "transformers already ${TRANSFORMERS_VER}"
fi

if [[ "${need_ct}" == "true" ]]; then
  record_action "pip install compressed-tensors==${CT_VER}"
  if [[ "${DRY_RUN}" -eq 0 ]]; then
    "${PIP_BIN}" install --upgrade "compressed-tensors==${CT_VER}"
  fi
else
  record_action "compressed-tensors already ${CT_VER}"
fi

if [[ "${need_vllm}" == "true" ]]; then
  record_action "pip install vllm wheel ${VLLM_WHEEL_URL}"
  if [[ "${DRY_RUN}" -eq 0 ]]; then
    "${PIP_BIN}" install --upgrade "${VLLM_WHEEL_URL}"
  fi
else
  record_action "vllm already ${VLLM_VERSION}"
fi

AFTER_PROBE="{}"
if [[ "${DRY_RUN}" -eq 0 ]]; then
  AFTER_PROBE="$(probe_python)"
  if [[ -z "${AFTER_PROBE}" ]]; then
    AFTER_PROBE='{}'
  fi
  echo "probe_after=${AFTER_PROBE}"
  node -e '
    const after = JSON.parse(process.argv[1] || "{}");
    const want = JSON.parse(process.argv[2]);
    const errors = [];
    if (after.vllm !== want.vllm_version) errors.push(`vllm got ${after.vllm} want ${want.vllm_version}`);
    if (after.transformers !== want.transformers) errors.push(`transformers got ${after.transformers} want ${want.transformers}`);
    if (after.compressed_tensors !== want.compressed_tensors) {
      errors.push(`compressed-tensors got ${after.compressed_tensors} want ${want.compressed_tensors}`);
    }
    const torchBase = String(after.torch || "").match(/^(\d+\.\d+\.\d+)/)?.[1] || null;
    if (torchBase !== want.torch_base) errors.push(`torch base got ${after.torch} want ${want.torch_base}`);
    if (want.torch_local_version && after.torch !== want.torch_local_version) {
      errors.push(`torch local got ${after.torch} want ${want.torch_local_version}`);
    }
    const hip = String(after.hip || "");
    if (!hip.startsWith(want.hip_prefix)) errors.push(`hip got ${after.hip} want prefix ${want.hip_prefix}`);
    if (errors.length) {
      console.error(JSON.stringify({ status: "FAIL", errors }, null, 2));
      process.exit(2);
    }
    console.log(JSON.stringify({ status: "PASS", after }, null, 2));
  ' "${AFTER_PROBE}" "${INSTALL_JSON}"
else
  AFTER_PROBE="${BEFORE_PROBE}"
fi

# Write receipt via stdin for action list to avoid brittle argv quoting.
ACTIONS_TEXT="$(printf '%s\n' "${ACTIONS[@]}")"
node -e '
  const fs = require("node:fs");
  const targets = JSON.parse(process.argv[1]);
  const before = JSON.parse(process.argv[2] || "{}");
  const after = JSON.parse(process.argv[3] || "{}");
  const dryRun = process.argv[4] === "1";
  const pythonBin = process.argv[5];
  const receiptPath = process.argv[6];
  const actions = fs.readFileSync(0, "utf8").split("\n").filter(Boolean);
  const payload = {
    schema_version: "1.0",
    stage: "C0-B",
    phase: "INSTALL",
    dry_run: dryRun,
    status: dryRun ? "DRY_RUN" : "PASS",
    written_at_utc: new Date().toISOString(),
    python_bin: pythonBin,
    targets,
    before,
    after,
    actions,
    lifecycle_note:
      "This receipt covers runtime installation only. run-all.sh stops the model service on exit.",
    claim_boundary:
      "PASS only means pinned Python packages match runtime-pin.json on this host. It does not prove model quality or product gates."
  };
  if (dryRun && (before.torch_error || !before.torch)) {
    payload.host_note = "Non-Radeon or missing torch probe; dry-run only plans the install path.";
  }
  fs.writeFileSync(receiptPath, JSON.stringify(payload, null, 2) + "\n");
  console.log(JSON.stringify({ status: payload.status, receipt: receiptPath, actions: actions.length }, null, 2));
' \
  "${INSTALL_JSON}" \
  "${BEFORE_PROBE}" \
  "${AFTER_PROBE}" \
  "${DRY_RUN}" \
  "${PYTHON_BIN}" \
  "${RECEIPT_PATH}" <<EOF
${ACTIONS_TEXT}
EOF

echo "Install receipt: ${RECEIPT_PATH}"
