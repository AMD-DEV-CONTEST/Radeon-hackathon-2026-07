# Project Specification — Local Dev Evidence Agent (LDEA)

| Field | Value |
|-------|--------|
| Track | **Track 2** — Development & Local Deployment of Private AI Agents |
| Product one-liner | Local dev evidence agent — **refuse unverified completion narratives** |
| Document status | Submission-ready · 2026-08-06 |
| Author | reflect (`starsstreaming`) |

---

## 1. Overview

### 1.1 Problem

After AI-assisted coding became common, “done” got cheap:

- The model says “fixed” in chat.
- Developers close the day with “everything is finished.”
- Write-ups look complete but are **not bound to real code changes and test results**.

LDEA is not a chat summarizer. It is a **verifiable development outcomes ledger**: only items that pass the evidence gate may be publicly described as completed or fixed.

### 1.2 Product position

| Dimension | Description |
|-----------|-------------|
| Form | Local CLI agent + deterministic evidence core |
| Inference | AMD Radeon + ROCm + vLLM (OpenAI-compatible); data stays private by default |
| Memory | Session L0 event log → L1 outcome state machine |
| Non-goals | Does not auto-write product code; does not replace CI; **LLM must not set `verified`** |

### 1.3 Contest capability map

| Contest capability | LDEA landing |
|--------------------|--------------|
| Reasoning / planning | `run` / `demo --live`: multi-round tool-calls under ambiguous goals |
| Tool use | claim, git_diff, run_tests / ingest_test_output, scan_privacy, show_outcomes, end_session, render_report |
| Memory | `.ldea/sessions/<id>/` — events, store, report, meta, trace |
| Task execution | Offline `close`/`demo` rule pipeline; online agent closes with a report |
| Private local | `127.0.0.1` / SSH tunnel only; no mandatory cloud LLM vendor |
| Radeon / ROCm | §5–§6 deployment + measured opts |

---

## 2. Application scenarios

### 2.1 Primary: end-of-day / end-of-task verification

**Trigger:** Need a honest answer to “what actually shipped?”

**Flow:**

1. In a work repo: `ldea close --claim "…" --test "…"` (or agent `run` first).
2. System records the claim, collects git + tests, rebuilds L1.
3. Five-section report; only `verified` enters **Achievements**.

**Value:** Turns “feels done” into ledger status + evidence paths. Fits private teams that cannot upload code to cloud agents.

### 2.2 Contrast matrix (contest narrative)

| Story | Input | Expected |
|-------|--------|----------|
| A | “All done today” + no git/tests | `abandoned`, empty achievements |
| B | “Ship-ready” + git diff only | `evidenced`, not completed |
| C | “Fixed” + tests still failing | `evidenced`, not verified |
| D | Login error taxonomy + diff + pytest fail→pass | `verified`, may say fixed |

- Full matrix: `ldea demo --suite` (offline, **recommended for video**)
- Short contrast: `ldea demo` (A vs verified)

### 2.3 Agent: ambiguous-goal investigation

**Trigger:** Conflicting claims — “should be fixed” vs “calling it a day.”

**Flow:** Local Qwen multi-round tools → L1 is authority → `render_report`.

**Commands:** `ldea demo --live` or `ldea run "<ambiguous goal>"`.

### 2.4 Out of scope

- Long learning-style recaps (other product line).
- Remote SaaS code hosting analysis.
- Contest build: no cross-session auto-merge, no full IDE plugin.

---

## 3. Agent architecture

### 3.1 Logical architecture

```text
                 User goal / close claim / demo
                              │
         ┌────────────────────┼────────────────────┐
         ▼                    ▼                    ▼
   runClose (rules)     runAgent (LLM loop)     doctor
   no GPU               local OpenAI-compatible
         │                    │
         │   tools: claim · git_diff · tests · privacy ·
         │          show_outcomes · end_session · render_report
         └────────────────────┬────────────────────┘
                              ▼
                 ┌──────────────────────────┐
                 │  airecap-plus (core)     │
                 │  L0 events.jsonl         │
                 │  → rule aggregate L1     │
                 │  claimed → … → verified  │
                 └────────────┬─────────────┘
                              ▼
              Deterministic report.md / report.json
              (LLM must not write verified)
```

### 3.2 Deployment (private)

```text
[Dev machine · Node CLI LDEA]
        │  SSH -L 8000:127.0.0.1:8000
        ▼
[AMD Radeon GPU host · ROCm]
        │
        ▼
   vLLM OpenAI API :8000
   Qwen2.5-7B-Instruct
   bind 127.0.0.1 only
```

- Code, test logs, privacy scans stay on the dev machine disk (`.ldea/`).
- Inference hits only the owned GPU host — **not** a third-party LLM cloud (unless the user changes the endpoint).

### 3.3 Repository boundary

| Package | Role |
|---------|------|
| **local-dev-evidence-agent** | CLI, agent loop, tool adapters, privacy scan, report, demos |
| **airecap-plus** (`file:../airecap-plus`) | L0 ingest, binding, aggregation, outcome state machine, session store |

Both are shipped under `source/` in this PR.

### 3.4 Session memory layout

```text
.ldea/sessions/<session_id>/
  events.jsonl      # L0
  store.json        # L1
  meta.json
  report.md / report.json
  agent-trace.json  # or close-trace.json
```

Navigate: `ldea ls` / `ldea show [id]`.

---

## 4. Core capabilities

### 4.1 Evidence state machine (hard gate)

| Status | Meaning | May say “completed”? |
|--------|---------|----------------------|
| `claimed` | Claim only | No |
| `evidenced` | Code etc. present; verification open | No (partial) |
| `verified` | Evidence + verification anchors | **Yes** |
| `abandoned` | Session ended without enough evidence | No |
| `contradicted` | Counter-evidence | No |

Fixed report banner:

> Only `status=verified` may be written as completed/fixed; the LLM must not self-certify verified; bare claims → abandoned.

### 4.2 Tools

| Tool | Role |
|------|------|
| `claim` | Record a claim; **alone never verifies** |
| `git_diff` | Worktree/staged/commit → file_change |
| `run_tests` / `ingest_test_output` | Run or inject tests → test_result |
| `scan_privacy` | Email / API key / connection-string risks |
| `show_outcomes` | Read L1 for agent decisions |
| `end_session` | Close; bare claims tend to abandoned |
| `render_report` | Deterministic Markdown/JSON report |

### 4.3 Dual execution paths

| Path | Entry | GPU? | Use |
|------|-------|------|-----|
| Rules | `close` / `demo` / `demo --suite` | No | Daily close, reproducible CI, contest matrix |
| Agent | `run` / `demo --live` | Yes | Ambiguous goals, tool planning, “agent” demo |

**Design point:** Verifiable conclusions do not depend on model honesty. The model explores; the ledger adjudicates.

### 4.4 Report surface

1. Achievements (verified only)  
2. Code evidence  
3. Verification evidence  
4. Decision trail  
5. Public risk  
6. Open / not-publicly-done  

---

## 5. Model & local deployment

### 5.1 Model

| Item | Value |
|------|--------|
| Primary | Qwen2.5-7B-Instruct |
| Why | Strong instruction + tool-call ecosystem; fits consumer Radeon VRAM/speed |
| API | OpenAI-compatible Chat Completions + tools |
| Alternate | Any compatible endpoint via `LDEA_LLM_*` |

### 5.2 Dependencies

**Dev machine:** Node ≥ 20, npm, git, SSH client, optional pytest.  
**GPU host:** AMD Radeon + ROCm, vLLM (ROCm build), local model weights.  
**Source:** build `airecap-plus` then `local-dev-evidence-agent`.

### 5.3 Environment variables

| Variable | Default | Notes |
|----------|---------|--------|
| `LDEA_LLM_BASE_URL` | `http://127.0.0.1:8000/v1` | Local / tunnel |
| `LDEA_LLM_MODEL` | `qwen2.5-7b-instruct` | Must match served name |
| `LDEA_LLM_API_KEY` | `local` | Any non-empty for local |
| `LDEA_ROOT` | `.ldea` | Ledger root |
| `LDEA_CWD` | process cwd | Work repo under inspection |

### 5.4 Startup

**GPU host**

```bash
rocm-smi
vllm serve /models/Qwen2.5-7B-Instruct \
  --host 127.0.0.1 --port 8000 \
  --served-model-name qwen2.5-7b-instruct \
  --attention-backend TRITON_ATTN \
  --enable-auto-tool-choice \
  --tool-call-parser hermes \
  --max-model-len 4096 \
  --gpu-memory-utilization 0.85 \
  --enforce-eager
```

**Dev machine**

```bash
ssh -L 8000:127.0.0.1:8000 <gpu-host>
cd source/airecap-plus && npm install && npm run build
cd ../local-dev-evidence-agent && npm install && npm run build
export LDEA_LLM_BASE_URL=http://127.0.0.1:8000/v1
export LDEA_LLM_MODEL=qwen2.5-7b-instruct
node dist/cli.js doctor
node dist/cli.js demo --suite
node dist/cli.js demo --live
```

### 5.5 Verification checklist

| Step | Expect |
|------|--------|
| `npm test` | All pass |
| `doctor` | `LLM: OK` + models list |
| `demo --suite` | A abandoned · B/C evidenced · D verified |
| `demo --live` | Multi-step tools; report; no fake “completed” without evidence |

---

## 6. Inference-speed optimization on AMD Radeon GPU

> Maps to **40 points**: local inference + speed optimization.  
> Numbers from 2026-08-03 dry-run (gfx1100 cloud + dev tunnel).

### 6.1 Hardware / software baseline

| Item | Value |
|------|--------|
| GPU | AMD Radeon · DID 0x744b · **gfx1100** |
| VRAM | vLLM `--gpu-memory-utilization 0.85` |
| ROCm | **7.2.1** (`rocm7.2.1_navi` image) |
| vLLM | **0.16.0** |
| Model | `/models/Qwen2.5-7B-Instruct` · served `qwen2.5-7b-instruct` |
| Serve flags | `127.0.0.1:8000` · max-model-len **4096** · TRITON_ATTN · auto-tool-choice · hermes · enforce-eager |
| Generation throughput | **~24 tok/s** (via SSH tunnel; completion=25, wall≈1.04s) |
| Live E2E | `demo --live` **verified=1** · 8 tools · **~12s** |

### 6.2 Optimizations (problem → lever → result)

| # | Lever | Problem | Mechanism | Result |
|---|-------|---------|-----------|--------|
| 1 | Bind inference to `127.0.0.1` only | Privacy + accidental exposure | No public API; shortest path | Tunnel doctor/models 200; no public API key |
| 2 | `--attention-backend TRITON_ATTN` | ROCm/navi attention backend | Image-recommended backend | Stable multi-hour service |
| 3 | `--max-model-len 4096` (demo host) | KV VRAM vs multi-tool rounds | Trade context for stability | VRAM ~85%; live multi-round OK |
| 4 | auto-tool-choice + hermes parser | Agent needs real tool-calls | Structured tools | Live steps use tool_calls |
| 5 | `--enforce-eager` + gpu-mem 0.85 | Graph capture / VRAM spikes | Eager lowers compile risk | ~24 tok/s sustained |
| 6 | 1 tool/round + deterministic close | Wasted long generation | GPU only for planning path | Offline demo seconds; live ~tens of seconds |
| 7 | SSH local forward, not public :8000 | Security + judge topology | `ssh -L 8000:…` | Local curl models OK |

### 6.3 End-to-end “felt speed” (engineering, not kernels)

- **Rules when possible:** `close` / offline `demo` burn **zero** GPU.  
- **Ingest tests:** `ingest_test_output` avoids re-running heavy suites in demos.  
- **Deterministic reports:** no second LLM “summary” impersonating the ledger.

GPU budget is spent on **planning and tool choice**, not on writing fake completions.

### 6.4 Known limits

- 7B may occasionally drift from tool schema (Hermes text fallback in code).  
- Throughput depends on PCIe/tunnel/concurrency; demos assume single user.  
- Claim/evidence order matters; live demo goal fixes a safe tool order.

---

## 7. Source structure & dependencies

```text
source/
  airecap-plus/                 # evidence core
  local-dev-evidence-agent/     # agent CLI
    src/cli.ts agent.ts tools.ts report.ts privacy.ts llm.ts …
    tests/ fixtures/login-error-demo/
```

**npm runtime:** `airecap-plus` via `file:../airecap-plus`  
**npm dev:** typescript, vitest, @types/node  

One-shot: `npm test && npm run build && node dist/cli.js demo`

---

## 8. Demo video

| Item | Value |
|------|--------|
| Path | `demo/demo_video.mp4` |
| Duration | ~**2 min 38 s** (slightly under 3–5 min suggestion; full functional loop covered) |
| Must show | ROCm/vLLM · `doctor` · gate matrix · report · live tool trace · `ls/show` |

Approximate timecodes:

| Segment | Time | Content |
|---------|------|---------|
| Stance | 0:00–0:15 | Refuse unverified completion / verified gate |
| GPU / vLLM | 0:15–0:35 | Radeon + ROCm + local 127.0.0.1 |
| doctor | 0:35–0:50 | `LLM: OK` |
| demo / suite | 0:50–1:40 | Multi-story status differences |
| live agent | 1:40–2:15 | Ambiguous goal + tools + verified report |
| ls/show + close | 2:15–2:38 | Multi-session ledger |

---

## 9. Self-check vs scoring

### Functional completeness & value (60)

| Point | Evidence |
|-------|----------|
| Real scenario, differentiated | §2; demo contrast |
| Agent closed loop | live / run + tool trace |
| Memory & replay | `.ldea/sessions` |
| Usability | close/ls/show; offline demo |
| Privacy | scan_privacy report column |
| UX | Gate banner + CLI contrast footer |

### AMD Radeon & ROCm (40)

| Point | Evidence |
|-------|----------|
| Real local inference | Video GPU segment + doctor |
| Speed optimization | §6 table |
| Fluid end-to-end | Video to report |

---

## 10. Honest roadmap

| Stage | Content |
|-------|---------|
| Contest (now) | Gate ledger, dual path, multi-session list, ROCm agent |
| Next | Real-repo habits, weekly rollup, session search |
| Later | Claude/Codex logs → **candidate** L0 → still gated by git/tests (chat never self-verifies) |

---

## 11. Revision

| Date | Change |
|------|--------|
| 2026-08-03 | Spec skeleton; gfx1100 / ROCm 7.2.1 / ~24 tok/s / live verified |
| 2026-08-06 | `demo --suite`; video path; English submission pack for PR |
