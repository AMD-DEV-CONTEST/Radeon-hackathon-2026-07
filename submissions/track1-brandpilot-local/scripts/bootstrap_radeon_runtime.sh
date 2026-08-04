#!/usr/bin/env bash
set -u

PYTHON="/opt/venv/bin/python"
MODE="check"
OUTPUT_PATH=""
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"

usage() {
  printf '%s\n' "safe diagnostic: usage bootstrap_radeon_runtime.sh (--check-only|--install) [--output PATH]"
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --check-only)
      MODE="check"
      shift
      ;;
    --install)
      MODE="install"
      shift
      ;;
    --output)
      [ "$#" -ge 2 ] || { usage; exit 2; }
      OUTPUT_PATH="$2"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      printf '%s\n' "safe diagnostic: unsupported argument"
      exit 2
      ;;
  esac
done

if [ ! -x "$PYTHON" ]; then
  printf '%s\n' "runtime python: unavailable"
  exit 1
fi
if [ -z "${PERSISTENT_ROOT:-}" ] || [ ! -d "$PERSISTENT_ROOT" ]; then
  printf '%s\n' "persistent storage: unavailable"
  exit 1
fi

WHEELHOUSE="${PERSISTENT_ROOT%/}/brandpilot-wheelhouse"
mkdir -p -- "$WHEELHOUSE"

PACKAGE_ROWS="$(cat <<'EOF'
diffusers|diffusers|0.39.0
transformers|transformers|4.57.6
accelerate|accelerate|1.13.0
safetensors|safetensors|0.7.0
fastapi|fastapi|0.116.1
uvicorn|uvicorn|0.35.0
pydantic|pydantic|2.11.7
pydantic-core|pydantic_core|2.33.2
python-multipart|multipart|0.0.20
Pillow|PIL|11.3.0
opencv-python-headless|cv2|4.12.0.88
aiofiles|aiofiles|24.1.0
httpx|httpx|0.28.1
EOF
)"

missing_specs=()
while IFS='|' read -r distribution import_name version; do
  if ! "$PYTHON" - "$distribution" "$import_name" "$version" <<'PY' >/dev/null 2>&1
import importlib
import importlib.metadata
import sys

distribution, import_name, expected = sys.argv[1:]
actual = importlib.metadata.version(distribution)
if actual != expected:
    raise SystemExit(1)
importlib.import_module(import_name)
PY
  then
    missing_specs+=("${distribution}==${version}")
  fi
done <<< "$PACKAGE_ROWS"

if [ "$MODE" = "install" ] && [ "${#missing_specs[@]}" -gt 0 ]; then
  for spec in "${missing_specs[@]}"; do
    distribution="${spec%%==*}"
    version="${spec##*==}"
    normalized="$(printf '%s' "$distribution" | tr '[:upper:].-' '[:lower:]__')"
    wheel=""
    while IFS= read -r candidate; do
      wheel="$candidate"
      break
    done < <(find "$WHEELHOUSE" -maxdepth 1 -type f \
      \( -iname "${distribution}-${version}-*.whl" -o -iname "${normalized}-${version}-*.whl" \) \
      -print)
    if [ -z "$wheel" ]; then
      "$PYTHON" -m pip download \
        --only-binary=:all: \
        --no-deps \
        --dest "$WHEELHOUSE" \
        "$spec"
      while IFS= read -r candidate; do
        wheel="$candidate"
        break
      done < <(find "$WHEELHOUSE" -maxdepth 1 -type f \
        \( -iname "${distribution}-${version}-*.whl" -o -iname "${normalized}-${version}-*.whl" \) \
        -print)
    fi
    [ -n "$wheel" ] || {
      printf '%s\n' "runtime package wheel: unavailable"
      exit 1
    }
    "$PYTHON" -m pip install --no-deps "$wheel"
  done
fi

set +e
RUNTIME_JSON="$("$PYTHON" - <<'PY'
import importlib
import importlib.metadata
import json

packages = [
    ("diffusers", "diffusers", "0.39.0"),
    ("transformers", "transformers", "4.57.6"),
    ("accelerate", "accelerate", "1.13.0"),
    ("safetensors", "safetensors", "0.7.0"),
    ("fastapi", "fastapi", "0.116.1"),
    ("uvicorn", "uvicorn", "0.35.0"),
    ("pydantic-core", "pydantic_core", "2.33.2"),
    ("Pillow", "PIL", "11.3.0"),
]
versions = {}
imports_ready = True
for distribution, import_name, expected in packages:
    try:
        actual = importlib.metadata.version(distribution)
        importlib.import_module(import_name)
    except Exception:
        actual = None
        imports_ready = False
    versions[distribution] = actual
    if actual != expected:
        imports_ready = False

torch_ready = False
gpu_available = False
hip_available = False
amd_radeon = False
memory_48gib_class = False
torch_version = None
hip_version = None
device_name = None
try:
    import torch
    torch_version = str(torch.__version__)
    hip_version = str(getattr(torch.version, "hip", "") or "")
    gpu_available = bool(torch.cuda.is_available() and torch.cuda.device_count() > 0)
    hip_available = bool(hip_version)
    device_name = torch.cuda.get_device_name(0) if gpu_available else None
    amd_radeon = bool(device_name and ("amd" in device_name.lower() or "radeon" in device_name.lower()))
    if gpu_available:
        memory_48gib_class = int(torch.cuda.get_device_properties(0).total_memory) >= 45 * 1024**3
    torch_ready = (
        torch_version == "2.9.1+gitff65f5b"
        and hip_version == "7.2.53211-e1a6bc5663"
    )
except Exception:
    pass

ready = all(
    (
        imports_ready,
        torch_ready,
        gpu_available,
        hip_available,
        amd_radeon,
        memory_48gib_class,
    )
)
print(json.dumps({
    "runtime_ready": ready,
    "imports_ready": imports_ready,
    "torch_preserved": torch_ready,
    "gpu_available": gpu_available,
    "hip_available": hip_available,
    "amd_radeon_detected": amd_radeon,
    "memory_48gib_class": memory_48gib_class,
    "pytorch_version": torch_version,
    "hip_rocm_version": hip_version,
    "device_name": device_name,
    "package_versions": versions,
}))
raise SystemExit(0 if ready else 1)
PY
)"
runtime_status=$?
set -e

if [ "$runtime_status" -eq 0 ]; then
  printf '%s\n' "Radeon runtime: available"
else
  printf '%s\n' "Radeon runtime: unavailable"
fi
if [ "${#missing_specs[@]}" -eq 0 ]; then
  printf '%s\n' "runtime packages: available"
elif [ "$MODE" = "install" ]; then
  printf '%s\n' "runtime package installation: completed"
else
  printf '%s\n' "runtime packages: unavailable"
fi
printf '%s\n' "persistent wheelhouse: available"

checker_ready=false
if [ "$runtime_status" -eq 0 ] &&
  "$PYTHON" "$REPOSITORY_ROOT/scripts/radeon_environment_check.py" >/dev/null 2>&1; then
  checker_ready=true
fi

if [ -n "$OUTPUT_PATH" ]; then
  output_parent="$(dirname -- "$OUTPUT_PATH")"
  mkdir -p -- "$output_parent"
  temporary_output="$(mktemp "${output_parent}/.radeon-bootstrap.XXXXXX")"
  trap 'rm -f -- "${temporary_output:-}"' EXIT
  BOOTSTRAP_RUNTIME_JSON="$RUNTIME_JSON" \
  BOOTSTRAP_CHECKER_READY="$checker_ready" \
  BOOTSTRAP_WHEELHOUSE_READY=true \
  "$PYTHON" - "$temporary_output" <<'PY'
import json
import os
import sys
from pathlib import Path

payload = json.loads(os.environ["BOOTSTRAP_RUNTIME_JSON"] or "{}")
payload["environment_checker_ready"] = os.environ["BOOTSTRAP_CHECKER_READY"] == "true"
payload["persistent_wheelhouse_ready"] = os.environ["BOOTSTRAP_WHEELHOUSE_READY"] == "true"
Path(sys.argv[1]).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
  mv -- "$temporary_output" "$OUTPUT_PATH"
  trap - EXIT
fi

[ "$runtime_status" -eq 0 ] && [ "$checker_ready" = true ]
