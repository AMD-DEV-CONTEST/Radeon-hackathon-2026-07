#!/bin/bash
# MedGlass — one-command environment setup.
#
# * On an AMD GPU / ROCm box: installs ROCm packages, builds whisper.cpp and
#   llama.cpp with hipBLAS, downloads models.
# * On a plain laptop (no GPU, no compiler, no sudo): installs Python deps,
#   `pywhispercpp` (prebuilt CPU wheel) and the YuNet face model, so the full
#   app runs on CPU.
#
# Idempotent: safe to re-run.
# Usage: bash setup.sh
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

echo "==> MedGlass setup"

# --- Python environment ----------------------------------------------------
PYTHON="${PYTHON:-python3}"
$PYTHON -c "import pip" 2>/dev/null || $PYTHON /tmp/get-pip.py --user --break-system-packages >/dev/null 2>&1 || true

install_py() {
    if command -v pipx >/dev/null 2>&1; then
        echo "    (use pipx / venv as you prefer)"
        return
    fi
    VENV_OK=false
    if [ -x .venv/bin/python ] && [ -f .venv/bin/activate ]; then
        # Existing, intact venv (a missing activate script means a half-built
        # one from a pre-ensurepip box; rebuild it below).
        VENV_OK=true
    elif "$PYTHON" -m venv .venv >/dev/null 2>&1 \
        && [ -x .venv/bin/python ] && [ -f .venv/bin/activate ]; then
        VENV_OK=true
    fi
    if [ "$VENV_OK" = true ]; then
        PYTHON=.venv/bin/python
        "$PYTHON" -m pip install --upgrade pip
        "$PYTHON" -m pip install -r requirements.txt
    else
        echo "    venv unavailable (python3-venv missing); using user site (--break-system-packages)"
        "$PYTHON" -m pip install --user --break-system-packages --upgrade pip
        "$PYTHON" -m pip install --user --break-system-packages -r requirements.txt
    fi
}
install_py

# --- ROCm / GPU native builds (only if a compiler is present) --------------
HAVE_CC=false
command -v g++ >/dev/null 2>&1 && command -v make >/dev/null 2>&1 && HAVE_CC=true

if [ "$HAVE_CC" = true ] && command -v rocm-smi >/dev/null 2>&1; then
    echo "==> ROCm detected; building GPU backends"
    sudo apt-get update 2>/dev/null || true
    sudo apt-get install -y --no-install-recommends \
        build-essential cmake clang-21 hipcc hip-utils \
        libamdhip64-dev libhipblas-dev librocblas-dev \
        rocm-device-libs-21 rocm-smi rocminfo python3-venv 2>/dev/null || true

    # Target the local RDNA4 arch (R9700 = gfx1201). Detect it, or fall back.
    AMDGPU_TARGET="$(rocm-smi --showproductname 2>/dev/null \
        | grep -oE 'gfx[0-9]+' | head -1 || true)"
    [ -z "${AMDGPU_TARGET}" ] && AMDGPU_TARGET="gfx1201"
    echo "    AMDGPU_TARGET=${AMDGPU_TARGET}"

    if [ ! -x vendor/whisper.cpp/build/bin/whisper-cli ]; then
        mkdir -p vendor
        test -d vendor/whisper.cpp || git clone --depth 1 \
            https://github.com/ggerganov/whisper.cpp vendor/whisper.cpp
        (cd vendor/whisper.cpp && cmake -B build \
            -DGGML_HIP=ON -DAMDGPU_TARGETS="${AMDGPU_TARGET}" \
            -DCMAKE_BUILD_TYPE=Release -DWHISPER_BUILD_TESTS=OFF && \
            cmake --build build -j"$(nproc)")
    fi
    # Qwen3.6 needs llama.cpp b9180+ (MTP); master is fine.
    if [ ! -x vendor/llama.cpp/build/bin/llama-cli ]; then
        mkdir -p vendor
        test -d vendor/llama.cpp || git clone --depth 1 \
            https://github.com/ggerganov/llama.cpp vendor/llama.cpp
        (cd vendor/llama.cpp && cmake -B build \
            -DGGML_HIP=ON -DAMDGPU_TARGETS="${AMDGPU_TARGET}" \
            -DCMAKE_BUILD_TYPE=Release -DGGML_CUDA=OFF && \
            cmake --build build -j"$(nproc)" --target llama-cli llama-server)
    fi
else
    echo "==> No compiler/ROCm: using prebuilt CPU whisper (pywhispercpp) + template LLM"
    "$PYTHON" -m pip install --user --break-system-packages pywhispercpp 2>/dev/null || \
        "$PYTHON" -m pip install pywhispercpp 2>/dev/null || true
fi

# --- Models ----------------------------------------------------------------
echo "==> Downloading models"
"$PYTHON" scripts/download_models.py whisper || true

echo
echo "==> Setup complete."
echo "    Start the server:  bash scripts/start_server.sh 127.0.0.1 8100"
echo "    Open the web UI:   http://127.0.0.1:8100"
echo "    No-hardware demo:  python3 scripts/run_demo.py"
