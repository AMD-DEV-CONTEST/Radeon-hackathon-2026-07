#!/usr/bin/env bash
# Rocky ISA-verification lever: compile a HIP/C++ kernel and show the ACTUAL emitted
# AMDGPU ISA for a given arch, so you can VERIFY which instruction a matmul/dot/loop
# resolves to (catches compiler fallbacks) instead of asserting it. Also surfaces
# exact target-feature gates (e.g. gfx1201: __builtin_amdgcn_sdot4 -> "needs feature
# dot1-insts" => RDNA4 int-dot is a DIFFERENT instruction, not classic dp4a).
#
# Usage:
#   disasm-gfx.sh kernel.hip [gfx1201] [grep-regex]
#   disasm-gfx.sh kernel.hip gfx1201 'v_wmma|v_dot|v_swmmac|v_dual'
#
# Companion: llvm-mc (assemble hand-written ISA the auto-packer won't emit, e.g. VOPD
# V_DOT2C dual-issue bundles) and llvm-objdump (disassemble a prebuilt .co/.hsaco).
# NOTE: the AMD-blog gfx90a/amdphdrs/Code-Object-v1 recipe is STALE — current ROCm is
# COv5 via lld; use --save-temps (below) or clang-offload-bundler --unbundle, not amdphdrs.
set -euo pipefail
SRC="${1:?usage: disasm-gfx.sh kernel.hip [arch] [grep-regex]}"
ARCH="${2:-gfx1201}"
RE="${3:-v_wmma|v_swmmac|v_dot[0-9]|v_dual|v_pk_|v_fma|global_load_b|ds_[a-z]+_b|s_endpgm}"

# Resolve the SDK toolchain (TheRock 7.14 pip SDK in qat714, or system ROCm).
SDK="${ROCM_PATH:-/home/jmonk/miniconda3/envs/qat714/lib/python3.12/site-packages/_rocm_sdk_devel}"
HIPCC="$SDK/bin/hipcc"; [ -x "$HIPCC" ] || HIPCC="$(command -v hipcc)"

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
# Compile the source IN PLACE with -I on its own dir so local #includes (sibling
# headers like decode_common.hpp) resolve; run from TMP so --save-temps lands the
# device .s there. (Copying only the .hip to a tempdir loses its headers.)
ABS="$(cd "$(dirname "$SRC")" && pwd)/$(basename "$SRC")"
SRCDIR="$(dirname "$ABS")"
echo ">> compiling $SRC for $ARCH (feature-gate errors below are DIAGNOSTIC, not noise):"
( cd "$TMP" && "$HIPCC" --offload-arch="$ARCH" -O3 -I"$SRCDIR" --save-temps -c -o k.o "$ABS" ) 2>&1 \
    | grep -iE 'error|needs target feature|note' || true
S="$(ls "$TMP"/*"$ARCH"*.s 2>/dev/null | head -1 || true)"
[ -n "$S" ] || { echo "!! no device ISA emitted (compile failed — see feature gate above)"; exit 1; }
echo ">> emitted $ARCH ISA (filtered: $RE):"
grep -iE "$RE" "$S" | sed 's/^[[:space:]]*//' | sort | uniq -c | sort -rn | head -25
echo ">> full ISA saved alongside via --save-temps in the build dir if you need the schedule."
