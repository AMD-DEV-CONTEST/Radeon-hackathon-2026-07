# AlphaNoah Digital Employee Frontend Model

> F03-B Product Architecture Review
> 状态：前端展示层设计。本文件不新增 DigitalEmployee Runtime aggregate，不修改
> Skill、SkillResolver、Event/Task 状态机、API、SQLite、权限或执行语义。

## 0. 结论与边界

“数字员工”是企业用户理解 AlphaNoah 能力的产品投影，不是当前 Runtime 中已经存在
的实体。

```text
企业产品语言                  当前工程事实

Digital Employee
├─ 职责                       ResponsibilityAssignment（按 Event 决定）
├─ 能力模块                   SkillDefinition / SkillContext
├─ 当前工作                   Event / Decision / Task 的只读摘要
├─ 工作记录                   安全 Audit/Timeline 的产品化投影
├─ 知识范围                   Skill hint / Event knowledge provenance 的摘要
└─ 权限说明                   未来受审计的能力说明；当前没有权限系统
```

F03-B 只用确定性 Mock 建立该产品语言。页面必须明确标识数据源，不能让用户误以为
Mock 员工、在线状态、绩效数字或权限已经由 Runtime 提供。后续真实读取仍遵守
F03-A 的单向边界：

```text
Runtime 安全读取投影
        ↓
wire DTO / decoder
        ↓
DigitalEmployee Adapter
        ↓
DigitalEmployee View Model
        ↓
Provider / hooks
        ↓
/employees UI
```

前端 Adapter 不调用 `SkillResolver`。未来执行链仍由后端拥有：

```text
Event
  ↓
Responsibility routing / product binding
  ↓
SkillResolver（后端确定性解析）
  ↓
SkillContext
  ↓
Runtime / Provider
```

Digital Employee 不能绕过、重命名或复制这条执行链，也不能在浏览器中选择 Skill
或推演 Runtime 状态。

## 1. 企业产品定义

### 1.1 数字员工是什么

数字员工是一个只读展示聚合，用企业岗位语言回答：

- 它叫什么、承担什么职责；
- 它由哪些能力模块支撑；
- 当前是否有可观测的工作活动；
- 今天处理了多少工作、还有多少待处理；
- 最近完成或等待了什么；
- 能使用哪些知识范围，受到什么操作边界约束。

它是“职责 + 能力 + 工作上下文”的入口，不是一个聊天人格，也不代表浏览器里运行
了自治 Agent。工作记录以 Event/Task/Audit 事实为主，不以消息气泡为主。

### 1.2 DigitalEmployee 不等于 Skill

| 概念 | 职责 | 基数关系 | 生命周期所有者 |
|---|---|---|---|
| DigitalEmployee | 面向企业的岗位、能力和工作展示聚合 | 一个员工可展示多个能力模块 | 当前仅前端产品投影 |
| SkillDefinition | 有边界的分析指导、匹配条件、升级规则和知识查询提示 | 一个 Skill 可被未来多个岗位复用 | Runtime，只有 active/deprecated |
| SkillContext | Resolver 为一个 Event 解析出的明确分析上下文 | 每次解析恰好返回一个或失败 | Runtime |
| ResponsibilityAssignment | 为一个 Event 选择责任 owner | 每次路由返回一个 assignment | Runtime |
| Task | Decision 产生的工作对象 | 当前通过 assignee 文本指派 | Runtime |

DigitalEmployee 不能被解释为 Skill 包装器。当前仓库也不存在
DigitalEmployee-to-Skill、DigitalEmployee-to-Task 或 owner-to-employee 的持久化
关系。F03-B Mock 可以表达合理的产品组合，但必须保留 `source: "mock"`，不得把这
些组合声明成 Runtime 事实。

## 2. 已审计的真实 Runtime 事实

### 2.1 Skill

`src/alphanoah_a1/skill.py` 中的真实 `SkillDefinition` 字段为：

```text
skill_id
version
status: active | deprecated
analysis_instructions
supported_event_types[]
supported_asset_types[]
escalation_rules[]
knowledge_query_hints[]
```

真实约束：

- Skill 是不可变的声明式对象，没有可执行 hook；
- `SkillStatus` 只有 `active` 和 `deprecated`；
- 只有 active Skill 能产生 `SkillContext`；
- `SkillContext` 包含 Skill ID/version、analysis instructions、escalation rules、
  knowledge query hints 和 resolution reason；
- `DeterministicSkillResolver` 只按 Event 的 `event_type`、metadata 中的
  `asset_type` 做确定性匹配；
- generic fallback Skill 被禁止；
- 没有匹配、只有 deprecated 匹配或最高特异度冲突都会明确失败；
- Skill definitions 当前是 Python 内存定义，不是 SQLite aggregate，也没有列表
  API；
- 仓库包含两个 synthetic demo declarative Skills，以及一个内置 synthetic
  cold-holding Skill；这些都不能被宣称为生产数字员工。

公开 Web Adapter 只会在已知 Event 的详情/analysis 投影中返回已解析的
`skill_id`、`skill_version`，analysis 读取还可返回该 Event 的安全
`knowledge_sources`。它不公开 Skill 列表、Skill 详情、
`analysis_instructions`、员工绑定或能力模块名称。

### 2.2 Responsibility、Task 与工作记录

- `ResponsibilityDirectory` 从受审查的本地 JSON 规则按
  `asset_id → location → event_type` 固定顺序，为一个 Event 返回
  `owner_id`、`owner_name`、`match_type` 和 `matched_key`；
- 未匹配时返回 `UNASSIGNED`；
- 示例 responsibility directory 明确标记为 synthetic demo，不是员工目录；
- ResponsibilityAssignment 是 Event 路由结果，不是数字员工档案；
- Task 的 `assignee` 是字符串，没有 DigitalEmployee foreign key；
- 当前 HTTP 只能按已知 Event ID 读取一个 Task 的 ID/status/owner，不能列出某个
  员工的任务；
- Timeline 只按已知 Event ID 返回安全 Audit 子集，不能按员工查询；
- 当前没有员工指标、员工在线状态、员工知识库、员工工作记录或员工权限 API。

因此，F03-B 不得用 Task assignee 或 Responsibility owner ID 自动“拼出”真实员工，
也不得从 HTTP 连通性推导员工在线。

## 3. 数据职责与来源

来源分为：

- **Runtime**：当前后端已有且可安全读取的事实；
- **Product projection**：未来需要独立、安全、只读契约组合的产品字段；
- **F03-B Mock**：本阶段确定性展示数据，不代表 Runtime 事实。

| 字段 | 产品职责 | 当前可用来源 | F03-B 策略 | 未来真实来源 |
|---|---|---|---|---|
| `id` | 稳定路由和关联键 | 无员工 ID | Mock 稳定 ID | DigitalEmployee read projection |
| `name` | 企业可理解的岗位名 | Responsibility 有 event-scoped owner name，但不是员工名 | Mock 产品文案 | 受审查的岗位目录 |
| `description` | 一句话说明职责边界 | 无 | Mock，可为 null | 岗位产品配置 |
| `status` | 最近观测的可用/工作状态 | 无 | Mock，明确 observedAt | presence/health 聚合 |
| `stage` | 产品成熟度展示 | 无 | Mock | 产品配置，只读 |
| `responsibilities` | 负责的业务范围 | 有 event-scoped routing 事实，无可枚举 API | Mock | 安全责任目录投影 |
| `skills` / `capabilityModules` | 将 Skill 解释为企业能力 | SkillDefinition 有技术匹配字段，无产品名称/列表 API | Mock 能力名称；可附非展示 source ref | Skill list + 产品 metadata + binding |
| `currentTasks` | 当前相关工作 | 有 Task，但无员工关联和列表 API | Mock | 员工任务 read projection |
| `todayMetrics` | 今日 handled/pending 摘要 | 无聚合 API | Mock；未知用 null | 有时间窗定义的只读指标 |
| `workRecords` | 最近事实化工作轨迹 | 单 Event timeline，无员工关联 | Mock | 安全 Audit/Task projection |
| `knowledge` | 可用知识范围/来源摘要 | Skill query hints；单 Event knowledge sources | Mock；不得把 hint 当知识内容 | 受控 knowledge catalog/provenance |
| `permissionSummary` | 人可理解的操作限制 | 当前无权限系统 | Mock 说明文字，不启用操作 | 认证授权后的 capability projection |

### 3.1 null、unknown 与数据质量

- 不知道的业务值使用 `null`，未知枚举保留 raw 值并显示 `unknown`；
- 空数组表示“已读取且没有项目”，`null`/`unavailable` 表示“当前不能读取”，二者
  不能混用；
- `0` 只表示确认过的零，不能作为缺失 metric 的默认值；
- 时间必须有来源；不能用浏览器当前时间冒充 `observedAt`；
- Skill `knowledge_query_hints` 是检索提示，不是已授权知识内容；
- Skill `analysis_instructions` 不进入 Digital Employee UI；
- `permissionSummary` 只说明边界，不能产生 `canApprove=true` 等授权判断；
- 未知 ID、未知 status/stage 或数据源错误不能回退到另一个 Mock 员工。

建议所有 aggregate 和子投影沿用 F03-A `DataQuality`：

```ts
interface DataQuality {
  availability: "available" | "partial" | "unavailable";
  unknownFields: readonly string[];
  contractWarnings: readonly string[];
}
```

## 4. 展示生命周期

```ts
type DigitalEmployeeStage =
  | "intern"
  | "trial"
  | "production"
  | "paused"
  | "retired";
```

这五种 stage **只是数字员工中心的只读产品展示状态**，不是后端状态机、Skill
status、Event/Task 状态、权限等级或自动化开关。F03-B 不定义迁移、不提供变更按钮，
也不根据 stage 决定 Runtime 是否允许执行。

| Stage | 企业含义 | 视觉语义 | 明确不代表 |
|---|---|---|---|
| `intern` | 观察学习期，帮助理解现场，输出需谨慎解释 | 中性/信息色，标注“观察” | 模型正在训练、可读取全部数据 |
| `trial` | 试岗辅助期，产品文案强调人工确认 | attention 色，标注“需确认” | Runtime 自动设置 human review |
| `production` | 已稳定用于定义好的职责范围 | 稳定信息色，避免大面积绿色 | 自动批准、无限权限或 SLA |
| `paused` | 暂停展示为当前可调度能力 | muted/warning，清楚写“暂停” | Event CANCELLED、Task PAUSED（不存在该状态） |
| `retired` | 历史保留，不再作为当前岗位入口 | muted，降低层级但保持可读 | Skill deprecated 或数据删除 |

Stage 与 SkillStatus 独立。例如 production 员工可能包含一个未知/不可读取的能力
模块；retired 员工也不能使 Runtime Skill 自动 deprecated。

## 5. 前端 View Model

### 5.1 文案与枚举策略

继续复用 F03-A 的 `ViewText`，避免数字员工 feature 再造一套翻译类型：

```ts
type ViewText =
  | { readonly kind: "literal"; readonly value: string }
  | { readonly kind: "message"; readonly id: string };

type DigitalEmployeeOperationalStatus =
  | "online"
  | "offline"
  | "working"
  | "unknown";
```

- Mock 产品文案用 `{ kind: "message", id }`，由现有 `I18nContext.text()` 解析；
- 未来后端安全显示文本用 `literal`，不能作为翻译 key；
- status/stage 的标签由 UI translation key 映射，不把中文或英文写进 adapter；
- 未知 raw 枚举保存在模型中，不能 cast 成 online/production；
- 名称和企业专有名词是否本地化由产品配置决定，不由组件猜测。

### 5.2 主模型

```ts
interface DigitalEmployeeView {
  readonly id: string;
  readonly name: ViewText;
  readonly description: ViewText | null;

  readonly status: DigitalEmployeeOperationalStatus;
  readonly rawStatus: string | null;
  readonly statusLabel: ViewText;
  readonly statusObservedAt: string | null;

  readonly stage: DigitalEmployeeStage | "unknown";
  readonly rawStage: string | null;
  readonly stageLabel: ViewText;

  readonly responsibilities: readonly ResponsibilityView[];
  readonly skills: readonly CapabilityModule[];
  readonly currentTasks: readonly CurrentTaskView[];
  readonly todayMetrics: TodayMetricsView;
  readonly workRecords: readonly WorkRecord[];
  readonly knowledge: readonly KnowledgeScopeView[];
  readonly permissionSummary: PermissionSummaryView;

  readonly quality: DataQuality;
}
```

字段名保留 `skills` 是为了表达来源关系，页面标题和用户文案统一使用“能力模块”，
不显示 Skill ID、prompt 或 analysis instructions。

### 5.3 子模型

```ts
interface ResponsibilityView {
  readonly id: string;
  readonly label: ViewText;
  readonly scope: ViewText | null;
  readonly quality: DataQuality;
}

interface SkillSummary {
  // Adapter 内部安全来源摘要，不直接渲染技术标识。
  readonly skillId: string;
  readonly version: string;
  readonly runtimeStatus: "active" | "deprecated" | "unknown";
  readonly rawRuntimeStatus: string;
  readonly supportedEventTypes: readonly string[];
  readonly supportedAssetTypes: readonly string[];
  readonly quality: DataQuality;
}

interface CapabilityModule {
  readonly id: string;
  readonly name: ViewText;
  readonly description: ViewText | null;
  readonly availability:
    | "available"
    | "limited"
    | "unavailable"
    | "unknown";
  readonly sourceSkill:
    | {
        readonly skillId: string;
        readonly version: string;
      }
    | null;
  readonly quality: DataQuality;
}

interface CurrentTaskView {
  readonly id: string;
  readonly title: ViewText;
  readonly runtimeStatus: string | null;
  readonly statusLabel: ViewText;
  readonly updatedAt: string | null;
  readonly eventId: string | null;
  readonly quality: DataQuality;
}

interface TodayMetricsView {
  readonly handled: number | null;
  readonly pending: number | null;
  readonly windowStartedAt: string | null;
  readonly observedAt: string | null;
  readonly quality: DataQuality;
}

interface WorkRecord {
  readonly id: string;
  readonly occurredAt: string | null;
  readonly occurredLabel: ViewText | null;
  readonly title: ViewText;
  readonly detail: ViewText | null;
  readonly kind:
    | "event_detected"
    | "analysis"
    | "knowledge_lookup"
    | "human_review"
    | "task"
    | "evidence"
    | "completed"
    | "unknown";
  readonly eventId: string | null;
  readonly taskId: string | null;
  readonly rawAction: string | null;
  readonly quality: DataQuality;
}

interface KnowledgeScopeView {
  readonly id: string;
  readonly label: ViewText;
  readonly sourceType:
    | "skill_hint"
    | "event_provenance"
    | "product_projection"
    | "unknown";
  readonly quality: DataQuality;
}

interface PermissionSummaryView {
  readonly mode: "read_only" | "human_confirmed" | "unknown";
  readonly label: ViewText;
  readonly constraints: readonly ViewText[];
  readonly isAuthoritative: false;
  readonly quality: DataQuality;
}
```

`CapabilityModule.availability` 是显示可用性，不是 Skill 的新状态机。
`SkillSummary.runtimeStatus` 必须保留真实 active/deprecated/unknown；映射规则只决定
如何解释，不能写回 Runtime。`WorkRecord` 是审计事实摘要，不是聊天消息，也不包含
模型思维链、prompt、原始 response 或任意 Audit details。

### 5.4 集合模型

```ts
interface DigitalEmployeeCollection {
  readonly source: "mock" | "http";
  readonly employees: readonly DigitalEmployeeView[];
  readonly observedAt: string | null;
  readonly quality: DataQuality;
}
```

列表与详情从同一 collection 选择可避免详情出现另一套 Mock。详情查询未来若使用
独立 endpoint，也必须返回相同 `DigitalEmployeeView`。

## 6. Adapter 与 Runtime 的关系

未来映射应保持：

| 真实来源 | Adapter 行为 | 产品投影 |
|---|---|---|
| Responsibility owner/rules | 仅在有正式 read projection 和明确绑定时映射 | responsibilities / identity hint |
| SkillDefinition safe fields | decoder 后保留 ID/version/raw status；过滤 instruction | SkillSummary |
| SkillSummary + 产品 metadata | 组合企业名称和说明 | CapabilityModule |
| Event/Decision/Task | 只读、安全、按员工明确关联 | currentTasks / metrics |
| safe Timeline/Audit | action 白名单、去敏、稳定排序 | WorkRecord |
| knowledge query hints | 标记为 hint，不冒充知识内容 | KnowledgeScopeView |
| capability/authorization projection | 仅在后端权威契约存在后映射 | PermissionSummaryView |

Mock 不应模拟 wire DTO 或伪造现有 endpoint。Mock builder 直接生成产品 View Model，
并以固定时钟/固定 ID 保证测试确定性。未来 Http data source 必须经 decoder 与
adapter，缺 endpoint 时 fail-closed，不得暗中回退 Mock。

## 7. 推荐 feature 目录与数据源

```text
frontend/src/features/digital-employees/
├── components/
│   ├── EmployeeRosterItem.tsx
│   ├── EmployeeIdentity.tsx
│   ├── CapabilityModuleList.tsx
│   ├── WorkRecordList.tsx
│   └── EmployeeState.tsx
├── pages/
│   ├── DigitalEmployeeListPage.tsx
│   └── DigitalEmployeeDetailPage.tsx
├── types/
│   ├── digitalEmployee.ts
│   └── dataSource.ts
├── provider/
│   ├── DigitalEmployeeProvider.tsx
│   ├── useDigitalEmployees.ts
│   └── useDigitalEmployee.ts
├── mock/
│   ├── mockDigitalEmployees.ts
│   └── MockDigitalEmployeeDataSource.ts
└── index.ts
```

未来有真实契约后再增加：

```text
api/
├── digitalEmployeeDtos.ts
├── digitalEmployeeDecoders.ts
└── HttpDigitalEmployeeDataSource.ts
adapter/
├── digitalEmployeeAdapter.ts
├── capabilityModuleAdapter.ts
└── workRecordAdapter.ts
```

数据源接口建议：

```ts
interface DigitalEmployeeDataSource {
  readonly source: "mock" | "http";
  getInitialCollection(): DigitalEmployeeCollection | null;
  getEmployees(options?: {
    signal?: AbortSignal;
  }): Promise<DigitalEmployeeCollection>;
}
```

- source 选择只发生在 App composition root；
- 页面、组件和路由不 import Mock；
- hooks 从一个 collection 选择 list/detail，不重复读取；
- 与 WorkspaceDataSource 分开，避免员工目录刷新导致 Workspace snapshot 重读；
- 复用 F03-A 的 abort、旧请求隔离、last-known-on-error 原则；
- 若未来 API 详情不可从集合满足，再扩展显式 `getEmployee(id)`，而不是在组件 fetch。

`ViewText` 和 `DataQuality` 第一版复用 F03-A 的公共类型，避免重复定义。若更多
feature 复用，再单独提取到中立 presentation core；F03-B 不为此重构 F03-A。

## 8. 路由、错误与可访问性

### 8.1 路由

```text
/employees        数字员工列表
/employees/:id    数字员工详情
```

- 保留现有 Workspace shell、主题、locale、Motion 和 Noah Pulse；
- 列表项使用真实链接，支持复制、刷新和浏览器前进/后退；
- 未知 `:id` 显示员工详情范围内的 not-found，不静默跳回第一个员工，也不把整个
  App 重定向到 `/`；
- `/employees/` 规范化行为保持一致；
- 员工详情返回列表时保留可理解的导航位置。

### 8.2 loading、empty、partial、error

- loading：保留页面结构和明确文本，不伪造员工卡；
- empty：说明“当前数据源没有数字员工”，不是系统故障；
- partial：已知字段继续展示，未知字段显式为“暂无数据/未知”；
- error 且有 last-known collection：继续显示并标记数据可能陈旧；
- error 且无数据：显示可恢复错误和重试入口；
- unknown ID：独立 not-found；
- Http source unavailable：明确“读取契约尚不可用”，不展示 Mock。

### 8.3 可访问性

- 页面使用 `main`、列表使用语义 list、详情分区使用有层级的 heading；
- 整个列表项是可聚焦链接，不在链接中嵌套按钮；
- status/stage 同时提供文字和图形，不能只靠颜色；
- 在线圆点等装饰图形 `aria-hidden`，状态文字可被读屏读取；
- 当前导航使用 `aria-current="page"`；
- 动效遵守现有 `MotionConfig` 和 `prefers-reduced-motion`，不使用无限呼吸/闪烁；
- 键盘焦点清晰，返回、重试等操作目标不小于现有 Design System 标准；
- dark/light 均满足正文、辅助文字、状态标签和焦点环对比度；
- 时间用 `<time datetime>`；未知时间不制造 datetime。

## 9. 产品信息架构

### 9.1 列表：5 秒内回答四个问题

`/employees` 首屏依次表达：

1. **有哪些员工**：岗位名和一句职责说明；
2. **谁在线/工作中**：状态文字、最后观测时间；
3. **负责什么**：2–4 条职责摘要，不列内部 Skill；
4. **今日状态**：handled、pending；未知时明确未知，不显示假零。

推荐结构：

```text
数字员工中心
├─ 数据源/观测时间（低干扰）
└─ 员工名册
   ├─ 身份 + status + stage
   ├─ 职责摘要
   ├─ 今日 handled / pending
   └─ 查看详情
```

不是 Admin Table，不使用大面积 KPI Dashboard，也不把每个 Skill 做成主卡片。

### 9.2 详情：回答职责、能力、任务和最近工作

`/employees/:id` 信息顺序：

1. 基本身份、status、stage、数据新鲜度；
2. 工作职责；
3. 能力模块（Skill 的产品化名称，不显示 Skill ID/prompt）；
4. 当前任务；
5. 最近工作记录；
6. 知识范围与操作边界（次级信息）。

工作记录采用时间线/事实列表：

```text
10:32  发现设备温度异常
10:33  查询已授权的历史故障来源
10:35  等待人工确认
```

它不是聊天记录：没有用户/Agent 气泡、输入框、typing indicator、消息已读或模型
思维链。点击关联 Event/Task 只能跳转到已有只读上下文，不产生写操作。

## 10. F03-B 明确不做

- 不创建、编辑、复制、删除或自然语言生成数字员工；
- 不修改 Runtime、SQLite、SkillDefinition、SkillResolver、状态机、API 或 Docker；
- 不增加 Skill 管理、Skill 选择器、Skill/Prompt 编辑器；
- 不显示 analysis instructions、prompt、原始模型响应或敏感 Audit details；
- 不实现用户、角色、权限、审批授权或设备控制；
- 不把展示 stage 当作自动化/权限开关；
- 不实现真实聊天、WebSocket、SSE 或轮询；
- 不实现真实 API、任务审批、Event 写操作或员工写操作；
- 不根据 Responsibility owner、Task assignee 或 Skill ID 猜测真实员工关系；
- 不把 Mock 数据混入 Runtime Workspace snapshot。

## 11. 未来 API 缺口（只记录）

当前不存在任何 DigitalEmployee API。未来至少需要单独审计：

```text
GET /api/management/digital-employees
GET /api/management/digital-employees/{employee_id}
```

只读契约需要定义：

1. 稳定 employee identity 与安全 display metadata；
2. employee ↔ responsibility rules 的正式关系；
3. employee ↔ Skill ID/version 的版本化 binding，以及安全能力名称；
4. status 的观测来源、`observed_at`、stale/unknown 语义；
5. stage 的配置所有者和只读投影；
6. employee ↔ Event/Task 的明确关联，不能只按 assignee 文本猜测；
7. 有界时间窗口的 handled/pending 指标定义；
8. 分页、稳定排序、opaque cursor 的工作记录；
9. knowledge 范围和 provenance 的安全摘要；
10. 经认证授权系统产生的 capability summary；在此前只能 unknown/read-only；
11. projection version、snapshot version 和 additive compatibility；
12. 404、未知 enum、partial、redaction 和访问控制错误。

这些 endpoint 不能返回 prompt、analysis instructions、credential、任意本机路径、
原始 Audit details 或模型思维链。F03-B 不实现这些 API，也不为页面新增临时 Python
路由。

## 12. 测试建议

### 12.1 类型、映射与数据源

- stage 五态与 unknown 的显示映射 table test；
- status online/offline/working/unknown 的标签和 tone table test；
- 不支持的 raw status/stage 被保留并显示 unknown；
- metric null 与 0 有不同输出；
- capability module 不渲染 Skill ID、prompt 或 analysis instructions；
- work record 按可靠 timestamp/固定 fallback 稳定排序；
- Mock data source list/detail 一致、ID 固定、无计时器、无网络；
- empty、partial、error、last-known 和 unknown ID；
- source 切换不泄漏上一 source 的员工 collection；
- abort/stale response 不覆盖新结果。

### 12.2 路由与回归

- `/employees` 可直接加载并渲染列表；
- `/employees/:id` 可直接加载正确详情；
- unknown ID 显示员工 not-found；
- 浏览器返回和当前导航状态正确；
- zh-CN/en-US 的身份、stage、status、职责和空态均可读；
- light/dark/system 与 reduced motion 继续生效；
- Workspace、Noah Pulse、Action Panel 和 F03-A Provider 回归通过；
- 键盘、focus、heading、list/link、aria-current、状态非纯颜色检查；
- 页面代码无 `fetch`/axios，无 API DTO/Mock 直接 import。

### 12.3 仓库验证

```text
npm run typecheck
npm test
npm run build
Python tests
compileall
git diff --check
```

同时做 scope scan：不得出现 Runtime、SQLite、API、Docker、依赖或 lockfile 变更。

## 13. 视觉验收标准

- 在 5 秒内能回答“有哪些数字员工、谁在线、负责什么、今天状态如何”；
- 详情在一个屏幕滚动上下文内建立“职责 → 能力 → 当前任务 → 最近工作”关系；
- 能力模块是次级内容，页面不出现 Skill ID、prompt 或开发者配置表格；
- 工作记录明显是事实时间线，不像聊天窗口；
- 不使用传统 Admin Table、大面积 KPI、密集卡片墙或 Landing Page Hero；
- 沿用现有 Glass、Design Token、Motion、light/dark 和工业低干扰风格；
- Glass 只表达主画布、列表浮层和详情层级，避免每一行重复 blur；
- green 只用于可信 online/success，working、stage 和未知信息使用各自语义；
- 1366×768 无水平滚动，1440×900 与 1920×1080 保持合理行长和留白；
- 中文、英文切换不截断岗位名、状态标签和职责；
- reduced motion 下不依赖 layout animation 理解页面；
- Mock 来源、观测时间和权限非权威性质清楚但不喧宾夺主。
