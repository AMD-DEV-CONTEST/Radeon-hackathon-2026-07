# Project Specification Document — Private SOC Triage Agent

Track 2: Agentic AI (Development & Local Deployment of Private AI Agents)

## 1. Application scenarios

Security teams running Wazuh (host IDS), Suricata (network IDS/IPS), and
Greenbone/OpenVAS (vulnerability scanning) generate a constant stream of
alerts. Manually correlating a raw alert with the right MITRE ATT&CK
technique, checking whether the source host has a known matching CVE, and
deciding on a response is slow and inconsistent across analysts — and this
telemetry is sensitive enough that it should not leave the network to reach
a third-party cloud LLM.

The Private SOC Triage Agent ingests alerts from these three tools,
retrieves relevant MITRE ATT&CK and CVE context from a local knowledge base,
correlates them, and produces an explained triage recommendation — with all
inference running locally on an AMD Radeon GPU. No alert data is sent to any
external API.

Example flow demonstrated in this repo: a burst of SSH brute-force alerts
from Wazuh + Suricata against the same host is correlated with a known
OpenSSH CVE (regreSSHion) on that host from Greenbone, and the agent
recommends blocking the source IP and checking for successful logins.

## 2. Agent architecture diagram

Security tools (Wazuh, Suricata, Greenbone) + local knowledge base (MITRE
ATT&CK, CVE) feed into an agent orchestrator (planning, tool routing,
multi-turn memory, role-based permission control), which loops with a
locally-served LLM on AMD Radeon GPU (vLLM), producing output for the
analyst chat interface. See `docs/architecture.png`.

## 3. Introduction to core capabilities

- [x] **Local knowledge retrieval (RAG)** — `src/rag/retriever.py`. Keyword-scored
      retrieval over a local MITRE ATT&CK / CVE corpus (`data/knowledge_base/`),
      zero external dependencies. Verified: alert-relevant technique/CVE
      excerpts are correctly retrieved per query (e.g. SSH alerts surface
      T1110 Brute Force + CVE-2024-6387; SQLi alerts surface T1190).
- [x] **Tool invocation** — `src/tools/{wazuh,suricata,greenbone}_tool.py`.
      Orchestrator exposes each as an OpenAI-compatible function-calling
      schema; the LLM decides when to call `get_vulns_for_host` etc. and the
      result is fed back into the conversation.
- [x] **Multi-step task planning** — `src/orchestrator/agent.py:triage_alert`.
      Flow: retrieve KB context -> ask LLM -> if LLM requests a tool, call it
      and re-prompt with the result -> final recommendation.
- [x] **Local multi-turn memory** — `src/orchestrator/memory.py`. Bounded
      conversation buffer so the analyst can ask follow-up questions
      ("why is this high severity?") with context retained.
- [x] **Permission control & privacy protection** — `src/orchestrator/permissions.py`.
      Role-based field redaction (e.g. a "trainee" role sees redacted
      source IP / username) applied before any alert data reaches the LLM.

All 5 optional capabilities implemented, verified end-to-end with sample
data via `python -m src.main --mode demo`.

## 4. Model introduction & local deployment plan

- Base model: **Qwen/Qwen3-8B** (dense, hybrid thinking/non-thinking mode — Qwen3
  ships instruction-tuned by default, no separate "-Instruct" variant)
- Fine-tuning: none used in the submitted version
- Serving: vLLM 0.16.1 (ROCm build), OpenAI-compatible API, tool-calling enabled
  via `--enable-auto-tool-choice --tool-call-parser hermes`
- Deployment target: AMD Radeon GPU (gfx1100 / RDNA3), ROCm 7.2.1, Radeon Cloud
  instance
- Model source: downloaded via **ModelScope** (`modelscope download`) rather
  than HuggingFace Hub — the Radeon Cloud sandbox's outbound network allowlist
  does not reach huggingface.co, but does reach modelscope.cn
- Development note: agent logic (orchestrator, RAG, tools, memory,
  permissions) was built and fully tested against a mock LLM client
  (`src/llm/mock_client.py`) before wiring to the live Radeon-served model —
  this let the full pipeline be validated without spending GPU credits. Tool
  data source (`tool_mode`) is decoupled from the LLM backend (`mode`), so the
  live-GPU model can be exercised against representative sample alert data
  while live Wazuh/Suricata/Greenbone API connectors remain future work.
- **Why Qwen3-8B, not a cloud API:** AMD's Token Factory (the free, cloud-hosted
  Model API) requires a mainland China phone number for account verification,
  which wasn't available to us. Rather than depend on a cloud API we couldn't
  even register for, this reinforced the case for genuine local deployment —
  Qwen3-8B was downloadable via ModelScope (reachable from the sandbox
  network, unlike huggingface.co) with no account gating at all, letting the
  entire inference pipeline run privately, on the Radeon GPU itself, exactly
  as Track 2 asks for.

## 5. Optimization description for inference speed on AMD Radeon GPU

Measured directly on the Radeon Cloud instance (gfx1100, ROCm 7.2.1) via
vLLM's `/metrics` endpoint, across the 3-alert demo run (4 LLM calls total,
including one tool-calling round trip):

| Metric | Value |
|---|---|
| Time to first token (avg) | ~0.53s (2.11s / 4 requests) |
| Requests completed successfully | 4 / 4 (0 errors, 0 aborts) |
| Total generation tokens | 4,288 |
| Avg tokens per response | ~1,072 |

**ROCm-specific tuning applied during setup:**
- Removed a CUDA-only `flash_attn` package that was pre-installed in the base
  image (`pip uninstall flash-attn`) — its presence caused vLLM's RoPE layer
  to attempt importing a CUDA-only C-extension (`flash_attn_2_cuda`) instead
  of falling back to its native ROCm-compatible kernel path.
- Served the model from a local ModelScope-downloaded directory
  (`/workspace/models/Qwen3-8B`) rather than a remote repo ID, avoiding
  repeated network round-trips during engine startup.

**Radeon/vLLM inference optimizations active by default** (confirmed in
startup logs): chunked prefill (`max_num_batched_tokens=2048`), prefix
caching, and asynchronous scheduling were all enabled — these reduce
time-to-first-token and improve throughput under concurrent requests on
ROCm without requiring manual tuning.

**Trade-off observed:** Qwen3's default "thinking mode" produces verbose
chain-of-thought before the final answer (visible in the demo — ~1,030 tokens
average per response), which improves triage reasoning quality but increases
latency. For a latency-sensitive production deployment, disabling thinking
mode (`/no_think` in the system prompt) or serving a quantized variant would
be the next optimization step.

---
*All sections reflect the actual implemented and benchmarked state of the
repo — capabilities, deployment, and performance numbers are drawn directly
from a live run on the Radeon Cloud GPU instance, not projected estimates.*
