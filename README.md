# Insurance RAG Agent

> Track 2: Development & Local Deployment of Private AI Agents
> An insurance intelligent Q&A Agent built on the Agently 4.1.4.1 framework, fully deployed locally on AMD Radeon GPU + ROCm

---

## Project Overview

Insurance RAG Agent is a private AI Agent system for insurance business scenarios. It provides five core capabilities: local knowledge retrieval (RAG), tool invocation, multi-step task planning, layered memory, and permission control. All core inference runs on the AMD Radeon GPU + ROCm platform and does not depend on closed-source remote APIs.

### Core Capabilities (official "choose 2 of 5" threshold — this project implements all 5)

| Capability | Implementation Module | Status |
|------|----------|------|
| Local knowledge retrieval (RAG) | FAISS ANN + Workspace packaging | Implemented |
| Tool invocation | file_tools / doc_tools / data_query | Implemented |
| Multi-step task planning | TriggerFlow five-step orchestration + reflection validation | Implemented |
| Local multi-turn memory | Session short-term + Namespace long-term | Implemented |
| Permission control & privacy protection | Directory whitelist + scope filtering + audit log | Implemented |

---

## Technology Stack

| Component | Choice | Version |
|------|------|------|
| Agent framework | Agently | 4.1.4.1 |
| Inference backend | vLLM (ROCm) | 0.6.x+ |
| Chat LLM | Qwen3-8B (FP16 / GPTQ-Int4) | — |
| Reasoning-enhanced LLM | DeepSeek-R1-Distill-Qwen-7B | — |
| Embedding | BGE-M3 (BAAI/bge-m3) | — |
| Vector index | FAISS (faiss-cpu) | 1.7.4+ |
| Persistence | Agently Workspace | — |
| PyTorch | torch (ROCm 6.3) | 2.9.1+rocm6.3 |
| torchvision | torchvision (ROCm 6.3) | 0.24.1+rocm6.3 |
| torchaudio | torchaudio (ROCm 6.3) | 2.9.1+rocm6.3 |
| Triton | pytorch-triton-rocm (ROCm 6.3) | 3.5.1 |
| Python | — | 3.12 |

### Runtime Environment (verified)

| Component | Actual Value |
|------|--------|
| Platform | Radeon Cloud remote container |
| GPU | AMD Radeon Graphics (gfx1100, RDNA 3) |
| VRAM | 48 GB |
| ROCm | 6.16.13 |
| CPU | 2× AMD EPYC 9334 (64 cores) |
| Memory | ~504 GB |

---

## Quick Start

### Prerequisites

- Radeon Cloud remote container (ROCm 6.16.13 pre-installed)
- AMD Radeon GPU gfx1100 (48GB VRAM)
- Python 3.12 (a virtual environment must be created to install PyTorch + vLLM)

### One-Command Startup

```bash
# 1. Install the ROCm environment (PyTorch full suite 2.9.1+rocm6.3 + vLLM + project dependencies)
bash scripts/setup_rocm.sh

# 2. Download models (Qwen3-8B / bge-m3 / DeepSeek-R1-Distill / bge-reranker)
bash scripts/download_models.sh

# 3. (Optional) Quantize the GPTQ-Int4 model (for performance comparison experiments)
python scripts/quantize_gptq.py

# 4. Configure the keys (local vLLM can use the default values)
cp .env.example .env

# 5. Start the vLLM inference service (automatically sets HSA_OVERRIDE + --device 0)
bash scripts/start_vllm.sh

# 6. Build the index
python scripts/build_index.py

# 7. Start the Agent
python scripts/start_agent.py
```

> For the full environment configuration and model deployment details, see [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)

---

## Observability (Trace)

The project integrates a Trace observability layer (referencing Lesson 23), recording the runtime facts of each run:

```bash
# View the Trace view of a specific run
python scripts/trace_view.py --run-dir .agently/runs/insurance/traces/<task_id>
```

Trace records two types of facts:
- **Business layer**: comprehension completion, R1 routing result, validation status, retrieval candidate count, R2 citation count, Session persistence
- **Framework layer**: TriggerFlow execution lifecycle, chunk execution, model request telemetry (provider/model/usage/duration)

Six observation views are provided: task / stage / operation / attempt / retrieval / citation.

---

## Evaluation & Release Gate (Eval)

The project integrates a segmented evaluation framework (referencing Lesson 24), including host-based deterministic checks + model-based semantic judging:

```bash
# Batch evaluation
python scripts/run_eval.py --cases docs/eval/insurance_qa_50.json --rounds 1 --trial-id trial-001

# Release gate check
python scripts/release_gate.py --result eval_results/trial-001/eval_results.json
```

Evaluation covers 4 stages with 17 rules:
- **retrieval**: retrieval sufficiency, hybrid retrieval usage, reranking application (host checks) + retrieval relevance (model judge)
- **citation**: citation presence, citation validity, source traceability (host checks)
- **answer**: non-empty answer, no hallucination markers (host checks) + factual accuracy, completeness (model judge)
- **end_to_end**: end-to-end satisfaction (model judge)

Release gate criteria: pass rate >= 80%, failure rate <= 10%, key stages pass, evaluation cases >= 10.

---

## Web Service & IM Integration

The project provides a FastAPI web service and a frontend chat interface (referencing Lesson 25):

```bash
# Start the web service (frontend + API)
python scripts/start_server.py
# Visit http://localhost:8080
```

### API Endpoints

| Endpoint | Method | Description |
|------|------|------|
| `/api/chat` | POST | Synchronous chat, returns the complete result |
| `/api/chat/stream` | POST | SSE streaming chat, pushes five-step pipeline progress in real time |
| `/api/health` | GET | Health check |
| `/api/sessions/{id}/history` | GET | Session history |
| `/api/im/webhook` | POST | IM webhook (WeCom / Feishu / DingTalk) |

### Frontend Features

- Apple HIG-style design (light background + orange theme)
- Real-time progress indicator for the TriggerFlow five-step pipeline
- Markdown rendering + expandable `[[ref:xxx]]` citation badges
- Multi-session management + responsive layout

---

## Environment Setup

### 1. ROCm Environment (pre-installed in the remote container)

```bash
# Verify the pre-installed ROCm environment
rocm-smi --showproductname
# Expected: AMD Radeon Graphics, gfx1100

rocminfo --version
# Expected: ROCk 6.16.13, HSA Runtime 1.18
```

### 2. Create a virtual environment + install the PyTorch ecosystem (ROCm)

```bash
python3.12 -m venv venv
source venv/bin/activate

# gfx1100 must use the ROCm 6.3 index (provides torch 2.9.1, compatible with vLLM 0.26.0)
# The ROCm 6.2 index only goes up to torch 2.5.1, which is incompatible with the new vLLM
# torch + torchvision + torchaudio + pytorch-triton-rocm must all be installed together
# Otherwise, on vLLM import, transformers will pull the CUDA versions of torchvision/torchaudio and crash
pip install torch==2.9.1+rocm6.3 torchvision==0.24.1+rocm6.3 torchaudio==2.9.1+rocm6.3 pytorch-triton-rocm==3.5.1 \
    --index-url https://download.pytorch.org/whl/rocm6.3 \
    --no-cache-dir --force-reinstall --no-deps
```

<details>
<summary>Alternative: download pre-built wheels from the official AMD repo (click to expand)</summary>

If the official PyTorch index is slow or unstable, you can download the ROCm pre-compiled wheels directly from the AMD Radeon repo:

```bash
# Download the ROCm 7.2.1 pre-compiled wheels (Python 3.12)
wget https://repo.radeon.com/rocm/manylinux/rocm-rel-7.2.1/torch-2.9.1%2Brocm7.2.1.lw.gitff65f5bc-cp312-cp312-linux_x86_64.whl
wget https://repo.radeon.com/rocm/manylinux/rocm-rel-7.2.1/torchvision-0.24.0%2Brocm7.2.1.gitb919bd0c-cp312-cp312-linux_x86_64.whl
wget https://repo.radeon.com/rocm/manylinux/rocm-rel-7.2.1/torchaudio-2.9.0%2Brocm7.2.1.gite3c6ee2b-cp312-cp312-linux_x86_64.whl
wget https://repo.radeon.com/rocm/manylinux/rocm-rel-7.2.1/triton-3.5.1%2Brocm7.2.1.gita272dfa8-cp312-cp312-linux_x86_64.whl

# Uninstall any existing CUDA versions before installing
pip uninstall -y torch torchvision torchaudio triton
pip install \
    torch-2.9.1+rocm7.2.1.lw.gitff65f5bc-cp312-cp312-linux_x86_64.whl \
    torchvision-0.24.0+rocm7.2.1.gitb919bd0c-cp312-cp312-linux_x86_64.whl \
    torchaudio-2.9.0+rocm7.2.1.gite3c6ee2b-cp312-cp312-linux_x86_64.whl \
    triton-3.5.1+rocm7.2.1.gita272dfa8-cp312-cp312-linux_x86_64.whl
```

> Note: the wheel versions in the AMD repo (ROCm 7.2.1) differ from those in the PyTorch index (ROCm 6.3),
> but both are compatible with the gfx1100 GPU. Choose either option; do not mix them.

</details>

### 3. Install vLLM (ROCm)

```bash
pip install vllm --no-build-isolation
```

### 4. Project Dependencies

```bash
pip install -r requirements.txt
```

> One-click install: `bash scripts/setup_rocm.sh` (see [docs/REPRODUCTION.md](docs/REPRODUCTION.md))
>
> **Common issues**: If `torch.cuda.is_available()` returns False, `torch.version.hip` is None,
> or errors such as `torchvision::nms` / `libcudart.so.13` / `triton has no attribute 'language'` appear,
> it means the CUDA version of the PyTorch ecosystem was installed instead of the ROCm version.
> Run `bash scripts/fix_rocm_torch.sh` to fix all issues in one step.

---

## Startup Guide

### Step 1: Start the inference service

```bash
source venv/bin/activate

# Terminal 1: vLLM Chat LLM service (main model Qwen3-8B)
# Use the launch script (automatically sets HSA_OVERRIDE_GFX_VERSION + --device 0)
bash scripts/start_vllm.sh              # C0 baseline (FP16), port 8000

# Terminal 2: reasoning-enhanced model (optional, invoked for complex computation/logical reasoning)
bash scripts/start_vllm.sh --reasoning  # DeepSeek-R1-Distill, port 8002

# Terminal 3: Embedding service
text-embeddings-router --model ./models/bge-m3 --port 8001
```

> **C2 INT4 quantization mode** (performance comparison experiment):
> ```bash
> # Quantization must be completed first: python scripts/quantize_gptq.py
> bash scripts/start_vllm.sh --int4       # INT4 GPTQ, port 8000
> ```
>
> **Manual startup** (environment variables must be set manually):
> ```bash
> # Prerequisite: install amdsmi (required for vLLM ROCm platform detection)
> cd /opt/rocm/share/amd_smi && pip install .
> export LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/opt/rocm/lib:/opt/rocm/lib64
> export HSA_OVERRIDE_GFX_VERSION=11.0.0  # required for gfx1100
> export ROCBLAS_USE_HIPBLASLT=1
> export HIP_VISIBLE_DEVICES=0
> python -m vllm.entrypoints.openai.api_server \
>     --model ./models/Qwen3-8B \
>     --device 0 \
>     --dtype bfloat16 \
>     --max-model-len 8192 \
>     --gpu-memory-utilization 0.85 \
>     --port 8000
> ```

### Step 2: Configure the keys

```bash
cp .env.example .env
# No changes are needed for local vLLM; use the default Empty-key
```

### Step 3: Build the index

```bash
python scripts/build_index.py
# Output: .agently/runs/insurance/index/faiss.index + id_map.json
```

### Step 4: Start the Agent

```bash
python scripts/start_agent.py
```

### GPU Mode vs CPU Mode

| Dimension | GPU Mode (recommended) | CPU Mode (fallback) |
|------|------------------|------------------|
| Inference backend | vLLM on ROCm (`--device 0`) | vLLM/llama.cpp on CPU |
| Speed | 18-69 tok/s (C0-C4) | 2-5 tok/s |
| Use case | Performance evaluation, Demo | Functional verification |
| Environment variable | `HSA_OVERRIDE_GFX_VERSION=11.0.0` required | Not needed |
| Configuration | Handled automatically by `start_vllm.sh` | Modify `base_url` to point to the CPU service |

---

## Dependency List

### Core Dependencies (requirements.txt)

```
agently==4.1.4.1
python-dotenv>=1.0.0
faiss-cpu>=1.7.4
numpy>=1.24.0
```

### System Dependencies (require separate installation)

| Dependency | Installation | Purpose |
|------|----------|------|
| ROCm 6.3+ | `apt install rocm-dev` | GPU driver (gfx1100 requires `HSA_OVERRIDE_GFX_VERSION=11.0.0`) |
| PyTorch 2.9.1 (ROCm 6.3) | `pip install torch==2.9.1+rocm6.3 --index-url https://download.pytorch.org/whl/rocm6.3` | Deep learning framework |
| torchvision 0.24.1 (ROCm 6.3) | `pip install torchvision==0.24.1+rocm6.3 --index-url https://download.pytorch.org/whl/rocm6.3` | Computer vision library (transformers dependency) |
| torchaudio 2.9.1 (ROCm 6.3) | `pip install torchaudio==2.9.1+rocm6.3 --index-url https://download.pytorch.org/whl/rocm6.3` | Audio processing library (transformers dependency) |
| pytorch-triton-rocm 3.5.1 | `pip install pytorch-triton-rocm==3.5.1 --index-url https://download.pytorch.org/whl/rocm6.3` | ROCm-compatible Triton compiler |
| amdsmi | `cd /opt/rocm/share/amd_smi && pip install .` | AMD SMI Python library (required for vLLM ROCm platform detection; if missing, `Failed to infer device type`) |
| vLLM 0.6.x+ (ROCm) | `pip install vllm --no-build-isolation` | Inference backend (startup requires `--device 0` + `LD_LIBRARY_PATH` containing `/opt/rocm/lib`) |
| text-embeddings-inference | cargo install / docker | Embedding service |
| GPTQModel | `pip install gptqmodel` | GPTQ-Int4 local quantization (optional, for performance comparison experiments) |

> **Important**: torch / torchvision / torchaudio / pytorch-triton-rocm must all use the ROCm versions.
> If only torch is installed and the other three are omitted, `pip install vllm` will pull the CUDA versions,
> causing errors such as `RuntimeError: operator torchvision::nms does not exist`,
> `OSError: libcudart.so.13` or `AttributeError: module 'triton' has no attribute 'language'`.
> In addition, vLLM requires the `amdsmi` Python module to detect the ROCm platform; if missing, it reports `Failed to infer device type`.
> Run `bash scripts/fix_rocm_torch.sh` to fix all issues in one step (including amdsmi installation).

### Development Dependencies (optional)

```bash
pip install -e ".[dev]"  # installs pytest, pytest-asyncio
```

---

## Project Structure

```
insurance-rag-agent/
├── configs/                    # Configuration files (behavior decoupled from model API)
│   ├── agent.toml              # Agent behavior configuration
│   └── models.toml             # Model API configuration
├── docs/                       # Project documentation
│   ├── SPECIFICATION.md        # Project specification document
│   ├── ARCHITECTURE.md         # Agent architecture diagram
│   ├── DEPLOYMENT.md           # Model & deployment plan
│   ├── GPU_ENVIRONMENT.md      # GPU environment evidence (gfx1100, 48GB)
│   ├── ROCm_OPTIMIZATION.md    # ROCm inference optimization notes
│   └── REPRODUCTION.md         # Offline reproduction guide
├── src/                        # Core source code
│   ├── agent/                  # Agent core (flow + pipeline + main)
│   ├── rag/                    # RAG pipeline (parser + chunker + indexer + retriever + bm25 + reranker)
│   ├── memory/                 # Layered memory (layers + recall + growth)
│   ├── session/                # Session management (handlers + registry + persistence)
│   ├── tools/                  # Tool modules (file + doc + data_query)
│   ├── workspace/              # Workspace persistence (ingest + retrieve)
│   ├── security/               # Security layer (permissions + audit)
│   ├── observability/          # Trace observability (trace_log + six views)
│   ├── eval/                   # Eval evaluation & release gate (checks + judge + cases + report)
│   ├── api/                    # Web service & IM integration (FastAPI + SSE + IM Router)
│   └── config.py               # Configuration loading
├── static/                     # Frontend pages (Apple HIG style)
│   ├── index.html              # Chat interface
│   ├── app.js                  # SSE streaming + Markdown rendering
│   └── styles.css              # Styles (orange theme)
├── scripts/                    # Startup and evaluation scripts
│   ├── build_index.py          # Index building
│   ├── start_agent.py          # Agent CLI startup
│   ├── start_server.py         # Web service startup (FastAPI + frontend)
│   ├── start_vllm.sh           # vLLM ROCm launch script (C0/C2/reasoning three modes)
│   ├── setup_rocm.sh           # One-click ROCm environment installation
│   ├── fix_rocm_torch.sh       # Fix CUDA→ROCm PyTorch switch issues
│   ├── patch_vllm_source.py    # vLLM source patch (torch 2.9.1 get_memory_info compatibility)
│   ├── vllm_rocm_patch.py      # vLLM monkey-patch (backup plan, loaded via sitecustomize.py)
│   ├── sitecustomize.py        # Python auto-load entry point (loads vllm_rocm_patch)
│   ├── download_models.sh      # Model download (with exclusion patterns)
│   ├── quantize_gptq.py        # GPTQ-Int4 local quantization
│   ├── benchmark_rag.py        # RAG benchmark testing
│   ├── run_eval.py             # Batch evaluation runner
│   ├── release_gate.py         # Release gate check
│   ├── trace_view.py           # Trace view viewer
│   └── collect_gpu_evidence.sh # GPU evidence collection
├── demo/                       # Demo samples
├── docs_data/                  # Sample insurance documents
├── .env.example                # Key template
├── requirements.txt            # Dependency list
├── pyproject.toml              # Project metadata
├── CONTRIBUTING.md             # Contribution & PR guide
├── LICENSE                     # Open source license
└── README.md                   # This file
```

---

## Configuration Notes

### agent.toml — Agent behavior configuration

```toml
[workspace]
root        = "./.agently/runs/insurance"
file_areas  = ["downloads", "artifacts", "reports"]

[session]
max_length      = 500
default_strategy = "key_fields_compress"
auto_resize     = true

[memory]
mode            = "AgentlyMemory"
recall_top_k    = 3

[rag]
chunk_size      = 512
chunk_overlap   = 64
faiss_index_type = "IndexFlatIP"
faiss_top_k     = 10
```

### models.toml — Model API configuration (dual-model scheme)

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

> Dual-model: Qwen3-8B (main model, RAG Q&A + fast response) + DeepSeek-R1-Distill-Qwen-7B (reasoning enhancement, complex computation/logical reasoning, port 8002).

### .env — Key configuration

```bash
cp .env.example .env
# Local vLLM uses the default Empty-key and requires no changes
# If using a cloud API alternative, fill in the corresponding API key
```

---

## Documentation Navigation

| Document | Content | Corresponding official requirement |
|------|------|-------------|
| [SPECIFICATION.md](docs/SPECIFICATION.md) | Application scenarios, core capabilities, architecture overview | Project specification document |
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | System architecture diagram, RAG pipeline, memory architecture | Agent architecture diagram |
| [DEPLOYMENT.md](docs/DEPLOYMENT.md) | Model selection, deployment plan, ROCm dependencies | Model & local deployment plan |
| [GPU_ENVIRONMENT.md](docs/GPU_ENVIRONMENT.md) | Actual GPU environment evidence (gfx1100, 48GB, ROCm 6.16.13) | GPU environment verification |
| [ROCm_OPTIMIZATION.md](docs/ROCm_OPTIMIZATION.md) | Optimization points, comparison experiments, GPU evidence | ROCm inference optimization notes |
| [REPRODUCTION.md](docs/REPRODUCTION.md) | Environment preparation, reproduction steps, troubleshooting | Offline reproducibility |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Fork & PR process | Submission method |
| [demo/demo_script.md](demo/demo_script.md) | Demo recording script | Demo video |

---

## Submission Method (Fork & PR)

This project is submitted via Fork + Pull Request as required by the competition. See [CONTRIBUTING.md](CONTRIBUTING.md) for details.

```bash
# 1. Fork the official repository to your personal GitHub
# 2. Clone your Fork
git clone https://github.com/<your-username>/<repo-name>.git
cd <repo-name>

# 3. Create a submission branch
git checkout -b track2-insurance-rag-agent

# 4. Copy the project files into a repository subdirectory
cp -r insurance-rag-agent/* ./track2/insurance-rag-agent/

# 5. Commit and push
git add .
git commit -m "feat: add Insurance RAG Agent for Track 2"
git push origin track2-insurance-rag-agent

# 6. Create a Pull Request on GitHub
```

---

## Troubleshooting

| Issue | Cause | Solution |
|------|------|----------|
| `rocm-smi` produces no output | ROCm driver not ready | Check the driver installation and confirm the user is in the `render`, `video` groups |
| `torch.cuda.is_available()` returns False | Installed the CUDA version of PyTorch instead of the ROCm version | Run `bash scripts/fix_rocm_torch.sh` to fix |
| `torch.version.hip` is None | Same as above, the CUDA version of torch has no HIP support | Same as above, confirm installation of `torch==2.9.1+rocm6.3` |
| `torch` version is `2.11.0+cu130` | `pip install vllm` automatically pulled the latest CUDA torch from PyPI, overwriting the ROCm version | Run `bash scripts/fix_rocm_torch.sh` (uses `--force-reinstall --no-deps` to prevent another overwrite); re-run the script after any subsequent `pip install` |
| vLLM `Failed to infer device type` | vLLM platform detection requires the `amdsmi` Python module to identify the ROCm platform; if not installed, no platform can be detected (CUDA also fails due to missing NVML), causing a `DeviceConfig` error | Install amdsmi: `cd /opt/rocm/share/amd_smi && pip install .` + `export LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/opt/rocm/lib:/opt/rocm/lib64`; or use `bash scripts/start_vllm.sh` (automatically detects and installs amdsmi) |
| vLLM `Failed to infer device type` (DEBUG shows `No module named 'amdsmi'`) | Same as above, vLLM `platforms/__init__.py` fails to `import amdsmi`, so the ROCm platform is unavailable | Same as above, amdsmi is a Python library bundled with ROCm, located at `/opt/rocm/share/amd_smi/` |
| `RuntimeError: operator torchvision::nms does not exist` | Installed the CUDA version of torchvision (incompatible with the ROCm version of torch) | Run `bash scripts/fix_rocm_torch.sh` (installs `torchvision==0.24.1+rocm6.3`) |
| `OSError: libcudart.so.13: cannot open shared object file` | Installed the CUDA version of torchaudio (missing CUDA runtime) | Run `bash scripts/fix_rocm_torch.sh` (installs `torchaudio==2.9.1+rocm6.3`) |
| `AttributeError: module 'triton' has no attribute 'language'` | Installed the CUDA version of triton or a leftover empty triton namespace directory remains | Run `bash scripts/fix_rocm_torch.sh` (uninstalls CUDA triton + removes leftover directories + installs `pytorch-triton-rocm==3.5.1`) |
| `OSError: libtorch_cuda.so: cannot open shared object file` | `torch_c_dlpack_ext` is a CUDA-only package and cannot find `libtorch_cuda.so` on ROCm (dependency chain: vLLM V1 -> xgrammar -> tvm_ffi -> torch_c_dlpack_ext) | Run `pip uninstall -y torch_c_dlpack_ext`, or `bash scripts/fix_rocm_torch.sh` (this fix is already included); `start_vllm.sh` also detects and uninstalls it automatically |
| `AttributeError: module 'torch.accelerator' has no attribute 'get_memory_info'` | vLLM 0.26.0 calls `torch.accelerator.get_memory_info()` (a torch 2.10+ API), but ROCm 6.3 only provides torch 2.9.1; the `sitecustomize.py` patch is not effective in spawn child processes | Run `python scripts/patch_vllm_source.py` (patches the vLLM source directly); `start_vllm.sh` and `fix_rocm_torch.sh` apply this patch automatically |
| `AttributeError: '_C' object has no attribute 'get_cuda_view_from_cpu_tensor'` | The CUDA wheel of vLLM installed from PyPI lacks the ROCm C++ extensions (`vllm._C`/`vllm._rocm_C` are both missing), and the V2 Model Runner calls an uncompiled C++ operator when creating a UVA Buffer | Run `python scripts/patch_vllm_source.py` (patches the UVA fallback); `start_vllm.sh` applies it automatically; the permanent fix is to install the ROCm build with `pip install vllm --extra-index-url https://wheels.vllm.ai/rocm/` |
| `Skipping import of cpp extensions ... torch >= 2.11.0` | The torchao that vLLM depends on requires torch 2.11+, but ROCm 6.3 only provides up to 2.9.1 | Non-fatal warning; torchao automatically falls back to a Python implementation and inference is unaffected |
| vLLM `Triton ... 0 active driver(s) found` | Poor Triton compatibility on ROCm (normal warning) | No action needed; vLLM automatically disables Triton and uses the Flash Attention backend |
| FAISS index building fails | The Embedding service is not running | `curl http://localhost:8001/v1/models` to confirm the service status |
| Agent connection timeout | The vLLM service is not running or the port does not match | Check `base_url` in `configs/models.toml` and the API key in `.env` |
| Out of memory (OOM) | The model is too large or concurrency is too high | Use the INT4 quantized model, reduce `max-model-len`, lower `max-num-seqs` |
| Model download failure (bge-m3) | Some HuggingFace files are incompatible | `download_models.sh` already excludes `*.DS_Store,imgs/*` by default |

For more troubleshooting guidance see [docs/REPRODUCTION.md](docs/REPRODUCTION.md#part-5-common-problem-troubleshooting).

---

## License

[MIT License](LICENSE)

---

## Track Information

| Item | Content |
|------|------|
| Track | Track 2: Private AI Agents |
| Platform | Radeon Cloud remote container (gfx1100, 48GB VRAM) |
| ROCm | 6.16.13 |
| Framework | Agently 4.1.4.1 |
| Submission method | Fork → PR |
| Deadline | 2026-08-06 23:59 (UTC+8) |

## Submission Materials

| Material | Link / Location | Notes |
|------|------|------|
| Demo video | [https://share.weiyun.com/mucf0ZjP](https://share.weiyun.com/mucf0ZjP) | ~3-5 min, demonstrates the full pipeline on AMD Radeon GPU |
| Presentation (PPT) | [`docs/presentation/Insurance-RAG-Agent-Competition-EN.pptx`](docs/presentation/Insurance-RAG-Agent-Competition-EN.pptx) | Competition deck (English) |
| Project specification | [`docs/SPECIFICATION.md`](docs/SPECIFICATION.md) | Application scenarios, capabilities, architecture |
| Deployment & ROCm optimization | [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) + [`docs/ROCm_OPTIMIZATION.md`](docs/ROCm_OPTIMIZATION.md) | Model & local deployment plan, inference speed optimization |