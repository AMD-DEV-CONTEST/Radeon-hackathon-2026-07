# Intermittent CUBLAS_STATUS_EXECUTION_FAILED on the 4060 — unresolved; reboot before rehearsals

One-liner: local training on the dev box began failing intermittently
with CUBLAS_STATUS_EXECUTION_FAILED (afternoon July 17) after a full
day of GPU churn; root cause NOT determined; every code-level theory
was tested and eliminated; recommendation = reboot before local
training/rehearsal sessions and treat local trains as flaky until a
post-reboot canary passes. Radeon is unaffected (different OS, driver,
allocator; 10× headroom).

Evidence trail (all July 17, times approximate):
- Morning–13:00: many successful trains, identical code paths.
- 13:1x: two trains fail in backward (cublasGemmEx). Adding
  PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True "fixed" it —
  **placebo**: torch logs "expandable_segments not supported on this
  platform" on Windows. The success that followed was coincidence
  (corrects the claim in [[regen-roundtrip-milestone]]).
- 14:1x onward: rehearsal train fails in FORWARD (cublasSgemm inside
  the fp32 LoRA path), then reproducibly fails twice more.
- Eliminated by direct test, one variable at a time:
  - Bare fp32/bf16 GEMMs in a fresh process: PASS.
  - Data: all 54 examples forward+backward individually: PASS.
  - Exact first 4 training batches (same shuffle seed, same collate,
    batch 8): PASS in a standalone script.
  - Known-good older dataset through the real entrypoint: PASS.
  - New dataset through the real entrypoint: FAIL, FAIL — then the
    same command under CUDA_LAUNCH_BLOCKING=1: STILL FAIL, while the
    equivalent standalone repro passed minutes earlier.
- Conclusion: not data, not shapes, not our loop, not launch timing
  alone — nondeterministic environment failure. Ambient VRAM grew from
  ~0.4 to ~2.6 GiB over the day (browser etc.); WDDM paging pressure is
  the leading (unproven) suspect.

Operational policy going forward:
1. Reboot (or at least close GPU-hungry apps) before any local
   training or demo-rehearsal session; run one pilot train as a canary
   first.
2. Discovered in passing: configs/pilot_4060.toml still had
   batch_size=8 (the batch-4 OOM fix went only to local_4060 and
   cloud_radeon) — now aligned to 4/4, which also lowers pressure.
3. Do NOT chase this further on the 4060; it does not gate the
   submission. If it ever appears on the Radeon, that is a different
   investigation.
