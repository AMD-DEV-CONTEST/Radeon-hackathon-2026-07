# LoRA Training Failure Experiment Log (Reproducible Negative Result, Frozen)

> Status: **REJECTED_BY_FROZEN_QUALITY_GATE**
> **PRODUCTION_MODEL: STOCK_QWEN3_8B**
> Freeze date: 2026-08-04 (both the v1 and B1 rounds were rejected by the quality gate; the fine-tuning route is officially halted)
> Purpose: to record in full the configuration, data, results, SHA256 hashes, and decisions of both LoRA training rounds, as a reproducible negative result in the technical appendix.

## 1. Training Configuration (one-to-one correspondence with the failed adapters)

| Item | Value |
|---|---|
| Base model | `/workspace/Qwen3-8B` (Qwen3-8B, FP16) |
| LoRA | rank 16 / alpha 32 / dropout 0.05 / target `all-linear` |
| Training | epochs 2 / lr 5e-5 / batch 1 × grad_accum 16 / cosine / warmup 0.05 / FP16 / gradient checkpointing |
| Data | train 462 / dev 42 (template-grouped split) |
| Training result | train_loss 0.1982 · eval_loss 0.118 (**same-template dev, no predictive power for generalization**) |
| Training duration | ~43 min (gfx1100, 58 steps) |
| adapter | `/workspace/e-sentinel-lora` (adapter_model.safetensors + checkpoint-29/58) |
| Merged weights | `/workspace/Qwen3-8B-tuned` (not deleted, can be re-verified) |
| Evaluation | `evals/results/ablation-1785833868941.json` (tuned, local) |

## 2. Evaluation Results (frozen human-gold, 105 cases, local 8B)

| Variant | Recall | Precision | F1 | FPR | κ |
|---|---|---|---|---|---|
| **Stock agent** | 0.921 | 0.744 | 0.823 | 0.476 | 0.457 |
| **Tuned agent** | **0.714** | **0.592** | **0.647** | **0.738** | 0.135 |
| Stock dual | 0.508 | 0.941 | 0.660 | 0.048 | 0.407 |
| **Tuned dual** | **0.349** | 0.957 | **0.512** | 0.024 | 0.316 |

**Agent confusion matrix**: TP 58→45 · FP 20→31 · Recall 0.921→0.714 · FPR 0.476→0.738.
**Dual confusion matrix**: TP 32→22 · FP 2→1 (more conservative).

## 3. Root-Cause Analysis of the Failure (evidence-based, not speculation)

1. **Insufficient coverage/distribution, not merely insufficient quantity**: the 504 programmatic templates do not adequately cover the target distribution; eval_loss 0.118 only validates same-template fit and has no predictive power for generalization to near-real conversations.
2. **Missing Agent tool context**: training contained only isolated conversation classification, not "conversation + tool returns + final determination"; after fine-tuning, the model both missed detections and produced false positives in tool context (Dual became more conservative, Agent declined on both metrics), and risk calibration broke down.
3. **Template fitting / output distribution collapse**: the model learned template features rather than quality inspection rules, and failed to generalize.
4. **Not a uniform "stricter/looser" shift**: Dual more conservative + Agent more erratic points to tool-context conflict, rather than a uniform forgetting.

## 4. Integrity and Isolation Confirmation

- The 105 human-gold cases were **never used as training samples or as seeds for synthetic generation**; B1 checkpoint selection used an independent dev set of 266 cases.
- **Honest addition**: v1's aggregate results on human-gold (overall regression) directly drove B1's design decisions; therefore, after v1 this set was no longer a "completely untouched" model-selection holdout — but it never entered the training data or hyperparameter tuning, and the core fact of "no data leakage" remains unchanged.
- The training data `training/data/sft/*` passed triple decontamination (normalized exact match / character 5-gram Jaccard / character trigram hash vector cosine — the latter two are **lexical approximation detection**, not semantic embedding); the failsafe validation passed (all 3 gold variants were rejected).
- This negative result is preserved in full: not overwritten, not deleted, and reproducible.

## 5. B1 Training Record (second round, independent dev selection, still rejected)

### 5.1 Training Configuration (isolated variables vs. v1)

| Item | Value |
|---|---|
| Base model | `/workspace/Qwen3-8B` (Qwen3-8B, FP16) |
| LoRA | rank 16 / alpha 32 / dropout 0.05 / target `all-linear` (**same as v1, isolated variable**) |
| Training | **epochs 1 / lr 2e-5** / batch 1 × grad_accum 16 / cosine / FP16 / gradient checkpointing |
| Data | train **798** / dev **266** (independent dev selection; candidate set `candidates-b1-full.jsonl` **1064 entries** = base programmatic 504 + tool context 10 + counterfactual pairs 12 + hard negatives 6 (532 entries, `generate-training-data-b1.mjs`) + rehearsal 270 + stock-errors 262 (`generate-rehearsal.mjs`); decontamination rejected 0; train composition tool_context 14 / rehearsal 188 / counterfactual 22 / hard_negative 10 / programmatic 564; dev composition tool_context 1 / rehearsal 82 / programmatic 183) |
| Training result | train_loss **0.379** · eval_loss **0.133** (epoch 1) |
| Training duration | ~40 min (50 steps) |
| adapter | `/workspace/e-sentinel-lora-b1` |
| Merged weights | `/workspace/Qwen3-8B-tuned-b1` |

### 5.2 Independent Dev Selection Evaluation (dev-goldset 266 cases, human-gold untouched)

| Variant | Recall | Precision | F1 | FPR | κ |
|---|---|---|---|---|---|
| dual | 0.861 | 0.873 | 0.867 | 0.148 | 0.481 |
| **agent** | **0.986** | 0.582 | 0.732 | **0.836** | 0.275 |

**agent confusion matrix (dev: 144 severe / 122 non-severe)**: TP≈142 / FP≈102.
Severe violations were almost fully recovered (Recall 0.986), but **83.6% of non-violations were misjudged** — the agent severely over-escalated in tool context.

**Selection verdict: FAIL** (agent FPR 0.836 ≫ target 0.25). Per the pre-established stop condition (stop after two failures), no further training.

### 5.3 Root-Cause Wording (graded evidence strength)

- **Proven**: B1 severely over-escalated on the Agent path on the independent dev, failing the quality gate.
- **Supported by strong evidence**: the missed-detection correction samples in the training data (stock_errors, 114 missed detections) and the tool-context distribution pushed the model toward escalation.
- **Not independently proven**: exactly which 114 entries and which sample type contributed the most — establishing causality would require a data-subset ablation; **no third training round will be opened for this**.

### 5.4 Stock Comparison on the Same Dev (rigorous attribution, 2026-08-04)

| Variant | Stock (dev 266) | B1 (dev 266) | Delta |
|---|---|---|---|
| dual Recall | 0.986 | 0.861 | −0.125 |
| dual FPR | 0.164 | 0.148 | −0.016 |
| agent Recall | 1.000 | 0.986 | −0.014 |
| **agent FPR** | **0.623** | **0.836** | **+0.213** |
| agent F1 | 0.791 | 0.732 | −0.059 |
| agent κ | 0.262 | 0.275 | +0.013 |

**Attribution conclusions**:
1. The dev itself is harder (Stock agent FPR on dev 0.623 vs gold 0.476), which explains the elevated absolute FPR.
2. **B1 is worse than Stock on the same dev** (agent FPR +0.213, dual Recall −0.125) — B1 training worsened agent over-escalation and weakened dual recall.
3. On the same dev and the same tool path, B1 is worse than Stock → **the failure is attributed to model fine-tuning**, not to the dev or the tool environment.

## 6. SHA256 / Checksum Summary (reproducibility anchors)

> Note: this table covers **key artifacts** (evaluation data, configuration, scripts, results; the base model and merged-weight shards live on the remote instance — see "To be added on the instance" below). The train/dev/sft hashes are **file-byte** hashes (verified consistent with the on-disk files); the `train_jsonl_sha256`/`dev_jsonl_sha256` inside `decontamination-report.json` are hashes of **all conversations concatenated**, a different algorithm — do not conflate them.

| Artifact | SHA256 |
|---|---|
| **Evaluation data / results** | |
| gold-set `evals/configs/gold-set-human-v1.json` | `f1e0bfddcaf5556c8c3e35fc5f36aa7c3009a2fad660002ec882b448da0c81ec` |
| dev-goldset `evals/configs/dev-goldset.json` (266 cases, independent selection) | `d3b2c0efe3374abc3d435aae268935fb20f1d5655c1483572d62c2dafa81146d` |
| v1 tuned evaluation `evals/results/ablation-1785833868941.json` | `f32bc05933ba309fb0e9e83b10ad1fcf3cddf8dc25ae71f9c3115f31cd7d1fe9` |
| B1 dev-selection evaluation `evals/results/ablation-1785846354625.json` | `d60f453f66e81c12abaf1de8771e371f45196bd9560ee1c5e7f740a3c9e623c2` |
| Stock dev control `evals/results/ablation-1785853332828.json` | `df550302f8945d3c2e4e3b92d6803d1ad5508f29dcc7ce4e910eff0f37dfce87` |
| Quantization evaluation `evals/results/quantization-gptq-20260804.json` | `cc650f0e508b0968bd806a301a069cfda8da3b9853fdfe45f75d3dc2f341dcc8` |
| **Training data (file-byte hashes, verified)** | |
| candidates-b1-full.jsonl | `1f69eba7a95a428f5daeea384b8e8242a3cea2c80b95537e98ffb6f8151ccba8` |
| candidates-b1.jsonl | `d02b3f439f5afd3f485af8001c05d5e10901a741a5cbc2285ea2dd46bfceef38` |
| rehearsal.jsonl | `40466b82d1706bf0136633299a0570c82de411c116d81b75c238e8e84dfcb231` |
| stock-errors.jsonl | `10ac48897779f078b9c93c42cb101684bd83622127784aa6064fe62a13501a48` |
| train.jsonl | `49428feb7bd7ded710ec87ce8ee90dbe3374e285e766a1ea927c31feceabdcb5` |
| dev.jsonl | `2f47e60fd8769c13a6c3f8553667f27597ba94df89f56a64845f92a63bc5a217` |
| sft/train.jsonl | `9101f2812b17ead77afbec2164c001c88b53b6692953ea73b68b5179f378c271` |
| sft/dev.jsonl | `1bbfdddd6d33c4d265b6872bafbd644aa5b164c657ffa9ef27d54e72d5af9fa3` |
| decontamination-report.json | `9d80f0ce9ad114ae7fbeef138cb204a85a358265e469c824bab4b7927af4263e` |
| **Config / scripts (reproducibility anchors)** | |
| training/config/templates.json | `0ef3fa7d8a4c4e96787fbaaf4061f52a508ced37e154882f870fc76e52ab0875` |
| training/config/templates-b1.json | `97bcc6b88e4021d95b332b91c6a6beec8ae530e9633e534c6aa2b92b3b11f7e1` |
| training/lora-train.py | `6654a6fa129ca03dcbd78c804a5a186107af51ded01bd9f76780a830f1688e7f` |
| training/merge-lora.py | `03fb959cecbd81b4e62b143ee3eaed5bd15dc75b64969dee18513a62134b756b` |
| scripts/generate-training-data.mjs | `59887afeffaef1ff64709a8b9613d0225a6086dfc59d89d5d774e3d0c89ce401` |
| scripts/generate-training-data-b1.mjs | `9c3e1f91aa42fe45a4afccdaba96edc8c868404ca8d39a9438f19ec740551477` |
| scripts/generate-rehearsal.mjs | `9b5ce1ef7d356f303da3dbe6e94c3af1e1d9de3d53488de43a63ff6b14906b6c` |
| scripts/contamination-check.mjs | `728802e1b6ba7097598962b8c3479a224dd35128a6f89d1cc0964bd853a9124d` |
| **Adapter / merged weights** | |
| v1 adapter (`e-sentinel-lora/adapter_model.safetensors`) | `48b186b94ad683c76bfbe8caf138043bdcdfd2e837c7bdef88392d8002448621` |
| B1 adapter (`e-sentinel-lora-b1/adapter_model.safetensors`) | `1cbe1e6077faa543330ac3fda28c43b8fec2d61d9533a3c73ae8819c429a6ce8` |
| B1 merged config (`Qwen3-8B-tuned-b1/config.json`) | `d6485023aa2f3ae7c0a6bbd2b43fb3a5b4d61fe3223675b288fc6d9251543d2a` |
| Base model `/workspace/Qwen3-8B` revision + weight shards | **To be added on the instance** (remote, not locally accessible) |
| `Qwen3-8B-tuned-b1` weight shards | **To be added on the instance** (remote, not locally accessible) |

## 7. Formal Decision (halt fine-tuning)

- **REJECTED_BY_FROZEN_QUALITY_GATE** (v1: overall regression on human-gold; B1: agent FPR 0.836 on the independent dev).
- **PRODUCTION_MODEL: STOCK_QWEN3_8B** — production and the material's main version retain Stock.
- Failed adapters are retained (not deleted, prohibited from production loading), reproducible.
- The 105 human-gold cases continue to serve only as frozen evaluation, never entering training or hyperparameter selection (honest boundary: see Section 4 — v1 aggregate results influenced B1 decisions).

## 8. Implications for Follow-up Score-Improvement Items

1. The fine-tuning route has been halted; the remaining time shifts to deterministic score-improvement items (C4 retrieval, GPTQ W4A16 quantization, materials quality gate).
2. Quantization positioning: **a high-value validation experiment, not an automatic speedup** (vLLM 0.26 has an RDNA3-specific W4A16 path for gfx1100, but this is version/architecture-specific support that does not generalize to all AMD GPUs; moreover, switching between the old and new implementations plus historical Qwen-GPTQ compatibility issues require running the acceptance quality gate — see `QUANTIZATION-EN.md`).
3. Training narrative: the main text does not hide the failure; the technical appendix presents the two tables rejected by the quality gate — demonstrating that the evaluation quality gate can reject degraded models, that the team does not selectively report, and that production selection is based on real quality.
