> ⚠️ STALE：本文件已归档，唯一信源见 docs/TRUTH.md。
# 官方树可用专家白名单（批量核验报告）

> 生成：2026-07-29 · 工具：`scripts/verify_lora_whitelist.py`（HF API 全量扫描，经 hf-mirror）
> 原始数据：`docs/lora_whitelist_scan.csv`（全部 349 条逐项判定）
> 铁律：`adapter_config.json :: base_model_name_or_path` 精确 == `Qwen/Qwen3.6-27B` 才算 PASS。
> 背景：hermes_s2 事故（真实基座 = samscrack/Opus-CoT-Stage1，静默错位）后建立的核验流程。

## 0. 总览

| 树 | adapter 总数 | PASS | MIRROR | LOCAL_PATH | VARIANT | 坏/缺配置 |
|---|---|---|---|---|---|---|
| `Qwen/Qwen3.6-27B`（官方） | **335**（比网页显示的 309 多） | 238 | 1 | 15 | 5 | 76 |
| `unsloth/Qwen3.6-27B`（镜像） | 14 | 0 | 7 | 0 | 1 | 6 |

**但 PASS≠可用**：238 个 PASS 里，148 个是 dementor-research 的 DPO/SFT 实验矩阵、22 个是 EvilScript 的 taboo 解释性研究系列、7 个 ericmao 课程作业——刨掉批量研究产物，**技能级独立 PASS ≈ 61 个**，其中值得当专家的见下。

## 1. 🏆 头号发现：BTL-3 —— hermes_s2 的完美替补

**`badtheorylabs/BTL-3`**（65 赞，官方树第一热门 adapter）

| 维度 | 实测 | 对我们的意义 |
|---|---|---|
| base_model | `Qwen/Qwen3.6-27B` **精确匹配，且钉死到 revision `6a9e13bd…`** | 通过铁律，比我们自己的文档还严谨 |
| 能力 | agentic coding + 结构化工具调用：**BFCL v4 AST 88.5%、irrelevance 91.2%（知道何时不调用工具）、HumanEval 95.1%** | 正是 hermes_s2 想当而没当成的"工具专家" |
| 形态 | PEFT LoRA r32/α64，adapter 934MB，Apache-2.0，附 SHA-256 | 独立 adapter 可热切；许可干净可参赛 |
| target_modules | 含 DeltaNet 的 `in_proj_qkv/z/b/a、out_proj` 全套（模型卡给了 vLLM 启动参数） | 说明是对 Qwen3.6 混合架构完整训练的，不是老配方硬套 |
| 风险 | ① 默认非 thinking 模式（RL-0013 的 thinking 会复读/不停机，模型卡自曝）② 需过我们的 llama.cpp 转换墙——**已核**：其 target_modules 正则与 teichai 同族（unsloth 风格，覆盖 DeltaNet in_proj/out_proj），teichai 已成功转出（992 tensors），BTL-3 走同一补丁路径，但须本地实转验证 ③ repo **无现成 GGUF**（仅 954MB safetensors）④ 934MB adapter 比 teichai 大，热切延迟要实测 | 都可控 |

**行动建议**：`router.py` 的 `"tool"` 路由从 hermes_s2 换成 BTL-3。比"退回原生 function calling"更好——MoL 三专家叙事完整保留，且 BFCL 数字可直接写进 PPT。**换完必须核对我们本地基座权重是否就是 revision `6a9e13bd…`**（BTL-3 钉死了这个 revision，这正是它比 hermes_s2 靠谱的地方，别在自己身上重演）。

## 2. ✅ 即插即用白名单（技能级 PASS，按推荐排序）

| Adapter | 领域 | 配置 | 热度 | 备注 |
|---|---|---|---|---|
| **badtheorylabs/BTL-3** | 工具调用/编码 agent | r32/α64 | 65👍 177DL | 见上，首选 |
| **hotdogs/qwen3.6-27b-cybersecurity-lora** | 网络安全分析 | r8/α16 | 9👍 515DL | 下载量最高的技能级 LoRA；契合"调查 Agent"叙事 |
| **TeichAI/…-Fable-5-Experimental-LoRA** | 叙事/创作 | r64/α64 | 9👍 | 我们在用的 teichai，本次扫描再次确认 PASS ✅ |
| **yuxinlu1/…-chinese-xianxia-lora-v2** | 中文仙侠写作 | r16/α32 | 8👍 208DL | 中文创作专家候选 |
| Cyb3rDudu/cyb3r | 安全（细节待读卡） | r64/α128 | 2👍 87DL | cybersecurity 的备胎 |
| ~~nkasmanoff/qwen3.6-27b-opencode-lora~~ | 编码 agent | r16/α32 | 24DL | **终审降级**：模型卡是空白模板（零训练信息/零许可证），且 target_modules 含 DeltaNet 模块需过转换墙。不上台 |
| s-g-labs/linlu-lora-v0.4-qwen3.6-27b | 人格/助手 | r32/α64 | 66DL | s-g-labs 出品（就是模型卡里带 LoRA 激活自检代码的那家）；注意 **v0.2 是 LOCAL_PATH，只有 v0.4 干净 PASS** |
| SwarmDo/SwarmDo-A1 / A2 | 多 agent 协作 | r32–48 | 各 1👍 | 与 MoL 多专家叙事相关，可读卡再定 |

## 3. ⚠️ 降级与反转（相对上次人工预判）

- **yuxinlu1 系列反转**：上次判"同作者同配方大概率过"——错。实扫结果：xianxia v2 ✅，但 **crime-fiction v2 / folk-horror v2 的 base 写的是本地路径 `C:\AI\models\Qwen3.6-27B-HF`**（LOCAL_PATH：大概率是干净基座的本地拷贝，但 config 无法证明，须读模型卡确认）。同作者≠同配方，逐个核没有捷径。
- **hotdogs/mythos5k**：NO_CONFIG（根目录无 adapter_config.json），排除。
- **kai-os/Opus4.6-reasoning**：双杀——base 是 unsloth 镜像（MIRROR）+ 模型卡自曝 OOM 半成品，排除。
- **Delentia/jitna 套件**（router/executor/guardian/scribe 四件套，概念上和 MoL 高度同构）：模型卡是**空白模板**，零文档零出处，不可信，观察名单。
- **samscrack 全家**（Opus-CoT-S1-Hermes-S2-SFT 等）：NO_CONFIG / 挂错树，与 hermes_s2 同一血统，全部远离。

## 4. 🔍 MIRROR_BASE（unsloth 树 7 个 + kai-os）

phishing-detector、cybersec-v4、Webcoda、CyberSentinel 等方向都不错，但基座是 `unsloth/Qwen3.6-27B` 镜像。**用前必须做一次官方 vs unsloth 权重 checksum 对比**；不一致则整批放弃。优先级低——白名单里已有同方向的干净替代（cybersecurity-lora）。

## 5. 🎭 上台阵容终审（2026-07-29 深夜，用户要求"完美适配才行"）

对拟上台 4 专家做了终审级核验（逐个拉上游 config 全文 + repo 文件清单 + 转换墙预判）：

| 位置 | 候选 | 终审结论 |
|---|---|---|
| tool/code | **BTL-3** | ✅ **过**。base 精确 + 钉 revision；target_modules 正则与 teichai 同族 → 转换墙同一补丁路径可过（须本地实转确认）；无现成 GGUF，需自转 954MB safetensors |
| agent/plan | **teichai** | ✅ **过**（已转换 992 tensors、bench 实测过，全链路唯一"已完成"的） |
| security | **cybersecurity-lora** | ✅ **过，且是四个里最干净的**：target_modules 仅 q/k/v/o+MLP，**完全不含 DeltaNet 模块 → 零转换墙风险**，r8 仅约百 MB 级 |
| code/doc | ~~fable5~~ | ❌ **出局**：repo 已 404/私有化（API 返回鉴权错误），本地从未下载成功（bench 记录 converted:false）。**"完美适配"第 0 条是拿得到货** |

fable5 替补核验结果：opencode-lora（空白模型卡）、baddie5419/code-lora（无卡 + 全模块 DeltaNet）均不达"完美适配"标准。
**终审阵容建议：3 LoRA + base = 4 专家位** —— BTL-3（tool+code 双路由，它本就是 agentic-coding 出身，HumanEval 95.1%）、teichai（plan）、cybersecurity（security 新增）、base 原生 thinking（doc 路由，兼展示"无 adapter 也是一等公民"）。skill_map 里 fable5 全部清除。

## 5b. 🪑 fable5 空位（doc/研究位）候选终审（2026-07-29）

用户要求从白名单池里再补一个顶 fable5 的空位。按终审标准（模型卡 + config 全文 + 体积/转换墙）核了 3 个方向候选：

| 候选 | 领域 | 终审结论 |
|---|---|---|
| **lananhyeuem/qwen3.6-27b-multilingual-rag-lora-n7** | **证据 grounded 问答（RAG）** | ✅ **推荐**。base 精确匹配、Apache-2.0、非 gated、卡有实质内容（LlamaFactory 训练，k=3 检索证据 + N=7 `<priors>` 范例上答题）。**领域与"调查 Agent + 证据引用"叙事严丝合缝**。风险：① r128/α256、adapter ~1.8GB（全阵容最大，热切延迟须实测）② target_modules 含 DeltaNet 全套（out_proj/in_proj_qkv/z/a/b）→ 转换墙同 teichai 补丁路径 ③ 38 下载/0 赞，社区验证弱，行为测试必须做 |
| gr33r/ux-writing-1-lora | UX 文案审校 | 🟡 备胎。工程质量全场最佳（盲测 83% 胜率、有独立评测代码、q/k/v/o+MLP 零转换墙、159MB、Apache-2.0），但领域太窄（UI 字符串重写），与调查叙事不搭 |
| s-g-labs/linlu-lora-v0.4 | 微信风格人格扮演 | ❌ 不上台。模型卡教科书级（含 assert 自检、采样契约），但它是**角色扮演 persona LoRA**（时间戳气泡+表情包），放进 Private AI Agent 评审语境是跑题 |

同作者 n5 变体（in-context 深度 N=5）为降级备份。**若 n7 行为测试不过或 1.8GB 热切延迟不可接受 → 回退"base 原生 thinking 顶 doc 位"方案，不降级硬塞。**

## 5c. 🔁 jitna 四件套复审（2026-07-29，用户点名）

上次仅凭 router 一个空白模型卡整套否决——**复审推翻"不可信"判定，但维持"不上台"结论**，理由更换如下：

**它是什么**：Delentia AI（泰国曼谷）的 "Delentia OS / JITNA" 项目——**1+4 支柱架构：冻结基座 + 4 个角色 LoRA（Router 路由 / Executor 工具执行 / Guardian 安全审查 / Scribe 上下文压缩）在 VRAM 内热切（宣称平均 11.2ms）**。这与 ScrewShell 的 MoL 是同一架构思想的独立实现。v0.4 基于 Llama-3.1-8B，v0.5.1 刚移植到 Qwen3.6-27B（7/24 发布，比我们扫描早 4 天）。

**复审硬指标（以 executor 为例）**：
- ✅ base 精确 == `Qwen/Qwen3.6-27B`，非 gated，unsloth QLoRA，r32/α64
- ✅ target_modules 正则最终只落在 **q_proj/v_proj** → **零转换墙风险**（不碰 DeltaNet 模块）
- ✅ adapter 仅 ~68MB，热切负担极小；org 另发布配套 `jitna-v0.5.1-27B-gguf`
- ❌ 单 repo 模型卡仍空白（信息全在 org 主页），0 赞
- ❌ 宣传口径浮夸且不可复现："<0.3% 幻觉率"、六项指标全 100.00%、"ZK-FDIA 数学安全方程 F=D^I×A"——自证评测、无第三方复跑；且指标标注 v0.4.1（8B 版），27B 移植版效果未证
- ❌ **深度耦合自家 JITNA 协议**：executor 输出他们的 JSON/TOON schema、guardian 依赖他们的签名门控。脱离 Delentia OS 单独热切，行为大概率不是通用技能而是"说他们的方言"

**结论**：不上台（耦合协议 + 自证指标），但**升格为 PPT 的"相关工作"弹药**——"泰国团队 Delentia OS 与我们独立地在 Qwen3.6-27B 上实现了同一 frozen-base + 角色 LoRA 热切架构"，这是 MoL 路线正确性的第三方旁证，比自说自话有力得多。可选实验：guardian（r16、q/v only、几十 MB）作为 reviewer-pass 的候选试一把，成本极低，不进主线。

## 6. 流程结论（写进 PPT 的弹药）

- 全量 349 个 adapter 里**只有 ~17% 是技能级且基座可证干净**的——"树大"和"能用"差一个数量级，这正是自动核验闸的价值。
- dementor-research 的 39 个 BAD_CONFIG（base_model 字段非法）验证了上次的观察：研究批量产物会污染 model tree 统计。
- 本脚本已产品化：`scripts/verify_lora_whitelist.py`（支持 `HF_ENDPOINT` 镜像、Link 分页、五级判定），可作为 ScrewShell "专家准入 CI" 的第一道闸——**这把 hermes_s2 事故变成了工程成熟度故事**。
