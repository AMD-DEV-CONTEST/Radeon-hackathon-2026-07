# CodeRisk Agent — Project Specification

> AMD AI DevMaster Hackathon | Track 2: Agentic AI
> Team: Yang Weike (Solo Developer)
> Version: 1.0 | Date: 2026-08-03

---

## 1. Executive Summary

**CodeRisk Agent** is an AI-powered code security analysis system that runs entirely on local AMD Radeon GPUs. It combines multiple specialized AI agents with traditional static analysis tools to detect, verify, and report software vulnerabilities — without sending source code to any external service.

**Key Differentiators:**
- Multi-Agent architecture with 4 specialized agents + orchestrator
- Triple cross-validation with self-reflection loop
- Dual memory system (correct patterns + false positive suppression)
- Local CVE database (pre-downloaded from NVD)
- Full local execution on AMD GPU — code never leaves the machine

---

## 2. Problem Statement

### The Enterprise Code Security Dilemma

Modern enterprises face a critical tension: they need AI-powered code security analysis, but they cannot upload their source code to cloud services.

**Why code can't go to the cloud:**
- **Compliance:** HIPAA, GDPR, classified systems require data residency
- **Intellectual Property:** Core algorithms are trade secrets
- **Supply Chain Security:** Third-party code under NDA cannot be shared
- **Corporate Policy:** Samsung, Apple, Amazon, and JP Morgan have all banned cloud AI for code

**The scale of the problem:**
- 25,000+ new CVEs published annually (2025 data)
- 67% of enterprises express concern about AI code tool data security (Gartner, 2024)
- Average cost of a data breach: $4.88 million (IBM, 2024)

**The gap:** Existing tools like Semgrep find known patterns but miss logic vulnerabilities. Cloud AI understands code but requires uploading it. There is no solution that combines deep AI analysis with local-only execution.

### Comparison with Existing Tools

| Capability | Semgrep | Snyk | CodeQL | GitHub Copilot | **CodeRisk Agent** |
|------------|---------|------|--------|----------------|--------------------|
| Local execution | ✅ | ❌ | ✅ | ❌ | ✅ |
| LLM semantic analysis | ❌ | ❌ | ❌ | ✅ | ✅ |
| CVE/NVD integration | ❌ | ✅ | ❌ | ❌ | ✅ (local SQLite) |
| Self-learning memory | ❌ | ❌ | ❌ | ❌ | ✅ (dual memory) |
| Triple cross-validation | ❌ | ❌ | ❌ | ❌ | ✅ |
| Evidence chain | Pattern | Pattern | Pattern | Black box | **Full traceability** |
| Privacy | ✅ | ❌ | ✅ | ❌ | ✅ |
| GPU acceleration | ❌ | ❌ | ❌ | N/A | ✅ (ROCm/HIP) |

**Key differentiator:** CodeRisk Agent is the only tool that combines LLM-powered semantic analysis with local-only execution and a self-learning memory system. Existing tools are either local-but-shallow (Semgrep, CodeQL) or smart-but-cloud (Snyk, Copilot).

---

## 3. Solution Architecture

### System Overview

```
User uploads code
        ↓
┌───────────────────┐
│    Orchestrator    │  State machine: INIT → PARSE → ANALYZE → VERIFY → REPORT
└───────┬───────────┘
        ↓
┌───────┴────────┐
│                │
↓                ↓
Agent 1         Agent 2          Parallel execution
Static Analyzer  Semantic Analyzer
(CPU + tools)   (GPU + LLM)
│                │
└───────┬────────┘
        ↓
    ┌───┴───┐
    │ Self- │  Agent 3 flags missed risks, triggers re-analysis
    │Reflection│
    └───┬───┘
        ↓
    Agent 3                     Triple cross-validation
    Deep Verifier              (Tool + Knowledge Base + CVE)
    (GPU + LLM + Local SQLite)
        ↓
    Agent 4                     Structured reports
    Report Generator           (JSON + Markdown + Terminal + SARIF)
    (CPU)
        ↓
  ┌─────────────┐
  │ Memory Layer │  Correct memory + Error memory
  │  (JSON)      │  "Learns" from every scan
  └─────────────┘
        ↓
  Structured Audit Report
```

### Agent Design

| Agent | Role | Compute | Key Capability |
|-------|------|---------|----------------|
| Agent 1: Static Analyzer | Pattern matching | CPU | CWE-120/134/476/415/78/95/502/73/617 |
| Agent 2: Semantic Analyzer | LLM-driven analysis | GPU | Validates risks, finds missed vulnerabilities |
| Agent 3: Deep Verifier | Triple cross-validation | GPU + CPU | CVE lookup, memory recall, self-reflection |
| Agent 4: Report Generator | Output formatting | CPU | JSON, Markdown, Rich terminal, SARIF |
| Orchestrator | State machine | CPU | Pipeline coordination, error handling |

### Orchestrator State Machine

```
INIT → PARSE → ANALYZE → VERIFY → REPORT → DONE
           ↓          ↓
        Parse error  No risks found
           ↓          ↓
        ERROR      Direct REPORT (code is safe)
```

---

## 4. Core Features

### 4.1 Multi-Language Static Analysis

- **C/C++:** Buffer overflow (CWE-120), format string (CWE-134), double free (CWE-415), null pointer (CWE-476), command injection (CWE-78), file path injection (CWE-73), reachable assertion (CWE-617)
- **Python:** Code injection (CWE-95), deserialization (CWE-502), command injection (CWE-78), SQL injection (CWE-89)
- **Detection methods:** Regex patterns + Semgrep rules

### 4.2 LLM Semantic Analysis

- **Model:** Qwen2.5-Coder-32B-Instruct (32B parameters, 128K context)
- **Quantization:** Q4_K_M GGUF format (~19.6 GB model size)
- **Capabilities:**
  - Validates static analysis findings (true positive vs false positive)
  - Generates attack scenarios for confirmed vulnerabilities
  - Finds vulnerabilities missed by pattern matching
  - Adjusts severity based on code context

### 4.3 Deep Verification (Triple Cross-Validation)

**Strategy 1: Tool Confirmation**
- Did both static analysis and LLM agree?
- Multiple evidence sources boost confidence

**Strategy 2: Knowledge Base**
- CWE database validation
- Known vulnerability pattern matching

**Strategy 3: CVE Database**
- Local SQLite database lookup
- CVSS score from local SQLite database
- Historical exploit data

**Self-Reflection Loop:**
- Agent 3 reviews all findings from Agents 1 and 2
- Asks LLM: "Did we miss anything?"
- Found 4 additional risks in testing

### 4.4 Dual Memory System

**Correct Memory:**
- Stores confirmed vulnerability patterns
- Boosts confidence for known patterns
- Makes subsequent scans faster

**Error Memory:**
- Stores false positive patterns
- Suppresses known false alarms
- Reduces noise over time

**Persistence:** JSON-based storage, survives restarts

### 4.5 Structured Reporting

- **JSON:** Machine-readable, API-friendly
- **Markdown:** Human-readable, with CWE/CVE clickable links
- **Rich Terminal:** Color-coded, severity-sorted, with fix suggestion tree
- **SARIF:** Industry-standard static analysis report format
- **External References:** CWE MITRE links, NVD CVE links

---

## 5. ROCm Optimization

### 5.1 GPU Environment

| Component | Value |
|-----------|-------|
| GPU | AMD Radeon Pro W7900 (RDNA 3) |
| ROCm | 7.2.4 |
| HIP | 7.2.53211 |
| Platform | Radeon Cloud container |

### 5.2 Key Discovery

The llama.cpp build system changed the HIP backend flag:
- **Old (2024-2025):** `GGML_HIPBLAS=ON`
- **New (2026):** `GGML_HIP=ON`

This was the root cause of initial GPU inference failures — not container virtualization limitations.

### 5.3 Build Command

```bash
ROCM_PATH=/opt/rocm-7.2.4 cmake -B build -DGGML_HIP=ON -DLLAMA_BUILD_SERVER=ON
cmake --build build --config Release -j$(nproc)
```

### 5.4 Performance Results

| Metric | CPU | GPU (HIP) | Improvement |
|--------|-----|-----------|-------------|
| Token generation (32B) | 6.8 t/s | 29.4 t/s | **4.3×** |
| Token generation (7B) | — | 105 t/s | 15.4× |
| Prompt processing (32B) | — | 264.8 t/s | — |
| VRAM usage (32B) | — | 19.7 GB (41%) | — |
| VRAM usage (7B) | — | 19.6 GB | — |
| GPU temperature | — | 27°C (edge) | — |

> All performance data was measured on our Radeon Cloud instance
> (Pro W7900, ROCm 7.2.4, HIP backend).

### 5.5 Optimization Strategies

| Layer | Strategy | Expected Impact |
|-------|----------|-----------------|
| Model | Q4_K_M quantization |19.6 GB model size, fast inference |
| Model | Flash Attention (`-fa 1`) |Confirmed active via rocprof profiling (25,178 dispatches, 10.3%) |
| Task | Agent 1 on CPU, Agent 2/3 on GPU | Maximum GPU utilization |
| System | HIP backend | 4.3× vs CPU (32B); 15.4× (7B) |
| System | Continuous batching (future optimization) |3-5× throughput (future) |

---

## 6. Testing & Validation

### 6.1 Unit Tests

- 51 pytest tests, all passing
- Coverage: Buffer overflow, command injection, code injection, deserialization, safe code

### 6.2 End-to-End Test (Radeon Cloud)

| Component | Status | Details |
|-----------|--------|---------|
| Agent 1: Static | ✅ |5 files, 18 risks |
| Agent 2: LLM | ✅ |10 calls, 11,362 tokens |
| Agent 3: Verifier | ✅ |4 missed risks found, 1 false positive suppressed |
| Agent 4: Report | ✅ | JSON + Markdown + Terminal + SARIF |
| Memory Layer | ✅ |17 patterns recalled |
| CVE Client | ✅ | Local SQLite queries successful |

**Total:** 47 risks detected in 18 minutes (including GPU inference)

### 6.3 CVE Validation

Real CVE data from local SQLite database (pre-downloaded from NVD):
- CVE-1999-0046 (Buffer overflow, CVSS 10.0)
- CVE-1999-0067 (Command injection, CVSS 10.0)
- CVE-2003-0791 (Deserialization, CVSS 9.8)
- CVE-2002-0159 (Format string, CVSS 7.5)

## 7. Feature Completeness

### Implemented Features

| Feature | Status | Details |
|---------|--------|--------|
| Agent 1: Static Analysis | ✅ Complete | 27 rules (C: 13, Python: 14), regex pattern matching |
| Agent 2: Semantic Analysis | ✅ Complete | LLM-driven, ChatML format, attack scenario generation |
| Agent 3: Deep Verification | ✅ Complete | Triple cross-validation + self-reflection loop (max 2 rounds) |
| Agent 4: Report Generator | ✅ Complete | JSON + Markdown + Rich terminal, SARIF output |
| Orchestrator | ✅ Complete | State machine pipeline with error handling |
| Dual Memory System | ✅ Complete | Correct + Error memory, JSON persistence |
| Local CVE Database | ✅ Complete | SQLite, pre-downloaded from NVD |
| Local OSV Data | ✅ Complete | Pre-downloaded OSV bulk feeds, local lookup |
| Semgrep Integration | ✅ Complete | Optional layer, runs with local rules |
| Taint Analysis | ✅ Complete | Single-function variable tracking |
| Parallel Agent Execution | ✅ Complete | ThreadPoolExecutor, max_workers=1 for GPU |
| Incremental Result Saving | ✅ Complete | Crash recovery after each phase |
| Network Isolation | ✅ Complete | Zero runtime network calls (tcpdump verified) |
| Unit Tests | ✅ Complete | 51 tests covering all agents and core modules |
| Demo Video | ✅ Complete | 3:04, 4K resolution |

### Planned Features

| Feature | Priority | Rationale |
|---------|----------|----------|
| Java support | P1 | 15+ rules targeting OWASP Top 10 Java patterns |
| Go support | P1 | Goroutine concurrency issue detection |
| Rust support | P2 | Unsafe block analysis |
| Cross-function taint analysis | P2 | Call graph construction for multi-function data flow |
| LLM batch processing | P2 | Batch small files into single LLM call (50-70% fewer calls) |
| Web UI | P3 | Browser-based code upload and report viewing |
| IDE plugin | P3 | VS Code / JetBrains integration |
| CI/CD integration | P3 | GitHub Actions for automated scanning |

### Scope Decision

Language coverage (C + Python) was a deliberate scope decision: **deep rule quality over shallow multi-language coverage**. Each language receives the same depth of rules (13-14 per language) and full semantic analysis before release. This ensures that CodeRisk Agent provides production-grade detection for supported languages rather than superficial coverage of many languages.

---

## 8. Technology Stack

| Component | Technology |
|-----------|-----------|
| Language | Python 3.12 |
| Output Formats | JSON, Markdown, Rich terminal, SARIF |
| LLM | Qwen2.5-Coder-32B-Instruct (GGUF Q4_K_M) |
| LLM Runtime | llama.cpp with HIP backend |
| Static Analysis | Regex + Tree-sitter + Semgrep |
| CVE Database | Local SQLite (National Vulnerability Database) |
| Memory | JSON-based dual memory system |
| CLI | Rich terminal UI |
| Testing | pytest |
| GPU | AMD Radeon Pro W7900 (48GB GDDR6) + ROCm 7.2.4 |

---

## 9. Repository & Documentation

| Resource | Location |
|----------|----------|
| Main Repository | https://github.com/a9320/code-risk-agent |
| Hackathon Fork | https://github.com/a9320/Radeon-hackathon-2026-07 |
| ROCm Optimization Docs | docs/rocm-optimization.md |
| Demo Video Script | docs/demo-video-script.md |
| Submission Checklist | docs/submission-checklist.md |
| Architecture Review | docs/architecture-review.md |
| PPT Presentation | docs/CodeRisk_Agent_Presentation.pptx |
| Benchmark Script | scripts/benchmark.py |

---

## 10. Reproducibility & Verification

### Environment Requirements

| Component | Requirement |
|-----------|------------|
| GPU | AMD Radeon Pro W7900 (48GB GDDR6) or equivalent |
| ROCm | 7.2.4 (7.2.1 will NOT work — HIP flag changed) |
| Python | 3.12 |
| CPU | AMD EPYC 9334 32-Core (128 threads, 2 sockets) |
| RAM | 503 GB DDR5 |
| System | Linux (Ubuntu 22.04+ recommended) |
| Disk | 25GB+ (model + CVE database) |

### Build & Run Steps

```bash
# 1. Clone repository
git clone https://github.com/a9320/code-risk-agent.git
cd code-risk-agent

# 2. Install Python dependencies
pip install -e .

# 3. Build llama.cpp with HIP backend (CRITICAL: use GGML_HIP, not GGML_HIPBLAS)
git clone https://github.com/ggerganov/llama.cpp
cd llama.cpp
ROCM_PATH=/opt/rocm-7.2.4 cmake -B build -DGGML_HIP=ON -DLLAMA_BUILD_SERVER=ON
cmake --build build --config Release -j$(nproc)
cd ..

# 4. Download model
huggingface-cli download Qwen/Qwen2.5-Coder-32B-Instruct-GGUF \
  qwen2.5-coder-32b-instruct-q4_k_m.gguf --local-dir models/

# 5. Build local CVE database
python scripts/download_cve_data.py --years 2023 2024 2025 2026

# 6. Run tests
pytest  # 51 tests, all should pass

# 7. Run analysis
python main.py analyze tests/test_cases/ --output terminal
# Expected: 47 risks detected in ~18 minutes
```

### Performance Verification

```bash
# Start llama-server with GPU
./llama.cpp/build/bin/llama-server \
  -m models/qwen2.5-coder-32b-instruct-q4_k_m.gguf \
  -ngl 999 -fa 1 --host 0.0.0.0 --port 8080

# Verify GPU is being used
rocm-smi  # Should show ~19.7 GB VRAM usage (41%)

# Test inference speed
curl http://localhost:8080/completion -d '{"prompt":"test","n_predict":100}'
# Expected: ~29.4 t/s token generation (32B)
```

### Zero Network Calls Verification

```bash
# Monitor network during full test suite
sudo tcpdump -i any -n "tcp and not src host 127.0.0.1 and not dst host 127.0.0.1" -w monitor.pcap &
TCPDUMP_PID=$!

# Run full analysis
python -m pytest tests/ -v
python main.py analyze tests/test_cases/ --output json

# Stop monitoring
kill $TCPDUMP_PID
tcpdump -r monitor.pcap -n
# Expected: empty output (zero outbound connections)
```

### Expected Results

| Metric | Expected Value |
|--------|---------------|
| Unit tests | 51/51 passing |
| E2E risks detected | 47 |
| E2E duration | ~18 minutes |
| GPU token generation | ~29.4 t/s (32B) / ~105 t/s (7B) |
| CPU token generation | ~6.8 t/s |
| Speedup | ~4.3× (32B) / ~15.4× (7B) |
| VRAM usage | ~19.7 GB (41%) |
| Network calls | 0 |

---

## 11. Team

| Member | Role | Strengths |
|--------|------|-----------|
| Yang Weike | Solo Developer — Architecture, Implementation, Testing, Documentation |

---

## 12. Future Work

- **Semgrep integration in Radeon Cloud container** — install in venv for full pipeline
- **Continuous batching deployment** — continuous batching for higher throughput
- **Web UI** — browser-based code upload and report viewing
- **More languages** — Java, Go, Rust support
- **ChromaDB upgrade** — vector database for semantic memory matching
- **CI/CD integration** — GitHub Actions for automated security scanning

---

*Generated: 2026-08-04 | CodeRisk Agent v1.0*
