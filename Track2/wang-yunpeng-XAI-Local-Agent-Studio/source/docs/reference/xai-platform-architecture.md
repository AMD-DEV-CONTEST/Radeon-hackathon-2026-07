# XAI 平台 — 本地化私有超级 Agent 一体化平台 · 架构总纲（v2 重构）

> 重构依据：老大 2026-07-17 提示词《本地化私有超级Agent一体化平台研发方案》＋ 前序 XAI 核心（Guardian/Reason/Meta/Runner/KB/Orchestrator/Distill）。
> 视角：架构师 / 工程师 / 代码开发。底座维持 **Grok 开源内核（模型无关）**，OpenClaw / Hermes / WorkBuddy+Coze / Grok Build 全部作为**能力吸收对象**，通过抽象层接入，不替换底座。

---

## 0. 设计铁律（不可违背）

1. **底座不变**：Grok 开源内核；所有引擎经 `ModelBackend` 注入任意模型（本地量化 / GPT / Claude / GLM / 通义），底座不绑死任何一家。
2. **松耦合独立进程**：四引擎 + 中台各自独立 class，未来各自独立进程，可单独启停 / 升级 / 扩容。
3. **本地优先、数据闭环**：无境外遥测、无强制云端上传；对话 / 源码 / 记忆仅落本地。
4. **统一入口、结果汇总**：用户只面对「统一操作台」，一条指令经意图路由自动分流，结果全局汇总。
5. **单一事实源**：全局统一记忆池消除引擎间记忆割裂；权限分级唯一拦截点。

---

## 1. 总体架构（四引擎 + 一中台 + 一网关 + 一池 + 三横切）

```
┌──────────────────────────────────────────────────────────────────┐
│                    统一操作台 Console（WorkBuddy+Coze 风格）          │
│        拖拽画布 · 多端统一入口 · 团队共享资产 · 企业级日志            │
└───────────────────────────────┬──────────────────────────────────┘
                                 │ ① 用户指令进入
                                 ▼
                  ┌──────────────────────────────┐
                  │   意图路由器 Intent Router     │ ← 痛点2：自动识别+分发
                  │  OFFICE / CODE / LONGTERM /    │   （办公/长期业务/代码）
                  │  RESEARCH / GENERAL            │
                  └──────────┬───────────────────┘
        ┌────────────────────┼─────────────────────────┐
        ▼                    ▼                         ▼
┌──────────────┐   ┌──────────────────┐   ┌──────────────────────┐
│ 执行网关      │   │  代码引擎         │   │  调度中台(Orchestrator)│
│ OpenClaw      │   │  Grok Build       │   │ 多子Agent·工作流编排   │
│ 桌面/浏览器/  │   │ 仓库解析/重构/     │   │ 权限日志/KB·RAG        │
│ 文档/定时/    │   │ Git/终端/漏洞/测试 │   │                       │
│ MCP/办公生态  │   │                   │   │                       │
└──────┬───────┘   └────────┬─────────┘   └───────────┬──────────┘
       │                    │                         │
       └────────────────────┼─────────────────────────┘
                            ▼
              ┌──────────────────────────────────┐
              │   全局统一记忆池 Unified Pool      │ ← 痛点1：消除割裂
              │   (Hermes 四层 + engine 标签共享)  │
              └──────────────────────────────────┘
                            │
                            ▼
        ┌────────────────────────────────────────────┐
        │  横切能力（对所有引擎生效，统一调度）          │
        │  • Guardian 权限分级（痛点3：高危二次确认）   │
        │  • Reason 思考增强（吸收 GPT 链式/多工具/多模态）│
        │  • Meta 元认知（Brier 在线校准 + L8 审计）     │
        │  • Runner 超长任务（吸收 Claude Fiber5 规划）  │
        │  • Distill 自蒸馏（Hermes 复盘→技能）          │
        └────────────────────────────────────────────┘
```

---

## 2. 需求 → 架构映射表（逐条闭环）

### 2.1 四产品核心能力吸收
| 来源 | 平台角色 | 落地模块 | 关键能力 |
|------|----------|----------|----------|
| OpenClaw（龙虾） | 统一执行网关 | `openclaw_gateway.py` | 桌面操控 / 浏览器自动化 / 批量文档 / 定时任务 / MCP / 企业微信·钉钉·飞书 |
| Hermes（爱马仕） | 全局记忆与进化大脑 | `memory.py` + `distill.py` | 四层分级记忆 / 跨会话经验 / 自动复盘→标准化技能 / 后台值守 / 进程隔离并行 |
| WorkBuddy + Coze | 可视化协同调度中台 | `frontend/` + `orchestrator.py` | 拖拽工作流 / 多子Agent分工 / 权限日志 / 私有KB·RAG / 多端入口 / 团队共享 |
| Grok Build | 垂直代码子引擎 | `grok_build_engine.py` | 本地仓库解析 / 批量重构 / Git+终端 / 低内存Mac / 漏洞检测 / 单测生成 |

### 2.2 顶尖大模型能力吸收
| 模型能力 | 落地位置 |
|----------|----------|
| GPT 多步骤链式推理 | `reason.self_refine` / `reason.thinking_protocol` |
| GPT 多工具并行调用 | `orchestrator` 并行节点 + `openclaw_gateway.MCPAdapter` |
| GPT 图文多模态综合 | `reason` 协议 multimodal slot（预留，模型后端支持即生效） |
| GPT 复杂需求拆解 | `intent_router` + `runner.plan` |
| Claude Fiber5 百万上下文 | `memory` 长期层 + `kb` 分块窗口（可配大窗口模型） |
| Claude Fiber5 像素级屏幕识别 | `openclaw_gateway.BrowserAdapter.screenshot` + `DesktopAdapter` |
| Claude Fiber5 超长文档无损解析 | `kb` 解析器 + `grok_build_engine.RepoParser` |
| Claude Fiber5 长复杂任务规划 | `runner` 分步 + checkpoint + 续跑 |

### 2.3 硬性部署约束落地
| 约束 | 落地方式 |
|------|----------|
| ① 全流程本地化私有化 | `ModelBackend` 默认 `StubBackend`/本地；无遥测；记忆/KB/对话落本地文件 |
| ② 模块化松耦合 | 每引擎独立 class + 独立进程入口（future `xai-engine-*`）；`register()` 可热换适配器 |
| ③ 兼容离线量化+各家API | `model_router` 支持 `local-quantized` / `openai` / `anthropic` / `glm` / `qwen` 路由与 fallback |
| ④ 两套部署方案 | Mac 32G：单进程轻量（默认）；Linux 集群：每引擎一进程（compose/未来） |
| ⑤ 统一操作台 | `frontend` 单一入口 + `intent_router` 自动分流 + 结果全局汇总 |

### 2.4 三痛点解决
| 痛点 | 方案 | 模块 |
|------|------|------|
| ① 记忆割裂 | 全局统一记忆池（engine 标签 + 跨引擎查询，单一事实源） | `memory.py` |
| ② 意图自动识别分发 | 意图路由器（关键词+可选模型消歧，确定性兜底） | `intent_router.py` |
| ③ 权限分级管控 | 分级策略（P0/P1/P2）+ 高危二次确认队列 | `guardian.py` |

---

## 3. 模块清单与当前状态（v2）

| 模块 | 文件 | 状态 | 说明 |
|------|------|------|------|
| 模型后端 | `model_backend.py` | ✅ | 抽象 + Stub，模型无关 |
| 模型路由 | `model_router.py` | ✅ | 节点级多模型 + fallback |
| 安全审批 | `guardian.py` | 🔧升级中 | 加分级策略 + 二次确认（痛点3） |
| 思考增强 | `reason.py` | ✅ | 预算/协议/自精炼/多轨迹 |
| 元认知 | `meta.py` | ✅ | Brier 在线校准 + L8 四维审计 |
| 超长任务 | `runner.py` | ✅ | 分步/checkpoint/续跑/质量门 |
| 知识库 | `kb.py` | ✅ | 本地 RAG（非 IMA） |
| 多Agent编排 | `orchestrator.py` | ✅ | 管线 + 协作两模式 |
| 自蒸馏进化 | `distill.py` | ✅ | 探针→抽取→验证→注册 + GEPA |
| 统一记忆池 | `memory.py` | 🔧升级中 | 四层 + engine 标签 + 跨引擎（痛点1） |
| 技能注册 | `skills.py` | ✅ | SKILL.md + 优先级 + 渐进披露 |
| **意图路由** | `intent_router.py` | 🚧子Agent | 痛点2 |
| **执行网关** | `openclaw_gateway.py` | 🚧子Agent | OpenClaw 吸收 |
| **代码引擎** | `grok_build_engine.py` | 🚧子Agent | Grok Build 吸收 |
| 中枢控制环 | `control_loop.py` | ✅ | 单向环（已解 C1） |
| 前端 | `frontend/` | 🔧升级中 | 四引擎 + 意图路由 + 记忆池 + 权限 |
| Rust 真集成 | `rust/xai-grok-*` | ✅ | guardian / reason 两 crate 已 cargo test |

---

## 4. 进程与部署拓扑

### Mac 32G 轻量（默认，单进程）
```
xai-console (前端 Vite+React)
   └─ xai-core (Python 单进程：router + gateway + engine + memory + guardian + reason + meta + runner + orchestrator + distill)
        └─ 本地模型 (Ollama/MLX) 或 用户提供的 API key（可选）
```
资源约束：模型走量化（如 Qwen3.6-35B-MoE 4bit）；核心 spine 内存 < 200MB（不含模型）。

### Linux 企业集群（每引擎一进程，经消息总线）
```
xai-console ──┐
              ├─ xai-gateway (OpenClaw 进程)
              ├─ xai-code (Grok Build 进程)
              ├─ xai-orch (调度中台进程)
              ├─ xai-memory (Hermes 记忆服务，单一事实源)
              └─ xai-brain (Guardian/Reason/Meta/Runner/Distill 横切服务)
   进程间：本地 Unix socket / gRPC；记忆池经 xai-memory 统一读写。
```

---

## 5. 数据闭环与隐私

- 所有持久化：`~/.xai/` 本地目录（记忆池 / KB 索引 / 工作流 JSON / 审批日志）。
- 无第三方遥测；若用户接入外部模型 API，仅该次请求出网（可配置走代理 / 完全离线）。
- 企业合规：Guardian 审计日志落本地，支持导出。

---

## 6. 落地路线（本轮推进）

1. ✅ 架构总纲（本文件）
2. 🚧 三独立模块（intent_router / openclaw_gateway / grok_build_engine）由子 Agent 并行实现 + 单测全绿
3. 🔧 memory → 统一记忆池；guardian → 分级权限（主 Agent 实施）
4. 🔧 前端平台化（四引擎 + 意图路由 + 记忆池 + 权限面板）
5. ✅ 整合：导出 + 全量 pytest 全绿 + 文档/记忆同步
6. 下一步（待指令）：接真实模型后端 / Rust 其余 crate / 画布 JSON 驱动真实核心

> 诚实边界：OpenClaw 网关、Grok Build 引擎当前为**抽象+Stub**（沙箱无法真控桌面/执行 git），接口与路由真实可测；接入真实 OpenClaw/Hermes 时仅需替换适配器实现，不动架构。
