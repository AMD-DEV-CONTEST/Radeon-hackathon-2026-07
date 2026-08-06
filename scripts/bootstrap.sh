#!/usr/bin/env bash
# Bootstrap a blank AMD GPU server from this repo alone.
#
# Steps:
#   1. Verify OS-level ROCm is already installed (we cannot install it here)
#   2. Install uv if missing
#   3. Create the Python 3.12 venv and install the project
#   4. Download the llama-server binary (ROCm build)
#   5. Download all model weights
#   6. Validate the installation
#
# Usage:
#   BG_PVC=/persistent/BuildGuard-Radeon-backup bash scripts/bootstrap.sh
#
# Override any BG_* variable to match a non-standard layout:
#   BG_PVC=/data/bg BG_VENV=/data/bg/envs/app-py312 bash scripts/bootstrap.sh
#
# Requirements (must be pre-installed at OS level):
#   - ROCm 7.2.1 (amdgpu-install from https://repo.radeon.com/amdgpu-install/)
#   - Python 3.12 (python3.12 on PATH)
#   - curl, git

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"

# ---------------------------------------------------------------------------
# Layout (mirrors server_env.sh defaults)
# ---------------------------------------------------------------------------
export BG_PVC="${BG_PVC:-/persistent/BuildGuard-Radeon-backup}"
export BG_REPO="${BG_REPO:-$REPO_ROOT}"
export BG_ENVS="${BG_ENVS:-$BG_PVC/envs}"
export BG_VENV="${BG_VENV:-$BG_ENVS/app-py312-rocm721}"
export BG_MODELS="${BG_MODELS:-$BG_PVC/models}"
export BG_RUNTIME="${BG_RUNTIME:-$BG_PVC/runtime}"
export BG_LOGS="${BG_LOGS:-$BG_PVC/logs}"
export BG_RUN="${BG_RUN:-$BG_PVC/run}"
export BG_WORKSPACE="${BG_WORKSPACE:-$BG_PVC/workspace}"
export BG_ARTIFACTS="${BG_ARTIFACTS:-$BG_PVC/artifacts}"
export BG_DATASETS="${BG_DATASETS:-$BG_PVC/data}"

HF_MIRROR="${HF_MIRROR:-https://hf-mirror.com}"
TORCH_INDEX="${TORCH_INDEX:-https://download.pytorch.org/whl/rocm7.2.1}"
PYPI_MIRROR="${PYPI_MIRROR:-https://pypi.tuna.tsinghua.edu.cn/simple}"

# llama.cpp ROCm release to download
LLAMA_RELEASE="${LLAMA_RELEASE:-b4407}"
LLAMA_ARCHIVE="llama-${LLAMA_RELEASE}-bin-ubuntu-x64.zip"
LLAMA_URL="https://github.com/ggml-org/llama.cpp/releases/download/${LLAMA_RELEASE}/${LLAMA_ARCHIVE}"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
info()  { printf '\n\e[1;34m==\e[0m \e[1m%s\e[0m\n' "$*"; }
ok()    { printf '  \e[32m✓\e[0m %s\n' "$*"; }
warn()  { printf '  \e[33m!\e[0m %s\n' "$*"; }
die()   { printf '\n\e[1;31mERROR:\e[0m %s\n' "$*" >&2; exit 1; }

hf_download() {
  local repo="$1" remote="$2" dest="$3"
  local url="$HF_MIRROR/$repo/resolve/main/$remote"
  mkdir -p "$(dirname "$dest")"
  if [[ -f "$dest" ]]; then
    ok "EXISTS: $dest"
    return 0
  fi
  echo "  Downloading $(basename "$dest")..."
  curl --fail --location --progress-bar --retry 3 --retry-delay 5 \
    -o "${dest}.tmp" "$url"
  mv "${dest}.tmp" "$dest"
  ok "$dest"
}

hf_download_dir() {
  # Download all files listed in a HuggingFace repo's file list via the API.
  # Falls back gracefully if the API call fails (offline / mirror gap).
  local repo="$1" dest_dir="$2"
  mkdir -p "$dest_dir"
  echo "  Fetching file list for $repo..."
  local file_list
  file_list=$(curl -fsSL "$HF_MIRROR/api/models/$repo" 2>/dev/null \
    | python3 -c "
import json,sys
data=json.load(sys.stdin)
for s in data.get('siblings',[]):
    print(s['rfilename'])
" 2>/dev/null || true)
  if [[ -z "$file_list" ]]; then
    warn "Could not fetch file list for $repo — skipping (re-run after network access)"
    return 0
  fi
  while IFS= read -r fname; do
    hf_download "$repo" "$fname" "$dest_dir/$fname"
  done <<< "$file_list"
}

# ---------------------------------------------------------------------------
# Step 0: Preflight
# ---------------------------------------------------------------------------
info "Preflight checks"

command -v python3.12 >/dev/null 2>&1 || die "python3.12 not found. Install Python 3.12 first."
command -v curl >/dev/null 2>&1       || die "curl not found."
command -v git >/dev/null 2>&1        || die "git not found."

# ROCm check — rocm-smi or amd-smi must be present
if ! command -v rocm-smi >/dev/null 2>&1 && ! command -v amd-smi >/dev/null 2>&1; then
  die "Neither rocm-smi nor amd-smi found. Install ROCm 7.2.1 first:
  https://repo.radeon.com/amdgpu-install/
  sudo apt install amdgpu-dkms rocm"
fi
ok "ROCm tools present"

ROCM_VER=$(rocm-smi --version 2>/dev/null | grep -oP '[\d.]+' | head -1 || \
           amd-smi version 2>/dev/null | grep -oP '[\d.]+' | head -1 || echo "unknown")
ok "ROCm version: $ROCM_VER"

# ---------------------------------------------------------------------------
# Step 1: Create directories
# ---------------------------------------------------------------------------
info "Creating directory layout under $BG_PVC"
mkdir -p "$BG_ENVS" "$BG_MODELS/llm" "$BG_MODELS/vision" \
         "$BG_MODELS/embedding" "$BG_MODELS/reranker" \
         "$BG_RUNTIME/llama.cpp" \
         "$BG_WORKSPACE" "$BG_LOGS" "$BG_RUN" "$BG_ARTIFACTS" "$BG_DATASETS"
ok "Directories ready"

# ---------------------------------------------------------------------------
# Step 2: Install uv
# ---------------------------------------------------------------------------
info "Checking uv"
if ! command -v uv >/dev/null 2>&1 && [[ ! -x "$HOME/.local/bin/uv" ]]; then
  echo "  Installing uv..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
else
  export PATH="$HOME/.local/bin:$PATH"
  ok "uv $(uv --version 2>/dev/null || echo 'present')"
fi

# ---------------------------------------------------------------------------
# Step 3: Create venv and install project
# ---------------------------------------------------------------------------
info "Creating venv at $BG_VENV"

if [[ ! -d "$BG_VENV" ]]; then
  uv venv "$BG_VENV" --python python3.12
  ok "venv created"
else
  ok "venv already exists"
fi

PIP="$BG_VENV/bin/pip"
PYTHON="$BG_VENV/bin/python"

info "Installing PyTorch 2.9.1+rocm7.2.1"
if "$PYTHON" -c "import torch; assert '+rocm' in torch.__version__" 2>/dev/null; then
  ok "ROCm PyTorch already installed: $("$PYTHON" -c 'import torch; print(torch.__version__)')"
else
  "$PIP" install --quiet \
    "torch==2.9.1+rocm7.2.1" \
    "torchvision==0.24.1" \
    --index-url "$TORCH_INDEX"
  ok "PyTorch installed: $("$PYTHON" -c 'import torch; print(torch.__version__)')"
fi

info "Installing project dependencies"
"$PIP" install --quiet \
  -e "$BG_REPO/.[amd,pdf,mobileclip]" \
  -c "$BG_REPO/constraints/rocm-7.2.1-py312.txt" \
  --extra-index-url "$PYPI_MIRROR"
ok "Project installed"

# ---------------------------------------------------------------------------
# Step 4: Download llama-server binary
# ---------------------------------------------------------------------------
info "Downloading llama-server (ROCm build, release $LLAMA_RELEASE)"

LLAMA_DIR="$BG_RUNTIME/llama.cpp/rocm-7.2.1/$LLAMA_RELEASE"
LLAMA_BIN="$LLAMA_DIR/llama-server"

if [[ -x "$LLAMA_BIN" ]]; then
  ok "llama-server already present at $LLAMA_BIN"
else
  mkdir -p "$LLAMA_DIR"
  ARCHIVE_PATH="$BG_RUNTIME/$LLAMA_ARCHIVE"
  echo "  Downloading $LLAMA_URL..."
  curl --fail --location --progress-bar --retry 3 --retry-delay 5 \
    -o "$ARCHIVE_PATH" "$LLAMA_URL"
  echo "  Extracting..."
  unzip -q "$ARCHIVE_PATH" -d "$LLAMA_DIR"
  rm "$ARCHIVE_PATH"
  # The zip may nest one level deep; find the binary wherever it landed
  FOUND=$(find "$LLAMA_DIR" -name llama-server -type f | head -1)
  if [[ -z "$FOUND" ]]; then
    die "llama-server not found after extraction. Check $LLAMA_DIR"
  fi
  chmod +x "$FOUND"
  # Move to expected flat location if nested
  if [[ "$FOUND" != "$LLAMA_BIN" ]]; then
    mv "$FOUND" "$LLAMA_BIN"
  fi
  ok "llama-server ready at $LLAMA_BIN"
fi

# ---------------------------------------------------------------------------
# Step 5: Download model weights
# ---------------------------------------------------------------------------
info "Downloading LLM — Qwen3-14B-Q8"
LLM_DIR="$BG_MODELS/llm/qwen3-14b-q8"
hf_download "Qwen/Qwen3-14B-GGUF" "Qwen3-14B-Q8_0.gguf" "$LLM_DIR/Qwen3-14B-Q8_0.gguf"

info "Downloading embedding model — Qwen3-embedding-0.6b"
hf_download_dir "Qwen/Qwen3-Embedding-0.6B" "$BG_MODELS/embedding/qwen3-embedding-0.6b"

info "Downloading reranker model — Qwen3-reranker-0.6b"
hf_download_dir "Qwen/Qwen3-Reranker-0.6B" "$BG_MODELS/reranker/qwen3-reranker-0.6b"

info "Downloading vision models"

# YOLO11-PPE
PPE_DIR="$BG_MODELS/vision/yolo11-ppe"
hf_download "keremberke/yolov8-construction-hardhat-detection" \
  "yolov8m/weights/best.pt" "$PPE_DIR/yolo11m_safety.pt" || \
  warn "YOLO11-PPE not found on mirror — place yolo11m_safety.pt manually at $PPE_DIR/"

# Crack / damage / corrosion models (existing script handles these)
info "Downloading crack/corrosion specialist models"
bash "$SCRIPT_DIR/download_crack_models.sh"

# MobileCLIP2-S0
info "Downloading MobileCLIP2-S0 semantic router"
bash "$SCRIPT_DIR/download_mobileclip2_s0.sh"

# ---------------------------------------------------------------------------
# Step 6: Validate
# ---------------------------------------------------------------------------
info "Validating installation"

"$PYTHON" "$SCRIPT_DIR/verify_rocm_runtime.py" && ok "ROCm runtime OK"
"$PYTHON" "$SCRIPT_DIR/verify_model_inventory.py" "$BG_REPO/configs/competition/models.yaml" \
  && ok "Model inventory OK"
"$BG_VENV/bin/buildguard" validate-config --config "$BG_REPO/configs/competition/app.yaml" \
  && ok "App config OK"

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
printf '\n\e[1;32m✓ Bootstrap complete.\e[0m\n'
cat <<EOF

Next steps:
  1. Start all services:
       BG_PVC=$BG_PVC scripts/start_all.sh

  2. Open SSH tunnel from your local machine:
       ssh -L 18000:127.0.0.1:8000 -L 18501:127.0.0.1:8501 amd -N

  3. Access:
       Streamlit UI  http://localhost:18501
       API           http://localhost:18000
       Swagger       http://localhost:18000/docs

  If any model download failed, re-run with:
       HF_MIRROR=https://hf-mirror.com bash scripts/bootstrap.sh
EOF
