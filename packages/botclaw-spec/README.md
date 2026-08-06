# @botversex/botclaw-spec

BotClaw 契约层的"唯一真源 (single source of truth)". 3 份对齐产物:

| 形态 | 目录 | 消费方 |
| --- | --- | --- |
| JSON Schema | `schemas/` | 跨语言校验器 / OpenAPI 生成 |
| TypeScript | `ts/` | `apps/web` (和未来 sdk-ts) |
| Python Pydantic | `python/botclaw_spec/` | `apps/api` / `apps/realtime` / sdk-py |

## 现状 (v0.9 draft)

BotClaw v0.9 是**字段冻结草案**，不是对外标准发布版：

- 已有参考实现：`so101`、`reachy_mini`
- 已对齐：Skill Registry、DeviceCapabilities、JointUpdate、DatasetEpisode、TrainingJob
- 新增占位：Safety Primitives、Verb Taxonomy、Workflow Node Taxonomy
- 不承诺：跨硬件 100% 复用、完整 Safety Runtime、商标认证体系

Freeze point:
- `BotClaw-v0.9-freeze-point.md` marks the current schema freeze boundary.
- Any "完成/可发布" claim must pass `scripts/botclaw-acceptance-gate.sh`.

## 开发原则

1. **Schema 优先**: 任何字段变更先改 `schemas/*.schema.json`, 再手工同步 TS 和 Python
2. **向后兼容**: 小版本 bump 只允许新增可选字段
3. **版本号**: `BOTCLAW_SPEC_VERSION` 同步存在 TS/Python 两侧

## Safety Primitives (v0.9 placeholders)

BotClaw borrows four safety primitives from the TidyBot architecture and defines
their protocol contracts before implementing full runtime behavior:

| Primitive | Contract | v0.9 Meaning |
| --- | --- | --- |
| Rewind | future event replay log | Record enough run events to diagnose and eventually roll back failed motion |
| Lease System | `schemas/runtime_lease.schema.json` | Only one user/workflow/agent controls a runtime at once |
| Safety Envelope | `schemas/safety_envelope.schema.json` | Runtime-advertised joint/workspace bounds and response mode |
| Auto-hold | `schemas/skill_run_event.schema.json` | Failures must surface as explicit events; runtime implementation later decides hold/home behavior |

v0.9 only freezes the schemas. Full enforcement belongs to the M16+ runtime
safety layer.

## Taxonomies

- `docs/verb_taxonomy.md` defines the v0.9 standard verbs.
- `docs/workflow_node_taxonomy.md` aligns BotverseX workflow categories with
  Qualia Studio buckets.
