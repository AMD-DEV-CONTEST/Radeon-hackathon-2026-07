#!/bin/bash
# scripts/collect_gpu_evidence.sh — one-click GPU evidence collection
#
# Usage:
#   bash scripts/collect_gpu_evidence.sh
#
# Output directory: docs/benchmarks/logs/
set -e

OUTPUT_DIR="docs/benchmarks/logs"
mkdir -p "$OUTPUT_DIR"

echo "=== Collecting GPU evidence to $OUTPUT_DIR/ ==="

echo "--- GPU model ---"
rocm-smi --showproductname > "$OUTPUT_DIR/gpu_model.txt" 2>&1
cat "$OUTPUT_DIR/gpu_model.txt"

echo "--- ROCm version ---"
rocminfo --version > "$OUTPUT_DIR/rocm_version.txt" 2>&1
cat "$OUTPUT_DIR/rocm_version.txt"

echo "--- GPU detailed info ---"
rocminfo > "$OUTPUT_DIR/rocminfo_full.txt" 2>&1
echo "  (saved rocminfo_full.txt)"

echo "--- GPU running status ---"
rocm-smi > "$OUTPUT_DIR/rocm_smi.txt" 2>&1
cat "$OUTPUT_DIR/rocm_smi.txt"

echo "--- Python environment ---"
{
    echo "Python: $(python --version 2>&1)"
    echo "pip: $(pip --version 2>&1)"
    python -c "import torch; print(f'torch={torch.__version__}, cuda={torch.cuda.is_available()}, hip={torch.version.hip}')" 2>&1 || echo "torch: not installed"
    python -c "import vllm; print(f'vllm={vllm.__version__}')" 2>&1 || echo "vllm: not installed"
} > "$OUTPUT_DIR/python_env.txt" 2>&1
cat "$OUTPUT_DIR/python_env.txt"

echo "--- CPU info ---"
lscpu | grep -E "Model name|CPU\(s\)|Thread" > "$OUTPUT_DIR/cpu_info.txt" 2>&1
cat "$OUTPUT_DIR/cpu_info.txt"

echo "--- Memory info ---"
free -h > "$OUTPUT_DIR/memory_info.txt" 2>&1
cat "$OUTPUT_DIR/memory_info.txt"

echo "=== Evidence collection complete ==="
echo "File list:"
ls -la "$OUTPUT_DIR/"
