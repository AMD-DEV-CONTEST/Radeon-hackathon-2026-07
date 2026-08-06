# Audit and History

## AuditRecord

每条记录至少包含：

```text
actor
action
object_type
object_id
previous_state
new_state
timestamp
trace_id
```

实现额外保存 `audit_id` 和结构化 `details`。

## 当前记录范围

- Event、Decision、HumanReview、Task、Evidence、Review 的创建；
- Event 和 Task 状态变化；
- DecisionHook 路由；
- 人工结果；
- 非法操作和重复提交拒绝；
- 分析格式错误和失败后重新发起。

Event 状态更新与对应 AuditRecord 在一个 SQLite 事务内提交。

## 历史重建

`AlphaNoahRuntime.snapshot(event_id)` 返回：

- Event；
- 关联 Decisions；
- HumanReviews；
- Tasks；
- Evidence；
- Post-task Reviews；
- 按写入顺序排列的完整审计记录。

CLI 按 `trace_id` 输出 actor、动作、对象和前后状态。程序重启不会丢失记录。

## 数据保留边界

当前只保存合成结构化数据和引用，不保存真实图片、真实 SOP 或客户资料。数据库文件由 `.gitignore` 排除。

## 状态

| 分类 | 内容 |
|---|---|
| Implemented | SQLite audit、trace timeline、快照、重启恢复 |
| Partially implemented | 审计防篡改只依赖本地数据库，没有 hash chain |
| Designed only | 导出报告、保留期限、签名、备份 |
| Future work | append-only 归档和外部验证锚点 |
