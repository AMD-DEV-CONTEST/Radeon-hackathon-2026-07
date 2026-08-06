#!/bin/bash
# scripts/fix_vllm_rocm.sh — vLLM ROCm fix bootstrap script
#
# Root cause:
#   The vLLM installed from PyPI is a CUDA-compiled build; the vllm._C module is not available on ROCm.
#   Caused by: AttributeError: '_OpNamespace' '_C' object has no attribute 'silu_and_mul'
#         AttributeError: '_OpNamespace' '_C' object has no attribute 'rms_norm'
#
#   The previous patch approaches (vllm_rocm_ops.py registering Python ops, source patches, etc.)
#   were only stopgaps and cannot cover all vLLM 0.26.0 _C call paths.
#
# Correct approach:
#   Build vLLM from source, compiling HIP/ROCm native kernels with PYTORCH_ROCM_ARCH=gfx1100.
#   This way vllm._C is compiled as the ROCm version and all _C operators are natively available.
#
# vLLM 0.26.0 version notes:
#   - The recommended version for gfx1100 (Radeon RX 7900) (fixes the slow warmup of v0.21-v0.25)
#   - ROCm 6.3 has no prebuilt wheel (only ROCm 7.0/7.2.1 do), so it must be built from source
#   - Official docs: https://docs.vllm.ai/en/latest/getting_started/installation/gpu.html
#
# Usage:
#   source venv/bin/activate
#   bash scripts/fix_vllm_rocm.sh
#
set -e
export LANG=en_US.UTF-8
export LC_ALL=en_US.UTF-8

echo ""
echo "╔═══════════════════════════════════════════════════════════"
echo "║  vLLM ROCm fix tool"
echo "╠═══════════════════════════════════════════════════════════"
echo "║"
echo "║  Problem diagnosis:"
echo "║    PyPI vLLM = CUDA-compiled build → vllm._C not available on ROCm"
echo "║    Symptom: AttributeError: '_C' object has no attribute 'silu_and_mul'"
echo "║          AttributeError: '_C' object has no attribute 'rms_norm'"
echo "║"
echo "║  Why the previous patch approaches did not work:"
echo "║    vllm_rocm_ops.py (Python op registration) → cannot cover all _C call paths"
echo "║    patch_vllm_source.py (source patch) → vLLM 0.26.0 IR scheduling bypasses the patch"
echo "║    vllm_c.py backend disabled → still needs _C ops, pure Python fallback is very slow"
echo "║"
echo "║  Correct approach: build vLLM from source (ROCm native compilation)"
echo "║    PYTORCH_ROCM_ARCH=gfx1100 python setup.py develop"
echo "║    → vllm._C compiled as the ROCm native version, all _C ops natively available"
echo "║    → no _C patches needed, normal performance"
echo "║"
echo "║  vLLM 0.26.0 is the recommended version for gfx1100:"
echo "║    - Fixes the slow warmup of v0.21-v0.25 on Radeon GPUs"
echo "║    - ROCm 6.3 has no prebuilt wheel, source build required"
echo "║    - Prebuilt wheels only support ROCm 7.0 and 7.2.1"
echo "║"
echo "╚═══════════════════════════════════════════════════════════"
echo ""

# check the current vLLM status
echo "=== Current environment check ==="
python -c "
import sys

# Check torch
try:
    import torch
    print(f'torch: {torch.__version__}')
    print(f'HIP: {torch.version.hip}')
    if torch.cuda.is_available():
        print(f'GPU: {torch.cuda.get_device_name(0)}')
except Exception as e:
    print(f'torch: ERROR - {e}')

# Check vLLM
try:
    import vllm
    print(f'vLLM: {vllm.__version__}')
except Exception as e:
    print(f'vLLM: not installed or import error - {e}')

# Check vllm._C (the key indicator)
try:
    import vllm._C
    print(f'vllm._C: OK (ROCm native compilation)')
    print()
    print('vLLM is already built from source. No fix needed.')
    sys.exit(0)
except ImportError:
    print(f'vllm._C: MISSING (CUDA PyPI version, needs rebuild)')
    print()
    print('This is the root cause of all _C operator errors.')
    print('Fix: bash scripts/rebuild_vllm_rocm.sh')
" 2>/dev/null || true

echo ""
echo "╔═══════════════════════════════════════════════════════════"
echo "║  Fix steps:"
echo "║"
echo "║  1. Build vLLM from source (15-40 minutes):"
echo "║     bash scripts/rebuild_vllm_rocm.sh"
echo "║"
echo "║  2. Start vLLM:"
echo "║     bash scripts/start_vllm.sh"
echo "║"
echo "║  If the build fails, check:"
echo "║     hipcc --version        (ROCm compiler)"
echo "║     cmake --version        (requires >= 3.26)"
echo "║     python -c 'import torch; print(torch.__version__, torch.version.hip)'"
echo "║"
echo "╚═══════════════════════════════════════════════════════════"
echo ""

# Ask if user wants to proceed with rebuild
read -p "Run the source build now? (y/N) " -r
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo ""
    echo "Starting the vLLM source build..."
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    bash "$SCRIPT_DIR/rebuild_vllm_rocm.sh"
else
    echo ""
    echo "Run manually: bash scripts/rebuild_vllm_rocm.sh"
fi