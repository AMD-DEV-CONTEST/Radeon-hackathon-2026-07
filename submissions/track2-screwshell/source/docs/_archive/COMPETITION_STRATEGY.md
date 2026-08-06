> ⚠️ STALE：本文件已归档，唯一信源见 docs/TRUTH.md。
# ScrewShell — 参赛策略（AMD AI DevMaster Hackathon 2026 · Track 2）

> ⚠️ **内部策略文档，请勿随 PR 提交。** 配套证据见 `docs/LORA_SOURCE_VERIFICATION.md`。

> **✅ 状态更新（2026-07-29，见 `HANDOFF_EXPERT_ROSTER.md`）**：本文件 §2 描述的 `hermes_s2`/`fable5` 渗入提交文档问题**已解决**——两专家已从阵容彻底清除（hermes_s2 基座静默错配、fable5 仓库 404/私有化），相关文档（SPEC/PPT/视频脚本/README）已全部改写为新阵容 `btl3`(工具/代码) + `cybersec`(安全,新增) + `teichai_fable5_plan`(规划) + `rag_n7`(文档,回退=base)。**注意**：本节 §2 推荐的 "Option A（工具步改用基座原生 function calling、不挂 LoRA）" 已被用户拍板的最终阵容**取代**——最终选择是用 `btl3`（BTL-3 LoRA）顶替工具步，而非去 LoRA 化。请勿据此文档回退到 Option A，以免推翻已确认阵容。MoL 不变量风险分析本身仍成立，可作为复盘教训。

---

## 0. 一句话结论

ScrewShell 几乎是**为 Track 2（Private AI Agent Development & Local Deployment）量身做的**：纯本地、跑在 AMD Radeon（ROCm）上、五能力齐全、还有 MoL 这个明确的"创新点"。**契合度很高，不是硬凑。**

但有一处**会直接冲掉 submission 的雷必须先在 8/6 前排掉**：你上一轮核实出的 `hermes_s2` 基座错配，已经写进了 SPEC / PPT / 视频脚本里，而且是以"已转换✓、行为已验证"的正面姿态写的。

---

## 1. 比赛规则/主题速读（来自仓库现有文档）

| 项 | 内容 |
|---|---|
| 赛道 | **Track 2 — Private AI Agent Development & Local Deployment** |
| 硬件主题 | **AMD Radeon（ROCm）** —— 评委必须"看到真实 Radeon 在跑" |
| 截止 | **2026-08-06 23:59 (UTC+8)**；建议 **8/5 前** PR（留 1 天缓冲） |
| 提交物 ① | 英文 SPEC 文档（`docs/SPEC.md`） |
| 提交物 ② | 源码 + README（英文，5 个规定章节） |
| 提交物 ③ | **3–5 分钟演示视频，必须露 `rocm-smi`** 证明真在 Radeon 上跑 |
| 提交物 ④ | 10 页 PPT / Poster（英文，money slide = benchmark 数） |
| 提交方式 | Fork `AMD-DEV-CONTEST/Radeon-hackathon-2026-07` 提 PR |

**评委看重的（从规则反推）**：① 真·本地/隐私；② 真·跑在 Radeon/ROCm；③ agent 能力（RAG/工具/规划/记忆/权限）；④ 创新点；⑤ 真实硬件 demo 可复现。ScrewShell 五项全中。

---

## 2. 🔴 #1 风险：hermes_s2 基座错配已渗入提交文档

上一轮已核实：`hermes_s2`（真实来源 `samscrack/Qwen3.6-27B-Hermes-S2-LoRA`）是 **stage-2 LoRA，真实基座是 `samscrack/Qwen3.6-27B-Opus-CoT-Stage1`，不是干净的 `Qwen/Qwen3.6-27B`**。架构一致 → llama.cpp 能静默加载、能出 token，但行为错位。

而仓库里这些地方**仍以"正确/已验证"姿态写了 hermes_s2**：

- `docs/SPEC.md` §2 架构图（L56-57）：`LoRA experts (GGUF) hermes_s2 (tool) · fable5 · teichai`
- `docs/SPEC.md` §4 模型表（L87）：`hermes_s2 … converted ✓`
- `docs/SPEC.md` §5（L112）：`Behavior differentiation verified at temp=0: hermes_s2 adds tool-selection reasoning`
- `docs/PPT_OUTLINE.md` Slide 5（L29）：`hermes_s2 (tool) · fable5 · teichai`
- `docs/VIDEO_SCRIPT.md` Shot 1（L24）：`expert badge switching (teichai → hermes_s2)`

**为什么这是 submission 杀手**：
1. 整套 **MoL 立论 = "N 个专家共享同一个冻结基座"**。hermes_s2 打破这个不变量——它要的是 Opus-CoT-Stage1，不是干净基座。评委若核对 config 或复跑，立论直接垮。
2. §5 那条"hermes_s2 adds tool-selection reasoning"是在**错配基座**上测的，结论无效；demo 里"工具专家"实际在产出错位行为。
3. 这正是你项目反复踩的"能加载、但跑不对"类 bug——而且现在它进了**比赛材料**。

### 修复（推荐 Option A）
把"工具"这一步从 `hermes_s2` LoRA **改成在干净基座上用 Qwen3.6-27B 的原生 function calling**（llama.cpp `/v1` 原生支持 Qwen 工具调用；搜索证据也显示 Qwen3.6-27B 原生工具调用很强，"有望成为 Hermes Agent 最可靠的本地大脑"）。

- `router.py` 的 `skill_map` 里，`tool` 技能 → 干净基座 + 工具调用 system prompt + function schema（**不挂 LoRA**）。
- `teichai`（规划）、`fable5`（代码/doc）继续用 LoRA —— 它们的基座是对的。
- 效果：① 彻底消除错配雷；② 工具专家反而更准（原生调用）；③ MoL 故事保留（2 个 LoRA 专家 + 1 个原生工具调用模式，全在同一个干净基座上）；④ demo 的"专家切换"变成 `teichai → [原生工具调用] → fable5`，诚实可复现。

> 备选 Option A'：换一个基座就是干净 `Qwen3.6-27B` 的工具 LoRA。但原生调用更简单更强，**优先推荐 Option A**。

---

## 3. macaron / Mind Lab 参考定位（已核实 ✅）

你记的 "MOM" 实为 **macaron** —— **Mind Lab（mindlab.ltd，"A Lab for Experiential Intelligence"）开源的 Macaron A2UI**。已拉 HF 模型卡核实：

- **它是什么**：一个 **LoRA 适配器**（Tall 变体），让"个人 Agent"根据对话上下文/产品状态/可用动作，**生成结构化 UI 卡片（A2UI v0.8）**——即 Agent 自己"画"界面。不是通用聊天模型。
- **基座（写得很干净）**：`Qwen/Qwen3-30B-A3B-Instruct-2507`（Qwen3 MoE，注意：是 **Qwen3 不是 Qwen3.6**，你记成 3.6 属于口误，PPT 里别写错）。
- **方法**：GRPO 后训练 + LoRA（r=16/alpha=32，全线性层）；MIT 许可；有技术报告（arXiv 2605.24830）。
- **家族**：Tall(Qwen3-30B) / Grande(Qwen3-235B) / Venti(GLM 5.1)，都是 LoRA 适配器发布。

### 为什么它对你有用（定位框架）
- **它是"千问基座 + LoRA 增强"这条路的干净范本**：base_model 明确、适配器独立发布、协议/许可清晰。正好反衬你 hermes_s2 那种"基座没核实就写进文档"的坑——这也是你该在 PPT 里体现的工程纪律。
- **它不是你的竞品，是同一生态的参照系**：macaron = 单任务 LoRA 能力（生成 UI）；ScrewShell = 把多个社区 LoRA（teichai/fable5）+ 原生工具调用**编排**到一张 Radeon 上跑的多技能 Agent 系统。
- **ScrewShell 的差异化**（对标 macaron 这类"强 Qwen LoRA"工作）：
  - MoL 多专家热切，把多技能压进单卡 VRAM（~50GB→~17GB）—— macaron 只解决"一个能力怎么做对"，你解决"N 个能力怎么在一张卡上共存"。
  - 每条结论带 `file#Lx-Ly` 引用 + JSON 审计——**证据优先**，评审记忆点强。
  - 隐私 by construction（沙箱/allowlist/零远程 API）—— 直接命中 Track 2 主题。
- **一句话对标（可进 PPT）**：*"Macaron 证明了在千问基座上用 LoRA 打磨单点能力可行；ScrewShell 把这类能力变成可在单张 Radeon 上热切、可审计、可引用的多技能调查 Agent。"*

→ 你的故事不要讲成"我也要做个 Qwen3.6 agent"，而是讲**"在单张 Radeon 上用 MoL 把多专家塞进 VRAM，并给每个结论附证据链"**。

---

## 4. 倒计时行动表（7/28 → 8/5，约 8 天）

| 天 | 动作 | 产出 |
|---|---|---|
| D1 (7/28) | **排 hermes_s2 雷**：改 `router.skill_map` 用原生工具调用；重跑 `scripts/day4_e2e_test.py` + `bench/benchmark_mol.py` | 工具步骤跑通且无错配 |
| D2 (7/29) | 改提交文档：SPEC §2/§4/§5、PPT Slide5、VIDEO Shot1 同步真实状态 | 文档与代码一致 |
| D3 (7/30) | 在真机 W7900 上跑通端到端 demo，确认 `rocm-smi` 可见 | demo 脚本定稿 |
| D4 (7/31) | 录视频（按 VIDEO_SCRIPT，修正专家切换镜头）导 `screwshell-demo-radeon.mp4` | 提交物③ |
| D5 (8/1) | 做 10 页 PPT（money slide = benchmark；加一页"MoM/单模型参考 vs ScrewShell MoL"对比） | 提交物④ |
| D6 (8/2) | SPEC 终校 + README 五章节 + 源码清理 + 去标识（`deploy.sh` 已用 env var） | 提交物①② |
| D7 (8/3) | Fork + PR，写 PR 描述（一段摘要 + 视频/材料链接） | 提交 |
| D8 (8/4–5) | 缓冲：处理实例/端口漂移、补 benchmark 小字说明 | 安全提交 |

---

## 5. 提交前自检（在 SUBMISSION_CHECKLIST 基础上加一条）

- [ ] **NEW**：hermes_s2 已从 skill_map 移除/改为原生工具调用；SPEC/PPT/VIDEO 三处描述同步，无任何"hermes_s2 已转换✓/行为已验证"残留。
- [ ] SPEC §5 benchmark 的 8.04ms/1305× 旧 9B 数字已明确标注"退役、不带入 27B 栈"（checklist 已要求）。
- [ ] 视频两处 `rocm-smi` 露脸（Shot 2 & 5）。
- [ ] `grep` 全仓无 host/port 硬编码、无密钥；core path 零远程 API。
- [ ] 内部文档（本文件、SUBMISSION_CHECKLIST、LORA_SOURCE_VERIFICATION）**不进 PR**。

---

## 6. 我可以直接帮你做的下一步

1. 改 `router.py` 的 `skill_map`，把 `tool` 路由到原生 function calling（Option A）；
2. 同步改 SPEC §2/§4/§5、PPT Slide5、VIDEO Shot1 三处 hermes_s2 描述；
3. 出一版"MoL vs 单模型参考（MOM/OpenClaw）"对比页，直接进 PPT。

你确认 MOM 具体是哪个，或让我直接开干以上 1–3，我就动手。
