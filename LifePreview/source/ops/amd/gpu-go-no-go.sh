#!/usr/bin/env bash
set -Eeuo pipefail

ENV_FILE="${1:-/persistent/douyin-amd/config/amd.env}"
OUTPUT_JSON="${2:-}"
MEMORY_CURRENT_MAX_BYTES=47244640256
FILE_CACHE_MAX_BYTES=34359738368
PVC_AVAILABLE_MIN_BYTES=5368709120
GPU_USE_MAX_PERCENT=5
GPU_VRAM_USED_MAX_BYTES=1073741824

fail() {
  printf 'AMD GPU go/no-go: %s\n' "$1" >&2
  exit 2
}

[[ -f "$ENV_FILE" && ! -L "$ENV_FILE" ]] || fail "amd.env is missing or unsafe"
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

: "${AMD_ROOT:?AMD_ROOT must be configured}"
[[ "$AMD_ROOT" == /persistent/* && -d "$AMD_ROOT" ]] || {
  fail "AMD_ROOT must be an existing /persistent directory"
}
OUTPUT_JSON="${OUTPUT_JSON:-$AMD_ROOT/release-evidence/gpu-go-no-go/latest.json}"
case "$OUTPUT_JSON" in
  "$AMD_ROOT"/*) ;;
  *) fail "go/no-go evidence must remain under AMD_ROOT" ;;
esac

CURRENT_FILE="/sys/fs/cgroup/memory.current"
STAT_FILE="/sys/fs/cgroup/memory.stat"
EVENTS_FILE="/sys/fs/cgroup/memory.events.local"
for required in "$CURRENT_FILE" "$STAT_FILE" "$EVENTS_FILE"; do
  [[ -f "$required" && ! -L "$required" ]] || {
    fail "cgroup v2 memory authority is unavailable"
  }
done

memory_current="$(tr -d '[:space:]' <"$CURRENT_FILE")"
file_cache="$(awk '$1 == "file" { print $2; found=1 } END { if (!found) exit 1 }' "$STAT_FILE")"
[[ "$memory_current" =~ ^[0-9]+$ && "$file_cache" =~ ^[0-9]+$ ]] || {
  fail "cgroup v2 memory values are invalid"
}

reasons=()
if (( memory_current >= MEMORY_CURRENT_MAX_BYTES )); then
  reasons+=("memory.current_not_below_44_gib")
fi
if (( file_cache > FILE_CACHE_MAX_BYTES )); then
  reasons+=("file_cache_not_recovered")
fi

pvc_available="$(df -PB1 -- "$AMD_ROOT" | awk 'END { print $4 }')"
[[ "$pvc_available" =~ ^[0-9]+$ ]] || fail "PVC availability is unreadable"
if (( pvc_available <= PVC_AVAILABLE_MIN_BYTES )); then
  reasons+=("pvc_available_not_above_5_gib")
fi

# Reject every residual FLUX, H3, ComfyUI, or GPU worker process.
own_group="$(ps -o pgid= -p "$$" | tr -d '[:space:]')"
[[ "$own_group" =~ ^[0-9]+$ ]] || fail "GPU gate process group is unreadable"
residual_processes="$({
  ps -eo pid=,pgid=,args= | awk -v own_group="$own_group" '
    {
      pid=$1
      pgid=$2
      $1=""
      $2=""
      command=tolower($0)
      is_residual = command ~ /comfyui\/.*main\.py/ || command ~ /creative-hub-dag-worker.*(--gpu-index|video-local|shidu-video-local)/ || command ~ /h3.*(worker|runner)/ || command ~ /flux.*(worker|runner)/
      if (pgid != own_group && is_residual) {
        print pid ":" command
      }
    }
  '
} || true)"
if [[ -n "$residual_processes" ]]; then
  reasons+=("residual_flux_h3_comfyui_or_gpu_worker")
fi

ROCM_SMI="${AMD_ROCM_SMI:-/opt/rocm/bin/rocm-smi}"
PYTHON_BIN="${AMD_PYTHON:-python3}"
gpu_use=-1
gpu_vram_used=-1
gpu_vram_total=-1
if [[ ! -x "$ROCM_SMI" ]]; then
  reasons+=("rocm_smi_unavailable")
else
  if gpu_telemetry="$($ROCM_SMI --showuse --showmeminfo vram --json 2>/dev/null)"; then
    mapfile -t gpu_values < <(
      AMD_GPU_TELEMETRY="$gpu_telemetry" "$PYTHON_BIN" - <<'PY'
import json
import os
import re

payload = json.loads(os.environ["AMD_GPU_TELEMETRY"])
found = {"use": None, "used": None, "total": None}

def number(value):
    match = re.search(r"-?[0-9]+", str(value))
    return int(match.group(0)) if match else None

def walk(value):
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).casefold()
            if "gpu use" in normalized and "%" in normalized:
                found["use"] = number(item)
            elif "vram total used memory" in normalized:
                found["used"] = number(item)
            elif "vram total memory" in normalized:
                found["total"] = number(item)
            walk(item)
    elif isinstance(value, list):
        for item in value:
            walk(item)

walk(payload)
if any(value is None for value in found.values()):
    raise SystemExit(2)
print(found["use"])
print(found["used"])
print(found["total"])
PY
    ) || true
    if [[ "${#gpu_values[@]}" -eq 3 ]] &&
       [[ "${gpu_values[0]}" =~ ^[0-9]+$ ]] &&
       [[ "${gpu_values[1]}" =~ ^[0-9]+$ ]] &&
       [[ "${gpu_values[2]}" =~ ^[1-9][0-9]*$ ]]; then
      gpu_use="${gpu_values[0]}"
      gpu_vram_used="${gpu_values[1]}"
      gpu_vram_total="${gpu_values[2]}"
      if (( gpu_use > GPU_USE_MAX_PERCENT )); then
        reasons+=("gpu_not_idle")
      fi
      if (( gpu_vram_used > GPU_VRAM_USED_MAX_BYTES )); then
        reasons+=("gpu_vram_not_released")
      fi
    else
      reasons+=("gpu_telemetry_invalid")
    fi
  else
    reasons+=("gpu_telemetry_unavailable")
  fi
fi

status="go"
if (( ${#reasons[@]} > 0 )); then
  status="no-go"
fi

output_dir="$(dirname -- "$OUTPUT_JSON")"
install -d -m 0700 -- "$output_dir"
tmp_json="$(mktemp "$output_dir/.gpu-go-no-go.XXXXXX")"
cleanup() {
  if [[ -n "${tmp_json:-}" && -f "$tmp_json" ]]; then
    rm -f -- "$tmp_json"
  fi
}
trap cleanup EXIT

AMD_GATE_STATUS="$status" \
AMD_GATE_REASONS="$(printf '%s\n' "${reasons[@]-}")" \
AMD_MEMORY_CURRENT="$memory_current" \
AMD_FILE_CACHE="$file_cache" \
AMD_PVC_AVAILABLE="$pvc_available" \
AMD_GPU_USE="$gpu_use" \
AMD_GPU_VRAM_USED="$gpu_vram_used" \
AMD_GPU_VRAM_TOTAL="$gpu_vram_total" \
AMD_EVENTS_FILE="$EVENTS_FILE" \
AMD_RESIDUAL_PRESENT="$([[ -n "$residual_processes" ]] && printf true || printf false)" \
"$PYTHON_BIN" - "$tmp_json" <<'PY'
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import sys

events_path = Path(os.environ["AMD_EVENTS_FILE"])
events_text = events_path.read_text(encoding="utf-8")
events = {}
for line in events_text.splitlines():
    name, raw = line.split()
    events[name] = int(raw)
status = os.environ["AMD_GATE_STATUS"]
reasons = [item for item in os.environ["AMD_GATE_REASONS"].splitlines() if item]
pvc_available = int(os.environ["AMD_PVC_AVAILABLE"])
gpu_use = int(os.environ["AMD_GPU_USE"])
gpu_vram_used = int(os.environ["AMD_GPU_VRAM_USED"])
payload = {
    "schemaVersion": "amd.gpu-go-no-go.v1",
    "status": status,
    "checkedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    "cgroupRoot": "/sys/fs/cgroup",
    "memoryCurrentBytes": int(os.environ["AMD_MEMORY_CURRENT"]),
    "memoryCurrentMaxExclusiveBytes": 47244640256,
    "fileCacheBytes": int(os.environ["AMD_FILE_CACHE"]),
    "fileCacheMaxBytes": 34359738368,
    "memoryEventsLocal": events,
    "memoryEventsLocalSha256": hashlib.sha256(events_text.encode()).hexdigest(),
    "pvcAvailableBytes": pvc_available,
    "pvcAvailableMinExclusiveBytes": 5368709120,
    "residualGpuProcessPresent": os.environ["AMD_RESIDUAL_PRESENT"] == "true",
    "gpuUsePercent": gpu_use,
    "gpuVramUsedBytes": gpu_vram_used,
    "gpuVramTotalBytes": int(os.environ["AMD_GPU_VRAM_TOTAL"]),
    "reasons": reasons,
}
Path(sys.argv[1]).write_text(
    json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
    encoding="utf-8",
)
PY
chmod 0600 -- "$tmp_json"
mv -- "$tmp_json" "$OUTPUT_JSON"
tmp_json=""
trap - EXIT

if [[ "$status" != "go" ]]; then
  printf 'AMD GPU gate is NO-GO; evidence: %s\n' "$OUTPUT_JSON" >&2
  exit 1
fi
printf 'AMD GPU gate is GO; evidence: %s\n' "$OUTPUT_JSON"
