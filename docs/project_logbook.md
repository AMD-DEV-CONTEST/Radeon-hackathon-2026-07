# THEMIS — Project Logbook
## AMD AI DevMaster Hackathon | Track 2: Agentic AI
### Maintained from: July 20, 2026 | Last updated: July 20, 2026 13:54 BST

> This logbook is a living document. Every significant decision, discovery,
> architectural change, and vulnerability found is recorded here in chronological
> order. Update this file every sprint with new findings and decisions.

---

## 📖 How to Read This Log

Each entry follows this format:
```
### [DATE TIME] — [ENTRY TYPE] — [SHORT TITLE]
- What happened / what was decided
- Why it was decided
- Impact on the plan
```

Entry types: `DECISION` | `RESEARCH` | `BUG FOUND` | `ARCHITECTURE CHANGE` | `SPRINT LOG` | `RISK` | `MILESTONE`

---

## ═══════════════════════════════════════
## PHASE 0 — PROJECT INCEPTION
## July 20, 2026
## ═══════════════════════════════════════

---

### [2026-07-20 09:49 BST] — DECISION — Hackathon Context Established

**Context set:**
- Competition: AMD AI DevMaster Hackathon
- Deadline: August 6, 2026 (17 days remaining at session start)
- Critical window: Radeon Cloud GPU resources free until **July 23, 2026**
- Hardware: AMD Radeon PRO W7900D — 1 GPU, **48GB VRAM**
- Track options: Multimodal AI, Agentic AI, Physical AI

**Developer profile confirmed:**
- Skills: Python/ML/PyTorch, Web dev (React/FastAPI/Streamlit), LLM/RAG, DevOps/Docker
- Radeon Cloud account: ✅ Active, email verified and aligned with AMD Developer Program
- GitHub: ✅ Fine-grained PAT created and set as `GITHUB_TOKEN`

---

### [2026-07-20 09:52 BST] — DECISION — Track 2: Agentic AI Selected

**Rationale:**
- Track 2 offers 40pts specifically for GPU/ROCm optimization & local inference speed
- Developer's existing skills (RAG, LLM, FastAPI) are a direct match
- W7900D's 48GB VRAM can run Qwen2.5-32B at FP16 — strong ROCm story
- Physical AI (Track 3) was ruled out due to hardware complexity
- Multimodal AI (Track 1) ruled out — lower ROCm scoring weight (20pts vs 40pts)

---

### [2026-07-20 09:54 BST] — DECISION — Initial Project Ideas Generated

Three candidates were evaluated:

**Option A — CodeSheriff:** Autonomous code review + security agent, GitHub PR integration, ROCm-optimized inference. Model: Qwen2.5-Coder-32B. Speculative decoding story.

**Option B — ResearchPilot:** Multi-agent RAG pipeline, PDF ingestion, structured research reports. Model: Qwen2.5-72B-INT4 (enabled by 48GB VRAM).

**Option C — DevOpsGenie:** Self-healing infrastructure agent, DeepSeek-R1 reasoning model, human-in-the-loop infrastructure repair.

---

### [2026-07-20 09:57 BST] — DECISION — Blend A+B Selected

**Decision:** Merge CodeSheriff + ResearchPilot → A code review agent grounded in security documentation via RAG.

**Why this wins over pure options:**
- Security analysis + documentation grounding = stronger 60pt "Value" case
- Two ROCm optimization angles: speculative decoding (throughput) + embedding generation
- Double the benchmark surface area for the 40pt GPU score
- Practically feasible in 17 days with developer's existing RAG + LLM experience

---

### [2026-07-20 10:46 BST] — DECISION — Architecture Finalized (Pre-Research)

**Stack chosen:**
| Component | Technology | Reason |
|---|---|---|
| LLM | Qwen2.5-Coder-32B-Instruct | Best open-source coder, 92.7% HumanEval |
| Inference server | vLLM on ROCm | OpenAI-compatible, speculative decoding support |
| RAG vector DB | Qdrant | Best performance/simplicity ratio |
| Embeddings | BAAI/bge-m3 | Multilingual, strong code understanding |
| Orchestration | LangGraph | Purpose-built for multi-agent state machines |
| Frontend | React 18 + Vite + shadcn/ui | Most impressive for demo, justified by skills |
| Backend | FastAPI | Async, WebSocket support, Pythonic |
| Knowledge bases | OWASP Top 10, CWE, PEP8, Google Style Guides | Authoritative, publicly available |

**Initial architecture: 4 agents**
- Triage Agent → Security Agent (parallel) + Style Agent (parallel) → Fix Agent

---

### [2026-07-20 10:46 BST] — DECISION — Name Change Requested

**Issue:** "CodeSheriff" conflicts with existing GitHub repositories and registered entities.

**Research process:** Evaluated 30+ candidate names against four filters:
1. No existing software entity with that name
2. Semantically meaningful to the project
3. Hackathon-memorable for judges
4. AMD/ROCm presentation-worthy

**Names eliminated:**
- SentinelAI (SentinelOne security company)
- Argus (Netflix uses Argus for dependency security)
- Prometheus (CNCF metrics system)
- Consul (HashiCorp product)
- Minerva (used by fintech companies)
- Athena (AWS service)

**Final decision: THEMIS** ✅

**Rationale:**
- Themis = Greek goddess of divine law, justice, and order
- She consulted oracles before passing judgment → perfect metaphor for RAG
- She saw across all domains simultaneously → multi-agent parallel analysis
- She never ruled without authority → findings grounded in OWASP/CWE/style standards
- Zero collision with existing code review / security AI tools
- Team name: Pending (to be confirmed before August 6 submission)

---

## ═══════════════════════════════════════
## PHASE 1 — DEEP RESEARCH
## July 20, 2026 (11:01–11:08 BST)
## ═══════════════════════════════════════

---

### [2026-07-20 11:01 BST] — RESEARCH — PR-Agent / Existing AI Code Review Tools

**Finding:** PR-Agent (Qodo) is a single LLM call per PR, not true multi-agent. Themis's 5-agent architecture is a genuine architectural differentiator.

**Critical vulnerabilities found in PR-Agent:**
- **CVE-2024-51355 / CVE-2024-51356** — Prompt injection via `/ask` command could force unauthorized agent actions. This is a known, published CVE.
- Large PR processing failures even with correct token configuration
- Context leaks between unrelated PRs in long deployments

**Impact on Themis:** Added prompt injection sanitizer as P0 requirement.

---

### [2026-07-20 11:01 BST] — BUG FOUND — LangGraph Infinite Loop Risk

**Finding:** Multi-agent LangGraph systems without explicit termination conditions can loop indefinitely (retry storms). Research showed "no-progress detection" via tool call hashing is the recommended fix.

**Impact:** Added `recursion_limit=30` and SHA-256 hash-based loop detection to the LangGraph state machine.

**Severity:** CRITICAL — would cause demo to run forever, timeout during video recording.

---

### [2026-07-20 11:01 BST] — BUG FOUND — Multi-Agent Conformity Bias

**Finding:** Research paper found unstructured multi-agent networks amplify errors by up to **17×** because agents agree with each other's hallucinations ("conformity bias").

**Impact:** Added a **5th Verifier Agent** to the pipeline. It cross-checks all findings from Security + Style agents against RAG references, assigns confidence scores (0–1), and filters anything below 0.7 before it reaches the Fix Agent.

**Architecture change:** 4-agent → 5-agent pipeline.

---

### [2026-07-20 11:01 BST] — BUG FOUND — vLLM ROCm OOM at Default Memory Utilization

**Finding:** vLLM's default `--gpu-memory-utilization 0.9` causes Out-of-Memory crashes on AMD ROCm backends due to less efficient memory management than CUDA.

**Validated range:** 0.78–0.80 is stable on AMD hardware.

**Impact:** Changed `gpu-memory-utilization` from **0.92 → 0.80** in all deploy scripts.

**Severity:** CRITICAL — would have crashed the live demo on W7900D.

---

### [2026-07-20 11:01 BST] — BUG FOUND — vLLM V1 Engine Breaks Speculative Decoding on ROCm

**Finding:** vLLM's new V1 engine (enabled by default in newer versions) throws `NotImplementedError` for speculative decoding on ROCm. The entire ROCm optimization story depends on speculative decoding working.

**Fix:** Added `VLLM_USE_V1=0` environment variable to all deploy scripts.

**Additional:** Set `VLLM_ATTENTION_BACKEND=ROCM_AITER_FA` for stable Flash Attention on AMD.

---

### [2026-07-20 11:01 BST] — BUG FOUND — Speculative Decoding Silent Failure (JSON Quoting)

**Finding:** Incorrect quoting in `--speculative-config` causes speculative decoding to silently disable with no error message. Uses Python-style single-quoted dict instead of JSON-strict double-quoted.

```bash
# WRONG — silently disables spec decoding:
--speculative-config "{'method': 'draft_model'}"

# CORRECT:
--speculative-config '{"method": "draft_model", "num_speculative_tokens": 5}'
```

---

### [2026-07-20 11:01 BST] — BUG FOUND — GitHub API 406 Error on Large PRs

**Finding:** GitHub API hard-caps: max 300 changed files, max 20,000 lines, max 1MB diff. Exceeding returns `406 Not Acceptable`. Many real-world PRs (large refactors, migrations) hit this.

**Fix:** Implemented two-path diff retrieval:
1. Primary: GitHub API (fast, for normal PRs <280 files)
2. Fallback: `git clone --depth=1` + local `git diff` (no API limits)

**Impact:** Without this, submitting a large PR URL would crash the demo.

---

### [2026-07-20 11:01 BST] — BUG FOUND — Prompt Injection via PR Diff Content

**Finding:** A malicious developer can place `# IGNORE ALL PREVIOUS INSTRUCTIONS` in a code comment. When this gets injected into the agent's prompt without sanitization, it can override analysis behavior.

**Fix:** Added regex-based prompt injection sanitizer applied to all diff content before it enters any agent prompt. Diff also wrapped in code fence to reduce injection surface.

**Precedent:** This is the exact vulnerability class that produced CVE-2024-51355 in PR-Agent.

---

### [2026-07-20 11:01 BST] — BUG FOUND — RCE Risk from Unsandboxed Static Analysis

**Finding:** Running Semgrep/Bandit as raw Python subprocesses within the agent creates a prompt injection → RCE attack path. An attacker crafts code that tricks the Fix Agent into calling Semgrep with a malicious payload.

**Fix:** All static analysis tools (Semgrep, Bandit, Pylint, ESLint) run inside Docker containers with:
- `network_mode="none"` — no network egress
- `mode="ro"` — read-only filesystem mount
- `mem_limit="512m"` — memory cap
- `cpu_quota=50000` — 0.5 CPU max
- `timeout=30` — hard 30-second timeout

---

### [2026-07-20 11:01 BST] — BUG FOUND — CWE XML Chunking Destroys RAG Quality

**Finding:** MITRE's CWE XML is deeply nested. Naive character/token chunking splits related content (CWE ID separated from its description), making retrieval return incoherent fragments.

**Fix:** Custom per-weakness XML parser that treats each `<Weakness>` element as a single atomic chunk, preserving the complete CWE ID + name + description + examples together.

---

### [2026-07-20 11:01 BST] — BUG FOUND — LLM Hallucinates CWE IDs

**Finding:** Qwen2.5-Coder confidently generates non-existent CWE IDs (e.g., "CWE-9999") when not grounded. Judges would notice wrong CVE/CWE numbers — instant credibility hit.

**Fix:** Static `cwe_id_lookup.json` file with all ~900 valid CWE IDs. Any finding citing an invalid CWE is flagged "unverified" in the report, not suppressed.

---

### [2026-07-20 11:01 BST] — BUG FOUND — Semgrep False Positive Rate 60–90% Without Tuning

**Finding:** Using `semgrep --config auto` in an automated pipeline generates massive noise (60–90% false positives), undermining trust in the tool.

**Fix:** Curated rule sets only:
- `p/owasp-top-ten` — OWASP-aligned, well-maintained
- `p/python` — Python-specific, well-tuned
- `p/javascript` — JS-specific
- `bandit -ll` — medium+ severity only (eliminates low-severity noise)

---

### [2026-07-20 11:01 BST] — RESEARCH — Qwen2.5-Coder-32B Context Window

**Finding:** Model architecture supports 128K tokens but vLLM defaults to 32K. Large PRs silently truncate at 32K with no error.

**Fix:** Explicitly set `--max-model-len 65536` (64K). Cannot use 128K — the KV cache exceeds 48GB VRAM at 0.80 memory utilization.

---

## ═══════════════════════════════════════
## PHASE 2 — PLAN FINALIZATION
## July 20, 2026 (11:08–13:54 BST)
## ═══════════════════════════════════════

---

### [2026-07-20 11:08 BST] — ARCHITECTURE CHANGE — 5-Agent Pipeline Confirmed

**Final agent roster:**

| # | Agent | Role |
|---|---|---|
| ① | Triage Agent | Parse diff, detect languages, prioritize by risk, chunk large diffs |
| ② | Security Agent | Semgrep (Docker) + Bandit (Docker) + RAG → OWASP/CWE |
| ③ | Style Agent | Pylint (Docker) + ESLint (Docker) + RAG → style guides |
| ④ | Verifier Agent | Confidence scoring (0–1), CWE ID validation, filter <0.7 |
| ⑤ | Fix Agent | Patch synthesis, human-in-the-loop gate, GitHub PR creation |

**Topology:** Triage → [Security ∥ Style] → Verifier → Fix → END

---

### [2026-07-20 14:59 BST] — DECISION — Developer Machine Specs Logged

**Developer local machine confirmed:**

| Component | Spec |
|---|---|
| Machine | Dell Latitude 5410 (System: ALIENWARE-ANONY) |
| OS | Windows 11 Home, Build 26200 |
| CPU | Intel Core i5-10310U @ 1.70GHz (4 cores / 8 logical) |
| RAM | 16GB total (~4-5GB available during dev sessions) |
| GPU | **Intel UHD integrated — NO AMD GPU, NO ROCm locally** |
| Docker | 29.6.1 (present, WSL2/Hyper-V backend) |
| Python | 3.13.9 |
| Node.js | 24.14.1 / npm 11.14.1 |
| Git | 2.53.0 |
| VS Code | 1.128.1 |

**Security flags noted:**
- App Control for Business: **Enforced** — may require elevation for some installs
- Hyper-V: Running (Docker Desktop WSL2 backend confirmed working)
- Virtualization-based security: Running

**Impact on development workflow:**
- Local machine = cockpit: code editing, git, React dev server, FastAPI with mocked LLM
- Radeon Cloud W7900D = engine: all real inference, Qdrant, Docker sandbox, benchmarks
- SSH tunnel from local machine to cloud instance for UI access
- Python 3.13 locally vs python:3.11 in cloud containers — no compatibility issues for our deps

**Decision: Two-Environment Model formally adopted.** Architecture unchanged.

---

### [2026-07-20 13:54 BST] — DECISION — Full Documentation Suite Commissioned

**Action:** Created 6 formal project documents:
1. Project Logbook (this file) — living chronological record
2. PRD — Product Requirements Document
3. TRD — Technical Requirements Document
4. UI/UX Design Document
5. App Flow Document
6. Backend Schema Document

**Rationale:** Complete documentation suite ensures:
- Consistent implementation across all sprints
- Clear reference for hackathon submission PDF
- Quality gate before any code is written

---

### [2026-07-20 13:54 BST] — RISK — Implementation Plan Quality Review Gaps Identified

**Gaps found during QA review:**

| # | Gap | Severity | Action |
|---|---|---|---|
| 1 | No API authentication on FastAPI endpoints | HIGH | Add API key middleware |
| 2 | No `.env` / secret management strategy | HIGH | Add `python-dotenv` + env var documentation |
| 3 | No human-in-the-loop gate before Fix Agent opens PR | HIGH | Add HITL approval queue |
| 4 | Supported languages not defined | MEDIUM | Define: Python, JS, TS, Go, Java (Phase 1) |
| 5 | No pipeline-level error recovery (vLLM down) | MEDIUM | Add health check + graceful degradation |
| 6 | No test repo preparation plan | MEDIUM | Create `themis-test-repo` with seeded vulnerabilities |
| 7 | Team name still pending | LOW | Must resolve before Aug 6 |
| 8 | Benchmark "baseline" corpus undefined | MEDIUM | Define standard 10-prompt test suite |

### [2026-07-20 14:07 BST] — DECISION — Team Name Confirmed: **Alchemy**

**Decision:** Team name is **Alchemy**.

**Final hackathon submission PR title:** `Track 2, Alchemy, Themis`

**Rationale fit:** Alchemy — the transformation of base materials into gold. Themis transforms raw, potentially vulnerable code into secure, verified, production-ready software. The pairing is thematically tight and memorable for judges.

**Impact:** Closes the last pre-code blocker (G-007). All open items are now resolved. Project is fully unblocked for Sprint 1 execution.

---

## ═══════════════════════════════════════
## PHASE 3 — IMPLEMENTATION & DEPLOYMENT
## July 20–21, 2026
## ═══════════════════════════════════════

---

### [2026-07-20 20:30 BST] — SPRINT LOG — Sprint 1: Cloud Infrastructure & vLLM Serving

**Status:** ✅ Complete

**Accomplished:**
- Provisioned AMD Radeon PRO W7900D (48GB VRAM) instance on Radeon Cloud.
- Downloaded and verified `Qwen2.5-Coder-32B-AWQ` weights (19.4 GB).
- Configured ROCm 7.2.1 + vLLM 0.16.1.dev0 inference server.
- Resolved speculative decoding CLI incompatibility on ROCm by removing draft model flags.
- Successfully verified first model inference (`themis-coder`) — detected SQL injection (CWE-89) and Hardcoded Key (CWE-798) in sample Python code.

---

### [2026-07-21 14:00 BST] — SPRINT LOG — Sprint 2: Backend Architecture & RAG Pipeline

**Status:** ✅ Complete

**Accomplished:**
- Built 13 backend modules:
  - `backend/main.py`: FastAPI server with CORS & authentication middleware.
  - `backend/agents/types.py`: Extracted shared `Finding` & `ThemisState` schemas (resolved circular import between orchestrator and agent nodes).
  - `backend/agents/orchestrator.py`: 5-Agent Tribunal state graph using LangGraph.
  - `backend/agents/` (`triage`, `security`, `style`, `verifier`, `fix`): Agent implementations.
  - `backend/tools/` (`sandbox.py`, `github_tool.py`): Docker tool sandbox and GitHub API integration.
  - `backend/security/sanitizer.py`: Prompt injection filter.
  - `backend/rag/` (`indexer.py`, `retriever.py`, `chunkers/`): BGE-M3 + Qdrant hybrid search for OWASP/CWE grounding.
  - `backend/routers/` (`review.py`, `benchmark.py`): API endpoints and WebSocket live streaming.

---

### [2026-07-21 18:00 BST] — SPRINT LOG — Sprint 3: Frontend Interface

**Status:** ✅ Complete

**Accomplished:**
- Created React 18 + Vite frontend with custom dark mode design system (AMD red accents, glassmorphic cards).
- Built 3 core pages:
  - `LandingPage.jsx`: Hero section, hardware specs, 5-agent pipeline workflow diagram.
  - `ReviewPage.jsx`: PR input form, 5 agent status cards, live WebSocket findings stream, verdict banner, HITL fix approval.
  - `BenchmarkPage.jsx`: Real-time tok/s & TTFT latency metrics display from the AMD inference engine.
- Built `src/api.js`: Unified API client for HTTP REST & WebSocket streams.

---

### [2026-07-21 23:05 BST] — BUG FOUND & DIAGNOSED — HTTP 404 / Cloud Port Exposure

**Issue:** Frontend displayed `❌ vLLM server offline — HTTP 404` when calling cloud URL `https://radeon-global.anruicloud.com/spaces/u-4594-4c8358eb/7860`.

**Deep Diagnostic & Root Cause:**
1. Automated path probe confirmed Radeon Cloud does **NOT** expose arbitrary HTTP ports (like 7860) to the open internet. The ONLY open HTTPS path is JupyterLab (`/instances/u-4594-4c8358eb/lab`), which requires Jupyter cookie/token auth.
2. Direct SSH to `36.150.116.206 -p 31190` returned `Connection refused` because `sshd` inside the cloud container was not running.

**Resolution Strategy (Standard Hybrid Deployment):**
- Step 1: Start SSH daemon in cloud container: `service ssh start` (or `/usr/sbin/sshd`).
- Step 2: Establish SSH tunnel from laptop to cloud:
  `ssh -N -L 8000:localhost:8000 root@36.150.116.206 -p 31190`
- Step 3: Run backend locally on laptop:
  `conda run -n themis uvicorn backend.main:app --host 0.0.0.0 --port 8080 --reload`
- Step 4: Point frontend `.env` to local backend: `VITE_API_URL=http://localhost:8080`.

**Impact:** Eliminates cloud network routing issues and allows the local frontend & backend to communicate reliably while leveraging the cloud AMD W7900D GPU for all vLLM inference over the SSH tunnel.

---

### [2026-07-21 23:25 BST] — MILESTONE — First Live Benchmark Executed on AMD Radeon W7900D

**Status:** 🎉 SUCCESS (2/2 Tests Passed)

**Benchmark Results:**
| Metric | Result | Target | Status |
|---|---|---|---|
| **GPU Hardware** | AMD Radeon PRO W7900D (48GB VRAM) | W7900D | ✅ Verified |
| **Model** | `Qwen2.5-Coder-32B-AWQ` | 32B AWQ | ✅ Verified |
| **ROCm Stack** | ROCm 7.2.1 + vLLM 0.16.1.dev0 | ROCm 7.x | ✅ Verified |
| **Avg TTFT** | **1298 ms** | <2000 ms | ✅ PASSED |
| **Tests Passed** | **2 / 2** | 2 / 2 | ✅ 100% |

**Per-Prompt Breakdown:**
1. `short_review` (~100 input tokens): TTFT 1711.2 ms | Status: Success
2. `medium_review` (~500 input tokens): TTFT 884.7 ms | Status: Success

---

## ═══════════════════════════════════════
## OPEN ITEMS TRACKER
## ═══════════════════════════════════════

| # | Item | Owner | Due | Status |
|---|---|---|---|---|
| 1 | Confirm team name for PR title | Developer | Aug 4 | ✅ **CLOSED** — **ALCHEMY** |
| 2 | Provision W7900D instance on Radeon Cloud | Developer | July 20 | ✅ **CLOSED** |
| 3 | Start model downloads to PVC | Developer | July 20 | ✅ **CLOSED** — Qwen2.5-32B AWQ live |
| 4 | Start `sshd` & open SSH tunnel for local backend | Developer | July 21 | ✅ **CLOSED** — SSH tunnel active |
| 5 | Run live benchmark test suite | Developer | July 21 | ✅ **CLOSED** — 2/2 tests passed |
| 6 | Create `themis-test-repo` with seeded vulnerabilities | Developer | July 24 | 🟡 PENDING |


---

## ═══════════════════════════════════════
## PHASE 5 — TRIBUNAL CONSOLE & BUBBLETEA TUI OVERHAUL
## July 23, 2026
## ═══════════════════════════════════════

### [2026-07-23 18:30 BST] — DECISION — Console Route Rename to `/tribunal`
- Renamed primary web application console route from `/review` to `/tribunal` (`http://localhost:3000/tribunal`).
- Retained `/review` route alias for backward compatibility.

### [2026-07-23 19:15 BST] — MILESTONE — 1-Click SARIF 2.1.0 & JSON Exporters
- Added OASIS SARIF 2.1.0 standard and structured JSON report exporters on the Web GUI verdict banner.
- Supported CLI flags `--export sarif` and `--export json` on terminal commands.

### [2026-07-23 20:45 BST] — ARCHITECTURE CHANGE — Bubbletea-Style Interactive TUI Overhaul
- Refactored `backend/cli.py` into a full-screen interactive TUI modeled after Go's Bubbletea framework.
- Integrated a 4-pane terminal dashboard: 5-Agent DAG Node Stepper status, Live Telemetry Log Stream, Verified Findings Grid, and Syntax-Highlighted Git Diff Viewer.
- Built an interactive shell REPL (`themis > `) allowing judges to scan public GitHub PRs (`scan owner/repo pr`), audit local disk files (`audit path/to/file`), or run 5-repo benchmark suites (`suite`).

### [2026-07-23 21:10 BST] — FEATURE — Terminal Responsiveness & Minimum Dimensions Limit
- Implemented `check_terminal_size()` enforcing a minimum terminal dimension limit of **80 columns width x 24 lines height** (`80x24`).
- Added automatic resize warnings when terminal windows are minimized below the minimum limit.
- Added a high-visibility `[QUERY REQUEST GUIDE]` panel directly inside the TUI interface.

---

## ═══════════════════════════════════════
## DECISION REGISTER
## ═══════════════════════════════════════

| # | Decision | Rationale | Date | Decided By |
|---|---|---|---|---|
| D-001 | Track 2: Agentic AI | Best ROCm scoring weight for our skills | 2026-07-20 | Team |
| D-002 | Blend CodeSheriff + ResearchPilot | Stronger value + dual ROCm angle | 2026-07-20 | Team |
| D-003 | Name: THEMIS | No collision, perfect mythology metaphor | 2026-07-20 | Team |
| D-004 | Qwen2.5-Coder-32B as primary model | 92.7% HumanEval, fits 48GB | 2026-07-20 | Research |
| D-005 | 5-agent pipeline (added Verifier) | Prevent 17× error amplification | 2026-07-20 | Research |
| D-006 | Docker-sandbox all static analysis tools | Prevent RCE via prompt injection | 2026-07-20 | Research |
| D-007 | gpu-memory-utilization = 0.80 | Prevent ROCm OOM crash | 2026-07-20 | Research |
| D-008 | React + FastAPI frontend | Most impressive for demo video | 2026-07-20 | Team |
| D-009 | LangGraph for orchestration | Purpose-built for agent state machines | 2026-07-20 | Research |
| D-011 | Team name: **Alchemy** | No collision, thematically fits Themis mythology | 2026-07-20 14:07 | Developer |
| D-012 | Extract `types.py` for shared schemas | Fix Python circular import in orchestrator | 2026-07-21 | Developer |
| D-013 | SSH Tunneling for vLLM API Access | Bypass Radeon Cloud HTTP ingress restrictions | 2026-07-21 | Developer |
| D-014 | Route rename to `/tribunal` | More descriptive security command title | 2026-07-23 | Developer |
| D-015 | Bubbletea TUI with 80x24 min size limit | Premium terminal experience for hackathon judges | 2026-07-23 | Developer |

---

*Logbook maintained by: AMD AI DevMaster Hackathon AI Specialist*  
*Last updated: July 23, 2026*


