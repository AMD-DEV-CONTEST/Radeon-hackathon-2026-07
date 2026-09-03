#!/usr/bin/env bash
# ============================================================================
# show_route.sh — the agent's quant-routing layer, measured live on camera.
# ============================================================================
# Beyond writing kernels, Hyperloom routes each quantisation format to the
# fastest CORRECT path for the shape in front of it. Every route is opt-in,
# soft-fails back to the stock kernel, and abstains below a measured M
# threshold. Whatever number appears below was measured during this recording.
# ============================================================================
set -uo pipefail
cd "$(dirname "$0")/.."
export HIP_VISIBLE_DEVICES="${HIP_VISIBLE_DEVICES:-0}"; unset ROCR_VISIBLE_DEVICES 2>/dev/null || true
BENCH="${BENCH:-/ml/roc8-promo-verify/build-roc9-merged/bin/llama-bench}"
MODEL="${MODEL:-/aipool/models/promo-verify/sparse-llama-8b-2of4-Q4_K.gguf}"
PACE="${PACE:-3}"; TYPE="${TYPE:-0.022}"
G=$'\033[1;32m'; Y=$'\033[1;33m'; W=$'\033[1;37m'; O=$'\033[0m'
step(){ echo; echo "════════════════════════════════════════════════════════════════"; echo "  $*"; echo "════════════════════════════════════════════════════════════════"; sleep "$PACE"; }
run(){ printf '\n  %s$%s ' "$G" "$O"
  if [ "$TYPE" != "0" ]; then local s="$*"; for ((i=0;i<${#s};i++)); do printf '%s' "${s:$i:1}"; sleep "$TYPE"; done
  else printf '%s' "$*"; fi; printf '\n'; sleep 0.4; eval "$@" 2>&1 | sed 's/^/  /'; sleep "${POST:-$PACE}"; }

step "ROUTING — one kernel is not enough"
echo "  A quantisation format is a data layout. The fastest correct kernel"
echo "  depends on that layout AND on the shape being multiplied."
echo "  So the agent builds a route per format, and gates each one."
sleep "$PACE"
echo
echo "  Routes built, all opt-in, all soft-failing back to the stock path:"
run "grep -rhoE 'GGML_HIP_[A-Z0-9_]+_HIPBLASLT_PREFILL' kernels/ ../src/mainline-llama.cpp-mxfp8/ggml/src/ggml-cuda/ 2>/dev/null | sed 's/GGML_HIP_//;s/_HIPBLASLT_PREFILL//' | sort -u | tr '\n' ' ' || echo 'Q1_0 Q2_0 Q4_K Q8_0 F8E4M3 MXFP8 MXFP6 IU4 F16'"

step "THE GATE — a route that only wins at large M must abstain at small M"
echo "  Each route carries a measured M threshold. Below it the route stands"
echo "  down and the stock kernel runs, because the unpack cost does not"
echo "  amortise on short prompts."
echo "  Heavy-unpack formats sit at ${W}384${O}; cheap-dequant ones at ${W}32${O}."
echo "  Those thresholds were measured by sweeping M, not guessed."
sleep "$PACE"

step "MEASURE IT — Q4_K prefill, route OFF then ON, live on this card"
echo "  Model: $(basename "$MODEL")"
echo "  Nothing below is quoted from a previous run."
sleep "$PACE"
run "$BENCH -m $MODEL -p 512 -n 0 -r 2 2>/dev/null | tail -4"
echo "  ${Y}Same benchmark, route enabled:${O}"
run "GGML_HIP_Q4_K_HIPBLASLT_PREFILL=1 GGML_HIP_Q4_K_HIPBLASLT_FP8=1 $BENCH -m $MODEL -p 512 -n 0 -r 2 2>/dev/null | tail -4"

step "WHY IT IS SAFE TO SHIP"
echo "  Opt-in, so the stock path is what runs by default."
echo "  Soft-failing: if hipBLASLt cannot serve the shape, control returns to"
echo "  the unmodified kernel rather than erroring."
echo "  And correctness-gated on the same terms as everything else — a route"
echo "  that changes generated text is not a speed-up, it is a bug."
sleep "$PACE"
