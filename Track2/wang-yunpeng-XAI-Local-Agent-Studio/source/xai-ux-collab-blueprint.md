# XAI 终极融合版·交互与协同蓝图（v2 增补）

> 本文件是 `xai-ultimate-blueprint-v2.md` 的**定向增补**，专门回答三个被反复追问的问题：
> 1. 画布拖拽功能应该在哪些环节、哪些功能页面实现？
> 2. 整个软件的架构要是什么样的交互形式？（WorkBuddy 式？扣子式？还是别的？）
> 3. 有没有加入多 Agent 协作，甚至「多 Agent 群聊」？GitHub 上那些模块（Octo-Vec / Agent Hub / OllamaFlow / MemOS / TrueAgent）怎么融进来？
>
> 引擎层、底座层、治理平面、Port/Adapter、升级策略等**已在 v2 定义，本文不再重复**，只做引用。
> 当前状态：规划讨论阶段，未改系统代码/前端。

---

## 0. 一句话结论（给审计 AI 先看）

- **交互形态 = 三入口合一的中台**：① 指挥台（WorkBuddy 式聊天）② 画布（扣子式 DAG 拖拽）③ 智能体群（Slack/Discord 式多 Agent 群聊 + Octo-Vec 看板）。三者共享同一个 XAI 引擎，不是三套系统。
- **画布拖拽只出现在 3 个页面**（Workflow 主画布 / Agents 能力组合画布 / Tasks 自动化编排），**绝不在画布里「加载 skill / MCP 节点」**——那会把环境层坍进执行层（v2 §9 已列为反模式）。
- **多 Agent 协作 + 群聊：已纳入**。它既体现在画布的「Agent 节点」（结构化流水线协作），也体现在独立的「智能体群 Agent Hub」页面（自由讨论群聊）。底层统一走 `Orchestrator` + `CoordinationPort` + 本地消息总线（参考 Octo-Vec / Agent Hub）。
- **GitHub 模块全部有落点**（见 §5 映射表），且都经 Port/Adapter 接入，不破坏 v2 的防腐层。

---

## 1. 整体交互形态：不是二选一，是「三入口中台」

### 1.1 与两类标杆的对比

| 维度 | WorkBuddy | 扣子(Coze) | 我们 XAI 中台 |
|---|---|---|---|
| 主交互 | 左侧栏 + 中部聊天 + Artifacts | 工作区 → Bot 编辑器 → 工作流画布 | **三入口并存**（见下） |
| 画布 | 弱（无 DAG 画布） | 强（节点拖拽 + 连线） | 强（扣子式 DAG） |
| 多 Agent | 专家/expert 切换，非群聊 | 多 Agent 在单聊天内协作 | **群聊室 + 画布 Agent 节点 双形态** |
| 治理 | 隐式（权限/审批 skill） | Human-in-loop 节点 | 显式 Guardian 横切 + 群聊审批浮层 |
| 本地优先 | 部分（云端托管） | 否（SaaS） | **完全本地，无云依赖** |

**结论**：我们不是「像 WorkBuddy」或「像扣子」的二选一，而是**把两者的强项焊在一起，再叠一个它们都没有的多 Agent 群聊室**，且全部本地优先。形态上最接近 **「扣子的工作流画布 + WorkBuddy 的指挥台 + 一个本地版 Slack 智能体群」** 的三合一中台。

### 1.2 三入口共享同一引擎（关键：避免重复设计）

```
            ┌────────────────────────────────────────────┐
            │             XAI 编排引擎（唯一大脑）          │
            │  intent_router · control_loop · Guardian    │
            │  Meta · Runner · Distill · Orchestrator     │
            └───────────────────┬────────────────────────┘
                                │ 统一经 Substrate/Capability Port 调度
        ┌───────────────────────┼───────────────────────┐
        ▼                       ▼                       ▼
  ┌───────────┐         ┌──────────────┐        ┌──────────────┐
  │ 入口①指挥台 │         │ 入口②画布     │        │ 入口③智能体群 │
  │(WorkBuddy式│         │(扣子式 DAG)   │        │(群聊+看板)   │
  │ 聊天)      │         │              │        │              │
  └───────────┘         └──────────────┘        └──────────────┘
```

三个入口**都只是 XAI 引擎的不同 UI 呈现**，背后是同一套 `control_loop`、同一套 `Guardian`、同一套底座。用户在指挥台说的话、在画布拖的 DAG、在群聊里派的任务，最终都汇入引擎的同一调度环。**这是避免「三套逻辑互相打架」的根本约束**。

---

## 2. 功能页面与导航结构

采用 **左侧栏导航 + 中部主区 + 右侧检查器** 的经典中台布局（类似扣子工作区 / digit-opus-hub / Clawith）。左栏固定，主区随选中页面切换。

| # | 页面 | 交互形态 | 是否有拖拽画布 | 职责 |
|---|---|---|---|---|
| 1 | **工作台 Dashboard** | 卡片/状态总览 | 否 | 概览：最近任务、Agent 在线状态、治理待办、记忆水位、自进化队列 |
| 2 | **指挥台 Command** | 聊天 + Artifacts（WorkBuddy 式） | 否 | 直接自然语言对话 XAI 引擎；A2UI 事件流（thinking/tool_call/interrupt）；随手派任务 |
| 3 | **画布 Workflow** | DAG 拖拽画布（扣子式） | **是（主画布）** | 编排执行流程：触发器→Agent步骤→工具调用→分支→记忆操作→人工闸门→模型路由 |
| 4 | **智能体 Agents** | 表单 + 能力组合画布 | **是（能力组合画布）** | 定义 Agent 工牌：拖入技能/工具/记忆作用域/模型画像，配置角色与权限 |
| 5 | **技能 Skills** | 列表 + 编辑器 | 否 | 管理 skill 库（SKILL.md frontmatter、优先级、渐进披露） |
| 6 | **连接 Connections(MCP)** | 列表 + 配置表单 | 否 | 管理 MCP 服务器：添加/信任/暴露工具，全局注册一次 |
| 7 | **记忆 Memory** | 层级可视化 + 检索 | 否 | 7 层记忆水位（工作/长期/锚点/反思/因果链/日记/用户画像）、engine 标签、跨引擎查询 |
| 8 | **任务与自动化 Tasks** | 列表 + 触发器编排 | **是（自动化轻量画布）** | cron/事件触发器 → 绑定某个画布工作流；一次性/重复调度 |
| 9 | **智能体群 Agent Hub** | 群聊 + 看板（Slack + Octo-Vec） | 看板（非自由画布） | 多 Agent 实时群聊、PM 派发、Kanban、SAST/成本看板 |
| 10 | **设置 Settings** | 表单 | 否 | 模型画像、治理规则（P0/P1/P2 阈值）、隐私/本地开关、升级锁版本 |

**环境/能力平面 = 页面 4/5/6**（注册一次、全局可用）；**任务/自动化平面 = 页面 8**；**执行/画布平面 = 页面 3**。这正是之前讨论的「三层分离」，UI 上用页面边界直接固化，从根上避免「每个画布重复加载 skill/MCP」。

---

## 3. 画布拖拽的落点（精确回答 Q1）

### 3.1 画布只在这 3 个页面出现

**① 画布 Workflow（主画布，扣子式 DAG）**
- 节点类型（引用已注册的能力，**不新建能力**）：
  - `trigger`（触发器：手动/cron/事件/Webhook）
  - `agent_step`（派给某个已注册 Agent，可配协作模式：流水线 / 群聊）
  - `tool_call`（调用已注册工具 / MCP 工具，按名引用）
  - `branch` / `condition`（条件分支）
  - `memory_op`（读写统一记忆池，按层引用）
  - `human_gate`（人工闸门节点 = Guardian 视觉化，对应 v2 §8 治理）
  - `model_router`（节点级多模型路由：便宜模型分类 / 强模型生成 / 多模态）
- **关键纪律**：节点只「引用」页面 4/5/6 已注册的能力（by name）。画布**不提供「加载 skill / 加载 MCP」节点**——那是环境平面的事。

**② 智能体 Agents（能力组合画布）**
- 这是「环境平面」的编辑态：把已注册的技能、工具、记忆作用域、模型画像**拖进一个 Agent 工牌**，组合成它的能力边界。
- 与 ① 的区别：这里是「定义能力」，① 是「使用能力」。两者职责不混。

**③ 任务与自动化 Tasks（自动化轻量编排）**
- 触发器（cron/事件）拖到一条已有的 Workflow 上，构成「定时/重复运行某个画布」。
- 比 ① 简单，是「Workflow + 触发器」的绑定，不是另起一套 DAG 语义。

### 3.2 为什么不在别的页面放画布

- **技能/连接/记忆/设置**：这些是「配置/注册」，用列表 + 表单即可，强行画布化反而增加认知负担且易诱发「在错误的地方加载能力」。
- **智能体群 Agent Hub**：用「看板 + 群聊」而非自由画布。协作关系由 Orchestrator 动态编排，不需用户在画布上手动画拓扑（那是 Workflow 的职责）。
- **指挥台**：聊天即输入，不需要画布。

> 这直接修正了早期蓝图里「把 skill/mcp 当画布节点」的缺陷（v2 §9 反模式第 2 条）。

---

## 4. 多 Agent 协作与「群聊」（精确回答 Q3）

### 4.1 多 Agent 协作：双形态

| 形态 | 落点 | 适用 | 底层 |
|---|---|---|---|
| **结构化协作** | 画布 `agent_step` 节点，节点间按 DAG 流转；支持「流水线流转」与「对话/协作写作」两模式（sidechain 隔离） | 确定性流程、可复现任务 | `Orchestrator` + `CoordinationPort` |
| **自由群聊** | 智能体群 Agent Hub 页面（群聊室） | 探索性任务、头脑风暴、跨 Agent 协商、人参与决策 | 本地消息总线 + `Orchestrator`(supervisor/PM) |

### 4.2 智能体群 Agent Hub（群聊室）设计

参考真实项目：**Octo-Vec**（PM 派发 + Kanban + SAST + 成本看板，MIT）、**loka1/mcp-agent-hub**（实时消息中枢 register/send_ask/result/SSE，GPL-3.0 → 仅参考其协议，自研同构用 Octo-Vec MIT 基底）、**realyinchen/AgentHub**（FastAPI+LangGraph supervisor 运行时，参考）、**Potarix/agent-hub**（统一本地 UI，参考治理 UI）。

**布局（Slack/Discord 式 + Octo-Vec 看板）：**
```
┌─────────────┬──────────────────────────────┬──────────────────┐
│ 在线 Agent   │  群聊流                        │ 任务看板(Kanban) │
│ 花名册       │  AgentA: 「我来分析需求…」     │ ┌────────────┐  │
│ (工牌/角色)  │  AgentB: 「我来做实现…」       │ │待派发│进行中│完成│ │
│ · 研究员     │  Human  : 「注意隐私合规」     │ └────────────┘  │
│ · 工程师     │  AgentA: 「已提交 PR，请审」   │ 实时: SAST/成本 │
│ · PM(派发)   │  [Guardian] AgentB 请求 P0    │ 子任务网络图    │
│              │  → 人工审批浮层弹出            │                  │
└─────────────┴──────────────────────────────┴──────────────────┘
```

**协议（本地消息总线，非 MCP 拼接）：**
- `register(agent_id, role, caps)` / `send_ask(from, to, msg)` / `broadcast(msg)` / `result(task_id, status)` / `heartbeat(agent_id)`。
- 传输：本地 WebSocket / SSE（同机，无外网）。
- 持久化：本地 SQLite（Octo-Vec 式三层记忆 Sunset/Sunrise 思路）。

**Guardian 横切覆盖群聊（关键，避免治理漏网）：**
- 群聊中任何 Agent 提议 P0/P1 操作（删文件、改凭证、强 push、外部请求）→ 该消息被引擎拦截，在群聊流里插入「⚠ 待人工确认」卡片 + 同步进页面 1/6 的治理待办。
- 人类在群聊里点「批准/拒绝」→ `Guardian.approval_queue` 消费 → 才真正经 Substrate Port 调底座执行。
- **这保证群聊不是「失控的 agent 自说自话」，而是「带闸门的协作」**——正好补上 Octo-Vec / Agent Hub 们都没有的治理平面（v2 §8 护城河）。

### 4.3 与现有代码的关系（不重复设计）

- `core/orchestrator.py`（已有 Stub）升级为真实的 PM/supervisor 调度器，复用 Octo-Vec 的派发模型。
- `CoordinationPort`（v2 §5.2）作为群聊总线契约，实现 `OctoVecBusAdapter`。
- 画布 `agent_step` 节点与群聊 `agent_step` 调用**同一个** `Orchestrator` 接口，只是触发方式不同（DAG 顺序 vs 群聊异步）。

---

## 5. GitHub 模块融合映射（精确回答「这些有没有融进来」）

| GitHub 项目 | 真实定位（已核实） | 在我们架构的落点 | 许可证/本地 |
|---|---|---|---|
| **OpenClaw（龙虾）** | 执行网关（桌面/浏览器/办公/MCP/cron） | **底座一半**：执行网关，替换 `openclaw_gateway.py` Stub | MIT / 本地 |
| **Hermes（爱马仕）** | 记忆 + GEPA 自进化内核 | **底座另一半**：记忆/进化，替换 `memory.py`/`distill.py` Stub | MIT / 本地 |
| **MemOS memos-local-plugin** | SQLite + JSON-RPC 本地统一记忆内核 | **底座内存耦合层**：OpenClaw(TS) + Hermes(Py) 同核 | MIT / 本地 |
| **TrueAgent** | 7 层 + 元认知反思记忆 | **记忆轴**：并入统一记忆核心的 7 层模型 | Apache-2.0 / 本地 |
| **OllamaFlow（richardyang92/AgentFlow）** | Electron + React Flow 纯本地画布 | **前端画布（页面 3）**：fork 加 Guardian 浮层 + 记忆面板 | Apache-2.0 / 本地 |
| **Octo-Vec** | 虚拟软件公司 24 Agent，PM 派发 + Kanban + SAST + 成本 | **多 Agent 组织/群聊（页面 9）** + `CoordinationPort` 实现基底 | MIT / 本地 |
| **loka1/mcp-agent-hub** | 实时消息中枢 SSE | **仅参考协议**（GPL-3.0 传染性，不自用），自研同构走 Octo-Vec MIT | GPL-3.0（弃用） |
| **realyinchen/AgentHub** | FastAPI + LangGraph supervisor | **参考** supervisor 运行时模型 | 待确认 / 参考 |
| **Potarix/agent-hub** | 统一本地 UI（OpenClaw+Hermes+…） | **参考** 治理/统一 UI 形态 | 待确认 / 参考 |
| **CoPaw（agentscope-ai）** | 阿里通义本地优先前端控制台 | **参考** 控制台形态（本身无画布，不 fork） | Apache-2.0 / 本地 |
| **n8n / Langflow / Dify / Flowise / ComfyUI** | 画布范式标杆 | **画布交互范式借鉴**（节点/连线/Human 节点/变量体系/图像流） | 多 MIT/Apache / 参考 |
| **digit-opus-hub / Clawith / AgentTeams·HiClaw** | 数字员工中台 + 治理平面 | **中台形态 + 治理（谁能@谁/调哪个LLM/MCP=策略）借鉴** | 参考 |

**融合原则（与 v2 一致）**：全部经 `Port/Adapter` 接入；Guardian 治理平面 100% 自研不外移；本地优先、无云依赖；许可证避开 GPL-3.0 传染性（loka1 仅参考协议）。

---

## 6. 三条交互入口如何不「互相打架」（给审计 AI 的重点）

| 潜在冲突 | 规避机制 |
|---|---|
| 指挥台派的任务 vs 画布 DAG vs 群聊派发，三套调度逻辑 | **统一汇入 `control_loop`**，入口只负责「把意图翻译成引擎输入」，不各自实现调度 |
| 画布 Agent 节点 vs 群聊 Agent，双套协作实现 | **共用 `Orchestrator` + `CoordinationPort`**，仅触发方式不同 |
| 群聊里 Agent 绕过 Guardian 自作主张 | **所有到底座的调用强制过 Guardian**（含群聊提议），见 §4.2 |
| 画布里重复加载 skill/MCP | **画布只引用已注册能力（by name）**，加载在环境平面（页面 4/5/6） |
| 前端 mock 当真实运行态 | 画布/群聊必须接 XAI 引擎真实执行，弃用 `simulator`（v2 §9 反模式第 7 条） |

---

## 7. 给审计 AI 的审查清单（可直接交给审计方）

请审计方逐条确认以下几点是否成立、有无冲突/假信号/结构性缺陷：

1. **分层自洽**：XAI 是「引擎」而非「底座」；底座 = OpenClaw + Hermes 内存耦合。是否存在 XAI 又当底座又当大脑的越界？
2. **三入口共享引擎**：指挥台/画布/群聊是否都汇入同一 `control_loop` 与 `Guardian`，无各自重复调度？
3. **画布落点正确**：拖拽画布是否仅出现在 Workflow / Agents / Tasks 三页面，且画布节点只「引用」已注册能力（无 skill/MCP 加载节点）？
4. **多 Agent 群聊纳入**：是否同时具备「画布 Agent 节点」与「Agent Hub 群聊室」双形态，且共用 Orchestrator？
5. **Guardian 横切群聊**：群聊中 P0/P1 提议是否被拦截为人工审批，而非 Agent 自行执行？
6. **本地优先未被破坏**：上述所有模块是否纯本地（无云记忆、无强制 API key、无外网依赖）？
7. **模型无关贯穿**：画布节点级路由、群聊各 Agent 独立模型画像是否都走 `ModelBackend` 抽象？
8. **GitHub 模块融合无越界**：Octo-Vec/Agent Hub/OllamaFlow 是否都经 Port/Adapter，未把其治理/权限模型直接耦合进 XAI？
9. **记忆架构单一事实源**：7 层 + 元认知记忆是否由底座统一托管（MemOS+TrueAgent），XAI 引擎与 OpenClaw/Hermes 读写同一源？
10. **升级跟随覆盖新增项**：前端 fork（OllamaFlow）、协同总线（Octo-Vec 式）是否也纳入 `integrations.lock` + Nightly CI 契约测试？

---

## 8. 待用户拍板（再动手前）

1. 三入口形态是否认可（指挥台 + 画布 + 群聊），还是先只做其中 1–2 个？
2. 前端 fork 选 **OllamaFlow**（Electron 桌面，纯本地）是否确认？还是坚持自研 React（当前 demo）？
3. 群聊总线是否采用 **Octo-Vec MIT 基底自研**（避开 loka1 的 GPL-3.0）？
4. 落地顺序建议：① 固化底座（OpenClaw+Hermes+MemOS）→ ② 指挥台接通真实引擎 → ③ 画布接通真实执行 → ④ 智能体群群聊 → ⑤ 技能/连接/记忆/任务管理面。

> 本文与 `xai-ultimate-blueprint-v2.md` 共同构成完整蓝图，交付审计前请两篇一并审阅。
