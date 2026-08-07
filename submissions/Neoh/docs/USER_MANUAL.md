# Radeon-Assistant — User & Operation Manual

> Work name: **Radeon-Assistant** (磐石 / "Bedrock")
> Team: **Neoh** · Track 2 — Private AI Agent Development & Local Deployment
> Everything in this manual runs **100 % locally on an AMD Radeon GPU** (ROCm). No external API is called during inference.

This manual is written for a first-time operator (including a judge) who has access to a Linux host with an AMD Radeon GPU. It covers installation, start-up, every screen of the Web UI, the CLI, all 15 agent skills, knowledge-base management, the OpenAI-compatible server, and troubleshooting.

For the **evaluation walkthrough** (what to click, in what order, and what to expect) see [`EVALUATION.md`](EVALUATION.md).

---

## 1. Prerequisites

| Item | Requirement | Verified configuration |
|---|---|---|
| GPU | ROCm-supported AMD Radeon (gfx1100 class) | Radeon Pro W7900D, 48 GB |
| VRAM | ≥ 30 GB for Qwen2.5-14B FP16 (≥ 16 GB for 7B) | 48 GB |
| OS | Ubuntu 22.04+ (or WSL2 on Windows) | Ubuntu 22.04, glibc 2.35 |
| Python | 3.14 | 3.14.3 (`/opt/venv314`) |
| ROCm | 7.14 | 7.14 |
| Stack | vLLM + torch from **AMD ROCm sources only** | vLLM 0.23.1.dev1+rocm7.14.0, torch 2.11.0+rocm7.14.0 |

> **ROCm-only.** This project targets AMD GPUs. Installing the deep-learning stack from PyPI pulls CUDA wheels that fail with `libcuda.so.1: cannot open shared object file`. Always use `install_rocm.sh`, which pins the AMD wheel indexes.

---

## 2. Installation (one time)

```bash
git clone https://github.com/RainmeoX/Radeon-hackathon-2026-07.git
cd Radeon-hackathon-2026-07/submissions/Neoh

# 1) Create the Python 3.14 venv and install the ROCm stack
bash install_rocm.sh                  # creates /opt/venv314, installs torch/vLLM/flash-attn (ROCm)

# 2) Download the model (~28 GB for 14B; 7B and 32B are also supported)
source setenv-rocm.sh
python scripts/download_model.py --model qwen2.5-14b

# 3) Build the hardware knowledge base from the bundled datasheets
python scripts/init_hardware_rag.py
```

`install_rocm.sh` also builds a small **glibc 2.35 compatibility shim** (`/opt/venv314/lib/libisoc23_shim.so`) that the AMD wheels need on Ubuntu 22.04. `setenv-rocm.sh` injects it via `LD_PRELOAD`.

### Environment loader — always source this first

```bash
source setenv-rocm.sh
```

It sets `LD_PRELOAD` (glibc shim), `HSA_OVERRIDE_GFX_VERSION=11.0.0`, `PYTORCH_ROCM_ARCH=gfx1100`, `FLASH_ATTENTION_TRITON_AMD_ENABLE=TRUE`, `PYTHONPATH` (amd_smi), and activates the venv. Override the venv with `VENV=/your/venv source setenv-rocm.sh`.

---

## 3. Starting the project

### 3.1 Web UI (recommended for demos)

```bash
source setenv-rocm.sh
python app.py --mode web --port 7860
```

Open <http://localhost:7860>. If you run on a remote box, forward the port (`ssh -L 7860:127.0.0.1:7860 user@host`).

* The model is **lazy-loaded on the first message**, not at page load. The first answer therefore takes ≈ 75–90 s (weight load + warm-up); every later answer is fast.
* Model, agent, and memory objects are cached with `st.cache_resource`, so they survive page reloads.

### 3.2 CLI

```bash
source setenv-rocm.sh
python app.py --mode cli
```

| Input | Effect |
|---|---|
| any text | Chat with RAG context |
| `task <description>` | Run the full Planner → Executor → Reflector loop with tools |
| `quit` / `exit` | Leave |

In CLI mode, high-risk tools stop and ask for approval on the terminal (`y/N`).

### 3.3 OpenAI-compatible server (for Dify or any OpenAI client)

```bash
source setenv-rocm.sh
python scripts/serve.py --model qwen2.5-14b        # listens on :8000/v1
```

See [`DIFY_INTEGRATION.md`](DIFY_INTEGRATION.md) for the Dify wiring.

### 3.4 Stopping / restarting

```bash
pkill -f "ui/web_app.py"            # stop the Web UI
pkill -9 -f "VLLM::"                # release VRAM if a worker is orphaned
rocm-smi --showmemuse               # confirm VRAM is back to 0 %
```

A killed Streamlit process can leave a `VLLM::EngineCore` worker holding ~28 GB. Always check `rocm-smi` before restarting, otherwise the next start fails to allocate KV cache.

---

## 4. Web UI guide

The interface is a single centred conversation column with a control sidebar on the left.

### 4.1 Sidebar

| Section | Control | What it does |
|---|---|---|
| **Brand** | `🤖 Bedrock` | Product identity; subtitle shows the active persona |
| — | **+ New chat** | Clears the conversation and the agent's short-term memory (long-term RAG index is kept) |
| **Interaction** | `Chat (RAG)` / `Agent Task (tools)` | Switches between retrieval-augmented Q&A and the tool-calling agent loop (see §4.3) |
| **Appearance** | `Dark mode` toggle | Light / dark theme; all colours come from a single token table |
| **Assistant mode** | `Hardware R&D` / `General` | Selects the system prompt (`hardware` is the default persona) |
| **Knowledge base** | Indexed-chunk badge, uploader, `Clear document index` | Shows how many chunks are searchable, indexes new PDF/DOCX/MD/TXT files on upload, or wipes the FAISS index |
| **Actions** | `Reload model` | Drops the cached engine/agent so the next message reloads the model (use after editing `config.yaml`) |

### 4.2 Main area

* **Welcome screen** — shown when the conversation is empty; four one-click suggestion chips seed a typical hardware question.
* **Message list** — user messages appear as blue bubbles, assistant messages as light grey blocks. Markdown and syntax-highlighted code are rendered.
* **Sources** — after a `Chat (RAG)` answer, a `Sources (n)` expander lists every retrieved chunk with its source file name, so an answer can be traced back to the datasheet it came from.
* **Composer** — the bottom input accepts multi-line text; `Enter` sends.

### 4.3 The two interaction modes

| Mode | Pipeline | Use it for |
|---|---|---|
| **Chat (RAG)** | embed query → FAISS top-k over the local manuals → inject chunks + last 5 turns → single LLM completion | "What is the I2C address of …", "Explain the working principle of …", datasheet comparisons |
| **Agent Task (tools)** | **Planner** (LLM → JSON step list, ≤ 5 steps) → **Executor** (runs each registered tool, HITL gate) → **Reflector** (LLM judges success) | "Generate a Verilog module …", "Read this file and summarise it", "Report GPU status" |

In `Agent Task` mode the reply is rendered as a structured trace: task status, then one block per step showing the step description, the tool that was invoked, and the raw tool output, followed by the reflector's verdict. This makes the agent's reasoning auditable rather than a black box.

---

## 5. Skills (14 registered tools)

All tools are registered in `tools/` and listed in `config.yaml → agent.tools`. Names must match exactly.

| # | Tool | Category | Approval | Example prompt (Agent Task mode) |
|---|---|---|---|---|
| 1 | `read_file` | file | no | "Read data/hardware_documents/W25Q128JV_SPI_Flash_Datasheet_sample.txt" |
| 2 | `write_file` | file | **yes** | "Write a summary of the TMP117 specs to generated/tmp117.md" |
| 3 | `delete_file` | file | **yes** | "Delete generated/scratch.txt" |
| 4 | `list_directory` | file | no | "List the files under data/hardware_documents" |
| 5 | `create_directory` | file | no | "Create a directory called generated/rtl" |
| 6 | `execute_command` | shell | **yes** | "Run `rocm-smi --showproductname`" |
| 7 | `execute_python` | code | **yes** | "Run Python that prints the I2C addresses 0x48–0x4B" |
| 8 | `code_interpreter` | code | **yes** | "Compute the RC time constant for R=10k, C=100nF" |
| 9 | `format_code` | code | no | "Format the Python file scripts/benchmark.py with black" |
| 10 | `get_system_info` | system | no | "Report the system information of this machine" |
| 11 | `get_gpu_info` | system | no | "Show the GPU status" |
| 12 | `get_process_list` | system | no | "Show the top processes by memory" |
| 13 | `generate_verilog` | hardware | no | "Generate a Verilog module for an I2C slave with an 8-bit register file" |
| 14 | `generate_testbench` | hardware | no | "Write a Verilog testbench for a 4-bit ALU named alu4" |
| 15 | `simulate_verilog` | hardware | no | "Compile and simulate generated/alu4_tb.v with iverilog/vvp" |

Generated HDL is written to `./generated/`.

> **Scope note.** `generate_verilog` / `generate_testbench` are LLM-based generation specialised by a hardware system prompt and datasheet RAG context. The generated HDL can be verified locally via the `simulate_verilog` tool, which compiles the design with **iverilog** and runs it with **vvp**, returning compile/simulation logs and a pass/fail verdict. This closes the loop from generation to simulation, though it is still a drafting aid for an engineer rather than a full EDA flow.

---

## 6. Knowledge base (RAG)

### 6.1 What is indexed

`memory/document_parser.py` handles four formats; PDF parsing uses `pdfplumber` and **extracts tables** (pin tables, electrical-characteristics tables) into the text stream so that numeric specs become searchable.

| Format | Parser | Notes |
|---|---|---|
| PDF | pdfplumber | text + tables; scanned/image-only PDFs yield no text |
| DOCX | python-docx | paragraphs + tables |
| MD | markdown | headings preserved |
| TXT | plain read | — |

Chunking: 512 characters with 50-character overlap; embeddings `all-MiniLM-L6-v2`; index FAISS `IndexFlatL2` persisted at `data/faiss_index/`.

### 6.2 Bundled hardware corpus

`data/hardware_documents/` ships a deliberately multi-format, multi-language corpus so retrieval can be judged end-to-end:

| File | Format | Content |
|---|---|---|
| `TMP117_Temperature_Sensor_Datasheet.pdf` | PDF (EN) | TI high-accuracy digital temperature sensor |
| `SN74LVC1G00_Logic_Gate_Datasheet.pdf` | PDF (EN) | TI single 2-input NAND gate |
| `CP2102_USB_UART_Datasheet.pdf` | PDF (EN) | Silicon Labs USB-to-UART bridge |
| `CW32L012_UserManual_CN_V1.3.pdf` | PDF (ZH) | Chinese MCU user manual |
| `RP2040_PicoSDK_README.md` | Markdown | Raspberry Pi Pico SDK overview |
| `LMT75_I2C_TempSensor_Datasheet_sample.docx` | DOCX | I²C temperature-sensor sample datasheet |
| `W25Q128JV_SPI_Flash_Datasheet_sample.txt` | TXT | SPI NOR flash sample datasheet |

Rebuild the index after changing the folder:

```bash
source setenv-rocm.sh
python scripts/init_hardware_rag.py     # hardware corpus
python scripts/init_rag.py              # general corpus (data/documents/)
```

Both write into the same `data/faiss_index/`.

### 6.3 Uploading from the UI

Sidebar → **Knowledge base** → drag files in. Each file is saved to `data/documents/` and indexed immediately; the chunk badge updates. `Clear document index` empties the vector store (files on disk are kept).

---

## 7. Safety, approval and audit

* Tools flagged `requires_approval=True` (`delete_file`, `write_file`, `execute_command`, `execute_python`, `code_interpreter`) pass through an approval gate in `agent/executor.py` before running. The list lives in `config.yaml → security.require_approval_for` and must stay in sync with the tool definitions.
* **CLI:** the gate prompts on the terminal and blocks until you answer.
* **Web UI:** a blocking terminal prompt is impossible inside a Streamlit script run, so the gate is driven by the sidebar **Tool safety** setting (see §4.1); every decision is still recorded.
* All tool calls, approval decisions, task runs and chat events are appended to `logs/audit.log` as JSON Lines. Chat bodies are **not** stored — only lengths — so the audit trail cannot leak private content.

---

## 8. Configuration reference (`config.yaml`)

| Key | Default | Meaning |
|---|---|---|
| `model.path` | `./models/Qwen2.5-14B-Instruct` | Local weights directory (safetensors) |
| `model.dtype` | `float16` | FP16 on gfx1100 |
| `model.gpu_memory_utilization` | `0.90` | Fraction of VRAM vLLM may claim |
| `model.n_ctx` | `8192` | Context window |
| `model.max_tokens` | `4096` | Max generated tokens |
| `model.tensor_parallel_size` | `1` | >1 needs multi-GPU + `VLLM_WORKER_MULTIPROC_METHOD=spawn` |
| `agent.prompt_template` | `hardware` | `hardware` (磐石 persona) or `generic` |
| `agent.max_iterations` | `10` | Planner/executor loop budget |
| `rag.top_k` | `5` | Chunks injected per query |
| `rag.chunk_size` / `chunk_overlap` | `512` / `50` | Chunking |
| `ui.port` | `7860` | Web UI port |
| `security.require_approval_for` | 5 tools | High-risk gate |

After editing, click **Reload model** in the sidebar (or restart) so the cached engine picks the change up.

---

## 9. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `ImportError: libcuda.so.1` | A CUDA wheel was installed | Reinstall torch/vLLM from AMD indexes via `install_rocm.sh` |
| `version GLIBC_2.38 not found` | Missing glibc shim | `source setenv-rocm.sh` (sets `LD_PRELOAD`); rebuild the shim with `install_rocm.sh` |
| vLLM does not recognise the GPU | `HSA_OVERRIDE_GFX_VERSION` unset | `source setenv-rocm.sh`; `app.py` also sets it before importing torch |
| First answer hangs ~80 s | Model weights loading | Expected; later answers are fast |
| Out of memory on start | Orphaned `VLLM::EngineCore` still holds VRAM | `pkill -9 -f "VLLM::"`, verify with `rocm-smi --showmemuse` |
| Upload says "could not extract text" | Scanned / image-only PDF | Provide a text PDF; OCR is out of scope |
| `streamlit: not found` | venv not active | `source setenv-rocm.sh`; `app.py` resolves the venv binary automatically |
| Web UI reachable but empty | Streamlit still booting | Wait a few seconds and reload |

---

## 10. File map (where to look)

```
submissions/Neoh/
├── app.py                     # entry point: --mode web | cli  (sets ROCm env first)
├── config.yaml                # single source of truth
├── setenv-rocm.sh             # runtime environment loader
├── install_rocm.sh            # ROCm-only installer
├── agent/                     # planner / executor / reflector / audit / prompts
├── inference/engine.py        # vLLM wrapper
├── memory/                    # FAISS vector store + document parser + manager
├── tools/                     # 14 registered tools
├── ui/web_app.py              # Streamlit Web UI
├── scripts/                   # model download, RAG init, serve, benchmark, doc generators
├── data/hardware_documents/   # bundled multi-format datasheet corpus
├── data/faiss_index/          # persisted vector index
├── generated/                 # HDL and files produced by the agent
└── logs/audit.log             # JSON-Lines audit trail
```
