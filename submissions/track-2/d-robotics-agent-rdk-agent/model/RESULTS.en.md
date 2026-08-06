> Chinese version: [RESULTS.md](RESULTS.md)

# RESULTS — All Model-Side Results on One Page

Each result block includes an evidence location, one locally runnable verification command, and an honest boundary.

## 1. SFT Effect: Base vs SFT (Teacher-Trajectory Replay Held Out During Evaluation and Released Afterward)

The same frozen Test prefix (49 tasks / 170 turns per arm), the same service stack, temperature=0, and hash-locked identity for every turn in both arms:

| Metric | Base | SFT | Δ |
|---|---:|---:|---:|
| Strict tool-call agreement (name + arguments) | 45/121 (37.19%) | **82/121 (67.77%)** | +30.58pp |
| Tool-name agreement | 48/121 (39.67%) | **93/121 (76.86%)** | +37.19pp |
| Tool-argument agreement | 45/121 (37.19%) | **82/121 (67.77%)** | +30.58pp |
| Call-count agreement | 81/121 (66.94%) | **97/121 (80.17%)** | +13.22pp |
| Clean final turn | 44/49 (89.80%) | **48/49 (97.96%)** | +8.16pp |
| All-turn task contract | 0/49 (0.00%) | **15/49 (30.61%)** | +30.61pp |

Paired view: 40 turns were correct only for SFT, while 3 turns were correct only for Base. The gain is not in “whether the model can emit a structured call” (94.2%/95.0% for the two arms), but in **selecting the right tool and providing the right arguments**. Cost: SFT generated tokens and latency are about 2.1× higher (p50 10.4s→18.8s).

```bash
cd benchmark/runs/model-ab-heldout113-20260805-v2
sha256sum -c SHA256SUMS
python3 ../../recompute_ab.py \
  --test ../../../data/releases/rdk-sft-v1-20260803/agentic/test.jsonl \
  arms/base.raw.jsonl arms/sft.raw.jsonl summary.json
```

Boundary: replay agreement ≠ end-to-end task success or physical effect; the Test was released after evaluation for reproduction and can no longer serve as a future uncontaminated evaluation set; the evaluation prefix is a deterministic ordered prefix (28 curated diagnostics + 5 curated controlled actions + 16 promoted diagnostics), not a random sample; strict final-text equality is 0 for both arms, so no claim of semantic correctness is made. See [benchmark/runs/…/RESULTS.en.md](benchmark/runs/model-ab-heldout113-20260805-v2/RESULTS.en.md).

## 2. Training: QLoRA-SFT Convergence Facts

One AMD Radeon gfx1100 GPU (48GB), 4-bit base + LoRA (r=8, α=16, 67,108,864 trainable parameters), 1 epoch / 119 optimizer steps / 948 micro-windows. The PyTorch peak recorded in Phase 2 was 37,633,069,056 allocated / 38,593,888,256 reserved bytes:

| checkpoint | validation mean CE |
|---|---:|
| step 0 | 1.1516 |
| step 119 (released) | **0.5937** |

```bash
cd examples/qwen3-32b-training && python3 verify_subset.py   # Compact training tree + Test hash reconciliation
```

Boundary: the CE reduction proves that fitting occurred; the A/B result in Section 1 above addresses the Agent capability improvement. Full retraining is optional, and numerical results may differ across hardware/software versions.

## 3. Deployment Identity: The Service Loaded the Training Artifact

The adapter `4dcee6914e3f9c61aeb33529208bf7e63f37c4c5ae5e0e37e7f7c6b3bfff20bf` (268,555,264 B) is identical across four sources: frozen training manifest = original file on the training host = local backup = ModelScope platform-side hash. Service `/health` reports `checkpoint-000119`, with about 19.3GB VRAM after loading; a 6-probe comparison demonstrates that the adapter changes behavior (capability probes are byte-identical, while all 3/3 behavioral probes differ).

```bash
cat model/served-model-manifest.json   # Identity chain + service timeline + behavioral comparison
# With Radeon: start the service following model/serving/README.md to reproduce
```

Boundary: there was a time window in which the Base service answered under the SFT model alias (faithfully recorded in the evidence). When verifying service identity, inspect both the response `model` field and `/health`; see `model/serving/README.md` for the integration interface.

## 3.5 Does that difference actually finish a task?

The metrics above are agreement with frozen references. Put the same two models behind the real `rdk-agent` workflow on a live RDK X5, change nothing but the model, and ask for the same capability:

| | Base | SFT |
| --- | --- | --- |
| Workflow nodes completed | 3 / 5 (60%) | **5 / 5 (100%)** |
| Outcome | stalled at CLI live acceptance; operator terminated after 14 min 25 s | **accepted** in 4 min 04 s |

Base did not crash — it produced a result the acceptance node could not parse (`Agent 的结构化结果无法解析`), which is exactly the capability the strict tool-call metric measures. The offline number is the mechanism behind the live outcome, not a separate claim. Full run detail, including what is *not* proven: [AGENT_E2E.en.md](AGENT_E2E.en.md).

## 4. Radeon Inference Optimization

### 4.1 Main 32B agent model (the model this repository is about)

Same base, same adapter, same GPU, temperature=0, 14 tasks / 44 turns / 2 passes = 88 trials per arm. Baseline is the unmodified production inference path; the optimization is true token streaming plus a lean LoRA decode path (`radeon-optimization/qwen3-32b-agentic-sft/runtime.py`):

| Metric | Baseline | Optimized | Change |
|---|---:|---:|---:|
| User-visible TTFT p50 | 17.41 s | **8.26 s** | **2.11×** |
| User-visible TTFT p95 | 83.97 s | **12.89 s** | **6.52×** |
| Decode | 6.54 tok/s | **6.72 tok/s** | +2.8% |
| Output agreement vs baseline | — | **88/88 byte-identical** | all quality gates passed |

```bash
cd radeon-optimization/qwen3-32b-agentic-sft && cat results.json   # generated on the Radeon host by benchmark.py
```

Boundary: the gain is honest to classify as a streaming/TTFT optimization, not a kernel speedup — the production server already paid the prefill and then withheld every token until generation ended. Two higher-ceiling candidates (merging LoRA into the NF4 base; `torch.compile` + StaticCache decode) were implemented, measured on the machine, and rejected on evidence; see the README in that directory. The optimization is validated but not yet wired into the live serving path.

### 4.2 Single-GPU Qwen3-Next-80B Deployment (Independent Case Study)

Official pre-quantized Q4_K_M (48.4GB) + ROCm/HIP llama.cpp on one gfx1100 GPU; the optimization changes only KV precision (Q8→Q4) and the number of GPU-offloaded layers (45→47):

| Metric | Baseline | Optimized | Change |
|---|---:|---:|---:|
| Prefill (2,332 tok) | 1,271.45 tok/s | **1,397.39 tok/s** | +9.9% |
| Decode (64 tok) | 37.19 tok/s | **49.82 tok/s** | +34.0% |
| Median TTFT | 2,021.26 ms | **1,808.76 ms** | −10.5% |
| Mean wall-clock latency | 3,727.88 ms | **3,084.19 ms** | −17.3% |

The optimized configuration also passes all three canaries: structured tool_calls, tool continuation, and 42,028-token needle retrieval.

```bash
cd radeon-optimization/qwen3-next-80b && python3 verify_results.py   # Recompute saved aggregates and deltas from ten records
```

Boundary: this case study is independent of the 32B SFT mainline (not the demo model and not the teacher); verification recomputes the saved measurement evidence rather than rerunning inference; only the TTFT median is stored, so the delta is verifiable but the distribution cannot be reconstructed.

## Overall Result (One-Sentence Version)

> On Radeon: training converged (CE −48.4%), artifact identity closed across four hash-matched sources, SFT improved strict tool-call agreement by 30.6 percentage points (0→15 tasks satisfying the all-turn contract), inference on that same 32B model cut user-visible TTFT by 2.11× with byte-identical outputs, and an independent case study demonstrated single-GPU deployment optimization for an 80B-class model (decode +34%). Every claim above is tied to saved evidence; the commands on this page distinguish offline recomputation from GPU-required benchmark reruns.
