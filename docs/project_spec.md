# InventoryDoc Agent — Project Specification Document

> AMD AI DevMaster Hackathon 2026 — Track 2: Development & Local Deployment of Private AI Agents

---

## 1. Application Scenarios

### 1.1 Problem Context

Enterprise warehouse inventory counting is a core business process. When the physical count diverges from the system record, a variance analysis must be performed and presented to management for approval before adjustments can be made. This process is currently manual, slow, and error-prone.

### 1.2 Target Scenarios

| Scenario | Description | Current Pain |
|---|---|---|
| **Monthly inventory count** | Warehouse teams count stock, compare with ERP system | 2-3 days of manual spreadsheet analysis |
| **Adjustment meeting prep** | Finance needs variance reports with evidence chains | Data scattered across 10+ files in mixed formats (CSV/XLSX/TXT) |
| **Audit trail generation** | Internal/external auditors need traceable analysis | No automated audit trail; manual work is not reproducible |
| **Multi-category variance review** | Identify categories with abnormally high variance rates | Easy to miss patterns when done manually |

### 1.3 Input Data

The agent processes 10 business files in mixed formats:

| File Type | Content | Format |
|---|---|---|
| Inventory snapshots | System stock quantities by SKU | CSV/XLSX |
| Physical count results | Actual counted quantities | XLSX |
| Scan logs | Warehouse movement records (in/out) | CSV/TXT |
| Product master data | SKU attributes, cost prices, categories | XLSX |
| Location master data | Warehouse location status | XLSX |
| Historical inventory | Previous period stock levels | XLSX |
| Monthly reports | Monthly inventory summaries | XLSX |

### 1.4 Expected Output

| Deliverable | Format | Description |
|---|---|---|
| Variance detail sheet | Excel (6 tabs) | SKU-level variance with conditional formatting |
| Analysis report | Markdown (8 chapters) | Statistical analysis with explanations |
| Management summary | Markdown | Executive summary with risk grading |
| Analysis result JSON | JSON | Machine-readable metadata + audit trail |
| Quality gate result | Embedded in JSON | 7 automated quality checks |

---

## 2. Agent Architecture

### 2.1 System Architecture Diagram

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

### 2.2 Module Architecture

| Module | File | Responsibility |
|---|---|---|
| Agent Core | `src/agent.py` | 10-step workflow orchestration, state machine |
| Data Engine | `src/rag.py` | Multi-format file loading (CSV/XLSX/TXT) |
| Noise Detector | `src/noise_detector.py` | 3-type noise identification |
| Tools | `src/tools.py` | Excel I/O, variance computation |
| Memory | `src/memory.py` | Cross-file consistency checks |
| Quality Checker | `src/quality_checker.py` | 7 automated quality gates |
| Report Generator | `src/report_generator.py` | LLM management report (GPU layer) |
| UI | `src/ui.py` | Gradio web interface (4 tabs) |
| I18N | `src/i18n.py` | Bilingual support (EN/ZH) |
| Input Validator | `src/input_validator.py` | Data contract validation |

### 2.3 Data Flow

```
Input (10 files)
    │
    ▼
Input Validation (data_contracts.yaml)
    │
    ▼
10-Step Deterministic Workflow (pure pandas, zero LLM)
    │
    ▼
Quality Checks (7 gates, critical = blocks report)
    │
    ├──→ Excel (6 sheets) + Analysis Report (8 chapters) + JSON
    │
    ▼
LLM Management Report (real / mock / demo mode)
    │
    ▼
Management Review → Adjustment Execution
```

---

## 3. Core Capabilities

### 3.1 Three Core Innovations

#### 3.1.1 Intelligent Noise Detection

Automatically identifies 3 types of noise in input data:

| Noise Type | Example | Detection Method |
|---|---|---|
| NOISE interference | Records prefixed with `NOISE-` in scan logs | Pattern matching |
| Abnormal records | Quantities exceeding physical limits | Statistical thresholds |
| Inapplicable files | Monthly reports, historical snapshots | File-type classification |

**Impact**: Eliminates 68 noise records from the sample dataset automatically.

#### 3.1.2 Three-Dimensional Baseline Selection

Picks the correct baseline file by comparing across 3 dimensions:

| Dimension | Method |
|---|---|
| Encoding scheme | Character encoding compatibility check |
| Time window | Temporal proximity to count date |
| Data granularity | SKU-level vs. aggregate-level matching |

**Impact**: Prevents wrong baseline selection, which is the #1 cause of manual errors.

#### 3.1.3 Three-Class Log Correlation

Compares actual net in/out variance (not just "was there an operation"):

| Class | Meaning |
|---|---|
| Fully explainable | In-out operations fully account for the variance |
| Partially explainable | Operations explain part of the variance |
| Unexplained | No matching operations found; needs investigation |

**Impact**: Precise classification for 159 records (14/21/124 in sample data).

### 3.2 Enterprise Features

| Feature | Description |
|---|---|
| **Audit-grade evidence chain** | Every run has `run_id`, input-file hashes, per-step timing |
| **Quality gate system** | 7 checks with severity levels; critical failures block reports |
| **Input data contract** | Validates all required files before execution |
| **Deterministic workflow** | 10 pure-pandas steps; results are reproducible |
| **Disposition recommendations** | 5 rule-based action classes for each variance item |
| **Bilingual UI** | English and Chinese interface with language toggle |
| **Chat with evidence** | FAQ answers cite specific workflow outputs |

### 3.3 AI Agent Capability Mapping (Track 2)

| Track 2 Requirement | Implementation |
|---|---|
| Multi-step Planning | 10-step workflow + state machine + blocking gates |
| Tool Calling | CSV/XLSX/TXT loaders, Excel generator, MD report, LLM report |
| Memory | `ConsistencyMemory` for cross-file consistency + chat history |
| Grounding | All conclusions based on uploaded business files; LLM never fabricates |
| Local Deploy | Fully local, zero cloud API dependency |

---

## 4. Model Introduction & Local Deployment Plan

### 4.1 LLM Model Selection

| Model | Size | Quantization | VRAM | Purpose |
|---|---|---|---|---|
| Qwen2.5-7B-Instruct | 7B | Q4_K_M (GGUF) | ~5 GB | Primary: management report generation |
| Llama-3.1-8B-Instruct | 8B | FP16 | ~16 GB | Alternative: higher quality output |

### 4.2 Deployment Architecture

```
┌─────────────────────────────────────────────────┐
│              AMD Radeon GPU (24GB VRAM)          │
│  ┌─────────────┐                                 │
│  │ vLLM Engine │  or  llama.cpp                  │
│  │ (LLM infer) │      (GGUF loader)              │
│  └─────────────┘                                 │
│         ↑                                        │
│         │    ROCm 6.x                            │
│  ┌──────┴──────────────────────────┐             │
│  │      ROCm Runtime Layer         │             │
│  └─────────────────────────────────┘             │
└─────────────────────────────────────────────────┘
         ↑
    vLLM API (localhost:8000/v1)
         ↑
┌────────┴────────────────────────────────────────┐
│         Agent Core (Python)                     │
│  ┌──────────┐ ┌──────────┐ ┌──────────────┐   │
│  │ 10-Step  │ │ Pandas   │ │ Report Gen.  │   │
│  │ Workflow │ │ (data)   │ │ (LLM call)   │   │
│  └──────────┘ └──────────┘ └──────────────┘   │
└────────────────────────────────────────────────┘
         ↑
┌────────┴────────────────────────────────────────┐
│         Gradio Web UI                           │
│    http://localhost:7860                         │
└─────────────────────────────────────────────────┘
```

### 4.3 Deployment Steps

```bash
# Step 1: Install dependencies
pip install -r requirements.txt

# Step 2: Download model (Qwen2.5-7B GGUF)
python3 -c "
from modelscope import snapshot_download
snapshot_download('Qwen/Qwen2.5-7B-Instruct-GGUF',
    local_dir='./qwen-model',
    allow_patterns=['*q4_k_m*gguf'])
"

# Step 3: Start LLM service (llama.cpp with ROCm)
./llama.cpp/build/bin/llama-server \
  -m ./qwen-model/qwen2.5-7b-instruct-q4_k_m.gguf \
  --host 0.0.0.0 --port 8000 -ngl 99 -a qwen2.5

# Step 4: Launch Agent UI
python3 start_ui.py
```

### 4.4 Fallback Modes

| Scenario | Solution |
|---|---|
| No GPU available | `--demo` mode (pure rules, no LLM) |
| LLM service not started | `--mock` mode (simulated LLM response) |
| Port conflict | `GRADIO_SERVER_PORT=7861 python3 start_ui.py` |
| Insufficient VRAM | Use smaller quantization (Q4_K_M) or smaller model |

---

## 5. AMD Radeon GPU Inference Optimization

### 5.1 Optimization Strategy

| Layer | Technique | Expected Impact |
|---|---|---|
| **LLM Inference** | FP16 mixed precision on ROCm | ~50% VRAM reduction vs FP32 |
| **Batching** | vLLM continuous batching + PagedAttention | 2-4x throughput, larger batch size |
| **Quantization** | INT4/INT8 GGUF (Qwen2.5-7B Q4_K_M) | Fits in 24GB VRAM with headroom |
| **CPU Pipeline** | Batch file loading, incremental caching | Full workflow ~8 seconds |

### 5.2 Performance Metrics

#### 10-Step Workflow (CPU, Pandas)

| Step | Time | Description |
|---|---|---|
| Step 1-2: Load + Noise | ~2s | Multi-file read + NOISE detection |
| Step 3: Baseline | <1s | 3-D comparison |
| Step 4: Log cleaning | ~1s | NOISE filter + time window |
| Step 5-6: Variance | ~1s | Count result + amount matching |
| Step 7: Correlation | ~1s | 3-class comparison |
| Step 8-9: Check + Analysis | <1s | Location + category |
| Step 10: Deliverables | ~1s | Excel + MD generation |
| **Total** | **~8s** | Deterministic, reproducible |

#### LLM Report Generation (GPU)

| Metric | AMD RX 7900 XTX (FP16) |
|---|---|
| Model | Qwen2.5-7B-Instruct Q4_K_M |
| Time to first token | ~300ms |
| Output tokens | ~800-1200 |
| Generation time | ~10-15s |

### 5.3 AMD ROCm Advantages

| Dimension | AMD ROCm | NVIDIA CUDA |
|---|---|---|
| Open source | Fully open | Closed |
| Hardware cost | Lower | High-end GPUs expensive |
| Enterprise lock-in | None | NVIDIA-dependent |
| LLM support | vLLM native | vLLM native |

### 5.4 Benchmarking

```bash
python3 scripts/benchmark_llm.py
# Output: model list, latency, chars/sec, estimated tokens/sec
```

---

## 6. Ground Truth Validation

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

---

## 7. Competitive Advantage

| Capability | Manual Analysis | Other AI Solutions | InventoryDoc Agent |
|---|---|---|---|
| Automatic noise detection | ❌ manual exclusion | ❌ not available | ✅ 3 noise types auto-detected |
| Smart baseline selection | ⚠️ experience-based | ❌ not available | ✅ auto-judges usable data |
| 3-class log correlation | ⚠️ easy to misjudge | ❌ simple matching | ✅ precise net-variance comparison |
| Quality checks | ❌ none | ❌ none | ✅ 7 automated checks |
| Analysis time | 2-3 days | 30 minutes | **<1 minute** |
| Deployment | N/A | cloud API | **local GPU, data never leaves device** |

---

## 8. Tech Stack

| Component | Technology |
|---|---|
| LLM Inference | vLLM + ROCm / llama.cpp |
| Agent Orchestration | 10-step deterministic workflow (pandas) |
| Data Processing | Pandas + multi-format file loading |
| UI | Gradio web interface (4 tabs) |
| Platform | AMD Radeon GPU + ROCm 6.x |
| Language | Python 3.10+ |

---

> Document version: v1.1 | Last updated: 2026-07-31
