# Human in the Loop

## 当前确认点

异常 Decision 到达 `PENDING_HUMAN_REVIEW` 后，只有显式 HumanReview 才能继续：

```text
PENDING_HUMAN_REVIEW
├── APPROVED → task creation authorized
├── REJECTED → terminal
└── REVISED → NEEDS_MORE_EVIDENCE
```

## HumanReview 记录

| 字段 | 含义 |
|---|---|
| `human_review_id` | 唯一记录 |
| `reviewer` | 必须为非空 `human:*` actor |
| `decision_id` | 被审查 Decision |
| `outcome` | APPROVED / REJECTED / REVISED |
| `comment` | 人工说明 |
| `timestamp` | UTC 时间 |
| `revision_request` | REVISED 时必填 |

CLI 的 `--decision approve|reject` 是操作者的显式输入，不是模型生成的批准。省略参数时程序交互询问。

## 防止“模型假装人工”

- `system:*`、`model:*` 或空身份不能提交 HumanReview；
- DecisionHook 不能自行生成 HumanReview；
- 人工结果与后续 task creation 是两个独立审计动作；
- 任务完成后的规则复查不能追溯替代前面的人工批准。

## 状态

| 分类 | 内容 |
|---|---|
| Implemented | approve/reject/revise、actor 校验、注释、UTC 时间、审计 |
| Partially implemented | CLI 是明确输入，但没有图形按钮或登录会话 |
| Designed only | 审批超时、多审批人、权限角色、电子签名 |
| Future work | 生产身份系统和不可否认性控制 |
