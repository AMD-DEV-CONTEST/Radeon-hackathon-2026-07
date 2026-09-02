# OpenAlpha Sentinel - AMD Radeon / ROCm Benchmark Report

| Field | Value |
|---|---|
| Team | Coreline Systems Limited |
| Report date | `2026-07-17` |
| Benchmark version | Application evidence commit `8f9aad7a206287b2158f0fccb7a70c4a7373aa87`; clean offload-validation commit `25129cdd853a4fe5a258386350d933339b381028` |
| Status | `ROCm llama-bench snapshot and 37/37 layer offload verified; comparative optimization pending; optional 24-hour soak not run` |

> Truthfulness gate: the saved July 17 evidence verifies the model hash, a ROCm `llama-bench` run configured with `-ngl 99`, actual `37/37` layer assignment on `ROCm0`, 35 Radeon-host tests, separate real CLI and loopback HTTP `200` application requests, and one controlled restart/persistence trace. It does not record structured LLM extraction, a comparable CPU/Radeon improvement, TTFT percentiles, labeled quality-set results, active peak VRAM, or a 24-hour soak; do not infer those results from this evidence.

## 1. Objective

This report measures whether OpenAlpha Sentinel's core local AI path runs on an AMD Radeon GPU through ROCm and whether targeted optimizations improve the fixed end-to-end strategy-document pipeline without an unacceptable quality loss.

The primary optimization metric is cold-cache documents processed per minute on a fixed 100-document performance set. Interactive inference is reported separately through time to first token (TTFT), decode throughput, and complete-answer latency.

## 2. Current Verification Status

| Item | Status | Evidence |
|---|---|---|
| ROCm environment available | Verified | ROCm 7.2.1 image |
| `llama.cpp` ROCm/HIP build | Verified | Commit `1b99711a5f2582ec99686eb7958844749c223cf5` |
| Radeon device detection | Verified | `gfx1100`, approximately `49,136 MiB` reported VRAM |
| Clean runtime code | Verified | Commit `8f9aad7a206287b2158f0fccb7a70c4a7373aa87` in each final evidence manifest |
| Clean offload validation | Verified | Commit `25129cdd853a4fe5a258386350d933339b381028`; `generated/rocm-offload-validation-20260717T152430Z.txt` |
| Model artifact present and hash checked | Verified | `generated/rocm-benchmark-20260717T051324Z.txt` |
| Radeon-host automated tests | Verified | 35 passed on Python 3.12.3; text and JUnit artifacts saved |
| CLI application request | Verified | `generated/rocm-cli-rag-20260717T050851Z.txt`; `backend=llama.cpp-rocm`, commit-pinned citation lines `8-28` |
| Loopback HTTP application request | Verified | `generated/rocm-http-rag-20260717T050918Z.txt`; HTTP `200`, `backend=llama.cpp-rocm`, commit-pinned citation lines `8-28` |
| ROCm GPU-layer assignment | Verified | Independent verbose load reports `offloaded 37/37 layers to GPU` on `ROCm0` |
| Structured extraction | Not separately validated | No structured-extraction artifact in the current evidence set |
| Controlled restart/persistence | Verified | All three PIDs changed; health, repeat seed, protected counts, notifications, integrity, and foreign keys checked |
| CPU/Radeon comparison | Not run | No result directory was produced |
| Optimization comparison | Not run | No result directory was produced |
| Optional 24-hour soak | Not run (optional) | No soak report was produced |

## 3. Hardware and Software Configuration

### 3.1 Radeon Host

| Item | Value |
|---|---|
| Cloud/provider | Radeon Cloud |
| Image | AMD OneClick Base / ROCm 7.2.1 / Python 3.12.3 |
| OS | Ubuntu 24.04.4 LTS |
| GPU commercial model | Not available; the platform did not expose a reliable model name |
| GPU architecture | `gfx1100` |
| Reported VRAM | approximately 48 GiB / `49,136 MiB` |
| HIP | `7.2.53211` |
| System RAM | 503 GiB |
| `llama.cpp` repository | `https://github.com/ROCm/llama.cpp` |
| `llama.cpp` commit | `1b99711a5f2582ec99686eb7958844749c223cf5` |
| Build flags | `GGML_HIP=ON`, `AMDGPU_TARGETS=gfx1100`, Release, curl disabled |

### 3.2 Model and Runtime

| Item | Value |
|---|---|
| Model | Qwen3-8B GGUF |
| File | `Qwen3-8B-Q4_K_M.gguf` |
| License | Apache-2.0 |
| Expected SHA-256 | `d98cdcbd03e17ce47681435b5150e34c1417f50b5c0019dd560e4882c5745785` |
| Verified SHA-256 | `d98cdcbd03e17ce47681435b5150e34c1417f50b5c0019dd560e4882c5745785` |
| Context length | `8192` |
| GPU-layer CLI argument / measured assignment | `-ngl 99` configuration upper bound; independent load trace measured `37/37` layers on `ROCm0` |
| Batch / micro-batch | Not recorded in the current evidence set |
| Threads | Not recorded in the current evidence set |
| Flash attention or equivalent | `on` |
| OpenAlpha prompt version | Not separately versioned in the current evidence set |
| Embedding model and hash | Not exercised or recorded in the current evidence set |

## 4. Benchmark Data Sets

Keep the following sets separate; do not combine their metrics.

| Set | Purpose | Size | Version/hash |
|---|---|---:|---|
| Quality set | Human-labeled public strategy material; evaluates extraction and citations | Planned: at least 30 | Not assembled or run |
| Performance set | Team-authored synthetic documents with fixed length distribution | Planned: 100 | Not assembled or run |
| Safety set | Prompt-injection/resource-boundary cases, not part of extraction score | Planned: 30 | Not assembled or run |

Record the source manifest, annotation guide, expected output, and document-length distribution in the raw benchmark directory.

## 5. Compared Configurations

| ID | Configuration | Cache | Purpose |
|---|---|---|---|
| C1 | CPU baseline, same model/prompt/context where feasible | cold and warm | Reference |
| C2 | Radeon baseline, no pipeline optimization | cold and warm | GPU adoption |
| C3 | Radeon optimized: trimming, batching, hash cache, bounded pipeline | cold and warm | Final optimized system |

Any unavoidable difference between C1/C2/C3 must be documented. Do not compare different models or quality settings as if only the processor changed.

## 6. Measurement Procedure

1. Pin the code commit, model hash, prompt version, context, seed, and data-set hashes.
2. Restart the model service and record its complete startup/device/offload log.
3. Warm the runtime only for warm-cache runs; clear application/model caches for cold-cache runs.
4. Run at least five repetitions per measured configuration; the saved baseline uses five.
5. Save machine-readable per-request timings and aggregate them only after all runs finish.
6. Record TTFT P50/P95, decode tokens/s, complete latency, docs/min, peak VRAM, GPU utilization, failure rate, and retry rate.
7. Evaluate the resulting strategy cards and citations with the same scoring script.
8. Keep raw output, environment capture, and aggregation commands beside this report.

## 7. Commands and Artifacts

```bash
# Workstation: deploy the pinned runtime and start all loopback services.
./scripts/server_deploy.sh
./scripts/server_cli.sh doctor
./scripts/server_cli.sh seed
./scripts/server_cli.sh -- ask \
  "Summarize Daily Equity Mean Reversion and cite the source."

# Radeon host: collect the saved baseline snapshot.
cd /workspace/openalpha-sentinel
./scripts/benchmark_rocm.sh

# Deterministic local quality evaluation; the final labeled quality set is pending.
.venv/bin/python scripts/evaluate_local.py
```

| Artifact | Path or URL |
|---|---|
| Environment and benchmark capture | `generated/rocm-benchmark-20260717T051324Z.txt` |
| Radeon-host tests | `generated/rocm-test-run-20260717T050554Z.txt`, `generated/rocm-test-results-20260717T050554Z.xml`; 35 passed on Python 3.12.3 |
| CLI cited RAG transcript | `generated/rocm-cli-rag-20260717T050851Z.txt`; real CLI transport, `llama.cpp-rocm`, commit-pinned citation lines `8-28` |
| Loopback HTTP cited RAG transcript | `generated/rocm-http-rag-20260717T050918Z.txt`; HTTP `200`, `llama.cpp-rocm`, commit-pinned citation lines `8-28` |
| Restart and persistence trace | `generated/rocm-restart-trace-20260717T051301Z.txt`; all three PIDs changed and database/notification invariants passed |
| Runtime and GPU snapshot log | `generated/rocm-llama-runtime-20260717T051305Z.log`; command, load/listen, request timings, and one capture-time GPU-wide snapshot, without actual offloaded-layer count |
| Actual offload validation | `generated/rocm-offload-validation-20260717T152430Z.txt`; clean commit `25129cdd...`, `37/37` layers, 4,455.34 MiB model buffer, 1,152.00 MiB KV buffer |
| Raw C1 results | Not produced; CPU comparison was not run |
| Raw C2 results | No separate pipeline-baseline result; the saved `llama-bench` snapshot is listed below |
| Raw C3 results | Not produced; optimized comparison was not run |
| Aggregated baseline metrics | `generated/rocm-benchmark-20260717T051324Z.txt` |
| Deterministic local quality evaluation | `generated/local-evaluation.json` |
| GPU monitor evidence | One capture-time snapshot reports 63% GPU use and `6,642,937,856` bytes used; active peak and process/model attribution were not measured |

## 8. Performance Results

### 8.1 Interactive Inference

| Configuration | TTFT P50 | TTFT P95 | Decode tokens/s | Complete-answer P50 | Complete-answer P95 | Peak VRAM |
|---|---:|---:|---:|---:|---:|---:|
| C1 CPU baseline | Not measured | Not measured | Not measured | Not measured | Not measured | N/A |
| C2 Radeon baseline | Not measured | Not measured | `93.47 +/- 0.08` | Not measured | Not measured | Not measured |
| C3 Radeon optimized | Not measured | Not measured | Not separately measured | Not measured | Not measured | Not measured |

### 8.1.1 Verified Radeon Baseline Snapshot

| Measurement | Result |
|---|---:|
| `llama-bench pp512`, five repetitions, ROCm, `ngl=99` | `3033.77 +/- 154.27 tok/s` |
| `llama-bench tg256`, five repetitions, ROCm, `ngl=99` | `93.47 +/- 0.08 tok/s` |
| Application smoke requests completed | `15/15` |
| Mixed application-request mean / median | `4.8424 s / 5.5056 s` |
| Mixed application-request min / max | `0.00546 s / 10.1801 s` |
| GPU-wide capture-time snapshot | 63% GPU use and `6,642,937,856` bytes used; not process- or model-attributed, and not a peak |

The application figures mix deterministic tool routes and LLM-backed routes. They prove end-to-end execution but are not TTFT percentiles or a pure LLM latency distribution.

### 8.2 End-to-end Pipeline

| Configuration | Cold docs/min | Warm docs/min | Embedding docs/s | Failure rate | Retry rate |
|---|---:|---:|---:|---:|---:|
| C1 CPU baseline | Not measured | Not measured | Not measured | Not measured | Not measured |
| C2 Radeon baseline | Not measured | Not measured | Not measured | Not measured | Not measured |
| C3 Radeon optimized | Not measured | Not measured | Not measured | Not measured | Not measured |

### 8.3 Optimization Calculation

```text
Cold throughput improvement = (C3 cold docs/min - C2 cold docs/min)
                              / C2 cold docs/min * 100

Result: Not calculated because C2 and C3 pipeline throughput were not measured
```

## 9. Quality Results

| Metric | C1 | C2 | C3 | Target |
|---|---:|---:|---:|---:|
| Required-field correct value or correct `unknown` | Not measured | Not measured | Not measured | >=95% |
| Key categorical Macro-F1 | Not measured | Not measured | Not measured | >=0.80 |
| Deterministic license-field accuracy | Not measured | Not measured | Not measured | >=95% |
| Citation support rate | Not measured | Not measured | Not measured | >=95% |
| Resolvable commit-pinned citations with correct original-file lines | Not measured | Verified for saved examples only | Not measured | 100% |
| Fabricated URLs | Not measured | None observed in saved examples; no aggregate evaluation | Not measured | 0 |
| Schema pass rate | Not measured | Not measured | Not measured | No target fixed for this evidence set |

Quality change from C2 to C3: not calculated because comparable labeled evaluations were not run.

## 10. Reliability and 24-hour Run

| Item | Result |
|---|---|
| Soak start/end | Not run (optional) |
| Duration | Not run (optional) |
| Jobs attempted/completed/partial/failed | Not measured in a soak run |
| Model requests and failures | Not measured in a soak run |
| Retries | Not measured in a soak run |
| Process crashes | Not measured in a soak run |
| Peak database size / final integrity check | Peak size not measured; the controlled restart trace records `integrity_check=ok` |
| Controlled restart/resume result | Pass for one saved trace: llama/API/worker all stopped and restarted with three changed PIDs; model and API health checks passed |
| Duplicate card/notification result | Repeat seed created 0 cards and skipped 3 revisions; protected counts and notifications stayed unchanged |
| Post-restart database checks | `integrity_check=ok`; 0 foreign-key violations |

The final model runtime is available and one controlled process-mode restart/persistence check passed. This short trace is not 24x7 evidence. The optional 24-hour soak was not run; no continuous-run claim is made.

## 11. Conclusion

The Qwen3-8B Q4_K_M model was benchmarked by `llama-bench` with the ROCm backend on one `gfx1100` Radeon device using configured `-ngl 99`. The saved five-repetition snapshot measured `3033.77 +/- 154.27 tok/s` for `pp512` and `93.47 +/- 0.08 tok/s` for `tg256`. An independent clean load measured `37/37` layers on `ROCm0`. OpenAlpha also saved 35 passing Radeon-host tests, separate real CLI and loopback HTTP `200` cited responses labeled `llama.cpp-rocm`, a controlled three-process restart/persistence trace, and a validated 3:39.9 video with two real backend-labeled responses and 96 same-request GPU-activity samples. Structured LLM extraction quality, comparative CPU/Radeon optimization, TTFT percentiles, labeled quality results, active peak-VRAM tracing, and the optional 24-hour soak remain unmeasured or not run and must not be presented as measured improvements, peak-memory evidence, or 24x7 proof.
