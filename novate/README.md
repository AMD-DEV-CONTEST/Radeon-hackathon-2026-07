# Nova — Private Local Research Assistant

**AMD AI DevMaster Hackathon — Track 2: Development & Local Deployment of Private AI Agents**

Nova is a fully local, private AI agent that answers questions grounded in your
own documents (RAG), invokes local tools, and remembers conversation context —
all running on an **AMD Radeon GPU** via the **ROCm** software stack. No
document or query is sent to a third-party API for core functionality.

## Core capabilities implemented

| Capability | How |
|---|---|
| **Local knowledge retrieval (RAG)** | Documents chunked, embedded, and stored in a persistent local **Chroma** vector DB; queries retrieve the closest chunks. |
| **Tool invocation** | A lightweight router matches intents like "list files", "read file X", "calculate ..." to local Python functions. |
| **Local multi-turn memory** | A bounded in-memory conversation window is included in every prompt so Nova handles natural follow-ups. |
| **Permission control & privacy protection** | File tools are hard-restricted to an allow-list of directories (`config.ALLOWED_TOOL_DIRS`); any path outside it is refused. |

## Architecture

```
User (Gradio UI)
      │
      ▼
 NovaAgent.ask()
      │
      ├─► Intent router ──► matched? ─► Tool (list_files / read_file / calculator)
      │                                        (permission-checked against ALLOWED_TOOL_DIRS)
      │
      ├─► not matched? ──► VectorStore.query() ──► Chroma (local, persistent)
      │                                                   embeddings via sentence-transformers
      │
      ├─► ConversationMemory (bounded window, in-process)
      │
      ▼
 Prompt assembly (system + memory + context + user turn)
      │
      ▼
 LocalLLMClient ──► OpenAI-compatible vLLM endpoint (Radeon Cloud Dedicated Model API)
      │
      ▼
 Model inference on AMD Radeon GPU (ROCm), deployed via radeon-global.anruicloud.com
```

## Repository layout

```
private-local-agent/
├── app.py                  # Gradio chat UI (demo entrypoint)
├── ingest.py                # CLI: build/refresh the local vector DB
├── config.py                 # Central configuration (env-overridable)
├── requirements.txt
├── .env.example
├── data/sample_docs/          # Sample document(s) — replace with your own
├── chroma_db/                 # Persistent local vector store (generated)
├── scripts/
│   └── deploy_notes.md         # Radeon Cloud vLLM Dedicated Model API deployment notes
├── src/
│   ├── llm_client.py          # Client for the local OpenAI-compatible server
│   ├── embeddings.py          # Local embedding model wrapper (GPU-aware)
│   ├── vectorstore.py         # Chroma persistence + chunking + retrieval
│   ├── memory.py               # Bounded multi-turn conversation memory
│   ├── tools.py                 # Tool implementations + permission allow-list
│   └── agent.py                  # Orchestrator: routing, prompt assembly
└── tests/
    └── test_agent.py               # Unit tests (mocked LLM/store — no GPU needed)
```

## Environment setup (AMD Radeon GPU via Radeon Cloud)

Nova's core inference runs on an AMD Radeon GPU provisioned through
[Radeon Cloud](https://radeon-global.anruicloud.com/), using the platform's
built-in **vLLM Dedicated Model API** deploy type. This is the reproducible
path an evaluator would follow — no manual ROCm/llama.cpp build required for
the LLM server itself.

1. **Get a GPU instance serving your model (Radeon Cloud → Dedicated Model API):**
   - Log in at https://radeon-global.anruicloud.com/
   - Profile → **Add Template** → set **Deploy Type = vLLM Model API**
   - Fill in the **Serve Command**, keeping the required host/port:
     ```bash
     vllm serve <model-name> --host 0.0.0.0 --port 8000
     ```
   - Click **Add Template**, then **Launch** it from **My Templates**.
   - Once ready, the instance details show a dedicated **Base URL**
     (`.../spaces/<id>/8000/v1`), **Model** name, and **API Key** — copy all three.

   *(Optional, for fast local iteration before you have a dedicated instance
   running: Radeon Cloud also offers free shared endpoints — Token Factory →
   Public Free Model APIs — for quick testing. Switch to your own Dedicated
   Model API instance before recording the demo video, since core inference
   must run on your own AMD Radeon GPU deployment for this track.)*

2. **Get a workspace to run Nova itself** (same Radeon Cloud account):
   - Add/launch a second template (or reuse the same instance) and open its
     **JupyterLab** ("Open Notebook") for a full in-browser Linux terminal —
     no local ROCm setup needed on your own machine.
   - Alternatively, connect via **SSH** (Profile → add your SSH public key,
     enable "SSH Access (advanced)" on the template, then `ssh <user>@<host> -p <port>`).

3. **Install Python dependencies** (inside the JupyterLab terminal or SSH session):
   ```bash
   python -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   cp .env.example .env
   ```

4. **Point Nova at your deployed model** — edit `.env`:
   ```bash
   NOVA_LLM_BASE_URL=<the Base URL from step 1, e.g. https://.../spaces/<id>/8000/v1>
   NOVA_LLM_MODEL_NAME=<the model name you passed to `vllm serve`>
   NOVA_LLM_API_KEY=<the API Key from step 1>
   ```

5. **(Optional) ROCm-enabled PyTorch** for GPU-accelerated local embeddings —
   most Radeon Cloud container images ship this already; if not:
   ```bash
   pip install torch --index-url https://download.pytorch.org/whl/rocm6.1
   ```

## Startup guide

**Step 1 — Confirm your vLLM endpoint is live** (from step 1 above):
```bash
curl <NOVA_LLM_BASE_URL>/chat/completions \
  -H "Authorization: Bearer <NOVA_LLM_API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{"model":"<NOVA_LLM_MODEL_NAME>","messages":[{"role":"user","content":"Hello"}]}'
```

**Step 2 — Build the local knowledge base:**
```bash
python ingest.py
```
This embeds and indexes everything under `data/sample_docs/` (replace with
your own `.txt`/`.md` files first, then re-run).

**Step 3 — Launch the assistant UI:**
```bash
python app.py
```
Open `http://localhost:7860` in your browser — or expose it publicly from a
Radeon Cloud Notebook with `rc-tunnel` (see `scripts/deploy_notes.md`).

**Step 4 — Try it:**
- "List the files you have access to" → tool invocation
- "Calculate: (24 * 7) + 15" → tool invocation
- "What does the sample document say about ROCm?" → RAG retrieval
- Ask a follow-up without repeating context → multi-turn memory
- Ask Nova to read a file outside `data/sample_docs/` → permission control refuses it

**Step 5 — When done, destroy the instance** (Profile → Active Instance →
**Destroy Instance**) so it stops consuming credits.

## Running tests

Tests mock the LLM and vector store so they run without a GPU or live server:
```bash
pytest tests/ -v
```

## Dependency list

See `requirements.txt`. Key libraries: `openai` (client for the local
OpenAI-compatible server), `chromadb` (local vector store), `sentence-transformers`
(local embeddings), `gradio` (UI), `pytest` (tests).

## Inference speed optimization notes (ROCm / vLLM on Radeon Cloud)

- vLLM's continuous batching and PagedAttention (used automatically by
  `vllm serve`) give strong throughput on a single Radeon GPU without extra
  tuning.
- Prefer a quantized model variant (e.g. AWQ/GPTQ builds where available) to
  reduce VRAM pressure and increase throughput on a single GPU instance.
- The embedding model (`bge-small-en-v1.5`) is intentionally lightweight so
  RAG retrieval doesn't compete heavily with the main LLM for GPU resources.
- Conversation memory is capped (`NOVA_MEMORY_MAX_TURNS`) to bound prompt
  length and keep per-turn latency predictable.
- Keep the vLLM serve command's `--host 0.0.0.0 --port 8000` exactly as
  required by the platform — changing the port breaks the routed Base URL.

## Privacy & permission model

All file-access tools resolve and validate paths against
`config.ALLOWED_TOOL_DIRS` before touching disk. Requests for paths outside
this allow-list are refused with an explicit error — this holds regardless
of how the request is phrased, satisfying the "permission control & privacy
protection" capability for this track.
