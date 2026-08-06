# Core Runtime

## 实现位置

- `src/alphanoah_a1/runtime.py`
- `src/alphanoah_a1/models.py`
- `src/alphanoah_a1/state_machine.py`
- `src/alphanoah_a1/storage/sqlite_store.py`

## 核心对象

| 对象 | 当前职责 | 持久化 |
|---|---|---|
| Event | 现实输入及闭环主状态 | `events` |
| Decision | 对 Event 的规则/模型形状判断 | `decisions` |
| HumanReview | 明确的人工结果 | `human_reviews` |
| Task | 经批准生成的整改任务 | `tasks` |
| Evidence | 执行结果引用及验证状态 | `evidence` |
| Review | 任务完成后的复查 | `post_reviews` |
| AuditRecord | 所有创建、转换、拒绝和恢复 | `audit_records` |
| SkillDefinition | Skill 契约和版本 | 不持久化；定义在 `skill.py` |

所有对象使用唯一 UUID 前缀 ID。Event 额外拥有 `trace_id`，其他对象通过关联关系进入同一审计链。

## 运行顺序

```text
create_event
→ analyze_event
→ submit_human_review
→ create_task
→ start_task
→ submit_evidence
→ begin_review
→ review_task
```

每个外部等待点之前已有 SQLite 状态。程序重启后可按 ID 继续读取，不依赖进程内对象。

## 一致性

- Event 转换在 `BEGIN IMMEDIATE` 事务中检查 expected state；
- Event 状态更新与对应 AuditRecord 原子提交；
- evidence idempotency key 与 Evidence 在同一事务登记；
- 非法操作写入 `operation_rejected`；
- SQLite connection 每次操作后显式关闭；
- `reset()` 只清空调用者明确选择的数据库。

## 状态

| 分类 | 内容 |
|---|---|
| Implemented | 运行方法、状态检查、SQLite、快照、trace timeline |
| Partially implemented | 跨多个对象的业务操作不是单一数据库大事务 |
| Designed only | 多进程队列、Web API、权限、迁移工具 |
| Future work | 分布式执行、租户隔离、远程同步 |
