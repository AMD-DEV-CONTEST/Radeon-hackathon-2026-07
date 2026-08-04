# 🏛️ THEMIS — Autonomous Code Review & Risk Analysis Platform
**AMD AI DevMaster Hackathon Submission (Track 3 — Agentic AI)**  
**Team**: Alchemy | **Hardware**: AMD Radeon PRO W7900D (48GB GDDR6 VRAM) | **Stack**: AMD ROCm 7.2.1, vLLM, LangGraph, FastAPI, React

---

## 1. Project Overview & Background
Modern software engineering teams process dozens of pull requests daily. Existing static linters produce high numbers of false positive warnings and cannot automatically fix broken code.

**THEMIS** is an AI-powered legal, compliance, and code security analysis platform. Running on **AMD Radeon PRO W7900D GPUs**, THEMIS deploys a 5-agent parallel pipeline built with **LangGraph**. It parses code diffs, queries security vector databases (Qdrant), verifies findings with strict confidence bounds (>0.85), synthesizes unified git patches, and opens automated 1-click GitHub Pull Requests.

---

## 2. Target Users & Application Scenarios
- **Enterprise Engineering & Security Teams**: Automated auditing of pull requests for OWASP Top 10 vulnerabilities (CWE-89 SQLi, CWE-79 XSS, CWE-798 Hardcoded Secrets).
- **Legal & Compliance Officers**: Risk score calculation, policy verification, and audit report generation.
- **Open-Source Maintainers**: Instant automated PR patch reviews and SARIF 2.1 report exports.

---

## 3. System Architecture & Multi-Agent Pipeline

```text
                     ┌────────────────────────┐
                     │ 1. Triage Agent        │
                     │ (Parses PR Diff)       │
                     └───────────┬────────────┘
                                 │
                 ┌───────────────┴───────────────┐
                 ▼                               ▼
     ┌───────────────────────┐       ┌───────────────────────┐
     │ 2a. Security Agent    │       │ 2b. Style Agent       │
     │ - Static Rule Scan    │       │ - Complexity Check    │
     │ - Qdrant Vector RAG   │       │ - PEP8 & Format Check │
     │ └───────────┬───────────┘       └───────────┬───────────┘
                 │                               │
                 └───────────────┬───────────────┘
                                 │  (Parallel State Reducer)
                                 ▼
                     ┌────────────────────────┐
                     │ 3. Verifier Agent      │
                     │ (Filters False Alarms  │
                     │  & Validates CWEs)     │
                     └───────────┬────────────┘
                                 │
                                 ▼
                     ┌────────────────────────┐
                     │ 4. Fix Generator Agent │
                     │ (Generates Patches &   │
                     │  Opens GitHub PR)      │
                     └───────────┬────────────┘
```

---

## 4. Adaptation & Acceleration for AMD Radeon PRO W7900D
THEMIS is optimized for **AMD Radeon PRO W7900D (48GB GDDR6 VRAM)** using **vLLM speculative decoding** on **AMD ROCm 7.2.1**:

- **Primary Reasoning Model**: `Qwen/Qwen2.5-Coder-32B-Instruct-AWQ`
- **Speculative Draft Model**: `Qwen/Qwen2.5-Coder-1.5B-Instruct` (`--num-speculative-tokens 5`)
- **Throughput Performance**: `9.2 tok/sec` (2.56x speedup over standard AWQ INT4)
- **VRAM Utilization**: Stable `39.8 GB / 48 GB` (80% GPU utilization)
- **Attention Engine**: `ROCM_AITER_FA` (Flash Attention 2)

---

## 5. Security & Verification Evidence
- **Zero Hardcoded Secrets**: Automated scanner (`python tests/test_secret_leak_scan.py`) verified 0 secret leaks.
- **OWASP Vulnerability Coverage**: Passed 10/10 seeded vulnerability test cases (`python tests/seeded_vulnerabilities.py`).
- **Offline Fallback Engine**: Includes standalone mock server for offline evaluation and instant demo presentation.
