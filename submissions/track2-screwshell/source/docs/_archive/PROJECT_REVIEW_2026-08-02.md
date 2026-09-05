> ⚠️ **ARCHIVED（2026-08-02）** — 本文件已移至 `docs/_archive/`，不再是在役文档。其结论已并入 **`docs/TRUTH.md`（唯一信源，SSOT）**；本文件仅作历史参考，**不再作为真相依据**。技术事实一律以 `docs/TRUTH.md` 为准。

# ScrewShell 项目评审与行动 —— 从「项目文档定义的需求&目标」出发（修订版 v2，2026-08-02 合并 SUMMARY）

> 评审日期：2026-08-02
> 评审视角：以**本项目文档中明确写出的需求&目标**为尺，拔高到产品 / 流程 / 参赛达标层面，不陷行级 bug。
> 修订说明：初版误把「djb 个人的 AI PM 转型目标」当唯一尺子，套出一套创业式 PRD 评审框架，与本项目真实需求不符。本版撤回错配的 3 条 P1，改用文档里的两层真实需求&目标重审，主体改为「8/6 提交达标风险清单」。
> **2026-08-02 合并说明**：原 `PROJECT_SUMMARY.md`（散落文档整合）的内容已并入本文 §7–§9，该文件改为 2 行重定向存根。**本文现为唯一「评审与行动」文档**；技术事实一律以 `docs/TRUTH.md`（SSOT）为准，本文不重复持有。

---

## 0. 一句话结论

工程底座扎实、差异化清晰，但**对黑客松 Track 2 的「达标风险」集中在「叙事可信度」和「头号卖点是否真生效」两处**，而不是「缺 PM 文档 / 不能 clone-and-run」这类初版误判的点。最该在 8/6 前排掉的是：① 0.65ms 这个数字经不起懂行评委追问；② 「证据型答案」这块招牌目前代码层面其实**没有行级引用**（死代码 + 错误吞没链）。信源(TRUTH)自身漂移的老坑已于 2026-08-02 20:15 回写 TRUTH v7 闭环（见 §3 已闭环项）。

---

## 1. 评审尺 = 项目文档里写明的需求&目标（两层）

**Layer A —— 参赛需求（Track 2: Private AI Agent Development & Local Deployment）**
- 交付物（docs/_archive/SUBMISSION_CHECKLIST.md）：① 英文 SPEC ② 源码 + README（5 章）③ 3–5 分钟视频**必须露 `rocm-smi`** ④ ≤10 页 PPT。
- 评委打分锚点（docs/_archive/COMPETITION_STRATEGY.md §1 / docs/E2E_OPTIMIZATION.md §1.1）：
  真·本地 / 隐私 · 真·跑在 Radeon/ROCm · agent 五能力（RAG / 工具 / 规划 / 记忆 / 权限）· 一个创新点 · 真实硬件 demo 可复现。
- 创新点不是「切换省」一个点，而是 **「在单张 AMD 上优化整个本地 agent 栈」**（MoL 热换装 + 本地小模型独有优化 B1–B7）。
- 头号卖点 = **证据型答案（带行级引用）**，必须真生效（docs/E2E_OPTIMIZATION.md §8 P0 / §3.1 B4）。

**Layer B —— 作品集需求（djb 转型目标，范围需钉对）**
- 双交付 = 「代码项目 + PM 方法论包」。但此处的 PM 包是 **E2E 双链框架 / 工具编队 squad / 「把验证做进流程而非靠记性」**（FRONTEND_TOOL_E2E_STRATEGY §0/§6）——这些文档里**已经有了**，不是缺口。

---

## 2. 初版错在哪（已撤 / 已重定性）

| 初版条目 | 处理 | 为什么错 |
|---|---|---|
| P1-1「PM 方案包缺失（无 PRD/JTBD/画像/GTM）」 | **撤** | 错配的尺。正确的「PM 方法论包」（双链/squad/验证进流程）文档里已存在；我硬塞了创业 PRD。 |
| P1-2「只有工程指标，无产品指标」 | **撤** | 项目有 G1–G5 验收闸 + benchmark + E2E 框架明确要求的「端到端 4 步调查数字 / 质量+效率 A/B / 引用准确率」。 |
| P1-3「不可开箱即用 / 不能 clone-and-run」 | **撤** | 黑客松要的是视频演示露 rocm-smi，**根本不要求 clone-and-run**；这是我个人偏好漏进去了。 |
| P0-1「信源失准」 | **保留，重定性** | 不改事实，但定性从「产品诚信问题」改为「文档-代码失同步的流程老坑」（见 §3 已闭环项）。 |
| P0-2「多步规划虚标」 | **保留，重定性** | 不是诚信红线，而是「提交达标风险 + 已知数据缺口」——评委核对 config 或复跑会发现规划无专属专家（见 §3-P1-能力缺口）。 |

---

## 3. 达标风险清单（评审主体，按对 8/6 提交的威胁度排序）

### 🔴 P0-卖点：「证据型答案」目前代码层面没有行级引用（最该先排，待排代码期）
- `orchestrator` 最终答案的 `EvidenceCard` 里 `citations=[]` 是**死代码**（docs/E2E_OPTIMIZATION.md §2.1「findings 引用裂缝」；§8 标为 **当前最大裂缝 / P0**）。
- 叠加 **A2 错误吞没链**：`chat()` 失败返回 `("", GenStats(0,0))`，orchestrator 走 `_extract_json`→None→浪费一次 action，且 `step failed` 不上浮给用户——一条 query 可全程静默失败却产出「看似完整」的答案（docs/E2E_OPTIMIZATION.md §2.1）。
- **后果**：头号差异化「证据型答案（带行级引用）」在代码里实际不成立，行级引用几乎全压在一次 LLM 自觉上。27B Q4 会编造 `file#Lx-Ly`。
- **修复方向（文档已有方案）**：程序化引用校验器（B4），校验引用文件/行号真实存在、片段确实被检索过；并修 A2 让失败上浮 + 留痕。这是 docs/E2E_OPTIMIZATION.md §8 的 P0、§3.1 的 B4，已是既定方向，只是没落地。
- **排期状态（代码债⑤）**：此即用户标注的「代码债⑤」。文档层无法修复，须改 `orchestrator` + `chat()`，**单独排入代码期**，不在此轮文档清理内实现。

### 🔴 P0-叙事：0.65ms 这个数字经不起懂行评委追问
- README §5 / TRUTH §1.5 的 `avg 0.65 ms` 测的是 `POST /lora-adapters` 的**控制面 scale toggle**，是近乎 no-op 的 HTTP 调用，不是真实切换成本（docs/E2E_OPTIMIZATION.md §1.2）。
- llama.cpp 的 LoRA 是**逐 token 附加 matmul**：切换本身免费，但「adapter 激活态」对**每个生成 token** 持续征 15–25% decode 税（已观测 31→23.4–26 tok/s）。
- **叙事风险**：懂 llama.cpp 的评委一句「你测的 0.65ms 到底是什么」就问倒，立论 credibility 直接塌。
- **重构方向（文档已给）**：换成「切换控制面成本 ≈ 0；真实成本是 adapter 激活态每 token 15–25% decode 税；用 per-request 路由只在需要的步骤支付」。把「可被挑战的数字」换成「可防守的数字」，并自然引出调度优化故事。

### 🟠 P1-叙事：§5 单维叙事没打到 Track 2 打分锚点
- 当前优化故事全压在推理核心（VRAM / 切换 / 吞吐），上面 5 层（Planner / Router / RAG / Tools / Memory / Safety）在「优化叙事」上**零贡献**（docs/E2E_OPTIMIZATION.md §1.1）。
- 对 Track 2，单点推理优化读起来是「我切换模型很省」，而不是「我在 AMD 上优化了整个本地 agent 栈」——后者才是赛道打分锚点。
- **升级方向**：① 扩成「Agent Stack Optimization on Radeon」（推理核心 MoL + RAG GPU 嵌入 batch + 编排路由缓存/换装调度 + 内存 SQLite 本地 IO）；② 补一次真实 27B 栈 4 步调查 e2e 数字（总耗时/峰值 VRAM/有效吞吐/答案质量分），替代纯组件级 microbenchmark；③ 加 MoL vs 单基座 A/B（同任务准确率/延迟/VRAM 三维）。

### 🟠 P1-地雷：KV 失效 re-prefill 从未实测（热切真实成本存疑）
- llama.cpp slot KV 复用依赖「前缀权重一致」。roomy 模式每步 per-request 切换 lora，切换后已缓存的共享前缀 KV 是否仍有效**从未实测**（docs/E2E_OPTIMIZATION.md §4）。
- 若失效，每次换帽子都强制全量 re-prefill——这才是热切的**真实**成本，而非 0.65ms 控制面 toggle。
- **建议**：一次针对性实测（固定前缀 + 变 lora 请求，对比命中/失效 prefill 耗时）；结果本身即是优化故事素材，且决定 §1.2 叙事怎么写。

### 🟡 P2-机会：Mixture 多专家 scale 组合 = 本地相对云端唯一结构性优势，但没用
- llama.cpp 的 per-request `lora` 数组 + scale 组合，云端 API 给不了（你没法在 OpenAI 上按请求混合多个 adapter 权重比例）（docs/E2E_OPTIMIZATION.md §3.2）。
- 当前 router 正则硬选一个、scale 恒 1.0，**Mixture 那一半没被使用**。前提是数据：须用 G3 式混合行为实测证明「混合真比单专家好」，否则是噱头（评委一句「你的 mixture 有数据吗」就问倒）。文档已将其排除进 PPT future work，属「待决 / 可选赌」。

### ✅ 已闭环：信源(TRUTH)漂移 + README/AGENT 同步（2026-08-02 20:15）
- 原 P0「TRUTH 自身漂 / README §4 待转化 T1 / AGENT 端口 31033」三项，已于 2026-08-02 20:15 回写 **TRUTH v7** 并修 AGENT/README/SPEC/AUTOTUNE 闭环：
  - `TRUTH.md` §2 `teichai_plan` 改「✗ 无权重，降级 base」；§8.3 加 v7 + 纪律「部署/运行现实一旦变化必须回写本表」。
  - `AGENT.md` §5 端口 31033→31010。
  - `README.md` §4 LoRA 状态去「待转化 T1」、架构图补 L3 治理、Repository Layout 补 `autotune/`；`SPEC.md` / `AUTOTUNE.md` 同步。
- 详见 `docs/TRUTH.md` §8.3 v7。本项不再作为开放风险。**教训**：建 SSOT 不够，必须有「现实变化→回写信源」的强制闸（已写入 TRUTH 纪律），否则信源自身也会漂。

### 🟠 P1-能力缺口：多步规划无专属专家，但文档标 5/5（提交达标风险）
- 「多步规划」三大文档标 5/5 核心能力，现实是规划专家无权重、降级裸基座。属已知数据缺口（RUNBOOK §3「data gap, not a bug」），但对外仍写「5/5」会在评委核对 config / 复跑时露馅。
- docs/_archive/SUBMISSION_CHECKLIST.md §2 要求 4 个 on-stage 专家全过 G1–G5；teichai 无权重 → 过不了 G1（无 tensor 可 match）→ 「multi-step planning」不能声称有专属专家。
- **处置（二选一，非诚信问题）**：要么补 teichai 权重真把规划做出来；要么文档里把「5/5 多步规划」改为「规划由基座原生 thinking 提供（专家权重待补）」，并与 TRUTH §2 漂移一并回写。

---

## 4. 亮点（保留，且贴合 Track 2 打分点）

1. **价值主张清晰**：隐私优先的本地调查员，痛点真实（敏感材料不能上云）——直接命中 Track 2 主题。
2. **真差异化 + 有数据**：MoL 单卡多专家，VRAM 50→18.9GB、切换 0.65ms（控制面）、decode 23.4–26 tok/s——故事骨架在。
3. **证据型答案（设计意图）**：行级引用 + JSON 审计，信任/可审计角度强——**只是代码尚未落地（见 §3-P0-卖点）**。
4. **autotune 三层系统真实落地**：L1/L2/L3 + W7900 真机双档换装验证（4.6–5.1s/次，4 专家最坏 19.4s），四维评分 + 降级铁律 + 指纹防护——工程深度信号，且是「本地部署规划」的原始素材。
5. **防御性测试意识**：forbidden 专家回归、per-query 换装计数、VRAM 真实百分比——成熟度信号。
6. **RUNBOOK 可复现**：部署固化进仓库（符合「部署依赖必须进仓库」）。
7. **本地小模型独有优化清单 B1–B7**（docs/E2E_OPTIMIZATION.md §3.3）：GBNF 约束解码 / 引用校验 / 调用预算 / prefill 瘦身 / Mixture / thinking 预算 / 证据卡记忆——这是「本地部署优化」赛道该讲的**原创方法论**，目前多未落地，但思路已是差异化资产。

---

## 5. 行动建议（按 8/6 截止，杠杆排序）

**A. 守信源纪律（已完成，2026-08-02 20:15）** —— 回写 TRUTH v7 + 修 AGENT/README/SPEC/AUTOTUNE，详见 §3「已闭环」项；新增 TRUTH §8.3 纪律「现实变化须回写 TRUTH」。

**B. 修头号风险：让「证据型答案」真生效（P0-卖点，最高杠杆，待排代码期）**
- 落地引用校验器（B4）+ 修 A2 错误吞没链（失败上浮 + 留痕）。这是头号卖点的生死线，也是评委最可能深挖的点。

**C. 重构 0.65ms 叙事（P0-叙事）**
- README §5 / TRUTH §1.5 改为「decode 税 + 按步付费」模型，保留 VRAM(18.9GB)/9s 实打实数字，撤掉可被挑战的控制面 0.65ms 主叙事（可保留为脚注）。

**D. 补端到端证据（P1-叙事）**
- 一次真实 27B 栈 4 步调查 e2e 数字（总耗时/峰值 VRAM/有效吞吐/答案质量分）+ MoL vs 单基座 A/B；优先做 KV 失效 re-prefill 实测（决定 C 叙事怎么写）。

**E. 演示资产（8/5 前）**
- 录 3–5 分钟视频（**两处露 rocm-smi**，Shot 2 & 5）+ ≤10 页 PPT（money slide = benchmark，加一页「本地小模型独有优化 B1–B7 vs 云端」对标）。

---

## 6. 下一步

别再补「PM 文档」。先做 **B（让证据型答案真生效，代码期）+ C（重构 0.65ms 叙事）+ D（补 e2e 证据）**——这三步直接命中 Track 2 打分锚点与头号卖点生死线，且都已在文档里被定义为既定方向，成本可控、杠杆最高。要不要我起草引用校验器(B4)+A2 修复的落地方案？你拍板我就干。

---

## 7. 文档地图（谁说了算 / 谁已失效）—— 合并自原 PROJECT_SUMMARY §2

| 文档 | 角色 | 状态 | 说明 |
|---|---|---|---|
| `docs/TRUTH.md` | **唯一信源（SSOT）** | ✅ 权威 | 项目目的/技术事实/参赛状态。变更须走 §8.3 变更日志。 |
| `AGENT.md`（根） | 轻量索引 | ✅ 权威 | 指向 TRUTH；§5 端口 31010（2026-08-02 改正）。 |
| `README.md`（根） | 对外门面 | ✅ 在役 | 5 章齐全；架构图/能力表/阵容表已抽离、改指向 TRUTH（避免重复），保留运行命令。 |
| `docs/SPEC.md` | 交付物① | ✅ 在役 | 英文技术规格；提交前从 TRUTH 反向同步。 |
| `docs/AUTOTUNE.md` | autotune 子系统 | ✅ 权威（从属 TRUTH §1.6） | L1/L2/L3 + W7900 真机验证。 |
| `docs/E2E_OPTIMIZATION.md` | 优化**叙事+行动**（合并版） | ✅ 在役 | 由 FRAMEWORK+REVIEW 合并（2026-08-02）；§1–§6 框架叙事，§7–§11 编排行动。 |
| `docs/FRONTEND_TOOL_E2E_STRATEGY.md` | 作品集**方法论** | ✅ 在役 | E2E 双链、工具编队、验证进流程。 |
| `docs/PROJECT_REVIEW_2026-08-02.md` | **本文（唯一评审与行动）** | ✅ 最新 | 以两层真实需求为尺；主体是 8/6 达标风险清单（§3）。 |
| `HOW_TO_OPEN.md`（根） | 怎么打开界面 | ✅ 最新（8/2） | 端口 31010、3/4 专家、SSH 隧道。 |
| `deploy/w7900/RUNBOOK.md` | 部署手册 | ✅ 最新（8/2） | 从编译到确定性验证的全链路。 |
| `bench/BENCHMARK_STATUS.md` · `bench/LORA_GGUF_GATES.md` | 实测数据 | ✅ 权威数据 | VRAM/switch/tok-s；G1–G5 闸（注意：`LORA_GGUF_GATES.md` 中 teichai 行已更正为「无权重」）。 |
| `docs/_archive/*`（18 份 md） | **已归档 STALE** | ❌ 失效 | 物理保留、可逆，**不再作为信源**。 |
| `backups/instance_backup/*` | 实例备份快照 | ⚠️ 历史 | PATH_D_HANDOFF 等，仅供溯源。 |

> **整理结论**：在役文档已按「信源(TRUTH) / 交付物(SPEC+README) / 部署(RUNBOOK) / 优化叙事(E2E_OPTIMIZATION) / 方法论(FRONTEND) / 评审(本文)」分好工；2026-08-02 的 TRUTH 漂移 + README 同步老坑已闭环（§3）。新人只读上表 ✅ 行 + TRUTH。

---

## 8. 已知坑速查（部署/运行）—— 合并自原 PROJECT_SUMMARY §7

- `Permission denied (publickey)` → 本地 pubkey 未进服务器白名单。
- 启动失败/路径缺失 → 旧文档写 `/persistent/...`（失效）；真实根是 `/workspace/persistent/screwshell_run`。
- `NotImplementedError` in convert → Qwen3.6 合并 QKV + 未合并 PR #24627 → 需 `deploy/w7900/patch_lora_converter.py`。
- 只挂上最后 1 个 adapter → 重复 `--lora` 已弃用，必须单个逗号分隔值 `--lora a.gguf,b.gguf,c.gguf`。
- adapter 命名 `GGUF` 永不激活 → `.gguf` 须放 `loras/<逻辑名>/adapter.gguf`（父目录名即 key）。
- 输出有/无 LoRA 无差异 → adapter 惰性；须 seed=42/temp=0 确定性 A/B 验证；测完把 scale 归零（残留 1.0 污染全局）。
- 规划类问题跑 base → `teichai_plan` 无权重，非 bug，是数据缺口。

---

## 9. 给新读者的最短路径

1. 先读 `README.md`（门面）+ **本文**（唯一评审与行动文档）。
2. 要技术事实 → `docs/TRUTH.md`（信源）。
3. 要交材料 → `docs/SPEC.md` + `README` + 录视频 + PPT。
4. 要复现 → `HOW_TO_OPEN.md` + `deploy/w7900/RUNBOOK.md`。
5. 要优化叙事/卖点 → `docs/E2E_OPTIMIZATION.md`（由 FRAMEWORK+REVIEW 合并）。
6. 要作品集方法论 → `docs/FRONTEND_TOOL_E2E_STRATEGY.md`。
7. 要风险与下一步 → 本文 §3。
8. **不要**读 `docs/_archive/*`（STALE）。
