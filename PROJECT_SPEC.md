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

- Base model: Qwen3-8B-Instruct (TODO: confirm final choice after Radeon
  instance testing — may adjust for latency/VRAM tradeoff)
- Fine-tuning: none used in the submitted version (a QLoRA cybersecurity
  fine-tune was explored separately but is out of scope for this submission
  timeline)
- Serving: vLLM, OpenAI-compatible API
- Deployment target: AMD Radeon GPU (gfx1100 / RDNA3) via Radeon Cloud,
  Deploy Type "vLLM Model API", `vllm serve <model> --host 0.0.0.0 --port 8000`
- Development note: agent logic (orchestrator, RAG, tools, memory,
  permissions) was built and fully tested against a mock LLM client
  (`src/llm/mock_client.py`) before wiring to the live Radeon-served model —
  this let the full pipeline be validated without spending GPU credits.

## 5. Optimization description for inference speed on AMD Radeon GPU

TODO — fill in after benchmarking on the live instance:
- Quantization approach used (if any) and measured speed/quality tradeoff
- Batching / KV-cache settings tuned for Radeon
- Before/after latency and throughput numbers
- Any ROCm-specific tuning applied

---
*Section 5 pending final GPU benchmarking run. Everything else reflects the
actual implemented and tested state of the repo as of this submission.*
