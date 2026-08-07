# Radeon-Assistant

A local AI agent system that runs on AMD Radeon GPUs via the ROCm software stack. Inference, embedding, and vector search all run on local hardware. This is a learning / development project built for AMD Radeon Hackathon 2026-07 (Track 2 — Private AI Agent Development & Local Deployment).

**Team:** Neoh

---

## Overview

Radeon-Assistant combines a hand-written agent loop (Planner → Executor → Reflector) with a FAISS-backed RAG knowledge base, a registry of built-in tools, and human-in-the-loop approval for high-risk operations. All LLM inference runs locally on an AMD Radeon GPU through vLLM + ROCm — no external API is called during inference.

The project started as a general-purpose local agent framework. Hardware R&D usage scenarios were added later as a specialization layer (see *Hardware R&D specialization* below).

### What it does

- Local document Q&A over a private RAG knowledge base (PDF / DOCX / MD / TXT)
- File / shell / Python / system operations via natural-language tool calls
- Multi-step task planning with self-reflection and retry
- Human-in-the-loop approval for high-risk operations, with a JSON-Lines audit log
- (Specialized) hardware R&D assistance: hardware-domain system prompt, local Verilog / SystemVerilog module and testbench generation, and chip-datasheet table / pin extraction for the knowledge base

### Scope / limitations (objective)

- Verilog / testbench generation is LLM-based text generation; it is **not** connected to a simulator (e.g. iverilog) for automatic verification.
- The hardware features are usage-scenario specializations on top of a general agent framework, not a from-scratch EDA engine.
- Model selection is backed by a local throughput / latency benchmark (`docs/benchmark_qwen2.5-14b.md`); 14B is the tested default, 7B also runs.

---

## Key features

| Feature | Implementation |
|---------|---------------|
| Local inference | Qwen2.5 (14B-Instruct FP16 by default; 7B also tested) via vLLM + ROCm |
| RAG knowledge base | FAISS (IndexFlatL2) + all-MiniLM-L6-v2 embeddings; PDF / DOCX / MD / TXT |
| Tool calling | 14 built-in tools across file / shell / code / system / hardware categories |
| Multi-step planning | Planner decomposes → Executor runs → Reflector evaluates → retry if needed |
| Human-in-the-loop | High-risk operations (delete, command exec, code exec) require explicit approval |
| Audit logging | JSON-Lines audit log records tool calls, approvals, tasks |
| Memory | Short-term conversation buffer (20 messages) + long-term vector retrieval |
| Interfaces | Streamlit Web UI + CLI |

---

## Architecture

The system is organized into layers:

1. **User layer** — Streamlit Web UI and CLI entry points
2. **Agent layer** — Planner (task decomposition) → Executor (step execution) → Reflector (result evaluation)
3. **Safety layer** — human-in-the-loop approval gate + audit logger
4. **Tool layer** — 14 registered tools (file / shell / code / system / hardware)
5. **Memory layer** — short-term buffer + FAISS long-term vector store with document parser
6. **Inference layer** — vLLM with ROCm backend, Qwen2.5 model
7. **Hardware layer** — AMD Radeon GPU (tested on Radeon Pro W7900)

> Architecture diagram: `docs/architecture.png` (if present in your checkout).

---

## Project structure

```
submissions/Neoh/
├── agent/ # Agent core
│ ├── core.py # RadeonAgent main loop
│ ├── planner.py # Task decomposition
│ ├── executor.py # Step execution with HITL approval
│ ├── reflector.py # Result evaluation
│ ├── audit.py # Audit logger (JSON-Lines)
│ └── prompts.py # System prompt templates (generic / hardware)
├── inference/ # LLM inference
│ ├── engine.py # vLLM wrapper
│ └── model_loader.py # Multi-source model downloader
├── memory/ # Memory & RAG
│ ├── manager.py # Memory manager
│ ├── vector_store.py # FAISS vector store
│ └── document_parser.py # PDF / DOCX / MD / TXT parser (tables extracted from PDF)
├── tools/ # Tool registry
│ ├── registry.py # Tool registration center
│ ├── file_tools.py # File operations
│ ├── shell_tools.py # Command execution
│ ├── code_tools.py # Code interpreter
│ ├── system_tools.py # System info
│ └── hardware_tools.py # Hardware R&D tools (Verilog / testbench generation)
├── ui/
│ └── web_app.py # Streamlit frontend
├── scripts/ # Helper + doc-generation scripts
│ ├── download_model.py # Model download CLI
│ ├── init_rag.py # General RAG initialization CLI
│ ├── init_hardware_rag.py # Hardware knowledge-base initialization CLI
│ ├── serve.py # OpenAI-compatible server
│ ├── benchmark.py # Throughput / latency benchmark
│ ├── generate_spec.py # Build docs/project_spec.pdf
│ ├── generate_architecture.py # Build docs/architecture.png
│ └── generate_poster.py # Build docs/poster.png
├── docs/ # Specification, reports, posters, architecture diagram
│ ├── project_spec.pdf # Track 2 specification (PDF)
│ ├── architecture.png # System architecture diagram
│ ├── poster.png # Single-page poster
│ ├── POSTER.md # Poster source content
│ ├── TEST_REPORT.md / TEST_REPORT.zh-CN.md # Functional test reports
│ ├── benchmark_qwen2.5-14b.md / .json # Benchmark results
│ ├── DIFY_INTEGRATION.md # Dify wiring guide
│ ├── CLOUD_RUN.md # Radeon Cloud bring-up runbook
│ └── PROJECT_PLAN.md # Project planning notes
├── notebooks/
│ └── startup.ipynb # JupyterLab startup / demo notebook
├── app.py # Entry point (web / cli)
├── config.yaml # Configuration
├── requirements.txt # Python dependencies
├── install_rocm.sh # Linux install script (ROCm-only)
├── setenv-rocm.sh # ROCm env loader (source before running)
├── SUBMISSION.md # Submission checklist (requirement → file map)
└── .gitignore
```

> Tool counts: 5 file + 2 shell + 2 code + 3 system + 2 hardware = 14 registered tools.

---

## Environment requirements

### Hardware

- **GPU:** AMD Radeon Pro W7900 / RX 7900 series (or any ROCm-supported Radeon)
- **VRAM:** ≥ 16 GB for Qwen2.5-7B FP16; ~30 GB for 14B FP16
- **RAM:** ≥ 16 GB
- **Storage:** ≥ 10 GB (model + dependencies)

### Software

- **OS:** Ubuntu 22.04+ (ROCm); Windows via WSL2
- **Python:** 3.14
- **ROCm:** 7.14 (tested)
- **vLLM:** 0.23.1.dev1+rocm7.14.0 (ROCm pre-built wheel, Python 3.14)
- **torch / torchvision / torchaudio:** 2.11.0 / 0.26.0 / 2.11.0 +rocm7.14.0
- **flash-attn:** 2.8.3 (ROCm build)

> **ROCm-only — CUDA is blacklisted.** This is an AMD ROCm environment with no NVIDIA GPU / CUDA runtime. The deep-learning stack (torch / vllm / flash-attn / xformers) must come **only** from AMD ROCm sources (`repo.amd.com`, `rocm.frameworks.amd.com`), never from PyPI / Tsinghua (those serve CUDA wheels that fail with `libcuda.so.1`). Do **not** run `pip install -r requirements.txt` for the DL stack — use `install_rocm.sh` (the exact commands are baked into that script).
>
> **Note on gfx1100:** W7900 / RX 7900 are gfx1100. vLLM must be told to recognize them via `HSA_OVERRIDE_GFX_VERSION=11.0.0` (set automatically in `app.py` / `scripts/serve.py`). Windows desktop cannot run ROCm inference — use Linux + AMD GPU (e.g. Radeon Cloud).

---

## Installation

### Step 1: Clone

```bash
git clone https://github.com/RainmeoX/Radeon-hackathon-2026-07.git
cd Radeon-hackathon-2026-07/submissions/Neoh
```

### Step 2: Virtual environment (Python 3.14)

```bash
# 推荐用 uv 创建 Python 3.14 venv（install_rocm.sh 默认目标 /opt/venv314）
uv python install 3.14
uv venv --python 3.14 /opt/venv314
source /opt/venv314/bin/activate # Linux
# venv\Scripts\activate # Windows (WSL2 内亦可用)
```

### Step 3: Install vLLM (ROCm wheel)

```bash
bash install_rocm.sh # Linux / WSL2
```

Installs dependencies and `vllm` from the official ROCm pre-built wheel.

### Step 4: Download the model

```bash
python scripts/download_model.py --model qwen2.5-14b
```

Supports HuggingFace Hub / hf-mirror / ModelScope with fallback. Model saved to `./models/Qwen2.5-14B-Instruct/`.

### Step 5: (Optional) Initialize RAG

```bash
mkdir -p data/documents
# cp your.pdf your.docx your.md data/documents/
python scripts/init_rag.py
```

---

## Configuration

Edit `config.yaml`. Notable fields:

```yaml
model:
  path: "./models/Qwen2.5-14B-Instruct" # 7B also works
  engine: vllm
  n_ctx: 8192
  gpu_memory_utilization: 0.90
  temperature: 0.7
  max_tokens: 4096

agent:
  max_iterations: 10
  memory_enabled: true
  prompt_template: "hardware" # "hardware" (default) or "generic"
  tools:
    - read_file / write_file / delete_file / list_directory / create_directory
    - execute_command / execute_python / code_interpreter / format_code
    - get_system_info / get_gpu_info / get_process_list
    - generate_verilog / generate_testbench # hardware specialization

rag:
  vector_store: "faiss"
  embedding_model: "all-MiniLM-L6-v2"
  chunk_size: 512
  chunk_overlap: 50
  top_k: 5

security:
  audit_log_enabled: true
  require_approval_for: [delete_file, write_file, execute_command, execute_python, code_interpreter]
```

---

## Usage

### Web UI

```bash
source setenv-rocm.sh   # 加载 ROCm 环境 + 激活 venv（新 shell 时执行一次）
python app.py --mode web --port 7860
```

Open `http://localhost:7860`. Chat with RAG context, upload documents, view history.

### CLI

```bash
source setenv-rocm.sh   # 加载 ROCm 环境 + 激活 venv（新 shell 时执行一次）
python app.py --mode cli
```

- Type a message for chat.
- `task <description>` — run a multi-step planned task.
- `quit` / `exit` — leave.

### Hardware R&D specialization

Set `agent.prompt_template: "hardware"` (default) so the agent answers in a hardware-R&D framing and cites datasheet sources by name. To build a hardware knowledge base:

```bash
mkdir -p data/hardware_documents
# cp your datasheets / reference manuals / errata here
python scripts/init_hardware_rag.py
```

PDF tables (pin tables, parameter tables) are extracted and indexed so they become searchable. The `generate_verilog` / `generate_testbench` tools let the planner produce Verilog / SystemVerilog modules and testbenches locally (written to `./generated/`).

---

## AMD Radeon GPU notes

| GPU | Model | Generation speed | VRAM |
|-----|-------|------------------|------|
| Radeon Pro W7900 | Qwen2.5-14B FP16 | ~27.5 tokens/s (measured) | ~30 GB |
| Radeon Pro W7900 | Qwen2.5-7B FP16 | ~46 tokens/s (measured) | ~15 GB |

Measured on AMD Radeon Cloud (Radeon Pro W7900D, 48 GB VRAM, single GPU, ROCm 7.14, vLLM 0.23.1, Python 3.14).

---

## Safety & privacy

- All LLM inference, embedding, and vector search run locally on the AMD GPU; no external API is called during inference.
- High-risk tools (`delete_file`, `write_file`, `execute_command`, `execute_python`, `code_interpreter`) pause for explicit user approval before execution.
- Significant events are recorded in `logs/audit.log` (JSON Lines). Chat content is logged as length summaries only.

---

## Test report

Functional test reports covering the agent loop, RAG, tool calling, hardware R&D tools, HITL approval, serving, and web UI are available:

- English: [`docs/TEST_REPORT.md`](docs/TEST_REPORT.md)
- 中文：[`docs/TEST_REPORT.zh-CN.md`](docs/TEST_REPORT.zh-CN.md)

## Demo video
https://t.bilibili.com/1233490160518168609?share_source=pc_native

A throughput / latency benchmark on the Radeon Pro W7900 is also recorded in [`docs/benchmark_qwen2.5-14b.md`](docs/benchmark_qwen2.5-14b.md).

---

## Dependencies

See `requirements.txt`. Key CPU-side packages: `faiss`, `sentence-transformers`, `streamlit`, `pdfplumber`, `python-docx`, `psutil`, `pydantic`, `pyyaml`. The deep-learning stack (`torch`, `vllm`, `flash-attn`, `transformers`) is installed by `install_rocm.sh` from AMD ROCm sources only — never via plain `pip` (which would pull CUDA builds).

---

## License

MIT
