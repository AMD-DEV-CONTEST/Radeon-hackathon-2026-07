#!/bin/bash
set -e

if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi

export HF_HUB_OFFLINE=1

echo "================================================="
echo "🛡️ WARDEN GPU BENCHMARK SUITE (ROCm)"
echo "================================================="

# --- Step 0: Auto-tune ROCm env vars for the detected GPU (MI250 / MI300X / RX) ---
# This prints the auto-detected caps the benchmark below will actually
# use. On AMD Cloud, judges see a one-line probe → no manual config.
if command -v rocm-smi >/dev/null 2>&1; then
    echo "[Step 0] Detecting GPU + applying tuned ROCm env vars..."
    eval "$(python scripts/tune_rocm.py 2>/dev/null | grep -E '^export ')"
    echo "  GPU: ${WARDEN_TUNED_GPU_NAME:-(unknown)}"
    echo "  GPU_MAX_HEAP_SIZE=${GPU_MAX_HEAP_SIZE:-}"
else
    echo "[Step 0] rocm-smi not found — using default ROCm heap caps."
fi
echo ""

# --- Step 0b: Host kernel tuning (swappiness, hugepages, fd limit) ---
# Only meaningful on a bare-metal AMD Cloud droplet. Inside docker the
# container inherits the host's swappiness/hugepages anyway, so running
# it once on the host before the benchmark catches both contexts.
if [ -x scripts/tune_system.sh ]; then
    echo "[Step 0b] Applying host kernel tuning (vm.swappiness, THP, ulimit)..."
    sudo scripts/tune_system.sh --apply 2>/dev/null || true
fi
echo ""

# --- Step 0c: rocBLAS tuning-cache warmup ---
# llama.cpp autotunes rocBLAS GEMM kernels on first use per shape and
# caches the winner in ~/.cache/rocblas. Without a warmup, the first
# real prompt pays that autotune cost INSIDE the telemetry window,
# inflating the measured latency/joules. Prime the cache before the
# measurement starts so the window sees steady-state performance.
echo "[Step 0c] Warming rocBLAS tuning cache (GEMM autotune)..."
if command -v rocblas-bench >/dev/null 2>&1; then
    # fp16 GEMMs: the shapes llama.cpp uses for prompt-eval (prefill) + decode
    rocblas-bench -f gemm -m 4096 -n 4096 -k 4096 --a_type f16_r --b_type f16_r --c_type f16_r --compute_type f16_r >/dev/null 2>&1 || true
    rocblas-bench -f gemm -m 1024 -n 1024 -k 1024 --a_type f16_r --b_type f16_r --c_type f16_r --compute_type f16_r >/dev/null 2>&1 || true
    echo "  rocBLAS tuning cache primed."
else
    echo "  rocblas-bench not found — skipping (llama.cpp will autotune in-window)."
fi
echo ""

# Start the power and telemetry measurement in the background
echo "Starting GPU telemetry monitoring concurrently with workloads..."
python benchmarks/measure_power.py --output benchmarks/results/adaptive_routing_telemetry.csv --duration 300 --interval 100 &
TELEMETRY_PID=$!
echo ""

# --- Step 1b: LLM phase-split benchmark (prefill vs decode + cache hit/miss) ---
# Streams Tier 2 generations with cache_prompt off then on, reporting the
# prefill/decode phase split (tokens/s per phase) and the cache speedup.
# Skips gracefully (exit 0) when no model/llama.cpp is available.
echo "[Step 1b] LLM phase-split benchmark (prefill/decode + cache hit/miss)..."
python benchmarks/llm_phase_benchmark.py --runs 2 2>&1 | tee benchmarks/results/llm_phase_benchmark.console.txt
echo ""

# --- Step 2: Enterprise attack-corpus evaluation (precision/recall/F1) ---
# Sweeps all 210 samples from attack_samples_v2/ through the Warden
# router, computes per-family P/R/F1 + overall confusion matrix.
echo "[Step 2] Running attack-corpus evaluation (210 samples, 13 families)..."
python scripts/eval_attacks.py \
    --corpus attack_samples_v2/manifest.jsonl \
    --out-dir benchmarks/results \
    --label attack_eval 2>&1 | tee benchmarks/results/attack_eval.console.txt
echo ""

# --- Step 3: Red-team mutation testing (drift vs baseline) ---
# Generates 200 attack variants via deterministic mutators (base64, zwsp,
# homoglyph, paraphrase, payload-swap), sweeps them, reports drift
# vs the Step 2 baseline.
echo "[Step 3] Red-team mutation testing (200 mutants, seed=42)..."
python scripts/red_team.py \
    --corpus attack_samples_v2/manifest.jsonl \
    --baseline benchmarks/results/attack_eval.json \
    --out-dir benchmarks/results \
    --n 200 --seed 42 \
    --label red_team 2>&1 | tee benchmarks/results/red_team.console.txt
echo ""

echo "Stopping telemetry monitoring..."
kill $TELEMETRY_PID 2>/dev/null || true
echo "Benchmark complete. Results saved to benchmarks/results/adaptive_routing_telemetry.csv"

echo "================================================="
echo "Full benchmark + red-team flow complete."
echo "  Telemetry:     benchmarks/results/adaptive_routing_telemetry.csv"
echo "  Phase-split:   benchmarks/results/llm_phase_benchmark.json"
echo "  Eval JSON:     benchmarks/results/attack_eval.json"
echo "  Eval CSV:      benchmarks/results/attack_eval.csv"
echo "  Red-team:      benchmarks/results/red_team.json"
echo "  Red-team:      benchmarks/results/red_team.csv"
echo "================================================="
