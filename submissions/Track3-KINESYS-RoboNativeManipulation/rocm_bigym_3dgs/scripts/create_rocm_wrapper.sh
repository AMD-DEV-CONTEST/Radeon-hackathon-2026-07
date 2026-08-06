#!/usr/bin/env bash
set -euo pipefail

ROCM_ROOT=${ROCM_ROOT:-/opt/rocm-7.2.1}
ROCM_WRAPPER=${ROCM_WRAPPER:-${AMD_BIGYM_ROOT:-/workspace/amd-bigym-3dgs}/toolchains/rocm-wrapper}

test -x "$ROCM_ROOT/lib/llvm/bin/clang++" || {
  printf 'ROCm clang++ not found: %s\n' "$ROCM_ROOT/lib/llvm/bin/clang++" >&2
  exit 2
}

mkdir -p "$ROCM_WRAPPER/bin"
ln -sfn "$ROCM_ROOT/include" "$ROCM_WRAPPER/include"
ln -sfn "$ROCM_ROOT/lib" "$ROCM_WRAPPER/lib"

TASK_HIPCC="$ROCM_WRAPPER/bin/hipcc"
if test -e "$TASK_HIPCC" && ! test -f "$TASK_HIPCC"; then
  printf 'Refusing to overwrite non-file path: %s\n' "$TASK_HIPCC" >&2
  exit 2
fi

{
  printf '%s\n' '#!/usr/bin/env bash'
  printf '%s\n' 'set -euo pipefail'
  printf 'export LIBRARY_PATH="%s/lib${LIBRARY_PATH:+:$LIBRARY_PATH}"\n' "$ROCM_ROOT"
  printf 'export LD_LIBRARY_PATH="%s/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"\n' "$ROCM_ROOT"
  printf 'exec "%s/lib/llvm/bin/clang++" -I"%s/include" -L"%s/lib" -Wl,-rpath,"%s/lib" "$@"\n' \
    "$ROCM_ROOT" "$ROCM_ROOT" "$ROCM_ROOT" "$ROCM_ROOT"
} > "$TASK_HIPCC"
chmod 0755 "$TASK_HIPCC"
printf 'ROCm compiler wrapper ready: %s\n' "$ROCM_WRAPPER"
