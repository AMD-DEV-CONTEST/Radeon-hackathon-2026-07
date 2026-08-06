# Demo Recording Script

> Official requirement: 3-5 minute demo video, must show real running and AMD Radeon GPU inference

---

## Before Recording

### Environment Check Checklist

```bash
# 1. Confirm GPU and ROCm
rocm-smi --showproductname
rocminfo --version

# 2. Confirm vLLM service is running
curl http://localhost:8000/v1/models

# 3. Confirm Embedding service is running
curl http://localhost:8001/v1/models

# 4. Confirm the index has been built
ls .agently/runs/insurance/index/faiss.index

# 5. Test that the Agent can start
python scripts/start_agent.py
# Type "quit" to exit, confirm no errors
```

### Recording Tools

- OBS Studio / ScreenStudio (recommended)
- Resolution: 1920x1080
- Frame rate: 30fps
- Format: MP4

---

## Recording Script (4 minutes)

### Part 1: Scenario and Value (0:00 - 0:30)

**Visual**: Show the project introduction section of README or SPECIFICATION.md

**Narration/Captions**:

> Insurance RAG Agent — a private AI Agent built for the insurance business
> 
> Pain points: complex insurance clauses, difficult cross-document correlation, long customer wait times, and forgetting across conversations
> 
> Solution: built on the Agently framework, fully deployed locally on AMD Radeon GPU + ROCm, closing the loop across five core capabilities

### Part 2: Architecture and Core Capabilities (0:30 - 1:30)

**Visual**: Show the Mermaid architecture diagram in `docs/ARCHITECTURE.md`

**Narration/Captions**:

> The system architecture is divided into seven layers:
> - Inference layer: vLLM on ROCm, Qwen3-8B
> - Vector index layer: FAISS ANN retrieval
> - Orchestration layer: TriggerFlow five-step business flow
> - Tool layer: file read/write, document analysis, business data query
> - Memory layer: Session short-term + Task + Namespace long-term
> - Security layer: directory whitelist + scope filtering + audit logs
> - Observability layer: performance benchmarks + task quality evaluation
>
> Of the official 5 capability gates, we implement all 5.

### Part 3: Hands-on Demonstration (1:30 - 3:30) — must show Radeon

**Visual 1: GPU evidence (1:30 - 1:45)**

```bash
# Enter in terminal
rocm-smi --showproductname
rocminfo --version
```

**Visual 2: vLLM startup logs (1:45 - 2:00)**

```bash
# Show the running vLLM logs (in the already-started terminal)
# Key info: model loaded, ROCm detected, GPU memory
```

**Visual 3: Agent interaction (2:00 - 3:30)**

```bash
python scripts/start_agent.py
```

Enter the following queries (use the samples in `demo/sample_queries.json`):

**Query 1: RAG knowledge retrieval**

```
> What is the coverage scope of Employer Liability Insurance?
```

**Expected demonstration**:
- Step1-5 execution process logs
- FAISS top-K retrieval results
- Answer with source annotations

**Query 2: Multi-turn memory**

```
> What about the claims process? (carrying over the previous context)
```

**Expected demonstration**:
- Session context_window carries the previous context
- Understands that "that" refers to "Employer Liability Insurance"

**Query 3: Tool invocation**

```
> List all the uploaded insurance documents
```

**Expected demonstration**:
- Tool call file_tools.list_files
- Returns the document list

**Query 4: Cross-session memory**

```
> quit
# Restart the Agent
python scripts/start_agent.py
> Which insurance did I ask about last time?
```

**Expected demonstration**:
- Namespace long-term memory recall
- Answers "You asked about Employer Liability Insurance last time"

### Part 4: Performance Optimization Comparison (3:30 - 4:00)

**Visual 1: Show benchmark results**

```bash
# Show docs/benchmarks/summary.csv or terminal output
cat docs/benchmarks/summary.csv
```

**Visual 2: GPU utilization monitoring**

```bash
# Run in another terminal
rocm-smi --showuse
```

**Narration/Captions**:

> Performance optimization comparison:
> - C0 baseline (FP16): 18.3 tok/s, 15.2GB VRAM
> - C2 extreme (INT4): 58.7 tok/s, 6.5GB VRAM
> - Throughput up 3.2x, VRAM down 57%
>
> Optimization methods: GPTQ INT4 quantization + PagedAttention + concurrency 8 + short context
> Reproduction script: bash scripts/run_benchmark.sh C0 / C2

---

## Post-Recording Checklist

| Check item | Passing criteria |
|--------|----------|
| Video length | 3-5 minutes |
| GPU on screen | rocm-smi output visible |
| Real running | Complete Agent interaction process |
| Five-step flow | Step1-5 logs visible |
| Source annotations | Answer includes ref sources |
| Performance data | At least two sets of comparison data |
| Multi-turn interaction | Shows continuous context |
| Cross-session memory | Shows Namespace recall |

---

## Supplementary Materials (PPT / Poster Suggested Structure)

If you need to make a PPT or Poster, here is a suggested structure:

1. **Scenario pain points** (1 page): insurance business pain points + local deployment value
2. **Core capabilities** (1 page): five-capability mapping table
3. **Architecture diagram** (1 page): the system architecture diagram in ARCHITECTURE.md
4. **Demo flow** (1 page): five-step business flow + screenshots
5. **Performance optimization** (1 page): C0 vs C2 comparison table + charts
6. **Results and value** (1 page): efficiency improvement data + privacy protection value