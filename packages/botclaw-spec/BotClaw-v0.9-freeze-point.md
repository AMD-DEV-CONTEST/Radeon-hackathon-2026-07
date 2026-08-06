# BotClaw v0.9 Freeze Point

Date: 2026-04-26
Status: Active (internal)

This file marks a milestone snapshot for BotClaw v0.9. From this point, schema
fields are frozen unless a documented change process is followed.

## 1) Frozen Scope

The following files are considered the v0.9 contract baseline:

- `packages/botclaw-spec/schemas/skill.schema.json`
- `packages/botclaw-spec/schemas/device_capabilities.schema.json`
- `packages/botclaw-spec/schemas/joint_update.schema.json`
- `packages/botclaw-spec/schemas/robot_state.schema.json`
- `packages/botclaw-spec/schemas/dataset_episode.schema.json`
- `packages/botclaw-spec/schemas/training_job.schema.json`
- `packages/botclaw-spec/schemas/safety_envelope.schema.json`
- `packages/botclaw-spec/schemas/runtime_lease.schema.json`
- `packages/botclaw-spec/schemas/skill_run_event.schema.json`
- `packages/botclaw-spec/python/botclaw_spec/__init__.py`
- `packages/botclaw-spec/ts/index.ts`
- `apps/api/app/data/skills_seed.json`

## 2) Freeze Rules

1. No direct field changes in frozen schemas without updating:
   - `packages/botclaw-spec/python/botclaw_spec/__init__.py`
   - `packages/botclaw-spec/ts/index.ts`
   - `packages/botclaw-spec/BotClaw-v0.9-draft.md`
2. Any breaking change must be recorded as a v1.0 candidate, not patched into
   v0.9 silently.
3. Every "done" claim must pass the BotClaw gate script:
   - `scripts/botclaw-acceptance-gate.sh`

## 3) Allowed Change Types During Freeze

- Documentation improvements
- Non-breaking optional fields with explicit rationale
- Runtime implementations that consume the frozen contracts
- Test and validation script enhancements

## 4) Out of Scope for v0.9

- Full TidyBot safety runtime behavior (only schemas are frozen)
- Full Qualia Studio node parity
- Public certification/trademark process

## 5) Re-open Procedure

To modify frozen contract fields:

1. Open a change note in `packages/botclaw-spec/docs/`.
2. Classify as `non_breaking` or `breaking`.
3. Update schema + Python + TS in one batch.
4. Re-run `scripts/botclaw-acceptance-gate.sh`.
5. Update this freeze file with a new date and summary.
