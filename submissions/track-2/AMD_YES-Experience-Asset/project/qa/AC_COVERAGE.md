# Public AC Coverage Map

> **2026-08-05 update:** every previously planned private/undisclosed
> evaluation intent has been made developer-visible in
> [`spec/FINAL_SPRINT_EXECUTION_PACKAGE.md`](../spec/FINAL_SPRINT_EXECUTION_PACKAGE.md).
> Rows below mentioning a private suite or private sign-off describe the older
> plan, not a remaining E5–E9 gate. Runtime evidence is still required.

This map prevents a green framework check from being reported as a green
product. Status describes the **verification mechanism**, not implementation.

| AC | Public mechanism ready now | Runtime evidence still required |
|---|---|---|
| AC-01 | Provenance/adapted-state invariant | End-to-end fixture and human privacy review |
| AC-02 | Public contract only | Editable UI checkpoints and human review |
| AC-03 | Asset statement/evidence checker | Adversarial output and source-trace review |
| AC-04 | Resume fixture contract | Persistence/restart integration test |
| AC-05 | Five-route structural and expected-state checker | Routed output review |
| AC-06 | Public contract only | Cross-render consistency/browser test |
| AC-07/08 | Privacy fixture/expected contract | Permission-state and human privacy tests |
| AC-09/10 | Correction/conflict/incomplete contracts | Multi-turn E2E behavior |
| AC-11 | Manifest/local-proof requirements | W7900/ROCm/vLLM trace |
| AC-12..16 | Public quality contract | Product integration, language and interaction tests |
| AC-17 | Deterministic progress/ETA checker | State-to-UI integration |
| AC-18 | Loop contract | Recorded complete Track 2 scenario |
| AC-19 | Manifest validator | Real complete run manifest |
| AC-20 | Frozen comparison/declared-change checker | Repeated baseline/candidate runs and statistics |
| AC-21 | Metric definitions and summary helper | Product instrumentation/moderated use |
| AC-22 | PR metadata checker/template | Completed PR evidence pack |
| AC-23/24 | Disclosure scan and sign-off process | Private suite and owner decision |
| AC-25 | Seven-category inventory checker | Private same-gate variants |
| AC-26/29 | Prospective candidate-plan validator | Timestamped approval and retained history |
| AC-27/28 | Promotion guardrail contract | Quality regression, concurrency and overload runs |
| AC-30 | Public retrieval-phase trace schema/checker and M4/M5 gate | Runtime denial/allow trace, no-match path and current-asset non-contamination review |

No row may become product `PASS` from code inspection alone. Update this map
when a real verification method is added; keep private case contents and exact
thresholds out of it.
