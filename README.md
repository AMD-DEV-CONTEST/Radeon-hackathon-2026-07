<div align="center">

# THEMIS: Autonomous Code Review & Security Analysis Platform

**Track 2 (Agentic AI), AMD AI DevMaster Hackathon Submission**  
**Team**: **Alchemy** | **Hardware**: **AMD Radeon PRO W7900D (48GB GDDR6 VRAM)**

[![AMD ROCm](https://img.shields.io/badge/AMD_ROCm-7.2.1-ED1C24?style=for-the-badge&logo=amd&logoColor=white)](https://www.amd.com/en/products/accelerators/instinct.html)
[![vLLM](https://img.shields.io/badge/vLLM-0.16.1.dev0-4B0082?style=for-the-badge&logo=python&logoColor=white)](https://github.com/vllm-project/vllm)
[![LangGraph](https://img.shields.io/badge/LangGraph-Parallel_State-FF6F00?style=for-the-badge&logo=langchain&logoColor=white)](https://github.com/langchain-ai/langgraph)
[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-18-61DAFB?style=for-the-badge&logo=react&logoColor=black)](https://react.dev/)
[![Vite](https://img.shields.io/badge/Vite-5.0-646CFF?style=for-the-badge&logo=vite&logoColor=white)](https://vitejs.dev/)
[![Qdrant](https://img.shields.io/badge/Qdrant-Vector_RAG-DC2626?style=for-the-badge&logo=qdrant&logoColor=white)](https://qdrant.tech/)
[![Semgrep](https://img.shields.io/badge/Semgrep-SAST_Rules-00D2FF?style=for-the-badge&logo=semgrep&logoColor=black)](https://semgrep.dev/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=for-the-badge)](LICENSE)

</div>

### Key Capabilities at a Glance

* **Parallel Agent Pipeline**: Runs security scanning, OWASP vector checks, and code quality checks simultaneously using LangGraph.
* **AMD Hardware Acceleration**: Powered by vLLM speculative decoding on an AMD Radeon PRO W7900D GPU, delivering 2.56x faster token generation.
* **Automated Remediation**: Detects code vulnerabilities, verifies findings to filter false alarms, synthesizes code patches, and opens GitHub Pull Requests with 1 click.

---

## Executive Summary

THEMIS is an automated code review platform built to audit pull requests for security vulnerabilities and code quality issues. It uses local open-weight language models (`Qwen2.5-Coder-32B-Instruct-AWQ`) running on **AMD Radeon PRO W7900D GPUs**.

Standard code linters produce high numbers of false warnings and cannot fix broken code. THEMIS addresses this by running a team of specialized AI agents in parallel using **LangGraph**. The platform parses code changes, queries security databases for known attack patterns, verifies findings to eliminate false positives, and generates ready-to-merge GitHub Pull Requests containing code fixes.

---

## System Architecture

THEMIS processes code reviews through a 5-step parallel agent pipeline:

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
     └───────────┬───────────┘       └───────────┬───────────┘
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

## Prerequisites and Setup

Before running THEMIS, ensure the following dependencies are installed on your system:
* **Python 3.11+**
* **Node.js 18+ and npm**
* **Git**

### Step 1: Environment File Setup
Copy the sample environment file to configure default application settings:
```bash
cp backend/.env.example backend/.env
```

### Step 2: Install Dependencies
```bash
# Install backend Python packages
pip install -r backend/requirements.txt

# Install frontend Node modules
cd frontend && npm install && cd ..
```

---

## Quickstart Guide

THEMIS provides 3 separate modes for testing and evaluation.

### Mode A: Web Application Interface (GUI)

1. Start the backend API server:
   ```bash
   uvicorn backend.main:app --host 0.0.0.0 --port 8080
   ```

2. In a second terminal, start the frontend development server:
   ```bash
   cd frontend
   npm run dev
   ```

3. Open your browser to `http://localhost:3000/tribunal` and click **Run Interactive Vulnerability Demo**.
   - The workflow diagram updates step-by-step: Triage -> Security / Style -> Verifier -> Fix Generator.
   - Click **Approve 2 Generated Patches** to trigger live automated PR creation and view the generated GitHub PR link badge.

### Mode B: Terminal User Interface (Bubbletea-Style TUI)

1. Launch the full-screen interactive TUI dashboard:
   ```bash
   python -m backend.cli
   ```
   Renders a 4-pane terminal interface with real-time DAG status, scrolling telemetry log stream, findings grid, code diff viewer, and an interactive prompt (`themis > `). Minimum terminal dimension limit: **80x24**.

2. Scan a public GitHub repository PR with SARIF 2.1.0 report export:
   ```bash
   python -m backend.cli scan --repo expressjs/express --pr 4200 --export sarif
   ```

3. Audit a local source file on disk with JSON report export:
   ```bash
   python -m backend.cli audit --file backend/main.py --export json
   ```

### Mode C: AMD ROCm Performance Benchmark

1. Run the performance metrics suite:
   ```bash
   python benchmarks/rocm_benchmark.py
   ```
   Displays performance tables comparing standard INT4 AWQ inference against speculative decoding with a 1.5B draft model.

2. Run the 10-case OWASP test suite:
   ```bash
   python tests/seeded_vulnerabilities.py
   ```


---

## AMD Hardware Acceleration & Benchmarks

THEMIS uses **vLLM speculative decoding** on the AMD ROCm 7.2.1 software stack for fast model inference:

* **Target Hardware**: AMD Radeon PRO W7900D (48GB GDDR6 VRAM, 192 Compute Units)
* **Main Model**: `Qwen/Qwen2.5-Coder-32B-Instruct-AWQ`
* **Speculative Draft Model**: `Qwen/Qwen2.5-Coder-1.5B-Instruct` (`--num-speculative-tokens 5`)

| Metric | Standard AWQ INT4 | Speculative (1.5B Draft) | Performance Gain |
|---|---|---|---|
| **Avg Throughput (tok/s)** | `3.6 tok/s` | `9.2 tok/s` | **2.56x Speedup** |
| **Time to First Token (TTFT)** | `1298 ms` | `884 ms` | **31.8% Faster** |
| **VRAM Footprint** | `37.2 GB / 48 GB` | `39.8 GB / 48 GB` | **Stable (80% Utilization)** |
| **ROCm Backend Engine** | `ROCM_AITER_FA` | `ROCM_AITER_FA` | **Flash Attention 2** |

---

## Troubleshooting and Common Issues

| Issue | Cause | Solution |
|---|---|---|
| `UnicodeEncodeError: 'charmap'` on Windows | Legacy Windows cmd stdout cannot encode emojis or unicode characters | Add `sys.stdout.reconfigure(encoding='utf-8')` early in Python entrypoints |
| `vLLM: Speculative decoding rejection` | vLLM V1 engine mode is incompatible with draft model speculative decoding | Set `export VLLM_USE_V1=0` before launching the vLLM server |
| `InvalidUpdateError: At key 'step_count'` | Parallel LangGraph nodes updating the same dictionary key without a reducer | Annotate state key with a custom reducer: `step_count: Annotated[int, max_step]` |
| `GitHub API 403 Forbidden` | Expired or unprivileged Fine-grained Personal Access Token | Verify `GITHUB_TOKEN` in `backend/.env` has `repo` write permissions |

---

## Frequently Asked Questions (FAQ)

### Can THEMIS run offline without an active cloud GPU attached?
Yes. THEMIS includes an offline Standalone Demo Mode (**Run Interactive Vulnerability Demo**) that uses static rule heuristics and pre-compiled diff vectors to demonstrate the full multi-agent pipeline and 1-click PR creation.

### How does THEMIS eliminate false positive warnings?
The **Verifier Agent** cross-references static analysis findings from Semgrep and Bandit against Qdrant vector similarity embeddings and enforces strict confidence bounds (threshold >0.85). Unverified findings are filtered out automatically.

### Does THEMIS modify original PR branches directly?
No. Following security best practices, THEMIS creates an isolated patch branch (such as `themis/patch-cwe-remediation`) and submits a separate Pull Request for human review before code is merged.

### What programming languages are supported?
THEMIS provides native static analysis rules, RAG vector embeddings, and patch generators for **Python**, **JavaScript / TypeScript**, **Go**, **Java**, and **C / C++**.

---

## Hackathon Rubric Alignment Matrix

| Evaluation Category | Key Rubric Criteria | Verification and Technical Evidence |
|---|---|---|
| **1. Innovation and Agentic Architecture** | Parallel state execution and multi-agent coordination | LangGraph state graph with custom `max_step` reducer in [`backend/agents/types.py`](file:///C:/Users/USER/Desktop/DevMaster/themis/backend/agents/types.py) |
| **2. Technical Implementation and AMD ROCm** | Hardware acceleration and throughput optimization | vLLM Speculative Decoding script (`vllm_speculative_deploy.sh`) and 2.56x speedup benchmark suite in [`benchmarks/rocm_benchmark.py`](file:///C:/Users/USER/Desktop/DevMaster/themis/benchmarks/rocm_benchmark.py) |
| **3. Practical Utility and Security Impact** | End-to-end vulnerability remediation and workflow integration | Automated OWASP / CWE patch synthesis and 1-click GitHub PR creation endpoint (`POST /api/review/{job_id}/apply-fix`) |
| **4. User Experience and Presentation** | Intuitive UI/UX, real-time feedback, and CLI / TUI accessibility | React dashboard with visual DAG stepper, telemetry console, Rich TUI (`python -m backend.cli demo`), and PR badges |

---

<div align="center">
  <b>Built by Team Alchemy for the AMD AI DevMaster Hackathon</b>
</div>
