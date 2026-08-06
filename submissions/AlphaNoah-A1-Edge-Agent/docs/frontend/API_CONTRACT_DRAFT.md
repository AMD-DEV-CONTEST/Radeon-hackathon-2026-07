# AlphaNoah Frontend API Contract Draft

## 1. 阅读规则

本文严格区分：

- **CURRENT**：当前仓库已实现并有测试的 HTTP contract；
- **RUNTIME ONLY**：Runtime/Store 中存在，但当前 HTTP API 未公开；
- **DRAFT / GAP**：前端需要的建议 contract，当前不可调用。

任何 DRAFT endpoint、字段或状态都不能在前端被当作已实现能力。F00 不改变 API。

## 2. 当前传输契约（CURRENT）

### 2.1 基础边界

- Origin：仅 `http://127.0.0.1:<port>`；
- 默认端口：8090；
- API prefix：`/api`；
- Method：只有已列出的 GET/POST；其他 method 返回 405；
- CORS：未启用，OPTIONS 返回 405；
- Query：所有 query parameter 当前都返回 400；
- POST body：UTF-8 `application/json`；
- 必须且只能有一个 `Content-Type` 和一个十进制 `Content-Length`；
- 不接受 `Transfer-Encoding`；
- body 最大 16 KiB；
- request target 最大 2048 characters；
- 重复 JSON key、未知字段和非法控制字符会被拒绝；
- response：`application/json; charset=utf-8`、`Cache-Control: no-store`、
  `X-Content-Type-Options: nosniff`。

ID 必须匹配当前形态：

```text
event_<32 lowercase hex>
task_<32 lowercase hex>
```

### 2.2 错误结构

```ts
interface ApiError {
  error_code:
    | "EVENT_NOT_FOUND"
    | "TASK_NOT_FOUND"
    | "INVALID_REQUEST"
    | "HUMAN_REVIEW_REQUIRED"
    | "PROVIDER_UNAVAILABLE"
    | "ANALYSIS_NOT_AVAILABLE"
    | "ANALYSIS_FAILED"
    | "INTERNAL_ERROR";
  message: string;
}
```

已知 status 使用：

| HTTP | 典型 error |
|---|---|
| 400 | INVALID_REQUEST |
| 404 | EVENT_NOT_FOUND、TASK_NOT_FOUND 或未知 route 的 INVALID_REQUEST |
| 405 | 不支持 method 的 INVALID_REQUEST |
| 409 | ANALYSIS_NOT_AVAILABLE、HUMAN_REVIEW_REQUIRED 或非法/重复操作 |
| 411 | 缺少 Content-Length |
| 413 | body 过大 |
| 414 | request target 过长 |
| 415 | 非 UTF-8 application/json |
| 422 | ANALYSIS_FAILED |
| 500 | INTERNAL_ERROR |
| 503 | PROVIDER_UNAVAILABLE |

前端必须按 `error_code` 分支，不能依赖英文 message 做业务判断。

## 3. 当前 endpoint（CURRENT）

### 3.1 `POST /api/events`

精确 request：

```ts
interface CreateEventRequest {
  location: "A08";
  asset_type: "air_conditioner";
  description: string; // trimmed, 1..2000
}
```

`location` 最大 200、`asset_type` 最大 100，但当前场景只接受上面的精确值。

Response `201`：

```ts
interface CreateEventResponse {
  event_id: string;
  status: "NEW";
}
```

该 endpoint 进入现有 QR/Golden Path/Runtime 创建 Event；不执行分析。

### 3.2 `GET /api/events/{event_id}`

Response `200`：

```ts
interface AnalysisProjection {
  detected_issue: string;
  decision_type: string;
  reasoning_summary: string;
  evidence: string[];
  model_or_rule: string;
  confidence: number;
  requires_human_review: boolean;
  severity: "UNKNOWN" | "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
}

interface EventDetailResponse {
  event_id: string;
  status: EventStatus;
  skill_id: string | null;
  skill_version: string | null;
  analysis: AnalysisProjection | null;
  decision: {
    decision_id: string;
    status: DecisionStatus;
    requires_human_review: boolean;
  } | null;
}
```

该 endpoint 不返回 Event timestamp/type/location/asset/description/trace ID。

### 3.3 `GET /api/events/{event_id}/analysis`

Response `200`：

```ts
interface EventAnalysisResponse {
  event_id: string;
  status: EventStatus;
  analysis: AnalysisProjection;
  skill: {
    skill_id: string;
    skill_version: string | null;
  } | null;
  knowledge_sources: string[];
}
```

来源是已持久化 Event、Decision 和 Audit metadata。GET 不触发 Provider、Skill
resolution 或 Knowledge retrieval。没有 Decision 时按 Event 状态返回
ANALYSIS_NOT_AVAILABLE、PROVIDER_UNAVAILABLE 或 ANALYSIS_FAILED。

### 3.4 `POST /api/events/{event_id}/review`

精确 request：

```ts
interface SubmitReviewRequest {
  action: "approve" | "reject";
  comment: string; // trimmed, 1..1000
}
```

Response `200`：

```ts
interface SubmitReviewResponse {
  event_id: string;
  status: "APPROVED" | "REJECTED";
  human_review_id: string;
  outcome: "APPROVED" | "REJECTED";
  decision_id: string;
}
```

当前 Web contract 不支持 Runtime 已有的 `REVISED`。成功 review 不自动创建 Task。

### 3.5 `GET /api/events/{event_id}/task`

Response `200`：

```ts
interface EventTaskResponse {
  event_id: string;
  task: {
    task_id: string;
    status: TaskStatus;
    owner: string;
  } | null;
}
```

该 GET 只读，不创建或启动 Task。

### 3.6 `POST /api/tasks/{task_id}/evidence`

精确 request：

```ts
interface SubmitEvidenceRequest {
  description: string; // trimmed, 1..2000
}
```

Response `201`：

```ts
interface SubmitEvidenceResponse {
  task_id: string;
  task_status: "EVIDENCE_SUBMITTED";
  evidence_id: string;
  validation_status: "PENDING";
}
```

只接受文本描述。后端生成 `synthetic_text_statement` 和固定 synthetic reference；
不接受文件、路径或 attachment。Task 必须已由现有流程进入 `IN_PROGRESS`。

### 3.7 `GET /api/events/{event_id}/timeline`

Response `200` 是数组：

```ts
interface TimelineEntry {
  sequence: number;       // 1-based persisted audit order
  timestamp: string;
  action: string;
  entity_type: string;
  entity_id: string;
  status: string;
}

type EventTimelineResponse = TimelineEntry[];
```

不返回 actor、transition summary、safe metadata 或完整 Audit details。

## 4. Runtime 对象与 HTTP 投影

### 4.1 Event

`RUNTIME ONLY` 完整字段：

| 字段 | 类型 |
|---|---|
| event_id | string |
| source | string |
| timestamp | ISO-8601 string |
| raw_input_ref | string |
| normalized_input | JSON object |
| detected_issue | string |
| confidence | number |
| severity | string |
| status | EventStatus |
| trace_id | string |
| event_type | string |
| location | string |
| asset_id | string |
| reporter | string |
| description | string |
| attachments | string[] |
| metadata | JSON object |

当前 HTTP 直接公开 `event_id/status`；`detected_issue/confidence/severity` 只在有
Decision 时进入 AnalysisProjection。其余事实没有安全 Web 投影。

### 4.2 Analysis

`AnalysisResult` 字段：

```text
detected_issue
decision_type
reasoning_summary
evidence[]
model_or_rule
confidence
requires_human_review
severity
```

AnalysisResult 不是独立 SQLite table。成功分析时：

- Event 保存 detected_issue/confidence/severity；
- Decision 保存 decision_type/reasoning/evidence/model_or_rule/confidence/
  requires_human_review/risk_level/status；
- Skill 和 knowledge provenance 进入 Audit details 的安全 metadata。

前端不能假设存在 analysis ID 或 analysis status。

### 4.3 Decision

`RUNTIME ONLY` 完整字段：

```text
decision_id
event_id
decision_type
reasoning_summary
evidence[]
model_or_rule
confidence
requires_human_review
status
risk_level
```

当前 HTTP detail 公开 ID/status/requires_human_review；其余经 AnalysisProjection
公开。

### 4.4 Task

`RUNTIME ONLY` 完整字段：

```text
task_id
source_decision_id
task_type
assignee
description
expected_result
deadline
status
```

当前 HTTP 只公开 task_id/status/owner（assignee）。

### 4.5 Evidence

`RUNTIME ONLY` 完整字段：

```text
evidence_id
task_id
type
file_or_data_ref
submitted_by
timestamp
validation_status
description
```

当前 HTTP 只有提交 response，没有 GET/list。`file_or_data_ref` 不应直接公开本机
路径；未来必须沿用 safe reference policy。

### 4.6 Audit

`RUNTIME ONLY` 完整字段：

```text
audit_id
actor
action
object_type
object_id
previous_state
new_state
timestamp
trace_id
details
```

当前 timeline 只公开 sequence/timestamp/action/entity_type/entity_id/status。
前端不应请求完整 details；其中可能包含内部模型 metadata。

### 4.7 其他相关对象

- HumanReview：Runtime 有 reviewer/outcome/comment/timestamp/revision_request；
  当前 HTTP 只在写 response 返回 ID/outcome。
- Notification：Runtime 有 durable local outbox，状态为 CREATED/DELIVERED/FAILED；
  当前无 HTTP read endpoint，且 CREATED 不代表已投递。
- Review：Runtime 有 evidence post-review/closure 记录；当前无 HTTP read/write
  endpoint。
- SkillDefinition：Runtime 有 active/deprecated、安全匹配字段和 analysis
  instructions；当前只从 Event analysis 暴露 skill ID/version。
- ProviderDiscoveryResult：已有只读 discovery status；当前无 HTTP endpoint。

## 5. 前端所需 API 缺口

| 缺口 | 阻塞的 UI | 风险 |
|---|---|---|
| Event 列表/分页/排序 | Activity stream、轮询 | 不能从已知单个 ID发现事件 |
| Event facts 安全投影 | EventSummary、行动面板 | 当前 detail 没有位置、资产、时间、描述 |
| 一致的 action-card read model | 展开面板 | 多请求之间可能看到不同版本 |
| Notification 列表 | Noah Pulse queue | Runtime 有 outbox，HTTP 不公开 |
| Task 完整安全摘要 | 行动面板 | 描述、预期结果、deadline 缺失 |
| Evidence 列表/安全摘要 | 任务证据 | 当前只能 POST |
| HumanReview/PostReview 摘要 | 确认与复查历史 | timeline 不能呈现完整结构化结果 |
| Workspace freshness/version | 有限轮询 | 无 cursor/updated-at/ETag |
| health endpoint | SystemHealth | 无 Web/SQLite aggregate health |
| Responsibility/DigitalRole read API | Management | 只有本地 JSON directory |
| Skill list API | Management | 只有 Python definitions |
| Provider discovery/config read API | Management | 只有 CLI/内部 Python |
| Edge node 模型/API | Management | 当前完全不存在 |
| Conversation/command API | 上下文输入 | 当前完全不存在 |
| 静态托管/fallback | 浏览器入口 | 当前只返回 JSON |

另外，当前全局拒绝 query parameter。新增分页 endpoint 前必须让 handler 只对明确
支持的 route 解析 allowlisted query，不能全局放开任意 query。

## 6. 建议的最小增量契约（DRAFT / GAP）

以下只用于拆分后续任务，不是当前 API。

### 6.1 Workspace Event feed

```text
GET /api/workspace/events?limit=<1..100>&cursor=<opaque>
```

```ts
interface WorkspaceEventsDraft {
  items: EventSummary[];
  next_cursor: string | null;
  observed_at: string;
}
```

要求：

- cursor opaque；
- 默认稳定排序为 timestamp desc + event_id；
- GET 无副作用；
- 字段是 Event 的安全投影，不读取 raw_input_ref、arbitrary metadata 或附件路径。

### 6.2 Action card

```text
GET /api/events/{event_id}/action-card
```

返回 `AgentActionCard` 的 snake_case wire shape。建议由应用 read service 在一次
读取边界内组合 Event/Decision/HumanReview/Task/Evidence/Review/Audit 的安全投影。
它不能调用 Provider 或改变状态。

若后端暂不提供 aggregate endpoint，前端可以组合现有 detail/analysis/task/
timeline，但必须把缺失字段显示为 unavailable，不能生成占位业务事实。

### 6.3 Notice feed

```text
GET /api/workspace/notices?limit=<1..100>&cursor=<opaque>
```

返回 Notification 的安全投影和必要 Event/Decision 状态。read/dismiss 不在第一版
写回 Notification status。

### 6.4 Management reads

```text
GET /api/management/digital-roles
GET /api/management/skills
GET /api/management/providers
GET /api/management/edge-nodes
GET /api/system/health
```

每个 endpoint 在对应 Runtime 模型/配置存在后才实现。Edge node 不得在没有正式
模型时返回 synthetic 列表。Provider response 不包含 secret value，只能返回
环境变量名或 `credential_configured: boolean`。

### 6.5 Capabilities

Action card 可以返回确定性的 capabilities：

```ts
interface ActionCapabilitiesDraft {
  can_submit_review: boolean;
  can_submit_text_evidence: boolean;
  can_use_context_conversation: boolean;
}
```

它只用于 UI enable/disable；写 endpoint 仍必须重新做 Runtime 状态校验。

## 7. 不建议在第一阶段新增的 API

- 通用 SQL/snapshot dump endpoint；
- 完整 Audit details endpoint；
- prompt、原始模型响应或 analysis instructions endpoint；
- 浏览器直连 Provider；
- 任意文件路径/下载 endpoint；
- 自动 approve、自动 Task 创建或设备控制；
- WebSocket；
- Skill/Prompt 编辑；
- 用户/权限管理；
- 多 Agent 群聊。

## 8. 客户端契约规则

- wire types 保持后端 snake_case，mapper 转换为 UI camelCase；
- mapper 是纯函数并有 fixture tests；
- unknown enum/status 显示为 unsupported，不能默认映射为正常；
- 所有 timestamp 按 ISO-8601 解析并保留原值用于审计显示；
- Event/Decision/Task 状态只读；
- POST 禁止自动重试；网络结果不明时先重新 GET；
- GET 可有限退避重试，但不触发副作用；
- API error 按 error_code 分类；
- 不把 404 API route 交给 SPA fallback；
- UI optimistic state 只用于按钮 loading，不提前改变业务状态。
