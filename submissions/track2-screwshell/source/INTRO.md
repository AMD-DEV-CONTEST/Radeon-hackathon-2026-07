# ScrewShell —— 你的本地私有 AI 调查智能体

> 完全本地、隐私优先。跑在单张 AMD Radeon PRO W7900 上，用 MoL（Mixture-of-LoRA）让一个基座拥有多种专家技能。

**AMD AI DevMaster Hackathon 2026 · Track 2 — Private AI Agent Development & Local Deployment**

---

## 一句话定位

ScrewShell 是一个**完全本地、私有**的 AI 调查智能体：把它指向你机器上的一个工作区文件夹，它就能规划调查、检索本地证据、调用只读本地工具，最后返回**带行级引用的证据型答案**——全程不出本机。

---

## 解决什么问题

知识工作者会积累大量敏感材料：设计文档、合同、代码库、会议笔记。这些内容**不能上传到云端 AI**，但人工审阅又慢又容易漏。

ScrewShell 是你「自己机器上的私有调查员」，能回答这类多步问题：

> 「ROCm 迁移计划的主要风险是什么？引述相关文档。」
> 「现在调查这个仓库，解释为什么 benchmark 变慢了。只用本地文件。」

它会规划调查 → 用本地 RAG 取证据 → 调用只读工具 → 返回带 `file.md#L42-L58` 行级引用的证据型答案。每一步都可审计，数据永不离开本机。

---

## 三大特征

| # | 特征 | 说明 |
|---|---|---|
| 1 | **默认私有** | 推理、嵌入、检索、记忆全部本地；六种只读工具全部本地，零远程 API 调用、零遥测 |
| 2 | **MoL 单基座多技能** | 一个冻结的 27B 基座（Qwen3.6-27B）+ 多个 LoRA 专家，在同一常驻基座上热切换；社区专家即插即用 |
| 3 | **证据型答案** | 每条结论配证据卡（文件/行引用 + 置信度 + 审计轨迹），可随时复验 |

---

## 6 层架构

```
User ── Web UI (Gradio) / CLI
        ▼
  Orchestrator（自研轻量 ReAct 循环）
  ├─ Task Planner        任务卡 + 子步骤（技能标签）
  ├─ Skill Router        启发式路由 → 激活一个 LoRA 专家     ← MoL 入口
  ├─ Local RAG Pipeline  摄取 → 分块 → 本地嵌入 → 向量检索 → 引用
  ├─ Tool Layer          rag_search / read_file / list_dir / grep /
  │                       shell_readonly / rocm_smi （只读、沙箱化）
  ├─ Artifact/Evidence/Memory Store  原始输出 / 证据卡 / SQLite 会话
  ├─ Safety Layer        工作区沙箱、路径白名单、危险命令拒绝、JSON 审计日志
  └─ MoL Inference Core                              ← 40 项优化
       ├─ 冻结 Qwen3.6-27B-Q4_K_M GGUF（~16.8 GB，常驻 W7900 VRAM）
       ├─ LoRA 专家：btl3 / cybersec / rag_n7（已转化）；teichai_plan（规划，无权重降级 base）
       ├─ Router：每步在常驻基座上热切换 LoRA（llama.cpp adapter swap）
       └─ ROCm 运行时：llama.cpp HIP 构建 + llama-server（OpenAI 兼容 /v1）
```

---

## 五大核心能力（5/5）

| 能力 | 实现 | 演示 |
|---|---|---|
| **本地 RAG** | 文件夹摄取 → 行感知分块 → 本地 GPU 嵌入（Qwen3-Embedding-0.6B）→ 余弦检索 → `file#Lx-Ly` 引用 | 问本地文档得带引答案 |
| **工具调用** | 6 个只读本地工具，权限门后；原始输出离上下文存入 Artifact Store | UI 可见工具回执 |
| **多步规划** | Task Planner 发任务卡；每步技能标签并路由到 LoRA 专家 | 实时规划面板 |
| **多轮记忆** | SQLite 会话历史 + 任务状态 + 证据库；追问可解析先前结论 | 「哪个文件支持这点？」可用 |
| **权限控制** | 工作区沙箱、工具/路径白名单、密钥路径黑名单、危险命令拒绝、人工审批钩子、JSON 审计日志、零遥测 | UI 审计面板 |

---

## AMD Radeon 上的 MoL 优化（实测）

**问题**：一个 agent 需要多种专家技能。朴素做法是每技能一个完整模型 → 每次切换全量重载，或 N× VRAM 装不下单张 48GB 卡。

**优化**：在 W7900 VRAM 中常驻一个冻结 27B 基座，每步切换 **MB 级 LoRA 适配器**，而不是重载整套模型。

**W7900 48GB / ROCm 7.2.4 实测对比：**

| 指标 | 朴素每技能模型 | MoL 热切换（实测） |
|---|---|---|
| 3 技能 VRAM | **~50 GB**（3×16.8 GB，装不下 48GB） | **18.9 GB**（基座+适配器常驻） |
| 技能切换 | 全量 27B 重载 = 秒级 | **平均 0.65 ms** 热切 |
| 吞吐 | 每技能专用模型 | 基座 **31.0 tok/s** 解码 / ~100 tok/s 预填充；带适配器 23.4–26 tok/s |
| 模型加载 | 每次切换重载成本 | **9 s** 一次，之后常驻 |

**更深一层的实测依据**（为什么用「全局切换 + 串行队列」架构）：
- per-request 换帽 **100% 摧毁前缀 KV 缓存**（re-prefill +2.35s），而全局 `POST /lora-adapters` toggle **KV 全命中**（两者差 **415 倍**）。
- 真机 decode 健康 **~30 tok/s**；带适配器时每 token 15–25% decode 税——这同时证明适配器真实参与计算路径。

**LoRA 专家阵容**（全部校验基座 == `Qwen/Qwen3.6-27B`）：

| 专家 | 来源 | 适配技能 | GGUF 状态 |
|---|---|---|---|
| `btl3` | `badtheorylabs/BTL-3` (r32/α64) | tool / code | 已转化 ✓ |
| `cybersec` | `hotdogs/qwen3.6-27b-cybersecurity-lora` (r8/α16) | security | 已转化 ✓ |
| `rag_n7` | `lananhyeuem/qwen3.6-27b-multilingual-rag-lora-n7` (r128/α256) | doc / 证据报告 | 已转化 ✓ |
| `teichai_plan` | `TeichAI/...Fable-5-Experimental-LoRA` (r64) | agent / 规划 | 无权重来源 ✗（运行时降级 base） |

> 注：`teichai_plan` 当前无可用 GGUF 权重，路由到它时静默降级为基座原生能力——这是数据缺口，非 bug，如实标注。

---

## 产品形态：两种入口，一个后端

ScrewShell 提供两种接入方式，共享同一套后端：

1. **自研网页对话 agent**：Gradio UI（:7860）走自研 ReAct Orchestrator + Toolkit + MoL 路由。
2. **兼容成熟前端（opencode / pi）**：外部 agent 前端**不直接连 llama-server**，而是连到 ScrewShell 作为**中转网关**（relay，:18090，OpenAI `/v1` 兼容协议）。ScrewShell 夹在中间，对流量统一做配置注入、可观测采集、调优、MoL 路由。

```
front-end → ScrewShell relay → llama-server
```

配套**统一观测层**：`/health`、`/v1/observ/{summary,events,gpu}`；并落地了 **gateway 五层调优旋钮**（配置自动化 / 容量规划 / 推理调度 / 可靠性守护 / 一键编排启动）。

---

## 意义与展望

- **隐私**：敏感数据不出本机，满足企业/个人无法上云的数据审查场景。
- **成本**：一个基座 + MB 级适配器 = 多技能，而非多套完整模型。
- **开放**：社区训练的 LoRA 专家即插即用——丢一个 GGUF 适配器就获得一项新技能。
- **未来方向**：统一观测/调优层进一步深化（部署配置自动生成、容量规划、推理调度、进程守护）。

---

## 参赛信息

- **赛事**：AMD AI DevMaster Hackathon 2026
- **赛道**：Track 2 — Private AI Agent Development & Local Deployment
- **截止**：2026-08-06 23:59 (UTC+8)
- **许可证**：Apache-2.0

---

*本文基于仓库权威信源 `docs/TRUTH.md` 撰写；所有技术数字与 TRUTH 一致。*
