# Production Readiness Scorecard

Assessment date: 2026-07-29. A gap is not silently waived for the hackathon.

| # | Definition of done | State | Evidence / gap | Close effort |
|---|---|---|---|---|
| 1 | Context utilization measured | N/A for deterministic fallback; GAP for model path | The L2 control plane does not retain chat context. Gemma/Diffusers trace token metrics are not yet captured. | 0.5 day after Radeon reconnect |
| 2 | State externalized | PARTIAL | Hash ledger, checkpoint, and final state are files; automatic resume from checkpoint is not implemented. | 0.5 day |
| 3 | Compaction tested | N/A for current L2 path | No long conversational session exists. Reassess if a free-form coworker loop is enabled. | design gate |
| 4 | Destructive actions require approval | PASS | `ActionPolicy` requires approval for send, publish, shell, overwrite, delete, sign, and account connection. | maintain |
| 5 | Permissions enforced in code | PASS within submitted surface | Untrusted write/side-effect attempts are denied in code; no publishing credential is held by the workflow. | connector-specific audit later |
| 6 | Tool execution sandboxed | PASS for reviewed adapter | Observed Docker receipt proves non-root, no network, read-only root, dropped capabilities, resource limits, one writable workspace, filesystem-escape denial and boundary-only secret injection. This does not cover every future tool. | maintain and repeat per adapter |
| 7 | Pause/resume/retry survives kill | GAP | Per-stage checkpoints exist; killed-process resume and human wait signals do not. | 1–2 days |
| 8 | Structured outputs/assertions | PARTIAL | Typed contracts and deterministic assertions cover the critical release path. Real model structured outputs still need schema validation evidence on Radeon. | 0.5 day |
| 9 | Input/output guardrails | GAP | Exact-source claims and output audits exist. PII and prompt-injection classifiers are absent because no free-form tool agent is enabled. | 1 day before connectors |
| 10 | ≥50 cases per top failure mode | PASS for five Level-1 modes | 250 synthetic cases, 50 per named mode, must pass 100%. Real trace-derived cases remain unavailable before pilot traffic. | add weekly |
| 11 | LLM judge calibrated | GAP | The blinded 100-case/300-label protocol, durable service and strict gates are implemented, but the production evidence set still has 0 qualifying human calibration labels. TPR and TNR must both be strictly above 80% before use. | five raters plus adjudication |
| 12 | CI blocks regression; all traces logged | PARTIAL | CI gate, 250-case control eval, and local hash-ledger traces are implemented. Production retention and a real hosted deployment are not. | 1 day |

## Launch decision

The deterministic local reference is fit for technical review. The competition
submission is **not yet releasable**: real Radeon execution, visual benchmark,
and human preference gates remain blocked. The Demo Video and PR are present. No superiority,
persuasion, or ROCm-performance claim is permitted before those artifacts
exist.

## Risk order

1. Restore Radeon kernel/terminal control and execute the frozen gate.
2. Run sequential Gemma, SDXL, and SigLIP2 phases; capture retention, semantic
   score, latency, VRAM, and all output hashes.
3. Preserve the included 190.9-second Demo Video and append live Radeon evidence
   only after a real hardware run is captured.
4. Run blinded preference and operator-time studies.
5. Add killed-process resume and model-output schema guards before any hosted
   or connector-enabled release.
