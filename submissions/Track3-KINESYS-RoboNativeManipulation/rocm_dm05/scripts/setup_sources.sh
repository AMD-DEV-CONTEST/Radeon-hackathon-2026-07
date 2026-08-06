#!/usr/bin/env bash
set -euo pipefail

ROOT=${1:-$PWD/third_party}
mkdir -p "$ROOT"

if [[ ! -d "$ROOT/opendm/.git" ]]; then
  git clone https://github.com/dexmal/opendm.git "$ROOT/opendm"
fi
git -C "$ROOT/opendm" checkout 89474e8d4e39a4b48458fcb2e119685a8118d5cc
PATCH_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../patches" && pwd)
for patch in opendm-runtime.patch opendm-amd-inference-optimizations.patch; do
  if git -C "$ROOT/opendm" apply --check "$PATCH_ROOT/$patch" 2>/dev/null; then
    git -C "$ROOT/opendm" apply "$PATCH_ROOT/$patch"
  elif git -C "$ROOT/opendm" apply --reverse --check "$PATCH_ROOT/$patch" 2>/dev/null; then
    echo "$patch is already applied"
  else
    echo "OpenDM checkout does not match the pinned base for $patch" >&2
    exit 2
  fi
done

if [[ ! -d "$ROOT/amd-bigym-3dgs-rocm/.git" ]]; then
  git clone https://github.com/eust-w/amd-bigym-3dgs-rocm.git \
    "$ROOT/amd-bigym-3dgs-rocm"
fi
git -C "$ROOT/amd-bigym-3dgs-rocm" checkout \
  f66b9150ca7cfd48746147dfa8326a2657ab309e

echo "OPENDM_ROOT=$ROOT/opendm"
echo "BIGYM_3DGS_ROOT=$ROOT/amd-bigym-3dgs-rocm"
