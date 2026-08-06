# Bunker - 3-5 Minute Demo Script

**Track 2 - Private AI Agent on AMD Radeon / ROCm**

This script walks a single, self-contained demo: a legal/financial team running
**confidential document operations** on a private, local AI agent. Every step is
reproducible and every claim (local vs external) is shown from live telemetry.

---

## Before recording (not on camera)

1. Start the local vLLM server on ROCm:

   ```bash
   python3 -m vllm.entrypoints.openai.api_server \
       --model Qwen/Qwen3-30B-A3B --quantization gptq --dtype float16 \
       --max-model-len 32768 --gpu-memory-utilization 0.85 \
       --enable-prefix-caching --enable-chunked-prefill
   ```

2. Confirm ROCm is visible to torch:

   ```bash
   python scripts/validate_rocm.py   # expect [OK] ROCm active.
   ```

3. Seed and index the confidential sample documents:

   ```bash
   # Windows:  .venv310\Scripts\python.exe scripts\demo_ingest.py
   python scripts/demo_ingest.py
   # Seeded 4 docs; ingest -> {'indexed': 4, 'skipped': 0, 'failed': 0, ...}
   ```

   The documents come from `demo/sample_documents/` (an NDA, a fund performance
   memo, a portfolio review, and a contract renewal) and are copied into
   `data/documents/` and indexed into local ChromaDB. They contain the exact
   facts used in the questions below.

4. Optional fallback if no ROCm box is available for the recording: run the
   **Ollama dev path** (`BUNKER_INFERENCE__BACKEND=ollama`, `qwen3:0.6b`) - the
   dashboard still shows real telemetry. Replace segment 1 with a screenshot of
   `validate_rocm.py` and say the GPU segments were captured on the ROCm box.

---

## The script

### Segment 1 - ROCm validation (0:00-0:35)

**Purpose.** Prove the AMD GPU / ROCm claim before anything else.

**Commands.**

```bash
python scripts/validate_rocm.py
```

**On screen.** A terminal showing:

```text
torch version             : 2.x.x+rocm6.2
torch.version.hip         : 6.2
torch.cuda.is_available() : True
GPU count                 : 1
GPU name                  : AMD Radeon RX 7900 XTX
[OK] ROCm active.
```

**Narrator cue.** "First, proof this is really local AMD hardware - the same
torch build that powers the agent reports HIP 6.2 and an AMD Radeon GPU."

---

### Segment 2 - App startup (0:35-1:15)

**Purpose.** Show the agent booting with the privacy dashboard up front.

**Commands.**

```bash
uvicorn src.main:app --host 0.0.0.0 --port 7860
curl http://localhost:7860/health
```

**On screen.** A clean server boot (no traceback), then the Gradio UI at
`http://localhost:7860/`: chat on the left, and the **Privacy Dashboard** on
the right showing Local Inference %, Local/External/Failed inference counts,
and bytes.

**Narrator cue.** "One shared runtime backs the whole app - chat, agent, RAG,
and the audit log, so the dashboard reflects everything we do next."

---

### Segment 3 - Document ingestion / RAG with citations (1:15-2:00)

**Purpose.** Show grounded, cited answers over confidential documents - the core
workflow.

**Commands.** (ingestion already ran; you can re-run to show it is idempotent)

```bash
python scripts/demo_ingest.py        # optional re-run: files show as "skipped"
```

Then in the chat:

> What governing law applies to the Acme-Meridian NDA, and how long does the
> confidentiality term last?

**On screen.** The thoughts panel shows the RAG route, search queries, and
grounded: yes. The answer ends with `[1] [2]`-style citations and states
*"Delaware"* and *"three (3) years."*

Then a **multi-hop** question that must combine two documents:

> Which fund strategy posted the highest net return in Q3 2026, and does the
> custody services agreement auto-renew?

**On screen.** The pipeline runs multiple retrieval hops, accumulates notes,
and answers with citations: *"Global Equities (+6.8%)"* and *"the agreement
auto-renews for successive one-year terms unless either party gives 90 days'
written notice."*

**Narrator cue.** "No cloud upload - ChromaDB with ROCm embeddings, and every
answer grounded in passages it can cite. It will not invent facts."

*(Optional 20s proof of no-hallucination)* - ask:

> What discount rate does our pension actuarial report assume?

**On screen.** The pipeline returns `INSUFFICIENT_CONTEXT` instead of
fabricating a number.

---

### Segment 4 - Follow-up tool use (2:00-2:30)

**Purpose.** Show the ReAct agent actually using tools, not just answering.

> List the files in my documents folder, then read the Q3 fund memo and tell me
> the fund AUM.

**On screen.** The thoughts accordion shows ordered tool calls:
`file_list(...)` → `file_read(q3_fund_performance.txt)`, then the answer
"$840M as of 30 September 2026" with the tool observations.

**Narrator cue.** "The same local model drives a multi-step agent loop with a
task planner and nine gated tools."

---

### Segment 5 - Denied write permission (2:30-3:00)

**Purpose.** Show that irreversible actions are **denied by default** - a
fail-safe no prompt can bypass.

> Write a file called draft_renewal_notes.md with a one-line summary of the
> renewal terms.

**On screen.** The `PermissionController` gates `file_write` inside the tool
body and the request is **denied** - the tool does not run, and the denial is
recorded in the permission history and audit log. (Dangerous tools are denied
out of the box; there is no UI bypass.)

**Narrator cue.** "Writes are gated inside the tool body, so no prompt can talk
the model past this. Denied - and the denial itself is audited."

---

### Segment 6 - Approved local draft / write (3:00-3:30)

**Purpose.** Show the approved path completing a real local file write.

Approval is an explicit opt-in for recordings: restart the app with
`BUNKER_PRIVACY__DEMO_MODE=true` (or set it before startup), then ask the same
question again.

```bash
# Windows:  $env:BUNKER_PRIVACY__DEMO_MODE="true"
export BUNKER_PRIVACY__DEMO_MODE=true
uvicorn src.main:app --host 0.0.0.0 --port 7860
```

**On screen.** The write request is approved, the file
`data/documents/draft_renewal_notes.md` is written locally, and the agent
confirms it. Optionally `type data\documents\draft_renewal_notes.md` to show
the file on disk.

**Narrator cue.** "Denied by default, approved only when the operator opts in.
Approved here - the draft lands in a local folder, on this machine, with
nothing sent anywhere."

> **Why two modes?** Deny-by-default is the safe production posture; demo mode
> exists so the approved path is demonstrable on camera. Both paths are tested
> in the suite (`tests/test_dspy_agent.py`, `tests/test_security_injection.py`).

---

### Segment 7 - Audit & privacy dashboard (3:30-4:10)

**Purpose.** Prove the local-vs-external claims with live telemetry.

**Commands.**

```bash
curl http://localhost:7860/api/privacy/status
type data\audit\audit.jsonl | tail -n 5        # Windows: Get-Content ... | Select-Object -Last 5
```

**On screen.** The dashboard's Local Inference % (100.0 with zero external and
zero failed), the per-backend counters (`vllm`), the live audit JSONL lines,
and the API response showing local events/bytes. If the Radeon Cloud fallback
were enabled, its events would appear as **external** here.

**Narrator cue.** "Every inference and tool call is recorded with its backend.
A hundred percent local is a measured number - and if an external fallback
ever ran, the dashboard would say so."

---

### Segment 8 - Benchmark artifact (4:10-5:00)

**Purpose.** Close with measured performance and a reproducible artifact.

**Commands.**

```bash
./scripts/benchmark.sh --vllm-url http://localhost:8000 --iterations 3
cat artifacts/benchmark_<timestamp>.json
```

**On screen.** The script streams TTFT/throughput per iteration, then the JSON
artifact with `summary.ttft.median_ms`, `summary.throughput.median_tok_s`, and
the captured `rocm-smi` VRAM/use/temp output.

**Narrator cue.** "Numbers, not screenshots: every run writes a timestamped
artifact with medians and ROCm metrics you can reproduce."

**Outro (optional, up to 15s):** `make test-unit` ending green (147 passed,
3 env-dependent skips) as a final quality signal.

---

## Segment timing budget

| Segment | Content | Time |
| :--- | :--- | :--- |
| 1 | ROCm validation | 0:35 |
| 2 | App startup | 0:40 |
| 3 | RAG with citations (+ INSUFFICIENT_CONTEXT) | 0:45 |
| 4 | Follow-up tool use | 0:30 |
| 5 | Denied write permission | 0:30 |
| 6 | Approved local write | 0:30 |
| 7 | Audit / privacy dashboard | 0:40 |
| 8 | Benchmark artifact | 0:50 |
| **Total** | | **~5:00** |

## If a segment misbehaves live

- **RAG answer drifts from the sample facts** → ask the question again or use
  the exact phrasing above; grounding + backtracking keeps answers cited.
- **Dashboard shows a failed inference** → the app still runs; use it to demo
  the *honest* telemetry ("this is why the claim is measured, not assumed").
- **No GPU on the recording machine** → run the Ollama dev path for segments
  2-7 and keep the segment-1 ROCm proof as a captured clip.
