#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/common.sh"

require_command python3
require_command git
require_command rocminfo
require_command rocm-smi
mkdir -p "$RUNTIME_EVIDENCE_DIR"

ROCM_ROOT=${ROCM_ROOT:-/opt/rocm}
test -d "$ROCM_ROOT" || fail "ROCm root is missing: $ROCM_ROOT"

ARCH_COUNT=$(rocminfo | awk '/Name: +gfx1100/{count++} END{print count+0}')
test "$ARCH_COUNT" -ge 1 || fail "rocminfo did not report gfx1100"
if test "$ARCH_COUNT" -eq 1 && test "$INFERENCE_GPU" != "$SIM_GPU"; then
  fail "one gfx1100 is available, so INFERENCE_GPU and SIM_GPU must select the same device"
fi

{
  printf 'captured_at=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf 'hostname=%s\n' "$(hostname)"
  printf 'rocm_root=%s\n' "$ROCM_ROOT"
  printf 'gfx1100_count=%s\n' "$ARCH_COUNT"
  printf 'inference_gpu=%s\n' "$INFERENCE_GPU"
  printf 'inference_provider=%s\n' "$INFERENCE_PROVIDER"
  printf 'sim_gpu=%s\n' "$SIM_GPU"
} > "$RUNTIME_EVIDENCE_DIR/amd-preflight.env"
rocminfo > "$RUNTIME_EVIDENCE_DIR/rocminfo.txt"
rocm-smi --showproductname --showuniqueid --showmeminfo vram --showuse \
  > "$RUNTIME_EVIDENCE_DIR/rocm-smi-before.txt"

printf 'AMD_PREFLIGHT_OK gfx1100=%s inference_gpu=%s sim_gpu=%s\n' \
  "$ARCH_COUNT" "$INFERENCE_GPU" "$SIM_GPU"
if test "$ARCH_COUNT" -eq 1; then
  printf 'WARN: an external inference service and gsplat may share one GPU in separate processes; run the smoke memory gate before formal evaluation.\n'
fi
