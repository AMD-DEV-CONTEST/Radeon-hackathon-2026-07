# AlphaNoah Frontend Task Plan

## 1. 执行原则

F01–F06 必须可以独立 review、测试和提交。每个任务开始前重新确认仓库基线和
API；本计划中的 DRAFT endpoint 不是预先授权的实现。

共同约束：

- Runtime/SQLite/状态机语义只能复用，不能复制或绕过；
- Node.js 只用于开发和构建；
- 生产由 Python 托管静态产物；
- 不引入完整重型企业 UI 框架；
- 不实现用户系统、复杂权限、3D、WebSocket、小程序、Tauri、Skill 编辑器、
  Prompt 编排、多 Agent 群聊或大型 Dashboard；
- 每个后端 GET 必须无副作用；
- 每个写操作必须继续通过现有应用/Runtime；
- Windows 和 Linux 都使用跨平台命令。

## 2. 推荐开发顺序

```text
F01 基础与静态交付
  -> F02 Workspace 读取契约
  -> F03 Workspace 主画布
  -> F04 Noah Pulse 与行动面板
  -> F05 Management
  -> F06 上下文输入与发布硬化
```

## F01 — React 基础与 Python 静态交付边界

### 目标

建立可测试、可构建、可由 Python 同源托管的最小前端工程和应用 shell。

### 明确范围

- 新增 `frontend/`；
- React、TypeScript、Vite、React Router、Motion、Lucide；
- 原生 CSS variables/CSS Modules 的基础 tokens；
- `/`、`/events/:eventId` 和 `/management/*` route shell；
- 404/加载/错误边界；
- Vite 开发代理 `/api -> 127.0.0.1:8090`；
- Python HTTP 层增加显式 static root、MIME、缓存和受限 SPA fallback；
- `/api/*` 优先且未知 API 继续返回 JSON 404；
- build artifact 不要求 Node 生产进程。

### 不做什么

- 不实现 Workspace 内容、Pulse、行动面板或 Management 数据；
- 不新增业务 API；
- 不修改 Runtime、Adapter、SQLite 或状态机；
- 不启用 CORS；
- 不添加真实写操作。

### 验收标准

- `npm run build` 产生静态产物；
- Python 服务可以同时返回 `/`、hashed asset 和现有 `/api/*`；
- deep link `/events/<id>` 返回 `index.html`；
- 缺失 asset 和未知 `/api` 不 fallback；
- 无 build 时 API 可按明确策略独立启动或给出清晰启动错误；
- 生产启动不需要 Node；
- Windows/Linux 路径处理一致。

### 测试要求

- frontend type-check、unit test、production build；
- Python static resolver tests：path traversal、dotfile、MIME、cache、fallback、
  method、API priority；
- 全部现有 Python tests；
- `compileall`、`git diff --check`。

### 建议提交信息

`feat(frontend): scaffold React app and static delivery`

## F02 — Workspace 只读 API 与 typed client

### 目标

为 Activity、Event facts、Notice queue 和行动面板提供最小安全读取契约。

### 明确范围

- 审核后实现 Event feed、安全 EventSummary、Notice feed 和 action-card read
  projection 中获批的最小集合；
- route-specific allowlisted pagination query；
- opaque cursor、stable ordering、observed_at；
- 只读应用 projection service，不直接 SQL；
- frontend typed fetch client、wire types、mappers、error mapping；
- fixture 明确覆盖 null Decision/null Task/空 Evidence/unknown status。

### 不做什么

- 不增加业务写 endpoint；
- 不触发 Provider、Skill resolution、Knowledge retrieval、Notification 创建或
  状态迁移；
- 不返回 raw_input_ref、arbitrary metadata、prompt、secret、文件路径或完整
  Audit details；
- 不实现页面视觉。

### 验收标准

- 新 GET 在重复调用下不改变数据库和 Audit；
- feed 可以发现 Event，不要求前端预先知道 event_id；
- action-card 字段全部可追溯到 Runtime 对象；
- Notification `CREATED` 不被映射为 delivered/read；
- 前端对 unknown enum fail visibly；
- 现有 7 个 API 行为完全不变。

### 测试要求

- Adapter/application projection unit tests；
- loopback HTTP contract tests；
- 无副作用/Provider call count tests；
- pagination/cursor/limit/error/redaction tests；
- TypeScript mapper fixture tests；
- 全量 Python 和 frontend checks。

### 建议提交信息

`feat(web): add safe workspace read projections`

## F03 — Workspace 主画布与 Activity

### 目标

实现非 Dashboard 化的主要工作台：现场状态、Event 活动流和可恢复 deep link。

### 明确范围

- Workspace shell；
- last-updated、stale/offline 明示；
- Event activity list 和 severity/status 表达；
- `/events/:eventId` 选择状态；
- 页面可见性驱动的有限轮询、退避和手动刷新；
- 智能指令输入的视觉入口和本地导航/筛选能力；
- 未具备 conversation capability 时清楚禁用远端发送。

### 不做什么

- 不实现 Pulse 行为和完整行动面板；
- 不发送聊天/Provider 请求；
- 不自动分析、确认、创建/开始 Task；
- 不做大型图表、3D 或 WebSocket。

### 验收标准

- 用户能从 Activity 打开并 deep-link 一个 Event；
- loading/empty/error/stale 状态完整；
- Event 事实缺失时显示 unavailable，不使用 fixture 补齐；
- 后台 tab 降低或停止轮询；
- 列表更新不抢焦点、不重排当前选择；
- 键盘可完成导航。

### 测试要求

- Workspace route/component tests；
- polling fake-timer、visibility、retry tests；
- empty/error/stale/unknown enum fixtures；
- accessibility smoke tests；
- production build 和 Python 回归。

### 建议提交信息

`feat(frontend): add workspace activity surface`

## F04 — Noah Pulse、行动面板与现有人工操作

### 目标

实现低干扰 Noah Pulse、结构化 AgentActionCard，以及现有 review/evidence 操作。

### 明确范围

- idle/informational/attention/approval_required/critical/expanded；
- 确定性 notice priority、dedupe、queue、session dismiss；
- capsule、summary、non-modal action panel；
- Event facts、analysis、risk、knowledge、Task/Evidence、timeline；
- 现有 approve/reject；
- 现有 text evidence submit（只在 capability 允许时）；
- reduced motion、aria live、focus safety；
- 写成功/结果不明后重新读取。

### 不做什么

- 不把 dismiss 当作业务处理；
- 不实现自动批准、自动 Task 创建/开始、final review 或设备控制；
- 不上传文件；
- 不乐观修改 Event/Decision/Task 状态；
- 不实现 conversation。

### 验收标准

- priority 固定为 critical > approval > attention > information；
- 同优先级顺序稳定；
- 自动行为最多 capsule -> 非模态 summary；
- expanded 只由用户/deep link 进入；
- 用户输入中不自动抢焦点；
- approval 未解除时关闭 summary 后仍保留可见计数；
- POST 防重复，错误按 error_code 显示；
- reduced motion 下无位移/循环动画。

### 测试要求

- Pulse policy 纯函数 table tests；
- queue dedupe/dismiss/recovery tests；
- reduced-motion/focus/keyboard/aria tests；
- approve/reject/evidence success、409、网络结果不明 tests；
- Python API 回归和 frontend build。

### 建议提交信息

`feat(frontend): add Noah Pulse and action panel`

## F05 — Management 只读空间

### 目标

提供简洁的数字岗位、Skill、Provider、Edge node 和系统状态视图。

### 明确范围

- 经单独审计后增加必要的只读 management/health projections；
- DigitalRole 只映射 ResponsibilityDirectory；
- SkillSummary 不暴露 analysis instructions；
- Provider 使用现有 config/discovery status，隐藏 credential value；
- Edge node 仅在正式模型/API 存在时显示；
- SystemHealth 使用确定性汇总和 checkedAt；
- Management 子导航、列表、详情摘要、空/未知状态。

### 不做什么

- 不编辑 Skill/Prompt；
- 不自动安装服务、下载模型、切换 Provider 或执行 smoke；
- 不创造虚构 Edge node；
- 不增加用户/权限后台；
- 不把 ResponsibilityAssignment 宣称为自治 Agent。

### 验收标准

- 每个字段有明确后端来源；
- API 不返回 secret、本机敏感路径或任意 config；
- unavailable/not configured/credential missing 清楚区分；
- 没有 Edge node 数据时显示“尚无契约”，不是假数据；
- Management 不影响 Workspace 轮询和当前 Event。

### 测试要求

- management projection/redaction/no-side-effect tests；
- health deterministic aggregation tests；
- route、empty/error/unknown status、keyboard tests；
- secret-shape scan；
- 全量 Python/frontend checks。

### 建议提交信息

`feat(frontend): add read-only management space`

## F06 — 上下文输入契约、可访问性与发布硬化

### 目标

在不把聊天变成产品主体的前提下完成上下文输入边界，并把第一阶段前端硬化为可发布
artifact。

### 明确范围

- 先审计并批准最小 REST context interaction contract；无获批 API 时发送保持禁用；
- 输入显式绑定 Event/Decision/Task context；
- response 作为分析辅助内容显示，不伪装成 HumanReview/Task/Audit；
- 完整键盘路径、screen reader labels、contrast、reduced motion；
- error recovery、offline/stale、unknown capability；
- frontend unit/integration/e2e smoke；
- 静态 artifact manifest、版本信息、缓存验证；
- Windows/Linux 原生启动文档和 release checklist。

### 不做什么

- 不实现多 Agent 群聊、长期聊天平台、WebSocket；
- 不让模型执行 HumanReview 或设备控制；
- 不保存 secret；
- 不扩展为复杂权限/用户系统；
- 不引入 Node 生产 server。

### 验收标准

- 结构化 facts/risks/actions 始终比 conversation 更显著；
- 无 capability 时没有网络发送；
- 模型内容不会自动改变任何 Runtime 状态；
- WCAG 关键路径检查通过；
- production artifact 可由干净环境构建并由 Python 托管；
- API/static cache/fallback 安全回归通过；
- release 不包含 source map、secret 或本地数据库。

### 测试要求

- context boundary/unsupported capability tests；
- keyboard、focus、live region、reduced motion、contrast tests；
- browser smoke：Workspace -> Event -> review -> refreshed state；
- clean build/reproducibility/static manifest tests；
- 全量 Python tests、compileall、frontend type-check/test/build、
  `git diff --check` 和敏感信息扫描。

### 建议提交信息

`feat(frontend): harden contextual workspace release`

## 3. 每个任务的提交门槛

每个 F01–F06 在提交前至少确认：

1. 变更范围只包含当前任务；
2. Runtime/SQLite/state-machine diff 已审阅；
3. 现有 API contract regression 通过；
4. 新增依赖有必要性和 license 记录；
5. Python 全量 tests 与 compileall 通过；
6. frontend type-check/test/build 通过（F01 起）；
7. `git diff --check` 通过；
8. 无 `.env`、key、token、数据库、模型、source map 或本机路径；
9. Windows/Linux 命令不依赖单一 shell；
10. 文档中的 CURRENT/DRAFT 状态与代码一致。
