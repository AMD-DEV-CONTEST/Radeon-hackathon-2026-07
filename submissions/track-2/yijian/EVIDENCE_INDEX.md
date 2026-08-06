# Evidence Index

Every published metric resolves to a file under `evidence/` and a SHA-256 entry in the final hash bundle. Pending values are never replaced by estimates.

| Evidence | File | State |
|---|---|---|
| Machine source of truth | `submission-status.json` | GENERATED; competition alias remains `current-27b` |
| 720 SFT manifest | `evidence/data/agent-sft-manifest.json` | PASS; 720/24/24 and sealed inaccessible |
| Base revision and shard hashes | `evidence/model/base-manifest.json` | VERIFIED |
| vLLM / ROCm environment | `evidence/environment/qwen3-14b-vllm.json` | VERIFIED |
| Smoke raw/profile | `evidence/training/smoke-metrics.json` / `smoke-profile.json` | PASS |
| Micro raw/profile | `evidence/training/micro-metrics.json` / `micro-profile.json` | PASS |
| Full raw/profile | `evidence/training/full-metrics.json` / `full-profile.json` | PASS |
| Frozen adapter manifest | `evidence/model/adapter-freeze.json` | FROZEN; tree SHA `9de299…0ff0` |
| Private local adapter verification | `evidence/model/local-adapter-archive.json` | PASS; path and weights omitted |
| 220/24/40 runtime evaluation | `evidence/evaluation/formal-evaluation.json` | PASS; 39/40 faithful, severe contradictions 0 |
| Blind review result/status | `evidence/evaluation/blind-review-result.json` / `blind-review-status.json` | COMPLETE / FAIL; 27B 4.6133, base 2.8500, LoRA 2.5400 |
| Sealed-once status | `evidence/evaluation/sealed-status.json` | NOT OPENED after failed blind review; access count 0 |
| Coexistence matrix | `evidence/performance/coexistence-summary.json` | PASS; 3 profiles × 30 cycles, OOM 0 |
| v3 prefix/context ablation | `evidence/performance/ablation-status.json` | NOT RERUN; no v3 claim |
| 27B rollback health | `evidence/deployment/rollback-health.json` | PASS |
| Public source manifest | `evidence/submission/public-snapshot-manifest.json` | PASS; 141 allowlisted files |
| Public snapshot validation | `evidence/submission/public-snapshot-validation.json` | PASS; 189/189 tests, clean startup, 0 secret/private/forbidden findings |
| Release-gate status | `evidence/release/release-gate-status.json` | BLOCKED; blind false, sealed false, competition fallback retained |
| Immutable evidence hash bundle | `evidence/hash-bundle.json` | GENERATED; 32 indexed files; bundle SHA `f59548c40f4588c83dde361ddc68804c7f6c7e7e5832334c0cefc40da593af9b` |

The evidence directory contains summaries, manifests, reports, and hashes—not private training rows, sealed prompts, model weights, raw videos, authorization screenshots, or reviewer comments.
