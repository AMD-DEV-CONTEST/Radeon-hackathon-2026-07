> Chinese version: [README.md](README.md)

Authors: Han Zhaoming; Wang Ming


# RDK MagicBox Distillation Closed Loop (distill)

**A Qwen3-32B Agentic SFT model trained on AMD Radeon (gfx1100, ROCm) was deployed as an inference service through a hash-bound identity chain. On a teacher-trajectory Test kept isolated during evaluation and released afterward for reproduction, it improved strict tool-call agreement from 37.2% to 67.8%.** This repository provides verifiable evidence for each model-side stage.

## Results (Start Here)

Base vs SFT on the same frozen Test prefix (49 tasks / 170 turns per arm), with the same service stack, temperature=0, and hash-locked model identity for every turn in both arms:

| Metric | Base | SFT | Δ |
|---|---:|---:|---:|
| Strict tool-call agreement (name + arguments) | 37.2% | **67.8%** | +30.6pp |
| Tool-name agreement | 39.7% | **76.9%** | +37.2pp |
| All-turn task contract | 0/49 | **15/49** | +30.6pp |
| Clean final turn | 89.8% | **98.0%** | +8.2pp |

Paired result: 40 turns were correct only for SFT, while 3 turns were correct only for Base. The gain is not in “whether the model can emit a structured call” (both arms are ~95%), but in **selecting the right tool, providing the right arguments, and making the right number of calls**. Cost: SFT uses about 2.1× the generated tokens/latency. For the complete methodology, cost, and boundaries, see [benchmark/runs/…/RESULTS.en.md](benchmark/runs/model-ab-heldout113-20260805-v2/RESULTS.en.md). **For a one-page summary of all model-side results (SFT effect + training convergence + deployment identity + Radeon inference optimization), see [RESULTS.en.md](RESULTS.en.md).**

## Closed-Loop Path and Evidence

```text
 Data pipeline                  Training               Artifact identity              Deployment           Evaluation
 examples/magicbox-            examples/qwen3-        adapter sha256                 model/                benchmark/
 data-pipeline/                32b-training/          4dcee691…f20bf                 served-model-         runs/…-v2/
 npm run check                 119 steps              Four-way byte match:           manifest.json        49-task A/B
 Byte deterministic ✔          CE 1.152→0.594         frozen manifest/training host/ health+process args+ identity locked
 fail-closed negative tests ✔  Phase1/2 PASS ✔        local backup/ModelScope        Base/SFT diff ✔      per turn ✔
```

## Public Artifacts (ModelScope)

| Artifact | Location | Key Verification |
|---|---|---|
| LoRA adapter (checkpoint-000119) | [ming01/Qwen3-32B-Agentic-SFT-r1-v3](https://modelscope.ai/models/ming01/Qwen3-32B-Agentic-SFT-r1-v3/summary) | `adapter_model.safetensors` 268,555,264 B, SHA-256 `4dcee691…f20bf`; the platform-side hash is byte-identical to the frozen training manifest |
| Training data (sanitized train + validation) | [ming01/RDK-Agentic-SFT-Sanitized-v1](https://modelscope.ai/datasets/ming01/RDK-Agentic-SFT-Sanitized-v1/files) | The schema is byte-identical to the version in this repository; the Test was historically held out during evaluation and was released with this repository afterward for reproduction |

Base model: `unsloth/Qwen3-32B-bnb-4bit@7f721e74` (4-bit base + LoRA loaded at runtime, not a merged quantized deliverable).

## Three Reproduction Tiers (Go as Deep as Your Hardware Allows)

**Tier 0 — Ordinary computer, about 5 minutes, no model invocation:**

```bash
# Data pipeline closed loop: re-export → re-verify → byte-compare with canonical outputs → negative tests → secret scan
cd examples/magicbox-data-pipeline && pip install -r requirements.txt && npm run check

# Reconcile hashes across the training evidence chain
cd ../qwen3-32b-training && python3 verify_subset.py

# A/B: evidence byte integrity + recompute the full table from raw records (must match every published summary item)
cd ../../benchmark/runs/model-ab-heldout113-20260805-v2
sha256sum -c SHA256SUMS
python3 ../../recompute_ab.py \
  --test ../../../data/releases/rdk-sft-v1-20260803/agentic/test.jsonl \
  arms/base.raw.jsonl arms/sft.raw.jsonl summary.json
```

**Tier 1 — Radeon GPU available, about 20 minutes:** Download the public base + adapter, start the service with one command, confirm that the health check reports `checkpoint-000119`, and reproduce the Base/SFT behavioral difference with the probes. Full instructions: [model/serving/README.en.md](model/serving/README.en.md).

**Tier 2 — RDK board available:** Configure `rdk-agent` itself to use the OpenAI-compatible API exposed by the Radeon service, then run the existing `rdk-agent → sophonctl → RDK` path; the physical effect is determined by the board-side observation from that run.

Training does not need to be rerun: the public adapter is the artifact used by the demo and A/B evaluation; frozen training code, configuration, and one example command are available in `examples/qwen3-32b-training/`. The historical facts are 119 optimizer steps on one AMD Radeon gfx1100 GPU. Full retraining is optional, and numerical results may differ across hardware and software versions.

## Directory Guide

| Directory | Contents | In One Sentence |
|---|---|---|
| `examples/magicbox-data-pipeline/` | Original production code + small frozen inputs + canonical outputs | How the data is produced and verified |
| `examples/qwen3-32b-training/` | Byte-frozen training code + compact result evidence; see the fixed tag for full history | Training implementation, convergence, and artifact hashes |
| `model/` | Identity chain + Base/SFT behavioral difference + service timeline | The deployed weights are the weights produced by training |
| `model/serving/` | Original server artifact (same evidence hash) + serve.sh + dependencies | Tier 1: run it yourself |
| `benchmark/` | Frozen replay evaluator + sealed run evidence | How much stronger SFT is than Base, and at what cost |
| `data/releases/…/agentic/test.jsonl` | Historically held-out frozen Test (released after evaluation) | Evaluation input, SHA `d1e1856b…5e283`, for independent re-scoring by judges |
| [`AGENT_E2E.en.md`](AGENT_E2E.en.md) | End-to-end run of the real agent workflow on a live RDK X5, SFT vs Base | SFT 5/5 nodes accepted; Base stalls at 3/5 |
| `radeon-optimization/qwen3-32b-agentic-sft/` | Inference optimization of **this** 32B model on gfx1100 + on-device A/B | user-visible TTFT 2.11×, outputs byte-identical |
| `radeon-optimization/qwen3-next-80b/` | Qwen3-Next-80B single-GPU deployment optimization (independent case study) | decode +34%, reproducible offline |
| [`EVIDENCE_MAP.en.md`](EVIDENCE_MAP.en.md) | Claim → evidence file → hash master index | One map for the entire repository |

## Boundaries (Use These in Public Claims)

Replay agreement measures contract agreement with historically held-out teacher trajectories; it **does not equal** end-to-end Agent success, board-side execution, or a physical effect. The latter must be demonstrated jointly by the Agent run, `sophonctl`, and board-side observation from that run — that demonstration is [`AGENT_E2E.en.md`](AGENT_E2E.en.md), which is one task per arm rather than a sampled success rate, and which still leaves physical displacement to human visual confirmation. The Test was released after evaluation for reproduction and should no longer be used as a future uncontaminated evaluation set. The evaluation prefix is a deterministic ordered prefix rather than a random sample, and it contains no promoted controlled-actuation tasks. The training data includes 848 marked promoted samples (revertible with a one-line filter; see the dataset README). The training code is a verified fail-closed snapshot bound to the original host and environment; the full historical training evidence is fixed at tag [`model-evidence-full-20260806`](https://github.com/wm19999/rdk-sophon/tree/model-evidence-full-20260806/model/examples/qwen3-32b-training).

## Licensing Note

This repository currently declares no unified license; all rights to the source code are reserved until the repository owner confirms a license. The public model, dataset, and third-party dependencies are each governed by the licenses listed in their respective repositories.
