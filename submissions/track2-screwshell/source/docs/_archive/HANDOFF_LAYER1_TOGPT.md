# ScrewShell 第一层（中继网关）需求与方案交接文档

> **用途**：本文档用于把项目背景 + 第一层详细需求交接给外部 AI（GPT 等）协助设计。
> **读者**：不熟悉本项目的人。请先读 §1–§4（需求），§5–§6（方案方向，简略）供对齐。
> **立场**：需求是用户（djb）确认的设想；方案是本项目 Agent 当前的方向，**未最终拍板**，待外部协助裁决。

---

## §1 项目一句话

ScrewShell = 完全本地、隐私优先的 AI 调查智能体，跑在单张 **AMD Radeon PRO W7900 (48GB, ROCm)** 上，用 **MoL（Mixture-of-LoRA，LoRA 热切换）** 在同一冻结基座（Qwen3.6-27B Q4_K_M GGUF，由 llama-server 服务）上实现多专家技能。参加 **AMD AI DevMaster Hackathon 2026 · Track 2（Private AI Agent Development & Local Deployment）**。

当前已实现：自研 ReAct orchestrator + 6 层架构（Planner / Skill Router / Local RAG / Tool Layer / Evidence+Memory+Safety Store / MoL Inference Core），以及 autotune 三层（L1 技能包 / L2 容量规划 / L3 双档换装）。**LoRA 阵容**：btl3 / cybersec / rag_n7 已转 GGUF 常驻，teichai_plan 无权重降级 base。

---

## §2 用户确认的整张架构蓝图（3 层）

| 层 | 内容 | 状态 |
|---|---|---|
| 第 0 层 | 本地私有 MoL 调查智能体（上述 6 层 + autotune），跑在 W7900 上 | **已落地** |
| 第 1 层 | **两种入口共享一个后端**：自研 Gradio Web UI + 成熟前端（opencode / pi）都连到 ScrewShell 暴露的同一套 OpenAI `/v1` 接口；ScrewShell 作为**中转网关**，在转发给底层 llama-server 前做配置注入 / 可观测 / 调优 / MoL 路由 | **半落地**（仅 P0/P1 薄适配 + 借外部 llama-swap 跑 peers 模式） |
| 第 2 层 | **统一观测 / 调优层**（计划态）：两种入口共享同一套可观测信号与调优旋钮；UI 对话即采集 e2e 优化数据 | **未实现** |

本文档只聚焦**第 1 层**。

---

## §3 第 1 层详细需求

### §3.1 核心目标
用户要求：ScrewShell 不应只服务自己的 UI，而要成为**所有前端流量的统一中枢**。链路应为：
```
前端(opencode / pi / 自研 Gradio UI)
   → ScrewShell 中转网关（OpenAI /v1 兼容）
   → llama-server（W7900 上的 Qwen3.6-27B）
```
ScrewShell 在转发前统一处理：**配置注入、可观测采集、推理调优、MoL 路由**。前端侧零改造（指向 ScrewShell 端口即可）。

### §3.2 功能需求拆解（5 片）
| 片 | 需求 | 说明 |
|---|---|---|
| ① 前置网关 + 鉴权 | 暴露 OpenAI `/v1` 兼容接口；API-key 鉴权；request-id / run-id 关联 | 所有前端流量先过 ScrewShell |
| ② 可观测 | 采集：tools 实际可用性探活、首 token 延迟、思考耗时占比、KV 占用、LoRA 路由命中 | 之前踩坑：`/v1/models` 的 `capabilities` 字段恒为 `["completion"]`，**不可信**，必须用真实请求判定 |
| ③ 模型生命周期守护（managed-mode） | 网关**接管 llama-server 生命周期**：自动启动、启动前配置校验（端口占用/二进制路径/模型存在）、进程守护（SSH 断开不被回收）、崩溃自动重启 | 当前现状见 §4 |
| ④ MoL 按请求 skill 路由 + thinking 调度 | 按请求注入 per-request LoRA（scale 组合）、按 agentic/非 agentic 切换 thinking | **这是项目灵魂，现有任何通用网关都不做** |
| ⑤ ScrewShell 自己是"中转" | 在转发路径上做 ④ 的路由/调度注入，串联 ①②③ | 不是简单反向代理，要在转发前改写请求 |

### §3.3 非功能 / 约束
- **本地私有、零云依赖**：核心推理不出本机；可选 web 工具默认关闭。
- **协议**：必须兼容原生 OpenAI `tools` 协议（opencode / pi 零改造接入的前提）。
- **硬件**：AMD W7900 48GB，ROCm 7.2.4，llama.cpp HIP 构建。
- **基座**：Qwen3.6-27B-Q4_K_M GGUF，常驻 VRAM ~16.8GB；带 LoRA 时 18.9GB。
- **已知启动铁律**（部署侧已坐实）：llama-server 必须加 `--jinja`（否则 tools 调不动）、`--reasoning-budget`（否则 "hi" 卡 130s+）、`--ctx-size 131072`、`setsid` 启动（否则 SSH 断开被回收）。

---

## §4 当前现状与已踩的坑（第 1 层现状）

- **P0/P1 已做**：ScrewShell 侧薄适配（`screwshell/core/mol_engine_llamacpp.py`）——注入 `Authorization` / `X-Request-Id` / `X-Run-Id`、解析网关 model id、状态面板数据。**但这只是"网关客户端"侧，不是网关本身。**
- **真正的网关角色由外部 `llama-swap` 承担**，且只跑 **peers 模式**（网关不接管 llama-server 生命周期）。
- **managed-mode 流式断流**：llama-swap v246 的 managed 模式（网关接管 llama-server 生命周期）在流式响应时会断。**这是 ③ 的最大阻塞。**
- **MoL 路由对外部前端不生效**：router 在 ScrewShell 自研 orchestrator 内部；外部前端（opencode/pi）走网关直连 llama-server 时**绕过 MoL 路由 / thinking 调度 / 工具治理**。这是 ④⑤ 的核心缺口（即"LoRA 自动路由是否对所有进来的请求生效"——待确认项）。
- **RUNBOOK 明确写"不重写 messages/tools/SSE"** → 当前"统一管控"只兑现了 auth/id/model 映射一小截。
- **pi 已移出范围（P0.5）**，仅 opencode 路径实测过工具调用。

---

## §5 方案方向（简略，待裁决）

**总判断：第一层 ≈ 70% 可借成熟开源项目，30% 新做；那 30% 恰是项目差异化灵魂。**

拼装思路（薄代理串联三片现成能力）：
```
前端 → ScrewShell 薄代理（新做：④ MoL 路由注入 + ⑤ 串联）
        → 鉴权/路由片（借 LiteLLM 或 one-api，或继续 llama-swap）
        → 可观测片（借 Helicone，自托管代理，改 base_url 即可）
        → 生命周期片（借 LocalAI 或 llama-swap managed）
        → llama-server
```

- **借（不用新写）**：① 鉴权+路由 → LiteLLM / one-api；② 可观测 → Helicone（Apache 2.0 自托管，纯代理零侵入）；③ 生命周期 → LocalAI（把 llama.cpp 包成 gRPC backend，自带生命周期+监控）或 llama-swap managed。
- **新做（必须自己写）**：中间**薄代理**——在转发前注入 per-request LoRA / thinking 调度（④），并串起上述三片（⑤）。这是 ScrewShell 独有、无人能代劳的部分。

---

## §6 参考项目速查（给协助者的弹药）

| 项目 | 定位 | 与第 1 层关系 | License |
|---|---|---|---|
| **LocalAI** | 本地 OpenAI 替代品，把 llama.cpp 包成 gRPC backend | 最接近第 1 层整体：API key 认证+多用户配额+模型生命周期+系统监控+WebUI，AMD/ROCm 镜像现成 | MIT |
| **LiteLLM** | AI 网关事实标准（100+ 供应商） | 借 ①：虚拟 key/auth/路由回退/request id；把 base_url 指向本地 llama-server 即可用 | 核心 Apache 2.0 |
| **one-api**（songquanpeng） | 轻量 LLM API 网关 | 借 ①：key 管理/配额/负载均衡/用量，支持本地后端；比 LiteLLM 轻 | MIT |
| **llama-swap** | 本地模型网关（alias/swapping/peering） | 已在用；peers 模式可借，managed 模式 v246 流式断流（③ 阻塞点） | — |
| **Helicone** | LLM 可观测代理 | 借 ②：纯代理改 base_url，自动记请求/延迟/token/用户维度，可自托管 | Apache 2.0 |
| **Langfuse** | LLM 可观测（SDK 式嵌套 trace） | ② 备选：trace 更深、带 eval，但需 SDK 埋点 | MIT |
| **Open WebUI** | 坐在 llama.cpp 前的成熟 UI | 第 2 层方向2 参照（UI 即另一前端+可观测面板）；第 1 层不直接用 | MIT |

**关键提醒**：以上项目绝大多数是云端/通用导向，**没有任何一个做"本地 27B 上的 MoL 按 skill 路由 + thinking 调度"**——这是 ScrewShell 必须自写的部分。

---

## §7 待外部协助裁决的开放问题

1. **③ 生命周期片怎么选**：LocalAI（取代 llama-server，最完整但改部署拓扑）vs llama-swap managed（已在用但流式断流，需等上游修或打补丁）vs 自写 supervisor？哪种对"本地单模型 + AMD ROCm"最稳？
2. **⑤ 薄代理该不该自己写 HTTP 代理**，还是直接复用 LiteLLM 的 proxy + 写个自定义 middleware 注入 MoL 路由？即：是自研薄代理，还是"LiteLLM + 插件"？
3. **④ MoL 路由如何对外部前端流量生效**：是在网关层拦截 `/chat/completions` 请求、按内容/header 注入 per-request lora，还是要求前端在请求里带 skill 标识？协议怎么定才不让 opencode/pi 感知？
4. **架构取舍**：是坚持"ScrewShell 自研薄代理串三片"，还是退一步"直接用 LocalAI 当网关 + ScrewShell 只做 MoL 路由插件"？哪种更省事且不丢差异化？

---
*文档生成：2026-08-03，基于项目 Agent 与用户 djb 的对话确认。需求部分为用户设想（已确认），方案部分为方向性（未拍板）。*
