# 前端工具选型 × 端到端优化整体方案

> 适用语境：djb 的 AI PM 转型作品集 + screwshell（MoL 热换装推理产品）的研发工作流优化。
> 核心命题：**端到端优化不只发生在产品运行时（MoL 推理链），也发生在"你坐在哪个前端工具里把东西造出来"的研发工作流。** 前端工具选型，是研发 E2E 的第一道闸；选错 = 整条链埋雷、反复 re-explain、验证断层。

---

## 0. 重新定义"端到端优化"：两条 E2E 链

| 链 | 含义 | 你在哪一层 |
|---|---|---|
| **产品运行时 E2E** | 规划 → 路由 → RAG → 工具 → 生成 → MoL 换装 | 你已经磨到极致的是"MoL 换装/显存/吞吐"这一小段（即"40 项优化"） |
| **研发工作流 E2E** | 需求 → 代码 → 验证 → 交付/演示 | 前端工具（WorkBuddy / OpenCode / Codex / Claude Code / Pi）是这个链的"切片机" |

**本方案只解决第二条链的工具选型**，并把它并入端到端优化叙事：因为工具选对了，研发 round-trip 最少、上下文不丢、验证闸能自动挂上——这本身就是"延迟 + 效果"双重优化。

---

## 1. 候选工具谱系（2026-07 现状核实）

| 工具 | 架构定位 | 许可证/厂商 | 一句话特征 |
|---|---|---|---|
| **WorkBuddy** | IDE 嵌入式 + 本地 agent + 云端连接器生态（本会话所在） | 闭源产品 | 一站式：研究/写/跑/可视化/交付/记忆/自动化 |
| **OpenCode** | 本地 client/server，TUI/桌面/IDE 多前端 | MIT（SST 团队，~180K+⭐） | 开源、模型无关(75+ provider)、LSP 原生、隐私优先 |
| **Codex** | 云端异步 agent + 桌面指挥中心 | OpenAI（ChatGPT 订阅内含） | 云端 sandbox 并行、worktree 隔离、skills、自动化动作 |
| **Claude Code** | 终端/IDE/Slack/GitHub/Web 多面 | Anthropic（闭源，$20–200/mo） | 六层扩展（CLAUDE.md/Skills/Hooks/Subagents/MCP/Agent Teams）最成熟 |
| **Pi (pi.dev)** | 极简 harness（OpenClaw 内核） | MIT（Mario Zechner） | 4 工具、<1000 token 系统提示、靠扩展/技能/包自拼 |

> 你列出的"Work Buddy / Open Code / Codex"是三个代表；Claude Code 与 Pi 是你 PM 研究路径里的对照样本，一并纳入评分。

---

## 2. 四维度评分卡（针对 screwshell 语境的定性判断）

维度定义（你的原话）：
- **集成能力**：能否接 screwshell 的本地代码、本地 llama-server、MCP 连接器、是否能在沙箱里跑 Node/Python headless 验证。
- **性能表现**：agent loop 延迟、上下文窗口管理、长任务稳定性、并行执行能力。
- **可扩展性**：能否自定义 skill/subagent/MCP、能否并行多 agent、配置能否打包移植。
- **开发效率实际提升**：少返工、少 re-explain、能跑真机验证、交付物能直接产出。

| 工具 | 集成能力 | 性能表现 | 可扩展性 | 开发效率 | 一句话定位 |
|---|:--:|:--:|:--:|:--:|---|
| **WorkBuddy** | ★★★★★ | ★★★★ | ★★★★ | ★★★★★ | 编排中枢 + 交付/演示面 |
| **OpenCode** | ★★★★ | ★★★★ | ★★★★★ | ★★★★ | 重型实现 + 本地模型 + 你拥有源码 |
| **Codex** | ★★★ | ★★★★★ | ★★★★ | ★★★★ | 批量/并行/一次性大改的云端工厂 |
| **Claude Code** | ★★★★ | ★★★★ | ★★★★★ | ★★★★★ | 日常主力 + 确定性质量闸（hooks） |
| **Pi** | ★★ | ★★★ | ★★★★★(需自拼) | ★★ | 陪练/读源码/独立搭原型的 harness 实验室 |

**逐项解读（关键事实，非旧印象）：**
- **OpenCode** 的杀手锏是 **LSP 原生**（type-aware 理解代码，不是 grep）+ **client/server 可远程驱动** + **本地 llama.cpp/Ollama 直接接 screwshell 私有推理**，且**隐私优先、不存你的代码**——对敏感/本地权重项目最稳。
- **Codex** 已不是"聊天助手"，而是**云端异步并行工厂**：多 sandbox 同时跑、worktree 隔离、subagents 并行、skills 把"指令+资源+脚本"打包、还有**定时自动化动作**（后台跑、进审查队列）。代价：依赖联网/云端，本地私有服务（如你的 llama-server）接入不如 OpenCode 直。
- **Claude Code** 的 **Hooks = 确定性质量闸**（编辑后自动 lint/format/安全扫描，必定执行，不靠模型记性）——正好补你项目一直有的"缺验证闸"老坑；setup 能打包成 plugin 一键移植。
- **Pi** 故意"不造" MCP/subagent/plan mode，全靠扩展自拼；它的最大价值是**可读源码、做 context engineering 实验、独立搭你自己的 harness**（你的"读懂→改→独立搭"学习路径正解），但日常生产力不如上面四个。

---

## 3. 结论：不是"选一个"，是"分层编队"

单一工具无法同时赢下"交互精细控制 + 云端并行批量 + 本地私有推理 + 确定性质量闸 + 演示交付"。正确做法是**按任务切片编队**，每条切片用最顺手的那把刀：

```
                    ┌─────────────────────────────────────────┐
                    │            研发 E2E 编队（squad）          │
                    └─────────────────────────────────────────┘
  需求/研究/演示交付  ──►  WorkBuddy   （本会话：可视化 + present_files + 连接器 + 记忆）
  重型实现/长编码     ──►  OpenCode    （本地模型、LSP、你拥有源码、隐私）
  一次性大改/并行评测  ──►  Codex       （云端 sandbox 并行、skills、自动化动作）
  日常主力 + 质量闸   ──►  Claude Code （hooks 确定性质量闸、plugin 移植）
  读源码/独立搭原型   ──►  Pi          （harness 实验、context engineering）
```

**任务 → 工具 决策表：**

| 任务类型 | 首选工具 | 理由 |
|---|---|---|
| 写 roomy 真机跑测脚本 + 产出 `_e2e_evidence/run_roomy.log` | WorkBuddy 编排 + 用户在真机跑 | 脚本可 present，但真机载 27B + 4 LoRA 属重操作，需在用户真机执行 |
| 起草 `OPTIMIZATIONS_40.md`（拆那 40 项） | OpenCode / Claude Code | 长任务、上下文稳、hooks 自动质量闸 |
| 跑 RAG 召回评测 + 端到端答案 MoL-vs-base 打分 | Codex 并行 sandbox（或 WorkBuddy 自动化定时跑） | 可同时派多个评测 agent、互不干扰 |
| 修 README/SPEC 的 VRAM 矛盾（纯文档） | WorkBuddy / 任意 | 轻量 |
| 落地"预测式预热"代码 | OpenCode（本地模型可即时验证） | 需接 screwshell 代码真值、跑 headless 验证 |
| 演示视频编排（露 rocm-smi + 快路径） | WorkBuddy | visualizer + present_files 交付面 |
| 读懂 Pi/OpenCode 源码、独立搭 harness | Pi | 极简可改、RPC/SDK 可嵌入 |

---

## 4. 把"工具层"并入 screwshell 的端到端优化策略

你前两轮审计发现的缺口，用编队可以一次性补齐——**工具的每段都对应一道验证闸**：

| screwshell 缺口（前两轮审计） | 用哪把刀补 | 优化本质 |
|---|---|---|
| roomy 0.65ms 只有微基准、无端到端留证 | WorkBuddy 写脚本 + 真机跑 | 研发 E2E 延迟账补全 |
| "40 项优化"是空标签 | OpenCode/Claude Code 长任务拆 | 效果/完整性验证闸 |
| RAG 无召回评测、无端到端答案质量 | Codex 并行评测 sandbox | **效果优化**闸（最大洞） |
| 缺"预测式预热"实现 | OpenCode 本地验证 | 延迟优化补完 |
| VRAM 数字矛盾 | WorkBuddy 轻修 | 文档一致性 |
| 缺确定性质量闸（老坑） | Claude Code hooks | **流程层验证闸** |

> 这正好回应你一直强调的方法论：**别陷在行级 bug，要拔高到流程/系统层**。工具编队 + hooks/自动化 = 把"验证闸"从人工记得，变成系统强制。

---

## 5. 落地路线（对齐 8/6 截点，30 天）

**第 1 周（P0，决定招牌是否成立）**
1. WorkBuddy 起草 `scripts/run_roomy_e2e.py` + 真机产出 `run_roomy.log`（roomy 快路径端到端留证）。
2. 演示视频脚本：对齐快路径 + 露 `rocm-smi`（用 WorkBuddy 编排）。

**第 2 周（P1，补效果优化洞）**
3. OpenCode/Claude Code 起草 `OPTIMIZATIONS_40.md`，挂钩 SPEC。
4. Codex 并行跑 `bench/eval_e2e.py`（MoL-vs-base + 引用准确率）+ RAG 召回评测。

**第 3 周（P1，修一致性）**
5. 修 README/SPEC VRAM 措辞、`rag_n7`↔`n7` 命名根治。

**第 4 周（P2，流程层闭环）**
6. 用 Claude Code hooks 把"评测闸门"钉死（编辑即 lint + 跑 G1–G5）。
7. 真机起服务做一次完整调查，产出端到端时延 trace。

---

## 6. 给评委的一句话（作品集表达）

> "我的端到端优化覆盖两条链：产品运行时（MoL 热换装把换装从 5s 降到 0.65ms）+ 研发工作流（按任务切片的前端工具编队，让每类任务都用最顺手的 agent，并用 hooks/自动化把验证闸从人工变成系统强制）。两条链共用同一套方法论——**把验证做进流程，而不是靠记性**。"

---

*附：本方案评分基于 2026-07 公开资料（OpenCode 官网/zread、OpenAI Codex 文档、Claude Code 六层扩展文档、pi.dev）的定性判断，非实时基准测试。若要对外放绝对数字，需补一份可控环境的 head-to-head benchmark。*
