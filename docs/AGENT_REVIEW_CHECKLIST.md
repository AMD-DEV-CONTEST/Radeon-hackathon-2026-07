# Agent Review Checklist

Use this checklist when an agent (or a reviewer) submits code to Bunker. It
pins the conventions this repo depends on: source-grounded RAG, a strictly
local inference backend, and statistical integration testing. Every box should
be ticked before a change is considered review-ready.

## Conventions
- [ ] Every `dspy.*` import verified against installed version?
- [ ] `dspy.LM` used, NOT `dspy.OpenAI`?
- [ ] `dspy.configure(lm=...)` called exactly once?
- [ ] Assertions wrapped with the transform step?
- [ ] `grep -rE "https?://(?!localhost|127.0.0.1)" src/` returns nothing new?
- [ ] No `teacher_settings` pointing at a cloud model?
- [ ] `cache=False` on every `dspy.LM` instantiation?
- [ ] Optimizer runs only in `scripts/`, never in `src/`?

## Tests
- [ ] No test asserts only `result is not None` or `len(result) > 0`?
- [ ] Every integration test uses statistical pass-rate (k-of-n)?
- [ ] Did you test prompt injection from untrusted PDFs? (`make test-security`)
- [ ] Did you test the "Deny" path for the PermissionController? (`make test-security`)
- [ ] Are latency/VRAM thresholds asserted? (`make test-perf`, thresholds via `BUNKER_PERF_*`)
