# InventoryDoc Agent

**One-liner**: A locally-deployed, private inventory variance audit Agent — a deterministic 10-step workflow with an evidence-chain quality gate that turns 10 messy inventory files into auditable, verifiable, meeting-ready adjustment materials.

> AMD AI DevMaster Hackathon 2026 — Track 2: Private AI Agent Development & Local Deployment

## Quick Start

> **Requirements**: Python 3.10+, pip. GPU optional (the workflow itself is CPU pandas; only the management report needs vLLM/ROCm).

### Install

```bash
git clone https://github.com/cyslmsolomon/Radeon-hackathon-2026-07.git
cd Radeon-hackathon-2026-07
pip install -r requirements.txt
```

### Launch

Two entry points, one shared Agent core:

| Mode | Command | Notes |
|------|---------|-------|
| **CLI one-shot** | `python3 run_full_workflow.py` | Runs all 10 steps, outputs Excel + MD — good for batch/CI |
| **Gradio Web UI** | `python3 start_ui.py` | Interactive upload → analyze → download |
| **Web UI (alt)** | `python3 -m src.agent` | Same as `start_ui.py` |

> 💡 CLI and UI run **independently**: CLI output files can be used directly, and the UI can run the workflow on files you upload.
>
> 💡 Port 7860 busy? Use `GRADIO_SERVER_PORT=7861 python3 start_ui.py`

### Management Report (GPU inference)

```bash
# Demo mode (pure rules, data-driven, no GPU needed)
python3 scripts/generate_report.py --demo

# Mock mode (simulated LLM response, no hardcoded facts, no GPU needed)
python3 scripts/generate_report.py --mock

# Real LLM mode (requires a local inference service on localhost:8000)
python3 scripts/generate_report.py
```

### One-command submission verification

```bash
python3 scripts/verify_submission.py
# Runs: tests → full workflow → quality gate → report generation → git safety check
```

### Judge's 5-minute acceptance path

```bash
python3 scripts/verify_submission.py                  # one-click full check
python3 tests/test_workflow.py                        # core logic tests
python3 run_full_workflow.py                          # full workflow
python3 scripts/generate_report.py --demo             # demo-mode report
python3 scripts/generate_report.py --mock             # mock-LLM report
```

### GPU / LLM Benchmark

```bash
python3 scripts/benchmark_llm.py
# Output: model list, latency, chars/sec, estimated tokens/sec
```

#### Start a local LLM inference service (AMD ROCm GPU)

Download a GGUF model and serve it with `llama.cpp`:

```bash
# Install modelscope (China mirror)
pip install modelscope -i https://pypi.tuna.tsinghua.edu.cn/simple

# Download Qwen2.5-7B GGUF (~4.4GB, Q4_K_M quantization)
python3 -c "
from modelscope import snapshot_download
snapshot_download('Qwen/Qwen2.5-7B-Instruct-GGUF',
    local_dir='./qwen-model',
    allow_patterns=['*q4_k_m*gguf'])
"

# Start inference service (requires llama.cpp compiled with ROCm/HIP support)
./llama.cpp/build/bin/llama-server \
  -m ./qwen-model/qwen2.5-7b-instruct-q4_k_m.gguf \
  --host 0.0.0.0 --port 8000 -ngl 99 -a qwen2.5
```

> ⚠️ `generate_report.py` depends on `data/output/analysis_result.json`, which is produced by the CLI workflow. If you only launched the UI, run the workflow from the "Analyze" tab first.

More: [Project Report](docs/project_report.md) · [Enterprise Architecture](docs/enterprise_architecture.md) · [Evaluation](docs/evaluation.md) · [GPU Demo Runbook](docs/gpu_demo_runbook.md) · [Demo Script](scripts/demo_script.md) · [PRD](docs/product_prd.md)

## The Problem

Warehouse management holds an inventory adjustment meeting and needs materials that clearly explain the variance and support accountability. But reality:

- 10 data files scattered across CSV/XLSX/TXT with inconsistent encodings
- Manual analysis takes 2-3 days and is error-prone (wrong baseline, cost mistaken for selling price, inconsistent numbers)
- By the time management sees the report, the cause of the variance can no longer be explained

## What We Built

**InventoryDoc Agent** is a locally-deployed inventory variance audit Agent. Upload the count data and it automatically:

### Three Core Innovations

1. **Intelligent Noise Detection** — automatically identifies 3 types of noise (NOISE interference, abnormal records, inapplicable files) with no manual filtering
2. **Three-Dimensional Baseline Selection** — picks the correct baseline by comparing encoding scheme, time window, and data granularity
3. **Three-Class Log Correlation** — compares actual in/out variance (not just "was there an operation"), precisely classifying records as explainable / partially explainable / unexplained

### Enterprise-Grade Features

- **Audit-grade evidence chain** — every run has a `run_id`, input-file hashes, and per-step timing traces; every conclusion is traceable
- **Quality gate system** — 7 quality checks with severity/gate logic; critical failures block report generation (`report_allowed=False`)
- **Input data contract** — validates all 10 files before running; blocks automatically if required files are missing
- **Deterministic workflow** — 10 pure-pandas steps, zero LLM involvement in facts, results are reproducible
- **Audit evidence pack / adjustment pack** — Excel (6 sheets, conditional formatting) + analysis report (8 chapters) + `analysis_result.json` (metadata + quality gate + audit trail)
- **Management report** — data-driven, no hardcoded SKUs; Top-5 comes from `_metadata.top_variance_skus`
- **Disposition recommendations** — 5 deterministic rule classes (adjust directly / need supporting docs / need on-site re-check / need location check / need special rectification)

## Why This Is an AI Agent

| Agent Capability | Implementation in This Project |
|---|---|
| **Multi-step Planning** | 10-step deterministic workflow + state-machine orchestration + blocking gates |
| **Tool Calling** | CSV/XLSX/TXT loaders, Excel generator, MD report, LLM report |
| **Memory** | `ConsistencyMemory` for cross-file consistency + persisted conversation history |
| **Grounding** | Every conclusion is based on the uploaded business files; the LLM never fabricates |
| **Local Deploy** | Fully local, zero cloud API dependency |

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Gradio Web UI (4 Tabs)                        │
│  [Analyze]  [📊 Management Report]  [💬 Chat]  [About]           │
└──────────────────────────────┬──────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────┐
│                   Agent Core (10-Step Workflow)                  │
│                                                                 │
│  Step 1:  Multi-format load     Step 6:  Variance amount calc    │
│  Step 2:  Smart noise detection Step 7:  3-class log correlation │
│  Step 3:  3-D baseline selection Step 8: Location status check   │
│  Step 4:  Scan-log cleaning     Step 9:  Category analysis       │
│  Step 5:  Count result load     Step 10: Deliverables            │
│                                                                 │
│  ┌───────────────┐ ┌──────────────┐ ┌──────────────────────┐   │
│  │ Noise Detector│ │ Quality Check│ │ Consistency Memory   │   │
│  │ (3 noise types)│ │ (7 checks)   │ │ (cross-file)         │   │
│  └───────────────┘ └──────────────┘ └──────────────────────┘   │
└──────────────────────────────┬──────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────┐
│                   Output Deliverables                            │
│  Excel (6 sheets) + Markdown Report (8 chapters) + Analysis JSON │
└──────────────────────────────┬──────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────┐
│              Local LLM Report Generator (GPU layer)              │
│  vLLM / llama.cpp + AMD ROCm                                    │
│  Generates: management summary + risk grading + Top-5 SKU        │
│  interpretation + action recommendations                        │
└─────────────────────────────────────────────────────────────────┘
```

## Competitive Advantage

| Capability | Manual Analysis | Other AI Solutions | InventoryDoc Agent |
|---|---|---|---|
| Automatic noise detection | ❌ manual exclusion | ❌ not available | ✅ 3 noise types auto-detected |
| Smart baseline selection | ⚠️ experience-based | ❌ not available | ✅ auto-judges usable data |
| 3-class log correlation | ⚠️ easy to misjudge | ❌ simple matching | ✅ precise net-variance comparison |
| Quality checks | ❌ none | ❌ none | ✅ 7 automated checks |
| Analysis time | 2-3 days | 30 minutes | **<1 minute** |
| Deployment | N/A | cloud API | **local GPU, data never leaves device** |

## Ground Truth Validation

Tested against real supply-chain inventory data; every metric matches manual analysis:

| Metric | Agent Output | Manual Verification | Status |
|---|---|---|---|
| SKU total | 528 | 528 | ✅ |
| System stock total | 21,144 units | 21,144 units | ✅ |
| Recount total | 20,173 units | 20,173 units | ✅ |
| Net variance | -971 units | -971 units | ✅ |
| Overall variance rate | 4.6% | 4.6% | ✅ |
| Shrinkage amount | -1,146,805.36 CNY | -1,146,805.36 CNY | ✅ |
| Net variance amount | -989,900.97 CNY | -989,900.97 CNY | ✅ |
| NOISE detected | 68 records | 68 records | ✅ |
| 3-class log correlation | 14/21/124 | 14/21/124 | ✅ |
| Abnormal category | Bathroom furniture 16.0% | Bathroom furniture 16.0% | ✅ |
| Quality checks | 7/7 passed | 7/7 passed | ✅ |

## Data Boundaries & AI Division of Labor

- **Fact computation**: all 10 workflow steps run in pandas — no randomness, no LLM. Results are reproducible and auditable
- **LLM role**: only natural-language expression in the management-report step; never involved in fact computation or data decisions
- **Local deployment**: data is read from local directories and written to local directories; no external API or cloud service is called
- **No Dify dependency**: the current MVP needs no Dify, n8n, or enterprise systems. CLI + Gradio + local LLM complete the end-to-end loop. Dify Agent Workbench is reserved for phase-2 enterpriseization

## Lightweight Policy Knowledge Base

The project ships lightweight policy docs describing the business rules the Agent enforces:

- [`docs/knowledge/inventory_adjustment_policy.md`](docs/knowledge/inventory_adjustment_policy.md) — adjustment principles, process, and amount criteria
- [`docs/knowledge/warehouse_counting_sop.md`](docs/knowledge/warehouse_counting_sop.md) — counting SOP and quality-gate requirements
- [`docs/knowledge/scan_log_governance.md`](docs/knowledge/scan_log_governance.md) — NOISE data handling, log integrity, correlation classes
- [`docs/knowledge/location_management_policy.md`](docs/knowledge/location_management_policy.md) — location status classes and risk-flag rules

## Why AMD ROCm

- **Data security**: inventory data involves stock amounts and supplier info — it cannot go to the cloud. Local GPU deployment keeps data on-device end to end
- **Zero API cost**: deploy once, no ongoing token fees; a major advantage for high-frequency enterprise use
- **Offline capable**: works even in warehouses with poor connectivity; no external service dependency
- **Open ecosystem**: ROCm is fully open source — no vendor lock-in, deeply customizable

## GPU Optimization (Track 2 Requirement)

The knowledge base requires quantified metrics. Our approach:

| Layer | Optimization | Expected Impact |
|---|---|---|
| LLM inference | FP16 mixed precision on ROCm | ~50% VRAM reduction vs FP32 |
| vLLM | Continuous batching + PagedAttention | 2-4x throughput, larger batch |
| Quantization | INT4/INT8 GGUF (e.g., Qwen2.5-7B Q4_K_M) | fits 24GB VRAM with headroom |
| CPU pipeline | Batch file loading, incremental caching | full workflow ~8s |

Measured on the workflow: the 10-step pandas pipeline completes in ~8 seconds (pure computation). LLM report metrics (TTFT, tokens/sec, peak VRAM) are captured by `scripts/benchmark_llm.py` and `data/output/report_generation_metadata.json` on the target AMD Radeon GPU; see the [GPU Demo Runbook](docs/gpu_demo_runbook.md) for the live-demo evidence checklist.

## Tech Stack

- **LLM inference**: vLLM + ROCm (AMD Radeon GPU acceleration), llama.cpp supported
- **Agent orchestration**: 10-step deterministic workflow (pandas-driven, zero-LLM fact computation, auditable)
- **Data processing**: Pandas + multi-format file loading
- **UI**: Gradio web interface (4 tabs: Analyze, Management Report, Chat, About)
- **Platform**: AMD Radeon GPU + ROCm 6.x

## Project Structure

```
inventory-agent/
├── src/
│   ├── agent.py              # Agent core (10-step workflow orchestration)
│   ├── report_generator.py   # LLM management report generation (GPU layer)
│   ├── noise_detector.py     # intelligent noise detection
│   ├── quality_checker.py    # 7 quality checks
│   ├── memory.py             # cross-file consistency memory
│   ├── rag.py                # multi-format file loading & grounding
│   ├── tools.py              # Excel read/write & computation tools
│   └── ui.py                 # Gradio web interface
├── config/
│   ├── settings.yaml          # model/data/noise/quality config
│   ├── ground_truth.yaml      # sample-data benchmark
│   └── data_contracts.yaml    # input file contract
├── data/input/               # input data (10 business files, not committed)
├── data/output/              # output (Excel + MD + JSON, generated)
├── scripts/
│   ├── generate_report.py    # management report generation (GPU entry)
│   ├── mock_llm_server.py    # mock LLM service (testing)
│   ├── benchmark_llm.py      # LLM health check & performance test
│   ├── verify_submission.py  # one-click submission verification
│   └── demo_script.md        # demo recording script
├── docs/
│   ├── project_report.md     # project technical report
│   ├── product_prd.md        # product requirements doc
│   ├── enterprise_architecture.md  # enterprise architecture doc
│   ├── evaluation.md         # acceptance & test criteria
│   ├── gpu_demo_runbook.md   # GPU live-demo runbook
│   └── knowledge/            # business policy knowledge base
├── tests/test_workflow.py    # unit tests
├── run_full_workflow.py      # full workflow CLI
└── start_ui.py               # launch Gradio UI
```

## Demo Video & Presentation

📥 **Download from GitHub Release**: [InventoryDoc Agent V1.1 — Release v1.1](https://github.com/cyslmsolomon/Radeon-hackathon-2026-07/releases/tag/v1.1)

| File | Description |
|---|---|
| `InventoryDoc_Agent_Demo_EN.mp4` | English demo video (3-5 min) |
| `InventoryDoc_Agent_Demo.mp4` | Chinese demo video (3-5 min) |
| `InventoryDoc_Agent_Demo_EN.pptx` | English presentation slides |

The demo video covers: Web UI walkthrough, CLI pipeline execution, AMD ROCm GPU inference evidence (`rocm-smi` + benchmark), quality gate verification, and management report generation.

## Team

| Role | Name | Responsibility |
|---|---|---|
| Developer | — | Use-case definition, product design, Agent development, data processing, system integration |

## Contact

- Email: 1026858211@qq.com

## Submission Checklist (AMD AI DevMaster Track 2)

- [x] Project Specification Document (`docs/project_spec.md`)
- [x] Project source code (`src/`, complete and runnable)
- [x] README (environment, startup guide, architecture, dependency list)
- [x] Demo video (3-5 min, [Release v1.1](https://github.com/cyslmsolomon/Radeon-hackathon-2026-07/releases/tag/v1.1))
- [x] Supplementary materials — PPT ([Release v1.1](https://github.com/cyslmsolomon/Radeon-hackathon-2026-07/releases/tag/v1.1))
- [x] GitHub repository (fork of AMD-DEV-CONTEST/Radeon-hackathon-2026-07)
- [ ] AMD Developer Program registration confirmed
