# Intelligent Claims Agent System

> Upload an invoice — automatically complete **multimodal OCR → authenticity verification → medical insurance drug catalog lookup → claims amount calculation** — with support for multi-turn conversational follow-up.
> Large model inference runs on **AMD Radeon GPU + ROCm**. Fully local deployment; your data never leaves your network.
>
> Submission for **AMD Radeon GPU Hackathon · Track 2** (Local AI Agent Application).

---

## Features

- 🖼️ **Multimodal Invoice Recognition**: Vision LLM directly extracts invoice fields + drug line items from images — no OCR templates needed.
- 🛡️ **Official Authenticity Verification**: Connects to the official tax verification API; seller/buyer/amount are cross-checked item by item.
- 📚 **RAG Drug Catalog Retrieval**: Local vector store with three-tier retrieval (exact / semantic / out-of-catalog threshold).
- 🧮 **Deterministic Claims Decision**: Three-tier rules (Category A / Category B / commercial innovative drugs), pure-code calculation, fully auditable.
- 💬 **Conversational UI + Multi-Turn Memory**: Gradio Chat with streaming progress + conclusion card, supports follow-up questions.
- ⚡ **AMD ROCm Inference + Targeted Optimization**: GGUF quantization, full-layer offload, image compression, `/no_think`, streaming, cache warm-up — with built-in benchmark script.

---

## Requirements

| Item | Version / Notes |
|------|-----------------|
| OS | Windows / Linux (client) |
| Python | 3.12 (conda environment recommended) |
| Inference backend | AMD Radeon GPU (gfx1100) + ROCm 7.2.4 + llama.cpp `llama-server` (separate or same machine) |
| Multimodal model | Qwen3 VLM, `Qwen3.6-27B-Q8_0.gguf` (with vision projector) |
| Network | Access to official invoice verification API (for authenticity check); first run downloads embedding model via hf-mirror |

> The Agent / RAG / frontend run on the client CPU; large model inference runs on the AMD Radeon GPU. The two are decoupled via an **OpenAI-compatible HTTP endpoint**.

---

## Quick Start

### Step 0 · Prepare the Inference Backend (AMD Radeon + ROCm)

On a machine with an AMD Radeon GPU, start an OpenAI-compatible service with llama.cpp:

```bash
./llama-server \
  -m /root/Downloads/Qwen3.6-27B-Q8_0.gguf \
  --mmproj <vision-projector.gguf> \
  -ngl 999 \
  --host 0.0.0.0 --port 8080 \
  --ctx-size 8192
```

### Step 1 · Set Up the Tunnel to the Backend

If the backend is on a remote machine, map local port `8000` to backend port `8080` via SSH tunnel:

```bash
ssh -N -L 8000:localhost:8080 -p <ssh-port> <user>@<backend-host>
```

> If the backend is on the same machine at port `8080`, you can skip the tunnel. Just set `MODEL_PORT` to `8080` in `config.py` or via environment variable.

Verify the endpoint is reachable (should return HTTP 200):
```bash
curl http://localhost:8000/v1/models
```

### Step 2 · Create Environment & Install Dependencies

```bash
# conda recommended
conda create -n claim-agent python=3.12 -y
conda activate claim-agent

# install with mirror for faster downloads
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### Step 3 · Build the Drug Catalog Vector Store (run once)

```bash
python -m rag.build_index
```
> First run downloads `bge-small-zh-v1.5` from the HuggingFace mirror (hf-mirror) and builds 24 drug catalog vectors into `data/chroma/`.

### Step 4 · Start the Application

```bash
python app.py
```
Then open **http://localhost:7860** in your browser. Upload an invoice image and click send to see staged progress + the claims conclusion card. You can then continue asking follow-up questions.

---

## Key Configuration (`config.py` / environment variables)

All configuration is centralized in `config.py` and can be overridden by environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `MODEL_HOST` / `MODEL_PORT` | `localhost` / `8000` | Inference endpoint address (tunneled to AMD backend 8080) |
| `MODEL_BASE_URL` | `http://localhost:8000/v1` | OpenAI-compatible endpoint |
| `MODEL_ID` | `/root/Downloads/Qwen3.6-27B-Q8_0.gguf` | Model identifier |
| `LLM_TEMPERATURE` | `0.1` | Sampling temperature (lower = more deterministic) |
| `LLM_TIMEOUT` | `180` | Single inference timeout (seconds) |
| `EMBEDDING_MODEL` | `BAAI/bge-small-zh-v1.5` | Local embedding model |
| `EMBEDDING_DEVICE` | `cpu` | Embedding device (`cpu` / `cuda`; ROCm also identified as `cuda`) |
| `HF_ENDPOINT` | `https://hf-mirror.com` | HuggingFace mirror endpoint |
| `RAG_SCORE_THRESHOLD` | `0.6` | Semantic retrieval threshold; below threshold + not commercial innovative drug → out-of-catalog |
| `VERIFY_URL` | `https://inv-veri.com/check` | Official invoice verification API |
| `DEFAULT_REIMBURSE_RATIO` | `0.7` | Default pooled reimbursement ratio (catalog entries can override) |
| `APP_PORT` | `7860` | Frontend port |

**Windows PowerShell tip**: Set encoding first to avoid Chinese garbled text:
```powershell
$env:PYTHONIOENCODING="utf-8"; $env:PYTHONUTF8="1"
```

---

## Testing & Benchmarking

```bash
# Unit / integration tests (by milestone)
python test_core.py     # M1 backend connectivity + basic OCR/verification
python test_rag.py      # M2 RAG three-tier retrieval regression
python test_tools.py    # M3 four business tools unit tests
python test_agent.py    # M4 Agent tool calling + multi-turn memory + deterministic pipeline

# Inference performance benchmark (AMD ROCm backend)
python bench.py --n 5 --concurrency 8 --vision fapiao2.jpg
```

---

## Project Structure

```
fake_ocr_test/
├── app.py                 # Gradio Chat frontend (conversational + streaming + conclusion card)
├── config.py              # Centralized configuration (endpoint/model/RAG/claims rule params)
├── bench.py               # AMD ROCm inference performance benchmark script
├── requirements.txt       # Dependencies
│
├── tools/                 # Business tools layer (LangChain @tool)
│   ├── ocr_tool.py        # Multimodal invoice extraction
│   ├── verify_tool.py     # Official authenticity verification
│   ├── rag_tool.py        # Drug catalog retrieval wrapper
│   └── decision_tool.py   # Claims rules deterministic calculation
│
├── rag/                   # Retrieval Augmented Generation
│   ├── retriever.py       # Three-tier retriever (exact/semantic/threshold)
│   └── build_index.py     # Offline Chroma vector store construction
│
├── agent/                 # Agent orchestration
│   ├── agent.py           # LLM tool-calling Agent + memory follow-up
│   ├── pipeline.py        # Deterministic claims pipeline (main review, streaming)
│   └── memory.py          # Session memory SessionStore
│
├── data/
│   ├── drug_catalog.json  # Medical insurance drug catalog (24 sample entries)
│   └── chroma/            # Vector store persistence dir (generated by build_index)
│
├── test_core.py / test_rag.py / test_tools.py / test_agent.py   # Tests
├── fapiao.jpg / fapiao2.jpg   # Sample invoices
├── 项目说明文档.md          # Project description (scenario/architecture/capabilities/deployment/AMD optimization)
├── 设计文档.md              # Detailed design document
└── invoice_verify_api.md    # Official verification API documentation
```

---

## Dependencies

See [`requirements.txt`](./requirements.txt). Tested environment (Python 3.12):

| Package | Version | Purpose |
|---------|---------|---------|
| gradio | 5.44.1 | Frontend Chat UI |
| langchain | 1.3.14 | Agent orchestration framework |
| langchain-core | 1.4.9 | Core abstractions (@tool, etc.) |
| langgraph | 1.2.9 | Agent runtime + memory checkpointer |
| langchain-openai | 1.3.5 | OpenAI-compatible endpoint integration |
| langchain-community | 0.4.2 | Community integrations |
| chromadb | 1.5.9 | Vector store |
| sentence-transformers | 5.1.2 | Local embedding |
| numpy | 1.26.4 | Numerical computation |
| requests | 2.32.5 | HTTP calls |
| pydantic | 2.10.6 | Data validation |
| Pillow | 10.4.0 | Image compression preprocessing |

> Note: This project uses **LangChain 1.x new version** (`langchain.agents.create_agent`, based on langgraph), not the legacy 0.2.x `AgentExecutor`.

---

## FAQ

- **What happens if I upload a non-medical invoice (e.g., daily necessities)?**
  The system will find all items are outside the reimbursement catalog (similarity below threshold) and explicitly classify it as "suspected non-medical invoice, not eligible for claims" — no incorrect amount calculation.

- **Can't connect to the endpoint / first token is slow?**
  First run `curl http://localhost:8000/v1/models` to confirm the tunnel and backend are working; make sure `-ngl 999` has offloaded all model layers to the GPU.

- **First upload is slow?**
  The first run loads the embedding model; `app.py` already warms it up in the background on startup. Normally it's ready shortly after you open the interface.

- **Share link creation fails (frpc)?**
  This doesn't affect local usage — just access via `http://localhost:7860`. For public sharing, manually place the frpc file as prompted by Gradio.

---

## Related Documents

- [`项目说明文档.md`](./项目说明文档.md) — Application scenarios, architecture diagram, core capabilities, model deployment, AMD optimization notes
- [`设计文档.md`](./设计文档.md) — Complete design document
- [`invoice_verify_api.md`](./invoice_verify_api.md) — Official verification API documentation
