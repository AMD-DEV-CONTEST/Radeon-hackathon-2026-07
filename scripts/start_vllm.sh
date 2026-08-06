#!/bin/bash
# scripts/start_vllm.sh — vLLM ROCm startup script (gfx1100 compatible)
#
# Prerequisites:
#   vLLM must be built from source for ROCm (vllm._C natively compiled).
#   If not, run: bash scripts/rebuild_vllm_rocm.sh
#
# This script handles:
#   1. ROCm environment variables (HSA_OVERRIDE_GFX_VERSION, LD_LIBRARY_PATH)
#   2. amdsmi availability (vLLM ROCm platform detection)
#   3. torch_c_dlpack_ext cleanup (CUDA-only package)
#   4. vllm._C availability check (source build verification)
#   5. get_memory_info patch (torch 2.9.1 < 2.10 compatibility)
#   6. GPU availability verification
#   7. vLLM service launch
#
# Usage:
#   source venv/bin/activate
#   bash scripts/start_vllm.sh              # Default: FP16 baseline (C0)
#   bash scripts/start_vllm.sh --int4       # INT4 quantized (C2, batch=8)
#   bash scripts/start_vllm.sh --c3         # INT4 + batch=16 + HIP graph (C3 full optimization)
#   bash scripts/start_vllm.sh --reasoning  # Reasoning model (port 8002)
#
# GPU memory notes (gfx1100, 48GB VRAM):
#   Measured idle VRAM ~42GB, 0.90×48=43.2GB exceeds available space causing OOM.
#   All modes uniformly use GPU_UTIL=0.85 (0.85×48=40.8GB < 42GB).
#
set -e
export LANG=en_US.UTF-8
export LC_ALL=en_US.UTF-8

# ============================================================
# 1. ROCm env vars (must be set before vLLM import)
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── load _lib.sh (if it exists), otherwise use a minimal inline implementation ──
if [ -f "$SCRIPT_DIR/_lib.sh" ]; then
    source "$SCRIPT_DIR/_lib.sh"
else
    _SCRIPT_START_TIME=$(date +%s)
    _STEP_START_TIME=""
    _STEP_NAME=""
    step_start() {
        _STEP_NAME="$1"
        _STEP_START_TIME=$(date +%s)
        local now=$(date '+%Y-%m-%d %H:%M:%S')
        echo ""
        echo "┌──────────────────────────────────────────────────────────"
        echo "│ [$now] START: $_STEP_NAME"
        echo "└──────────────────────────────────────────────────────────"
    }
    step_end() {
        local now_epoch=$(date +%s)
        local now=$(date '+%Y-%m-%d %H:%M:%S')
        local elapsed=$((now_epoch - _STEP_START_TIME))
        local mins=$((elapsed / 60))
        local secs=$((elapsed % 60))
        echo ""
        echo "┌──────────────────────────────────────────────────────────"
        echo "│ [$now] DONE: $_STEP_NAME"
        echo "│ Actual time: ${mins}m ${secs}s"
        echo "└──────────────────────────────────────────────────────────"
    }
    estimate_total() {
        echo ""
        echo "║  Estimated total time: ${3:-${1}-${2} minutes}"
    }
    script_total_time() { echo ""; }
    script_summary() { echo ""; }
fi

# Note: this script finally uses exec to launch the vLLM service, and exec replaces the current process,
# so the trap EXIT will not fire when the vLLM service exits.
# Monitoring only covers the pre-start check phase (Steps 1-5); the vLLM service itself runs indefinitely.
estimate_total 1 3 "1-3 minutes (pre-start checks), then the vLLM service runs continuously"

# CRITICAL: amdsmi needs ROCm shared libraries at runtime.
# Without LD_LIBRARY_PATH, amdsmi import fails even after pip install.
export LD_LIBRARY_PATH="${LD_LIBRARY_PATH:-}:/opt/rocm/lib:/opt/rocm/lib64"

# gfx1100 (RDNA 3) requires this, otherwise GPU is not visible
export HSA_OVERRIDE_GFX_VERSION=11.0.0

# ROCm performance tuning
export ROCBLAS_USE_HIPBLASLT=1          # Enable hipBLASLt (~2x throughput)
export HIP_VISIBLE_DEVICES=0            # Use GPU 0 only

# Clean up env vars that vLLM 0.26.0 doesn't recognize (causes warnings)
unset VLLM_ATTENTION_BACKEND 2>/dev/null || true
unset VLLM_USE_V1 2>/dev/null || true

# Use HIP_VISIBLE_DEVICES instead of CUDA_VISIBLE_DEVICES on ROCm
# (vLLM 0.26.0 warns about CUDA_VISIBLE_DEVICES deprecation on ROCm)
unset CUDA_VISIBLE_DEVICES 2>/dev/null || true

# PYTHONPATH includes scripts/ for sitecustomize.py
# sitecustomize.py is auto-imported at Python startup and contains two critical patches:
#   1. infer_schema patch: accept str subclasses (like LayerName) as str — fixes the LayerName error
#   2. get_memory_info patch: compatibility layer for torch < 2.10
# This patch applies to all Python processes, including vLLM's EngineCore subprocess.
export PYTHONPATH="${SCRIPT_DIR}:${PYTHONPATH:-}"

# Uncomment for debugging
# export VLLM_LOGGING_LEVEL=DEBUG
# export CUDA_LAUNCH_BLOCKING=1

# ============================================================
# 2. Ensure amdsmi is installed (required for vLLM ROCm platform detection)
# ============================================================
step_start "Step 1: check amdsmi (required for vLLM ROCm platform detection)" "estimated <10s"
# vLLM's platform detection imports 'amdsmi' to identify ROCm.
# Without it, no platform is detected -> "Failed to infer device type".
# amdsmi is distributed with ROCm at /opt/rocm/share/amd_smi/
if ! python -c "import amdsmi" 2>/dev/null; then
    echo "WARNING: amdsmi not installed. vLLM cannot detect ROCm platform without it."
    echo "Searching for amdsmi source in ROCm installation..."
    AMD_SMI_DIR=""
    for dir in /opt/rocm/share/amd_smi /opt/rocm/share/amd-smi /opt/amd/share/amd_smi; do
        if [ -f "$dir/setup.py" ] || [ -f "$dir/pyproject.toml" ]; then
            AMD_SMI_DIR="$dir"
            break
        fi
    done
    if [ -n "$AMD_SMI_DIR" ]; then
        echo "Installing amdsmi from: $AMD_SMI_DIR"
        pip install "$AMD_SMI_DIR" 2>/dev/null || {
            echo "ERROR: Failed to install amdsmi. vLLM will fail to start."
            echo "Manual fix: cd $AMD_SMI_DIR && pip install ."
            exit 1
        }
        echo "amdsmi installed successfully"
    else
        echo "ERROR: amdsmi source not found in common ROCm paths."
        echo "Try: find /opt -name 'setup.py' -path '*amd*smi*' 2>/dev/null"
        echo "Or:  pip install amdsmi (if available on PyPI)"
        exit 1
    fi
fi

step_end

# ============================================================
# 3. Pre-start cleanup: remove packages that break ROCm
# ============================================================
step_start "Step 2: clean up incompatible packages (quark + torch_c_dlpack_ext + humming)" "estimated <15s"

# quark (amd-quark): online quantization plugin. vLLM 0.26.0 auto-loads this plugin at startup,
# but the quark import chain triggers the moe_runner.py -> LayerName infer_schema error.
# We do not need online quantization (we use GPTQ offline quantization), so uninstall it to eliminate the error.
if python -c "import quark" 2>/dev/null; then
    echo "  [INFO] quark detected (triggers LayerName error in vLLM 0.26.0). Removing..."
    pip uninstall -y quark amd-quark 2>/dev/null || true
    echo "  [OK] quark removed"
else
    echo "  [OK] quark not installed (skip)"
fi

# torch_c_dlpack_ext: CUDA-only, causes "libtorch_cuda.so not found" error
# Dependency chain: vLLM V1 -> xgrammar -> tvm_ffi -> torch_c_dlpack_ext
if python -c "import torch_c_dlpack_ext" 2>/dev/null; then
    echo "  [INFO] torch_c_dlpack_ext detected (CUDA-only, breaks ROCm). Removing..."
    pip uninstall -y torch_c_dlpack_ext 2>/dev/null || true
    echo "  [OK] torch_c_dlpack_ext removed"
else
    echo "  [OK] torch_c_dlpack_ext not installed (skip)"
fi

# torchcodec: CUDA-only, requires libnvrtc.so.13 (not available on ROCm)
# sentence_transformers imports it for audio/video modality, but text embedding doesn't need it
if python -c "import torchcodec" 2>/dev/null; then
    echo "  [INFO] torchcodec detected (CUDA-only, requires libnvrtc.so.13). Removing..."
    pip uninstall -y torchcodec 2>/dev/null || true
    echo "  [OK] torchcodec removed"
else
    echo "  [OK] torchcodec not installed (skip)"
fi

# humming: CUDA-only optimization package, tries to import cuda.bindings.driver
# which doesn't exist on ROCm. vLLM 0.26.0 tries to import humming during
# EngineCore initialization, causing a warning (non-fatal but noisy).
# Uninstall to avoid the cuda.bindings ModuleNotFoundError.
if python -c "import humming" 2>/dev/null; then
    echo "  [INFO] humming detected (CUDA-only, requires cuda.bindings). Removing..."
    pip uninstall -y humming humming-kernels 2>/dev/null || true
    echo "  [OK] humming removed"
else
    echo "  [OK] humming not installed (skip)"
fi

step_end

# ============================================================
# 4. Fix LayerName infer_schema error (CRITICAL)
# ============================================================
step_start "Step 3: fix LayerName infer_schema error (six-layer fix)" "estimated <15s"
# vLLM 0.26.0 + torch 2.11.0: LayerName (a str subclass) is not recognized by infer_schema.
# This error causes the EngineCore subprocess to crash.
#
# Fix plan (six-layer guarantee): run fix_layername.py
#   Layer A: replace the LayerName class definition with LayerName = str (root fix)
#   Layer B: regex-scan all vLLM .py files, replace LayerName annotations
#   Layer E: fix broken replacements such as strType
#   Layer F: patch the _resolve_layer_name function (fixes the Layer A side effect)
#   Layer C: directly patch torch/_library/infer_schema.py
#   Layer D: enhance torch_utils.py preprocessing (modifies both __annotations__)

FIX_SCRIPT="$SCRIPT_DIR/fix_layername.py"
if [ -f "$FIX_SCRIPT" ]; then
    python "$FIX_SCRIPT"
else
    echo "  [WARN] fix_layername.py does not exist, using the inline patch (four-layer fix)..."

    # inline patch: Layer A — replace the LayerName class definition with LayerName = str
    python -c "
import subprocess, sys, os, re, shutil

# find the vLLM directory
result = subprocess.run([sys.executable, '-m', 'pip', 'show', 'vllm'],
                       capture_output=True, text=True, timeout=30)
vllm_dir = None
for line in result.stdout.split('\n'):
    if line.startswith('Location:'):
        loc = line.split(':', 1)[1].strip()
        cand = os.path.join(loc, 'vllm')
        if os.path.isdir(cand):
            vllm_dir = cand
            break

if not vllm_dir:
    print('  [FAIL] could not find the vLLM directory')
    sys.exit(1)

print(f'  [INFO] vLLM directory: {vllm_dir}')

# Layer A: replace the LayerName class definition with LayerName = str
tu = os.path.join(vllm_dir, 'utils/torch_utils.py')
if os.path.isfile(tu):
    with open(tu) as f: c = f.read()
    if 'LAYERNAME_CLASS_REPLACED' not in c:
        # find the class LayerName(str) definition
        pattern = r'class\s+LayerName\s*\(\s*str\s*(?:,[^)]*)?\s*\)\s*:'
        if re.search(pattern, c):
            c = re.sub(pattern, 'LayerName = str  # LAYERNAME_CLASS_REPLACED', c, count=1)
            with open(tu, 'w') as f: f.write(c)
            print('  [OK] Layer A: class LayerName(str) -> LayerName = str')
        else:
            # force-append at the end of the file
            c += '\n# LAYERNAME_CLASS_REPLACED: fallback\nLayerName = str\n'
            with open(tu, 'w') as f: f.write(c)
            print('  [OK] Layer A: appended LayerName = str at the end (fallback)')
    else:
        print('  [OK] Layer A: already patched (skip)')
else:
    print('  [WARN] torch_utils.py does not exist')

# Layer B: regex-scan all .py files (use \b to avoid mismatching LayerNameType)
count = 0
for root, dirs, files in os.walk(vllm_dir):
    dirs[:] = [d for d in dirs if d != '__pycache__']
    for fname in files:
        if not fname.endswith('.py'): continue
        fpath = os.path.join(root, fname)
        try:
            with open(fpath) as f: c = f.read()
        except: continue
        orig = c
        c = re.sub(r'(\w+\s*:\s*)LayerName\b', r'\1str', c)
        c = re.sub(r'Optional\[LayerName\]', 'Optional[str]', c)
        if c != orig:
            try:
                with open(fpath, 'w') as f: f.write(c)
                count += 1
            except: pass
print(f'  [OK] Layer B: patched {count} files')

# Layer E: fix broken replacements such as strType (caused by the pure string replacement in patch_vllm_source.py)
count = 0
for root, dirs, files in os.walk(vllm_dir):
    dirs[:] = [d for d in dirs if d != '__pycache__']
    for fname in files:
        if not fname.endswith('.py'): continue
        fpath = os.path.join(root, fname)
        try:
            with open(fpath) as f: c = f.read()
        except: continue
        orig = c
        # fix strType (from a partial replacement of LayerNameType)
        c = re.sub(r'\bstrType\b', 'str', c)
        # generic fix: layer_name: strXXX -> layer_name: str
        c = re.sub(r'(layer_name\s*:\s*)str([A-Z]\w*)', r'\1str', c)
        if c != orig:
            try:
                with open(fpath, 'w') as f: f.write(c)
                count += 1
            except: pass
print(f'  [OK] Layer E: fixed strType errors in {count} files')

# Layer F: patch the _resolve_layer_name function
# After Layer A replaces LayerName = str, isinstance(layer_name, LayerName)
# returns True for all strings, causing the layer_name.value access to fail.
# Replace the .value if isinstance pattern with a safe getattr access.
tu = os.path.join(vllm_dir, 'utils/torch_utils.py')
if os.path.isfile(tu):
    with open(tu) as f: c = f.read()
    if 'RESOLVE_LAYERNAME_FIX' not in c:
        orig_pat = r'return\s+layer_name\.value\s+if\s+isinstance\s*\(\s*layer_name\s*,\s*LayerName\s*\)\s+else\s+layer_name'
        m = re.search(orig_pat, c)
        if m:
            orig_code = m.group(0)
            patched = \"return getattr(layer_name, 'value', layer_name)  # RESOLVE_LAYERNAME_FIX\"
            c = c.replace(orig_code, patched, 1)
            with open(tu, 'w') as f: f.write(c)
            print('  [OK] Layer F: _resolve_layer_name patched')
        else:
            loose = r'layer_name\.value\s+if\s+isinstance\s*\(\s*layer_name\s*,\s*LayerName\s*\)'
            m2 = re.search(loose, c)
            if m2:
                orig2 = m2.group(0)
                patched2 = \"getattr(layer_name, 'value', layer_name)  # RESOLVE_LAYERNAME_FIX\"
                c = c.replace(orig2, patched2, 1)
                with open(tu, 'w') as f: f.write(c)
                print('  [OK] Layer F: _resolve_layer_name patched (loose)')
            else:
                print('  [WARN] Layer F: pattern not found')
    else:
        print('  [OK] Layer F: already patched (skip)')

# Layer C: patch torch infer_schema.py
try:
    result2 = subprocess.run([sys.executable, '-m', 'pip', 'show', 'torch'],
                            capture_output=True, text=True, timeout=30)
    torch_dir = None
    for line in result2.stdout.split('\n'):
        if line.startswith('Location:'):
            torch_dir = os.path.join(line.split(':', 1)[1].strip(), 'torch')
            break
    if torch_dir and os.path.isdir(torch_dir):
        is_path = os.path.join(torch_dir, '_library/infer_schema.py')
        if os.path.isfile(is_path):
            with open(is_path) as f: c = f.read()
            if 'INFER_SCHEMA_STR_SUBCLASS_FIX' not in c:
                # dynamically extract the first parameter name of infer_schema
                sig_match = re.search(r'def\s+infer_schema\s*\(\s*(\w+)', c)
                param_name = sig_match.group(1) if sig_match else 'prototype_function'
                func_match = re.search(r'(def\s+infer_schema\s*\([^)]*\)\s*(?:->\s*\S+\s*)?:)', c)
                if func_match:
                    fix = f'''
    # INFER_SCHEMA_STR_SUBCLASS_FIX
    try:
        _anns = getattr({param_name}, '__annotations__', None)
        if _anns:
            _new = {{}}
            _ch = False
            for _k, _v in _anns.items():
                if isinstance(_v, type) and issubclass(_v, str) and _v is not str:
                    _new[_k] = str
                    _ch = True
                else:
                    _new[_k] = _v
            if _ch:
                {param_name}.__annotations__ = _new
    except Exception:
        pass
'''
                    pos = func_match.end()
                    c = c[:pos] + fix + c[pos:]
                    with open(is_path, 'w') as f: f.write(c)
                    print('  [OK] Layer C: infer_schema.py patched')
                else:
                    print('  [WARN] Layer C: infer_schema function definition not found')
            else:
                print('  [OK] Layer C: already patched (skip)')
        else:
            print('  [WARN] Layer C: infer_schema.py does not exist')
    else:
        print('  [WARN] Layer C: torch directory not found')
except Exception as e:
    print(f'  [WARN] Layer C: {e}')

# clean up __pycache__
count = 0
for root, dirs, _ in os.walk(vllm_dir):
    if '__pycache__' in dirs:
        try:
            shutil.rmtree(os.path.join(root, '__pycache__'))
            count += 1
        except: pass
print(f'  [OK] cleaned up {count} __pycache__ directories')
"
fi

# verify the patch
echo "  === Verifying the patch ==="
python -c "
import subprocess, sys, os, re
result = subprocess.run([sys.executable, '-m', 'pip', 'show', 'vllm'],
                       capture_output=True, text=True, timeout=30)
vllm_dir = None
for line in result.stdout.split('\n'):
    if line.startswith('Location:'):
        vllm_dir = os.path.join(line.split(':', 1)[1].strip(), 'vllm')
        break

if vllm_dir and os.path.isdir(vllm_dir):
    # verify Layer A: LayerName = str
    tu = os.path.join(vllm_dir, 'utils/torch_utils.py')
    if os.path.isfile(tu):
        with open(tu) as f: c = f.read()
        if 'LAYERNAME_CLASS_REPLACED' in c or 'LayerName = str' in c:
            print('  [OK] Layer A: torch_utils.py LayerName = str')
        else:
            print('  [FAIL] Layer A: torch_utils.py does not contain LayerName = str')
        # check whether a class LayerName(str) definition still exists
        if re.search(r'^\s*class\s+LayerName\s*\(\s*str', c, re.MULTILINE):
            print('  [FAIL] Layer A: class LayerName(str) definition still exists!')
        else:
            print('  [OK] Layer A: no class LayerName(str) definition')
        # verify Layer F: _resolve_layer_name patched
        if 'RESOLVE_LAYERNAME_FIX' in c:
            print('  [OK] Layer F: _resolve_layer_name patched (getattr)')
        elif re.search(r'layer_name\.value\s+if\s+isinstance\s*\(\s*layer_name\s*,\s*LayerName', c):
            print('  [FAIL] Layer F: _resolve_layer_name not patched (still has .value if isinstance)')
        else:
            print('  [OK] Layer F: _resolve_layer_name has no dangerous pattern')
    else:
        print('  [WARN] torch_utils.py does not exist')

    # verify Layer B: no LayerName annotations
    layername_count = 0
    for root, dirs, files in os.walk(vllm_dir):
        dirs[:] = [d for d in dirs if d != '__pycache__']
        for fname in files:
            if not fname.endswith('.py'): continue
            fpath = os.path.join(root, fname)
            try:
                with open(fpath) as f: c = f.read()
                if re.search(r'\w+\s*:\s*LayerName\b', c):
                    layername_count += 1
            except: pass
    if layername_count == 0:
        print('  [OK] Layer B: no LayerName type annotations')
    else:
        print(f'  [WARN] Layer B: {layername_count} files still have LayerName annotations')

    # verify Layer C: infer_schema.py
    result2 = subprocess.run([sys.executable, '-m', 'pip', 'show', 'torch'],
                            capture_output=True, text=True, timeout=30)
    torch_dir = None
    for line in result2.stdout.split('\n'):
        if line.startswith('Location:'):
            torch_dir = os.path.join(line.split(':', 1)[1].strip(), 'torch')
            break
    if torch_dir and os.path.isdir(torch_dir):
        is_path = os.path.join(torch_dir, '_library/infer_schema.py')
        if os.path.isfile(is_path):
            with open(is_path) as f: c = f.read()
            if 'INFER_SCHEMA_STR_SUBCLASS_FIX' in c:
                print('  [OK] Layer C: infer_schema.py str subclass preprocessing')
            else:
                print('  [WARN] Layer C: infer_schema.py not patched')
        else:
            print('  [WARN] Layer C: infer_schema.py does not exist')
    else:
        print('  [WARN] Layer C: torch directory not found')
else:
    print('  [WARN] could not locate the vLLM directory for verification')
"

step_end

# ============================================================
# 5. Verify vllm._C module
# ============================================================
step_start "Step 4: verify the vllm._C module" "estimated <10s"
echo "=== Checking vllm._C availability ==="
python -c "
import sys

# vllm must be imported first so that the _C extension is loaded and registers torch.ops._C.* operators
try:
    import vllm
    import vllm._C
    print(f'  [OK] vLLM {vllm.__version__} + vllm._C loaded (ROCm native)')
except ImportError as e:
    print(f'  [FAIL] vllm._C not available: {e}')
    print('')
    print('  Fix: bash scripts/rebuild_vllm_rocm.sh')
    sys.exit(1)

import torch
print(f'  [OK] torch {torch.__version__}, HIP {torch.version.hip}')

# Check key _C operators (must be after import vllm._C)
ops_to_check = ['silu_and_mul', 'rms_norm', 'fused_add_rms_norm', 'rotary_embedding']
all_ok = True
for op_name in ops_to_check:
    try:
        getattr(torch.ops._C, op_name)
        print(f'  [OK] torch.ops._C.{op_name}')
    except (AttributeError, RuntimeError) as e:
        print(f'  [FAIL] torch.ops._C.{op_name}')
        all_ok = False

if not all_ok:
    print('')
    print('  Diagnostic: available _C operators:')
    available = [op for op in dir(torch.ops._C) if not op.startswith('_')]
    if available:
        for op in available[:20]:
            print(f'    - {op}')
        if len(available) > 20:
            print(f'    ... and {len(available) - 20} more')
    else:
        print('    (none registered)')
    print('')
    print('  Run: bash scripts/rebuild_vllm_rocm.sh')
    sys.exit(1)

# Check get_memory_info (informational only)
try:
    torch.accelerator.get_memory_info
    print('  [OK] torch.accelerator.get_memory_info available (torch >= 2.10)')
except AttributeError:
    print('  [INFO] get_memory_info not natively available (patched by Patch 1)')

# verify that the LayerName fix is effective (critical test: importing moe_runner does not error)
try:
    from vllm.model_executor.layers.fused_moe.runner import moe_runner
    print('  [OK] moe_runner imported successfully (LayerName fix effective)')
except Exception as e:
    if 'LayerName' in str(e) or 'infer_schema' in str(e):
        print(f'  [FAIL] moe_runner import failed: LayerName error still present!')
        print(f'    Error: {e}')
        sys.exit(1)
    else:
        print(f'  [WARN] moe_runner import failed (not a LayerName error): {e}')

# verify whether LayerName is str
try:
    from vllm.utils.torch_utils import LayerName
    if LayerName is str:
        print('  [OK] LayerName is str (Layer A effective)')
    else:
        print(f'  [WARN] LayerName is {LayerName} (Layer A not effective; relies on Layer C fallback)')
except Exception as e:
    print(f'  [WARN] could not verify the LayerName type: {e}')

print('')
print('  vllm._C verified: all checks passed')
"

if [ $? -ne 0 ]; then
    echo ""
    echo "  ERROR: vllm._C verification failed!"
    echo "  Run: bash scripts/rebuild_vllm_rocm.sh"
    exit 1
fi

step_end

# ============================================================
# 5. Verify GPU availability (fail fast)
# ============================================================
step_start "Step 5: verify ROCm GPU availability" "estimated 10-30s"
echo "=== Verify ROCm GPU ==="
python -c "
import torch
print(f'torch: {torch.__version__}')
print(f'HIP: {torch.version.hip}')
print(f'cuda available: {torch.cuda.is_available()}')
if torch.cuda.is_available():
    print(f'GPU: {torch.cuda.get_device_name(0)}')
    print(f'GPU count: {torch.cuda.device_count()}')
else:
    print('ERROR: GPU not available! Check HSA_OVERRIDE_GFX_VERSION')
    exit(1)
"

step_end

# ============================================================
# 6. Select launch config
# ============================================================
step_start "Step 6: select launch config + check model files" "estimated <5s"
MODEL_DIR="./models"
CHAT_TEMPLATE="$MODEL_DIR/qwen3_nonthinking.jinja"
PORT=8000

# Parse argument
MODE="${1:-baseline}"

case "$MODE" in
    --int4|c2|C2)
        echo "=== Mode: C2 extreme optimization (INT4 GPTQ, batch=8) ==="
        MODEL_PATH="$MODEL_DIR/Qwen3-8B-GPTQ-Int4"
        SERVED_MODEL_NAME="Qwen3-8B"
        QUANT_ARG="--quantization gptq"
        MAX_LEN=4096
        MAX_SEQS=8
        GPU_UTIL=0.85
        EXTRA_ARGS="--enable-prefix-caching"
        EAGER_ARG="--enforce-eager"
        ;;
    --c3|c3|C3)
        echo "=== Mode: C3 full optimization (INT4 + batch=16 + HIP graph) ==="
        echo "  Operator-level optimization: enable HIP/CUDA Graph capture (no --enforce-eager)"
        echo "  Reference: OPTIMIZATION_EXECUTION_PLAN.md sec 3.5 operator-level optimization"
        MODEL_PATH="$MODEL_DIR/Qwen3-8B-GPTQ-Int4"
        SERVED_MODEL_NAME="Qwen3-8B"
        QUANT_ARG="--quantization gptq"
        MAX_LEN=4096
        MAX_SEQS=16
        GPU_UTIL=0.85
        EXTRA_ARGS="--enable-prefix-caching --enable-chunked-prefill"
        EAGER_ARG=""  # no --enforce-eager, enable HIP Graph capture
        ;;
    --reasoning)
        echo "=== Mode: Reasoning model (DeepSeek-R1-Distill) ==="
        MODEL_PATH="$MODEL_DIR/DeepSeek-R1-Distill-Qwen-7B"
        SERVED_MODEL_NAME="deepseek-ai/DeepSeek-R1-Distill-Qwen-7B"
        QUANT_ARG=""
        MAX_LEN=4096
        MAX_SEQS=4
        GPU_UTIL=0.85
        EXTRA_ARGS=""
        EAGER_ARG="--enforce-eager"
        PORT=8002
        CHAT_TEMPLATE=""  # Reasoning model uses default template
        ;;
    baseline|c0|C0|*)
        echo "=== Mode: C0 baseline (FP16) ==="
        MODEL_PATH="$MODEL_DIR/Qwen3-8B"
        SERVED_MODEL_NAME="Qwen3-8B"
        QUANT_ARG=""
        MAX_LEN=8192
        MAX_SEQS=4
        GPU_UTIL=0.85
        EXTRA_ARGS=""
        EAGER_ARG="--enforce-eager"
        ;;
esac

# Ensure non-thinking template exists (only for non-reasoning modes)
if [ -n "$CHAT_TEMPLATE" ] && [ ! -f "$CHAT_TEMPLATE" ]; then
    echo "Downloading qwen3_nonthinking.jinja to $CHAT_TEMPLATE..."
    mkdir -p "$(dirname "$CHAT_TEMPLATE")"
    curl -sL https://qwen.readthedocs.io/en/latest/_downloads/c101120b5bebcc2f12ec504fc93a965e/qwen3_nonthinking.jinja -o "$CHAT_TEMPLATE"
fi

# Check model exists
if [ ! -d "$MODEL_PATH" ]; then
    echo "ERROR: Model dir not found: $MODEL_PATH"
    echo "Run first: bash scripts/download_models.sh"
    exit 1
fi

step_end

# ============================================================
# 7. Start vLLM
# ============================================================
step_start "Step 7: start the vLLM service" "estimated 1-3 minutes (model loading), then runs continuously"
echo "  Note: after the vLLM service starts it runs continuously, this step has no step_end"
echo "  Expected startup sequence: load model -> compile kernel -> start API server"
echo "  First startup is slow; subsequent runs are faster with prefix caching"
echo ""
echo "=== Starting vLLM ==="
echo "Model:          $MODEL_PATH"
echo "Served name:    $SERVED_MODEL_NAME"
echo "Port:           $PORT"
echo "Quant:          ${QUANT_ARG:-none}"
echo "MaxLen:         $MAX_LEN"
echo "MaxSeqs:        $MAX_SEQS"
echo "GPU util:       $GPU_UTIL"
echo "Eager:          ${EAGER_ARG:--enforce-eager (default)}"
if [ -z "$EAGER_ARG" ]; then
    echo "  -> HIP Graph capture enabled (operator-level optimization)"
fi
echo ""

# Build chat-template arg (reasoning model doesn't use non-thinking template)
TEMPLATE_ARG=""
if [ -n "$CHAT_TEMPLATE" ] && [ -f "$CHAT_TEMPLATE" ]; then
    TEMPLATE_ARG="--chat-template $CHAT_TEMPLATE"
fi

# --served-model-name: MUST match the model name in configs/models.toml.
#   Without this, vLLM uses the --model path (e.g. ./models/Qwen3-8B) as the
#   API model name, but Agently client sends "Qwen3-8B" from models.toml,
#   causing "model not found" errors.
#
# --device 0: now that amdsmi is installed, vLLM detects ROCm platform.
#   ROCm platform expects integer device IDs, not "cuda" string.
#
# --enforce-eager: disable CUDA/HIP graph compilation.
#   C0/C2/--reasoning: keep --enforce-eager (more stable ROCm compatibility)
#   C3 (--c3):         remove --enforce-eager, enable HIP Graph capture (operator-level optimization A)
#                      Reference: OPTIMIZATION_EXECUTION_PLAN.md sec 3.5 operator-level optimization
exec python -m vllm.entrypoints.openai.api_server \
    --model "$MODEL_PATH" \
    --served-model-name "$SERVED_MODEL_NAME" \
    --device 0 \
    --dtype bfloat16 \
    --max-model-len $MAX_LEN \
    --max-num-seqs $MAX_SEQS \
    --gpu-memory-utilization $GPU_UTIL \
    $EAGER_ARG \
    $QUANT_ARG \
    $TEMPLATE_ARG \
    $EXTRA_ARGS \
    --port $PORT
