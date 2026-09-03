#!/usr/bin/env bash
# ============================================================================
# verify-roc8-promotion.sh — does roc9-merged build and pass from a CLEAN tree?
# ============================================================================
# The promotion gate. roc9-merged's working tree currently carries 6 UNTRACKED
# .cu/.cuh files, and ggml-hip/CMakeLists.txt globs "../ggml-cuda/*.cu" — so the
# local build compiles a source set a fresh clone does not have. Commit
# b2b87656c already fixed exactly this failure mode once (untracked
# mul_mat_q1_0_hipblaslt.*). This script checks it cannot happen again by
# building from a git worktree, which contains committed content ONLY.
#
# Exit 0 = safe to fast-forward roc8. Non-zero = do not promote.
# ============================================================================
set -uo pipefail
SRC="${SRC:?set SRC to your llama.cpp checkout}"
WT="${WORK:-/tmp/roc8-verify}/tree-${BRANCH:-roc8}"
BUILD="${WORK:-/tmp/roc8-verify}/build-${BRANCH:-roc8}"
LOG="${WORK:-/tmp/roc8-verify}/verify-$(date +%Y%m%d-%H%M%S).log"
BRANCH="${BRANCH:-roc9-merged}"
mkdir -p "${WORK:-/tmp/roc8-verify}"
exec > >(tee -a "$LOG") 2>&1

echo "=== roc8 promotion gate: clean-tree build of $BRANCH ==="
cd "$SRC"
echo "[*] source HEAD: $(git rev-parse --short "$BRANCH")  ($(git rev-list --count roc8..$BRANCH) commits ahead of roc8)"

echo "[*] creating clean worktree (committed content only)"
git worktree remove --force "$WT" 2>/dev/null || true
rm -rf "$WT"
git worktree add --detach "$WT" "$BRANCH" >/dev/null 2>&1 || { echo "!! worktree add failed"; exit 1; }

echo "[*] confirming the untracked kernels are ABSENT from the clean tree:"
for f in mul_mat_2of4_iu4_k64.cu swmmac24_iu4_k64.cu dot2_bf16_probe.cu; do
  if [ -e "$WT/ggml/src/ggml-cuda/$f" ]; then echo "    PRESENT (tracked): $f"; else echo "    absent (untracked, as expected): $f"; fi
done

echo "[*] configuring"
source "$SRC/use-rocm714.env"
HIPCXX="${HIPCXX:-$(command -v clang++)}"   # or your ROCm SDK clang++
rm -rf "$BUILD"
cmake -S "$WT" -B "$BUILD" \
  -DCMAKE_BUILD_TYPE=Release \
  -DGGML_HIP=ON -DAMDGPU_TARGETS=gfx1201 \
  -DCMAKE_HIP_COMPILER="$HIPCXX" \
  -DGGML_CUDA_FA=ON -DGGML_CUDA_FA_ALL_QUANTS=OFF \
  -DGGML_HIP_CK_REF_DIR="${GGML_HIP_CK_REF_DIR:-/nonexistent-ck-ref-intentionally-disabled}" \
  -DLLAMA_CURL=OFF \
  > "$BUILD.configure.log" 2>&1
rc=$?
if [ $rc -ne 0 ]; then echo "!! CONFIGURE FAILED (see $BUILD.configure.log)"; tail -25 "$BUILD.configure.log"; exit 2; fi
echo "    configure OK"

echo "[*] building (this is the actual gate) — $(nproc) jobs"
t0=$(date +%s)
cmake --build "$BUILD" -j "$(nproc)" --target llama-bench test-backend-ops llama-cli > "$BUILD.build.log" 2>&1
rc=$?
echo "    build took $(( $(date +%s) - t0 ))s"
if [ $rc -ne 0 ]; then
  echo "!! BUILD FAILED FROM CLEAN TREE — DO NOT PROMOTE"
  echo "--- last errors ---"
  grep -iE "error:|undefined reference|No such file" "$BUILD.build.log" | head -20
  exit 3
fi
echo "    BUILD OK from clean tree"

echo "[*] correctness: test-backend-ops MUL_MAT on ROCm0"
HIP_VISIBLE_DEVICES=0 timeout -s KILL 1800 "$BUILD/bin/test-backend-ops" test -o MUL_MAT -b ROCm0 \
  > "$BUILD.tbo.log" 2>&1
rc=$?
OK=$(grep -c "  OK" "$BUILD.tbo.log" || true); OK=${OK:-0}
FAIL=$(grep -ac "FAIL" "$BUILD.tbo.log" || true); FAIL=${FAIL:-0}
echo "    test-backend-ops: OK=$OK FAIL=$FAIL (exit $rc)"
if [ "$FAIL" -gt 0 ] || [ $rc -ne 0 ]; then
  echo "!! CORRECTNESS REGRESSION — DO NOT PROMOTE"
  grep -iE "FAIL" "$BUILD.tbo.log" | head -15
  exit 4
fi

echo
echo "=== GATE PASSED ==="
echo "  clean-tree build:      OK"
echo "  test-backend-ops:      $OK OK / $FAIL FAIL"
echo "  -> roc8 can be fast-forwarded to $BRANCH"
echo "  log: $LOG"
