#!/usr/bin/env bash
set -euo pipefail

python_bin="${SIGNALFORGE_PYTHON:-python3}"

if ! command -v "$python_bin" >/dev/null 2>&1; then
  echo "Python executable is unavailable: $python_bin" >&2
  exit 1
fi

flash_dir="$($python_bin - <<'PY'
import importlib.util
spec = importlib.util.find_spec("flash_attn")
if spec and spec.submodule_search_locations:
    print(next(iter(spec.submodule_search_locations)))
PY
)"

if [[ -z "$flash_dir" ]]; then
  echo "No flash_attn package is active; no Radeon runtime remediation is required."
  exit 0
fi

error_file="$(mktemp)"
trap 'rm -f "$error_file"' EXIT
if "$python_bin" -c 'import flash_attn' 2>"$error_file"; then
  echo "The active flash_attn package imports successfully; no remediation is required."
  exit 0
fi

if ! grep -q 'flash_attn_2_cuda' "$error_file"; then
  echo "flash_attn failed for an unrecognized reason; refusing to mutate the environment." >&2
  cat "$error_file" >&2
  exit 1
fi

disabled_dir="${flash_dir}.cuda-only-disabled"
if [[ -e "$disabled_dir" ]]; then
  echo "Remediation target already exists: $disabled_dir" >&2
  exit 1
fi

mv "$flash_dir" "$disabled_dir"
echo "Disabled the incompatible CUDA-only flash_attn package: $disabled_dir"
echo "Restore it with: mv '$disabled_dir' '$flash_dir'"
