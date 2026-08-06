# Model Introduction & Local Deployment Plan (Model Intro & Local Deployment Plan)

> Meets the official requirements: model selection rationale, quantization strategy, inference backend, ROCm dependencies, startup method, offline reproducibility

---

## Part 1: Model Selection

### 1.1 Chat LLM: Qwen3-8B (main model)

| Dimension | Description |
|------|------|
| Model | Qwen3-8B |
| Parameter count | 7B |
| Context length | 131072 (trimmed to 4096-8192 at deployment) |
| Reason for selection | AMD ROCm official workshop benchmark model (first choice for gfx1100 optimization); thinking/non-thinking modes switchable, balancing fast response with deep reasoning; 128K context suitable for long insurance documents; C-Eval 78-82, MATH 90 (thinking mode) |
| Quantization strategy | FP16 (baseline) → INT8 → INT4 (GPTQ/AWQ), see ROCm_OPTIMIZATION.md |
| License | Apache 2.0 |

### 1.2 Reasoning-Enhanced Model: DeepSeek-R1-Distill-Qwen-7B

| Dimension | Description |
|------|------|
| Model | deepseek-ai/DeepSeek-R1-Distill-Qwen-7B |
| Parameter count | 7B |
| Context length | 4096 (trimmed during distillation) |
| Reason for selection | SOTA in mathematical reasoning (MATH-500 92.8, AIME 55.5%); recommended by the AMD official blog for deployment on Radeon GPU; transparent and auditable CoT chain-of-thought |
| Applicable scenarios | Subtasks requiring deep thinking, such as complex claims calculations, policy comparison analysis, logical reasoning |
| Deployment port | 8002 (independent of the main model's 8000) |
| Quantization strategy | FP16 (baseline), optional AWQ INT4 |

> The main model Qwen3-8B already has a built-in thinking mode; the reasoning-enhanced model serves as an optional independent service, invoked only when extremely deep reasoning is needed.

### 1.3 Embedding Model: BGE-M3

| Dimension | Description |
|------|------|
| Model | BAAI/bge-m3 |
| Vector dimension | 1024 |
| Reason for selection | Multilingual support (mixed Chinese/English documents); 1024 dimensions balance recall accuracy and index efficiency; supports dense retrieval + sparse retrieval + multi-vector retrieval |
| Deployment method | Local deployment, exposed via an OpenAI Compatible API (port 8001) |
| Quantization strategy | FP16 (embedding models are precision-sensitive; quantization is not recommended) |

### 1.4 Model Acquisition

```bash
# Method 1: HuggingFace download (requires internet)
# Note: use the hf command (huggingface-cli is deprecated)
pip install huggingface-hub
hf download Qwen/Qwen3-8B --local-dir ./models/Qwen3-8B
hf download BAAI/bge-m3 --local-dir ./models/bge-m3 --exclude "*.DS_Store" "imgs/*"

# Reasoning-enhanced model
hf download deepseek-ai/DeepSeek-R1-Distill-Qwen-7B --local-dir ./models/DeepSeek-R1-Distill-Qwen-7B

# Cross-Encoder reranking model
hf download BAAI/bge-reranker-base --local-dir ./models/bge-reranker-base

# Method 2: ModelScope download (more stable on domestic networks)
pip install modelscope
modelscope download --model Qwen/Qwen3-8B --local_dir ./models/Qwen3-8B
modelscope download --model BAAI/bge-m3 --local_dir ./models/bge-m3

# Method 3: GPTQ quantized model
# Note: Qwen3-8B-GPTQ-Int4 has no pre-built version; it must be generated via local quantization
# Run: python scripts/quantize_gptq.py (quantize from the FP16 source model)
# Or use the download_models.sh script (with a built-in SKIP_QUANTIZE flag)
```

### 1.5 RAG Data Processing Dependencies

| Dependency package | Version | Purpose | Required |
|--------|------|------|------|
| python-docx | >=1.1.0 | Word (.docx) document parsing | Required for Word documents |
| beautifulsoup4 | >=4.12.0 | HTML document parsing | Required for HTML documents |
| rank-bm25 | >=0.2.2 | BM25 sparse retrieval (hybrid retrieval) | Required for hybrid retrieval |
| sentence-transformers | >=2.7.0 | Cross-Encoder reranking model loading | Required for reranking |
| jieba | >=0.42.1 | Chinese word segmentation (optimizes BM25 effectiveness) | Recommended |

> All dependencies are included in `requirements.txt`; install all at once with `pip install -r requirements.txt`.
> When a non-essential dependency is missing, the system degrades gracefully (only skips the corresponding feature, without affecting the core flow).

---

## Part 2: Inference Backend

### 2.1 vLLM (ROCm build) — Main Inference Backend

| Configuration item | Value | Description |
|--------|------|------|
| Version | vLLM 0.6.x+ (ROCm build) | The ROCm-specific version must be installed |
| Port | 8000 | OpenAI Compatible API |
| Model | Qwen3-8B | Uses the locally quantized version for INT4 comparison (`./models/Qwen3-8B-GPTQ-Int4`) |
| dtype | bfloat16 | ROCm recommends bf16 (natively supported by gfx1100) |
| max-model-len | 4096-8192 | Adjusted per experiment configuration |
| --device | cuda | **Must be specified explicitly** to bypass vLLM's automatic device detection (automatic detection fails on gfx1100) |
| PyTorch ecosystem | torch + torchvision + torchaudio + pytorch-triton-rocm | **All four must be ROCm versions**; otherwise, on vLLM import, transformers triggers a crash with the CUDA versions of torchvision/torchaudio |

> **Important**: on gfx1100 (RDNA 3), vLLM reports `RuntimeError: Failed to infer device type`.
> Root cause: vLLM's `DeviceConfig.__post_init__` calls `current_platform.device_type` to auto-detect the device;
> if `HSA_OVERRIDE_GFX_VERSION` is not set or is not in the activated venv environment, the GPU is not visible and detection fails.
> Solution: use the `scripts/start_vllm.sh` launch script, which automatically sets all required environment variables and adds `--device 0`.
>
> **PyTorch ecosystem compatibility**: `pip install vllm` automatically pulls the CUDA versions of torch/torchvision/torchaudio/triton,
> overwriting the installed ROCm versions. You must run `scripts/fix_rocm_torch.sh` or `scripts/setup_rocm.sh` to fix this.
> That script uses a `PIP_CONSTRAINT` triple-protection mechanism to lock the ROCm versions and prevent future `pip install` from overwriting them again.
>
> **torch_c_dlpack_ext issue**: the vLLM V1 engine loads the structured-output backend through the dependency chain
> `xgrammar -> tvm_ffi -> torch_c_dlpack_ext`. `torch_c_dlpack_ext` is a CUDA-only package and cannot find `libtorch_cuda.so` on ROCm.
> Both `fix_rocm_torch.sh` and `start_vllm.sh` automatically uninstall this package, and `tvm_ffi` falls back to its built-in DLPack support.
>
> **get_memory_info compatibility issue**: vLLM 0.26.0 calls `torch.accelerator.get_memory_info()` (a PyTorch 2.10+ API),
> but ROCm 6.3 only provides torch 2.9.1. The `sitecustomize.py` monkey-patch works in the main process, but the EngineCore
> child process created by vLLM via `spawn` does not inherit this patch. `patch_vllm_source.py` directly modifies the vLLM source files,
> ensuring the patch is applied in all processes. `start_vllm.sh`, `fix_rocm_torch.sh`, and `setup_rocm.sh` apply this patch automatically.
> After reinstalling vLLM, you must re-run `python scripts/patch_vllm_source.py`.

#### Method 1: Use the launch script (recommended)

```bash
source venv/bin/activate

# C0 baseline: FP16, non-thinking mode
bash scripts/start_vllm.sh              # default C0, port 8000

# C2 extreme optimization: INT4 GPTQ + concurrency 8 + prefix caching
bash scripts/start_vllm.sh --int4       # port 8000

# Reasoning-enhanced model: DeepSeek-R1-Distill
bash scripts/start_vllm.sh --reasoning  # port 8002
```

#### Method 2: Manual startup (all environment variables must be set manually)

```bash
# === Environment variables that MUST be set (otherwise vLLM startup fails) ===
# Prerequisite: install amdsmi (required for vLLM ROCm platform detection; if missing, "Failed to infer device type")
cd /opt/rocm/share/amd_smi && pip install .
export LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/opt/rocm/lib:/opt/rocm/lib64  # amdsmi runtime dependency
export HSA_OVERRIDE_GFX_VERSION=11.0.0  # gfx1100 (RDNA 3) compatibility, required!
export ROCBLAS_USE_HIPBLASLT=1          # enables hipBLASLt, roughly 2x throughput improvement
export HIP_VISIBLE_DEVICES=0            # restricts to GPU 0
export VLLM_USE_V1=1                    # vLLM V1 engine
export VLLM_ATTENTION_BACKEND=FLASH_ATTN # ROCm Flash Attention

# C0 baseline: FP16, non-thinking mode
curl -sL https://qwen.readthedocs.io/en/latest/_downloads/c101120b5bebcc2f12ec504fc93a965e/qwen3_nonthinking.jinja > qwen3_nonthinking.jinja
python -m vllm.entrypoints.openai.api_server \
    --model ./models/Qwen3-8B \
    --device 0 \
    --dtype bfloat16 \
    --max-model-len 8192 \
    --chat-template ./qwen3_nonthinking.jinja \
    --gpu-memory-utilization 0.85 \
    --port 8000

# C2 extreme optimization: INT4 + concurrency 8 + PagedAttention + short context
# Note: quantization must be run first: python scripts/quantize_gptq.py
python -m vllm.entrypoints.openai.api_server \
    --model ./models/Qwen3-8B-GPTQ-Int4 \
    --device 0 \
    --quantization gptq \
    --dtype bfloat16 \
    --max-model-len 4096 \
    --max-num-seqs 8 \
    --gpu-memory-utilization 0.90 \
    --enable-prefix-caching \
    --chat-template ./qwen3_nonthinking.jinja \
    --port 8000

# Reasoning-enhanced model (port 8002)
python -m vllm.entrypoints.openai.api_server \
    --model ./models/DeepSeek-R1-Distill-Qwen-7B \
    --device 0 \
    --dtype bfloat16 \
    --max-model-len 4096 \
    --max-num-seqs 4 \
    --gpu-memory-utilization 0.85 \
    --port 8002
```

### 2.2 Embedding Service

Use `text-embeddings-inference` or a simple Flask wrapper around BGE-M3:

```bash
# Method 1: text-embeddings-inference (recommended)
text-embeddings-router --model ./models/bge-m3 --port 8001

# Method 2: custom Flask service
python -c "
from sentence_transformers import SentenceTransformer
from flask import Flask, request, jsonify
app = Flask(__name__)
model = SentenceTransformer('./models/bge-m3')
@app.post('/v1/embeddings')
def embed():
    data = request.json
    vecs = model.encode(data['input']).tolist()
    return jsonify({'data': [{'embedding': v, 'index': i} for i, v in enumerate(vecs)]})
app.run(port=8001)
"
```

### 2.3 llama.cpp (for comparison experiments)

```bash
# Compile the ROCm version
git clone https://github.com/ggerganani/llama.cpp
cd llama.cpp && make GGML_HIPBLAS=1

# Start the server
./server -m ./models/Qwen3-8B-Q4_K_M.gguf \
    --port 8080 \
    -ngl 99 \
    -c 4096
```

---

## Part 3: ROCm Environment Dependencies

### 3.1 Actual Runtime Environment (verified)

> The following is the environment information actually collected from the remote container, collected on 2026-07-27. See [GPU_ENVIRONMENT.md](./GPU_ENVIRONMENT.md) for details.

| Component | Actual value | Description |
|------|--------|------|
| Host | `u-7666-c69eaa0a` (Radeon Cloud) | Remote container |
| GPU | AMD Radeon Graphics (gfx1100) | RDNA 3 architecture |
| VRAM | 48 GB | Ample, can run FP16 7B or even 14B |
| CU | 96 | Number of compute units |
| ROCm | 6.16.13 (kernel) / HSA 1.18 | Relatively new version |
| CPU | 2× AMD EPYC 9334 (64 cores) | Dual-socket |
| Memory | ~504 GB | System memory |
| Python | 3.12 (system) | A virtual environment must be created |
| PyTorch ecosystem | torch 2.9.1+rocm6.3 / torchvision 0.24.1+rocm6.3 / torchaudio 2.9.1+rocm6.3 / pytorch-triton-rocm 3.5.1 | Not pre-installed; the ROCm full suite must be installed |
| vLLM | Not pre-installed; must be installed | ROCm version |

### 3.2 Environment Verification Commands

```bash
# 1. Verify GPU visibility
rocm-smi --showproductname
# Expected: AMD Radeon Graphics, gfx1100

# 2. Verify the ROCm version
rocminfo --version
# Expected: ROCk 6.16.13, HSA Runtime 1.18

# 3. Verify the PyTorch ROCm ecosystem (after installation)
python -c "
import torch
print(f'torch: {torch.__version__}')
print(f'HIP: {torch.version.hip}')
print(f'cuda available: {torch.cuda.is_available()}')
import torchvision; print(f'torchvision: {torchvision.__version__}')
import torchaudio; print(f'torchaudio: {torchaudio.__version__}')
import triton; print(f'triton: {triton.__version__}')
"
# Expected: torch=2.9.1+rocm6.3, HIP=6.x, cuda=True, torchvision=0.24.1+rocm6.3, torchaudio=2.9.1+rocm6.3, triton=3.5.1

# 4. Verify vLLM (after installation)
python -c "import vllm; print(vllm.__version__)"
# Expected: 0.6.x
```

### 3.3 One-Click Installation Scripts

The project provides two scripts that work together to achieve one-click ROCm environment installation:

```bash
# Method 1: fresh installation (recommended for first use)
# Installs the PyTorch full suite + vLLM + project dependencies + PIP_CONSTRAINT triple protection
bash scripts/setup_rocm.sh

# Method 2: fix an existing environment (CUDA version of PyTorch -> ROCm version)
# Applicable when torch has been overwritten with the CUDA version after pip install vllm
bash scripts/fix_rocm_torch.sh
```

#### Installation Process Details

```bash
# 1. Create a virtual environment
python3.12 -m venv venv
source venv/bin/activate

# 2. Install vLLM (this pulls the CUDA version of torch, overwritten later)
pip install vllm --no-build-isolation

# 3. Install project dependencies
pip install -r requirements.txt

# 4. Install the ROCm PyTorch full suite (overwrites the CUDA version)
#    --no-deps: prevents pip from pulling CUDA nvidia dependencies
#    --force-reinstall: ensures the ROCm versions overwrite the CUDA versions
pip install torch==2.9.1+rocm6.3 torchvision==0.24.1+rocm6.3 torchaudio==2.9.1+rocm6.3 pytorch-triton-rocm==3.5.1 \
    --index-url https://download.pytorch.org/whl/rocm6.3 \
    --no-cache-dir --force-reinstall --no-deps

# 5. Clean up leftover CUDA dependencies
pip uninstall -y triton pytorch-triton pytorch-triton-xpu || true
pip uninstall -y nvidia-cudnn-cu13 nvidia-cusparselt-cu13 nvidia-nccl-cu13 nvidia-nvshmem-cu13 || true
pip uninstall -y nvidia-cublas nvidia-cuda-runtime nvidia-cufft nvidia-cufile nvidia-cuda-cupti || true
pip uninstall -y nvidia-curand nvidia-cusolver nvidia-cusparse nvidia-nvjitlink nvidia-cuda-nvrtc nvidia-nvtx || true

# 5.1 Uninstall the CUDA-only torch_c_dlpack_ext (vLLM V1 -> xgrammar -> tvm_ffi dependency chain)
#      This package cannot find libtorch_cuda.so on ROCm, causing vLLM startup to crash
pip uninstall -y torch_c_dlpack_ext || true

# 6. Remove leftover triton namespace directories (cause of AttributeError)
rm -rf venv/lib/python3.12/site-packages/triton

# 7. Create the PIP_CONSTRAINT file (permanent protection, prevents future pip install overwrites)
cat > venv/constraints.txt << 'EOF'
torch==2.9.1+rocm6.3
torchvision==0.24.1+rocm6.3
torchaudio==2.9.1+rocm6.3
pytorch-triton-rocm==3.5.1
triton==0.0.0
pytorch-triton==0.0.0
torch_c_dlpack_ext==0.0.0
EOF

# 8. Write the environment variables into venv/bin/activate (auto-loaded)
#    setup_rocm.sh / fix_rocm_torch.sh complete this step automatically
#    Includes: PIP_CONSTRAINT, PIP_EXTRA_INDEX_URL, HSA_OVERRIDE_GFX_VERSION, etc.

# 9. Verify
python -c "
import torch
print(f'torch: {torch.__version__}, cuda: {torch.cuda.is_available()}')
import torchvision; print(f'torchvision: {torchvision.__version__}')
import torchaudio; print(f'torchaudio: {torchaudio.__version__}')
import triton; print(f'triton: {triton.__version__}')
"
```

> **Triple-protection mechanism**:
> 1. `constraints.txt` locks the torch/torchvision/torchaudio/pytorch-triton-rocm versions + blacklists CUDA-only packages (triton/pytorch-triton/torch_c_dlpack_ext)
> 2. The `PIP_CONSTRAINT` environment variable automatically applies the constraints (written into venv/bin/activate)
> 3. `PIP_EXTRA_INDEX_URL` points to the ROCm index
>
> Any subsequent `pip install` will not overwrite the ROCm versions. If you rebuild the venv, you must re-run the scripts.

---

## Part 4: Agently Integration

### 4.1 Configuration Files

The model API configuration is independent of the Agent behavior and is stored in `configs/models.toml`:

```toml
[chat]
provider    = "OpenAICompatible"
base_url    = "http://localhost:8000/v1"
model       = "Qwen3-8B"
model_type  = "chat"
auth_env    = "LOCAL_LLM_API_KEY"

[reasoning]
provider    = "OpenAICompatible"
base_url    = "http://localhost:8002/v1"
model       = "deepseek-ai/DeepSeek-R1-Distill-Qwen-7B"
model_type  = "chat"
auth_env    = "LOCAL_REASONING_API_KEY"

[embedding]
provider    = "OpenAICompatible"
base_url    = "http://localhost:8001/v1"
model       = "BAAI/bge-m3"
model_type  = "embeddings"
auth_env    = "LOCAL_EMBED_API_KEY"
```

### 4.2 Code Integration

```python
# Key configuration logic in src/config.py (after the I5 fix)
import os
import tomllib  # Python 3.11+; tomli is required for 3.10 and earlier
from pathlib import Path
from dotenv import load_dotenv
from agently import Agently

PROJECT_ROOT = Path(__file__).resolve().parent.parent

def load_config():
    """Load toml configuration + .env keys, returning a configuration dictionary."""
    load_dotenv(PROJECT_ROOT / ".env")
    with open(PROJECT_ROOT / "configs" / "agent.toml", "rb") as f:
        agent_cfg = tomllib.load(f)
    with open(PROJECT_ROOT / "configs" / "models.toml", "rb") as f:
        models_cfg = tomllib.load(f)
    return agent_cfg, models_cfg

def _require_env(env_key: str) -> str:
    """Read an environment variable, raising if missing rather than silently returning an empty string (M7 fix)."""
    value = os.environ.get(env_key, "")
    if not value:
        raise RuntimeError(f"Environment variable {env_key} is not set or is empty. Please configure it in the .env file.")
    return value

def configure_agently(models_cfg=None, agent_cfg=None) -> None:
    """I5 fix: only injects the model_request scheduling/retry configuration into the global scope.
    Model connection configuration is injected per-agent via set_settings in make_chat_agent and similar."""
    pressure_cfg = (agent_cfg or {}).get("pressure", {})
    Agently.set_settings("model_request", {
        "scheduler": {
            "max_concurrency": pressure_cfg.get("max_concurrent_requests", 4),
            "rate_per_second": pressure_cfg.get("rate_per_second", 0),
        },
        "retry_backoff_base": pressure_cfg.get("retry_backoff_base", 1.0),
        "retry_backoff_max": pressure_cfg.get("retry_backoff_max", 10.0),
        "retry_max_attempts": pressure_cfg.get("retry_max_attempts", 3),
    })

def make_chat_agent(models_cfg: dict):
    """I5: per-agent set_settings, no longer relying on global OpenAICompatible."""
    chat = models_cfg["chat"]
    agent = Agently.create_agent("insurance-chat")
    agent.set_settings("OpenAICompatible", {
        "base_url": chat["base_url"],
        "model": chat["model"],
        "model_type": chat["model_type"],
        "auth": _require_env(chat["auth_env"]),
        "request_options": chat.get("request_options", {}),
    })
    return agent
```

### 4.3 CPU Mode (degradation without a GPU environment)

```toml
# configs/models.toml — CPU mode
[chat]
provider    = "OpenAICompatible"
base_url    = "http://localhost:8000/v1"  # still requires a local vLLM/llama.cpp
model       = "Qwen3-8B"
model_type  = "chat"
auth_env    = "LOCAL_LLM_API_KEY"
```

> In CPU mode, inference speed drops significantly (roughly 5-10x), and it is intended only for functional verification, not performance evaluation.

---

## Part 5: Offline Reproducibility

See [REPRODUCTION.md](./REPRODUCTION.md) for details; core guarantees:

1. **Dependency locking**: `requirements.txt` + `pyproject.toml` fix the versions
2. **Configuration separation**: `agent.toml` (behavior) decoupled from `models.toml` (API)
3. **Key isolation**: the `.env.example` template, real keys are never committed
4. **Model caching**: download scripts provided, supporting offline loading
5. **Sample data**: the `docs_data/` directory contains sample insurance documents (supporting PDF/Word/HTML/TXT/MD)
6. **One-click startup**: `scripts/build_index.py` + `scripts/start_agent.py`
7. **RAG configuration**: BM25/reranking/Query rewriting can all be toggled via `agent.toml`, degrading gracefully when dependencies are missing

---

## Part 6: Startup Checklist

| Check item | Command | Expected result |
|--------|------|----------|
| GPU visible | `rocm-smi` | Shows the Radeon GPU |
| ROCm version | `rocminfo --version` | 6.5+ |
| PyTorch ROCm ecosystem | `python -c "import torch,torchvision,torchaudio,triton; print(torch.__version__,torchvision.__version__,torchaudio.__version__,triton.__version__)"` | All include the `+rocm6.3` suffix |
| GPU available | `python -c "import torch; print(torch.cuda.is_available())"` | True |
| vLLM service | `curl http://localhost:8000/v1/models` | Returns the model list |
| Embedding service | `curl http://localhost:8001/v1/models` | Returns the model list |
| Index built | `ls .agently/runs/insurance/index/` | faiss.index + id_map.json + bm25_index.pkl |
| BM25 index | `ls .agently/runs/insurance/index/bm25_index.pkl` | File exists |
| Workspace Records | `ls .agently/runs/insurance/records/` | chunk JSON files exist |
| Agent can start | `python scripts/start_agent.py` | Enters the interactive prompt |