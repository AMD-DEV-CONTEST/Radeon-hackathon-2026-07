case_id: CM-P61-FAILURE-001
date: 2026-06-05
phase: Phase 6.1 dark-line construction
severity: medium
category: verification_gap

## Summary

Phase 6.1 Layers 2-5 were all marked "done" by agents, but
post-audit found only L5 (deterministic routing) actually worked.

## What was wrong

| Layer | "Done" based on | Reality |
|-------|----------------|---------|
| L2 Intent Packet | git commit | validate_intent_packet() placed in wrong function via naive content.replace() — never executed |
| L3 Decomposition DAG | 358-line design doc | decompose() never called from any pipeline. Zero runtime code |
| L4 Participants | 254-line participants.py | imported nowhere. Dead code |
| L5 Deterministic Routing | verified in production | ✅ ACTUALLY WORKED |

## Root causes

1. **"git commit = done" fallacy**: acceptance criteria defaulted
   to "file exists in repo" instead of "pipeline runs end-to-end".

2. **No e2e verification gate**: no agent ran `POST /tasks` before
   marking complete. ILS-G005 (completion evidence) not enforced.

3. **Task description misdirection**: L3/L4 asked for "design docs",
   SCC produced docs. Different outcome had description said
   "wire decompose() into create_task pipeline."

4. **content.replace() fragility**: 3 rounds of patches kept placing
   code in wrong functions because string matching found wrong anchor.

## Gate violations triggered

- ILS-G001: intent_packet validation existed but at wrong location.
  False sense of enforcement.
- ILS-G005: tasks marked done without operational evidence.

## Correction applied

- create_task: intent_packet validation + on_intake hook wired correctly
- notify_gateway_task_dispatch: on_dispatch hook call inserted
- complete_task: on_completion hook call inserted

## Still open

- decompose() not called from create_task (L3 not wired)
- participants.py not imported by routing code (L4 not wired)

## See also

- ILS-R006: E2E verification before marking complete
