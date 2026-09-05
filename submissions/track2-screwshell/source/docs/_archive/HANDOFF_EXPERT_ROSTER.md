> ⚠️ STALE：本文件已归档，唯一信源见 docs/TRUTH.md。
# HANDOFF: 专家阵容落地工单（给下一个 Agent）

> 生成时间：2026-07-29 · 上一阶段：LoRA 来源核实 + 官方树全量扫描 + 上台阵容终审（全部完成）
> 本文档是**唯一权威交接入口**。开工前先通读本文，再按 §6 工单顺序执行。
> 比赛截止：**2026-08-06**（AMD AI DevMaster Hackathon 2026, Track 2 — Private AI Agent Development & Local Deployment）

---

## 0. TL;DR（30 秒版）

1. 原三专家里 **hermes_s2 基座错配**（真基座是 samscrack/Opus-CoT-Stage1，不是干净 Qwen3.6-27B，静默错位）、**fable5 repo 已 404/私有化**（且本地从未下载成功）。两个都必须清出系统。
2. 用户已拍板新阵容（4 步骤 × 4 LoRA，见 §1），全部经上游 `adapter_config.json` 逐字段终审，base 精确 == `Qwen/Qwen3.6-27B`。
3. 剩余工作全是**本地实操**：下载转换 3 个新 LoRA → 行为验证 → 改 `router.py` → 清两套提交文档里的 hermes_s2/fable5。纸面核验已做完，不要重复。

---

## 1. 已拍板的最终阵容（用户确认，勿改动阵容本身）

| Pipeline 步骤 | skill_map 键 | LoRA repo | 关键参数 | 状态 |
|---|---|---|---|---|
| ① plan 规划 | `agent` | `TeichAI/Qwen3.6-27B-Fable-5-Experimental-LoRA`（本地名 teichai_fable5_plan） | r64 | ✅ 已转换 + 已 bench，不用动 |
| ② tool/code 执行 | `tool` + `code`（双路由指同一 adapter） | `badtheorylabs/BTL-3` | r32/α64，954MB safetensors | ⬜ 待下载 + 转 GGUF |
| ③ security 审计 | `security`（**新增键**） | `hotdogs/qwen3.6-27b-cybersecurity-lora` | r8/α16 | ⬜ 待下载 + 转 GGUF（最容易） |
| ④ doc 证据报告 | `doc` | `lananhyeuem/qwen3.6-27b-multilingual-rag-lora-n7` | r128/α256，~1.8GB | ⬜ 待下载 + 转 GGUF + 行为测试 |
| fallback | `base` | 无 adapter（基座原生 thinking） | — | ✅ 一直可用 |

**回退预案（用户已同意）**：若 n7 行为测试不过、或 1.8GB 热切延迟不可接受 → `doc` 位回退为 `None`（base 原生 thinking），不硬塞降级品。备胎序列：同作者 n5 → gr33r/ux-writing-1-lora（159MB 零转换墙但领域窄）。

**必须清除**：`hermes_s2`（基座错配）、`fable5`（repo 404 + 从未下载成功）。这两个名字在代码、测试、文档中出现的每一处都要处理。

---

## 2. 为什么是这四个（证据索引，不要重查）

核验证据已沉淀在以下文档，按需查阅、**不要重新做网络核验**：

- `screwshell/docs/LORA_SOURCE_VERIFICATION.md` — hermes_s2 错配全链路证据（真基座 Opus-CoT-Stage1、模型卡原话"Useless without the right base"）。
- `screwshell/docs/OFFICIAL_TREE_WHITELIST.md` — 官方树 335 adapter 全量扫描报告；§5 上台终审、§5b fable5 空位补选、§5c jitna 复审。
- `docs/lora_whitelist_scan.csv` — 349 条原始判定（PASS 238 / 技能级独立 PASS ≈61）。
- `screwshell/docs/COMPETITION_STRATEGY.md` — 比赛规则速读 + macaron 对标定位 + 倒计时表。
- `scripts/verify_lora_whitelist.py` — 可复用准入 CI 脚本（新专家进池必须先过它）。

核心铁律（本项目血泪史，两次踩坑换来的）：
1. `adapter_config.json` 的 `base_model_name_or_path` 必须**精确** == `Qwen/Qwen3.6-27B`，逐个上游核实，不信任何二手文档（hermes_s2 教训）。
2. "能加载、能出 token" ≠ "挂对了"。同架构不同权重会**静默错位**；PEFT 宽松路径会**静默挂空**。行为验证不可省（见 §5 验收闸 G3）。
3. 拿得到货是第 0 条——下载成功、转换成功才算数（fable5 教训：文档写着"drop-in GGUF"，实际 repo 从未可达）。

---

## 3. 本机环境坑（已验证，直接照做，别重新趟）

- **HF 直连超时**（WinError 10060）。一切 HF 访问必须走镜像：`HF_ENDPOINT=https://hf-mirror.com`。下载用 `huggingface-cli download` 或 `hf_hub_download` 时同样带这个环境变量。
- HF API 列 adapter 用 `filter=base_model:adapter:X`（**`other=` 参数会被静默忽略**，返回 trending 列表——假数据）。
- 镜像返回的分页 Link header 指回 huggingface.co，需重写 host 才能翻页。以上三个坑 `scripts/verify_lora_whitelist.py` 已内置修复，可参考其实现。
- Python 用托管版：`C:\Users\djb\.workbuddy\binaries\python\versions\3.13.12\python.exe`。
- 转换墙：llama.cpp 的 LoRA→GGUF 转换对 Qwen3.6 DeltaNet 模块有已知问题（issue #21125），**teichai 已用补丁路径成功转出 992-tensor GGUF**——BTL-3 和 n7 的 target_modules 与 teichai 同族（unsloth 正则 + DeltaNet 全套），走同一条补丁路径。补丁细节见 `screwshell/docs/PATH_D_IMPLEMENTATION.md`。
- cybersecurity-lora 的 target_modules 只有 q/k/v/o + gate/up/down（无 DeltaNet 模块）→ **零转换墙风险**，建议先转它建立信心。

---

## 4. BTL-3 专属注意事项

- repo **没有现成 GGUF**，只有 `adapter_model.safetensors`（954MB），必须本地转换。
- 模型卡**钉死了基座 revision `6a9e13bd…`** 并附 SHA-256 → 开工第一步就核对本地基座权重是否同一 revision（见 G2）。不一致时优先换本地基座到该 revision，而不是无视。
- **必须用非 thinking 模式**调用（模型卡自曝 thinking 模式会复读/不停机）。
- chat_template 自带 `<function=...>` 工具调用格式，demo prompt 与 orchestrator 的工具协议要配合它（写 demo 脚本时注意）。

---

## 5. 验收闸（每个新专家必须全过，一个不过就不上台）

- **G1 转换闸**：safetensors → GGUF 转换成功，tensor 数与预期一致（对照 teichai 的 992-tensor 经验值按 r 值折算）。
- **G2 基座 revision 闸**：本地基座 GGUF 的源 revision == BTL-3 钉死的 `6a9e13bd…`（至少 BTL-3 要求；其余专家同基座顺带受益）。
- **G3 行为闸（防静默挂空/错位）**：同一 prompt 分别在 base 与 base+adapter 下推理，输出必须**可观测地不同且方向符合该专家领域**（例：cybersec 挂上后对日志片段的分析明显更专业）。参考 s-g-labs 模型卡的 "assert LoRA modules active" 思路。每个专家至少 3 条领域 prompt。
- **G4 热切延迟闸**：实测每个 adapter 的热切时间并记入 bench（尤其 n7 的 1.8GB——超过可接受阈值就触发回退预案）。
- **G5 回归闸**：`tests/test_mol_llamacpp.py` 更新后全绿；bench 重跑数据写回 `bench/`。

**注意**：`bench/benchmark_pathd.json` 里 hermes_s2 的 behavior 数据是在错配基座上测得的，**无效数据**，更新 bench 时一并清理/标注。

---

## 6. 工单（按序执行）

### T1 转换与验证（先易后难）
1. 下载 + 转换 `cybersecurity-lora`（零转换墙，建立流程信心）→ 过 G1/G3。
2. 核对基座 revision（G2）→ 下载 + 转换 `BTL-3` → 过 G1/G3/G4。
3. 下载 + 转换 `rag-lora-n7` → 过 G1/G3/G4；不过则执行回退预案（doc → None）。

### T2 改代码（`screwshell/screwshell/core/router.py`）
1. `DEFAULT_SKILL_MAP` 改为：
   ```python
   DEFAULT_SKILL_MAP = {
       "tool": "btl3",
       "code": "btl3",          # BTL-3 兼任（agentic-coding 出身，HumanEval 95.1%）
       "agent": "teichai_fable5_plan",
       "security": "cybersec",   # 新增
       "doc": "rag_n7",          # 回退时改 None
       "base": None,
   }
   ```
   （adapter 本地命名与 engine 注册名保持一致，对齐 `mol_engine_llamacpp.py` 的加载配置。）
2. 头部注释块整体重写：删掉 hermes_s2/fable5 的描述，写明四专家真实来源 + "base 均已上游核验精确匹配"。
3. 新增 `SECURITY_KW` 正则（如 `audit|vulnerab|CVE|exploit|permission|leak|malicious|security`）并插入 route() 优先级；**注意与 CODE_KW/PLAN_KW 的关键词重叠**（现有 plan vs analyze 已有重叠），改完跑 `scripts/day2_router_demo.py` 验证路由不串。
4. `mol_engine_llamacpp.py` / `orchestrator.py` 中 adapter 注册、server_args 里的 hermes_s2/fable5 引用同步更换。
5. `tests/test_mol_llamacpp.py` 中 fable5/hermes_s2 引用同步更新。

### T3 清文档（⚠️ 有两套，都要改）
- **两套目录都存在** SPEC.md / PPT_OUTLINE.md / VIDEO_SCRIPT.md / SUBMISSION_CHECKLIST.md：`docs/`（仓库根 docs，已被归档）和 `screwshell/docs/`（规范来源）。**已确认 s creewshell/docs/ 为单一权威**，无需再做 diff，其余文档均指向 `screwshell/docs/`。
- 具体清理点：
  - SPEC.md §2/§4/§5：基座表 hermes_s2 "converted ✓" 行、"hermes_s2 adds tool-selection reasoning" 表述 → 换成 BTL-3 + 新阵容。
  - PPT_OUTLINE.md Slide 5 专家列表 → 新四人组；新增两页素材见 §7。
  - VIDEO_SCRIPT.md Shot 1 "expert badge switching teichai → hermes_s2" → 改为新专家切换镜头。
  - README.md / PATH_D_HANDOFF.md / PATH_D_IMPLEMENTATION.md 里 "fable5 repo 附带 GGUF drop-in" 的说法已失效，标注或修正。
  - SUBMISSION_CHECKLIST.md 增加一条："所有上台 LoRA 均通过 G1–G5 验收闸"。

### T4 bench 与 demo
- 重跑 bench（新阵容），清理/标注 hermes_s2 的无效旧数据。
- demo 流程按 pipeline 四步走：plan(teichai) → tool(BTL-3) → security(cybersec) → doc(n7 或 base)。
- 可选加分项（用户未最终拍板，时间富余再做）：reviewer pass——doc 产出后切回 security 专家 critique 一轮，多一次热切+推理，"专家互相检查"画面感强。

---

## 7. PPT 弹药（已确认的叙事点，写材料时直接用）

1. **"MoL = Multi-Agent on a Single GPU"**（单独一页）：经典多 Agent 空间并行 3×17GB≈51GB 超出单卡；ScrewShell 把协作折叠到时间轴——冻结基座 17GB 常驻 + ≤2GB adapter 热切，四步顺序交接即消息传递。
2. **专家准入 CI**：335 adapter 全量扫描 → 238 PASS → 61 技能级 → 4 上台。"数量不是卖点，'任何合规 LoRA 十分钟内可成为新专家'的流水线才是卖点"。附 hermes_s2 反面案例（提交前自查揪出静默错配）。
3. **相关工作旁证**：Delentia OS/JITNA（曼谷团队）独立在 Qwen3.6-27B 上实现了同构架构（frozen base + 4 角色 LoRA 热切）——证明 MoL 是被多方独立验证的路线；差异化：他们靠自证指标，我们靠准入 CI + 证据引用 + 可复现 bench。
4. **macaron（Mind Lab A2UI）对标**：干净发布 LoRA 的范本（base 写死、MIT、独立 adapter）；话术见 COMPETITION_STRATEGY.md §3。注意 macaron 基于 **Qwen3-30B-A3B（Qwen3，非 3.6）**，别写错。
5. 克制叙事："不是不能挂 10 个 LoRA，是 pipeline 只有 4 个真实步骤"——角色数 3–4 是社区独立收敛的甜点位（Delentia 也是 4）。

---

## 8. 禁区（前几轮已否决，不要复活）

- ❌ hermes_s2 挂干净基座（静默错位）；❌ 整机换基座到 Opus-CoT-Stage1 / huihui abliterated / Heretic（赔掉 teichai + 无审查基座评审风险 + 工期自杀）。
- ❌ 跨代 LoRA（Qwen3 → 3.6 物理不兼容，社区"能用"是静默挂空假阳性）。
- ❌ unsloth 镜像树 14 个 adapter 直接用（须先权重 checksum 比对，未做）。
- ❌ jitna 四件套上台（协议方言 + 自证指标）；❌ opencode-lora / baddie5419（空白卡）；❌ linlu v0.4（微信 persona 跑题）；❌ kai-os Opus4.6-reasoning（OOM 半成品）。
