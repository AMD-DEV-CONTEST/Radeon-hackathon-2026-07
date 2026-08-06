# AlphaNoah Frontend UI Information Architecture

## 1. 产品结构原则

AlphaNoah 前端是一个以现场行动为中心的工作台，不是传统企业后台，也不是聊天
机器人外壳。

第一阶段只有两个一级空间：

1. **Workspace**：看见现场、理解事件、完成确认和跟进；
2. **Management**：以简洁只读/有限配置视图了解数字岗位、Skill、Provider、
   Edge 节点和系统状态。

Noah Pulse 常驻全局 shell，但保持低干扰。聊天/智能输入是上下文交互手段，
不替代事件事实、风险、依据、确认、Task 和 Audit。

## 2. 一级导航与路由

```text
/
├─ workspace
│  └─ events/:eventId             # deep link 到结构化行动面板
└─ management
   ├─ digital-roles
   ├─ skills
   ├─ providers
   ├─ edge-nodes
   └─ system-health
```

推荐 URL：

| Space | Route | 内容 |
|---|---|---|
| Workspace | `/` | 默认现场工作台 |
| Workspace | `/events/:eventId` | 保留工作台背景并展开 Event 行动面板 |
| Management | `/management/digital-roles` | 数字岗位/责任路由摘要 |
| Management | `/management/skills` | Skill 摘要 |
| Management | `/management/providers` | 模型与 Provider 状态 |
| Management | `/management/edge-nodes` | Edge 节点 |
| Management | `/management/system-health` | 系统健康 |

`/management` 重定向到 `/management/digital-roles`。Management 子页是同一个
一级空间，不应在主导航中展开成五个同级产品。

## 3. Workspace 信息架构

Workspace 使用一个主要画布，建议从上到下分成：

1. **现场状态条**
   - 系统连接/最后更新时间；
   - 当前活动、待确认、严重异常计数；
   - 数据 stale/offline 标识。
2. **当前事件或活动流**
   - 以 Event 为事实主线；
   - 显示时间、位置、资产、问题、严重度和 Runtime 状态；
   - 不以聊天消息作为列表主对象。
3. **智能指令输入**
   - 可用于筛选、定位、打开 Event 或发起后续已定义的上下文交互；
   - 没有 API capability 时必须清楚禁用，不发送虚构请求；
   - 不接受 secret，不直接控制设备。
4. **Noah Pulse**
   - 固定在 shell 的稳定位置；
   - 胶囊、摘要卡和行动面板共享同一 notice queue；
   - 不使用独立业务状态。
5. **结构化行动面板**
   - Event facts；
   - AI analysis；
   - risk；
   - knowledge sources；
   - human confirmation；
   - Task/Evidence status；
   - Audit timeline；
   - contextual conversation 区域。

行动面板建议为非模态侧面板或大尺寸 overlay，不夺取页面上下文。Event deep link
打开相同面板，刷新后仍能恢复；关闭面板返回 Workspace，不改变 Event 状态。

### 3.1 行动面板内容顺序

1. 标题、Event ID、Runtime 状态、严重度；
2. 必须立即看到的人工确认；
3. 现场事实；
4. AI 分析与置信度；
5. 风险和安全边界；
6. 知识依据；
7. Task 与 Evidence；
8. Audit timeline；
9. 上下文输入/对话。

确认操作不能藏在聊天流中。approve/reject 必须显示操作对象、后果、当前 Decision
和提交状态；成功后重新读取后端，不由 UI 乐观修改业务状态。

## 4. Management 信息架构

### 4.1 数字岗位

当前 Runtime 只有 `ResponsibilityDirectory` 和
`ResponsibilityAssignment`，没有独立 DigitalRole aggregate。因此第一版只能
把“数字岗位”定义为责任路由的管理投影，不能伪造自治 Agent 生命周期。

显示：

- owner ID/name；
- asset/location/event-type 路由摘要；
- unassigned fallback；
- 数据来源和只读状态。

### 4.2 Skill

显示 `SkillDefinition` 的安全摘要：

- skill ID/version；
- active/deprecated；
- supported event types/asset types；
- escalation rules；
- knowledge query hints。

不显示或编辑 prompt，不提供 Skill 编辑器，不在 UI 中让模型选择 Skill。

### 4.3 模型与 Provider

显示：

- Provider kind；
- enabled/configured/selected；
- discovery status；
- configured model 和安全 endpoint；
- 最近检查时间。

不显示 API key 值，不自动安装 Provider、下载模型、切换 Provider 或执行 smoke
test，除非后续有明确、审计过的操作契约。

### 4.4 Edge 节点

当前仓库没有 EdgeNode 模型或 API。页面在 API 完成前不能展示 mock 节点为真实
数据。后续最小摘要应只包含 identity、版本、最后观测时间和健康状态。

### 4.5 系统状态

系统状态汇总 Web Adapter、SQLite 可用性、Provider discovery 和 Edge node
观测。它是健康观测，不是 Event 状态机。当前没有公开 health endpoint。

## 5. 核心 UI 数据模型草案

以下是 TypeScript 方向草案。字段后标注当前来源；`gap` 表示当前公开 API 不提供，
不是可以假设存在的字段。

### 5.1 Runtime 状态引用

```ts
type EventStatus =
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

type DecisionStatus =
  | "PROPOSED"
  | "PENDING_HUMAN_REVIEW"
  | "APPROVED"
  | "REJECTED"
  | "REVISED"
  | "NEEDS_MORE_EVIDENCE"
  | "ESCALATED";

type TaskStatus =
  | "CREATED"
  | "IN_PROGRESS"
  | "EVIDENCE_SUBMITTED"
  | "UNDER_REVIEW"
  | "CLOSED"
  | "NEEDS_MORE_EVIDENCE"
  | "FAILED"
  | "CANCELLED";

type Severity = "UNKNOWN" | "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
```

这些 union 必须直接来自 Runtime；UI 不增加 `RESOLVED`、`ACKNOWLEDGED`、
`SNOOZED` 等业务状态。

### 5.2 AgentNotice

```ts
interface AgentNotice {
  id: string;                    // Notification.notification_id 或稳定派生 ID
  source: "notification" | "event" | "system";
  eventId: string | null;        // Notification.event_id
  decisionId: string | null;     // Notification.decision_id
  title: string;                 // Notification.title
  summary: string;               // Notification.content / 安全摘要
  createdAt: string;             // Notification.created_at / Event.timestamp
  runtimeStatus: EventStatus | null;
  decisionStatus: DecisionStatus | null;
  severity: Severity;
  requiresHumanReview: boolean;
  notificationStatus:
    | "CREATED"
    | "DELIVERED"
    | "FAILED"
    | null;
}
```

`priority` 不持久化为新业务字段，而是由
`requiresHumanReview + severity + runtimeStatus + createdAt` 的 UI policy
计算。UI 的 read/dismiss 只属于本地呈现；不能写成 Notification `DELIVERED`。
当前公开 API 没有 Notification 列表，整个模型需要 read API gap。

### 5.3 PulseState

```ts
type PulseBaseState =
  | "idle"
  | "informational"
  | "attention"
  | "approval_required"
  | "critical";

interface PulseState {
  base: PulseBaseState;
  presentation: "capsule" | "summary" | "expanded";
  activeNoticeId: string | null;
  queuedNoticeIds: string[];
  dismissedNoticeIds: string[];  // session-local presentation state
  expandedFrom: Exclude<PulseBaseState, "idle"> | null;
}
```

产品语言中的 `expanded` 被建模为 presentation，而不是与 critical 并列的业务
严重度。这样展开后仍保留原优先级，收起也不会改变 Runtime。若组件需要单一
判别值，可暴露：

```ts
type PulseVisualState = PulseBaseState | "expanded";
```

但其 reducer 内部仍应保留 `base`。

### 5.4 EventSummary

```ts
interface EventSummary {
  eventId: string;               // Event.event_id
  timestamp: string;             // Event.timestamp; current public API gap
  eventType: string;             // Event.event_type; gap
  location: string;              // Event.location; gap
  assetId: string;               // Event.asset_id; gap
  description: string;           // Event.description; gap
  detectedIssue: string;         // Event.detected_issue / analysis projection
  confidence: number;            // Event/Decision confidence
  severity: Severity;            // Event.severity / Decision.risk_level
  status: EventStatus;           // current public API
  skillId: string | null;        // current public API
  skillVersion: string | null;   // current public API
}
```

当前 `GET /api/events/{id}` 只提供 ID/status、Skill 和 Analysis/Decision 摘要，
不足以构造完整 EventSummary；不得用 URL、标题或本地 fixture 补齐事实。

### 5.5 AgentActionCard

```ts
interface AgentActionCard {
  event: EventSummary;
  analysis: {
    detectedIssue: string;
    decisionType: string;
    reasoningSummary: string;
    evidence: string[];
    modelOrRule: string;
    confidence: number;
    requiresHumanReview: boolean;
    severity: Severity;
  } | null;
  decision: {
    decisionId: string;
    status: DecisionStatus;
    requiresHumanReview: boolean;
  } | null;
  knowledgeSources: string[];
  task: {
    taskId: string;
    status: TaskStatus;
    owner: string;
    description: string | null;       // current public API gap
    expectedResult: string | null;    // gap
    deadline: string | null;          // gap
  } | null;
  evidence: Array<{
    evidenceId: string;
    type: string;
    submittedBy: string;
    timestamp: string;
    validationStatus: "PENDING" | "ACCEPTED" | "REJECTED";
    description: string;
  }>;                                // current public API gap
  timeline: Array<{
    sequence: number;
    timestamp: string;
    action: string;
    entityType: string;
    entityId: string;
    status: string;
  }>;
  capabilities: {
    canSubmitReview: boolean;
    canSubmitTextEvidence: boolean;
    canUseContextConversation: boolean;
  };
}
```

`capabilities` 表示当前 API 和当前对象是否支持某个 UI 操作，不代表新的业务状态。
后端必须继续最终校验；前端不能仅靠 `canSubmitReview` 绕过 Runtime。

### 5.6 DigitalRole

```ts
interface DigitalRole {
  id: string;                    // Responsibility owner_id
  name: string;                  // Responsibility owner_name
  source: "responsibility_directory";
  routes: Array<{
    matchType: "asset" | "location" | "event_type";
    matchedKey: string;
  }>;
  isFallback: boolean;           // owner_id === "UNASSIGNED"
}
```

这是责任目录的临时管理投影，不声明模型自治、会话、工具权限或在线状态。当前没有
公开 API。

### 5.7 SkillSummary

```ts
interface SkillSummary {
  skillId: string;               // SkillDefinition.skill_id
  version: string;               // SkillDefinition.version
  status: "active" | "deprecated";
  supportedEventTypes: string[];
  supportedAssetTypes: string[];
  escalationRules: string[];
  knowledgeQueryHints: string[];
}
```

不包含 `analysis_instructions`，因为当前安全 Web 投影明确不返回 prompt/instruction。
若未来需要管理详情，需单独审计权限和泄漏边界。

### 5.8 SystemHealth

```ts
type HealthObservation = "available" | "degraded" | "unavailable" | "unknown";

interface SystemHealth {
  checkedAt: string;
  overall: HealthObservation;    // 由 component observations 确定性汇总
  webAdapter: HealthObservation;
  persistence: HealthObservation;
  providers: Array<{
    kind: "ollama" | "vllm" | "openai_compatible" | "fake";
    status:
      | "AVAILABLE"
      | "DISABLED"
      | "NOT_CONFIGURED"
      | "CREDENTIAL_MISSING"
      | "CREDENTIAL_REJECTED"
      | "MODEL_MISSING"
      | "UNAVAILABLE"
      | "INVALID_RESPONSE";
    configuredModel: string;
    detail: string;
  }>;
  edgeNodes: Array<{
    nodeId: string;
    observedAt: string;
    status: HealthObservation;
  }>;                            // no current model/API
}
```

Health 是一次观测，不使用 EventStatus。Provider status 直接复用现有
`DiscoveryStatus`。`overall` 的汇总规则必须固定并可测试，不能让模型生成。

## 6. Noah Pulse 交互状态

### 6.1 状态行为

| 状态 | 视觉表现 | 自动展开 | 人工操作 |
|---|---|---|---|
| `idle` | 中性小胶囊、轻微在线点，不循环呼吸 | 否 | 可点击查看最近活动 |
| `informational` | 品牌/蓝色点、未读计数、单次淡入 | 不自动打开摘要卡 | 可查看或关闭；不要求业务操作 |
| `attention` | 琥珀色边/图标、简短摘要、无闪烁 | 可在用户空闲时从胶囊展开一次摘要；不打开行动面板 | 建议查看；是否行动由 Event/Task 状态决定 |
| `approval_required` | 明确“待人工确认”、Decision/Event 标识、主次操作入口 | 可展开非模态摘要；不得自动打开完整面板 | 需要显式 approve/reject；关闭摘要不等于处理 |
| `critical` | 高对比危险色、严重度文字和稳定图标；不只依赖颜色 | 可展开非模态摘要；不得抢焦点或自动打开完整面板 | 需要立即查看；具体操作仍由 Runtime capability 决定 |
| `expanded` | 结构化行动面板；保留来源 base state | 只由用户点击或 deep link 进入 | 在面板内执行已支持操作 |

“自动展开”只指 capsule -> summary 的非模态变化。任何状态都不能自动执行确认、
自动打开完整行动面板、移动键盘焦点或覆盖当前输入。

### 6.2 状态推导

推荐固定优先级：

```text
critical
  > approval_required
  > attention
  > informational
  > idle
```

推导原则：

- `severity === "CRITICAL"` 或明确 system unavailable -> `critical`；
- Event `PENDING_HUMAN_REVIEW` 且 Decision requires human review ->
  `approval_required`；
- HIGH severity、FAILED、ESCALATED、NEEDS_MORE_EVIDENCE 等需要关注状态 ->
  `attention`，除非已匹配更高优先级；
- 新的非操作性事件/通知 -> `informational`；
- 队列为空 -> `idle`。

具体 mapping 应在 F04 作为纯函数测试。不能把 `expanded`、dismissed 或 unread
写入 Event/Decision 状态。

### 6.3 多消息队列

- 不同优先级先按上述顺序；
- 同优先级按 `createdAt` 升序，再按稳定 ID 排序；
- 当前 expanded notice 保持稳定；只有新 critical 才显示旁路提示，不自动替换；
- summary 最多显示一条主消息和剩余数量；
- 关闭一条后选择队列中的下一条；
- 更新同一 Event 时合并到同一 notice identity，避免每次轮询重复入队；
- 终态 Event 可从 active queue 移出，但历史仍由 Activity/Audit 提供。

### 6.4 用户关闭与恢复

- 关闭 summary 只折叠到 capsule，并在当前 session 记录 dismiss；
- approval_required/critical 在后端条件未解除前仍保留计数和状态色；
- 新增更高优先级 notice、关联 Event 状态变化或用户点击 Pulse 时恢复；
- 页面刷新后从服务器重新派生，不能把 session dismiss 当业务完成；
- 第一版不持久化 snooze/read schema；若未来需要跨 session 偏好，另建明确的
  presentation preference contract。

### 6.5 减少动画

- 遵守 `prefers-reduced-motion: reduce`；
- Motion 配置使用 reduced motion 模式；
- reduced 时使用即时切换或短透明度变化，不做位移、弹簧、缩放和循环呼吸；
- 严禁闪烁；
- 状态仍用文字、图标、边框和计数表达，不能依赖动画。

### 6.6 避免抢占用户操作

- Pulse/summary 非模态，不锁定背景；
- 自动 summary 不调用 focus、不滚动页面；
- 用户正在输入、确认 dialog 打开或行动面板有未提交内容时延迟自动 summary；
- 新消息先更新胶囊计数，等待安全时机；
- 普通更新使用 `aria-live="polite"`；
- critical 可使用简短 `assertive` 文本，但同一 notice 只播报一次；
- 所有业务动作要求明确点击，并在提交期间防重复；
- 写入成功后以服务器重读结果为准。

## 7. 上下文输入与对话边界

当前没有 conversation API。第一版 IA 为上下文输入保留位置，但实现必须遵循：

- Event facts、风险和确认永远在结构化区域，不埋入消息历史；
- 输入默认绑定当前 Event/Decision/Task context；
- 未定义 capability 时禁用发送并说明原因；
- 不把输入直接发给 Provider endpoint；
- 不把模型文本当成 HumanReview；
- 不用聊天消息伪造 Task、Evidence 或 Audit；
- 不在 F00/F01 假造对话记录。

## 8. 第一版明确排除

用户系统、复杂权限、3D 工厂、WebSocket、小程序、Tauri、Skill 编辑器、Prompt
可视化、多 Agent 群聊和大型分析 Dashboard 均不进入本 IA。
