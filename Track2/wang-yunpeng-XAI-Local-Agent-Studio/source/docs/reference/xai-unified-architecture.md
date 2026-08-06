# XAI 统一架构：调度台 + 画布 + 流程化协同（吸收版）

> 底座决策：**Grok 开源内核**（xai-grok-* 系列）为底座，模型无关。
> OpenClaw / Hermes / Coze 级平台 / 数字员工中台 全部作为**吸收对象**，不替换底座。
> 本文件是调研（2026-07-17）后的架构定稿，承接 `xai-final-design.md`。

---

## 0. 一句话定位

XAI = **统一调度台（控制台）+ 画布（DAG 编排）+ 流程化协同引擎**，把 Guardian/Reason/Meta/Runner/KB/Orchestrator/Distill 七个能力以"有边界、可协作、能跑长任务"的方式组织起来，像数字员工中台一样运转，但底座仍是可替换的 Grok。

---

## 1. 调研吸收表（真实仓库 → 学什么 → 落在 XAI 哪层）

| 项目 | 真仓库 / 许可 | 我们吸收的点 | 映射到 XAI |
|---|---|---|---|
| **Dify** | langgenius/dify · Apache2 | 可视化 Workflow、RAG、插件生态、多模型、可观测 | 画布执行引擎 + 可观测指标 |
| **Coze Studio** | coze-dev · Apache2 | Go 微服务 + 工作流引擎 + 多渠道发布 | 画布节点语义 + 发布面 |
| **superagent-base** | Colin4k1024 · (Coze Studio 衍生) | 声明式 YAML Agent、Model Router（能力/成本/延迟+fallback）、MCP、SkillsHub、Tool 中间件链（retry/timeout/rate-limit/cache）、Workflow DAG、中断/恢复 checkpoint、**A2UI 结构化流式事件**、Experience Self-Evolution | `model_router.py` + `control_loop` A2UI 事件 + Runner checkpoint + Distill 经验沉淀 |
| **n8n** | n8n-io · Fair-code | 400+ 集成、代码节点、可自托管 | 工具节点 + 本地优先 |
| **DeerFlow** | bytedance/deer-flow · MIT | 超级 Agent 调度（Sub-Agent 并行 + 沙箱 + 持久记忆） | Orchestrator pipeline + Runner |
| **AgentScope** | agentscope-ai · Apache2（通义实验室） | **模型无关**多 Agent 消息调度引擎、ReMe 三层记忆（personal/task/tool）、标准工具封装、运行监控 | Orchestrator 消息总线 + `memory.py` |
| **Qwen-Agent** | QwenLM · Apache2（通义） | Qwen 深度优化、MCP、Code Interpreter、RAG | 工具/技能节点 |
| **digit-opus-hub** | kennyz · 数字员工中台 | React Flow 工作流编辑器、Agent 生命周期管理、Bull 异步队列（重试/退避）、实时 Dashboard、JWT/审计、成本追踪 | 画布前端 + Runner 队列 + 控制台 |
| **Clawith** | 开源多 Agent 协作 | "数字员工"而非 chatbot：持久身份 + 长期记忆 + 工作空间、**Agent Plaza 共享知识流** | Orchestrator 身份 + 共享黑板 |
| **openclaw-digital-workforce** | jiangye1314 · MIT | 数字员工工牌（状态/角色/绩效）、团队模板、角色与技能解耦、网关兼容 | 控制台工牌 + 角色预设 |
| **AgentTeams / HiClaw** | agentscope-ai/HiClaw · Apache2 | **治理平面**：谁可以@谁、调哪个 LLM、用哪个 MCP = 策略而非约定；Manager/TeamAdmin/TeamLeader/Workers 分层 | `guardian.governance` 策略 |
| **OpenClaw** | openclaw/openclaw · MIT（steipete） | Gateway(18789) hub-spoke、Tools 四档 profile、SKILL.md+YAML frontmatter+优先级、Workspace 文件(SOUL/IDENTITY/USER/TOOLS/AGENTS/HEARTBEAT/MEMORY)、Heartbeat(30min)、**before_tool_call Hook**、Markdown 记忆可 Git 版本化 | `guardian.before_tool_call` + `skills.py` + `memory.py` 文件约定 |
| **Hermes Agent** | NousResearch · MIT | **GEPA 自进化**（读执行 trace→变异 skill/prompt→约束门→人工复审 PR）、四层记忆（短/中/长/技能）、**渐进式披露 Level0/1/2**、agentskills.io 标准、技能跨实例导出 | `distill.gepa` + `memory.py` + `skills.py` 渐进披露 |
| **AgentBoard** | Samarth0211 · MIT | React Flow 暗色玻璃拟态、节点状态色（idle/running/done/error）、拓扑执行、实时日志/指标、**Critic 反射环** | 前端画布 + Meta=Critic 节点 |
| **AgentForge** | dangxingyu · MIT | React Flow 自定义节点、图解释器（并行/决策/循环）、无 eval 表达式引擎、Provider 抽象、运行护栏（max 节点/边/token/并行/循环）、Abort 信号 | 前端 + Runner 护栏 |

**核心结论**：把"开源 Coze（画布+工作流）"的**可视化编排**、"数字员工中台（digit-opus/Clawith/AgentTeams）"的**身份+治理+协作**、"OpenClaw"的**Hook+SKILL.md+Markdown 记忆**、"Hermes"的**GEPA 自进化+四层记忆+渐进披露**，全部焊进 Grok 底座。这正好补齐此前 XAI 缺的"前端表现层 + 多 Agent 治理 + 自进化闭环"。

---

## 2. 统一调度台（Unified Console）

左侧常驻控制台，是"中台"的入口，体现所有能力：

1. **数字员工花名册（Agent Roster）**：每个 Agent = 一张工牌，含 状态(working/idle/busy/offline)、角色、效率评分、完成任务数、运行时长。来源 = Orchestrator 注册的身份。
2. **模型路由状态（Model Router）**：列出已注册模型（DeepSeek/Grok/本地/任意），显示 能力/成本/延迟 实时分，当前默认路由与 fallback 链。
3. **知识库（KB）**：本地文件夹 RAG 状态（块数、最近检索命中）、四层记忆水位（短/中/长/技能）。
4. **审批队列（Guardian）**：P0 待人工确认动作、治理策略命中记录。Human 节点在此呈现。
5. **长任务进度（Runner）**：当前超长任务的里程碑进度条、checkpoint、质量门、续跑状态。
6. **可观测（Observability）**：Agent 请求数/延迟/错误率、Token、工具调用、校准 Brier 分（superagent-base 风格指标）。
7. **自进化（Distill）**：技能库规模、最近一次 GEPA 进化命中率、待人工复审的 PR。

---

## 3. 画布（Canvas / DAG）

中央 React Flow 画布，节点类型与 XAI 能力一一对应：

| 节点 | 含义 | 对应模块 |
|---|---|---|
| `agent` | 一个数字员工（带身份/角色） | Orchestrator |
| `model_router` | 节点级多模型路由 | model_router |
| `skill` | 调用一个 SKILL.md 技能 | skills |
| `mcp` | 调外部 MCP 工具 | tools |
| `kb` | 检索本地知识库 | kb + memory |
| `human` | 人工审批闸门（= Guardian P0） | guardian |
| `reflect` | 元认知校准/Critic 反射环 | meta |
| `code` | 执行代码/命令（经 guardian 审批） | guardian + tools |
| `conditional` | 条件分支（无 eval 表达式引擎） | runner 护栏 |
| `subflow` | 嵌套子工作流 | orchestrator |

**执行语义**（来自 AgentForge/DeerFlow/AgentBoard）：
- 拓扑排序（Kahn）执行；无依赖节点并行。
- 边 = 数据流（上游输出喂下游）+ 质量门约束。
- `reflect` 节点若连 `critic` 语义，触发上游重执行（反射环）。
- 支持循环/条件（受 Runner 护栏约束：max 节点/边/token/并行/循环次数）。
- 实时节点状态色：灰(idle)→蓝(running)→绿(done)/红(error)，动画边表示数据流动。
- A2UI 事件流（text/thinking/tool_call/tool_result/interrupt/done/progress/agent_switch）实时打印到日志面板。

---

## 4. 流程化协同机制（Flow Coordination）

- **消息总线（Orchestrator）**：Agent 间不直接互相调用内部，统一走消息总线（AgentScope 风格）。两种模式：
  - *pipeline*：DAG 流转（workflow）。
  - *collaborative*：多 Agent 就主题轮流发言，sidechain 隔离（各回 summary，主上下文不串味），共享 **Agent Plaza 黑板**做知识流。
- **身份与治理（Guardian）**：每个 Agent 有持久身份；治理策略规定 谁能@谁、能用哪个 LLM、能用哪个 MCP（AgentTeams 风格，策略而非约定）。
- **审批闸门（Guardian Hook）**：所有工具调用经 `before_tool_call` Hook → 风险分级 → P0 进审批队列（Human 节点）→ 其余按策略放行。
- **长任务（Runner）**：里程碑拆解 + checkpoint 落盘 + 质量门 + 断点续跑；异步队列 + 重试/退避（digit-opus Bull 风格）。
- **自进化（Distill）**：执行 trace 回流 → GEPA 读 trace 变异 skill/prompt → 约束门（测试/体积）→ 人工复审 PR → 注册进技能库。

---

## 5. 能力边界（Boundaries，互不打架）

| 模块 | 职责边界 | 禁止 |
|---|---|---|
| Guardian | 风险分级 + 治理 + 审批队列 | 不反向调用 reason/meta（C1 已修） |
| Reason | 思考脚手架（预算/协议/自精炼/多轨迹） | 不触发新控制环 |
| Meta | 置信校准(Brier) + L8 四维审计 + Critic | observe 只记录，不启新循环 |
| Runner | 超长任务拆解/checkpoint/续跑 | 不修改其他模块状态 |
| KB | 外部 RAG 检索 | 不改模型权重（伪逻辑1已澄清） |
| Memory | 四层记忆（短/中/长/技能） | 不越权写技能库（走 Distill） |
| Orchestrator | 多 Agent 消息总线 + 身份 + 治理执行 | 不直接执行工具（交 Guardian） |
| Distill | 自进化（GEPA） | 产物未过 guardian+测试不注册 |
| ControlLoop | 单向中枢：meta→reason→meta→guardian→execute→meta | 绝不互递归 |

---

## 6. 前端参考实现

见 `frontend/`：Vite + React + React Flow（对齐 AgentBoard/AgentForge/digit-opus-hub 的技术选型），浅色主题（用户偏好），单仓库可 `npm install && npm run dev`。

---

## 7. 落地路线（与 P0..P9 对齐）

- P0 Guardian：`before_tool_call` Hook + 治理策略 + 审批队列 ✅(本轮加固)
- P0.5 Reason：思考脚手架（已有）
- P2.5 KB + Memory：四层记忆 + SKILL.md 渐进披露 ✅(本轮新增 memory/skills)
- P6/P7 Orchestrator：消息总线 + 身份 + 治理执行 ✅(本轮接 governance)
- P9 Distill：GEPA 自进化 ✅(本轮新增 gepa)
- P10 Meta：Brier + L8（已有）
- §10 Runner：checkpoint/续跑（已有）
- 前端：统一调度台 + 画布 ✅(本轮新建 frontend)
- 模型路由：能力/成本/延迟 + fallback ✅(本轮新增 model_router)
