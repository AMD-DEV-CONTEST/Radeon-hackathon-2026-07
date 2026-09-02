# Data Flow

## 主流程

```text
examples/synthetic_food_sop_event.json
→ normalized_input
→ Event
→ FoodColdHoldingSkill
→ AnalysisResult
→ Decision
→ DecisionHook
→ HumanReview
→ Task
→ examples/synthetic_corrective_evidence.json
→ Evidence
→ Review
→ Event CLOSED
→ Audit timeline
```

## 当前工业分析路径

```text
same-host QR/local form or synthetic fixture
→ Event / NEW
→ explicit analyze event CLI
→ optional deterministic SkillResolver
→ bounded SkillContext
→ optional KnowledgeQuery / KnowledgeContext
→ OllamaAnalysisProvider
→ validated AnalysisResult
→ Decision
→ DecisionHook
→ PENDING_HUMAN_REVIEW
→ explicit ResponsibilityDirectory lookup
→ Notification / CREATED
```

QR POST 与模型调用是两个独立动作。当前没有后台队列、自动批准、自动 Task
或外部消息发送。Task 04 的责任匹配和本地 outbox 是显式的 post-Decision
操作。

## 节点契约

| 节点 | 输入 | 输出 | 失败处理 | 持久化 |
|---|---|---|---|---|
| Ingest | fixture mapping | Event | 不创建不完整事件外的执行动作 | Event + audit |
| Normalize | fixture `normalized_input` | typed mapping | Skill 校验失败 | Event remains/reaches FAILED |
| Analyze | normalized mapping | AnalysisResult | `InvalidAnalysisOutput` | Decision only after valid output |
| Skill resolve | Event type + `metadata.asset_type` | SkillContext | 显式无匹配/冲突；不调用模型、不创建 Decision | 解析结果进入现有 audit metadata |
| Hook | Decision | HookResult | 安全默认人工 | Decision + Event audit |
| Responsibility | Event + local directory | ResponsibilityAssignment | 无匹配返回 `UNASSIGNED` | 配置只读 |
| Outbox | Assignment + Decision | Notification / `CREATED` | decision_id 幂等 | Notification + audit |
| Human | explicit operator input | HumanReview | 非 human actor 拒绝 | HumanReview + Decision/Event |
| Task | approved Decision | Task | 非 APPROVED 拒绝 | Task + Event |
| Evidence | synthetic reference | Evidence | idempotency 拒绝重复 | Evidence + Task/Event |
| Review | Evidence list | Review | more/fail branches | Review + Task/Event |
| Archive | trace ID | snapshot/timeline | not found 明确报错 | SQLite |

## 本地与外部边界

确定性 Food Skill 流程和 QR POST 没有网络调用、云 API、Ollama 调用或模型
权重读取。Task 03 另有一个操作者显式触发、仅允许 loopback 的 Ollama
Analysis Provider 路径；它不会由 QR POST 自动调用。Task 03B 已记录一次
AMD Linux + `qwen3.5:9b` 直接结构化分析。

## 状态

| 分类 | 内容 |
|---|---|
| Implemented | 结构化 JSON → SQLite 闭环 |
| Partially implemented | raw input 只保存引用，没有文件内容管理 |
| Implemented and directly verified | 最小 Ollama payload、结构化输出校验、显式分析 CLI、一次 AMD Linux 模型运行 |
| Implemented and tested | 确定性负责人匹配、`UNASSIGNED` fallback、本地 Notification outbox |
| Partially implemented | GPU 只有单次前后快照，不是持续指标或 benchmark |
| Designed only | 图片上传、外部消息发送、物理手机访问、AMD metrics panel |
| Future work | 视频流、传感器流、企业数据连接器 |
