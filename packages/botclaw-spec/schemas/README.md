# BotClaw JSON Schemas

v0.9 draft freezes the currently implemented contracts and adds safety
placeholders for M16+ runtime work.

- `joint_update.schema.json` — 实时关节推流
- `robot_state.schema.json` — 快照态
- `device_capabilities.schema.json` — 设备能力声明
- `dataset_episode.schema.json` — 录制片段
- `training_job.schema.json` — 训练任务
- `skill.schema.json` — Skill registry entry
- `safety_envelope.schema.json` — 运行时安全边界占位
- `runtime_lease.schema.json` — 硬件控制租约占位
- `skill_run_event.schema.json` — Skill 执行事件占位

所有 schema 使用 JSON Schema Draft 2020-12.
