#!/bin/bash
# scripts/run_benchmark.sh — run performance benchmark comparison experiments
#
# Usage:
#   bash scripts/run_benchmark.sh C0    # baseline: FP16, single concurrency
#   bash scripts/run_benchmark.sh C1    # moderate: INT8, concurrency 4
#   bash scripts/run_benchmark.sh C2    # extreme: INT4, concurrency 8
#   bash scripts/run_benchmark.sh C3    # full: INT4, concurrency 16
#   bash scripts/run_benchmark.sh C4    # large VRAM: FP16, concurrency 16
#
# Prerequisite: the vLLM service has been started with the matching config
set -e

CONFIG="${1:-C0}"
OUTPUT_DIR="docs/benchmarks"
mkdir -p "$OUTPUT_DIR/logs"

echo "=== Running benchmark: $CONFIG ==="

# record the vLLM startup log (if present)
if curl -s http://localhost:8000/v1/models > /dev/null 2>&1; then
    echo "vLLM service is available"
else
    echo "Error: vLLM service is not running (http://localhost:8000)"
    echo "Please start vLLM with the $CONFIG config first:"
    echo "  See docs/DEPLOYMENT.md section 2.1"
    exit 1
fi

# collect the GPU status snapshot
echo "--- Collecting GPU status before the test ---"
rocm-smi > "$OUTPUT_DIR/logs/${CONFIG}_gpu_before.txt" 2>&1

# run the RAG retrieval benchmark
echo "--- Running the RAG retrieval benchmark ---"
python scripts/benchmark_rag.py 2>&1 | tee "$OUTPUT_DIR/logs/${CONFIG}_rag_benchmark.log"

# collect the GPU status snapshot
echo "--- Collecting GPU status after the test ---"
rocm-smi > "$OUTPUT_DIR/logs/${CONFIG}_gpu_after.txt" 2>&1

# collect VRAM usage
echo "--- Collecting VRAM usage ---"
rocm-smi --showmeminfo vram > "$OUTPUT_DIR/logs/${CONFIG}_vram_usage.txt" 2>&1

# collect GPU utilization
echo "--- Collecting GPU utilization ---"
rocm-smi --showuse > "$OUTPUT_DIR/logs/${CONFIG}_gpu_util.txt" 2>&1

echo ""
echo "=== Benchmark $CONFIG completed ==="
echo "Log files:"
ls -la "$OUTPUT_DIR/logs/${CONFIG}"*