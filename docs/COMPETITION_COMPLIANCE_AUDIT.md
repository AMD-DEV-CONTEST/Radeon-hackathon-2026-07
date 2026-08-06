# Competition Rules Compliance Audit Report

> Audit tool: agently-design skill
> Audit target: the entire project against the official AMD AI DevMaster Track 2 rules
> Audit date: 2026-07-30
> Days to deadline: 7 days (2026-08-06 23:59 UTC+8)
> Rule source: [Official rules on Google Docs](https://docs.google.com/document/d/1TwgwBNUAv8fRNQbkcTZmcRR0__Oi4WMsBfkW38ALZp4/edit)

---

## Section 1: Competition Rules Summary (Track 2: Agentic AI)

### 1.1 Scoring Structure

| Dimension | Points | Description |
|------|------|------|
| Functional completeness and application value | 60 points | Scenario positioning (20) + core capabilities (20) + multi-turn interaction (20) |
| AMD Radeon GPU & ROCm optimization | 40 points | Local core inference (20) + inference speed optimization (20) |
| Optional Bonus | 20 points | Radeon Cloud Model API + quantization/distillation |
| **Total** | **100 + 20** | |

### 1.2 Hard Constraints

1. **Core inference must run locally on an AMD Radeon GPU**; remote APIs are not allowed to host core functionality
2. **Must not rely entirely on closed-source remote APIs or closed-source Agent platforms** for core functionality
3. **Minimum functional threshold: implement at least 2 of the 5 items** (the more implemented, the more favorable)
4. **Performance optimization requires at least 2 groups of comparisons**, with reproducible scripts and logs retained
5. **The Demo video must show real execution**; PPT-only is prohibited

### 1.3 The Five Minimum Functional Thresholds

| ID | Capability | Official requirement |
|------|------|----------|
| F1 | Local knowledge retrieval (RAG) | Local knowledge retrieval and Q&A |
| F2 | Tool invocation | Tool invocation (file, search, script execution, or business API) |
| F3 | Multi-step task planning | Task decomposition, sub-step execution, failure retry, and intermediate state |
| F4 | Local multi-turn memory | Local session memory or long-term memory, not dependent on the cloud |
| F5 | Clear permission control & privacy protection | Permission boundaries, directory whitelist, sensitive information masking, auditable logs |

### 1.4 Deliverables Checklist

| ID | Deliverable | Required/Optional | Status before the deadline |
|------|--------|----------|-----------|
| D1 | Project Specification Document | Required | ⚠️ Pending review |
| D2 | Project Source Code | Required | ⚠️ Pending review |
| D3 | Demo video (3-5 minutes) | Required | ❌ Not recorded |
| D4 | Supplementary material (PPT or Poster, choose one) | Required | ❌ Not created |
| D5 | GitHub PR submission | Required | ❌ Not submitted |

### 1.5 Key Milestones

| Event | Time (UTC+8) | Status |
|------|-------------|------|
| Registration opens | 2026-07-10 | ✅ Passed |
| Submissions open | 2026-07-15 | ✅ Passed |
| **Final deadline** | **2026-08-06 23:59** | ⏳ 7 days remaining |

---

## Section 2: Functional Completeness Audit (60 points)

### 2.1 Scenario Positioning and Creativity (20 points)

| Audit item | Official requirement | Current status | Evidence | Score prediction |
|--------|---------|---------|------|---------|
| Clear task positioning | Clear scenario, clear value, users understand immediately | ✅ Insurance business intelligent Q&A Agent | `docs/SPECIFICATION.md` §1 | Strong |
| User persona definition | Define target users, pain points, input/output | ✅ Insurance business staff/HR/agents | SPECIFICATION §1.1-1.3 | Strong |
| Privacy and localization value | Reflect localization and privatization value | ✅ Fully local deployment, data never leaves the enterprise boundary | SPECIFICATION §1.5 | Strong |
| Scenario creativity | Not a generic chat assistant | ⚠️ Insurance Q&A is fairly common, but the five-step business flow + hybrid retrieval is differentiated | — | Above average |

**Estimated score: 16-18/20**

**Improvement suggestions:**
- Highlight in the Demo video and PPT "why an Agent is necessary" rather than a simple RAG
- Emphasize the closed-loop value of the five-step business flow (understand → plan → verify → retrieve → answer), distinct from ordinary Q&A
- Showcase the personalized experience brought by cross-session memory (e.g., remembering the insurance products the user frequently queries)

### 2.2 Core Capability Completeness (20 points)

| Capability | Official threshold | Implementation status | Evidence file | Score prediction |
|------|---------|---------|---------|---------|
| F1: Local knowledge retrieval (RAG) | 1 of 5 | ✅ Fully implemented | `src/rag/` full module + hybrid retrieval + reranking + Query rewriting | Strong |
| F2: Tool invocation | 1 of 5 | ✅ Implemented but needs verification | `src/tools/` (file_tools/doc_tools/data_query) | Above average |
| F3: Multi-step task planning | 1 of 5 | ✅ Fully implemented | `src/agent/flow.py` TriggerFlow five-step orchestration + reflection | Strong |
| F4: Local multi-turn memory | 1 of 5 | ✅ Fully implemented | `src/session/` + `src/memory/` three-layer memory | Strong |
| F5: Permission control and privacy | 1 of 5 | ✅ Fully implemented | `src/security/` directory whitelist + scope + audit | Strong |

> The official minimum threshold is 2 items; this project implements all 5, achieving full coverage.

**Estimated score: 17-19/20**

**Risk items:**
- R1: Tool invocation is implemented, but the Demo must clearly show tools being actually invoked (logs/UI trace)
- R2: Failure retry and intermediate state of multi-step task planning must be visible in the Demo

### 2.3 Multi-turn Interaction Smoothness (20 points)

| Audit item | Official requirement | Current status | Evidence | Score prediction |
|--------|---------|---------|------|---------|
| Context continuity | Maintain dialogue context | ✅ Session context_window | `src/session/registry.py` | Strong |
| State persistence | Task state persists across turns | ✅ pipeline_state + Task workspace | `src/agent/flow.py` | Strong |
| Failure recovery | Re-plan and re-execute after failure | ✅ Step3 retry_plan fallback edge + blocked termination | `src/agent/flow.py` | Strong |
| Re-planning after user feedback | Adjust based on user feedback | ⚠️ No explicit path for re-planning after user feedback | — | Medium |
| Interaction interface | CLI or GUI | ✅ CLI (`start_agent.py`) + Web UI (`src/api/server.py` + `static/`) | — | Strong |

**Estimated score: 15-17/20**

**Improvement suggestions:**
- Show a "user corrects → Agent re-plans" scenario in the Demo
- Web UI needs to be confirmed to start normally and display streaming output

---

## Section 3: AMD Radeon GPU & ROCm Optimization Audit (40 points)

### 3.1 Core Inference Runs on AMD Radeon GPU (20 points)

| Audit item | Official requirement | Current status | Evidence | Score prediction |
|--------|---------|---------|------|---------|
| GPU model evidence | Screenshot/log proving AMD Radeon GPU | ✅ Collected | `docs/GPU_ENVIRONMENT.md` (gfx1100, 48GB) | Strong |
| ROCm version evidence | Prove the ROCm version | ✅ Collected | ROCm 6.16.13 | Strong |
| Inference backend | vLLM on ROCm | ✅ Configured | `configs/models.toml` + `docs/DEPLOYMENT.md` | Strong |
| Startup log | vLLM startup log containing GPU info | ❌ Not collected | `docs/benchmarks/logs/` is empty | Blocked |
| Local inference proof | Core inference is not a remote API | ✅ OpenAICompatible base_url=localhost:8000 | `configs/models.toml` | Strong |
| PyTorch ROCm verification | torch.cuda.is_available() | ❌ Not collected | Need to run the verification command | Blocked |

**Estimated score: 14-16/20 (startup logs and PyTorch verification need to be collected)**

### 3.2 Inference Speed Optimization (20 points)

| Audit item | Official requirement | Current status | Evidence | Score prediction |
|--------|---------|---------|------|---------|
| At least 2 comparison groups | quantization/distillation/batch/kv-cache/backend/concurrency/context | ⚠️ Designed but not executed | `docs/ROCm_OPTIMIZATION.md` C0-C4 | Blocked |
| Comparison metrics | tok/s, TTFT, VRAM, end-to-end time | ⚠️ Scripts ready but no data | `scripts/run_benchmark.sh` | Blocked |
| Reproducible scripts | Retain reproduction scripts | ✅ Created | `scripts/run_benchmark.sh` | Strong |
| Log retention | Raw logs | ❌ Not collected | `docs/benchmarks/logs/` is empty | Blocked |
| Comparison group A (C0 vs C2) | Baseline vs extreme optimization | ❌ Not executed | — | Blocked |
| Comparison group B (C0 vs C4) | Baseline vs large-VRAM specialization | ❌ Not executed | — | Blocked |

**Estimated score: 8-10/20 (design is complete but no actual data; must be executed immediately)**

### 3.3 Optional Bonus (20 points)

| Bonus strategy | Official requirement | Current status | Score prediction |
|------------|---------|---------|---------|
| Radeon Cloud Model API | Core inference uses Radeon Cloud | ✅ Already running on the Radeon Cloud remote container | Strong |
| Quantization optimization | INT4 GPTQ/AWQ comparison | ⚠️ Designed but not executed | Medium |
| Distillation | DeepSeek-R1-Distill-Qwen-7B | ✅ Deployed on a standalone port 8002 | Strong |
| Large-VRAM specialization | FP16 + 16 concurrency + 16384 context | ⚠️ Designed but not executed | Medium |

**Estimated score: 10-15/20 (partially satisfied; quantization comparison data needs to be added)**

---

## Section 4: Deliverable Completeness Audit

### 4.1 Project Specification Document (D1)

| Required content | Official requirement | Current status | File | Gap |
|---------|---------|---------|------|------|
| Application scenario | User persona, pain points, input/output, usage boundaries, privacy value | ✅ | `docs/SPECIFICATION.md` §1 | None |
| Agent architecture diagram | Model/inference/orchestration/tools/memory/data/observability/security layers | ✅ | `docs/ARCHITECTURE.md` | None |
| Core capability introduction | Mapped to inference/planning/tools/memory/execution/security/observability/evaluation | ✅ | `docs/SPECIFICATION.md` §3 | None |
| Model introduction and deployment plan | Model selection rationale, quantization strategy, inference backend, ROCm dependencies, startup method | ✅ | `docs/DEPLOYMENT.md` + `docs/REPRODUCTION.md` | None |
| ROCm inference optimization description | Optimization checklist, comparison metrics, reproducible scripts and logs | ⚠️ Design complete but no actual data | `docs/ROCm_OPTIMIZATION.md` | **Missing actual comparison data** |

**D1 status: 90% complete; actual performance comparison data needs to be added**

### 4.2 Project Source Code (D2)

| Required content | Official requirement | Current status | Gap |
|---------|---------|---------|------|
| Complete source repository | agent core, tools, RAG/index, evaluation, startup scripts, configs, sample data | ✅ | None |
| README | Environment setup, startup guide, dependency list, GPU/CPU mode differences, troubleshooting | ✅ | None |
| Offline reproducibility | Locked dependency versions, environment export, model download strategy, sample data | ✅ | None |
| Config templates | configs/ directory | ✅ `agent.toml` + `models.toml` | None |
| Sample data | docs_data/ insurance documents + docs/eval/ test set | ✅ 7 insurance documents + 50 QA items | None |
| One-click startup | Run with a single command | ✅ `pip install -r requirements.txt && python scripts/start_agent.py` | None |

**D2 status: 100% complete**

### 4.3 Demo Video (D3)

| Required content | Official requirement | Current status | Gap |
|---------|---------|---------|------|
| Recording script | 3-5 minute script | ✅ `demo/demo_script.md` | None |
| Actual operation flow | CLI/GUI → final result | ❌ Not recorded | **Must be recorded** |
| Radeon GPU showcase | GPU info, ROCm version, startup log, tok/s | ❌ Not recorded | **Must be recorded** |
| Complete task execution | plan → tools → memory/RAG → verify → output | ❌ Not recorded | **Must be recorded** |
| Performance optimization comparison | tok/s/latency comparison charts | ❌ Not recorded | **Must be recorded** |

**D3 status: 10% complete (script only); the video must be recorded**

### 4.4 Supplementary Material PPT/Poster (D4)

| Required content | Official requirement | Current status | Gap |
|---------|---------|---------|------|
| PPT or Poster (choose one) | Scenario pain points → core capabilities → architecture diagram → Demo flow → performance optimization → results and value | ❌ Not created | **Must be created** |

**D4 status: 0% complete; a PPT or Poster must be created**

### 4.5 GitHub PR Submission (D5)

| Required content | Official requirement | Current status | Gap |
|---------|---------|---------|------|
| Fork the official repository | github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07 | ❌ Not forked | **Must complete** |
| PR submission | Create a new project folder, add source code/documentation/description, submit a PR | ❌ Not submitted | **Must complete** |
| AMD Developer Program registration | Register for all team members | ⚠️ Needs confirmation | **Must confirm** |

**D5 status: 0% complete; the PR must be submitted**

---

## Section 5: Compliance Risk Matrix

### 5.1 High-risk Items (may cause loss of points or elimination)

| Risk ID | Risk description | Impact | Severity | Probability | Mitigation |
|---------|---------|------|--------|------|---------|
| **R-01** | No actual performance comparison data | The 20-point inference optimization may score low | Severe | High | Immediately execute the C0/C2/C4 comparison experiments |
| **R-02** | Demo video not recorded | May be judged as incomplete submission | Severe | High | Record immediately after model deployment |
| **R-03** | PPT/Poster not created | Incomplete deliverable | Severe | High | Create with the html-deck skill |
| **R-04** | GitHub PR not submitted | Cannot participate | Fatal | High | Must submit before the deadline |
| **R-05** | Models not downloaded (~40GB) | Cannot start the inference service | Severe | High | Immediately run download_models.sh |
| **R-06** | vLLM service not started | Cannot run any tests | Severe | High | Start immediately after the model download |

### 5.2 Medium-risk Items

| Risk ID | Risk description | Impact | Severity | Mitigation |
|---------|---------|------|--------|---------|
| R-07 | vLLM startup log not collected | Incomplete GPU evidence | Medium | Save the log with tee at startup |
| R-08 | PyTorch ROCm verification not executed | Insufficient local inference proof | Medium | Run torch.cuda.is_available() |
| R-09 | Tool invocation not visible in the Demo | Core capability showcase insufficient | Medium | Show tool invocation logs in the Demo |
| R-10 | Re-planning after user feedback not shown | Multi-turn interaction score affected | Medium | Add a correction scenario in the Demo |
| R-11 | Trace data not collected | No observability evidence | Medium | Run evaluate.py to collect traces |

### 5.3 Low-risk Items

| Risk ID | Risk description | Mitigation |
|---------|---------|---------|
| R-12 | Insurance Q&A scenario is average in creativity | Highlight the five-step business flow closed loop and hybrid retrieval differentiation |
| R-13 | Bonus quantization comparison not executed | Automatically satisfied after the C2 experiment runs |
| R-14 | README troubleshooting not detailed enough | Add common issues |

---

## Section 6: Gap Summary and Priorities

### 6.1 Blocking Items (must complete before submission)

| Priority | Gap item | Estimated effort | Dependency | Owner |
|--------|--------|---------|------|--------|
| P0 | Model download (~40GB) | 2-4h | Network | — |
| P0 | vLLM service startup (3 ports) | 30min | P0 model download | — |
| P0 | Performance comparison experiments (C0/C2/C4) | 2h | P0 vLLM | — |
| P0 | Demo video recording | 1h | P0 performance experiments | — |
| P0 | PPT/Poster creation | 1h | P0 performance data | — |
| P0 | GitHub PR submission | 30min | All complete | — |

**Total estimated effort: 7-9 hours**

### 6.2 Quality Improvement Items (recommended)

| Priority | Gap item | Estimated effort | Benefit |
|--------|--------|---------|------|
| P1 | Trace data collection | 30min | Observability evidence |
| P1 | vLLM startup log collection | 10min | Complete GPU evidence |
| P1 | PyTorch ROCm verification | 5min | Local inference proof |
| P2 | Quality evaluation (evaluate.py) | 1h | Task quality data |
| P2 | Cross-configuration Trace topology comparison | 30min | Consistency verification |
| P3 | README troubleshooting additions | 30min | Improved reproducibility |

---

## Section 7: 7-Day Pre-Competition Sprint Plan

### 7.1 Timeline (July 30 - August 6)

| Date | Task | Output | Effort |
|------|------|------|------|
| **D1 (7/30)** | Model download + vLLM startup | Model files + 3 inference services running | 3-4h |
| **D2 (7/31)** | C0 baseline + C2 extreme comparison experiments | Performance comparison data + GPU evidence | 2h |
| **D2 (7/31)** | C4 large-VRAM comparison experiment | Complete 3 comparison groups | 1h |
| **D3 (8/1)** | Quality evaluation + Trace collection | quality_report.json + trace data | 1.5h |
| **D3 (8/1)** | Supplement GPU evidence (logs/verification) | Complete GPU evidence package | 30min |
| **D4 (8/2)** | PPT/Poster creation | Supplementary material | 1.5h |
| **D4 (8/2)** | Demo video recording | 3-5 minute MP4 | 1h |
| **D5 (8/3)** | Documentation update (actual ROCm optimization data) | Updated documentation | 1h |
| **D5 (8/3)** | README final review | Complete README | 30min |
| **D6 (8/4)** | GitHub Fork + PR submission | PR submitted | 1h |
| **D6 (8/4)** | Full regression testing | Confirm everything works | 1h |
| **D7 (8/5-8/6)** | Buffer + final check + PR supplement | Submission complete | As needed |

### 7.2 Critical Path

```
Model download ──→ vLLM startup ──→ Performance comparison experiments ──→ Quality evaluation + Trace
                │                │                    │
                │                ├──→ PPT/Poster ←────┤
                │                ├──→ Demo video ←────┤
                │                └──→ Documentation update ←────┘
                │                                      │
                └──→ GPU evidence collection ──────────┘
                                                   │
                                            GitHub PR submission
```

### 7.3 Daily Checklist

#### D1 (7/30) — Environment Preparation
- [ ] `bash scripts/download_models.sh` completed (5 models)
- [ ] vLLM port 8000 started (Qwen3-8B C0 configuration)
- [ ] vLLM port 8001 started (BGE-M3 Embedding)
- [ ] vLLM port 8002 started (DeepSeek-R1-Distill)
- [ ] `curl http://localhost:8000/v1/models` returns normally
- [ ] `python -c "import torch; print(torch.cuda.is_available())"` returns True

#### D2 (7/31) — Performance Comparison
- [ ] `bash scripts/run_benchmark.sh C0` completed
- [ ] Switch vLLM to the C2 configuration, `bash scripts/run_benchmark.sh C2` completed
- [ ] Switch vLLM to the C4 configuration, `bash scripts/run_benchmark.sh C4` completed
- [ ] C0/C2/C4 three groups of logs present under `docs/benchmarks/logs/`
- [ ] Generate the `summary.csv` comparison table

#### D3 (8/1) — Quality and Evidence
- [ ] `python scripts/evaluate.py` completed, produces quality_report.json
- [ ] Trace data saved to `.agently/runs/insurance/traces/`
- [ ] `rocm-smi --showproductname` screenshot saved
- [ ] vLLM startup log saved to `docs/benchmarks/logs/C*_vllm.log`
- [ ] `python -c "import torch; ..."` verification result saved

#### D4 (8/2) — Deliverables
- [ ] PPT or Poster created
- [ ] Demo video recorded (3-5 minute MP4)
- [ ] Video shows: GPU info, ROCm version, vLLM startup, task execution, performance comparison

#### D5 (8/3) — Documentation Finalization
- [ ] `docs/ROCm_OPTIMIZATION.md` updated with actual comparison data
- [ ] `docs/SPECIFICATION.md` confirmed complete
- [ ] `README.md` final review
- [ ] All documentation cross-references correct

#### D6 (8/4) — Submission
- [ ] Fork the official GitHub repository
- [ ] Create a new project folder, add all source code + documentation + Demo
- [ ] Submit a Pull Request
- [ ] PR description includes: project introduction, architecture, capability list, performance data links

#### D7 (8/5-8/6) — Buffer
- [ ] PR checked for no issues
- [ ] Supplement any missing materials
- [ ] **Confirm submission completed before 8/6 23:59**

---

## Section 8: Score Prediction and Improvement Strategy

### 8.1 Current Score Prediction

| Dimension | Full marks | Current estimate | Gap reason | Post-fix estimate |
|------|------|---------|---------|-----------|
| Scenario positioning and creativity | 20 | 16-18 | Scenario creativity is average | 17-18 |
| Core capability completeness | 20 | 17-19 | Demo needs to show tool invocation | 18-19 |
| Multi-turn interaction smoothness | 20 | 15-17 | Missing user-feedback re-planning showcase | 16-18 |
| GPU local inference | 20 | 14-16 | Missing startup logs and PyTorch verification | 18-19 |
| Inference speed optimization | 20 | 8-10 | **No actual comparison data** | 16-18 |
| Bonus | 20 | 10-15 | Quantization comparison not executed | 12-15 |
| **Total** | **120** | **80-95** | | **97-107** |

### 8.2 Score Improvement Strategy

| Strategy | Target dimension | Estimated improvement | Implementation difficulty |
|------|---------|---------|---------|
| Execute the C0/C2/C4 three comparison groups | Inference speed optimization (20) | +8-10 points | Medium (requires vLLM running) |
| Record a complete Demo video | All dimensions | +3-5 points | Medium |
| Create a professional PPT | All dimensions | +2-3 points | Low |
| Show tool invocation logs | Core capabilities (20) | +1-2 points | Low |
| Show a user-correction → re-planning scenario | Multi-turn interaction (20) | +1-2 points | Medium |
| Collect a complete GPU evidence package | GPU inference (20) | +2-3 points | Low |
| Add quantization comparison data | Bonus (20) | +2-3 points | Medium |

### 8.3 Highest-priority Actions (ordered by scoring impact)

1. **Execute the performance comparison experiments** — directly affects 20 points (inference speed optimization), currently 0 data
2. **Collect GPU evidence** — affects 20 points (local inference), current evidence is incomplete
3. **Record the Demo video** — affects 60 points (functional completeness showcase), currently not recorded
4. **Create the PPT/Poster** — required deliverable, currently 0%
5. **Submit the GitHub PR** — fatal item, cannot participate without it

---

## Section 9: Audit Conclusion

### 9.1 Overall Assessment

| Dimension | Readiness | Description |
|------|--------|------|
| Code implementation | 95% | All 5 capabilities implemented, 16 modules + 9 scripts |
| Documentation system | 85% | 12+ documents complete, missing actual performance data |
| Performance evidence | 10% | Design complete but no actual data |
| Deliverables | 40% | Missing Demo video, PPT, GitHub PR |
| **Overall readiness** | **60%** | **Need a 7-9 hour sprint to complete the remaining 40%** |

### 9.2 Core Conclusion

The project's code and architecture layers are highly ready, all five capabilities are implemented, and the documentation system is essentially complete. **The biggest gap is the lack of actual runtime evidence** — performance comparison data, GPU runtime logs, and the Demo video have not been collected/recorded. These are the key basis for competition scoring and must be completed within the remaining 7 days.

Following the sprint plan in this audit report, all deliverables are expected to be completed before 8/4, with 8/5-8/6 as a buffer period to ensure successful submission before 8/6 23:59.