# AlphaNoah Digital Employee Activation Flow

> F03-C Activation Architecture
>
> 本文只定义产品、应用适配器和前端读取边界，不修改 Runtime、SQLite、
> `SkillResolver`、状态机、Workflow、Decision 语义或设备执行权限。

## 0. 结论

F03-C 的第一条可信演示链应是：

```text
Demo button / future QR
        ↓ Event Source Adapter
Event / NEW
        ↓ existing analysis application
ResponsibilityDirectory
        ↓ explicit demo product binding
Digital Employee product projection
        ↓ existing Skill resolution and analysis facts
Work Record projection
        ↓
Human Review / PENDING_HUMAN_REVIEW
```

“数字员工被唤醒”是对既有 Event、Responsibility、Skill、Decision、
Notification 和 Audit 事实的产品化只读解释，不是新的 Runtime aggregate，
也不是第二套状态机。QR 和页面上的“模拟事件”按钮都只是 Event Source
Adapter；它们不能拥有分析、匹配、审批或任务语义。

当前公开 JSON API 无法直接完成这条演示链：`POST /api/events` 只接受一个
受限的餐厅空调场景并只创建 `NEW` Event；服务没有启动分析、事件发现、
Workspace 聚合、Notification 读取或 Digital Employee API。因此 F03-C
需要一个**独立、显式标记为 synthetic demo 的应用适配器**，而不是改变
现有 endpoint 的行为。

## 1. 真实仓库审计

### 1.1 Event 与 Event Source

`AlphaNoahRuntime.create_event()` 是当前统一 Event 写入边界。真实 Event
字段包括 `event_id`、`source`、`timestamp`、`event_type`、`location`、
`asset_id`、`description`、`severity`、`status`、`trace_id`、
`attachments` 和 `metadata`。显式工业 Event 必须提供 snake_case
`event_type` 和非空 `description`，创建后状态为 `NEW`。

仓库已有两个不同的 HTTP 边界：

- `web.py`：`127.0.0.1:8080` 的 HTML `GET/POST /report`，通过
  `QRIncidentInputAdapter` 创建 Event；
- `web_api.py`：`127.0.0.1:8090` 的 JSON API，通过
  `RestaurantAirconWebAdapter` 暴露受限黄金路径。

两者默认使用不同 SQLite 文件。若分别按默认命令启动，QR 提交不会自然
出现在 JSON API 或前端 Workspace 中。F03-C 不得把“两个服务都启动了”
误写成“它们共享数据”。

### 1.2 当前公开 JSON API

真实 endpoint 只有：

```text
POST /api/events
GET  /api/events/{event_id}
GET  /api/events/{event_id}/analysis
POST /api/events/{event_id}/review
GET  /api/events/{event_id}/task
POST /api/tasks/{task_id}/evidence
GET  /api/events/{event_id}/timeline
```

其中 `POST /api/events` 的精确请求是：

```ts
interface ExistingCreateEventRequest {
  location: "A08";
  asset_type: "air_conditioner";
  description: string;
}
```

它内部仍使用固定的 `device_not_shutdown` / `air_conditioner` 黄金路径，
响应仅为 `{ event_id, status }`。它不接受任意 `asset_id` 或 `type`，
不启动分析，不执行 Responsibility matching，也不生成 Workspace snapshot。
现有 GET 均要求调用方已经知道 `event_id`。

JSON server 是 loopback-only 的 `ThreadingHTTPServer`，仅支持 GET/POST，
拒绝查询参数，JSON body 上限 16 KiB，没有 CORS、静态资源托管、SPA
fallback 或认证。Vite 开发服务器只把相对 `/api` 代理到 8090。

### 1.3 Skill 与分析

`DeterministicSkillResolver` 只按 Event 的 `event_type` 和
`metadata.asset_type` 匹配 active `SkillDefinition`。无匹配、只有
deprecated 匹配或最高特异度冲突都会明确失败；不存在通用 fallback。

当前餐厅空调黄金路径可真实解析：

```text
event_type = device_not_shutdown
metadata.asset_type = air_conditioner
→ restaurant-aircon-shutdown@1.0-demo
```

`RestaurantAirconGoldenPath.analyze(event_id)` 会走现有可靠 Provider、
知识检索、SkillResolver、Runtime 和 DecisionHook，最终停在
`PENDING_HUMAN_REVIEW`。当前没有公开的“启动分析”endpoint。

### 1.4 Responsibility、Notification 与 Digital Employee

`ResponsibilityDirectory` 按固定优先级解析：

```text
asset_id exact match
→ location exact match
→ event_type exact match
→ UNASSIGNED
```

它返回 event-scoped `ResponsibilityAssignment`，不是员工目录。示例
`examples/responsibility_directory.json` 只覆盖 `PACK-003`、
`Packaging-Line-A` 和 `equipment_issue_report`，**不覆盖餐厅空调黄金路径
的 `A08-AIRCON` / `device_not_shutdown`**。

`create_notification_for_decision()` 仅允许等待人工关注的 Decision，并将
一条 `CREATED` 状态的 local-outbox Notification 持久化。每个 Decision
最多一条 Notification；它不表示消息已送达，不创建 HumanReview 或 Task。

F03-B 已明确：Digital Employee 只存在于产品展示层。当前没有
DigitalEmployee-to-Responsibility、DigitalEmployee-to-Skill 或
DigitalEmployee-to-Task 的 Runtime 关系；Task `assignee` 也只是字符串。
因此 F03-C 只能使用一个审查过、明确标记为 demo 的 product binding，
不能根据 owner name、Skill ID 或 Task assignee 猜测员工。

### 1.5 HITL、Task 与 Evidence

现有 `DecisionHook` 对需要人工确认的分析将 Event 和 Decision 置为
`PENDING_HUMAN_REVIEW`。只有 `human:*` actor 才能提交 HumanReview。
批准后仍需显式创建和启动 Task；之后才能提交 Evidence 并进入复核。
F03-C 的“唤醒完成”应停在等待人工确认，不得自动批准、创建 Task、
提交 Evidence 或执行设备动作。

### 1.6 当前前端边界

F03-A 已建立：

```text
wire DTO / decoder → adapter → View Model → DataSource/Provider → hooks → UI
```

`HttpWorkspaceDataSource` 因后端没有事件发现/Workspace read contract 而
明确 fail closed。当前 Workspace、Pulse 和 Digital Employee Center 均由
Mock DataSource 驱动。F03-B 的员工 `equipment-maintenance` 是 Mock 产品
投影，不能被宣称为 Runtime 实体。

## 2. F03-C 领域流程与权威性

| 阶段 | 当前权威来源 | F03-C 产品解释 |
|---|---|---|
| Event Source | Demo/QR input adapter | 事件如何进入系统 |
| Event | Runtime + SQLite | 发生了什么 |
| Responsibility | reviewed local directory | 谁应负责接住该事件 |
| Digital Employee | explicit demo product binding | 用企业岗位语言展示负责人 |
| Skill | existing SkillResolver + audit metadata | 支撑该岗位的能力模块 |
| Work Record | safe Audit/Timeline + actual analysis result | 员工做过什么 |
| Human Review | Decision/Event status | 下一步需要人确认什么 |

必须保持单向关系：

```text
Runtime facts
    ↓
Activation Web projection
    ↓
frontend decoder / adapter
    ↓
Activation View Model
    ↓
Workspace + Pulse + Employee detail
```

前端不得回写 `working`、工作记录或进度；这些只是由当前响应重新计算的
展示状态。Event/Decision/Task 状态仍以 Runtime 为唯一业务事实。

## 3. Event Source Adapter

### 3.1 第一版：Demo Event Source

第一版推荐增加 `DemoActivationInputAdapter`，调用既有
`runtime.create_event()`，写入与真实黄金路径兼容的固定场景：

```text
source        = demo_activation
actor         = adapter:demo-activation
event_type    = device_not_shutdown
asset_id      = A08-AIRCON
location      = Restaurant-Private-Room-A08
metadata      = {
  asset_type: air_conditioner,
  scenario_id: synthetic-restaurant-aircon-a08,
  data_classification: Synthetic demo data,
  incident_notice: Not a real production incident
}
```

请求只允许修改受限 description，不允许浏览器覆盖 event type、asset type、
Skill、owner、employee、severity、status 或 actor。这样才能复用真实
SkillResolver/Provider/HITL，而不是为示例输入 `equipment_abnormal` 凭空
假设一个尚不存在的 Skill。

### 3.2 QR 是同级来源，不是核心

未来 QR Adapter 也应输出同一个受控 Event 语义，再进入相同的 application
orchestrator。它不能直接写 Digital Employee、Pulse 或工作记录。若要让
现有 `/report` 参与同一演示，必须显式注入与 JSON API 相同的 application
和 database；F03-C 不应依赖两个默认数据库“碰巧一致”。

## 4. Before / After 展示状态

### Before

```text
设备维护员工
Online
Idle
当前工作：无
```

这里的 Online/Idle 仍是 F03-B Mock 产品投影。

### After

```text
设备维护员工
Working
正在处理：A08-AIRCON 未按时关闭
下一步：等待人工确认
```

映射规则：

- 已产生 Event，但尚未获得受审查 owner binding：不显示某员工 Working；
- owner 为 `UNASSIGNED` 或 binding 未知：显示“事件等待分派”；
- owner 明确绑定 `equipment-maintenance`，且 Event 非终态：显示 Working；
- `PENDING_HUMAN_REVIEW`：工作进度停在“等待人工确认”；
- FAILED/ESCALATED：显示异常/升级，不伪装为正常 Working；
- terminal 状态只能由 Runtime raw status 派生，不由 UI 自行推进。

## 5. Work Record：事实时间线，不是聊天

第一版工作记录只从真实安全里程碑生成：

```text
10:32  收到现场事件
10:33  匹配设备维护职责
10:34  使用已解析能力和知识上下文完成分析
10:35  提交建议，等待人工确认
```

每条记录必须有稳定 ID、Runtime/Audit sequence、实际 timestamp、kind、
event ID 和事实化标题。不得出现用户/Agent 气泡、输入框、typing 状态、
“AI 正在思考”或未被 Audit/analysis 证明的步骤。多个低层 Audit action
可以折叠成一个产品里程碑，但不能新增事实。知识记录只有在真实分析摘要
存在 knowledge match/source 时才显示。

## 6. 推荐的最小兼容后端边界

现有 `RestaurantAirconWebAdapter.create_event()` 不适合作为激活链：
改变它会破坏已冻结的 `POST /api/events` 行为。推荐并列新增：

```text
DemoActivationInputAdapter
        ↓
DemoActivationApplication
        ├─ runtime.create_event
        ├─ existing golden_path.analyze
        ├─ ResponsibilityDirectory.resolve
        ├─ runtime.create_notification_for_decision
        └─ safe Activation DTO projection
        ↓
DemoActivationWebAdapter
```

最小路由：

```text
POST /api/demo/events
GET  /api/demo/events/{event_id}
```

POST 同步完成“创建 Event → 分析 → responsibility/outbox”，停在 Human
Review；GET 只重建同一安全投影，不触发 Provider、不推进状态。不要增加
`current` singleton endpoint，因为多个事件时“current”没有可靠语义。

该边界可以被注入现有 `WebAdapterHTTPServer`，但必须与现有 adapter 并列，
现有七个 endpoint 的请求、响应和错误不得改变。它是 local synthetic demo
adapter，不是通用 Event API。

### 6.1 精确请求 DTO

```ts
interface DemoActivationRequestDto {
  scenario_id: "synthetic-restaurant-aircon-a08";
  description: string;       // trim 后 1..2000
  request_id: string;        // 1..128，安全不透明值；禁止路径和 secret 形状
}
```

只接受这三个字段，未知字段、空 description、未知 scenario、重复 JSON key、
超长/非法 request ID 均返回受控 400。

### 6.2 精确响应 DTO

```ts
interface DemoActivationResponseDto {
  projection_version: "f03c-demo-v1";
  replayed: boolean;
  event: {
    event_id: string;
    event_type: "device_not_shutdown";
    source: "demo_activation";
    timestamp: string;
    status: string;            // 保留 Runtime raw status
    severity: string;
    asset_id: "A08-AIRCON";
    location: "Restaurant-Private-Room-A08";
    description: string;
  };
  responsibility: {
    owner_id: string;
    owner_name: string;
    match_type: "asset" | "location" | "event_type" | "unassigned";
    matched_key: string;
  };
  analysis: {
    detected_issue: string;
    reasoning_summary: string;
    confidence: number;
    requires_human_review: boolean;
    knowledge_sources: readonly string[];
  } | null;
  notification: {
    notification_id: string;
    status: "CREATED" | "DELIVERED" | "FAILED";
    created_at: string;
  } | null;
  human_review: {
    decision_id: string;
    status: string;
    required: boolean;
    allowed_actions: readonly ("approve" | "reject")[];
  } | null;
  work_records: readonly {
    id: string;
    sequence: number;
    occurred_at: string;
    kind:
      | "event_received"
      | "responsibility_matched"
      | "analysis"
      | "knowledge_lookup"
      | "human_review";
    title: string;
    event_id: string;
    task_id: null;
  }[];
  quality: {
    availability: "available" | "partial" | "unavailable";
    unknown_fields: readonly string[];
    contract_warnings: readonly string[];
  };
}
```

响应不包含 prompt、analysis instructions、credential、原始 Audit details、
本机路径或模型思维链。`task_id` 在 F03-C 唤醒阶段必须为 null，因为人工
批准前不应存在 Task。

受控失败沿用 `{ error_code, message }` 外形；若 Event 已成功持久化后分析
失败，可附加 `event_id`，让 UI 展示失败事实而不是再创建一个 Event。

## 7. Digital Employee 产品投影

新增一个显式 demo binding，而不是 Runtime model：

```ts
const demoOwnerEmployeeBinding = {
  maintenance_001: "equipment-maintenance",
} as const;
```

F03-C 专用 responsibility fixture 需要明确加入：

```json
{
  "asset_id": {
    "A08-AIRCON": {
      "owner_id": "maintenance_001",
      "owner_name": "Equipment Maintenance"
    }
  }
}
```

这两者都必须标注 synthetic demo。后端只返回真实 ResponsibilityAssignment；
前端 Activation Adapter 将 `owner_id` 与 F03-B collection 做显式 join：

```ts
interface ActivationSnapshot {
  source: "demo-http";
  eventId: string;
  activeEmployeeId: string | null;
  activeCapabilityId: string | null;
  state:
    | "activating"
    | "working"
    | "approval_required"
    | "failed"
    | "unassigned";
  notice: PulseNotice;
  workRecords: readonly WorkRecord[];
  observedAt: string;
  quality: DataQuality;
}
```

这些 state 是展示投影，不是 Runtime transition。未知 owner、未知 employee
或 collection 尚未加载时必须 fail closed：保留 Event，Pulse 显示“等待
分派”，`activeEmployeeId=null`，绝不回退到第一个 Mock 员工。

## 8. 前端组合建议

推荐新增：

```text
frontend/src/features/activation/
├── api/
│   ├── activationApiDtos.ts
│   ├── activationApiDecoders.ts
│   └── HttpActivationDataSource.ts
├── adapter/
│   ├── activationAdapter.ts
│   └── activationBindings.ts
├── models/
│   ├── activationSnapshot.ts
│   └── activationDataSource.ts
├── hooks/
│   ├── ActivationProvider.tsx
│   └── useActivation.ts
└── mock/
    └── MockActivationDataSource.ts
```

`ActivationProvider` 放在 App composition root，由一次 activation snapshot
分别覆盖：

- Workspace：新增/聚焦当前 Event；
- Noah Pulse：显示 attention / approval required notice；
- Digital Employee：只覆盖匹配员工的 status、current task summary 和
  work records。

不得让 Workspace、Pulse 和 Employee 页面分别 fetch，亦不得直接修改
F03-A/F03-B Mock fixture。触发按钮调用 DataSource command；组件不直接
`fetch`。未来 QR 只替换 Event Source，不替换上述读取投影。

后端建议新增应用层文件，而不进入 core Runtime：

```text
src/alphanoah_a1/demo_activation.py
src/alphanoah_a1/demo_activation_adapter.py
examples/demo_activation_responsibility.json
```

若修改 `web_api.py`，只做新路由分派和 adapter 注入；不得把演示编排塞进
request handler。

## 9. 空输入、未知值、幂等与并发

### 输入与未知映射

- 空/空白 description：400，且不得创建 Event；
- 未知 scenario 或额外字段：400；
- 未知 Event/GET ID：404；
- Skill 无匹配/冲突：保留 FAILED Event，返回受控错误；
- Responsibility 为 `UNASSIGNED`：响应成功但 employee 为 null；
- owner 无产品 binding：标记 partial，不能猜测员工；
- 未知 Runtime status：保留 raw 值，映射到 unknown/failed-safe；
- 缺少 analysis/notification/timeline：返回 null/partial，不生成 Mock 补位。

### 幂等

Runtime Event 创建当前没有 idempotency key，不能宣称数据库级 exactly-once。
F03-C 可在 demo adapter 使用 `request_id`、进程内有界缓存和锁，并把
request ID 放入受控 Event metadata；同进程重复请求返回原 Event，
`replayed=true`。重启后可在本地 demo 的有界 `list_events()` 中按 metadata
恢复，但这不是多进程或生产级保证。

Notification 已以 Decision 为唯一边界并返回既有记录；这不等于 Event
创建也幂等。

### 并发与部分失败

`ThreadingHTTPServer` 会并发处理请求。Demo orchestrator 应在
“检查 request ID → 创建/恢复 Event → 分析 → Notification”周围使用进程内
互斥，至少阻止双击产生两个 Event。生产级跨进程锁不在 F03-C 范围。

现有 Runtime 操作不是一个覆盖整条激活链的数据库事务。若 Event 已创建而
分析或 notification 失败，应返回已有 `event_id` 和受控错误，后续 GET
展示真实 FAILED/partial 状态；不得静默回滚 UI 或自动新建第二个 Event。

## 10. Human Review 边界

F03-C 成功态必须是：

```text
Event.status = PENDING_HUMAN_REVIEW
Decision.status = PENDING_HUMAN_REVIEW
Notification.status = CREATED
Task = absent
Evidence = absent
```

Noah Pulse 可以打开现有结构化 Action Panel。Approve/Reject 仍只能调用
现有 `POST /api/events/{event_id}/review`，且本任务若不实现审批交互，应只
展示“等待人工确认”。不得自动调用 `create_task()`，也不得把 Pulse 的
expanded/dismissed 当作 HumanReview。

## 11. API 缺口

F03-C 之外仍缺少：

- `GET /api/workspace` 或事件 discovery；
- Digital Employee list/detail 的 authoritative read projection；
- employee ↔ responsibility/Skill/Event/Task 的正式版本化 binding；
- Notification list/read/dismiss contract；
- 按员工读取 work records；
- 激活 request 的数据库级幂等；
- 多事件 current-focus 规则、分页和 cursor；
- 同源静态托管/SPA fallback 或严格 CORS 策略；
- 认证、授权、租户、审计级责任目录版本。

这些缺口不得通过浏览器 localStorage、名字匹配或扩展 SQLite schema 在
F03-C 内“补齐”。

## 12. 测试建议

### Python

- exact DTO：合法请求、空白、额外字段、重复 JSON key、超长 body；
- Event Source：写入受控 source/type/asset/location/metadata；
- Skill：确实解析现有 restaurant-aircon Skill，不修改 Resolver；
- Responsibility：A08-AIRCON 匹配 maintenance_001，未知设备为 UNASSIGNED；
- Activation：Event → analysis → notification，最终停在 human review；
- HITL：Task/Evidence 为空，无自动审批；
- work record：仅映射真实 sequence/timestamp，不泄漏 private audit details；
- duplicate request ID：同进程返回同一 Event；并发双击只产生一个 Event；
- partial failure：保留 event ID，GET 可恢复；
- 现有七个 Web endpoint 回归完全不变。

### Frontend

- DTO decoder 拒绝缺字段、错误类型和未知 contract version；
- owner binding 精确匹配；UNASSIGNED/未知 owner 不回退 Mock；
- activation overlay 同时更新 Workspace、Pulse 和目标 Employee；
- Pulse 打开 Action Panel，员工详情显示非聊天 Work Record；
- before/after、失败、partial、重复请求和 retry；
- 中文/英文、dark/light、reduced motion、键盘焦点；
- 请求中按钮禁用，重复点击不并发发出写请求；
- 页面组件不直接 fetch，不发 WebSocket/SSE，不创建聊天或设备动作。

仓库验证继续运行：

```text
npm run typecheck
npm test
npm run build
Python tests
compileall
git diff --check
```

## 13. F03-C 完成判定

只有以下事实同时成立，才能称为“数字员工被事件唤醒”：

1. 一个受控 Event Source 创建了真实 Runtime Event；
2. 现有 SkillResolver/Provider 产生真实分析事实；
3. reviewed ResponsibilityDirectory 得到明确 assignment；
4. 显式 demo binding 将 assignment 投影到一个 F03-B 员工；
5. Workspace、Pulse 和员工详情消费同一个 Activation snapshot；
6. 工作记录来自实际 Audit/analysis，而不是预演动画或聊天文案；
7. 流程停在 Human Review，未创建 Task/Evidence 或执行设备动作；
8. 未新增 DigitalEmployee Runtime，未修改 SQLite、SkillResolver、
   Workflow 或 Decision 语义。
