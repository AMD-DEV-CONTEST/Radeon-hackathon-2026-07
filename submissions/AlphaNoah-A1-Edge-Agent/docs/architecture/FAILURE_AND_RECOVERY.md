# Failure and Recovery

## 显式失败分支

| 场景 | 行为 | 状态/恢复 |
|---|---|---|
| 分析 payload 缺字段或类型错误 | 抛出 `InvalidAnalysisOutput` 并审计 | `NEW→FAILED→NEW` 可重新发起 |
| 非法状态操作 | 拒绝并写 `operation_rejected` | 状态不变 |
| 人工拒绝 | 保存 HumanReview | `PENDING_HUMAN_REVIEW→REJECTED` |
| 人工要求修改 | 保存 revision request | `PENDING_HUMAN_REVIEW→NEEDS_MORE_EVIDENCE` |
| 证据不足 | Review 标记不足 | `UNDER_REVIEW→NEEDS_MORE_EVIDENCE→IN_PROGRESS` |
| 重复证据提交 | idempotency key 拒绝 | 只保留首次 Evidence |
| 复查失败 | 保存失败 Review | `UNDER_REVIEW→FAILED` |
| 并发旧状态写入 | expected state 不匹配 | `ConcurrentUpdateError`，不覆盖新状态 |
| 程序重启 | 重新打开同一 SQLite | 通过 ID/trace 恢复 |

## 终态

`CLOSED`、`REJECTED`、`CANCELLED` 和 `ESCALATED` 当前不能自动离开。需要新业务操作时必须先增加显式转换、审计和测试。

## 事务边界

已保证：

- Event 状态与 Event AuditRecord 原子提交；
- idempotency key 与 Evidence 原子提交；
- 连接关闭和异常 rollback。

未完全保证：

- 一个跨 Decision、Task、Event 的高层操作不是单个大事务；
- 当前没有崩溃后自动补偿器；
- 当前没有数据库迁移或备份工具。

## 状态

| 分类 | 内容 |
|---|---|
| Implemented | 上表主要失败路径、恢复、拒绝审计 |
| Partially implemented | 分析失败重试、补证据恢复 |
| Designed only | 自动补偿、dead-letter queue、运维恢复 CLI |
| Future work | 多节点容错和生产灾备 |
