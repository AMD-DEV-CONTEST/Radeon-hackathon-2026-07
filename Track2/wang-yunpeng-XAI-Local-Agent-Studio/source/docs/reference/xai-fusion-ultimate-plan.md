# XAI 终极融合版架构与上游升级跟随策略

> 调研日期：2026-07-17 · 约束：**本地硬件部署、排除一切云记忆方案** · 底座维持我们的 Grok 内核（模型无关）· 当前阶段仅规划、未改系统代码。

---

## 0. GitHub 实测结论（按"能否纯本地 + 许可证"筛）

| 项目 | 实测情况 | 本地？ | 许可证 | 结论 |
|---|---|---|---|---|
| **MemOS / memos-local-plugin** (`MemTensor/MemOS`) | 单一本地记忆内核：OpenClaw 进程内 TS 直连 + Hermes 经 Python Provider 走 stdio/TCP **JSON-RPC** 接同一 `bridge.cts`；SQLite + 本地向量，零云依赖 | ✅ | MIT 插件 / Apache-2.0 主仓 | **选为统一记忆核心** |
| **TrueAgent** (`sspygia/TrueAgent`) | 7 层嵌套记忆（工作→长期→锚点→**反思/元认知**→因果链→日记→用户画像）+ 自读源码自修 | ✅ | Apache-2.0 | **选其 7 层 + 元认知轴，并入记忆核心** |
| **OpenClaw** (`openclaw/openclaw`) | hub-spoke 网关；`SKILL.md` 技能 + `before_tool_call` Hook；可 headless CLI / Gateway daemon HTTP-RPC | ✅ | MIT | **选为执行网关（替换 Stub）** |
| **Hermes 自进化 GEPA** (`NousResearch/hermes-agent-self-evolution`) | DSPy+GEPA 遗传-帕累托提示进化，读轨迹→变异 SKILL/prompt→评估→PR | ✅（仅走 LLM，可指本地端点） | MIT（Darwinian Evolver 为 AGPL，仅外部 CLI，不 import） | **选为进化引擎（增强 distill）** |
| **OllamaFlow** (`richardyang92/AgentFlow`) | Electron+React+TS+Vite，React Flow 节点画布，Ollama 后端完全离线，自定义节点+Preload API | ✅ | Apache-2.0 | **选为前端画布基座（fork）** |
| **Octo-Vec** (`akhil2129/OCTO_VEC`) | "虚拟软件公司" 24 agent，PM 派发，三层记忆，实时看板（Kanban/网络图/财务），自动 SAST/SCA/Secrets+成本追踪 | ✅ | MIT | **选其协同/组织模型作参考，自研同构总线** |
| CoPaw (`agentscope-ai/CoPaw`) | 本地优先但**无可视化画布**（仅 Console/TUI） | ✅ | Apache-2.0 | ✗ 无画布，不作基座 |
| sggmico/agent-flow | React Flow 画布成熟，但**强制 OPENAI/ANTHROPIC key + Postgres/Redis**，非纯本地 | ✗ | MIT | ✗ 违反本地优先；仅作"需 Web 多人"时的备选（换本地 Ollama） |
| loka1/mcp-agent-hub | 实时 SSE 消息总线，但 **GPL-3.0 传染性** | ✅ | GPL-3.0 | ✗ 闭源集成风险；改用 Octo-Vec(MIT) 自研同构 |
| Potarix/agent-hub | 本地零遥测 UI 聚合器，细粒度权限审批（diff 弹窗） | ✅ | MIT | 仅作**治理浮层 UI 参考** |

---

## 1. 融合总原则

**我们的 Grok 底座（Python xAI core）= 控制面 / 大脑脊柱；外部项目 = 可插拔本地运行时。** 所有外部能力只经"**能力端口 Port + 适配器 Adapter**"接入，核心永远依赖 Port、不依赖上游实现。这是同时满足"融合最强能力"与"上游升级不伤身"的支点。

### 1.0 概念澄清（重要）
**xAI（Grok 底座）是整个融合的"宿主 / 控制面"，不是某个偏代码的引擎**；内部的 **Grok Build 代码引擎**才是负责代码开发的垂直子引擎。因此正确逻辑**不是**"代码→xAI / 其他→融合"的二分——xAI 从头到尾都是两者共同的脊柱。准确表述：xAI 控制面统一承接所有任务，按类型路由到各运行时；路由、治理(Guardian)、校准(Meta)、审计全部由 xAI 完成。Grok Build 只是"代码工程类"这一个运行时，跑在 xAI 内部、受治理、走统一记忆。

```
xAI 控制面 (Grok 底座: 意图路由·Guardian·control_loop·Meta·Runner·Distill·统一记忆)
   │  按任务类型路由（不是"代码 vs 其他"的二分）
   ├─ 代码开发工程        → Grok Build（xAI 自己的代码子引擎）
   ├─ 桌面/浏览器/办公/定时/MCP → OpenClaw 执行网关
   ├─ 记忆读写            → MemOS + TrueAgent 8层元认知（单一事实源）
   ├─ 进化 / 自蒸馏       → Hermes GEPA
   └─ 多智能体协同        → Octo-Vec 式总线（PM 派发/看板/SAST/成本）
```

```
体验层(OllamaFlow 画布 + 我们的治理/记忆浮层)
        │
控制面 / 大脑脊柱(XAI core: 意图路由·control_loop·Reason·Meta·Runner·Orchestrator·Distill)
        │
治理平面 Guardian(P0/P1/P2 + 人工闸门)  ← 我们的护城河，永不外移
        │
统一本地记忆核心(MemOS SQLite + TrueAgent 7 层元认知, JSON-RPC, 单一事实源)
        │
═══════ 能力端口 Port + 适配器 Adapter（升级隔离层）═══════
   ├─ OpenClaw 执行网关(CLI 子进程 / Gateway HTTP)
   ├─ Hermes 进化 GEPA(Python 同进程 import)
   └─ Octo-Vec 式协同总线(PM 派发 / 看板 / SAST / 成本)
        │
本地模型层(Ollama / MLX / GGUF 量化 + 可选用户 API key)
        └─ 全部落 ~/.xai/ · 无云 · 无遥测
```

## 2. 分层选型（替换我们当前什么）

| 层 | 选型 | 替换/增强 |
|---|---|---|
| 前端画布 | OllamaFlow(fork) + Guardian 浮层 + 记忆监控面板 | 替换简陋演示前端 |
| 控制面 | **我们的 Grok 底座 xAI core（不变）** | — |
| 治理平面 | **Guardian（自研，护城河）** | 叠加在一切之上 |
| 统一记忆核心 | MemOS + TrueAgent 7 层元认知 | `memory.py` 改为其适配器(facade)，废弃内置 deque |
| 执行网关 | OpenClaw（CLI / Gateway HTTP） | `openclaw_gateway.py` Stub→真适配器 |
| 进化引擎 | Hermes GEPA（Python import） | `distill.py` 增强 |
| 多智能体协同 | 自研总线（参考 Octo-Vec MIT） | 新增层（当前缺） |
| 代码引擎 | Grok Build（现有）+ 可选增强 | `grok_build_engine` |
| 本地模型 | Ollama/MLX/GGUF | `model_backend` |

## 3. 与我们"优势保全清单"对账（8 根全保）

- 模型无关 ✅（本地量化/各家 API 经 ModelRouter）
- 本地闭环 ✅（全栈本地，无云记忆）
- 横切贯穿 ✅（Guardian/Reason/Meta/Runner/Distill 在我们控制面，叠加于所有运行时）
- 统一记忆单一事实源 ✅（MemOS 即统一池，保留 engine 标签元数据）
- 自进化 ✅（Hermes GEPA + 我们的 Distill 约束门）
- **治理平面（护城河）✅ 强化**（外部项目全无分级治理，我们独家）
- 长任务 ✅（Runner checkpoint + OpenClaw 常驻）
- 数字员工中台 ✅（Octo-Vec PM 派发 + 工牌模型）

## 4. 与我们"问题清单"对账（填坑）

P1/P2 前端简陋→OllamaFlow；P3 画布未接真实核心→workflow_bridge 接 OllamaFlow；P4 环境层坍进画布→分层后环境平面独立；P5 多引擎 Stub→OpenClaw/Hermes 真接；P6 Grok 文案不一致→改"底座=Grok 模型无关核心"；P7 记忆/Guardian 未闭环→MemOS+Guardian 落地；P8 缺任务/自动化→Octo-Vec 看板+OpenClaw cron；P9 Rust 仅 2 crate→可保留 Guardian/Reason，其余由上游承担；P10 蒸馏需 key/集群→Hermes 本地端点 + 本地拓扑。

## 5. 上游升级跟随策略（核心新增）

1. **适配器/端口隔离（防腐层）**：外部项目只经 Adapter 实现稳定 Port（ExecutionGatewayPort / MemoryCorePort / CanvasPort / CoordinationPort / EvolutionPort）；核心依赖 Port，永不 import 上游内部。上游改版只动 Adapter。
2. **版本锁定清单 `integrations.lock`**：每个上游 pin 到 commit hash + 版本 + 我们消费的能力契约子集。
3. **能力契约文档**：每个 Port 写明依赖的上游行为（方法名/JSON Schema/退出码）。上游须保这些或我们升 Adapter。
4. **Nightly CI 兼容性闸门**：拉各上游 pin 版本→跑 Adapter 集成测试；破坏契约则 CI 红→先于用户知晓。
5. **订阅式滚动**：watch 上游 release；新版本在 staging 分支升 pin→跑契约测试→绿则 promote，红则维持旧 pin+开 issue。
6. **语义化能力而非实现**：MemoryCorePort 定义 `store/recall/reflect/evolve`，后端换 MemOS→TrueAgent 仅改 Adapter+manifest。
7. **治理平面永不外移**：Guardian 100% 自研，升级不耦合。
8. **数据迁移脚本**：记忆核心 schema 演进提供版本化迁移（SQLite ALTER/导出导入），schema 版本独立于上游。
9. **插件注册表协商**：各运行时启动注册 `name/version/capabilities/health`；版本不支持则优雅降级（Stub 兜底）而非崩溃，复用既有 Stub 模式。
10. **兼容性矩阵 `COMPAT.md`**：我们的 release ↔ 各上游 release ↔ 契约版本，每次升级维护。

## 6. 许可证与风险

- 全选 MIT / Apache-2.0；**避开 GPL-3.0**（loka1）→ 用 Octo-Vec MIT 自研同构。
- Hermes 的 Darwinian Evolver 是 AGPL，但仅外部 CLI，我们 import 主引擎（MIT），不触发。
- 异构栈：OpenClaw(TS)/Hermes(Python)/OllamaFlow(TS)/我们(Python+Rust)——靠 Port 隔离降低耦合。

## 7. 落地顺序建议（待拍板，未动手）

1. 先固化**记忆核心 + Port/Adapter 隔离层**（单一事实源，最该先稳）；
2. 再定**前端画布**（fork OllamaFlow + 治理浮层）；
3. 接**执行/进化运行时**（OpenClaw / Hermes 替换 Stub）；
4. 最后接**多智能体协同**（自研 Octo-Vec 式总线）。
