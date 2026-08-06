#!/bin/bash
# scripts/fix_rocm_torch.sh — fix torch to the ROCm version (compatible with the prebuilt wheel)
#
# Important change:
#   If the vLLM 0.26.0+rocm723 prebuilt wheel (bundling torch 2.11.0) is already installed,
#   this script does not downgrade torch; it only verifies that the current installation is correct.
#
#   The fix is performed only when torch is a CUDA version (no HIP).
#
# Usage:
#   source venv/bin/activate
#   bash scripts/fix_rocm_torch.sh
#
set -e
export LANG=en_US.UTF-8
export LC_ALL=en_US.UTF-8

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$SCRIPT_DIR/_lib.sh" ]; then
    source "$SCRIPT_DIR/_lib.sh"
else
    _SCRIPT_START_TIME=$(date +%s)
    _STEP_START_TIME=""
    _STEP_NAME=""
    declare -a _SUMMARY_NAMES=()
    declare -a _SUMMARY_TIMES=()
    declare -a _SUMMARY_ESTIMATES=()
    declare -a _SUMMARY_STATUS=()
    step_start() {
        _STEP_NAME="$1"; _STEP_ESTIMATE="${2:-unknown}"; _STEP_START_TIME=$(date +%s)
        local now=$(date '+%Y-%m-%d %H:%M:%S')
        echo ""; echo "┌──────────────────────────────────────────────────────────"
        echo "│ [$now] START: $_STEP_NAME"; echo "│ Estimated time: $_STEP_ESTIMATE"
        echo "└──────────────────────────────────────────────────────────"
    }
    step_end() {
        local now_epoch=$(date +%s); local now=$(date '+%Y-%m-%d %H:%M:%S')
        local elapsed=$((now_epoch - _STEP_START_TIME)); local mins=$((elapsed / 60)); local secs=$((elapsed % 60))
        echo ""; echo "┌──────────────────────────────────────────────────────────"
        echo "│ [$now] DONE: $_STEP_NAME"; echo "│ Actual time: ${mins}m ${secs}s"
        echo "└──────────────────────────────────────────────────────────"
        _SUMMARY_NAMES+=("$_STEP_NAME"); _SUMMARY_TIMES+=("${mins}m ${secs}s")
        _SUMMARY_ESTIMATES+=("$_STEP_ESTIMATE"); _SUMMARY_STATUS+=("OK")
    }
    step_fail() {
        local now_epoch=$(date +%s); local elapsed=$((now_epoch - _STEP_START_TIME))
        local mins=$((elapsed / 60)); local secs=$((elapsed % 60))
        _SUMMARY_NAMES+=("$_STEP_NAME"); _SUMMARY_TIMES+=("${mins}m ${secs}s")
        _SUMMARY_ESTIMATES+=("$_STEP_ESTIMATE"); _SUMMARY_STATUS+=("FAIL")
    }
    estimate_total() { echo ""; echo "║  Estimated total time: ${3:-${1}-${2} minutes}"; }
    script_total_time() {
        local now_epoch=$(date +%s); local elapsed=$((now_epoch - _SCRIPT_START_TIME))
        local mins=$(( (elapsed % 3600) / 60 )); local secs=$((elapsed % 60))
        echo "${mins}m ${secs}s"
    }
    script_summary() {
        echo ""; echo "╔═══════════════════════════════════════════════════════════"
        echo "║  fix_rocm_torch.sh step elapsed-time summary"
        echo "╠═══════════════════════════════════════════════════════════"
        local i=0
        for idx in "${!_SUMMARY_NAMES[@]}"; do
            printf "║  %-3s %-45s %-12s %s\n" "$((i+1))" "${_SUMMARY_NAMES[$idx]}" "${_SUMMARY_TIMES[$idx]}" "${_SUMMARY_STATUS[$idx]}"
            i=$((i+1))
        done
        echo "║  Total time: $(script_total_time)"
        echo "╚═══════════════════════════════════════════════════════════"
    }
    pip_install_watch() { echo "  Running: $1"; eval "$1"; }
fi

_finish() {
    local exit_code=$?
    if [ $exit_code -ne 0 ]; then step_fail; fi
    script_summary
    echo ""
    if [ $exit_code -eq 0 ]; then
        echo "  fix_rocm_torch.sh complete, total time: $(script_total_time)"
    else
        echo "  fix_rocm_torch.sh exited abnormally (code=$exit_code), ran for: $(script_total_time)"
    fi
}
trap _finish EXIT

estimate_total 1 15 "1-15 minutes (depends on whether a fix is needed)"

VENV_DIR="${VIRTUAL_ENV:-venv}"
VENV_ACTIVATE="${VENV_DIR}/bin/activate"

# ════════════════════════════════════════════════════════
# Step 0: detect the current torch status
# ════════════════════════════════════════════════════════
step_start "Step 0: detect the current torch status" "estimated <10s"

TORCH_INFO=$(python -c "
import torch, json
info = {
    'version': torch.__version__,
    'hip': torch.version.hip,
    'cuda_available': torch.cuda.is_available(),
}
print(json.dumps(info))
" 2>/dev/null || echo '{"version": "not installed", "hip": null, "cuda_available": false}')

TORCH_VERSION=$(echo "$TORCH_INFO" | python -c "import sys, json; print(json.load(sys.stdin)['version'])")
TORCH_HIP=$(echo "$TORCH_INFO" | python -c "import sys, json; print(json.load(sys.stdin)['hip'])")
TORCH_CUDA_OK=$(echo "$TORCH_INFO" | python -c "import sys, json; print(json.load(sys.stdin)['cuda_available'])")

echo "  torch version: $TORCH_VERSION"
echo "  HIP version: $TORCH_HIP"
echo "  cuda available: $TORCH_CUDA_OK"

# detect whether the vLLM prebuilt wheel is installed
VLLM_VERSION=$(python -c "import vllm; print(vllm.__version__)" 2>/dev/null || echo "not installed")
echo "  vLLM version: $VLLM_VERSION"

# detect whether there are NVIDIA CUDA dependencies
HAS_NVIDIA_DEPS=$(python -c "
import importlib.metadata as md
nvidia_pkgs = [d.metadata['Name'] for d in md.distributions() if 'nvidia' in d.metadata['Name'].lower()]
print('yes' if nvidia_pkgs else 'no')
" 2>/dev/null || echo "no")

echo "  NVIDIA CUDA deps: $HAS_NVIDIA_DEPS"

# decide whether a fix is needed
NEEDS_FIX=false
if [ "$TORCH_HIP" = "None" ] || [ -z "$TORCH_HIP" ]; then
    NEEDS_FIX=true
    echo ""
    echo "  ⚠️  torch has no HIP support (CUDA version), a fix is needed"
elif [ "$HAS_NVIDIA_DEPS" = "yes" ]; then
    NEEDS_FIX=true
    echo ""
    echo "  ⚠️  NVIDIA CUDA dependencies detected, cleanup needed"
elif [ "$TORCH_CUDA_OK" = "False" ]; then
    echo ""
    echo "  ⚠️  torch has HIP but the GPU is unavailable; may need to set HSA_OVERRIDE_GFX_VERSION"
    echo "  Try: export HSA_OVERRIDE_GFX_VERSION=11.0.0"
else
    echo ""
    echo "  ✅ torch is already the ROCm version and the GPU is available, no fix needed"
fi

step_end

# ════════════════════════════════════════════════════════
# If torch is already the ROCm version, skip the fix and only do verification and env config
# ════════════════════════════════════════════════════════
if [ "$NEEDS_FIX" = "false" ]; then

step_start "Step 1: torch is already the ROCm version, skipping the fix" "estimated <5s"
echo "  Current torch: $TORCH_VERSION (HIP: $TORCH_HIP)"
echo "  No need to uninstall/reinstall torch"

# If the vLLM prebuilt wheel is present, update constraints to match the current version
if [ "$VLLM_VERSION" != "not installed" ]; then
    echo ""
    echo "  vLLM $VLLM_VERSION detected, updating constraints to match the current version..."
    CONSTRAINTS_FILE="${VENV_DIR}/constraints.txt"
    cat > "$CONSTRAINTS_FILE" << EOF
# pip constraints - pin ROCm PyTorch ecosystem
# Updated by: fix_rocm_torch.sh (pre-built wheel detected)
# vLLM: ${VLLM_VERSION}
# torch: ${TORCH_VERSION}
torch==${TORCH_VERSION}
vllm==${VLLM_VERSION}
EOF
    echo "  Updated: $CONSTRAINTS_FILE"
fi

step_end

else
# ════════════════════════════════════════════════════════
# Fix needed: torch is the CUDA version
# ════════════════════════════════════════════════════════

# Step 1: uninstall the CUDA version
step_start "Step 1: uninstall the CUDA PyTorch ecosystem" "estimated <30s"
pip uninstall -y torch torchvision torchaudio || true
pip uninstall -y triton pytorch-triton pytorch-triton-xpu || true
pip uninstall -y cuda-toolkit cuda-bindings cuda-pathfinder || true
pip uninstall -y nvidia-cudnn-cu13 nvidia-cusparselt-cu13 nvidia-nccl-cu13 nvidia-nvshmem-cu13 || true
pip uninstall -y nvidia-cublas nvidia-cuda-runtime nvidia-cufft nvidia-cufile nvidia-cuda-cupti || true
pip uninstall -y nvidia-curand nvidia-cusolver nvidia-cusparse nvidia-nvjitlink nvidia-cuda-nvrtc nvidia-nvtx || true
pip uninstall -y torch_c_dlpack_ext || true

TRITON_DIR="${VENV_DIR}/lib/python3.12/site-packages/triton"
if [ -d "$TRITON_DIR" ]; then
    echo "Removing residual triton namespace: $TRITON_DIR"
    rm -rf "$TRITON_DIR"
fi
echo "CUDA PyTorch and NVIDIA dependencies cleaned up"
step_end

# Step 2: install the ROCm version of torch
# Prefer the prebuilt vLLM wheel (if ROCm >= 7.0)
step_start "Step 2: install the ROCm version of PyTorch" "estimated 3-8 minutes"

# detect the ROCm version
ROCM_HIP_VERSION=$(hipcc --version 2>/dev/null | grep "HIP version" | head -1 | sed 's/.*: *//' | cut -d. -f1-2)
ROCM_MAJOR=$(echo "$ROCM_HIP_VERSION" | cut -d. -f1)
echo "  ROCm version: $ROCM_HIP_VERSION (major: $ROCM_MAJOR)"

if [ "$ROCM_MAJOR" -ge 7 ] 2>/dev/null; then
    # ROCm >= 7.0: use the prebuilt vLLM wheel (bundles torch 2.11.0)
    echo ""
    echo "  ═══════════════════════════════════════════════════"
    echo "  ROCm $ROCM_HIP_VERSION >= 7.0, using the prebuilt vLLM wheel"
    echo "  This wheel bundles torch 2.11.0, matching ROCm 7.2.x"
    echo "  ═══════════════════════════════════════════════════"
    echo ""

    # temporarily unset constraints
    unset PIP_CONSTRAINT

    # install uv
    pip install uv 2>/dev/null || true

    # use uv to install the prebuilt vLLM wheel
    if command -v uv &>/dev/null; then
        echo "  Installing the vLLM prebuilt wheel with uv..."
        uv pip install vllm \
            --extra-index-url https://wheels.vllm.ai/rocm/ \
            --upgrade \
            --index-strategy unsafe-best-match 2>&1 || {
            echo "  uv install failed, trying pip with a specific version..."
            pip install "vllm==0.26.0+rocm723" \
                --extra-index-url https://wheels.vllm.ai/rocm/ 2>&1 || {
            echo "  pip also failed, trying to extract the wheel URL from the index page..."
            VLLM_WHEEL_URL=$(curl -s https://wheels.vllm.ai/rocm/vllm/ 2>/dev/null | \
                grep -oP 'https://[^"]+vllm-0\.26\.0\+rocm723[^"]+\.whl' | head -1)
            if [ -n "$VLLM_WHEEL_URL" ]; then
                VLLM_WHEEL_URL=$(echo "$VLLM_WHEEL_URL" | sed 's/%2B/+/g')
                echo "  Wheel URL: $VLLM_WHEEL_URL"
                pip install "$VLLM_WHEEL_URL" 2>&1
            else
                echo "  ERROR: could not obtain the vLLM wheel URL"
                echo "  Run manually: bash scripts/rebuild_vllm_rocm.sh"
                exit 1
            fi
            }
        }
    else
        pip install "vllm==0.26.0+rocm723" \
            --extra-index-url https://wheels.vllm.ai/rocm/ 2>&1 || {
        echo "  pip install failed, trying to extract the wheel URL from the index page..."
        VLLM_WHEEL_URL=$(curl -s https://wheels.vllm.ai/rocm/vllm/ 2>/dev/null | \
            grep -oP 'https://[^"]+vllm-0\.26\.0\+rocm723[^"]+\.whl' | head -1)
        if [ -n "$VLLM_WHEEL_URL" ]; then
            VLLM_WHEEL_URL=$(echo "$VLLM_WHEEL_URL" | sed 's/%2B/+/g')
            echo "  Wheel URL: $VLLM_WHEEL_URL"
            pip install "$VLLM_WHEEL_URL" 2>&1
        else
            echo "  ERROR: could not obtain the vLLM wheel URL"
            echo "  Run manually: bash scripts/rebuild_vllm_rocm.sh"
            exit 1
        fi
        }
    fi

    # get the actually installed versions
    NEW_TORCH_VER=$(python -c "import torch; print(torch.__version__)" 2>/dev/null || echo "unknown")
    NEW_VLLM_VER=$(python -c "import vllm; print(vllm.__version__)" 2>/dev/null || echo "unknown")
    echo "  Installed: torch $NEW_TORCH_VER, vLLM $NEW_VLLM_VER"

else
    # ROCm < 7.0: install torch 2.9.1+rocm6.3
    echo ""
    echo "  ROCm $ROCM_HIP_VERSION < 7.0, installing torch 2.9.1+rocm6.3"
    echo ""

    pip install torch==2.9.1+rocm6.3 \
        torchvision==0.24.1+rocm6.3 \
        torchaudio==2.9.1+rocm6.3 \
        pytorch-triton-rocm==3.5.1 \
        --index-url https://download.pytorch.org/whl/rocm6.3 \
        --no-cache-dir \
        --force-reinstall \
        --no-deps

    NEW_TORCH_VER="2.9.1+rocm6.3"
    NEW_VLLM_VER=$(python -c "import vllm; print(vllm.__version__)" 2>/dev/null || echo "not installed")
fi

step_end

# Step 3: create constraints
step_start "Step 3: create the pip constraints file" "estimated <5s"
CONSTRAINTS_FILE="${VENV_DIR}/constraints.txt"
cat > "$CONSTRAINTS_FILE" << EOF
# pip constraints - pin ROCm PyTorch ecosystem
# Updated by: fix_rocm_torch.sh
# torch: ${NEW_TORCH_VER}
# vLLM: ${NEW_VLLM_VER}
torch==${NEW_TORCH_VER}
EOF

# If vLLM is installed, also pin it
if [ "$NEW_VLLM_VER" != "not installed" ]; then
    echo "vllm==${NEW_VLLM_VER}" >> "$CONSTRAINTS_FILE"
fi

# Prevent CUDA-only packages from being installed
# Note: do not block triton — the vLLM prebuilt wheel bundles a ROCm-compatible triton dependency
cat >> "$CONSTRAINTS_FILE" << 'EOF'
torch_c_dlpack_ext==0.0.0
EOF

echo "Created: $CONSTRAINTS_FILE"
step_end

fi
# ════════════════════════════════════════════════════════
# The following steps run on both paths
# ════════════════════════════════════════════════════════

# Step 4: write environment variables into venv/bin/activate
step_start "Step 4: write environment variables into venv/bin/activate" "estimated <5s"
if [ -f "$VENV_ACTIVATE" ]; then
    # PIP_LOCK block
    if grep -q "ROCM_PIP_LOCK_BEGIN" "$VENV_ACTIVATE"; then
        sed -i '/# ROCM_PIP_LOCK_BEGIN/,/# ROCM_PIP_LOCK_END/d' "$VENV_ACTIVATE"
    fi
    cat >> "$VENV_ACTIVATE" << 'ROCM_LOCK'

# ROCM_PIP_LOCK_BEGIN - prevent pip from overriding ROCm torch
export PIP_CONSTRAINT="${VIRTUAL_ENV}/constraints.txt"
# ROCM_PIP_LOCK_END
ROCM_LOCK
    echo "  Written PIP constraint config"

    # ROCM_ENV block
    if grep -q "ROCM_ENV_BEGIN" "$VENV_ACTIVATE"; then
        sed -i '/# ROCM_ENV_BEGIN/,/# ROCM_ENV_END/c\
\
# ROCM_ENV_BEGIN - gfx1100 ROCm env vars\
export LD_LIBRARY_PATH="${LD_LIBRARY_PATH:-}:/opt/rocm/lib:/opt/rocm/lib64"\
export HSA_OVERRIDE_GFX_VERSION=11.0.0\
export ROCBLAS_USE_HIPBLASLT=1\
export HIP_VISIBLE_DEVICES=0\
export PYTHONPATH="${PYTHONPATH:-}:'"$SCRIPT_DIR"'"\
# ROCM_ENV_END' "$VENV_ACTIVATE"
    else
        cat >> "$VENV_ACTIVATE" << ROCM_ENV

# ROCM_ENV_BEGIN - gfx1100 ROCm env vars
export LD_LIBRARY_PATH="\${LD_LIBRARY_PATH:-}:/opt/rocm/lib:/opt/rocm/lib64"
export HSA_OVERRIDE_GFX_VERSION=11.0.0
export ROCBLAS_USE_HIPBLASLT=1
export HIP_VISIBLE_DEVICES=0
export PYTHONPATH="\${PYTHONPATH:-}:$SCRIPT_DIR"
# ROCM_ENV_END
ROCM_ENV
    fi
    echo "  Written ROCm env vars"
else
    echo "  WARNING: $VENV_ACTIVATE not found"
fi

# Apply now
export PIP_CONSTRAINT="${VENV_DIR}/constraints.txt"
export HSA_OVERRIDE_GFX_VERSION=11.0.0
export LD_LIBRARY_PATH="${LD_LIBRARY_PATH:-}:/opt/rocm/lib:/opt/rocm/lib64"
step_end

# Step 5: install amdsmi
step_start "Step 5: install amdsmi" "estimated <10s"
if ! python -c "import amdsmi" 2>/dev/null; then
    echo "  amdsmi not installed. Searching ROCm installation..."
    AMD_SMI_DIR=""
    for dir in /opt/rocm/share/amd_smi /opt/rocm/share/amd-smi /opt/amd/share/amd_smi; do
        if [ -f "$dir/setup.py" ] || [ -f "$dir/pyproject.toml" ]; then
            AMD_SMI_DIR="$dir"
            break
        fi
    done
    if [ -n "$AMD_SMI_DIR" ]; then
        echo "  Installing from: $AMD_SMI_DIR"
        pip install "$AMD_SMI_DIR" || echo "  WARNING: amdsmi install failed"
    else
        echo "  WARNING: amdsmi source not found"
        echo "  Try: find /opt -name 'setup.py' -path '*amd*smi*' 2>/dev/null"
    fi
else
    echo "  amdsmi already installed"
fi
step_end

# Step 6: verify
step_start "Step 6: verify the ROCm PyTorch ecosystem" "estimated 10-30s"
export HSA_OVERRIDE_GFX_VERSION=11.0.0
python -c "
import torch
print(f'torch version: {torch.__version__}')
print(f'HIP version: {torch.version.hip}')
print(f'cuda available: {torch.cuda.is_available()}')

if torch.cuda.is_available():
    print(f'GPU: {torch.cuda.get_device_name(0)}')
    x = torch.randn(100, 100, device='cuda')
    y = torch.matmul(x, x)
    print(f'GPU tensor test passed: shape={y.shape}')

    # Check vLLM
    try:
        import vllm
        print(f'vLLM: {vllm.__version__}')
        import vllm._C
        print('vllm._C: OK (ROCm native)')
    except ImportError as e:
        print(f'vLLM: not available ({e})')

    # Check amdsmi
    try:
        import amdsmi
        print('amdsmi: OK')
    except ImportError:
        print('amdsmi: MISSING (vLLM will fail!)')

    # Check NVIDIA deps
    try:
        import importlib.metadata as md
        nvidia_pkgs = [d.metadata['Name'] for d in md.distributions() if 'nvidia' in d.metadata['Name'].lower()]
        if nvidia_pkgs:
            print(f'WARNING: NVIDIA deps remain: {nvidia_pkgs[:3]}')
        else:
            print('No NVIDIA deps remaining')
    except:
        pass

    print()
    print('=== Verification PASSED ===')
else:
    print('ERROR: ROCm GPU not available')
    print('Debug:')
    print('  1. ls /dev/kfd /dev/dri/render*')
    print('  2. groups  # should include render,video')
    print('  3. export HSA_OVERRIDE_GFX_VERSION=11.0.0')
    exit(1)
"
step_end

# Step 7: Summary
step_start "complete" "estimated <5s"
echo "========================================"
echo "=== fix_rocm_torch.sh complete ==="
echo "========================================"
echo ""
echo "torch: $(python -c 'import torch; print(torch.__version__)' 2>/dev/null)"
echo "vLLM:  $(python -c 'import vllm; print(vllm.__version__)' 2>/dev/null || echo 'not installed')"
echo ""
echo "Environment variables written into venv/bin/activate"
echo "Constraints: ${VENV_DIR}/constraints.txt"
echo ""
echo "Next steps:"
echo "  source venv/bin/activate"
echo "  bash scripts/start_vllm.sh"
step_end