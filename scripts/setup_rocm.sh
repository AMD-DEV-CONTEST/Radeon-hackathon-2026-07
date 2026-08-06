#!/bin/bash
# scripts/setup_rocm.sh — ROCm env one-click setup (gfx1100 remote container)
#
# Usage:
#   bash scripts/setup_rocm.sh
#
# Prerequisites: ROCm 6.x pre-installed on container, Python 3.12
#
# Key design: Uses PIP_CONSTRAINT + constraints.txt protection
#   to ensure future pip install cannot override ROCm torch with CUDA version
#
# Monitoring features (provided by _lib.sh):
#   - Each step prints start/end time and elapsed time
#   - pip install operations print a heartbeat every 30 seconds (shows log size and last line)
#   - Auto-terminates on timeout and prints the recent log
#   - Prints the step elapsed-time summary table at the end of the script
set -e
export LANG=en_US.UTF-8
export LC_ALL=en_US.UTF-8

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# load the shared utility library (step timing, heartbeat monitoring, timeout protection)
source "$SCRIPT_DIR/_lib.sh"

# detect the ROCm version to decide the installation strategy
ROCM_HIP_VERSION=$(hipcc --version 2>/dev/null | grep "HIP version" | head -1 | sed 's/.*: *//' | cut -d. -f1-2)
ROCM_MAJOR=$(echo "$ROCM_HIP_VERSION" | cut -d. -f1)
if [ "$ROCM_MAJOR" -ge 7 ] 2>/dev/null; then
    estimate_total 10 25 "10-25 minutes (prebuilt wheel installation, no source compilation)"
else
    estimate_total 25 55 "25-55 minutes (building vLLM from source takes longer)"
fi

# trap: print the total elapsed time regardless of success/failure/interruption
_finish() {
    local exit_code=$?
    script_summary
    echo ""
    if [ $exit_code -eq 0 ]; then
        echo "  setup_rocm.sh completed, total time: $(script_total_time)"
    else
        echo "  setup_rocm.sh exited abnormally (code=$exit_code), ran for: $(script_total_time)"
    fi
}
trap _finish EXIT

# ════════════════════════════════════════════════════════
# Step 0: create the virtual environment
# ════════════════════════════════════════════════════════
step_start "Step 0: create virtual environment" "estimated <10s"
if [ ! -d "venv" ]; then
    python3.12 -m venv venv
else
    echo "  venv already exists, skipping creation"
fi
source venv/bin/activate
VENV_DIR="${VIRTUAL_ENV:-venv}"
VENV_ACTIVATE="${VENV_DIR}/bin/activate"
step_end

# ════════════════════════════════════════════════════════
# Step 1: verify the ROCm environment
# ════════════════════════════════════════════════════════
step_start "Step 1: verify ROCm environment (pre-installed)" "estimated <5s"
rocm-smi --showproductname
rocminfo --version
step_end

# ════════════════════════════════════════════════════════
# Step 2: clean up the existing CUDA PyTorch ecosystem
# Estimated time: <30s
# ════════════════════════════════════════════════════════
step_start "Step 2: clean up existing CUDA PyTorch ecosystem" "estimated <30s"
pip uninstall -y torch torchvision torchaudio || true
pip uninstall -y triton pytorch-triton pytorch-triton-xpu || true
pip uninstall -y cuda-toolkit cuda-bindings cuda-pathfinder || true
pip uninstall -y nvidia-cudnn-cu13 nvidia-cusparselt-cu13 nvidia-nccl-cu13 nvidia-nvshmem-cu13 || true
pip uninstall -y nvidia-cublas nvidia-cuda-runtime nvidia-cufft nvidia-cufile nvidia-cuda-cupti || true
pip uninstall -y nvidia-curand nvidia-cusolver nvidia-cusparse nvidia-nvjitlink nvidia-cuda-nvrtc nvidia-nvtx || true

# Remove torch_c_dlpack_ext (CUDA-only, causes libtorch_cuda.so error on ROCm)
pip uninstall -y torch_c_dlpack_ext || true

# Remove torchcodec (CUDA-only, requires libnvrtc.so.13; sentence_transformers
# imports it for audio/video modality but text embedding doesn't need it)
pip uninstall -y torchcodec || true

# Remove residual triton namespace directory (causes AttributeError on ROCm)
TRITON_DIR="${VIRTUAL_ENV:-venv}/lib/python3.12/site-packages/triton"
if [ -d "$TRITON_DIR" ]; then
    echo "Removing residual triton namespace: $TRITON_DIR"
    rm -rf "$TRITON_DIR"
fi
echo "Cleaned"
step_end

# ════════════════════════════════════════════════════════
# Step 3: install the PyTorch ecosystem
# ROCm >= 7.0: skip! The prebuilt vLLM wheel bundles torch 2.11.0, installed in Step 5
# ROCm < 7.0: install torch 2.9.1+rocm6.3 (required for building vLLM from source)
# ════════════════════════════════════════════════════════
if [ "$ROCM_MAJOR" -ge 7 ] 2>/dev/null; then
step_start "Step 3: skip torch install (ROCm >= 7.0, prebuilt wheel bundles torch)" "estimated <5s"
echo "  ROCm $ROCM_HIP_VERSION >= 7.0, prebuilt vLLM wheel bundles torch 2.11.0"
echo "  skipping the torch 2.9.1+rocm6.3 install to avoid version conflicts"
echo "  torch will be installed with the prebuilt wheel in Step 5 (rebuild_vllm_rocm.sh)"
step_end
else
step_start "Step 3: install ROCm PyTorch ecosystem (estimated 3-8 minutes)" "estimated 3-8 minutes"
echo "  Note: download torch+vision+audio+triton from the PyTorch ROCm index"
echo "  --no-deps: prevent pip from pulling CUDA nvidia dependencies"
pip_install_watch \
    "pip install torch==2.9.1+rocm6.3 torchvision==0.24.1+rocm6.3 torchaudio==2.9.1+rocm6.3 pytorch-triton-rocm==3.5.1 --index-url https://download.pytorch.org/whl/rocm6.3 --no-cache-dir --no-deps"

# Clean any CUDA packages that might have been pulled in
pip uninstall -y triton pytorch-triton pytorch-triton-xpu || true
pip uninstall -y nvidia-cudnn-cu13 nvidia-cusparselt-cu13 nvidia-nccl-cu13 nvidia-nvshmem-cu13 || true
pip uninstall -y nvidia-cublas nvidia-cuda-runtime nvidia-cufft nvidia-cufile nvidia-cuda-cupti || true
pip uninstall -y nvidia-curand nvidia-cusolver nvidia-cusparse nvidia-nvjitlink nvidia-cuda-nvrtc nvidia-nvtx || true

# Remove residual triton namespace directory
TRITON_DIR="${VIRTUAL_ENV:-venv}/lib/python3.12/site-packages/triton"
if [ -d "$TRITON_DIR" ] && ! python -c "import triton; triton.__version__" 2>/dev/null; then
    echo "Removing broken triton namespace: $TRITON_DIR"
    rm -rf "$TRITON_DIR"
    pip install pytorch-triton-rocm==3.5.1 \
        --index-url https://download.pytorch.org/whl/rocm6.3 \
        --no-cache-dir --no-deps
fi
step_end
fi

# ════════════════════════════════════════════════════════
# Step 4: install vLLM (ROCm native) — must be done before requirements.txt!
# ROCm >= 7.0: prebuilt wheel (vLLM 0.26.0+rocm723, bundles torch 2.11.0)
# ROCm < 7.0: build from source (PYTORCH_ROCM_ARCH=gfx1100)
#
# Root cause: the vLLM on PyPI is a CUDA-compiled build, so vllm._C is not available on ROCm.
#   Causes: AttributeError: '_C' object has no attribute 'silu_and_mul'
#
# Order note: the vLLM prebuilt wheel bundles torch 2.11.0+rocm and must be installed first.
#   If requirements.txt is installed first, sentence-transformers pulls the CUDA torch
#   (~2.5GB download), then the vLLM wheel replaces it, causing torch to be installed twice.
# ════════════════════════════════════════════════════════
if [ "$ROCM_MAJOR" -ge 7 ] 2>/dev/null; then
step_start "Step 4: install prebuilt vLLM 0.26.0+rocm723 wheel" "estimated 5-15 minutes"
echo "  Note: ROCm >= 7.0, using the prebuilt wheel (bundles torch 2.11.0)"
echo "  vllm._C is natively compiled, all _C operators available, no source compilation needed"
else
step_start "Step 4: build vLLM 0.26.0 from source (ROCm native compilation)" "estimated 15-40 minutes"
echo "  Note: clone vLLM v0.26.0 from GitHub, compile HIP kernels with the gfx1100 architecture"
echo "  after compilation the vllm._C module is natively available, no _C operator patches needed"
fi
echo ""

# call the standalone build script
bash "$SCRIPT_DIR/rebuild_vllm_rocm.sh"

step_end

# ════════════════════════════════════════════════════════
# Step 5: install the project dependencies
# Estimated time: 1-3 minutes
# At this point torch is already installed by the vLLM prebuilt wheel (torch 2.11.0+rocm),
# so sentence-transformers in requirements.txt will not pull the CUDA torch.
# ════════════════════════════════════════════════════════
step_start "Step 5: install project dependencies (estimated 1-3 minutes)" "estimated 1-3 minutes"
pip_install_watch "pip install -r requirements.txt"
step_end

# ════════════════════════════════════════════════════════
# Step 5.5: install amdsmi (required for vLLM ROCm platform detection)
# Estimated time: <10s
# ════════════════════════════════════════════════════════
step_start "Step 5.5: install amdsmi (required for vLLM ROCm platform detection)" "estimated <10s"
if ! python -c "import amdsmi" 2>/dev/null; then
    echo "amdsmi not installed. Searching ROCm installation..."
    AMD_SMI_DIR=""
    for dir in /opt/rocm/share/amd_smi /opt/rocm/share/amd-smi /opt/amd/share/amd_smi; do
        if [ -f "$dir/setup.py" ] || [ -f "$dir/pyproject.toml" ]; then
            AMD_SMI_DIR="$dir"
            break
        fi
    done
    if [ -n "$AMD_SMI_DIR" ]; then
        echo "Installing amdsmi from: $AMD_SMI_DIR"
        pip install "$AMD_SMI_DIR" || {
            echo "WARNING: Failed to install amdsmi from $AMD_SMI_DIR"
            echo "vLLM will fail with 'Failed to infer device type' without amdsmi."
        }
    else
        echo "WARNING: amdsmi source not found in common ROCm paths."
        echo "Try: find /opt -name 'setup.py' -path '*amd*smi*' 2>/dev/null"
    fi
else
    echo "amdsmi already installed"
fi
step_end

# ════════════════════════════════════════════════════════
# Step 6: create the pip constraints file (permanent protection)
# Uses the dynamically detected torch version, compatible with both the prebuilt wheel (torch 2.11.0) and source build (torch 2.9.1)
# ════════════════════════════════════════════════════════
step_start "Step 6: create pip constraints file" "estimated <5s"
CONSTRAINTS_FILE="${VENV_DIR}/constraints.txt"

# dynamically get the currently installed torch and vLLM versions
CURRENT_TORCH=$(python -c "import torch; print(torch.__version__)" 2>/dev/null || echo "unknown")
CURRENT_VLLM=$(python -c "import vllm; print(vllm.__version__)" 2>/dev/null || echo "unknown")
echo "  current torch: $CURRENT_TORCH"
echo "  current vLLM: $CURRENT_VLLM"

cat > "$CONSTRAINTS_FILE" << EOF
# pip constraints - pin ROCm PyTorch ecosystem, prevent CUDA override
# Generated by: setup_rocm.sh
# torch: ${CURRENT_TORCH}
# vLLM: ${CURRENT_VLLM}
torch==${CURRENT_TORCH}
EOF

# if vLLM is installed, pin its version
if [ "$CURRENT_VLLM" != "unknown" ]; then
    echo "vllm==${CURRENT_VLLM}" >> "$CONSTRAINTS_FILE"
fi

# prevent CUDA-only packages from being installed (these cause errors on ROCm)
# note: do not block triton — the vLLM prebuilt wheel bundles a ROCm-compatible triton dependency;
#   blocking triton causes uv/pip resolution conflicts and takes very long
cat >> "$CONSTRAINTS_FILE" << 'EOF'
torch_c_dlpack_ext==0.0.0
torchcodec==0.0.0
EOF

echo "Created: $CONSTRAINTS_FILE"
cat "$CONSTRAINTS_FILE"
step_end

# ════════════════════════════════════════════════════════
# Step 7: write environment variables into venv/bin/activate
# ════════════════════════════════════════════════════════
step_start "Step 7: write env vars into venv/bin/activate" "estimated <5s"
if [ -f "$VENV_ACTIVATE" ]; then
    if grep -q "ROCM_PIP_LOCK_BEGIN" "$VENV_ACTIVATE"; then
        sed -i '/# ROCM_PIP_LOCK_BEGIN/,/# ROCM_PIP_LOCK_END/d' "$VENV_ACTIVATE"
    fi
    cat >> "$VENV_ACTIVATE" << 'ROCM_LOCK'

# ROCM_PIP_LOCK_BEGIN - prevent pip from overriding ROCm torch with CUDA version
export PIP_CONSTRAINT="${VIRTUAL_ENV}/constraints.txt"
# ROCM_PIP_LOCK_END
ROCM_LOCK

    # Always replace ROCM_ENV block to ensure LD_LIBRARY_PATH is present
    if grep -q "ROCM_ENV_BEGIN" "$VENV_ACTIVATE"; then
        sed -i '/# ROCM_ENV_BEGIN/,/# ROCM_ENV_END/c\
\
# ROCM_ENV_BEGIN - gfx1100 ROCm env vars\
export LD_LIBRARY_PATH="${LD_LIBRARY_PATH:-}:/opt/rocm/lib:/opt/rocm/lib64"  # amdsmi needs ROCm libs\
export HSA_OVERRIDE_GFX_VERSION=11.0.0\
export ROCBLAS_USE_HIPBLASLT=1\
export HIP_VISIBLE_DEVICES=0\
export PYTHONPATH="${PYTHONPATH:-}:'"$SCRIPT_DIR"'"  # patch_vllm_source.py + sitecustomize.py\
# ROCM_ENV_END' "$VENV_ACTIVATE"
    else
        cat >> "$VENV_ACTIVATE" << ROCM_ENV

# ROCM_ENV_BEGIN - gfx1100 ROCm env vars
export LD_LIBRARY_PATH="\${LD_LIBRARY_PATH:-}:/opt/rocm/lib:/opt/rocm/lib64"  # amdsmi needs ROCm libs
export HSA_OVERRIDE_GFX_VERSION=11.0.0
export ROCBLAS_USE_HIPBLASLT=1
export HIP_VISIBLE_DEVICES=0
export PYTHONPATH="${PYTHONPATH:-}:$SCRIPT_DIR"  # patch_vllm_source.py + sitecustomize.py
# ROCM_ENV_END
ROCM_ENV
    fi
    echo "Written env vars to $VENV_ACTIVATE"
fi

# Apply now
export PIP_CONSTRAINT="${VENV_DIR}/constraints.txt"
export HSA_OVERRIDE_GFX_VERSION=11.0.0
export LD_LIBRARY_PATH="${LD_LIBRARY_PATH:-}:/opt/rocm/lib:/opt/rocm/lib64"
step_end

# ════════════════════════════════════════════════════════
# Step 8: verify the ROCm PyTorch ecosystem
# ════════════════════════════════════════════════════════
step_start "Step 8: verify ROCm PyTorch ecosystem" "estimated 10-30s"
python -c "
import torch
print(f'torch version: {torch.__version__}')
print(f'HIP version: {torch.version.hip}')
print(f'cuda available: {torch.cuda.is_available()}')
if torch.cuda.is_available():
    print(f'GPU: {torch.cuda.get_device_name(0)}')
    x = torch.randn(100, 100, device='cuda')
    y = torch.matmul(x, x)
    print(f'GPU tensor test passed: result shape={y.shape}')

    # Verify torchvision (ROCm-compatible)
    try:
        import torchvision
        print(f'torchvision: {torchvision.__version__}')
    except Exception as e:
        print(f'WARNING: torchvision import failed: {e}')

    # Verify torchaudio (ROCm-compatible)
    try:
        import torchaudio
        print(f'torchaudio: {torchaudio.__version__}')
    except Exception as e:
        print(f'WARNING: torchaudio import failed: {e}')

    # Verify triton (ROCm-compatible pytorch-triton-rocm)
    try:
        import triton
        print(f'triton: {triton.__version__}')
    except Exception as e:
        print(f'WARNING: triton import failed: {e}')

    # Verify amdsmi (required for vLLM ROCm platform detection)
    try:
        import amdsmi
        print(f'amdsmi: imported successfully')
    except Exception as e:
        print(f'WARNING: amdsmi import failed: {e}')
        print('  vLLM will fail without amdsmi. Install from /opt/rocm/share/amd_smi/')

    print('PyTorch ROCm ecosystem verified')
else:
    print('ERROR: ROCm/GPU not available')
    exit(1)
"
step_end

# ════════════════════════════════════════════════════════
# Step 8.5: torch compatibility patch (only get_memory_info, needed for torch < 2.10)
# ════════════════════════════════════════════════════════
step_start "Step 8.5: check torch compatibility patch" "estimated <10s"
# vLLM 0.26.0 calls torch.accelerator.get_memory_info() (a torch 2.10+ API).
# The prebuilt wheel bundles torch 2.11.0 (has this API), no patch needed.
# The source build uses torch 2.9.1 (no such API), a patch is needed.
NEEDS_MEM_PATCH=$(python -c "
try:
    torch.accelerator.get_memory_info
    print('no')
except AttributeError:
    print('yes')
" 2>/dev/null || echo "yes")

if [ "$NEEDS_MEM_PATCH" = "yes" ]; then
    echo "  patch needed: torch.accelerator.get_memory_info unavailable (torch < 2.10)"
    if [ -f "$SCRIPT_DIR/patch_vllm_source.py" ]; then
        python "$SCRIPT_DIR/patch_vllm_source.py" || {
            echo "  WARNING: the patch script has warnings, but startup should still work"
        }
    else
        echo "  WARNING: patch_vllm_source.py does not exist"
    fi
else
    echo "  torch.accelerator.get_memory_info available, no patch needed"
fi
step_end

# ════════════════════════════════════════════════════════
# Step 9: final verification
# ════════════════════════════════════════════════════════
step_start "Step 9: final verification" "estimated <10s"
python -c "
import torch
import faiss
import numpy
print(f'torch={torch.__version__}, hip={torch.version.hip}, cuda={torch.cuda.is_available()}')

# agently may not have a __version__ attribute; fall back to importlib.metadata
try:
    import agently
    try:
        agently_ver = agently.__version__
    except AttributeError:
        import importlib.metadata as md
        agently_ver = md.version('Agently')
    print(f'agently={agently_ver}')
except ImportError:
    print(f'agently=MISSING')

print(f'faiss={faiss.__version__}')
print(f'numpy={numpy.__version__}')
try:
    import amdsmi
    print(f'amdsmi=OK (vLLM ROCm platform detection enabled)')
except ImportError:
    print(f'amdsmi=MISSING (vLLM will fail! Install from /opt/rocm/share/amd_smi/)')

# Check vLLM _C module (should be natively compiled from source build)
try:
    import vllm
    import vllm._C
    print(f'vllm._C=OK (ROCm native, vLLM {vllm.__version__})')
except ImportError:
    print(f'vllm._C=MISSING (run: bash scripts/rebuild_vllm_rocm.sh)')

# Check key _C operators (must be after import vllm._C)
try:
    _ = torch.ops._C.silu_and_mul
    _ = torch.ops._C.rms_norm
    print(f'vllm._C.silu_and_mul+rms_norm=OK (native ROCm operators)')
except (AttributeError, RuntimeError):
    print(f'vllm._C operators=MISSING (run: bash scripts/rebuild_vllm_rocm.sh)')

print()
print('=== Setup complete ===')
print()
print('Protection layers in place:')
print('  1. constraints.txt pins torch + vLLM (dynamic version)')
print('  2. PIP_CONSTRAINT auto-applies constraint')
print('  3. vLLM ROCm native (vllm._C natively compiled)')
if 'get_memory_info' not in dir(torch.accelerator):
    print('  4. patch_vllm_source.py: get_memory_info compatibility (torch < 2.10)')
print()
print('Next steps:')
print('  1. source venv/bin/activate  # load env vars')
print('  2. bash scripts/download_models.sh  # download models')
print('  3. bash scripts/start_vllm.sh  # start vLLM')
print()
print('If vLLM still fails with _C operator errors:')
print('  bash scripts/rebuild_vllm_rocm.sh  # rebuild from source')
print()
"
step_end
