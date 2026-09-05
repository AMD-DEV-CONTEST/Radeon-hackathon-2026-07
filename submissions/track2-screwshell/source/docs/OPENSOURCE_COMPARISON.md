# ScrewShell 功能模块 × 成熟开源项目对标分析

> **定位**：产品演进方向研究文档（非信源）。黑客松截止 2026-08-06，本文不改变任何提交决策；
> 结论分「提交后可立即吸收的低风险改进」与「提交后的中期方向」两档。
> 数据来源：2026-08-04 联网检索（来源清单见附录），项目事实以 `docs/TRUTH.md` 与代码为准。

---

## 一、结论先行（三条）

1. **核心创新方向验证成立。** ScrewShell 的三项关键设计在成熟生态里都有对应物且方向一致：
   - MoL「全局 LoRA toggle + 串行锁」架构，与 S-LoRA / Punica / vLLM 论文里「多适配器混批有串行化代价、统一内存池才治本」的结论同向——你实测的「per-request 换帽毁 KV 100%、全局 toggle 全命中（415 倍差）」就是这条定理的实物证据；
   - 手写 ReAct 循环不引 agent 框架，符合 2026 年生态共识（"Start without a framework; add one when you hit a real limitation"）；
   - 引用三层校验器（语法→文件→实际检索过）对齐 Claude Citations API / Gemini span-grounded 的生产级做法——你缺的只是「quote 字符串回验」这一层。
2. **三处明显差距 + 一条横切轴（E2E 优化，见 §3.5/§4.6）**：RAG（无 rerank / 无 hybrid 检索）、路由（纯正则、无语义兜底）、可观测（自建 JSONL，无 trace 级 span 关联）；E2E 轴上最大可抄项是 llama.cpp **原生投机解码**（ngram / `--model-draft`）——本地 decode 26–31 tok/s 的直接解药，且你的 agent 结构化负载（JSON 工具调用）正是它的理想场景。
3. **两处「别动」**：推理后端保持 llama.cpp（ROCm 上最成熟；vLLM/SGLang/LoRAX 的 ROCm 支持均不如 llama.cpp，且 2 天内换后端=自杀）；编排不引 LangGraph（当前 659 行手写 loop 已覆盖你的全部需求，框架的收益点——状态持久化/多智能体/人工审批——你都不缺）。

---

## 二、对标方法

按 ScrewShell 的 9 个功能域分别检索成熟开源项目（每域取 2–5 个代表），再做「当前实现 → 生态做法 → 差距 → 建议」四栏对照。检索域：多 LoRA serving、LLM 路由、本地 RAG 平台、Agent 编排、可观测、工具沙箱、引用/证据、推理网关、评估。

---

## 三、逐模块对照表（核心交付）

| # | 功能模块 | ScrewShell 现状 | 成熟生态做法（代表项目） | 差距 | 建议 |
|---|---|---|---|---|---|
| 1 | **MoL 推理核心** | llama.cpp 单 base + 全局 `/lora-adapters` toggle；adapter 切换与生成串行（`asyncio.Lock`）；decode 税 15–25% | vLLM `--enable-lora` / SGLang / LoRAX：**request 级选 adapter + SGMV kernel 多适配器混批 + 统一内存池**（S-LoRA：单 A100 2000 adapter，4× 吞吐）；llama.cpp 生态侧有 **llama-swap**（Go 代理，按 model id 换装 + groups + ttl + preload） | llama.cpp 单客户端架构决定了你只能串行；成熟方案把「多适配器同时驻留」做进了 kernel/内存层 | **保持 llama.cpp**（ROCm 最成熟）。把 InferenceCoordinator 的「换后端」抽象留好（已具备）；提交后可研究 llama-swap 的 config 化换装思路 |
| 2 | **中继网关** | 自研 FastAPI `/v1`（X-Expert 信任 + `/lora-adapters` 404 屏蔽 + observ 端点） | **llama-swap**（MIT，单 Go 二进制 + yaml 即换装，支持 groups 并发、ttl 自动卸载、startup preload hooks、`/ui`+`/log` 监控）；LiteLLM（规则路由/回退链） | 你做了更严格的东西（信任边界、串行协调、可观测），llama-swap 胜在「零依赖、配置化、生产久经考验」 | 方向一致，不必换。可借鉴：ttl 自动卸载、startup 预载、config 热加载 |
| 3 | **Skill Router** | 纯正则关键词启发式（`SECURITY_KW`/`CODE_KW`…），确定性、可复现 | **RouteLLM**（LMSYS，BERT/矩阵分解分类器，MT-Bench 省 85% 成本 @95% 质量）；**semantic-router**（Aurelio，embedding 相似度路由，毫秒级、无 LLM 调用）；vLLM Semantic Router（推理层路由）；FrugalGPT | 正则快而笨：跨语言/同义改写/隐式意图会 miss，且无「置信度」概念；生态共识是「规则打底 + 嵌入兜底」两级 | **提交后**：给 router 加一层 embedding 相似度兜底（你已有本地嵌入 Qwen3-Embedding-0.6B，零新增依赖），未命中正则时走最近 skill 示例 |
| 4 | **本地 RAG** | 行感知分块（3200 字符/8 行 overlap）→ Qwen3-Embedding-0.6B → **numpy 点积检索** top_k=5 → `file#Lx-Ly` 引用 | **RAGFlow**（DeepDoc 版面感知解析 + 模板化切片 + 多路召回 + **cross-encoder 精排** + GraphRAG，引用回源到版面坐标）；AnythingLLM（工作区隔离 + 多向量库 LanceDB/Chroma/Qdrant）；PrivateGPT（LlamaIndex + Qdrant） | ① 无 rerank——top_k 直接喂 LLM，噪声大；② 无 hybrid（BM25 关键词 + 向量）——精确术语/代码符号召回差；③ numpy 全量点积，语料上万 chunk 后变慢；④ 无表格/PDF 版面理解 | **提交后第一优先**：加一层 rerank（bge-reranker 或简单 cross-encoder，RAGFlow 同款思路）；BM25 可先用 `rank_bm25` 库零配置接上 |
| 5 | **ReAct 编排器** | 手写 659 行循环：plan(TaskCard JSON) → 每步路由+挂 LoRA → ≤5 次 think/tool/finish → final 合成；`_extract_json` 正则+轻修复 | LangGraph（图状态机，v1.0）；OpenAI Agents SDK（最小抽象 + guardrails + handoffs + tracing）；AutoGen/CrewAI（多智能体）；**生态共识：基础 loop ≈50 行代码，框架在「多智能体/持久状态/HITL/可观测」这些你不需要的地方才值钱** | 差距≈0。手写 loop + 你自己造的 TaskCard/EvidenceCard 契约就是「极简 harness」的正确形态（与 earendil-works/pi 的极简哲学同路） | **不引框架**。可抄的只有一点：OpenAI Agents SDK 的 guardrail 分层（输入/输出 guard）——你有 PermissionGate，已有对应物 |
| 6 | **证据/引用** | 三层校验器（语法→文件→实际检索过）+ off/annotate/strip 三模式 + merge；`stats["citations"]` | Claude Citations API（span 级引用 + 字符偏移）；Gemini 三档：A 自由文本（不可用）/ B structured claims+source_ids / **C span-grounded + 引文原文字符串回验（生产推荐）**；clawpedia grounding 协议（R1–R5：引文必须指向检索集、引文原文必须逐字出现在源中） | 你已到 B+ 级（结构化 + source_id 校验），缺 C 级的 **「quote 逐字回验」**（校验引用的文本片段确实存在于该源 chunk） | 提交后补：citations.py 加 quote 字符串匹配层（`quote in chunk_text`），成本 ~30 行 |
| 7 | **工具层/沙箱** | 6 只读工具 + 路径 resolve 强校验 + 命令白名单 + 元字符禁令 + grep 逐文件过门 + JSONL 审计 | **E2B**（Firecracker microVM，~125ms 冷启动）；gVisor/Kata（内核隔离）；**agent-airlock**（LLM 工具调用安全层：ghost-args 剥离、网络 airgap、PII 掩码、路径校验、OpenTelemetry）；威胁模型四类：数据泄露/主机逃逸/横向移动/资源滥用 | 你的 fail-closed 白名单思路与 agent-airlock 同源（都很对）；但**无资源上限**（工具无超时/内存上限/磁盘限额）、无网络出口控制 | 提交后补：给 shell_readonly 加超时（`subprocess.run(timeout=)`）+ 输出截断上限；网络 airgap 对「默认私有」定位是天然卖点 |
| 8 | **可观测** | 自建 JSONL+SQLite 双写（RequestEvent：路由/适配器/TTFT/KV 命中）+ 内存 ring + 汇总 + Gradio 面板 | **Langfuse**（OTel 原生，traces/evals/prompt 管理，可自托管）；**OpenLIT**（OpenTelemetry 原生，K8s 友好）；OTel **GenAI Semantic Conventions**（`gen_ai.*` 属性标准）；决策树：有 OTel 基建→OpenLLMetry，要自托管 UI→OpenLIT/Langfuse | 自建 observ 与 OTel GenAI 属性命名不对齐——未来接 Langfuse 要写适配层；无 trace 级父子 span（请求→步骤→工具调用 的因果链） | **提交前不动**（离线优先 + 时间不允许）；提交后可把 RequestEvent 字段按 `gen_ai.*` 命名对齐，保持可移植 |
| 9 | **评估/质量闸** | `screwshell/eval/`（8 个纯函数评分器 + 回归门 compare + thresholds 单一事实源 + mock 全套） | Langfuse/Promptfoo 的 eval 功能；Ragas（RAG 指标）；生态做法补充点：**llm-as-a-judge**（人工 gold 集 + LLM 打分）、CI 内 eval 回归门（你在 verify_bugfixes.py §8 已做测试数闸，方向正确） | 你已有「客观评分器 + 回归门」，比多数开源 demo 强；缺 llm-as-a-judge 主观分（RAG 答案质量、引用相关性） | 提交后：eval 加一个 judge 评分器（用基座原生 thinking 当 judge，零外部依赖） |

### 3.5 E2E 优化（横切性能/质量轴）——补对标

> 上一版按「纵向功能域」组织，把 E2E 优化这条**横向轴**漏了。它横跨推理服务层（KV/吞吐/延迟）与编排层（prefill/预算/缓存/错误处理），正是 `docs/E2E_OPTIMIZATION.md` §8/§12/§13（T2–T15）的主题。下表状态以该文档 §13 实测为准（2026-08-04 代码真值）。

| E2E 子项 | ScrewShell 状态 | 成熟生态做法 | 差距/建议 |
|---|---|---|---|
| **KV/前缀缓存（T10 已测）** | 全局 toggle 保前缀全命中（415 倍差）；「system+工具规格前置、observations 后置」= 手动前缀布局 | vLLM **APC**（block 哈希表 + LRU）；SGLang **RadixAttention**（基数树、token 级共享、缓存感知调度；共享前缀场景比 vLLM 高 24–29% 吞吐） | llama.cpp 的 slot KV **跨请求不共享**（每 slot 独立），SGLang/vLLM 跨请求共享——架构级差距，也是未来并发多前端时换后端的主要动机；T10 实测 + 手动前缀布局已是当前可及最优 |
| **投机解码（未做）** | 无；decode 26–31 tok/s 是本地第一瓶颈 | llama.cpp 原生 `--model-draft`/llama-speculative（单流实测近 2 倍：42→72 tok/s）；**ngram 投机**（llama.cpp PR #19164，2026-01，零第二模型，适合代码/JSON/模板重复负载）；Qwen3.6 自带 **MTP 头**（vLLM 已支持；llama.cpp PR #22673 未合并） | **本地提速最大杠杆**：agent 工具调用全是结构化 JSON = ngram 投机理想负载；Qwen3.6-27B 的 MTP 是未来主菜 |
| **prefill 瘦身（T8 未做）** | 工具 spec 按 step 裁剪 flag 已预留未接线 | LLMLingua 等 prompt 压缩；共享前缀 KV 复用（同首行）；SGLang/vLLM 把共享前缀 prefill 变一次性成本 | 你的「本地 prefill 经济学」（B1）是**云端框架没有的原创故事**（云端 prefill 便宜没人关心）——评审叙事价值 > 工程价值 |
| **约束解码（T7 部分）** | `chat()` 已支持 `response_format/json_schema` + 能力探测；编排层 plan 未接（json_parse 兜底仍在） | llama.cpp GBNF/grammar；SGLang **compressed FSM + jump-forward**；vLLM guided decoding（Outlines/xgrammar） | 接编排层即可（planner 用 json_schema 压翻车率），工作量小、展示 llama.cpp 工程深度 |
| **路由/语义缓存（T14 未做）** | `router_cache` flag 已预留未接线 | LLM gateway **semantic cache**（embedding 相似命中直接回缓存、免推理）；Redis 生态 | 同 query/近 query 多轮追问可短路——与「多轮记忆」配合，本地省一次 30–45s 调用 |
| **错误上浮（T5 未做）** | `chat()` 失败返回 `("",GenStats)`，orchestrator 静默吞错 | circuit breaker（agent-airlock）；优雅降级 + 失败可见（SSE error 事件你已在 relay 层做了） | 与你的 P0 修复（activate 失败抛 RuntimeError + SSE error）同哲学，补 chat 层即可闭环 |
| **性能/质量回归闸（未做）** | `verify_bugfixes.py` §8 只闸测试数 | 持续基准 + latency/质量回归门（Langfuse alerts、LLM perf CI） | `bench/eval_e2e.py` 已有 A/B 基线 + compare 回归门，接 CI 定时跑即闭环 |
| **连续批处理/调度** | 串行锁（`asyncio.Lock`，单用户调查场景可接受） | vLLM continuous batching（16 流 165 tok/s vs llama.cpp 16 流 OOM） | **多前端并发**场景才需要；单用户调查 agent 不构成瓶颈——别为它换后端 |

---

## 四、重点模块深度分析

### 4.1 RAG：差距最大，直接抄 RAGFlow 的「多路召回 + 精排」

ScrewShell 现状：行感知分块（这是亮点，保留行号对引用极重要）→ 单路向量检索 → top_k=5 直接进 prompt。生态共识（RAGFlow / Onyx / 各家综述）是标准三段：**多路召回（向量 + BM25）→ 精排（cross-encoder）→ top_k 注入**。RAGFlow 用 YOLOv8 版面分析 + 模板化切片 + 多路召回 + 交叉编码器精排，「LLM-as-judge」评测里综合准确率 4.24/5（高于 Dify 3.67/5）。

你的场景（本地代码/文档审查）对**精确引用**要求高，而 top_k 无精排时噪音 chunk 直接进上下文，既烧 KV 又拉低引用准确率——这正是你 T4 引用校验器会抓到的那类问题（cite 了但内容不相关）。加 rerank 是**唯一一个能同时改善检索质量与引用准确率的杠杆**。

### 4.2 路由：正则打底没错，但缺「语义兜底」这一层

2026 生态的成熟度分级很清晰：关键字/规则（微秒级）→ 嵌入相似度（毫秒级）→ LLM 分类（秒级）。RouteLLM 证明学习式路由可省 85% 成本，但那是「多模型价格差」场景——你切换 LoRA 不花钱，所以**学 RouteLLM 意义不大**；真正值得抄的是 semantic-router 的嵌入相似度：你的 `SECURITY_KW` 正则对「帮我审一下这个 .env 泄露风险」这种隐式 security 意图会 miss（没有关键词），而 embedding 相似度兜底能接住。你已有 Qwen3-Embedding-0.6B 在跑，加一层毫秒级兜底几乎零成本。

### 4.3 MoL serving：你的串行锁是 llama.cpp 架构的必然，不是设计缺陷

多 LoRA serving 的成熟方案（LoRAX / vLLM / SGLang / S-LoRA）靠三件套解决问题：**SGMV kernel**（Punica，多 adapter 混批 ≈ 单 adapter 成本）、**统一内存池**（S-LoRA：KV + adapter 权重同池分页）、**request 级 adapter 选择**。llama.cpp 至今是单客户端架构，没有这三件套，所以你只能「全局 toggle + 串行锁」——这是当前约束下的正确解，且你的 KV 实测（415 倍差）为这个决策提供了量化依据。

但要注意天花板：**单卡串行 = 并发被锁死**，未来多前端（opencode/pi 同时接入）并发请求会排队。中期路线：① 保持 llama.cpp + InferenceCoordinator（现在）；② 等 vLLM/SGLang 的 ROCm 多 LoRA 成熟（2026 年 vLLM 已支持 Qwen，ROCm 在跟进）；③ 期间用 llama-swap 的 groups 思路跑「多端口多实例」绕过串行。

### 4.4 做对了：全局 toggle 而非 per-request lora（与论文结论互相印证）

S-LoRA 论文明确「不同 adapter 的请求串行化有惩罚」，你的实测给出的是它的反面证明：per-request 换帽 = KV 全毁 +2.35s，全局 toggle = 全命中（415×）。这说明你踩过的 P0 坑（混用两路径静默回退 base）不是孤例——混用恰恰是「request 级适配」在 llama.cpp 上的不完整实现。这个发现本身是很好的评审叙事点。

### 4.5 做对了：手写 ReAct 不引框架

2026 年多份生态综述的一致结论：**基础 agent loop ≈50 行代码，框架的收益在状态持久化、多智能体协作、HITL、tracing 这些点**——而 ScrewShell 用自建 TaskCard/EvidenceCard/ArtifactStore 契约实现了前两者，PermissionGate 实现了 HITL，observ 实现了 tracing 的雏形。你的 659 行手写 loop 是「极简 harness」的正确形态（与 earendil-works/pi 同路），评审时这反而是加分项：「无框架依赖、完全可控」。

### 4.6 E2E 优化：最有故事的横切轴

**最值得抄的是投机解码，最值得讲的是 prefill 经济学。**

- **投机解码 = 本地 26–31 tok/s 的最直接解药**：llama.cpp 原生 `--model-draft` 单流近乎翻倍（实测 42→72 tok/s）；**ngram 投机**（llama.cpp PR #19164，2026-01）不需要第二个模型，靠「输出重复输入」（代码、JSON、模板、路径）——你的 agent 负载（结构化 JSON 工具调用、重复 imports/文件路径）正是理想场景，且 ngram 永不损害正确性，可默认开启。**Qwen3.6-27B 自带 MTP 头**，vLLM 已支持（llama.cpp PR #22673 待合并）——这是「Qwen3.6 + 本地部署优化」赛道的重量级续集，值得在 README §5 future work 里写一句。
- **prefill 经济学（B1）= 云端框架给不了的原创点**：云端 prefill 又快又便宜没人关心；本地 ~100 tok/s 下 prompt 每省 1 token 都是钱。你的「工具 spec 裁剪 + 固定前缀 KV 复用」= 手动版 RadixAttention 前缀布局，T10 实测（415 倍差）就是它的量化证明。**评审叙事建议**：讲「整个 agent 栈的本地化优化」而非单点切换（这正是 E2E_OPTIMIZATION.md §1.1 指出的原 README 短板）——如今 KV 实测 + eval 闸已落地，叙事闭环只差补一组「投机解码开/关」的端到端数字。
- **架构天花板提示**：llama.cpp 的 slot KV 跨请求不共享（SGLang RadixAttention 的核心卖点），这是未来并发多前端时换 vLLM/SGLang 的主要动机——但单用户调查 + 串行锁在当下是正确的取舍，别提前换。

---

## 五、可落地改进清单（按性价比三档）

### A 档：提交后可立即吸收（低风险、低工作量）

| 改进 | 抄自 | 工作量 | 效果 |
|---|---|---|---|
| RAG 加 rerank（bge-reranker-base 或简单 cross-encoder） | RAGFlow | 0.5–1 天 | 检索精度 + 引用准确率双升 |
| BM25 混合检索（`rank_bm25` 库，numpy 已有类似基础） | RAGFlow/Onyx | 0.5 天 | 代码符号/精确术语召回 |
| shell_readonly 加超时 + 输出上限 | agent-airlock/E2B 资源上限 | 2 小时 | 防死循环/内存炸弹 |
| citations.py 加 quote 逐字回验层 | Gemini Approach C / Claude Citations | 半天 | 引用校验闭环到「内容级」 |
| 投机解码（ngram 投机，llama.cpp PR #19164） | llama.cpp 原生 | 0.5 天 | 结构化负载解码提速（agent JSON 工具调用理想场景）；无第二模型、不损正确性 |

### B 档：提交后中期方向

| 方向 | 抄自 | 说明 |
|---|---|---|
| 路由 embedding 相似度兜底 | semantic-router | 正则 miss 时走最近 skill 示例；复用现有嵌入模型 |
| RequestEvent 字段对齐 OTel `gen_ai.*` 命名 | OTel GenAI SemConv | 未来免适配接 Langfuse/OpenLIT |
| eval 加 llm-as-a-judge 评分器 | Langfuse/Ragas | 用基座原生 thinking 当 judge，零外部依赖 |
| 多实例并发（多端口 llama-server + groups） | llama-swap | 绕开串行锁的务实路线 |
| 网络出口管控（airgap 策略化） | agent-airlock | 「默认私有」卖点的硬证据 |
| 编排层接 json_schema 约束（T7 收尾） | SGLang compressed FSM / vLLM xgrammar | planner 用 `chat()` 已支持的 `response_format/json_schema` 压 JSON 翻车率 |
| llama.cpp `--model-draft` 投机解码（需第二小模型） | llama.cpp 原生 | 大模型单流提速，需先 bench 验收率 >70% 再上线 |

### C 档：明确不做（附理由）

| 方向 | 理由 |
|---|---|
| 换 vLLM/SGLang/LoRAX 后端 | ROCm 支持不如 llama.cpp；2 天内换 = 自杀；S-LoRA 等方案是 CUDA 系 |
| 引 LangGraph / OpenAI Agents SDK | 当前 loop 已覆盖全部需求；框架收益点你都不缺；多一层抽象多一层 churn |
| 上 Langfuse/OpenLIT 替代自建 observ | 离线优先 + 自建已满足；只在需要可视化 trace 树时再考虑 |
| RouteLLM 学习式路由 | 你的切换不花钱，省成本逻辑不成立；且需要偏好数据训练 |

---

## 六、风险提示

1. **黑客松剩余 2 天**：A 档里只有「超时+上限」「quote 回验」敢在提交前动；rerank/BM25 动 RAG 主链路，需等 8/6 提交后或当作「8/5 缓冲日」的独立分支验证。
2. **别让对标变成「评审要求」幻觉**：评委看的是 Radeon 上的差异化（MoL 热切换 + 全本地 + 证据引用），不是「你们有没有用 RAGFlow」。本文定位是产品演进地图，不是补齐清单。
3. **引用来源层级**：本报告大量引用生态综述/对比文（见附录），个别项目数字（如 RouteLLM 85%）是厂商/论文口径，落地前以官方 README 与实测为准。
4. **文档纪律**：本文非信源。若吸收 A 档改进，须同步 `docs/TRUTH.md` §3 测试数、`SUBMISSION_CHECKLIST.md` 与 `verify_bugfixes.py` §8 阈值。

---

## 附录：检索来源（2026-08-04 联网）

- 多 LoRA serving：dreaming.press《Serving Many Fine-Tuned Models on One GPU: LoRAX vs vLLM vs SGLang》；lin-guanguo.github.io《Per-User Multi-LoRA》（S-LoRA 2000 adapter / Punica SGMV 2ms / LoRAX 128 adapter）；axiomlogica《S-LoRA vs LoRAX vs vLLM PEFT》
- llama-swap：github.com/mikicvi/llama-swap（MIT，Go 单二进制，groups/ttl/preload/`/ui`）
- LLM 路由：klymentiev.com《LLM Router 2026》（RouteLLM 85%@95%、LiteLLM、vLLM Semantic Router v0.1 Iris）；zylos.ai《AI Agent Model Routing》；RouteLLM（LMSYS，ICLR 2025）
- 本地 RAG：onyx.app《Self-Hosted RAG in 2026》（RAGFlow/Onyx/AnythingLLM/Verba）；tmtpost《RAG准确率90%?先过文档解析这关》（RAGFlow DeepDoc / AnythingLLM 轻量）；blog.xbaby.xyz《AnythingLLM MaxKB RAGFlow 选型》
- Agent 编排：happycapyguide《AI Agent Frameworks Compared 2026》（"Start without a framework"）；securelastingservices《Agentic Frameworks First-Principles》（~50 行 loop）；talhachowdhury《Agent Architecture Patterns》（ReAct 模式）；liukunup《Agent 框架深度对比》
- 可观测：langfuse.com（OTel 原生/自托管/集成表）；juejin《AI Native 可观测性架构》（选型决策树：OpenLIT/OpenLLMetry/Langfuse）；OTel GenAI Semantic Conventions
- 工具沙箱：harryzhang.cn《Sandbox 在 AI Agent 中的应用》（四类隔离机制对比 + E2B/gVisor/Kata/Firecracker）；neelmishra《Code Sandboxes: E2B, Modal, Docker》；agent-airlock（PyPI，ghost-args/airgap/PII 掩码/OpenTelemetry）
- 引用/证据：skillmd.ai《How to Build citations-retrieval Agent Skill》；clawpedia《Knowledge Grounding and Citation Protocols》（R1–R5）；vadimall.com（Claude Citations API span 级引用）；gemilab《Citation-Grounded RAG with Gemini》（A/B/C 三档 + 字符串回验）
- E2E 优化（本轮补充）：yaoyuanzhou.github.io《SGLang 深度解析》（RadixAttention 前缀树）；prakashkagitha.github.io《Prefix Caching & KV-Cache Reuse》（APC vs RadixAttention 对比 + cascade attention）；aimadetools《SGLang vs vLLM》（共享前缀场景 +24–29% 吞吐）；sumguy.com / teachmeidea.com《Speculative Decoding》（llama.cpp `--model-draft` 42→72 tok/s、vLLM speculative_config、ngram 投机）；blog.bymar.co（llama.cpp PR #19164 ngram-mod / PR #22673 MTP、Qwen3.6 MTP 头）；specpicks《vLLM vs llama.cpp on RTX 3060》（单流 llama.cpp 优、并发 vLLM 优：16 流 OOM vs 165 tok/s）
