# Offline Reproduction Guide (Offline Reproduction Guide)

> Goal: any developer with an AMD Radeon GPU + ROCm environment can reproduce all of this project's functionality and performance data from scratch.

---

## Part 1: Environment Preparation

### 1.1 Actual Runtime Environment (verified)

> The following are the results actually collected from the remote container (2026-07-27), see [GPU_ENVIRONMENT.md](./GPU_ENVIRONMENT.md) for details.

| Component | Actual value |
|------|--------|
| Host | Radeon Cloud remote container |
| GPU | AMD Radeon Graphics (gfx1100, RDNA 3) |
| VRAM | 48 GB |
| CU | 96 |
| ROCm | 6.16.13 (kernel) / HSA Runtime 1.18 |
| CPU | 2× AMD EPYC 9334 (64 cores) |
| Memory | ~504 GB |
| Python | 3.12 (system, a venv must be created) |

### 1.2 Minimum Hardware Requirements

| Component | Minimum | Recommended | Actual environment |
|------|----------|----------|----------|
| GPU | AMD Radeon (gfx1100+) | Radeon Cloud | Radeon Cloud gfx1100 |
| VRAM | 8GB (INT4 quantization) | 16GB+ (FP16) | 48GB |
| Memory | 16GB | 32GB | 504GB |
| Storage | 50GB | 100GB SSD | Mountable in the container |

### 1.3 Software Requirements

| Component | Minimum version | Actual version | Installation method |
|------|----------|----------|----------|
| ROCm | 6.0+ | 6.16.13 | Pre-installed in the container |
| Python | 3.10+ | 3.12 | Bundled with the system |
| PyTorch | 2.9.1+ (ROCm 6.3) | Not pre-installed, must be installed | `pip install torch==2.9.1+rocm6.3 --index-url https://download.pytorch.org/whl/rocm6.3` |
| torchvision | 0.24.1+ (ROCm 6.3) | Not pre-installed, must be installed | `pip install torchvision==0.24.1+rocm6.3 --index-url https://download.pytorch.org/whl/rocm6.3` |
| torchaudio | 2.9.1+ (ROCm 6.3) | Not pre-installed, must be installed | `pip install torchaudio==2.9.1+rocm6.3 --index-url https://download.pytorch.org/whl/rocm6.3` |
| pytorch-triton-rocm | 3.5.1 | Not pre-installed, must be installed | `pip install pytorch-triton-rocm==3.5.1 --index-url https://download.pytorch.org/whl/rocm6.3` |
| vLLM | 0.6.x (ROCm) | Not pre-installed, must be installed | `pip install vllm --no-build-isolation` |

> **Important**: torch / torchvision / torchaudio / pytorch-triton-rocm must all use the ROCm versions.
> `pip install vllm` automatically pulls the CUDA versions and overwrites the ROCm versions; after installation, run `bash scripts/fix_rocm_torch.sh` to fix.

### 1.4 One-Step Installation

```bash
# After cloning the repository
cd insurance-rag-agent

# Create a virtual environment (remote container Python 3.12)
python3.12 -m venv venv
source venv/bin/activate

# One-click install of the PyTorch full suite (ROCm) + vLLM + project dependencies + PIP_CONSTRAINT triple protection
bash scripts/setup_rocm.sh

# If torch is still the CUDA version after setup_rocm.sh (overwritten by pip install vllm), run the fix script
bash scripts/fix_rocm_torch.sh

# Or install manually
pip install -r requirements.txt
```

---

## Part 2: Model Download & Caching

### 2.1 Download Script

```bash
# Download all models to the ./models/ directory
bash scripts/download_models.sh
```

Reference content of `scripts/download_models.sh`:

```bash
#!/bin/bash
set -e
mkdir -p ./models

echo "=== Downloading Qwen3-8B ==="
hf download Qwen/Qwen3-8B --local-dir ./models/Qwen3-8B

echo "=== Downloading DeepSeek-R1-Distill-Qwen-7B ==="
hf download deepseek-ai/DeepSeek-R1-Distill-Qwen-7B --local-dir ./models/DeepSeek-R1-Distill-Qwen-7B

echo "=== Downloading BGE-M3 ==="
hf download BAAI/bge-m3 --local-dir ./models/bge-m3

echo "=== Downloading BGE-Reranker-Base (reranking) ==="
hf download BAAI/bge-reranker-base --local-dir ./models/bge-reranker-base

echo "=== GPTQ-Int4 local quantization (Qwen3 has no official pre-quantized release) ==="
python scripts/quantize_gptq.py --source ./models/Qwen3-8B --target ./models/Qwen3-8B-GPTQ-Int4

echo "=== Model download complete ==="
ls -lh ./models/
```

> Note: `huggingface-cli` is deprecated; the new version uses the `hf` command.
> Qwen3 has no official GPTQ-Int4 pre-quantized release, so it must be quantized locally from FP16 via `scripts/quantize_gptq.py`.

### 2.2 Offline Loading

After downloading, modify `configs/models.toml` to point to the local paths:

```toml
[chat]
provider    = "OpenAICompatible"
base_url    = "http://localhost:8000/v1"
model       = "./models/Qwen3-8B"  # local path
model_type  = "chat"
auth_env    = "LOCAL_LLM_API_KEY"

[reasoning]
provider    = "OpenAICompatible"
base_url    = "http://localhost:8002/v1"
model       = "./models/DeepSeek-R1-Distill-Qwen-7B"  # local path
model_type  = "chat"
auth_env    = "LOCAL_REASONING_API_KEY"
```

Use the local paths when starting vLLM:

```bash
python -m vllm.entrypoints.openai.api_server \
    --model ./models/Qwen3-8B \
    --dtype bfloat16 \
    --port 8000
```

---

## Part 3: Complete Reproduction Steps

### Step 1: Environment verification

```bash
# Verify the GPU and ROCm (ROCm 6.16.13 is pre-installed in the remote container)
rocm-smi --showproductname
# Expected: AMD Radeon Graphics, gfx1100

rocminfo --version
# Expected: ROCk 6.16.13, HSA Runtime 1.18

# Create a virtual environment and install the PyTorch full suite (system Python 3.12 has no pre-installed torch)
python3.12 -m venv venv
source venv/bin/activate

# Install the ROCm PyTorch full suite (torch + torchvision + torchaudio + pytorch-triton-rocm)
pip install torch==2.9.1+rocm6.3 torchvision==0.24.1+rocm6.3 torchaudio==2.9.1+rocm6.3 pytorch-triton-rocm==3.5.1 \
    --index-url https://download.pytorch.org/whl/rocm6.3 \
    --no-cache-dir --force-reinstall --no-deps

# Verify (all should include the +rocm6.3 suffix, cuda=True)
python -c "
import torch, torchvision, torchaudio, triton
print(f'torch: {torch.__version__}')
print(f'cuda available: {torch.cuda.is_available()}')
print(f'torchvision: {torchvision.__version__}')
print(f'torchaudio: {torchaudio.__version__}')
print(f'triton: {triton.__version__}')
"
# Expected: torch=2.9.1+rocm6.3, cuda=True, torchvision=0.24.1+rocm6.3, torchaudio=2.9.1+rocm6.3, triton=3.5.1
```

### Step 2: Start the inference service

```bash
# Recommended: use the launch script (automatically installs amdsmi + sets LD_LIBRARY_PATH + HSA_OVERRIDE_GFX_VERSION + --device 0)
bash scripts/start_vllm.sh              # C0 baseline (FP16), port 8000
bash scripts/start_vllm.sh --reasoning  # DeepSeek-R1-Distill, port 8002

# Or start manually (environment variables must be set manually)
# Prerequisite: install amdsmi (required for vLLM ROCm platform detection; if missing, "Failed to infer device type")
cd /opt/rocm/share/amd_smi && pip install .
export LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/opt/rocm/lib:/opt/rocm/lib64  # amdsmi runtime dependency
export HSA_OVERRIDE_GFX_VERSION=11.0.0  # gfx1100 compatibility, required!
export ROCBLAS_USE_HIPBLASLT=1
export HIP_VISIBLE_DEVICES=0

# Terminal 1: start vLLM (Chat LLM — Qwen3-8B main model)
python -m vllm.entrypoints.openai.api_server \
    --model ./models/Qwen3-8B \
    --device 0 \
    --dtype bfloat16 \
    --max-model-len 8192 \
    --chat-template ./qwen3_nonthinking.jinja \
    --gpu-memory-utilization 0.85 \
    --port 8000

# Terminal 2: start the reasoning-enhanced model (optional — DeepSeek-R1-Distill-Qwen-7B)
python -m vllm.entrypoints.openai.api_server \
    --model ./models/DeepSeek-R1-Distill-Qwen-7B \
    --device 0 \
    --dtype bfloat16 \
    --max-model-len 4096 \
    --max-num-seqs 4 \
    --gpu-memory-utilization 0.85 \
    --port 8002

# Terminal 3: start the Embedding service
python -m text_embeddings_router --model ./models/bge-m3 --port 8001
```

### Step 3: Configure the keys

```bash
cp .env.example .env
# Edit .env; local vLLM can use the default Empty-key
```

### Step 4: Build the index

```bash
# Build the FAISS + BM25 index using the sample insurance documents
# Supports PDF/Word/HTML/TXT/MD formats
python scripts/build_index.py
```

Expected output:

```
[INFO] Parsing docs_data/insurance_policy.txt: 5 paragraphs (format=txt, title='Employer Liability Insurance Terms')
[INFO] Parsing docs_data/claims_guide.html: 12 paragraphs (format=html, title='Claims Guide')
[INFO] Document insurance_policy.txt: 8 chunks (format=txt, title='Employer Liability Insurance Terms')
[INFO] Document claims_guide.html: 15 chunks (format=html, title='Claims Guide')
[INFO] Total: 2 documents, 23 chunks (window=512, overlap=100, 20%=102)
[INFO] Workspace Records written: 23 -> .agently/runs/insurance/records
[INFO] Generating embedding...
[INFO] Embedding batch 1/1 complete
[INFO] Embedding matrix: (23, 1024)
[INFO] FAISS index built: 23 vectors
[INFO] BM25 index building: 23 documents
[INFO] BM25 index built
============================================================
Index building complete!
  Documents:   2
  Chunks: 23
  Vector dimension: 1024
  Chunking params: window=512, overlap=100 (20%)
  Workspace Records: 23
  FAISS index: .agently/runs/insurance/index
  BM25 index: built
  Elapsed:   3.2s
============================================================
```

### Step 5: Start the Agent

```bash
python scripts/start_agent.py
```

This enters interactive Q&A:

```
Insurance RAG Agent started (Agently 4.1.4.1 + vLLM ROCm)
Hybrid retrieval: FAISS+BM25+Rerank+QueryRewrite
Enter a question to start a conversation, type 'quit' to exit

> What is the claims process for Employer Liability Insurance?
[Step1] Understand natural language...
[Step2] Generate query method: rag_query
[Step3] Validate query parameters... passed
[Step4] FAISS retrieval top-10 + BM25 retrieval top-10
         Hybrid fusion: FAISS=10, BM25=8, after dedup fusion=12
         Cross-Encoder reranking: 12 candidates → top-5
         Workspace packaging 2000 chars
[Step5] Generate answer...

The claims process for Employer Liability Insurance is as follows:
1. Notify the insurance company within 48 hours of the accident [[ref:e1]]
2. Submit the claims application form and supporting materials [[ref:e2]]
3. The insurance company reviews and assesses the loss [[ref:e3]]
4. The claim payment is received (usually 7-15 business days) [[ref:e1]]
Source: insurance_policy.txt, claims_guide.html
```

### Step 6: Run the performance benchmark

```bash
# RAG retrieval benchmark
python scripts/benchmark_rag.py

# Output: docs/benchmarks/rag_benchmark.md
```

### Step 7: Run the GPU evidence collection

```bash
# Collect GPU model, ROCm version, VRAM usage, etc.
bash scripts/collect_gpu_evidence.sh

# Output: docs/benchmarks/logs/
```

### Step 8: Run the ROCm optimization comparison experiments

Refer to the four-step method in [ROCm_OPTIMIZATION.md](./ROCm_OPTIMIZATION.md):

```bash
# C0 baseline
bash scripts/run_benchmark.sh C0

# C2 extreme optimization (requires restarting vLLM with the INT4 model)
bash scripts/run_benchmark.sh C2

# View the summary
cat docs/benchmarks/summary.csv
```

---

## Part 4: Dependency Version Locking

### 4.1 Core Dependencies

| Package name | Version | Locking method |
|------|------|----------|
| agently | ==4.1.4.1 | requirements.txt + pyproject.toml |
| python-dotenv | >=1.0.0 | requirements.txt |
| faiss-cpu | >=1.7.4 | requirements.txt |
| numpy | >=1.24.0 | requirements.txt |
| pymupdf | >=1.23.0 | requirements.txt |
| python-docx | >=1.1.0 | requirements.txt |
| beautifulsoup4 | >=4.12.0 | requirements.txt |
| rank-bm25 | >=0.2.2 | requirements.txt |
| sentence-transformers | >=2.7.0 | requirements.txt |
| jieba | >=0.42.1 | requirements.txt |
| torch | 2.9.1+rocm6.3 | Installed separately + locked via constraints.txt |
| torchvision | 0.24.1+rocm6.3 | Installed separately + locked via constraints.txt |
| torchaudio | 2.9.1+rocm6.3 | Installed separately + locked via constraints.txt |
| pytorch-triton-rocm | 3.5.1 | Installed separately + locked via constraints.txt |
| torch_c_dlpack_ext | Not installed (blacklisted) | Locked to 0.0.0 in constraints.txt to prevent installation |
| vllm | 0.6.x (ROCm) | Installed separately |

### 4.2 Export the Complete Environment

```bash
# Export the conda environment
conda env export --no-builds > docs/environment_conda.yml

# Export the pip environment
pip freeze > docs/requirements_frozen.txt

# Use uv to export a lock file (recommended)
uv pip compile requirements.txt -o requirements.lock
```

### 4.3 Restoring from a Lock File

```bash
# Restore from the conda environment
conda env create -f docs/environment_conda.yml

# Restore from pip freeze
pip install -r docs/requirements_frozen.txt
```

---

## Part 5: Common Problem Troubleshooting

### 5.1 GPU Not Visible

```bash
# Check the driver
ls /dev/kfd  # should exist
ls /dev/dri/render*  # should exist

# Check user groups
groups $USER  # should include render, video

# Add user groups
sudo usermod -aG render,video $USER
# Takes effect after re-login
```

### 5.2 vLLM Startup Failure

```bash
# Check the PyTorch ROCm ecosystem (all should be ROCm versions)
python -c "
import torch, torchvision, torchaudio, triton
print(f'torch: {torch.__version__}, cuda: {torch.cuda.is_available()}')
print(f'torchvision: {torchvision.__version__}')
print(f'torchaudio: {torchaudio.__version__}')
print(f'triton: {triton.__version__}')
"

# If torch is the CUDA version or torchvision/torchaudio/triton are missing, run the fix script
bash scripts/fix_rocm_torch.sh

# Check HSA_OVERRIDE_GFX_VERSION (required for gfx1100)
echo $HSA_OVERRIDE_GFX_VERSION  # should be 11.0.0

# Check HIP_VISIBLE_DEVICES
echo $HIP_VISIBLE_DEVICES  # should be 0

# Use the launch script (automatically sets all environment variables + --device 0)
bash scripts/start_vllm.sh
```

Common errors and their solutions:

| Error message | Cause | Solution |
|----------|------|----------|
| `Failed to infer device type` | vLLM platform detection requires the `amdsmi` module; if not installed, the ROCm platform cannot be identified | Install amdsmi: `cd /opt/rocm/share/amd_smi && pip install .` + `export LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/opt/rocm/lib:/opt/rocm/lib64` |
| `Failed to infer device type` (DEBUG shows `No module named 'amdsmi'`) | Same as above, vLLM `platforms/__init__.py` fails to `import amdsmi` | Same as above, or use `bash scripts/start_vllm.sh` (automatically detects and installs) |
| `operator torchvision::nms does not exist` | CUDA version of torchvision | `bash scripts/fix_rocm_torch.sh` |
| `libcudart.so.13: cannot open shared object file` | CUDA version of torchaudio | `bash scripts/fix_rocm_torch.sh` |
| `module 'triton' has no attribute 'language'` | CUDA version of triton or leftover directories | `bash scripts/fix_rocm_torch.sh` |
| `libtorch_cuda.so: cannot open shared object file` | CUDA-only `torch_c_dlpack_ext` package (vLLM V1 -> xgrammar -> tvm_ffi dependency chain) | `pip uninstall -y torch_c_dlpack_ext`, or `bash scripts/fix_rocm_torch.sh`; `start_vllm.sh` also detects and uninstalls it automatically |
| `module 'torch.accelerator' has no attribute 'get_memory_info'` | vLLM 0.26.0 uses a torch 2.10+ API, but ROCm 6.3 only has torch 2.9.1; the `sitecustomize.py` patch is not effective in spawn child processes | `python scripts/patch_vllm_source.py` (patches the vLLM source directly); `start_vllm.sh` and `fix_rocm_torch.sh` apply it automatically |
| `'_C' object has no attribute 'get_cuda_view_from_cpu_tensor'` | The PyPI CUDA wheel of vLLM lacks the ROCm C++ extensions, and the V2 Model Runner's UVA Buffer calls an uncompiled operator | `python scripts/patch_vllm_source.py` (UVA fallback patch); the permanent fix is to install the ROCm version of vLLM |
| `Skipping import of cpp extensions ... torch >= 2.11.0` | torchao requires torch 2.11+, but ROCm 6.3 only provides up to 2.9.1 | Non-fatal warning, degrades automatically, inference unaffected |
| `Triton ... 0 active driver(s) found` | Triton compatibility warning on ROCm | No action needed, vLLM degrades automatically |

### 5.3 FAISS Index Building Failure

```bash
# Check the Embedding service
curl http://localhost:8001/v1/models

# Check the document directory (supports PDF/Word/HTML/TXT/MD)
ls docs_data/

# Rebuild (clear the old index)
rm -rf .agently/runs/insurance/index/
rm -rf .agently/runs/insurance/records/
python scripts/build_index.py
```

### 5.4 BM25 / Reranking Unavailable

```bash
# Check whether the dependencies are installed
pip list | grep -E "rank-bm25|sentence-transformers|jieba"

# If missing, install the dependencies
pip install rank-bm25 sentence-transformers jieba

# Verify the BM25 index file
ls .agently/runs/insurance/index/bm25_index.pkl

# Rebuild the index (including BM25)
python scripts/build_index.py
```

> BM25 and Cross-Encoder reranking are optional components; when missing, the system automatically degrades to pure FAISS retrieval.

### 5.5 Agent Connection Timeout

```bash
# Check the vLLM service
curl http://localhost:8000/v1/models

# Check the .env configuration
cat .env | grep LOCAL_LLM_API_KEY

# Check the models.toml configuration
cat configs/models.toml | grep base_url
```

---

## Part 6: Reproduction Validation Checklist

| Validation item | Validation method | Pass criteria |
|--------|----------|----------|
| Environment ready | `rocm-smi` + `python -c "import torch; print(torch.cuda.is_available())"` | GPU visible, returns True |
| PyTorch ecosystem | `python -c "import torch,torchvision,torchaudio,triton; print(torch.__version__,torchvision.__version__,torchaudio.__version__,triton.__version__)"` | All include the `+rocm6.3` suffix |
| Model loading | `curl http://localhost:8000/v1/models` | Returns the model list |
| Index building | `python scripts/build_index.py` | No errors, index files generated |
| BM25 index | `ls .agently/runs/insurance/index/bm25_index.pkl` | File exists |
| Source data storage | `ls .agently/runs/insurance/records/*.json` | chunk JSON files exist |
| Agent startup | `python scripts/start_agent.py` | Enters the interactive prompt |
| Q&A functionality | Enter "the claims process for Employer Liability" | Returns an answer annotated with `[[ref:xxx]]` citations |
| Hybrid retrieval | Log shows "FAISS=X, BM25=Y, after dedup fusion=Z" | All three retrieval paths executed |
| Reranking | Log shows "Cross-Encoder reranking: N candidates → top-M" | Reranking executed |
| RAG benchmark | `python scripts/benchmark_rag.py` | Generates the benchmark report |
| GPU evidence | `bash scripts/collect_gpu_evidence.sh` | Generates the evidence files |
| Performance comparison | `bash scripts/run_benchmark.sh C0` + `C2` | The two groups of data can be compared |