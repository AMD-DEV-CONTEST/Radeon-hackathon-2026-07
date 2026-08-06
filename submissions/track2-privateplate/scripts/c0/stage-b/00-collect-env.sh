#!/usr/bin/env bash
# Collect real Radeon/ROCm environment evidence. Run only on the GPU instance.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
if [[ -z "${PRIVATEPLATE_C0B_OUT_DIR:-}" ]]; then
  if [[ -z "${PRIVATEPLATE_RUN_ID:-}" ]]; then
    echo "PRIVATEPLATE_RUN_ID or PRIVATEPLATE_C0B_OUT_DIR is required." >&2
    exit 1
  fi
  PRIVATEPLATE_C0B_OUT_DIR="${ROOT}/benchmarks/c0/stage-b/${PRIVATEPLATE_RUN_ID}"
fi
OUT_DIR="${PRIVATEPLATE_C0B_OUT_DIR}"
case "${OUT_DIR}" in
  *privateplate-v2|*privateplate-v2.attempt1-arg-fail)
    echo "Refusing protected evidence directory: ${OUT_DIR}" >&2
    exit 1
    ;;
esac
RAW_DIR="${OUT_DIR}/raw"
cd "${ROOT}"

if ! command -v node >/dev/null 2>&1; then
  echo "Node.js >=22.13 is required before C0-B can start the model." >&2
  exit 1
fi
if ! command -v npm >/dev/null 2>&1; then
  echo "npm is required before C0-B can build the product provider." >&2
  exit 1
fi

node_version="$(node --version)"
npm_version="$(npm --version)"
node_semver="${node_version#v}"
IFS=. read -r node_major node_minor _ <<<"${node_semver}"
if [[ ! "${node_major}" =~ ^[0-9]+$ ]] ||
  [[ ! "${node_minor}" =~ ^[0-9]+$ ]] ||
  ((node_major < 22 || (node_major == 22 && node_minor < 13))); then
  echo "Node.js >=22.13 is required; found ${node_version}." >&2
  exit 1
fi

stamp="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
host="$(hostname || echo unknown)"
git_commit=""
git_dirty="unknown"
provenance_source="unavailable"
git_root="$(git -C "${ROOT}" rev-parse --show-toplevel 2>/dev/null || true)"
if [[ -n "${git_root}" ]] &&
  [[ "$(cd "${git_root}" && pwd -P)" == "$(cd "${ROOT}" && pwd -P)" ]]; then
  provenance_source="git"
  git_commit="$(git -C "${ROOT}" rev-parse HEAD)"
  # Exclude dynamic/legacy privateplate-* evidence trees so mid-run outputs
  # (and protected historical trees) do not flip git_dirty.
  if [[ -n "$(
    git -C "${ROOT}" status --porcelain --untracked-files=all -- \
      . \
      ':(exclude)benchmarks/c0/stage-b/privateplate-*' \
      ':(exclude)benchmarks/c0/stage-b/privateplate-*/**' \
      ':(exclude)benchmarks/c0/stage-b/raw' \
      ':(exclude)benchmarks/c0/stage-b/raw/**' \
      2>/dev/null
  )" ]]; then
    git_dirty="true"
  else
    git_dirty="false"
  fi
elif [[ -f "${ROOT}/PRIVATEPLATE_SOURCE_PROVENANCE.json" ]]; then
  provenance_source="packed_clean_commit"
  git_commit="$(
    node -e '
      const value = JSON.parse(require("node:fs").readFileSync(process.argv[1], "utf8"));
      if (!/^[0-9a-f]{40}$/i.test(value.git_commit ?? "")) process.exit(2);
      process.stdout.write(value.git_commit);
    ' "${ROOT}/PRIVATEPLATE_SOURCE_PROVENANCE.json"
  )"
  git_dirty="$(
    node -e '
      const value = JSON.parse(require("node:fs").readFileSync(process.argv[1], "utf8"));
      process.stdout.write(value.git_dirty === false ? "false" : "true");
    ' "${ROOT}/PRIVATEPLATE_SOURCE_PROVENANCE.json"
  )"
fi

if [[ ! "${git_commit}" =~ ^[0-9a-fA-F]{40}$ ]] ||
  [[ "${git_dirty}" != "false" ]]; then
  echo "C0-B requires an exact clean source commit before collecting hardware evidence." >&2
  exit 1
fi

integrity_temp="$(mktemp)"
trap 'rm -f "${integrity_temp}"' EXIT
node scripts/c0/stage-b/source-integrity.mjs \
  verify \
  "${ROOT}" \
  "${git_commit}" \
  "${provenance_source}" >"${integrity_temp}"

mkdir -p "${RAW_DIR}"
mv "${integrity_temp}" "${RAW_DIR}/source-integrity.json"
trap - EXIT

{
  echo "=== collected_at_utc ${stamp} ==="
  echo "=== hostname ${host} ==="
  echo "=== node ${node_version} ==="
  echo "=== npm ${npm_version} ==="
  echo "=== git_commit ${git_commit:-NOT_AVAILABLE} ==="
  echo "=== git_dirty ${git_dirty} ==="
  uname -a || true
  echo "=== rocm-smi ==="
  rocm-smi || true
  echo "=== rocminfo (first 200 lines) ==="
  rocminfo 2>/dev/null | head -n 200 || true
  echo "=== amd-smi / rocm-smi mem ==="
  rocm-smi --showmeminfo vram || true
  rocm-smi --showproductname || true
  echo "=== rocm version ==="
  if [[ -f /opt/rocm/.info/version ]]; then
    sed -n '1p' /opt/rocm/.info/version
  elif [[ -f /opt/rocm/.info/version-dev ]]; then
    sed -n '1p' /opt/rocm/.info/version-dev
  fi
  echo "=== python packages ==="
  if [[ -f /opt/venv/bin/activate ]]; then
    # shellcheck disable=SC1091
    source /opt/venv/bin/activate
  fi
  export PATH="/opt/venv/bin:${PATH}"
  python3 - <<'PY'
import importlib.metadata as metadata
import json, platform, sys
info = {
  "python": sys.version,
  "platform": platform.platform(),
}
try:
  import torch
  info["torch"] = torch.__version__
  info["hip"] = getattr(torch.version, "hip", None)
  info["cuda_available_flag"] = torch.cuda.is_available()
  if torch.cuda.is_available():
    info["device0"] = torch.cuda.get_device_name(0)
    props = torch.cuda.get_device_properties(0)
    info["total_memory_bytes"] = int(props.total_memory)
    info["device0_compute_units"] = int(props.multi_processor_count)
    info["device0_gfx"] = getattr(props, "gcnArchName", None)
    info["device_count"] = int(torch.cuda.device_count())
except Exception as exc:
  info["torch_error"] = str(exc)
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
  import transformers
  info["transformers"] = transformers.__version__
except Exception as exc:
  info["transformers_error"] = str(exc)
try:
  info["compressed_tensors"] = metadata.version("compressed-tensors")
except Exception as exc:
  info["compressed_tensors_error"] = str(exc)
print(json.dumps(info, ensure_ascii=False, indent=2))
PY
} | tee "${RAW_DIR}/environment-commands.txt"

export PRIVATEPLATE_ENV_STAMP="${stamp}"
export PRIVATEPLATE_ENV_HOST="${host}"
export PRIVATEPLATE_C0B_OUT_DIR="${OUT_DIR}"
export PRIVATEPLATE_ENV_NODE_VERSION="${node_version}"
export PRIVATEPLATE_ENV_NPM_VERSION="${npm_version}"
export PRIVATEPLATE_ENV_GIT_COMMIT="${git_commit}"
export PRIVATEPLATE_ENV_GIT_DIRTY="${git_dirty}"
export PRIVATEPLATE_ENV_PROVENANCE_SOURCE="${provenance_source}"

python3 - <<'PY'
import json, os, re, pathlib
out_dir = pathlib.Path(os.environ["PRIVATEPLATE_C0B_OUT_DIR"])
out = out_dir / "environment.json"
raw_text = (out_dir / "raw/environment-commands.txt").read_text(
    encoding="utf-8", errors="replace"
)
source_integrity = json.loads(
    (out_dir / "raw/source-integrity.json").read_text(encoding="utf-8")
)

def first_match(pattern, text, default=None):
    m = re.search(pattern, text, re.M)
    return m.group(1).strip() if m else default

gpu_name = (
    first_match(r"Card Series:\s*(.+)$", raw_text)
    or first_match(r'Marketing Name:\s*(AMD Radeon.+)$', raw_text)
    or first_match(r'"device0":\s*"([^"]+)"', raw_text)
)
driver = (
    first_match(r"Driver version:\s*(\S+)", raw_text)
    or first_match(r"ROCk module version\s+(\S+)", raw_text)
    or first_match(r'"hip":\s*"([^"]+)"', raw_text)
)
rocm_verified = bool(
    re.search(r"ROCm System Management Interface", raw_text, re.I)
    or re.search(r"ROCk module version", raw_text)
    or re.search(r'"hip":\s*"[^"]+"', raw_text)
    or re.search(r"Name:\s*gfx\d+", raw_text)
)
hardware_evidence_eligible = bool(gpu_name and driver and rocm_verified)

gfx_name = (
    first_match(r'"device0_gfx":\s*"([^":]+)', raw_text)
    or first_match(r"Name:\s*(gfx\S+)", raw_text)
)
gfx_block = re.search(r"Name:\s*gfx\S+(.{0,2000})", raw_text, re.S)
gfx_block_cu = (
    first_match(r"Compute Unit:\s*(\d+)", gfx_block.group(1))
    if gfx_block
    else None
)
cu_values = [int(value) for value in re.findall(r"Compute Unit:\s*(\d+)", raw_text)]
# Prefer rocminfo GPU-agent CU (W7900 = 96). Torch multi_processor_count on
# RDNA3 often reports WGP count (48) and must not override the hardware gate.
cu_count = (
    gfx_block_cu
    or (str(max(cu_values)) if cu_values else None)
    or first_match(r'"device0_compute_units":\s*(\d+)', raw_text)
)
pci_id = first_match(r"Chip ID:\s*(\d+)\(0x([0-9a-fA-F]+)\)", raw_text)
device_id_hex = first_match(r"\(DID,\s*GUID\)[^\n]*\n\s*0\s+\d+\s+0x([0-9a-fA-F]+)", raw_text)
vram_total = first_match(r'"total_memory_bytes":\s*(\d+)', raw_text)
smi_excerpt = "\n".join(
    [line for line in raw_text.splitlines() if "ROCm System Management Interface" in line or "Card Series" in line or "VRAM" in line or "gfx" in line.lower()][:40]
)

payload = {
    "schema_version": "1.2",
    "stage": "C0-B",
    "collected_at_utc": os.environ["PRIVATEPLATE_ENV_STAMP"],
    "hostname": os.environ["PRIVATEPLATE_ENV_HOST"],
    "provider_mode": "local_vllm_radeon",
    "remote_api": False,
    "evidence_eligible": hardware_evidence_eligible,
    "account_channel": os.environ.get("PRIVATEPLATE_ACCOUNT_CHANNEL"),
    "profile_url": os.environ.get("PRIVATEPLATE_PROFILE_URL"),
    "storage_mode": os.environ.get("PRIVATEPLATE_STORAGE_MODE"),
    "model_directory": os.environ.get("PRIVATEPLATE_MODEL_DIRECTORY"),
    "instance_id": os.environ.get("PRIVATEPLATE_INSTANCE_ID"),
    "credits_before": os.environ.get("PRIVATEPLATE_CREDITS_BEFORE"),
    "credits_after": None,
    "operator_receipts_status": "NOT_REQUIRED_FREE_INSTANCE",
    "model_profile": os.environ.get("PRIVATEPLATE_MODEL_PROFILE"),
    "run_id": os.environ.get("PRIVATEPLATE_RUN_ID"),
    "node_version": os.environ["PRIVATEPLATE_ENV_NODE_VERSION"],
    "node_requirement": ">=22.13",
    "node_preflight": "PASS",
    "npm_version": os.environ["PRIVATEPLATE_ENV_NPM_VERSION"],
    "git_commit": os.environ.get("PRIVATEPLATE_ENV_GIT_COMMIT") or None,
    "git_dirty": {
        "true": True,
        "false": False,
    }.get(os.environ.get("PRIVATEPLATE_ENV_GIT_DIRTY")),
    "source_provenance": os.environ["PRIVATEPLATE_ENV_PROVENANCE_SOURCE"],
    "source_integrity_verified": source_integrity.get("verified") is True,
    "source_integrity_mode": source_integrity.get("mode"),
    "source_manifest_sha256": source_integrity.get("manifest_sha256"),
    "source_file_count": source_integrity.get("file_count"),
    "source_integrity_log": "raw/source-integrity.json",
    "raw_command_log": "raw/environment-commands.txt",
    "gpu_name": gpu_name,
    "driver": driver,
    "rocm_verified": rocm_verified,
    "hardware": {
        "gfx_architecture": gfx_name,
        "compute_units": int(cu_count) if cu_count and cu_count.isdigit() else None,
        "chip_id_raw": pci_id,
        "device_id_hex": device_id_hex,
        "total_memory_bytes": int(vram_total) if vram_total and vram_total.isdigit() else None,
        "amd_smi_excerpt": smi_excerpt or None,
    },
    "software_versions": {
        "status": "PARTIAL_FROM_ENV_COMMANDS",
        "python": first_match(r'"python":\s*"([^"]+)"', raw_text),
        "torch": first_match(r'"torch":\s*"([^"]+)"', raw_text),
        "hip": first_match(r'"hip":\s*"([^"]+)"', raw_text),
        "vllm": first_match(r'"vllm":\s*"([^"]+)"', raw_text),
        "transformers": first_match(r'"transformers":\s*"([^"]+)"', raw_text),
        "compressed_tensors": first_match(r'"compressed_tensors":\s*"([^"]+)"', raw_text),
        "attention_backend": os.environ.get("VLLM_ATTENTION_BACKEND"),
        "tool_call_parser": None,
        "image_digest": os.environ.get("PRIVATEPLATE_IMAGE_DIGEST"),
    },
    "model_artifact": {
        "status": "PLANNED_ON_RADEON",
        "model_id": None,
        "revision": None,
        "weight_checksums": [],
        "quantization": None,
        "license": None,
        "chat_template_sha256": None,
    },
    "notes": "Values derived from live instance commands; do not hand-edit performance fields. model_artifact filled after model load on Radeon.",
}
out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"Wrote {out}")
PY

node --input-type=module -e '
  const { assertVerifiedRadeonEnvironment } = await import("./scripts/c0/stage-b/evidence-guard.mjs");
  await assertVerifiedRadeonEnvironment(process.argv[1]);
' "${OUT_DIR}/environment.json"
