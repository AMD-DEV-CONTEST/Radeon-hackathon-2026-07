# AlphaNoah Frontend Runtime Boundary

> F03-A Integration Architecture Review
> 状态：实现前边界设计；本文件不改变 Runtime、API、SQLite、Python 服务或前端行为。

## 0. 结论

当前仓库已经有一条受控的单事件 Runtime 黄金路径，也有一个 localhost-only
JSON Web Adapter；但它还不是 Workspace Read API。

现有读取能力以已知 `event_id` 为入口，只能分别读取 Event 安全摘要、Analysis、
Task 和 Timeline。它不能列出事件，不能生成 Workspace 聚合快照，也不能读取
Notification、Evidence 明细或系统健康。`AlphaNoahRuntime.snapshot()` 虽然能在
Python 进程内组装完整生命周期对象，但它不是公开 HTTP 契约，而且包含不适合直接
暴露的内部数据。

因此 F03-A 应建立下列单向边界，而不让 React 直接消费 Runtime JSON：

```text
Runtime / Web Adapter JSON
            |
            v
features/runtime/api       只声明、校验传输 DTO
            |
            v
features/runtime/adapter   纯函数映射；保留原始状态
            |
            v
features/runtime/models    Workspace View Model
            |
            v
WorkspaceProvider          Mock / future HTTP 可替换
            |
            v
features/runtime/hooks     React 生命周期与选择器
            |
            v
Workspace / Noah Pulse / Agent Action Panel
```

核心约束：

1. 后端 `EventStatus` 是唯一业务状态事实；前端不得维护另一张迁移表。
2. 前端 lifecycle、severity、notice priority 只是可重算的显示投影，不能写回
   Runtime。
3. `expanded` 是 Noah Pulse 的本地交互状态，不是 Runtime 或 Notification
   状态。
4. Mock 与 HTTP Provider 必须返回同一个 View Model，而不是让组件分别理解两套
   数据。
5. 当前 API 不足以构建真实 Workspace 时，必须显示 unknown/unavailable 或继续
  使用 Mock；不得捏造现场、健康、时间、事实或任务数据。

## 1. 审计范围与证据

本审计以实际实现为准，主要证据如下：

- `src/alphanoah_a1/web_api.py`：HTTP 路由、请求限制、响应头、启动/关闭；
- `src/alphanoah_a1/web_adapter.py`：公开 JSON 投影与稳定错误；
- `src/alphanoah_a1/web.py`：独立 QR HTML 申报入口；
- `src/alphanoah_a1/models.py`：Event、Decision、HumanReview、Task、Evidence、
  Review、Audit 数据类与状态枚举；
- `src/alphanoah_a1/notifications.py`：Notification 与本地 outbox；
- `src/alphanoah_a1/runtime.py`：黄金路径、内部 snapshot 与审计记录；
- `src/alphanoah_a1/state_machine.py`：唯一 Event 状态迁移图；
- `src/alphanoah_a1/storage/sqlite_store.py`：持久化关系与读取顺序；
- `src/alphanoah_a1/golden_path.py`：安全 Timeline 投影；
- `tests/test_web_adapter.py`：公开 HTTP 行为与失败契约；
- `frontend/src/types/index.ts`、`frontend/src/mock/index.ts`、
  `frontend/src/app/WorkspacePage.tsx`、
  `frontend/src/layouts/AppShell.tsx`、
  `frontend/src/components/pulse/NoahPulse.tsx` 和
  `frontend/src/components/workspace/AgentActionPanel.tsx`：当前 Mock 驱动 UI。

## 2. 当前真实 HTTP 边界

### 2.1 两个服务不是同一个边界

| 服务 | 实现 | 地址 | 能力 |
|---|---|---|---|
| QR HTML Demo | `web.py` | `127.0.0.1:8080` | `GET/POST /report`；服务端 HTML 表单 |
| JSON Web Adapter | `web_api.py` | `127.0.0.1:8090` | 下列七个 `/api` endpoint |

两者默认使用不同 SQLite 文件：

- QR：`tmp/alphanoah_qr_demo.sqlite3`
- JSON：`tmp/alphanoah_web_api.sqlite3`

如果分别按默认命令启动，它们不是天然共享的 Workspace 数据源。前端集成对象应是
`web_api.py`，不能把 `/report` HTML 当作 JSON API，也不能假设两个默认数据库内容
一致。

JSON 服务：

- 只允许绑定 `127.0.0.1`；
- 使用标准库 `ThreadingHTTPServer`；
- 默认端口 8090；
- 只支持 GET/POST，PUT/PATCH/DELETE/OPTIONS/HEAD 返回 405；
- 查询参数一律拒绝；
- JSON body 上限 16 KiB，只接受 UTF-8 `application/json`；
- 响应带 `Cache-Control: no-store` 与 `X-Content-Type-Options: nosniff`；
- 没有 CORS 响应头；
- 没有静态资源托管或 SPA fallback；
- `KeyboardInterrupt` 后在 `finally` 中 `server_close()`。

前端 Vite 开发服务已配置相对路径 `/api` 代理到
`http://127.0.0.1:8090`。未来 HTTP Provider 应使用相对 `/api`，不应把 8090
散落到组件中。生产环境仍需要单独落实同源静态托管边界；当前 Python JSON 服务
明确输出 “No frontend or authentication”。

### 2.2 公开 endpoint 与精确响应

以下是 `web_api.py` 和 `web_adapter.py` 当前真实契约。示例 TypeScript 仅用于描述
wire DTO，不代表已经存在这些前端文件。

#### `POST /api/events`

请求必须且只能包含：

```ts
interface CreateEventRequest {
  location: "A08";
  asset_type: "air_conditioner";
  description: string;
}
```

当前是受限餐厅空调 Demo，不是通用 Event 创建端点。成功为 201：

```ts
interface CreateEventResponse {
  event_id: string;
  status: "NEW";
}
```

#### `GET /api/events/{event_id}`

成功为 200：

```ts
interface ApiAnalysisProjection {
  detected_issue: string;
  decision_type: string;
  reasoning_summary: string;
  evidence: string[];
  model_or_rule: string;
  confidence: number;
  requires_human_review: boolean;
  severity: string;
}

interface ApiEventDetailResponse {
  event_id: string;
  status: string;
  skill_id: string | null;
  skill_version: string | null;
  analysis: ApiAnalysisProjection | null;
  decision: {
    decision_id: string;
    status: string;
    requires_human_review: boolean;
  } | null;
}
```

这个响应没有 Event 的 `timestamp`、`source`、`event_type`、`location`、
`asset_id`、`reporter`、`description`、`severity`、`trace_id` 或附件。前端不能从
该响应恢复当前 Mock 中的现场名称、事件标题、来源、时间和 facts。

#### `GET /api/events/{event_id}/analysis`

只读取已有持久化结果，不触发 Provider。成功为 200：

```ts
interface ApiAnalysisResponse {
  event_id: string;
  status: string;
  analysis: ApiAnalysisProjection;
  skill: {
    skill_id: string;
    skill_version: string | null;
  } | null;
  knowledge_sources: string[];
}
```

Event 未分析时为 409 `ANALYSIS_NOT_AVAILABLE`。Provider transport 失败后为 503
`PROVIDER_UNAVAILABLE`；无效分析输出后为 422 `ANALYSIS_FAILED`。独立运行的
JSON API 没有“开始分析”endpoint；测试通过注入同一个 application 并在 Python
侧调用 `application.analyze(event_id)`。

#### `POST /api/events/{event_id}/review`

请求必须且只能包含：

```ts
interface SubmitReviewRequest {
  action: "approve" | "reject";
  comment: string;
}
```

成功为 200：

```ts
interface SubmitReviewResponse {
  event_id: string;
  status: string;
  human_review_id: string;
  outcome: "APPROVED" | "REJECTED";
  decision_id: string;
}
```

这是写操作，不属于 F03-A 调用范围。当前公开 API 不支持 `REVISED`，即使 Runtime
模型支持该 outcome。

#### `GET /api/events/{event_id}/task`

成功为 200。不存在 Decision 或 Task 都是有效空态：

```ts
interface ApiTaskResponse {
  event_id: string;
  task: {
    task_id: string;
    status: string;
    owner: string;
  } | null;
}
```

响应没有 task type、description、expected result、deadline 或关联 Decision ID。

#### `POST /api/tasks/{task_id}/evidence`

请求必须且只能包含：

```ts
interface SubmitEvidenceRequest {
  description: string;
}
```

成功为 201：

```ts
interface SubmitEvidenceResponse {
  task_id: string;
  task_status: string;
  evidence_id: string;
  validation_status: string;
}
```

这是写操作，不属于 F03-A 调用范围。它只创建 synthetic text evidence，不是上传
接口。

#### `GET /api/events/{event_id}/timeline`

成功为 200，根响应是数组：

```ts
interface ApiTimelineEntry {
  sequence: number;
  timestamp: string;
  action: string;
  entity_type: string;
  entity_id: string;
  status: string;
}

type ApiTimelineResponse = ApiTimelineEntry[];
```

`sequence` 是该 Event trace 内按持久化 Audit 顺序重新从 1 编号。公开投影有意不
暴露 `actor`、`summary`、`details` 或 model metadata。

### 2.3 公开错误

所有受控 JSON 错误使用：

```ts
interface ApiErrorResponse {
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

前端不得依据英文 `message` 做逻辑判断，只能使用 HTTP status 与 `error_code`。
未知 `error_code` 必须进入通用兼容分支。

### 2.4 不是公开 API 的能力

`AlphaNoahRuntime.snapshot(event_id)` 会在 Python 进程内返回：

```text
event
decisions[]
notifications[]
human_reviews[]
tasks[]
evidence[]
reviews[]
audit[]
```

它是内部诊断/测试级组合，不是 HTTP endpoint。它包含 actor、reporter、原始引用、
metadata、Audit details、recipient 等数据，不能绕过 Web Adapter 直接序列化给
浏览器。SQLite `list_events()` 同样是内部存储 API，不是公开接口。

## 3. 当前 Runtime 数据事实

### 3.1 Event

`models.Event` 的持久化字段：

| 字段 | 类型/含义 |
|---|---|
| `event_id` | string，当前 ID 形状为 `event_` + 32 位 hex |
| `source` | string |
| `timestamp` | string |
| `raw_input_ref` | string |
| `normalized_input` | JSON object |
| `detected_issue` | string |
| `confidence` | number |
| `severity` | string；创建时 `UNKNOWN` |
| `status` | `EventStatus` |
| `trace_id` | string |
| `event_type` | string；默认 `legacy_observation` |
| `location` | string |
| `asset_id` | string |
| `reporter` | string |
| `description` | string |
| `attachments` | string[] |
| `metadata` | JSON object |

真实 `EventStatus` 全集：

```text
NEW
ANALYZED
PENDING_HUMAN_REVIEW
APPROVED
TASK_CREATED
IN_PROGRESS
EVIDENCE_SUBMITTED
UNDER_REVIEW
CLOSED
REJECTED
NEEDS_MORE_EVIDENCE
FAILED
CANCELLED
ESCALATED
```

唯一迁移图在 `state_machine.py:ALLOWED_TRANSITIONS`。前端只展示当前值和派生阶段，
不得复制迁移规则、预测下一状态或在本地执行迁移。

### 3.2 Analysis 与 Decision

`AnalysisResult` 是 Runtime 输入结果，不单独持久化：

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

Runtime 把其中一部分写回 Event，并创建持久化 `Decision`：

| Decision 字段 | 类型 |
|---|---|
| `decision_id` | string |
| `event_id` | string |
| `decision_type` | string |
| `reasoning_summary` | string |
| `evidence` | string[] |
| `model_or_rule` | string |
| `confidence` | number |
| `requires_human_review` | boolean |
| `status` | `DecisionStatus` |
| `risk_level` | string；默认 `UNKNOWN` |

`DecisionStatus`：

```text
PROPOSED
PENDING_HUMAN_REVIEW
APPROVED
REJECTED
REVISED
NEEDS_MORE_EVIDENCE
ESCALATED
```

公开 `analysis.severity` 实际来自 `Decision.risk_level`。当前可靠性校验认可
`LOW | MEDIUM | HIGH | CRITICAL`，但 wire DTO 仍应按外部 string 解码并处理未知
值。

### 3.3 Human Review

```text
human_review_id
reviewer
decision_id
outcome: APPROVED | REJECTED | REVISED
comment
timestamp
revision_request
```

公开 review endpoint 只投影 approve/reject，且不返回 reviewer、comment、
timestamp 或 revision request。

### 3.4 Task

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

`TaskStatus`：

```text
CREATED
IN_PROGRESS
EVIDENCE_SUBMITTED
UNDER_REVIEW
CLOSED
NEEDS_MORE_EVIDENCE
FAILED
CANCELLED
```

### 3.5 Evidence

```text
evidence_id
task_id
type
file_or_data_ref
submitted_by
timestamp
validation_status: PENDING | ACCEPTED | REJECTED
description
```

当前没有 Evidence 读取 endpoint。Timeline 只能表明 evidence audit 发生过，不能
替代 Evidence 内容。

### 3.6 Post Review

```text
review_id
event_id
task_id
evidence[]
result: PASSED | NEEDS_MORE_EVIDENCE | FAILED
reviewer_or_model
closed
follow_up_required
timestamp
comment
```

当前没有 Post Review 读取 endpoint。

### 3.7 Audit

持久化 `AuditRecord`：

```text
audit_id
actor
action
object_type
object_id
previous_state: string | null
new_state: string | null
timestamp
trace_id
details: JSON object
```

SQLite 使用自增 `sequence` 保证 trace 内读取顺序；`sequence` 不是
`AuditRecord.to_dict()` 字段。Web Adapter 只输出第 2.2 节的安全 Timeline 子集。

### 3.8 Notification

`notifications.py` 定义的是 durable local outbox intent，不是浏览器未读消息：

```text
notification_id
event_id
trace_id
decision_id
recipient_id
recipient_name
title
content
channel
status: CREATED | DELIVERED | FAILED
created_at
```

当前 `LocalNotificationOutbox` 只创建 `channel=local_outbox`、
`status=CREATED` 的记录，不执行外部投递；每个 Decision 通过 SQLite unique
约束最多一个 Notification。没有公开读取 endpoint，也没有“已读/关闭”状态。
因此 Noah Pulse 的 dismissed/expanded/queue cursor 必须是前端交互状态，不能冒充
Notification delivery 状态。

## 4. 当前前端如何理解数据

### 4.1 已有类型

`frontend/src/types/index.ts` 明确把现有类型标为 presentation-only/mock：

- `Severity = info | attention | warning | critical`
- `RuntimeStatus = NEW | ANALYZING | PENDING_HUMAN_REVIEW |
  TASK_RUNNING | WAITING_EVIDENCE | CLOSED`
- `PulseState = idle | informational | attention`
- `MockSystemHealth`
- `MockActivity`
- `MockEventSummary`
- `MockPulseNotice`
- `MockCommandSuggestion`

其中 `ANALYZING`、`TASK_RUNNING`、`WAITING_EVIDENCE` 不是后端
`EventStatus`。它们是当前 Demo 的显示桶，命名为 `RuntimeStatus` 容易误导，F03-A
应把它们迁移为明确的 presentation lifecycle phase，并保留真实 raw status。

### 4.2 当前组件耦合

- `WorkspacePage` 直接 import `mockActivities`、`mockSystemHealth` 和
  `mockCommandSuggestions`；
- `AppShell` 直接 import activity、summary 和 Pulse fixture，并负责关联查找；
- `NoahPulse` props 直接依赖 `MockPulseNotice`；
- `AgentActionPanel` props 直接依赖 `MockActivity` 与 `MockEventSummary`；
- status-to-label 和 lifecycle index 在 `WorkspacePage` 与
  `AgentActionPanel` 中重复；
- 没有 `fetch`、axios 或其他真实网络调用；
- Vite 已有 `/api -> 127.0.0.1:8090` 开发代理。

这些是 F03-A 要替换的依赖方向，不应通过把 API DTO import 进组件来解决。

## 5. 前端真正需要的 View Model

下面是建议语义。最终 TypeScript 可以拆文件，但字段职责应保持一致。

### 5.1 基础显示语义

```ts
type ViewText =
  | { kind: "literal"; value: string }
  | { kind: "message"; id: string };

type PresentationSeverity =
  | "info"
  | "attention"
  | "warning"
  | "critical";

type DataAvailability = "available" | "partial" | "unavailable";

interface DataQuality {
  availability: DataAvailability;
  unknownFields: readonly string[];
  contractWarnings: readonly string[];
}
```

`ViewText` 允许 Mock 继续使用 message id，也允许 Runtime 提供 literal text；runtime
feature 不需要 import React component。组件通过一个统一 renderer 解析，不能在
不同 Provider 分支写 `t()`。

### 5.2 `WorkspaceSnapshot`

```ts
interface WorkspaceSnapshot {
  source: "mock" | "http";
  site: {
    id: string | null;
    name: ViewText;
    area: ViewText | null;
  };
  health: HealthView;
  contextSignals: readonly WorkspaceContextSignal[];
  activeNotices: readonly PulseNotice[];
  events: readonly EventView[];
  actionSummaries: readonly ActionSummary[];
  currentFocus: ActionSummary | null;
  commandSuggestions: readonly CommandSuggestion[];
  observedAt: string | null;
  quality: DataQuality;
}
```

`currentFocus` 是由当前 selected event ID 从同一 snapshot 选择出的投影，不是后端
新增关系。Snapshot 应不可变，event/notice/action 使用 ID 关联。

### 5.3 `EventView`

```ts
type RuntimeEventStatus =
  | "NEW"
  | "ANALYZED"
  | "PENDING_HUMAN_REVIEW"
  | "APPROVED"
  | "TASK_CREATED"
  | "IN_PROGRESS"
  | "EVIDENCE_SUBMITTED"
  | "UNDER_REVIEW"
  | "CLOSED"
  | "REJECTED"
  | "NEEDS_MORE_EVIDENCE"
  | "FAILED"
  | "CANCELLED"
  | "ESCALATED";

type LifecyclePhase =
  | "detected"
  | "analysis"
  | "review"
  | "task"
  | "evidence"
  | "resolved"
  | "failed";

interface EventView {
  id: string;
  title: ViewText;
  detail: ViewText | null;
  sourceLabel: ViewText | null;
  occurredAt: string | null;
  location: ViewText | null;
  assetId: string | null;
  runtimeStatus: RuntimeEventStatus | "UNKNOWN";
  rawRuntimeStatus: string;
  lifecyclePhase: LifecyclePhase;
  severity: PresentationSeverity;
  rawSeverity: string | null;
  severityLabel: ViewText;
  requiresHumanAction: boolean;
  isTerminal: boolean;
  actionSummaryId: string | null;
  quality: DataQuality;
}
```

`lifecyclePhase`、`requiresHumanAction`、`isTerminal` 是显示投影，不定义迁移。必须
保留 `rawRuntimeStatus`，未知状态不能被 cast 掉。

### 5.4 `PulseNotice`

```ts
type PulseNoticeKind =
  | "informational"
  | "attention"
  | "approval_required"
  | "critical";

interface PulseNotice {
  id: string;
  eventId: string;
  kind: PulseNoticeKind;
  severity: PresentationSeverity;
  priority: number;
  title: ViewText;
  summary: ViewText;
  facts: ViewText | null;
  analysis: ViewText | null;
  nextAction: ViewText | null;
  requiresHumanAction: boolean;
  createdAt: string | null;
  runtimeStatus: RuntimeEventStatus | "UNKNOWN";
  rawRuntimeStatus: string;
  sourceNotificationStatus: string | null;
  quality: DataQuality;
}
```

`rawRuntimeStatus` 与 EventView 一样保留 Runtime 原值；quality warning 不能代替
raw truth。`idle` 应由 `activeNotices.length === 0` 推导，`expanded` 由组件本地
state 管理。
`approval_required` 可由 Decision 的 `requires_human_review=true` 且状态为
`PENDING_HUMAN_REVIEW` 派生，但不能写回 Decision。当前 HTTP API 没有
Notification 或列表读取能力，Http Provider 暂时无法构建可靠队列。

### 5.5 `HealthView`

```ts
interface HealthView {
  state: "healthy" | "degraded" | "unavailable" | "unknown";
  label: ViewText;
  components: readonly {
    id: string;
    label: ViewText;
    value: ViewText;
    state: "healthy" | "degraded" | "unavailable" | "unknown";
  }[];
  observedAt: string | null;
  quality: DataQuality;
}
```

Health 不是 Event 状态机。一次 HTTP 200 也不等于 Edge node、Provider、SQLite 和
Runtime 都 healthy。没有 health endpoint 时，Http Provider 必须返回 `unknown`，
不能沿用 Mock 的 nominal。

### 5.6 `ActionSummary`

```ts
interface ActionSummary {
  id: string;
  eventId: string;
  heading: ViewText;
  facts: readonly ViewText[];
  aiUnderstanding: ViewText | null;
  risk: {
    severity: PresentationSeverity;
    rawSeverity: string | null;
    explanation: ViewText | null;
  };
  suggestedAction: ViewText | null;
  decision: {
    id: string;
    status: string;
    requiresHumanReview: boolean;
  } | null;
  task: {
    id: string;
    status: string;
    owner: ViewText | null;
  } | null;
  evidenceStatus: string | null;
  timeline: readonly {
    sequence: number;
    timestamp: string | null;
    action: string;
    entityType: string;
    entityId: string;
    status: string;
  }[];
  quality: DataQuality;
}
```

当前 API 可提供 Analysis、Decision 摘要、Task 摘要和 Timeline，但不能提供 Event
facts、Task description 或 Evidence 明细。`decision_type` 是决策类别，不应自动
改写成具体 suggested action。缺失内容保持 `null`/partial。

## 6. Runtime → Adapter → View Model 映射

| Runtime/API 来源 | Adapter 规则 | View Model |
|---|---|---|
| Event `event_id` | 原样保留 | `EventView.id` |
| Event `status` | 校验 known status；同时保存 raw | `runtimeStatus`, `rawRuntimeStatus` |
| Event status | 纯函数分组，不含迁移 | `lifecyclePhase`, `isTerminal` |
| Analysis/Decision severity | 规范化大小写；保存 raw | presentation `severity`, `rawSeverity` |
| Analysis `detected_issue` | 安全文本；不得补写事实 | event title/action heading（仅可用时） |
| Decision `reasoning_summary` | 安全文本 | `aiUnderstanding` |
| Decision `evidence[]` | 这是分析依据文本，不等同 Evidence records | `facts` 或 knowledge basis，须明确标签 |
| Decision review flag/status | 只派生 attention | `requiresHumanAction`, Pulse kind |
| Task public projection | 只映射 id/status/owner | `ActionSummary.task` |
| Timeline | 依 sequence 排序并验证 timestamp | `ActionSummary.timeline` |
| Notification | 未来读取后才能建队列；CREATED 不等于 unread | `PulseNotice` |
| API nullable analysis/decision/task | 作为合法 loading/empty state | `null` + quality |
| API 缺失字段 | 不造默认业务事实 | `null` + `unknownFields` |

### 6.1 状态映射原则

推荐集中在一个穷尽纯函数中，并有单元测试：

```text
NEW                                      -> detected
ANALYZED                                 -> analysis
PENDING_HUMAN_REVIEW / APPROVED /
REJECTED / ESCALATED                     -> review
TASK_CREATED / IN_PROGRESS               -> task
EVIDENCE_SUBMITTED / UNDER_REVIEW /
NEEDS_MORE_EVIDENCE                      -> evidence
CLOSED / CANCELLED                       -> resolved
FAILED                                   -> failed
unknown                                  -> failed-safe unknown presentation
```

这是布局阶段，不是合法迁移图。`REJECTED`、`CANCELLED`、`FAILED`、`ESCALATED`
必须仍显示原始状态，不能只显示线性进度造成“正常完成”的误解。`FAILED` 和 unknown
使用非线性异常表达：不填满 Closed 轨道，也不标记六个阶段全部完成。

Severity 建议：

```text
LOW       -> info
MEDIUM    -> attention
HIGH      -> warning
CRITICAL  -> critical
UNKNOWN   -> info + explicit unknown label
other     -> attention + contract warning
```

未知值不可让 TypeScript 崩溃，也不可被误报为 success。

### 6.2 notice 排序

notice priority 是前端可重算排序，不是业务状态：

1. `critical`
2. `approval_required`
3. `attention`
4. `informational`

同级按可靠 `createdAt` 升/降序策略固定，再以 `id` 稳定排序。关闭/展开/当前队列
索引保持在 UI store 或 component state，不能修改 Runtime/Notification status。

## 7. 推荐目录

```text
frontend/src/features/runtime/
├── api/
│   ├── HttpWorkspaceDataSource.ts # 当前 fail-closed；不固定 event ID
│   ├── runtimeApiDtos.ts         # wire DTO，字段名保持 snake_case
│   ├── runtimeApiErrors.ts       # error_code -> typed failure
│   └── runtimeApiDecoders.ts     # unknown -> 运行时校验；不盲 cast
├── adapter/
│   ├── eventViewAdapter.ts
│   ├── actionSummaryAdapter.ts
│   ├── pulseNoticeAdapter.ts
│   ├── healthViewAdapter.ts
│   └── statusMapping.ts
├── models/
│   ├── workspaceSnapshot.ts
│   ├── eventView.ts
│   ├── pulseNotice.ts
│   ├── healthView.ts
│   ├── actionSummary.ts
│   └── provider.ts
├── hooks/
│   ├── WorkspaceProviderContext.tsx
│   ├── useWorkspace.ts
│   ├── useEvents.ts
│   ├── useHealth.ts
│   ├── usePulse.ts
│   └── useActionSummary.ts
├── mock/
│   ├── mockAdapterInputs.ts      # presentation fixture，不是 wire DTO
│   └── MockWorkspaceDataSource.ts
├── composition.ts               # 只供 App root/test 选择具体数据源
└── index.ts                     # 只导出公共 View Model/provider/hooks
```

API DTO 不应从 feature 顶层导出给页面。React 组件只 import View Model、Provider
context 和 hooks。Adapter、decoder 和 error normalization 保持内部；具体 Mock/HTTP
source 只能从明确的 composition 子入口选择。仓库 `.gitignore` 的模型制品规则必须
限定到根目录 `/models/`，不能误伤 `frontend/src/features/runtime/models/` 源码。

## 8. Provider 契约

推荐以一次一致快照为主，而不是让四个 hook 各自发请求：

```ts
interface WorkspaceRequest {
  selectedEventId?: string | null;
  signal?: AbortSignal;
}

interface WorkspaceDataSource {
  readonly source: "mock" | "http";
  getInitialSnapshot(): WorkspaceSnapshot | null;
  getWorkspace(request?: WorkspaceRequest): Promise<WorkspaceSnapshot>;
}
```

### `MockWorkspaceDataSource`

- 实现同一个 `getWorkspace()`；
- Mock fixture 经过 adapter 或等价 builder 生成 View Model；
- 不让组件 import `src/mock`；
- 支持确定性 success、empty、partial 和 error fixtures；
- 不用 timeout 模拟“真实感”，除非测试显式注入 scheduler。

### 未来 `HttpWorkspaceDataSource`

- 通过注入的 `RuntimeApiClient` 调用相对 `/api`；
- 通过 decoder 验证 unknown JSON；
- 只把 DTO 交给纯 adapter；
- 支持 `AbortSignal`；
- 统一转换 HTTP、network、contract 与 API error；
- 不包含 React state，不读 DOM，不直接翻译 UI labels。

当前 API 没有 event discovery，所以 Http Provider 暂不能完整实现
`getWorkspace()`。可先实现接口与显式 `unavailable/partial`，但不能暗中使用固定
event ID。真实启用应等待第 11 节的 read projection。

Provider 的选择应发生在 app composition root：

```text
App
└─ WorkspaceProviderContext(value = mockProvider | httpProvider)
   └─ AppShell / Workspace
```

组件不读取环境变量来分支，不出现 `if (mock) ... else fetch ...`。

## 9. Hook 设计

### `useWorkspace()`

唯一拥有异步请求生命周期：

```ts
interface WorkspaceResource {
  source: "mock" | "http";
  data: WorkspaceSnapshot | null;
  status: "idle" | "loading" | "ready" | "refreshing" | "error";
  error: WorkspaceReadError | null;
  refresh(): void;
}
```

- 初始 load 与 background refresh 分开；
- cleanup 时 abort；
- 防止旧请求晚到覆盖新 snapshot；
- source 切换后的首次 render 不暴露上一 source 的 snapshot；
- error 不清除仍可展示的 last-known snapshot；
- F03-A 不加入 WebSocket、SSE 或隐式高频 polling。

### `useEvents()`

从同一 `WorkspaceSnapshot.events` 派生稳定排序和 selected event，不再次请求。

### `useHealth()`

从同一 snapshot 返回 `HealthView`。HTTP 数据缺失时是 unknown，而不是根据 fetch
成功猜 healthy。

### `usePulse()`

从 `activeNotices` 派生当前 notice 与 queue metadata；只管理本地 dismiss/expanded
交互。notice 的业务来源仍是 adapter 的 snapshot。

这种设计保证 Workspace、Pulse 和 Action Panel 在一次 render 中看到同一版本的
数据，也便于未来把 Provider 迁移到 React Query 等实现而不改变 UI 合同；本阶段
无需引入该依赖。

## 10. 错误、缺字段与兼容策略

### 10.1 解码

网络响应一律先视为 `unknown`：

- required ID 缺失或类型错误：contract error；
- `analysis`、`decision`、`task` 的 `null`：合法业务空态；
- 新增未知字段：忽略但不失败；
- 未知 status/severity/error code：保留 raw，进入兼容显示；
- confidence 不是有限数或超出预期范围：标为 contract warning，不直接渲染进度；
- API error `message` 只展示，不能驱动分支。

F03-A 的 decoder 先锁定当前公开 JSON 的结构与基础类型；由于 HTTP Workspace source
仍 fail-closed，confidence 范围、timeline sequence 非负整数与 timestamp 可解析性
尚未作为真实读取路径启用。这三项是开启 HttpWorkspaceDataSource 前的明确阻断项，
不能由 UI 临时猜测或静默修正。

### 10.2 缺字段

当前 API 无法提供的字段使用 `null` 和 `DataQuality`，不要用：

- 当前时间冒充事件时间；
- “North Assembly” 等 Mock 现场冒充 HTTP 数据；
- HTTP 连通冒充 system healthy；
- `decision_type` 冒充建议操作；
- Analysis `evidence[]` 冒充已提交 Evidence records；
- Notification `CREATED` 冒充浏览器 unread/delivered。

### 10.3 时间与时区

- `utc_now()` 生成带 `+00:00` 的 ISO-8601；
- Runtime 内部 `create_event(timestamp=...)` 只验证非空字符串，不能假设所有内部
  Event 都是严格 ISO；
- 当前公开 Event detail 没有 Event timestamp，只有 Timeline timestamp；
- Adapter 保留原字符串，同时验证是否可解析；
- UI 最后一步按 locale/timezone 格式化；
- 不删除 offset，不自行追加 `Z`；
- 无效时间显示 unknown，并记录 contract warning；排序回退到 sequence/ID。

### 10.4 请求一致性

当前多个单事件 GET 之间没有 snapshot version/ETag。连续读取 Event、Task 和
Timeline 时 Runtime 可能变化，形成混合版本。Http Provider 不应声称它们是原子
snapshot；`quality.availability` 应允许 partial，未来聚合 endpoint 应提供统一
`observed_at` 或 version。

### 10.5 安全与部署

- 继续使用 relative `/api` 与 Vite proxy；
- 不启用宽泛 CORS；
- 不让组件知道数据库路径或本地文件引用；
- 不记录 response body、用户输入、actor 或敏感 error detail；
- 当前服务无 authentication，不能因 localhost 假设未来 LAN 部署安全；
- 不把内部 `Runtime.snapshot()` 直接公开。

## 11. API 缺口（只记录，不在 F03-A 修改）

### Blocker：Workspace event discovery

建议未来提供只读、分页、稳定排序的 Workspace projection，例如：

```text
GET /api/workspace
```

或：

```text
GET /api/workspace/events?limit=<bounded>&cursor=<opaque>
```

最低需要：event ID、occurred/updated time、source、location/site、asset、safe
description/detected issue、真实 Event status、severity、是否需人工处理。当前
`GET /api/events/{id}` 不能替代列表。

### Blocker：完整单事件 action projection

建议未来由 Web Adapter 输出受控 action-card read model，而不是暴露 Runtime
snapshot：

```text
GET /api/events/{event_id}/action-card
```

需要整合 safe facts、Analysis、risk、Decision 摘要、Task 摘要、Evidence 状态和
Timeline/version，明确 nullable 与权限边界。

### Major：Notification/notice 读取

建议：

```text
GET /api/workspace/notices?limit=<bounded>&cursor=<opaque>
```

需明确 notification delivery 与 UI unread/dismiss 是不同概念。当前没有队列、
acknowledge 或 read cursor；F03-A 不新增写操作。

### Major：System health

建议：

```text
GET /api/system/health
```

需要分别表达 Web Adapter、Runtime/SQLite、Analysis Provider、Edge node 的
observed state、timestamp 和 unknown；不能只返回一个模糊 boolean。

### Major：分析触发/编排所有权

`POST /api/events` 只创建 `NEW` Event；`GET analysis` 明确不触发 Provider，且没有
公开 analyze endpoint 或 background worker。后续 Demo 必须明确谁拥有
NEW → analysis 的编排。F03-A 不增加该写操作。

### Major：一致性与增量读取

未来聚合读取需要：

- bounded pagination；
- opaque cursor；
- stable order；
- snapshot/version 或 `observed_at`；
- cache/refresh contract；
- 新事件提示方式。

F03-A 禁止 WebSocket、SSE；普通 refresh 只能作为基础。

### Minor：API 版本与 capability

当前没有 schema version、capability document 或 OpenAPI。未来至少应给聚合
projection 一个版本字段，并定义 additive compatibility。不要因这个缺口让组件
依赖后端 dataclass。

### Deployment gap

当前 JSON server 不托管 `frontend/dist`，也不做 SPA fallback/CORS。生产接入必须
另设受审计的同源静态资源边界，或明确 reverse proxy；本任务只记录，不修改
Python/Docker。

## 12. Agent B 建议实现清单

按依赖顺序实施，避免同时重写视觉：

1. 新建 `features/runtime/models`，定义 View Model、Provider、resource/error；
2. 新建 wire DTO 与 decoder，DTO snake_case 不进入组件；
3. 新建 status/severity 映射纯函数，覆盖所有真实状态和 unknown；
4. 新建 Event、Action、Pulse、Health adapter；
5. 实现确定性的 `MockWorkspaceDataSource`，把现有 fixture 收口进 feature；
6. 实现 Provider Context 与 `useWorkspace`，其他 hooks 只做 selector；
7. 让 `WorkspacePage`、`AppShell`、`NoahPulse`、`AgentActionPanel` 改用 View
   Model/hooks；
8. 保持默认 Mock，不发真实请求；
9. 可建立 `HttpWorkspaceDataSource` 类型/骨架，但在缺少 event discovery 时不得用
   固定 ID 伪装完整实现；
10. 删除或重命名误导性的 presentation `RuntimeStatus`，不复制后端状态机。

实现完成后必须证明：

- 页面无 `fetch`/axios；
- UI 不 import API DTO；
- Mock 与 HTTP 实现同一个 Provider 接口；
- Pulse notice 来自 snapshot，而不是独立 fixture；
- unknown status、missing field、provider error 和 source switch 有测试；
- F02.6 的主题、locale、Pulse、Workspace 与无障碍回归继续通过。
