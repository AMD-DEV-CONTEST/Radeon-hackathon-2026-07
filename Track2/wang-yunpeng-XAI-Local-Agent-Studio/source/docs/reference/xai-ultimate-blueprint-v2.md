# XAI 终极融合版蓝图 v2

> 修正口径：XAI 是**编排引擎**（大脑/控制面），不是底座；底座是 **OpenClaw（执行网关）+ Hermes（记忆/进化内核）** 的内存级耦合内核。所有其他能力（画布、协同总线、Grok Build 代码引擎等）经 Port/Adapter 挂在引擎上。
>
> 目标：本地优先、模型无关、带企业级治理的数字员工中台。必须确实能跑，必须比别人强。

---

## 1. 定位与核心原则

### 1.1 一句话定位
**本地优先、模型无关、带企业级治理平面的数字员工中台。**

- 底座：OpenClaw + Hermes 内存级耦合的本地内核（执行 + 记忆 + 进化）。
- 引擎：XAI 控制面，负责任务编排、治理、校准、审计、长任务、自进化。
- 体验：OllamaFlow fork 作本地零代码画布，叠加 Guardian 治理浮层与记忆监控面板。

### 1.2 核心原则（不可妥协）

| # | 原则 | 含义 |
|---|---|---|
| P1 | **本地优先** | 无强制云端、无遥测、记忆与源码只落本地 `~/.xai/`。可选用户 API key，不默认外发。 |
| P2 | **模型无关** | 所有模型调用走 `ModelBackend` 抽象。Grok、DeepSeek、Ollama/MLX/GGUF 可热插拔。 |
| P3 | **治理平面不外移** | Guardian（P0/P1/P2 + 人工闸门）100% 自研，不依赖 OpenClaw/Hermes 的权限模型。 |
| P4 | **底座内存级耦合** | OpenClaw 与 Hermes 共享同一本地记忆事实源（MemOS SQLite + TrueAgent 7 层），非 MCP 外部拼接。 |
| P5 | **引擎只编排、不重复实现** | XAI 不重新写执行网关、不重新写记忆存储、不重新写进化算法；它负责“何时调谁、如何治理、如何校准”。 |
| P6 | **防腐层隔离上游** | 底座变更、上游发版，只应影响 Adapter/Port，不穿透 XAI 引擎。 |

---

## 2. 分层架构

```text
┌─────────────────────────────────────────────────────────────────────┐
│ 体验层 (UX)                                                         │
│  OllamaFlow fork · 本地拖拽画布 + Guardian 治理浮层 + 记忆监控面板   │
└──────────────────────────────────┬──────────────────────────────────┘
                                   │ 画布 JSON / DAG 描述
┌──────────────────────────────────┴──────────────────────────────────┐
│ 控制引擎层：XAI Engine                                                │
│  intent_router → control_loop → Reason → Meta → Runner → Distill     │
│  Grok Build 代码引擎 · 多智能体 Orchestrator · 模型路由器              │
└──────────────────────────────────┬──────────────────────────────────┘
                                   │ 调用 / 被调用
┌──────────────────────────────────┴──────────────────────────────────┐
│ 治理平面：Guardian（横向贯穿）                                         │
│  P0 危险操作 · P1 敏感操作 · P2 常规操作 · 人工闸门 · 审计日志          │
└──────────────────────────────────┬──────────────────────────────────┘
                                   │ 每次执行前裁决
┌──────────────────────────────────┴──────────────────────────────────┐
│ 底座接口层：Substrate Port / Adapter                                  │
│  稳定契约：memory 读写 · tool 执行 · evolution 触发 · agent 身份注册   │
└──────────────────────────────────┬──────────────────────────────────┘
                                   │ 内存级耦合
┌──────────────────────────────────┴──────────────────────────────────┐
│ 底座层：OpenClaw + Hermes 内存级耦合内核                              │
│  ┌──────────────────┐  ⇄  ┌──────────────────┐                      │
│  │ OpenClaw         │      │ Hermes           │                      │
│  │ 执行网关         │      │ 记忆 + 进化内核  │                      │
│  │ CLI / Gateway    │      │ GEPA · 8层记忆   │                      │
│  └──────────────────┘      └──────────────────┘                      │
│         │                            │                              │
│         └──────────────┬─────────────┘                              │
│                        ▼                                            │
│  统一本地记忆核心：MemOS SQLite + TrueAgent 7 层元认知记忆           │
│  （工作/长期/锚点/反思/因果链/日记/用户画像）                          │
└──────────────────────────────────┬──────────────────────────────────┘
                                   │ 模型调用
┌──────────────────────────────────┴──────────────────────────────────┐
│ 本地模型层：Ollama / MLX / GGUF 量化 + 可选用户 API key              │
└─────────────────────────────────────────────────────────────────────┘
```

### 2.1 为什么这样分层能避免结构性错误

- **XAI 不是底座**：如果 XAI 同时当底座和大脑，会变成“万物容器”，任何底座升级（如 OpenClaw 大版本）都会被迫改引擎，违反 P6。
- **治理平面横向贯穿**：它不是一个“层”而是跨所有层的切面。放在 XAI 引擎与底座之间，确保每次到底座的调用都经过裁决。
- **底座内部内存耦合**：OpenClaw 与 Hermes 共享同一 SQLite 事实源，解决“执行完了记忆不知道”的假信号问题。但 XAI 引擎通过 Substrate Port 与底座解耦，避免被 Hermes 的 GEPA 实现细节污染。
- **画布只是体验层**：OllamaFlow 只生成/展示 DAG，不直接调用 OpenClaw/Hermes，避免把“环境层”坍进画布。

---

## 3. 关键概念澄清（避免冲突与假信号）

| 概念 | 它是什么 | 常见误解 | 正确定位 |
|---|---|---|---|
| **XAI** | 编排引擎 | “XAI 是底座”或“XAI 只管代码” | 控制面/大脑，统一路由、治理、校准、审计 |
| **Grok** | 模型 backend + 代码引擎品牌 | “Grok 是底座” | Grok 模型是 ModelBackend 之一；Grok Build 是 XAI 引擎内的代码垂直子引擎 |
| **OpenClaw** | 执行网关 | “它是底座全部” | 底座的一半：执行（桌面/浏览器/办公/定时/MCP） |
| **Hermes** | 记忆 + 进化内核 | “它是底座全部” | 底座的另一半：7 层记忆 + GEPA 自进化 |
| **MemOS** | 本地统一记忆存储 | “它是另一个独立模块” | 是 OpenClaw+Hermes 共享的内存级事实源，被 XAI 引擎读写 |
| **Guardian** | 治理平面 | “它是 OpenClaw 的 hook 策略” | 自研，跨引擎、跨底座的独立策略层 |

---

## 4. 数据流：一条指令的完整生命周期

```text
用户通过画布/自然语言输入
         │
         ▼
┌──────────────────┐
│ 意图路由器        │  判断：办公/代码/研究/长期业务/通用
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ control_loop     │  生成执行计划 + 思考预算
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ Reason / Meta    │  思考增强 + 元认知校准（Brier）
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ Guardian         │  按 P0/P1/P2 裁决，必要时入人工队列
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ 任务路由          │  代码→Grok Build / 桌面→OpenClaw / 进化→Hermes
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ 底座执行          │  OpenClaw 执行 / Hermes 记忆读写 / GEPA 触发
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ 审计 + 校准更新   │  L8 审计 + Brier 更新 + Distill 沉淀 skill
└────────┬─────────┘
         │
         ▼
   结果返回画布 + 记忆回流统一记忆核心
```

---

## 5. 接口与契约（防腐层设计）

### 5.1 Substrate Port：XAI 引擎 ↔ 底座

```python
class SubstratePort(Protocol):
    # 执行
    async def execute(self, tool: str, args: dict, context: TaskContext) -> ExecutionResult: ...
    # 记忆
    async def memory_read(self, query: MemoryQuery) -> list[MemoryRecord]: ...
    async def memory_write(self, record: MemoryRecord) -> None: ...
    # 进化
    async def evolve(self, trace: ExecutionTrace) -> EvolutionProposal: ...
    # 身份
    async def register_agent(self, identity: AgentIdentity) -> None: ...
```

**为什么这是 Port，不是直接 import OpenClaw/Hermes？**

- 换底座版本（如 OpenClaw 2.x → 3.x）时，只改 `OpenClawSubstrateAdapter`，`XAI Engine` 不变。
- 未来如果想把底座的一部分换成 Rust 实现（如 IronClaw），也只需改 Adapter。

### 5.2 Capability Port：XAI 引擎 ↔ 其他运行时

| 运行时 | Port 契约 | 当前候选 |
|---|---|---|
| 画布 | `CanvasPort`：推送任务、订阅状态、返回结果 | OllamaFlow fork |
| 多智能体协同 | `CoordinationPort`：register / send_ask / result / heartbeat | Octo-Vec 式自研总线 |
| 代码引擎 | `CodeEnginePort`：repo parse / refactor / test / git | Grok Build（XAI 内部） |
| 外部工具 | `ToolPort`：schema + invoke | OpenClaw 工具经 Substrate Port 暴露 |

### 5.3 ModelBackend：XAI 引擎 ↔ 本地模型

- 统一接口：`complete(prompt, context)`、`complete_with_confidence(...)`。
- 实现：DeepSeekBackend、OllamaBackend、MLXBackend、GrokBackend（可选）等。
- 底座中的 OpenClaw/Hermes 也可以配置为调用同一个 Ollama/MLX 服务端，避免重复拉模型。

---

## 6. 模块职责与协作矩阵

| 模块 | 职责 | 与底座关系 | 与 XAI 引擎关系 |
|---|---|---|---|
| **intent_router** | 意图分类、任务拆解 | 调用 Substrate Port 预读用户记忆 | 引擎入口 |
| **control_loop** | 单向控制环：意图→思考→治理→执行→审计 | 通过 Guardian 调用底座 | 引擎中枢 |
| **Reason** | 思考增强、链式推理 | 不直接调用 | 引擎内部 |
| **Meta** | 元认知校准、Brier 校准 | 读写记忆核心 | 引擎内部 |
| **Guardian** | 权限分级、人工闸门、审计 | 拦截所有到底座的调用 | 横向切面 |
| **Runner** | 长任务、checkpoint、续跑 | 通过 Substrate Port 分阶段执行 | 引擎内部 |
| **Distill** | 触发 GEPA、沉淀 skill | 调用 Hermes 进化内核 | 引擎内部 |
| **Grok Build** | 代码工程：解析、重构、测试、Git | 必要时调用 OpenClaw 工具 | 引擎内的垂直代码引擎 |
| **Orchestrator** | 多智能体调度、Octo-Vec 式派发 | 通过 CoordinationPort | 引擎内部 |
| **OpenClaw** | 执行网关：桌面/浏览器/办公/MCP/定时 | 底座 | 通过 Substrate Port 被引擎调用 |
| **Hermes** | 记忆读写、GEPA 自进化 | 底座 | 通过 Substrate Port 被引擎调用 |
| **MemOS+TrueAgent** | 统一本地记忆事实源 | 底座核心 | 被引擎和底座共同读写 |

---

## 7. 本地部署拓扑（32G Mac / 本地服务器）

```text
单进程 + 多进程混合（默认单进程，可横向拆）

┌─────────────────────────────────────────────┐
│  xai-engine (Python)                        │
│  ├── control_loop / Guardian / Runner        │
│  ├── Grok Build (代码引擎)                    │
│  └── ModelRouter (本地模型 / API key)         │
└────────────┬────────────────────────────────┘
             │ Substrate Port (本地 Unix socket / SQLite)
┌────────────┴────────────────────────────────┐
│  openclaw-gateway (Node/TS)                 │
│  ├── CLI / HTTP Gateway                     │
│  ├── SKILL.md 工具注册                       │
│  └── MCP client (本地)                      │
└────────────┬────────────────────────────────┘
             │ 本地 JSON-RPC / 共享 SQLite
┌────────────┴────────────────────────────────┐
│  hermes-kernel (Python)                     │
│  ├── 7 层记忆读写                            │
│  └── GEPA 自进化                             │
└────────────┬────────────────────────────────┘
             │ SQLite
┌────────────┴────────────────────────────────┐
│  ~/.xai/mem.db (MemOS) + 向量/图扩展          │
└─────────────────────────────────────────────┘
             │
┌────────────┴────────────────────────────────┐
│  ollama / mlx (本地模型服务)                  │
└─────────────────────────────────────────────┘

前端：ollamaflow (Electron) ↔ xai-engine HTTP/WebSocket
```

---

## 8. 护城河与差异化（比别人强在哪里）

| 维度 | 我们 | 典型开源/竞品 |
|---|---|---|
| **治理** | P0/P1/P2 + 人工闸门，独立平面，任何执行必过 | OpenClaw 只有 hook 策略；Hermes 无治理；Dify/Coze 偏云端 |
| **记忆架构** | 7 层 + 元认知反思 + 本地 SQLite 单一事实源 | 多数项目 1-4 层，无元认知反思层；多 agent 记忆割裂 |
| **本地闭环** | 完全自托管，可选不出网 | 多数 SaaS 需出网；部分项目需 API key 或云端 |
| **模型无关** | ModelBackend 抽象，Ollama/MLX/GGUF/API 可热插拔 | 很多项目绑定特定模型或平台 |
| **底座耦合** | OpenClaw 与 Hermes 共享内存内核，执行与记忆不脱节 | 多数项目要么只有执行无进化，要么只有进化无执行 |
| **自进化** | Distill 触发 + Hermes GEPA + 约束门 + 人工复审 PR | 多数项目需手工写 prompt/技能 |
| **数字员工形态** | Agent 身份/工牌/协作/共享黑板 | 多数项目无组织模型 |

---

## 9. 反模式与不可妥协约束（结构陷阱）

| 反模式 | 后果 | 如何规避 |
|---|---|---|
| 把 XAI 又当底座又当引擎 | 升级底座时引擎被迫大改，底座无法替换 | 严格执行分层：XAI 只编排，底座=OpenClaw+Hermes |
| 让画布直接调用 OpenClaw | 环境层坍进执行层，重复配置每个流程 | 画布只生成 DAG，执行由 XAI 引擎路由 |
| 记忆走 MCP 外部拼接 | 延迟、序列化、丢失上下文，假信号 | 底座内共享 SQLite，XAI 经 Substrate Port 读写 |
| 把 Guardian 做成 OpenClaw hook | 治理被底座实现绑定，上游升级影响治理 | Guardian 自研，横向拦截，不依赖 hook 机制 |
| 一次接入 6 个上游项目 | 集成汤，无法调试，升级互相冲突 | 分阶段：先底座 → 再画布 → 再协同 |
| 模型绑定 Grok / DeepSeek | 用户换模型时整个引擎都要改 | 统一 ModelBackend 抽象 |
| 把前端 mock 当真实运行态 | 用户误以为系统能跑，实际是假信号 | 画布必须接到 XAI 引擎真实执行，不能再用 simulator |

---

## 10. 上游边界与升级策略

### 10.1 哪些随上游变，哪些不随

| 组件 | 我们 owns | 上游 owns | 升级影响 |
|---|---|---|---|
| XAI Engine / Guardian | 全部 | 无 | 由我们决定节奏 |
| Substrate Port 契约 | 我们 | 无 | 稳定后少变 |
| OpenClaw Adapter | 我们 | OpenClaw API | 上游升级只改 Adapter |
| Hermes Adapter | 我们 | Hermes API | 上游升级只改 Adapter |
| OllamaFlow fork | 我们 | 上游 UI 库 | 取上游 patch 合并到 fork |
| 本地模型 (Ollama/MLX) | 无 | 社区 | 通过 ModelBackend 隔离 |

### 10.2 升级跟随机制

1. `integrations.lock`：锁定每个上游的 commit/tag 和能力契约子集。
2. **Nightly CI 契约测试**：只测 Substrate Port / Capability Port 契约，不测上游内部。
3. **Staging 升 pin**：新 release 先升到 staging，跑全量契约测试。
4. **Promote 或 Hold**：绿 → 升 pin；红 → 维持旧 pin，开 issue 修 Adapter。
5. `COMPAT.md`：记录每个上游版本与 XAI 的兼容性矩阵。
6. **数据迁移脚本版本化**：MemOS schema 升级必须带迁移脚本，不允许破坏性 schema 变更。

---

## 11. 实施路线图（建议）

### 阶段 1：固化底座（6-8 周）
- [ ] 部署 OpenClaw 本地网关（headless CLI / HTTP）。
- [ ] 部署 Hermes 记忆/进化内核，接入 MemOS SQLite。
- [ ] 实现 OpenClaw 与 Hermes 的内存级共享记忆（TrueAgent 7 层模型）。
- [ ] 定义并冻结 Substrate Port 契约。
- [ ] 将 XAI 引擎现有的 `openclaw_gateway.py` / `memory.py` / `distill.py` Stub 替换为真实现。

### 阶段 2：引擎上底座（4-6 周）
- [ ] 把 XAI control_loop 的调用全部改走 Substrate Port，不再直接读写本地文件/memory.py。
- [ ] 让 Guardian 横向拦截 Substrate Port 调用。
- [ ] 实现 Runner 的长任务 checkpoint/续跑，基于底座执行。
- [ ] 把 Distill 的 GEPA 触发接到 Hermes 进化内核。

### 阶段 3：前端真跑（4-6 周）
- [ ] Fork OllamaFlow，去掉非本地依赖。
- [ ] 画布生成 DAG → XAI 引擎执行 → 结果回流，替代 simulator。
- [ ] 叠加 Guardian 治理浮层（审批队列、P0/P1/P2 状态）。
- [ ] 叠加记忆监控面板（7 层记忆水位、engine 标签）。

### 阶段 4：多智能体协同（可选，4-6 周）
- [ ] 实现 Octo-Vec 式协同总线（PM 派发、Kanban、Agent 身份）。
- [ ] 接入 CoordinationPort。
- [ ] 在多智能体讨论中叠加 Guardian（高危操作仍需人工确认）。

### 阶段 5：自进化闭环（持续）
- [ ] Distill 自动从执行 trace 生成 skill 提案。
- [ ] Hermes GEPA 约束门 + 测试门 + 人工复审 PR。
- [ ] 沉淀为项目级 skill 注册到 `~/.xai/skills/`。

---

## 12. 风险清单与缓解

| 风险 | 等级 | 缓解 |
|---|---|---|
| OpenClaw / Hermes 异构栈维护成本高 | 高 | 用 Substrate Port 隔离；只让 1-2 人维护 Adapter；其余人用 Port 开发 |
| 底座内存级耦合实现复杂（TS↔Python） | 高 | 先用 SQLite 共享 + 本地 JSON-RPC 通知；后续再用共享内存/FFI 优化 |
| 上游发版破坏 Adapter | 中 | `integrations.lock` + Nightly CI 契约测试 |
| 本地模型性能不足（32G Mac） | 中 | 默认用量化/小模型；复杂任务允许用户插 API key |
| 前端画布改造成本大 | 中 | Fork OllamaFlow 而非从零写；逐步替换而非重写 |
| 治理平面被绕过 | 高 | 所有到底座的调用必须经 Guardian；审计日志不可被 Adapter 删除 |
| 真信号/假信号：看似能跑，实际没接底座 | 高 | 每个阶段都有契约测试；不接受 mock 通过就宣称完成 |

---

## 13. 总结：这个版本与 v1 的关键变化

1. **XAI 从“脊柱/底座”退为“引擎”**：只负责编排、治理、校准、审计；不再试图拥有记忆池和执行网关。
2. **底座明确为 OpenClaw+Hermes 内存级耦合**：执行、记忆、进化在本地共享同一事实源。
3. **Guardian 位置更准**：不是 OpenClaw 的 hook，而是 XAI 引擎与底座之间的独立横向策略层。
4. **Substrate Port 区分“底座接口”和“能力端口”**：底座用 Substrate Port，画布/协同等用 Capability Port，避免一锅炖。
5. **升级策略更保守**：`integrations.lock` + Nightly CI 契约测试，确保上游升级不破坏核心。

这个蓝图的核心优势：**我们有别人没有的企业级治理平面；我们用本地优先的底座把执行和记忆真正焊在一起；我们让 XAI 作为大脑统领所有任务类型，而不是把 XAI 自己也变成底座的一部分。**
