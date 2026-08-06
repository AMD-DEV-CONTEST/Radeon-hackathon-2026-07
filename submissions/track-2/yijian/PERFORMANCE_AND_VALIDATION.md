# Performance and Validation

This report cites only immutable files listed in [EVIDENCE_INDEX.md](EVIDENCE_INDEX.md). Pending stages are labelled instead of estimated.

## Hardware and software

| Component | Frozen value |
|---|---|
| GPU | AMD Radeon PRO W7900, 48 GiB, gfx1100 |
| Base model | Qwen3-14B BF16 |
| Base revision | `40c069824f4251a91eefaf281ebe4c544efd3e18` |
| Training Torch / ROCm | `2.9.1+rocm7.2.1.gitff65f5bc` / HIP `7.2.53211-e1a6bc5663` |
| vLLM | `0.20.2rc1.dev15+g321fa2d6d.rocm721` |
| vLLM commit | `321fa2d6d1644629ac39d173f6393f37e14bf7b4` |
| Inference Torch / Transformers | `2.10.0+git8514f05` / `5.14.1` |
| KataGo | 1.16.5, OpenCL on gfx1100, official b40 network |

## Training evidence

| Stage | Result | Loss evidence | Peak reserved |
|---|---|---|---:|
| 4-step smoke | PASS | train 5.1350; eval 3.1074 | 36.961 GiB |
| 8-example / 30-step micro | PASS | 4.0948 → 3.6016; -12.05% | 37.631 GiB |
| 720-record / 2-epoch full | PASS | dev 3.1131 → 1.6685; -46.40% | 38.643 GiB |

The full run completed exactly 90 optimizer steps and 2 epochs in BF16 without FP16 fallback. Answer loss improved by 45.17%, planner by 39.84%, and follow-up by 72.83%; no measured task category regressed. The actual v3 training configuration is LoRA rank 8, alpha 16, dropout 0.10, learning rate `3e-5`, batch 1, gradient accumulation 16, and seed `20260803`. The frozen adapter tree SHA-256 is `9de29915ef28dfe66ee3b3239bc9ff70f5ee8a53176a09d918ac425c8cb90ff0`.

## Post-freeze evaluation

| Suite | Size | Required gate | Verified result |
|---|---:|---|---|
| Agent plan/tool/RAG/memory/multi-turn/evidence | 220 | legal plan 100%; raw structured output ≥98% | PASS: 220/220 raw valid, legal, and executed; fallback 0 |
| Failure and privacy | 24 | board and deterministic fallback available; unauthorized writes 0 | PASS: 24/24; unauthorized writes 0 |
| Unseen positions | 40 | evidence fidelity ≥95%; severe contradictions 0 | PASS: 39/40 structured and faithful (97.5%); severe contradictions 0 |
| Official specialty subset | 12 | severe errors 0 | PASS: 12/12 |
| Anonymous 14B / LoRA / 27B review | 30 × 3 | LoRA ≥20% over base, not below 27B, severe contradictions 0 | FAIL: 27B 4.6133; base 2.8500; LoRA 2.5400; uplift −10.88%; LoRA severe contradictions 5 |
| Sealed creator test | 8 units | one access only after a passing blind review | NOT OPENED; access count 0 |

The 40-position suite contains 12 reviewed specialty cases and 28 project-original positions. Each project position is rebuilt through goboard, checked for symmetry leakage, and paired with a fresh 128-visit KataGo analysis. None is training-eligible. One model response was not valid JSON, which is why fidelity is reported as 39/40 rather than silently rounded to 100%; it did not contain a severe contradiction or fabricated source.

## ROCm inference and real coexistence

| Profile | Valid cycles | OOM | Combined P95 | First-token P95 | KataGo P95 | Peak VRAM |
|---|---:|---:|---:|---:|---:|---:|
| memory utilization 0.72 | 30/30 | 0 | 10.3355 s | 0.1735 s | 0.5088 s | 39.518 GiB |
| memory utilization 0.75 | 30/30 | 0 | 11.9304 s | 0.1828 s | 0.6579 s | 40.921 GiB |
| memory utilization 0.78 | 30/30 | 0 | 10.3840 s | 0.1717 s | 0.9124 s | 42.403 GiB |

Every cycle overlaps KataGo analysis of the next position with LoRA generation for the previous evidence bundle. All three profiles pass the 12-second gate. The competition configuration selects 0.72 because it is the lowest passing fraction and preserves the most KataGo headroom. The first warm cycle is retained in the raw rows rather than removed; the reported P95 follows the frozen nearest-rank calculation over 30 cycles.

Prefix-cache off/on and 16,384/8,192 context ablations from the superseded adapter are excluded. They have not yet been rerun for v3, so this report makes no v3 ablation-speed claim. Quantization is not part of the release path.

## Rollback and release

The 27B service was restored after exclusive training and benchmark stages. The LoRA failed the completed anonymous human review, so the sealed-once set was not opened and the final release gate correctly retained the 27B competition alias. The frozen adapter remains an experimental, reproducible artifact and is never presented as the released competition model.
