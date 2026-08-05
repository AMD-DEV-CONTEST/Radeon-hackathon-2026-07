# Targeted-regen round trip validated July 17 — exact match 0.667 → 0.833

One-liner: the agent's eval-driven improvement loop works end to end on
the 4060 — resume build from registry → diagnose (feature_request weak,
0.667 recall) → augment_dataset(+30, focus) with frozen holdout →
retrain (141 examples, loss 0.026) → re-eval on the SAME 12-example
holdout: exact 0.667→0.833, category 0.917→1.00, priority 0.667→0.833.

Run: runs/build-northbeam-support-ticket-triage-20260717-115730 (train
grew 59→111→141 across two agent sessions; holdout untouched
throughout — augment-mode dedupe seeded from existing rows worked, and
resume_build reconstructed session state from registry + spec.json).

Unresolved: two consecutive train subprocesses failed with
CUBLAS_STATUS_EXECUTION_FAILED in backward (cublasGemmEx). CORRECTION
(later same day): the expandable_segments env var that appeared to fix
it is a NO-OP on Windows ("not supported on this platform") — the
success was coincidence. The failure recurred and was investigated
exhaustively; see [[cublas-flake-4060]] for the evidence trail and the
reboot-first policy. Radeon relevance low (48GB, no teacher/train VRAM
contention, ROCm allocator differs).

Agent reporting flaw fixed structurally: evaluate_student now returns
previous_tuned from the registry so the before/after table can't
silently substitute the base model as "before" (the 4B did exactly
that in its otherwise-correct summary).

Context-overflow fix validated: tool results truncated to 1200 chars
before entering conversation; the long two-augment session no longer
400s at 3×6144 slot size.
