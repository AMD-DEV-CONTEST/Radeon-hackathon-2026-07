> Chinese version: [EVIDENCE_MAP.md](EVIDENCE_MAP.md)

# EVIDENCE MAP — Claim → Evidence → Hash

The repository-wide canonical evidence index. Each row is an independently verifiable claim.

## Data

| Claim | Evidence | Key Hashes/Numbers |
|---|---|---|
| The data pipeline is deterministic and fail-closed | `examples/magicbox-data-pipeline/` (all five `npm run check` stages pass) | 11 output files are byte-identical to `expected/`; 15 tests; zero secret-scan findings |
| The origin of every example file is traceable | `examples/magicbox-data-pipeline/source-manifest.json` | 26 entries, each labeled verbatim/subset/sanitized |
| Composition and risk profile of the formal data release | `data/releases/rdk-sft-v1-20260803/RELEASE_README.orig.md` | 327 curated + 848 promoted (with 6 marker keys, allowing filtering and rollback); 428 evidence-related failures are labeled |
| Historically held-out Test released after evaluation | `data/releases/rdk-sft-v1-20260803/agentic/test.jsonl` | Isolated from training during evaluation; released with this repository after evaluation for reproduction; 113 tasks, 3,562,357 B, SHA `d1e1856b1185508a6f2e82af5797612edd90bfa83b595ceaf089f2ed9205e283` |
| Public sanitized dataset | [ModelScope: ming01/RDK-Agentic-SFT-Sanitized-v1](https://modelscope.ai/datasets/ming01/RDK-Agentic-SFT-Sanitized-v1/files) | train `40522e4e…`, validation `68ac3053…` (platform-side); schema shares the same source as this repository: `19854de1…` |
| Teacher lineage | The `session_file` and provenance markers in each sample's metadata | 1175/1175 samples are traceable to d-robotics-glm/glm-5.2 teacher sessions |

## Training

| Claim | Evidence | Key Hashes/Numbers |
|---|---|---|
| Training completed under the frozen contract | `examples/qwen3-32b-training/evidence/training-summary.json` + [full evidence tag](https://github.com/wm19999/rdk-sophon/tree/model-evidence-full-20260806/model/examples/qwen3-32b-training) | 119 optimizer steps, 948 micro-windows, final checkpoint `COMPLETE` |
| Learning curve | `examples/qwen3-32b-training/evidence/validations/validation-step-*.json` (0/30/60/90/119) | validation mean CE 1.1516 → 0.5936630333639499 |
| The compact training tree is byte-auditable | `examples/qwen3-32b-training/{source-manifest.json,verify_subset.py}` | Per-file SHA verification between the main-tree code and compact evidence; historical evidence moved out of the tree is retained under a fixed tag |
| Base-model source is pinned | `examples/qwen3-32b-training/artifacts/model-acquisition/qwen3-32b-bnb-7f721e74-verification.json` | `unsloth/Qwen3-32B-bnb-4bit@7f721e74a6a8…` |

## Model Artifacts and Deployment Identity

| Claim | Evidence | Key Hashes/Numbers |
|---|---|---|
| The adapter weights are the training output | `model/SHA256SUMS` + [ModelScope model repository](https://modelscope.ai/models/ming01/Qwen3-32B-Agentic-SFT-r1-v3/summary) | `adapter_model.safetensors` SHA `4dcee6914e3f9c61aeb33529208bf7e63f37c4c5ae5e0e37e7f7c6b3bfff20bf`, 268,555,264 B, byte-identical across four sources; the public `adapter_config.json` only normalizes the base path and revision for portability |
| The service loaded this exact adapter | `model/served-model-manifest.json` + `model/deployment_manifest.orig.json` | The deployment manifest binds the host fingerprint (u-7701-ae3eba8a/boot_id/GPU uid) and adapter SHA; `/health` reports checkpoint-000119 |
| The adapter is behaviorally active | `model/ab-probe/` (6 probes, temperature=0) | Capability probes (identity/math/tool_call) are byte-identical; all 3/3 behavioral probes show visible differences |
| Service-identity drift risk is documented | `serving_timeline_utc` and `known_footgun` in `model/served-model-manifest.json` | A Base service previously accepted the SFT model name through `--accepted-model-alias`, while the response `model` and `/health` truthfully recorded the actually loaded form |

## Evaluation (Base/SFT A/B)

| Claim | Evidence | Key Hashes/Numbers |
|---|---|---|
| SFT substantially improves tool-call agreement | `benchmark/runs/model-ab-heldout113-20260805-v2/{RESULTS.md,summary.json}` | Strict agreement 37.19%→67.77%; tool name 39.67%→76.86%; all-turn contract 0/49→15/49; paired 40:3 |
| Evaluation identity is locked per turn | `arms/*.manifest.json` from the same run + `response_models` in every raw record | Service-process arguments include `--adapter checkpoint-000119`; the 6 `--expect-file-sha256` items include adapter `4dcee691…` |
| Evidence is tamper-evident | `SHA256SUMS` + `arms/*.recovery-seal.json` | One-command verification with `sha256sum -c`; the interrupted arm was sealed once as a read-only snapshot |
| Costs are disclosed faithfully | Observed cost in `RESULTS.md` | SFT latency/tokens ≈ 2.1×; strict final-text equality is 0 for both arms (no claim of semantic correctness) |
| Independent re-scoring | `benchmark/recompute_ab.py` + Test + Base/SFT raw | Rebuilds references from public inputs and per-turn responses, then checks each item against `summary.json` |

## End-to-End Agent Run (Live RDK X5)

| Claim | Evidence | Key Hashes/Numbers |
|---|---|---|
| The offline gap decides whether a long-horizon task completes | `AGENT_E2E.en.md` + `assets/agent-e2e-sft-vs-base.png` | Same agent, same board, same task, model swapped: SFT 5/5 nodes accepted in 4 min 04 s; Base stalls at 3/5 and is terminated after 14 min 25 s |
| Base fails in the predicted way | Failure text in the same screenshot | `Agent 的结构化结果无法解析` — the acceptance node cannot parse the structured result, which is precisely the capability the SFT targets |
| No silent model substitution | Run banner in the same screenshot | `模型: d-robotics-glm/Qwen3-32B-Agentic-SFT-r1-v3`, `模型回退: 无` |
| Physical motion is not claimed | Agent's own report in the same run | 退出码 0 仅证明命令链路成功,不证明物理位移正确;仍需人类目视确认 |

## Radeon Inference Optimization

| Claim | Evidence | Key Hashes/Numbers |
|---|---|---|
| Inference optimization of the main 32B model is effective | `radeon-optimization/qwen3-32b-agentic-sft/{README.md,runtime.py,benchmark.py,results.json}` | Same base + adapter `4dcee691…` + GPU, 88 trials/arm: user-visible TTFT p50 17.41s→8.26s (2.11×), p95 6.52×, decode +2.8% |
| That optimization changes no outputs | `results.json` → `baseline_vs_optimized_output_agreement` + `quality_gates` | 88/88 outputs byte-identical; all gates passed; 0 failures/timeouts/truncations |
| Rejected candidates are recorded, not hidden | `radeon-optimization/qwen3-32b-agentic-sft/README.md` §5 + `results.json` → `boundaries` | LoRA-into-NF4 merge (delta below the quantization step, cosine 0.006) and `torch.compile`+StaticCache (slower at 3–6k prompts) implemented, measured, rejected |
| 80B single-GPU deployment optimization is effective | `radeon-optimization/qwen3-next-80b/{README.md,results/ab-20260730.json}` | Q4 KV + 47-layer offload: decode +34.0%, TTFT −10.5%; `verify_results.py` reproduces all ten measurements consistently |
| The optimization preserves functionality | Canary records in the same README | Structured tool_calls, tool continuation, and 42,028-token needle retrieval pass |
| Model source is pinned | Model fingerprint recorded in the README | `Qwen3-Next-80B-A3B-Instruct-Q4_K_M.gguf` 48,410,988,384 B, SHA `d103b273…` |

## Engineering Lessons (Recorded as Observed)

- **Service-identity drift:** The evaluator caught “SFT name requested, Base answered” in its first batch of records (2026-08-05); the public evidence therefore retains the response `model` and `/health` as proof of the actual service form.
- **The cost and value of strict fail-closed operation:** Each evaluation arm is bound to one service-process instance and cannot resume across a restart—three partially completed arms were discarded and rerun, making the identity of every record provable.
- **Multi-operator coordination:** Concurrent operations on the same training host caused two conflicting service switches; conclusion: evaluation resources must have a single owner.
