# Diary App — Deployment / Testing / Release Plan

> Local voice diary web app. Builds on the existing GraphVoice stack in this repo
> (VAD + Whisper-tiny WebGPU + graph agent + TTS) and the Bionic-Graph engine at
> `127.0.0.1:8088`. Status: plan locked, implementation started on branch `diary/app`.

## 0. Decisions (locked)
- **LLM**: `RobinsonLabs/Qwen3.6-35B-A3B-abliterated-GGUF` (MoE, ~3B active),
  cached at `/home/pdfexe/.cache/huggingface/hub/models--RobinsonLabs--Qwen3.6-35B-A3B-abliterated-GGUF/.../Qwen3.6-35B-A3B-abliterated-IQ4_XS.gguf`
  (19.2 GB, IQ4_XS). Run locally via **llama.cpp Vulkan** (see §1).
- **Graph**: one shared graph, local single-user app. Rich node types (people, places,
  events, daily-life facets).
- **TTS**: local (Kokoro), not cloud Qwen.
- **Deploy**: this box only (self-hosted, single node).

## 1. Runtime / deployment (LOCAL GPU via ROCm — verified)
- The prebuilt llama.cpp at `~/envs/llama.cpp` is compiled with **ROCm/HIP** and detects
  the AMD GPU as `ROCm0` (all 42 layers offload, ~18 GB VRAM for the IQ4_XS GGUF).
  `rocminfo` does NOT list the GPU, but llama.cpp's HIP runtime does — so the LLM runs on
  the GPU natively; no Vulkan build needed.
- Serve the cached GGUF via `llama-server` (OpenAI-compatible API) on
  **`http://127.0.0.1:8089/v1`**. Startup script: `scripts/start_llm_server.sh`.
  ~3B active params → fast turns; IQ4_XS leaves headroom in 48 GB for KV cache + context +
  TTS. NOTE: Qwen3.6 engages "thinking"/CoT by default — the agent should control
  `thinking`/`reasoning` per call (disable for low-latency interviewer turns).
- **TTS**: local **Kokoro** (pip install; multilingual incl. Chinese; tiny, CPU or GPU).
  Replaces `tts/qwen_tts_client.py`. (Install + wiring = Slice 3.)
- **Graph**: Bionic-Graph at `:8088` (already running).
- **Topology** (this box only): extend `docker-compose.yml` with `llama-server` +
  Kokoro + Bionic-Graph + `server.py` + static frontend.

## 2. Graph schema (one shared graph, rich node types)
Covers "a person's day" across **衣食住行** (clothing / food / lodging / travel) plus
the people / places / events the user mentions:
- **`Me`** — singleton owner. **`Day(date)`** — one per calendar day; `Me -[:lives_day]-> Day`.
- **Daily-life facets** (typed nodes an `Entry` can `mentions`):
  - 衣 `Clothing`, 食 `Food`/`Meal`, 住 `Shelter`/`Residence`, 行 `Transport`/`Trip`
  - `Person`, `Place`, `Event`, `Organization`, `Thing`, `Activity`, `Mood`, `Health`,
    `Work`, `Finance`
- **`Entry(turnId, text, ts, lang)`** per spoken turn; `Day -[:has_entry]-> Entry`;
  `Entry -[:mentions]-> <facet|person|place|event>`.
- **`Todo` / `Plan`** with `for_date` (cross-day edges) — drives the
  "you planned X tomorrow but never mentioned it" clarification.
- **Design around Bionic-Graph quirks** (`AGENTS.md` §Known quirks): unique node
  names/IDs (stale token index keeps matching removed keywords); client-side dedup on
  exact search; `V ids:[...]` + `limit` for exact counts (rank index mixes vertices+edges).

## 3. RBAC (local single-user → tool allowlist + guardrails)
Since it is local, RBAC is mainly **defensive guardrails on the agent's tools** (the LLM
should not delete the diary or exfiltrate it):
- ALLOW: create/read `Entry` + facet nodes, create `Todo`/`Plan`, read `Day`, search,
  read `Todo[date]`.
- DENY: delete days/entries, raw edge deletion, modify RBAC, touch other graphs.
- Enforced at the **MCP tool layer** (each tool asserts caller=`agent`, graph=owner) —
  also where the Cypher→Gremlin mismatch is absorbed.

## 4. Phased slices
- **Slice 0 — Local inference infra**: build llama.cpp (Vulkan), stand up `llama-server`
  on the GGUF, install Kokoro; smoke-test on GPU/Vulkan; add to compose.
- **Slice 1 — Graph foundation**: Bionic-Graph Python client (Gremlin, quirk-aware),
  schema + node-type defs, MCP tool allowlist + RBAC, unit tests. ← *in progress*
- **Slice 2 — Agent wiring**: point `graph_agent` at local `llama-server`; interviewer
  prompts (5 s greet, detail-probe, todo-clarification); summarize turns → graph via MCP tools.
- **Slice 3 — Local TTS**: replace `qwen_tts_client.py` with Kokoro; wire into turn flow.
- **Slice 4 — Frontend**: date-nav (scroll picker + yesterday/tomorrow quick actions,
  future-day color), dotted-face auto-listen (already present), re-verify Whisper 8/8.
- **Slice 5 — E2E + CI**: headless-browser diary flow; CI on self-hosted ROCm runner;
  security gate (no secrets committed).
- **Slice 6 — Release**: compose deploy on box, feature-flag diary UI, monitor vs SLA
  (first-word <1 s, turn <5 s).

## 5. Testing strategy
- **Unit** (`node --test`, `pytest`): schema + date-nav queries; todo cross-day logic;
  RBAC denials; agent prompt logic; STT/LLM output parsing.
- **WebGPU browser** (reuse `scripts/lib/headless-webgpu.mjs` + validate runners): VAD,
  Whisper (already 8/8), TTS. Hard-refuse swiftshader — real `amd/rdna-3` only.
- **Integration**: graph_agent → MCP → Bionic-Graph round-trip against live `:8088`
  (mirror `bionic-graph/tests/assertion_test.py`).
- **E2E** (headless browser): load → auto-listen → speak → graph updated → switch date →
  todo-clarification prompt.
- **CI**: untracked `.github/workflows/ci.yml` on a self-hosted ROCm runner; non-GPU jobs
  only fall back to `--allow-cpu`.

## 6. Branch / release flow
- feature branch `diary/app` off `develop`; small buildable commits.
- merge to `develop` (done for the encoder work already); **ask before merging to `main`**.
- security gate: `.gh_token`, `settings.json` api_key, and any LLM keys stay git-ignored.
