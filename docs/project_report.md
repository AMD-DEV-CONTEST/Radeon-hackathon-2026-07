# InventoryDoc Agent — Project Technical Report

> AMD AI DevMaster Hackathon | Track 2: Private AI Agent Development & Local Deployment

---

## One-Sentence Summary

**InventoryDoc Agent is a locally-deployed, private AI Agent built on AMD Radeon GPU + ROCm. Upload 10 inventory files and it automatically produces meeting-ready adjustment materials, pinpointing a net variance of 989,900.97 CNY.**

---

## 1. Project Background

### 1.1 Problem Definition

Enterprise warehouse counting is a core part of inventory management, but variance analysis has long depended on manual work:

| Pain Point | Current State | Impact |
|---|---|---|
| Scattered data | 10+ files (CSV/XLSX/TXT) with inconsistent encodings | open and convert each file by hand |
| Noise interference | NOISE interference data, abnormal records, inapplicable files mixed in | wrong conclusions from misused data |
| Slow analysis | 2-3 days from cleaning to report | delayed management meetings, untimely accountability |
| Error-prone | wrong baseline, cost mistaken for price, inconsistent numbers | untrustworthy evidence, wrong adjustment decisions |

### 1.2 Target Users

- Warehouse management: needs meeting-ready variance-analysis materials
- Inventory control specialists: need full automation from data cleaning to report generation
- Finance: needs accurate variance amounts and financial-impact estimates

## 2. Solution

### 2.1 Core Innovations

| Innovation | Description | Comparison with Market |
|---|---|---|
| **Automatic noise detection** | auto-identifies 3 noise types: NOISE interference, abnormal records, inapplicable files | not offered by others |
| **3-D baseline justification** | compares encoding / time-window / granularity to auto-select the correct baseline | others rely on manual experience |
| **3-class log correlation** | compares net variance (not just presence of operations), precise 3-way classification | others do simple matching |
| **7 quality checks** | built-in enterprise rules prevent baseline/cost/criteria errors | not offered by others |

### 2.2 10-Step Workflow

```
Step 1:  Multi-format file loading (CSV/XLSX/TXT)
    ↓
Step 2:  Intelligent noise detection (NOISE/abnormal/noise files)
    ↓
Step 3:  3-D baseline selection justification
    ↓
Step 4:  Scan-log cleaning (NOISE filter + time-window extraction)
    ↓
Step 5:  Count result loading (recount quantities are authoritative)
    ↓
Step 6:  Variance amount computation (cost-price matching + missing-value estimation)
    ↓
Step 7:  3-class log correlation (full/partial/no correlation)
    ↓
Step 8:  Location status check (active/disabled/under repair)
    ↓
Step 9:  Category analysis (variance rate desc + anomaly identification)
    ↓
Step 10: Deliverable generation (Excel 4 sheets + MD report)
    ↓
Quality check: 7 must_check_points auto-validated
```

## 3. Technical Architecture

### 3.1 System Architecture

```
┌─────────────────────────────────────────────────────┐
│              User Interface (Gradio)                 │
│  [Analyze] [📊 Mgmt Report] [💬 Chat] [About]        │
├─────────────────────────────────────────────────────┤
│          Agent Core (10-Step Workflow)               │
│  ┌──────────┐ ┌──────────┐ ┌────────────────────┐  │
│  │ Workflow │ │ Memory   │ │ Quality Checker    │  │
│  │ (10 steps)│ │(cross-file)│ │ (7 checkpoints)    │  │
│  └──────────┘ └──────────┘ └────────────────────┘  │
├─────────────────────────────────────────────────────┤
│         Data Engine (multi-format load/struct)       │
│  ┌──────────┐ ┌──────────┐ ┌────────────────────┐  │
│  │ Loader   │ │ Struct.  │ │ Noise Detector     │  │
│  │ (CSV/    │ │ (DataFrame│ │ (NOISE/abnormal/   │  │
│  │  XLSX/   │ │  parse)  │ │  noise-file detect) │  │
│  │  TXT)    │ │          │ │                    │  │
│  └──────────┘ └──────────┘ └────────────────────┘  │
├─────────────────────────────────────────────────────┤
│         Tools (Excel/compute/report generation)      │
├─────────────────────────────────────────────────────┤
│      LLM Inference (vLLM/llama.cpp + ROCm)          │
│         AMD Radeon GPU Acceleration                  │
│         (management report generation layer)         │
└─────────────────────────────────────────────────────┘
```

### 3.2 Core Modules

| Module | File | Function |
|---|---|---|
| Agent Core | `src/agent.py` | 10-step workflow orchestration |
| Data Engine | `src/rag.py` | multi-format loading + DataFrame structuring |
| Noise Detector | `src/noise_detector.py` | intelligent noise identification |
| Tools | `src/tools.py` | Excel I/O, computation, report generation |
| Memory | `src/memory.py` | cross-file consistency memory |
| Quality Checker | `src/quality_checker.py` | 7 quality checks |
| Report Generator | `src/report_generator.py` | LLM management report (GPU layer) |
| UI | `src/ui.py` | Gradio web interface |

### 3.3 AI Agent Capability Mapping (Track 2 Requirements)

| Capability | Implementation | Description |
|---|---|---|
| **Multi-step Planning** | 10-step workflow | from data loading to deliverable generation, each step has explicit I/O and quality checks |
| **Tool Calling** | file I/O + Excel generation + LLM report | Agent calls multiple tools for read, compute, report |
| **Memory** | `ConsistencyMemory` | cross-file consistency, persisted history results, chat history |
| **Permission / Local Deploy** | fully local | data never leaves the device, zero cloud API dependency |
| **RAG / Grounding** | the 10 business files | every conclusion is grounded in uploaded data, never fabricated |

## 4. AMD GPU Adaptation & Optimization

### 4.1 Platform Overview

Built on AMD Radeon GPU + ROCm open-source stack for fully local AI Agent deployment.

Two compute paths:

1. **Deterministic data processing (CPU, 10-step workflow)**: pandas performs all cleaning, variance computation, log correlation, and quality checks. No GPU required.
2. **LLM management report generation (GPU layer)**: vLLM/llama.cpp runs a local LLM on the AMD GPU for management summary, risk grading, and action recommendations.

| Component | Choice | Description |
|---|---|---|
| GPU hardware | AMD Radeon RX 7900 XTX | 24GB VRAM, FP16/BF16 |
| Inference engine | vLLM 0.6+ / llama.cpp | high-performance LLM inference |
| Deep learning | PyTorch 2.4+ ROCm | native AMD GPU support |
| Default model | meta-llama/Llama-3.1-8B-Instruct | 8B params, ~16GB FP16 VRAM |

### 4.2 ROCm Compatibility Implementation

#### 4.2.1 LLM Inference (GPU layer)

```python
# src/report_generator.py — LLM connection (OpenAI-compatible endpoint)
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(
    model="meta-llama/Llama-3.1-8B-Instruct",
    base_url="http://localhost:8000/v1",  # vLLM service address
    api_key="not-needed",                  # local: no API key needed
    temperature=0.3,
    max_tokens=2048,
    streaming=True,
)
```

Key config:
- `base_url` points to the local vLLM/llama.cpp service
- `api_key="not-needed"`: local deployment needs no authentication
- `temperature=0.3`: management reports require stable output

#### 4.2.2 vLLM Launch Example

```bash
# Start vLLM service (AMD ROCm)
vllm serve meta-llama/Llama-3.1-8B-Instruct \
    --host 0.0.0.0 --port 8000 \
    --dtype float16

# Or use llama.cpp
llama-server -m models/llama-3.1-8b-instruct.gguf \
    --host 0.0.0.0 --port 8000
```

### 4.3 Performance Optimization Strategy

#### 4.3.1 LLM Inference Optimization

| Technique | Description | Effect |
|---|---|---|
| **FP16 mixed precision** | float16 inference | ~50% VRAM reduction |
| **Continuous batching** | vLLM dynamic batching | 2-4x throughput |
| **PagedAttention** | vLLM memory management | larger batch support |
| **Quantized inference** | INT4/INT8 support | further VRAM reduction |

#### 4.3.2 Data Processing Optimization

| Technique | Description | Effect |
|---|---|---|
| **Batch file loading** | load multiple files at once | less I/O overhead |
| **Incremental workflow** | cache intermediate results | avoids recomputation |
| **DataFrame structuring** | auto-parse by column name/content | no predefined schema |

### 4.4 Deployment Architecture

```
┌─────────────────────────────────────────────────┐
│              AMD Radeon GPU (24GB VRAM)          │
│  ┌─────────────┐                                 │
│  │ vLLM Engine │                                 │
│  │ (LLM infer) │                                 │
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

### 4.5 Performance Baseline

#### 4.5.1 10-Step Workflow (CPU, Pandas)

Validated on real brand data:

| Step | Time (reference) | Description |
|---|---|---|
| Step 1-2: load + noise detection | ~2s | multi-file read + NOISE detection |
| Step 3: baseline selection | <1s | 3-D comparison |
| Step 4: log cleaning | ~1s | NOISE filter + time window |
| Step 5-6: variance computation | ~1s | count result + amount matching |
| Step 7: log correlation | ~1s | 3-class comparison |
| Step 8-9: check + analysis | <1s | location + category |
| Step 10: deliverables | ~1s | Excel + MD generation |
| **Total** | **~8s** | deterministic, reproducible |

#### 4.5.2 LLM Management Report Generation (GPU layer)

| Metric | AMD RX 7900 XTX (FP16) | Description |
|---|---|---|
| Model | Llama-3.1-8B-Instruct | 8B params |
| Time to first token | ~300ms (expected) | vLLM service |
| Output tokens | ~800-1200 | management report length |
| Generation time | ~10-15s (expected) | streaming output |

> Note: GPU numbers must be validated on the real AMD GPU + ROCm environment; supplement with `rocm-smi` screenshots and `tokens/sec` metrics (see `docs/gpu_demo_runbook.md`).

### 4.6 Why AMD ROCm

| Dimension | AMD ROCm | NVIDIA CUDA |
|---|---|---|
| Open source | ✅ fully open | ❌ closed |
| Cost | ✅ lower hardware cost | ❌ high-end GPUs expensive |
| Enterprise deployment | ✅ no vendor lock-in | ⚠️ NVIDIA-dependent |
| Ecosystem maturity | ⚠️ growing fast | ✅ mature |
| LLM support | ✅ vLLM native | ✅ vLLM native |

For private enterprise deployment, AMD ROCm's openness and cost advantage are decisive.

## 5. Testing & Validation

### 5.1 Ground Truth Validation

Tested against real supply-chain count data; every metric matches manual analysis:

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
| Bathroom furniture anomaly | 16.0% | 16.0% | ✅ |
| Quality checks | 7/7 passed | all passed | ✅ |

### 5.2 Business Value

| Metric | Manual Analysis | Agent | Improvement |
|---|---|---|---|
| Analysis time | 2-3 days | ~8s (pure compute) | **99%+** |
| Accuracy | experience-dependent | identical to ground truth | — |
| Auditability | none | 7 quality checks + full trace | — |
| Deployment | N/A | local GPU, data on-device | — |

## 6. Use Cases

| Scenario | Description |
|---|---|
| Enterprise inventory count | monthly/quarterly cycle-count variance analysis |
| Warehouse adjustment | preparation of adjustment materials before management meetings |
| Audit support | traceable variance-analysis evidence |
| Inventory optimization | strategy improvements based on variance data |

## 7. Roadmap

- Support more formats (PDF scans, database direct connection)
- Add visual charts (variance distribution, trend analysis)
- Multi-warehouse comparison
- ERP integration for automatic data collection
- Enhanced LLM capabilities: multi-turn follow-up and deep interpretation based on analysis results

## 8. Team

| Role | Name | Responsibility |
|---|---|---|
| Developer | — | use-case definition, product design, Agent development, data processing, system integration |

## 9. Contact

- Email: developer@example.com
