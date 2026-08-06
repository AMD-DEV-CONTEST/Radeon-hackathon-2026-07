# DecisionHook

## 定义

DecisionHook 是确定性控制组件，不是 Prompt，也不让模型直接推进状态。

实现位置：

- `src/alphanoah_a1/decision_hook.py`
- `src/alphanoah_a1/runtime.py`

## 第一阶段：分析后路由

| 条件 | 动作 | Event 目标状态 |
|---|---|---|
| evidence 为空或 confidence < 0.50 | `REQUEST_MORE_EVIDENCE` | `NEEDS_MORE_EVIDENCE` |
| risk level 为 `CRITICAL` | `ESCALATE` | `ESCALATED` |
| `requires_human_review=true` | `REQUEST_HUMAN_REVIEW` | `PENDING_HUMAN_REVIEW` |
| 确定性规则判断无异常 | `AUTO_APPROVE` | `CLOSED`（无任务） |
| 其他未知结果 | 安全默认请求人工 | `PENDING_HUMAN_REVIEW` |

## 第二阶段：人工结果后路由

| HumanReview | DecisionHook 动作 | Event 目标状态 |
|---|---|---|
| `APPROVED` | `CREATE_TASK` | `APPROVED` |
| `REJECTED` | `REJECT` | `REJECTED` |
| `REVISED` | `REQUEST_MORE_EVIDENCE` | `NEEDS_MORE_EVIDENCE` |

`CREATE_TASK` 是授权结果，任务对象仍由 Runtime 单独创建和审计。

## 安全边界

- 人工动作的 reviewer 必须为非空 `human:*` 身份；
- 模型或 `system:*` 不能提交 HumanReview；
- 未批准的 Decision 不能创建任务；
- Hook 只接收已经通过 Skill schema validation 的 Decision；
- 每次路由理由进入 AuditRecord。

## 状态

| 分类 | 内容 |
|---|---|
| Implemented | 所有上述路由、人工后二次路由、拒绝审计 |
| Partially implemented | policy 当前写在代码中，尚无配置版本迁移 |
| Designed only | 组织级审批矩阵、多级审批、过期审批 |
| Future work | 可审查的策略配置和签名发布 |
