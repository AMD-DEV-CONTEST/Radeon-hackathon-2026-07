# docs/E2E_OPTIMIZATION_FRAMEWORK.md

> **从属 `docs/TRUTH.md`（唯一信源）**。本文沉淀 2026 年一次独立对话的**框架层 / 叙事层 / 双视角**结论：对话起于 `D:\ai\screwshell-v2`（TRUTH v1 快照），结论在 `D:\git\screwshell`（TRUTH v6）经代码复核后做了校准。本文与 `docs/E2E_OPTIMIZATION_REVIEW.md`（编排层行动清单）**正交互补**——后者给"做什么"，本文给"为什么 + 叙事风险 + 双视角判断"。代码冲突时以 `screwshell/` 为准。

---

## 0. 与既有文档的关系

| 文档 | 视角 | 内容 |
|---|---|---|
| `E2E_OPTIMIZATION_REVIEW.md` | 编排层行动 | 引用验证器(P0) / GBNF(P1) / prefill 瘦身(P1) / 调用预算(P2) / 证据前置(P2) |
| **本文** | 框架叙事 + 双视角 | 优化叙事是否亮眼、A/B 独立判断、0.65ms 叙事风险、Mixture 待决、KV 缓存地雷 |

**已被 v6 推翻的早期判断**（勿再引用）：e2e 从未跑通 → 已真机 EXIT=0；默认 backend=peft(9B) → 已接 autotune；双激活路径是 bug → 现为 roomy(热切)/tight(重启) 刻意双档。校准细节见 §6。

---

## 1. 框架层结论：优化叙事是否贫瘠 / 不够亮眼

### 1.1 现状诊断
当前 README §5 / TRUTH §1.5 的"AMD Radeon 优化"故事是**单维度**的——证据全部集中在推理核心（6 层架构的最底层）：VRAM / 切换延迟 / decode 吞吐。上面 5 层（Planner / Router / RAG / Tools / Memory / Safety）在"优化叙事"上**零贡献**。

对 Track 2（Private AI Agent Development & Local Deployment），单点推理优化读起来是"**我切换模型很省**"，而不是"**我在 AMD 上优化了整个本地 agent 栈**"——后者才是赛道的打分锚点。

### 1.2 最脆弱的一行：0.65ms 热切
§5 表格的表头数字 `avg 0.65 ms` 测的是 `POST /lora-adapters` 的**控制面 scale toggle**（G4 闸与 README 自注都写明）。它衡量的是一次近乎 no-op 的 HTTP 调用，**不是真实切换成本**。llama.cpp 的 LoRA 是**逐 token 的附加 matmul**：切换本身免费，但"adapter 激活态"对**每一个生成 token** 持续征收未合并 LoRA 的运行时税（已观测 decode 31→23.4-26 tok/s，即 15-25% 降速）。

**叙事风险**：一个懂 llama.cpp 的评审会问"你测的 0.65ms 到底是什么？"——这个数字是脆弱的。

**重构方向（不是删，是换一套更诚实也更亮眼的叙事）**：
> 切换的控制面成本 ≈ 0（无需重载、无需重 prefill 设计）；真实成本是 **adapter 激活态每 token 15-25% 的 decode 税**；我们用 per-request 路由，让它**只在需要的步骤支付**。

这把"可被挑战的数字"换成"可防守的数字"，并自然引出"为什么不是所有步骤都挂 adapter"的调度优化故事。

### 1.3 三个升级方向（按叙事价值）
1. **全栈优化叙事**：把 §5 从"Inference Optimization"扩成"Agent Stack Optimization on Radeon"——推理核心(MoL) + RAG(GPU 嵌入 batch) + 编排(路由缓存/换装调度) + 内存(SQLite 本地 IO)。
2. **场景级基准**：补一次完整 4 步调查的端到端数字（总耗时 / 峰值 VRAM / 有效吞吐 / 答案质量分），替代纯组件级 microbenchmark。这是把"组件规格表"升级为"系统优化报告"的最快路径，也是 demo 视频里最易展示的镜头（rocm-smi 全程 21GB）。
3. **质量 + 效率双优化**：加 MoL vs 单基座的 A/B（同任务准确率/延迟/VRAM 三维对比），证明"热切换来专业能力，只付小代价"。

### 1.4 当前最该补的叙事证据
一次真实 27B 栈的 4 步调查 e2e 数字（§2/§3 的 4-12 分钟均为估算，缺真机分解）。**没有它，所有优化方向的优先级之争无法裁决**（见 §4 地雷）。

---

## 2. 视角 A：工程框架优化方向（独立判断，v6 校准）

### 2.1 v6 校准后的硬伤 / 工程债（仍成立）
| 项 | 状态 | 说明 |
|---|---|---|
| **A2 错误吞没链** | 仍成立 | `chat()` 失败返回 `("", GenStats(0,0))`，orchestrator 走 `_extract_json`→None→浪费一次 action；`step failed` 不上浮给用户。一条 query 可全程静默失败却产出"看似完整"的答案——直接威胁"证据型答案"卖点 |
| **findings 引用裂缝** | 仍成立 | orchestrator L429-430：`EvidenceCard(claim=trace.finding, citations=[], confidence=0.75)`——死代码式空引用。最终答案的行级引用几乎全压在一次 LLM 自觉上 |
| **prefill 隐性大头** | 仍成立 | 每次 ReAct 调用（L398）重发 `json.dumps(toolkit.spec(), indent=1)` 全量工具规格 + 3×1800 字符 observations；无 token 预算；8192 ctx 下长调查必撑爆且无降级 |
| **e2e 可观测性缺失** | 仍成立 | `RunResult.stats` 缺每次 LLM 调用的 prompt_tokens / prefill / decode 分解——而这正是优化 95% 瓶颈所需数据 |
| 双重激活路径 | **已非 bug** | v6 为 roomy(`engine.activate` POST) / tight(重启) 刻意双档；tight 模式显式置 `active_adapter=None` 防止 chat 注入过期 per-request lora。残留问题是**叙事未同步**（§1.2） |

### 2.2 架构机会
- **证据前置 RAG preflight**：RAG 检索不依赖 LLM（embedding 是 GPU 毫秒级），应在 plan 前无条件跑一次，直接喂 planner——同时解决"RAG 与编排割裂"和"少调 LLM"。
- **调用预算制**：`max_actions=5` 是云端习惯移植；本地每次 action 是 30-45s 的 LLM 调用，应降到 1-2 且 planner 直接产出首工具调用。
- **固定前缀 KV 复用**：system + 精简工具规格放最前，变动 observations 放最后。

### 2.3 对 README §5 / TRUTH §1.5 的含义
§5 表的 `0.65ms` 一行必须重构（见 §1.2），并补"KV 失效 re-prefill 真实成本"实测（见 §4）。其余 VRAM(18.9GB)/9s 加载数字是实打实的，可保留。

---

## 3. 视角 B：本地小模型特性（独立视角，v6 校准）

### 3.1 "慢 / 笨 / 窗小"逼出的云端不需要的独占优化点
- **慢**（decode 26-31 tok/s，prefill ~100 tok/s）：
  - **B1 Prefill 经济学**——本地第一约束。云端 prefill 又快又便宜，prompt 长度无人关心；本地 ~100 tok/s 下 prompt 瘦身是**性能优化而非卫生问题**（工具 spec 按 step 裁剪、observations 压缩、固定前缀 KV 复用）。云端 agent 框架（LangChain 等）无此对应物——这是"本地部署优化"赛道该讲的原创故事。
  - **B2 调用预算制**——云端可聊天式 ReAct（token 快，5 次往返无感）；本地每次 30-45s，"max 5 actions/step" 是直接移植错误约束。本地必须：planner 一次产出步骤+首工具调用、单步 1-2 次预算、检索置信度超阈值直接短路。
- **笨**（27B Q4 规划/格式弱）：
  - **B3 GBNF 约束解码**——llama.cpp 原生 `response_format: json_schema`，零成本压 JSON 翻车，展示工程深度（已列入 `E2E_OPTIMIZATION_REVIEW.md` P1）。
  - **B4 引用幻觉校验器**——"证据型答案"是核心卖点，但 27B Q4 会编造 `file#Lx-Ly`。需在答案产出前程序校验引用文件/行号真实存在、片段确实被检索过。本地必须做，云端准确率高可省（已列入 E2E_REVIEW P0，且与 §2.1 findings 裂缝合并修）。
  - **B5 planner skill tag 白名单校验**——planner 产出 skill 不验证就进路由，小模型会发明不存在的 skill；一行校验 + 正则兜底。
- **窗小**（8192 ctx）：
  - **B6 证据卡式记忆**——云端 128k 靠 history 暴力重放；本地必须工程化：证据卡压缩存储、observations 滚动摘要、多轮追问用检索注入。
  - **B7 thinking 预算分配**——Q4 长推理链质量退化；当前已实现"按空答率实时关 thinking"的保守档位机（governor），可进一步"仅 final synthesis 开 thinking"。

### 3.2 Mixture 多专家 scale 组合 = 本地相对云端唯一结构性性能优势？
**性能侧：是。** llama.cpp 的 per-request `lora` 数组 + scale 组合，云端 API 给不了（你没法在 OpenAI 上按请求混合多个 adapter 权重比例）。当前 router 正则硬选一个、scale 恒 1.0，**Mixture 那一半没被使用**。

**但前提是数据**：必须用 G3 式混合行为实测证明"混合真比单专家好"，否则是噱头声明（评审一句"你的 mixture 有数据吗"就问倒）。

> **待决项（留给用户拍板）**：是否赌这一页？它是潜在最亮眼的一页，但需一组混合行为实测，赌输成本高。`E2E_OPTIMIZATION_REVIEW.md` §3 已将其排除进 PPT future work——本文记录此张力，不替用户决策。

### 3.3 云端够快够强不做、本地必须做的清单（按叙事价值）
1. GBNF 约束解码保 JSON（B3）——展示 llama.cpp 工程深度
2. 引用幻觉校验器（B4）——加固核心卖点生死线
3. 调用预算经济学（B2）——本地部署优化的原创方法论
4. Prefill 瘦身 + KV 复用（B1）——本地第一大头
5. Mixture 路由（§3.2）——结构性优势，需数据
6. Thinking 预算分配（B7）——量化小模型独占旋钮
7. 证据卡式记忆（B6）——替代云端长窗暴力

---

## 4. 一个未测的地雷（A/B 共同关注）

**per-request lora 切换 vs 共享前缀 KV 缓存复用**。

llama.cpp 的 slot KV 复用依赖"前缀权重一致"。当前 roomy 模式每步 per-request 切换 lora（chat 注入 `lora` payload），**切换后已缓存的共享前缀 KV 是否仍有效，从未实测**。若失效，则每次换帽子都强制全量 re-prefill——这才是热切的**真实**成本，而不是 0.65ms 的控制面 toggle。

**建议**：一次针对性实测（固定前缀 + 变 lora 请求，对比命中/失效的 prefill 耗时）。结果本身即是优化故事素材，且决定 §1.2 / §2.3 的叙事该怎么写。

---

## 5. 本文新增待办（已与 E2E_OPTIMIZATION_REVIEW 去重）

| 待办 | 性质 | 优先级 |
|---|---|---|
| 重构 README §5 / TRUTH §1.5 的 0.65ms 叙事为"decode 税 + 按步付费"模型 | 叙事保命（护住 40 分大项） | **P0** |
| KV 失效 re-prefill 实测（§4） | 一次实验，决定热切成本表述 | P1 |
| Mixture 路由赌不赌（§3.2） | 用户决策，最亮眼但需数据 | 待决 |
| A2 错误吞没链 + findings `citations=[]` 修复 | 与 E2E_REVIEW P0 引用验证器合并 | P0（并入既有项） |

---

## 6. 校准记录（早期 v1 判断哪些被 v6 推翻）

| 早期(v1 / screwshell-v2)判断 | v6 事实 | 结论 |
|---|---|---|
| e2e 从未跑通真机 | tight 模式两次 EXIT=0，确定性 4 专家换装真机验证 | 推翻，autotune 方案成立 |
| 默认 backend=peft(9B 旧栈) | 已接 autotune + L3 双档治理，VRAM bug 已修 | 推翻 |
| 双重激活路径是设计 bug，须二选一 | L3 显式设计为 roomy(热切)/tight(重启)双档，且 tight 防 stale 注入 | 推翻为"刻意设计"，残留问题是叙事未同步 |
| 阵容待转 GGUF(T1) | 四专家全部已转✓，有真机 reload 数字 | 推翻 |
| 0.65ms 测的可能只是 HTTP 往返 | 部分成立：0.65ms 确为控制面 toggle；但适配器在路径中的证据是 decode 降速，非热切数字本身。重构叙事即可，不是"测量无效" | 校准为"叙事风险" |
