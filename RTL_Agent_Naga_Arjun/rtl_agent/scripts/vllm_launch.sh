#!/usr/bin/env bash
# =============================================================================
# scripts/vllm_launch.sh — Optimized vLLM server launch for AMD ROCm
#
# ATTENTION BACKEND SELECTION — read before running:
#
#   The correct attention backend depends on your GPU architecture:
#
#   • AMD Instinct (MI300X, MI250X, MI210) — datacenter GPUs:
#       VLLM_ATTENTION_BACKEND=ROCM_FLASH
#       These cards have full AoTriton/AITER support.
#
#   • AMD Radeon (RX 7900, RX 7800, Navi) — consumer/prosumer GPUs:
#       VLLM_ATTENTION_BACKEND=TRITON_ATTN   ← likely correct for Radeon
#       Radeon cards don't have the same AITER primitives as Instinct.
#
#   Set GPU_ARCH below, or override with:
#       GPU_ARCH=instinct ./scripts/vllm_launch.sh fp16-optimized
#       GPU_ARCH=radeon   ./scripts/vllm_launch.sh fp16-optimized
#
#   When in doubt, run `rocminfo | grep "Name:" | head -5` first,
#   then check: https://rocm.docs.amd.com/
#
# Usage:
#   ./scripts/vllm_launch.sh fp16            ← fp16 baseline (no optimizations)
#   ./scripts/vllm_launch.sh fp16-optimized  ← fp16 + prefix caching + tuned params
#   ./scripts/vllm_launch.sh awq             ← AWQ int4 + prefix caching
#   ./scripts/vllm_launch.sh gptq            ← GPTQ int4
# =============================================================================

set -euo pipefail

MODE="${1:-fp16-optimized}"

# ─── GPU Architecture Detection ───────────────────────────────────────────────
# Override with: GPU_ARCH=instinct ./scripts/vllm_launch.sh ...
GPU_ARCH="${GPU_ARCH:-auto}"

if [ "$GPU_ARCH" = "auto" ]; then
    # Try to detect from rocminfo
    if command -v rocminfo &>/dev/null; then
        GPU_NAME=$(rocminfo 2>/dev/null | grep -i "Name:" | grep -i "gfx\|Instinct\|Radeon" | head -1 | tr '[:lower:]' '[:upper:]')
        if echo "$GPU_NAME" | grep -qiE "INSTINCT|MI300|MI250|MI210|GFX942|GFX940|GFX941"; then
            GPU_ARCH="instinct"
        else
            GPU_ARCH="radeon"
        fi
        echo "[vllm_launch] Detected GPU architecture: $GPU_ARCH (from rocminfo)"
    else
        # rocminfo not available — default to radeon (safer)
        GPU_ARCH="radeon"
        echo "[vllm_launch] rocminfo not found — defaulting to GPU_ARCH=radeon"
        echo "               Override with: GPU_ARCH=instinct ./scripts/vllm_launch.sh $MODE"
    fi
fi

# ─── ROCm Environment Variables ───────────────────────────────────────────────
# Set attention backend based on GPU architecture
if [ "$GPU_ARCH" = "instinct" ]; then
    # Instinct (MI300X etc): ROCmFlashAttention backend via AoTriton
    export VLLM_ATTENTION_BACKEND="ROCM_FLASH"
    # AoTriton experimental flash attention for Instinct cards
    # Verify this env var is recognized on your vLLM version with: vllm serve --help
    export TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL="${TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL:-1}"
    echo "[vllm_launch] Attention backend: ROCM_FLASH (Instinct/AoTriton)"
else
    # Radeon (RX 7900 etc): Triton-based attention (AITER not available on Radeon)
    export VLLM_ATTENTION_BACKEND="TRITON_ATTN"
    echo "[vllm_launch] Attention backend: TRITON_ATTN (Radeon/Triton)"
fi

# Triton cache to avoid permission warnings on shared filesystems
export TRITON_CACHE_DIR="${TRITON_CACHE_DIR:-/tmp/triton_cache}"
mkdir -p "$TRITON_CACHE_DIR"

# ─── Model IDs ────────────────────────────────────────────────────────────────
MODEL_FP16="Qwen/Qwen2.5-Coder-7B-Instruct"
MODEL_AWQ="Qwen/Qwen2.5-Coder-7B-Instruct-AWQ"
MODEL_GPTQ="Qwen/Qwen2.5-Coder-7B-Instruct-GPTQ-Int4"

echo ""
echo "============================================================"
echo "  RTL-Agent vLLM Launch"
echo "  Mode    : $MODE"
echo "  GPU arch: $GPU_ARCH"
echo "  Attn    : $VLLM_ATTENTION_BACKEND"
echo "============================================================"
echo ""

# ─── Common Flags ─────────────────────────────────────────────────────────────
COMMON_FLAGS=(
    --port 8000
    --host 0.0.0.0
    --served-model-name Qwen/Qwen2.5-Coder-7B-Instruct
    --dtype float16          # float16: universally supported on all ROCm targets.
                             # bfloat16 may not be natively supported on all GFX
                             # architectures — fp16 is always safe.
    --max-model-len 8192     # covers full rolling context (sys prompt + code + errors × 3)
    --trust-remote-code      # required for Qwen2.5-Coder tokenizer
    --served-model-name Qwen/Qwen2.5-Coder-7B-Instruct  # fixed alias — agent_server.py doesn't need updating
)

# ─── Mode-specific flags ───────────────────────────────────────────────────────
case "$MODE" in

  fp16)
    # ── Baseline: fp16, NO optimizations ──────────────────────────────────────
    # Collect baseline numbers with rocm_bench.py --config baseline --runs 3
    echo "Mode: FP16 BASELINE (no optimizations — for benchmark comparison only)"
    python -m vllm.entrypoints.openai.api_server \
        --model "$MODEL_FP16" \
        "${COMMON_FLAGS[@]}" \
        --gpu-memory-utilization 0.85 \
        --max-num-seqs 32 \
        --disable-prefix-caching
    ;;

  fp16-optimized)
    # ── Optimized fp16: prefix caching + tuned KV cache + concurrency ─────────
    #
    # WHY prefix caching benefits this agent specifically:
    # Every self-correction iteration re-sends the same growing prefix to the LLM:
    #   Iter 1: [sys_prompt][user_spec]
    #   Iter 2: [sys_prompt][user_spec][DUT_v1][lint_errors]
    #   Iter 3: [sys_prompt][user_spec][DUT_v1][lint_errors][DUT_v2][sim_fail]
    # vLLM's radix attention cache reuses KV blocks from Iter 1 in Iters 2 and 3.
    # Cache hit rate grows with correction depth — a 3-iter chain achieves ~65-75%
    # token reuse on the shared prefix.
    #
    # --gpu-memory-utilization=0.90: allocates 90% of VRAM to KV cache pages.
    # --enable-chunked-prefill: overlaps prefill and decode, reducing TTFT variance.
    echo "Mode: FP16 OPTIMIZED (prefix caching + chunked prefill + tuned params)"
    python -m vllm.entrypoints.openai.api_server \
        --model "$MODEL_FP16" \
        "${COMMON_FLAGS[@]}" \
        --gpu-memory-utilization 0.90 \
        --max-num-seqs 64 \
        --enable-prefix-caching \
        --enable-chunked-prefill
    ;;

  awq)
    # ── AWQ int4: quantized weights + prefix caching ──────────────────────────
    #
    # AWQ reduces model weight memory from ~14GB (fp16) to ~4-5GB (int4),
    # freeing ~9GB of VRAM for the KV cache. Larger KV cache = more prefix
    # blocks = higher cache hit rate on long correction chains.
    echo "Mode: AWQ INT4 (quantized + prefix caching)"
    echo "Model: $MODEL_AWQ"
    python -m vllm.entrypoints.openai.api_server \
        --model "$MODEL_AWQ" \
        "${COMMON_FLAGS[@]}" \
        --quantization awq \
        --gpu-memory-utilization 0.92 \
        --max-num-seqs 128 \
        --enable-prefix-caching \
        --enable-chunked-prefill
    ;;

  gptq)
    # ── GPTQ int4: alternative quantization ──────────────────────────────────
    echo "Mode: GPTQ INT4 (quantized + prefix caching)"
    echo "Model: $MODEL_GPTQ"
    python -m vllm.entrypoints.openai.api_server \
        --model "$MODEL_GPTQ" \
        "${COMMON_FLAGS[@]}" \
        --quantization gptq \
        --gpu-memory-utilization 0.92 \
        --max-num-seqs 128 \
        --enable-prefix-caching \
        --enable-chunked-prefill
    ;;

  *)
    echo "ERROR: Unknown mode '$MODE'"
    echo "Usage: GPU_ARCH={instinct|radeon} $0 {fp16|fp16-optimized|awq|gptq}"
    exit 1
    ;;
esac
