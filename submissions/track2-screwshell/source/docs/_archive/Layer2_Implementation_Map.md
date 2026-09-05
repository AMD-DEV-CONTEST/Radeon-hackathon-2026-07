# ScrewShell 第 2 层（统一观测 / 调优层）实现地图

> 调研目的：调查互联网现有开源项目，把第 2 层需求逐一映射到"能直接借 / 该自己造"，并给出按性价比排序的落地路径。
> 适用约束：本地部署、AMD Radeon **W7900 (48GB)**、llama.cpp 推理引擎、单基座（Qwen3.6-27B）+ 热切换 LoRA（MoL）、两种入口（自研 Gradio + opencode/pi 等成熟前端）共享 **ScrewShell 中转网关** → llama-server。
> 成文：2026-08-03。初稿评审：2026-08-04（GPT 复审，见 §10 修订记录）。
> 本文档为架构调研，**未涉及代码改动**；但 §1.2 指出的混用 bug 已在当前 `mol_engine_llamacpp.py` 中实测存在，属待修项而非待调研项。

---

## 0. 一句话结论（经 GPT 复审修订）

你设想的第 2 层 = 一个"本地部署专属优化中枢"。调研 + 本机实测后，结论修订为：

- **网关"你已有"是错的**。当前只有 llama-swap **peers 代理**（:18080）+ 客户端薄适配层（`MoLLlamaCpp` 内的 key/model/id/审计），**没有真正的 ScrewShell `/v1` 公共中继**。而且 peers 模式根本**不暴露 `/lora-adapters`**（返 404，见 §1.6），MoL 切专家现在没法走网关。Phase 0 必须先建真中继。
- **可观测 v1 别上重型栈**。第一版用 **llama.cpp 原生 `timings` + 仓库已有的 `core/metrics.py`(`RunMetrics`/`CallRecord`) + `autotune/*` + 现有 Gradio 面板**，存 JSONL/SQLite。OpenLIT / OTel / ClickHouse / Grafana 留到指标稳定后再接。
- **MoL 切专家有两条真路径，本机已实测代价**（§1.2）：全局 `POST /lora-adapters`（KV 全命中，0 重 prefill）vs 请求级 `payload["lora"]`（KV 全失效，+2.35s）。**当前代码两条都发 = P0 静默失效**（专家退回基座，HTTP 零报错）。单卡 W7900 的 v1 决策是：**全局串行切 LoRA + 单请求推理队列**；“主代理 S0 + 专家 S1”只保留为后续真机实验，不能作为当前已证实的隔离方案（见 §1.4–§1.5）。
- **借/造**：配置自动化 / 容量规划小模块造（公式公开）；GBNF 约束解码、引用幻觉校验器直接借（最成熟、风险最低）；真正自造的只有两层语义胶水——① 本地推理信号→agent 体感的可观测语义；② 证据卡式记忆（产品差异化核心）。MoL 路由（`SkillRouter._decide()`）已基本写好。

---

## 1. 关键架构修正：MoL 切专家的原语与两条路径（本机实测）

这是本次调研最重要的发现，也修正了初稿里"把全局切换当成按请求切换"的错误。

### 1.1 旧思路（错原语，已弃）

初稿曾把 **llama-swap managed-mode** 当成切专家路径。它做的是"整模型进程替换"——为换个专家去**杀/起重整个 llama-server 进程**。流式断流、重载开销、单进程崩溃全中断。这条路已实测不可行，**弃用**。

### 1.2 两条真路径 + 实测代价（核心修正）

llama.cpp server 原生支持运行时切 LoRA，但**有两个不同的原语**，代价天差地别（实测见 `bench/kv_reprefill_report.md`，W7900 / Qwen3.6-27B-Q4_K_M / `n_ctx=8192` / `total_slots=4`，5 次采样零方差）：

| 路径 | 调用方式 | 前缀 KV | 实测代价 | 隔离性 |
|------|----------|--------|----------|--------|
| **D · 全局 toggle** | `POST /lora-adapters [{"id":N,"scale":1.0}]`（改 server **全局** LoRA 状态） | **全命中**（`cache_n=1656`，仅 4 tok 重 prefill） | **0 额外 prefill** | 全局共享，并发会互相踩踏 |
| **C · 请求级** | 在 completion 请求体里带 `"lora":[{"id":N,"scale":1.0}]` | **全失效** | **+1656 tok / +2.35 s**（warm 基线 415×） | 请求隔离，但代价高昂 |
| **混用 C+D** | 两路都发（见 §1.3 当前代码） | 不可预测 | P0 正确性 bug：专家**静默退回基座**，HTTP 零报错 | — |

> 初稿错误：把 `POST /lora-adapters` 写成"每次请求切专家"（暗示按请求隔离）。它实际改的是 **server 全局状态**，不是请求级。真正的请求级方式是 completion 请求体里的 `lora` 字段。两者不能混为一谈。

### 1.3 当前代码状态（已在踩 P0 bug，必须修）

`MoLLlamaCpp`（`screwshell/core/mol_engine_llamacpp.py`）**同时走了两条路**：
- `activate(name)` (`:259`) → `POST /lora-adapters`（全局 toggle，路径 D）
- `chat()` (`:581-584`) → 当 `active_adapter` 非空时往请求体塞 `payload["lora"]`（请求级，路径 C）

两条都发 = 报告 §3 的**混用静默失效**（探针 P3：6/12 生成逐字等于基座，连续多次稳定复现，且只有冷启才能恢复）。这是真 bug，不是待调研项。**修复方向不是"选 A 还是 B"，而是：v1 只用全局 toggle，从 `chat()` 删掉请求级 `lora` 注入**（见 §5 Phase 0）。

### 1.4 v1 决策：全局切 LoRA + 单请求推理队列

路径 D 的性能优势成立，但它是**全局状态**，不能靠“独立 slot”自动获得请求隔离。单卡 v1 先采用最简单、可验证的策略：由 `InferenceCoordinator` 统一排队，拿到锁后完成一次完整的“选择 LoRA → 推理/流式返回 → 清理”再释放锁。

- **所有入口共用同一条队列**：网页 Agent、opencode、pi 的请求都不能绕过中继直连 `llama-server`。
- **中继只做路由，Coordinator 才拥有状态**：中继得到 `RouteDecision`（目标专家、thinking 模式、request/run ID），交给 Coordinator；Coordinator 独占全局 LoRA 状态、切换锁、请求队列和流式清理。
- **v1 禁止请求级 `payload["lora"]`**：`chat()` 不再注入请求级 LoRA，避免 C+D 混用造成静默退回基座。
- **工具执行不占模型锁**：模型完成一轮回答或发出 tool call 后释放锁；工具在外部执行，下一次模型请求重新路由和排队。流式请求要等到 `[DONE]`、断开或超时清理后才能释放。
- **并发策略要显式**：队列满时返回 429 或排队超时，不能让多个请求同时改全局 LoRA。
- **外部前端不需要知道子代理**：opencode/pi 仍然只看到标准 OpenAI 请求/响应；它们的每一轮请求由中继独立判断并选择 LoRA，不插入隐藏的“consult expert”协议。

这一步牺牲并发，换取当前单卡上可证明的正确性和 KV 复用。未来若要并发，再选择“每专家独立 llama-server”或请求级 C，并重新测性能。

### 1.5 S0/S1 专家子代理：后续实验，不是 v1 前提

“主代理 S0 + 专家 S1”是一个有价值的优化假设，但目前不能写成已成立的结论：**slot 只隔离上下文/KV 序列，不代表隔离全局 LoRA 状态**。当前实测只覆盖单 slot；多 slot 下必须先验证：

1. S0 用 base 长上下文暂停；
2. 全局切到专家，S1 完成一次短咨询；
3. 切回 base，S0 继续生成；
4. 对比切换前后 `cache_n`、输出正确性和首 token 延迟。

只有这组测试证明 S0 的 KV 没有被清空或错误使用，S0/S1 才能进入 Phase 4。即使测试通过，专家子代理也只适用于自研网页 Agent 的内部编排；opencode/pi 仍走普通的请求路由。

### 1.6 影响

- llama-swap 在 MoL 场景**彻底弃用**：managed-mode 流式断流（已知坑）；peers 模式**不暴露 `/lora-adapters`**（G3 bug，`POST /lora-adapters` 经网关返 404），MoL 根本没法过网关。
- 可靠性反而变简单：单 llama-server 常驻 + 健康检查 + 自动重启；中继只做薄代理，`InferenceCoordinator` 负责状态串行，运行层/系统 supervisor 负责生命周期（避免 managed 的流式回归）。

---

## 2. 三平面边界（显式，经 GPT 复审保留并明确）

GPT 复审指出初稿"三平面雏形在但边界不够明确"。显式如下，且第 1 层"中继"与第 2 层"观测"在此收敛为三个平面：

```
┌─ 中继层 (Relay) ─────────────────────────────────────────────┐
│ 接收 网页端 / opencode / pi 的请求（统一 /v1 入口）            │
│ • 鉴权 / 审计 / request_id / run_id                            │
│ • 任务判断 → RouteDecision（调 SkillRouter，不直接发 HTTP）    │
│ • 调用 InferenceCoordinator，返回普通 SSE / JSON              │
│ • 不向外暴露原始全局 /lora-adapters 控制端点                  │
└──────────────────────────────────────────────────────────────┘
┌─ 运行层 (Runtime) ───────────────────────────────────────────┐
│ 生成 llama-server 启动参数（--jinja / ctx / --lora / thinking）│
│ 启动、健康检查、重启（进程守护）                               │
│ InferenceCoordinator：全局 LoRA 状态、切换锁、单请求队列       │
│ 管理 ctx / thinking 上限；不与中继重复持有并发锁               │
└──────────────────────────────────────────────────────────────┘
┌─ 观测层 (Observability) ─────────────────────────────────────┐
│ 记录首 token / prefill·decode / KV 命中 / thinking / LoRA 命中 │
│ v1：原生 timings + core/metrics.py 字段 + RequestEvent 存储     │
│      JSONL/SQLite + Gradio 面板                               │
│ 增强：OpenLIT(AMD GPU) / OTel / Grafana                        │
│ 驱动 e2e 优化闭环：体感差 → 面板定位是哪层 → 改运行层配置      │
└──────────────────────────────────────────────────────────────┘
```

边界规则：中继只负责协议兼容和路由决策；`InferenceCoordinator` 是全局 LoRA 与模型请求并发的唯一 owner；运行层负责进程和配置；观测层只接收事件、落盘和展示。原始 `/lora-adapters` 只能由 Coordinator 通过私有下游连接调用，不能让外部客户端绕过锁直接修改全局状态。

---

## 3. 第 2 层需求 → 现有项目 → 借/造 对照表

"方向 1"把网关定义为"自动化、可观测、不踩坑的本地模型配置层"，覆盖五层：

| # | 需求 | 现有项目 | 怎么借 | 本地 / AMD 适配 | 判定 |
|---|------|----------|--------|-----------------|------|
| ① | 部署配置自动化（算 `--jinja` / ctx / LoRA 路由 / 启动参数） | llama-swap `cmd`+`macros` 思路；ollama Modelfile；公开 VRAM 公式（craftrigs） | 借公开公式：权重 + KV + overhead = 显存；按 48GB 反推 ctx / 层数生成启动命令 | 单基座 + 多 LoRA，不需 llama-swap 本体 | **造（轻，`capacity.py`）+ 借公式** |
| ② | 可观测（探活、首 token、思考耗时、KV、LoRA 命中） | **llama.cpp 原生** `/v1/chat/completions` 返回 `timings`（prompt_ms / predicted_ms / per_second）；`--metrics`→`/metrics`；`/slots` 看并发 + KV；`GET /lora-adapters` 只能看**全局**状态，不能单独证明某个请求命中；**仓库已有** `core/metrics.py`（`RunMetrics`/`CallRecord` 带 prefill/decode/KV 命中率/by_adapter），但它是单次运行内存统计且非线程安全；**OpenLIT**（AMD GPU 增强项）；LiteLLM / agentgateway 请求级日志 | v1：`RouteDecision` + switch 响应 + 原生 `timings` 组成 `RequestEvent`，落 JSONL/SQLite，Gradio 展示；增强：OpenLIT + OTel 汇聚 | OpenLIT 的 AMD 能力先做实机验证；v1 不依赖 | **v1 借原生/已有字段，新增持久化事件和线程安全汇聚** |
| ③ | 容量规划（48GB 算 ctx 上限） | craftrigs VRAM 计算器（公式公开）；llama.cpp `/slots` + `--verbose` 实际分配校验 | 把公式写成模块，启动校验实际分配是否爆显存 | W7900=48GB；Qwen3.6-27B Q4 ~17GB，ctx 余量大 | **造（小模块）+ 借公式** |
| ④ | 推理调度（非 agentic 关 thinking 换快 ack） | Qwen3 的 `enable_thinking` / llama.cpp thinking 控制；`--reasoning-budget N` 是进程级上限 | v1 先做请求级 thinking 开/关 + 固定进程上限；不要假设已设置 CLI 上限时还能任意覆盖请求级预算；动态预算列为后续兼容性实验 | Qwen3.6 原生能力需按当前构建实测 | **先做开关，预算调度后做** |
| ⑤ | 可靠性（进程守护 + 启动校验） | systemd；docker `restart:unless-stopped`；或中继自身 supervision | 单进程常驻，健康检查 `/metrics` + 自动重启；启动校验 model loaded 日志 | 单 llama-server，比 llama-swap managed 稳 | **造（几行）或借 systemd** |

---

## 4. E2E 优化愿景逐项映射

你 E2E 文档里"把优化叙事扩成整个本地 agent 栈在 Radeon 上的优化"——多数能借：

| 愿景项 | 现状 | 可借项目 | 判定 |
|--------|------|----------|------|
| prefill 经济学 | 想分开计量 prefill / decode | llama.cpp native `timings` 天然把 `prompt_ms`(prefill) 与 `predicted_ms`(decode) 拆开；`core/metrics.py` 已聚合 `prefill_pct`/`decode_pct`/`unaccounted_s` | **直接借（已有基建）** |
| 调用预算制（call budget） | 想按 session 限 token | LiteLLM virtual keys + budgets；或中继自写计数（`RunMetrics` 已累加 token） | **轻造 / 借子集** |
| 证据卡式记忆 | 产品核心（带行级引用的证据） | 无直接对应；`verifiable-rag` 的 "claim → source span" 结构可借鉴 | **造（你的差异化）** |
| GBNF 约束解码 | 想约束证据输出格式 | **llama.cpp 原生 GBNF + `json.gbnf` + xgrammar**（编译状态机，开销 5–15%）；`MoLLlamaCpp.chat()` 已支持 `grammar`/`response_format` 降级 | **直接借，成熟低风险** |
| 引用幻觉校验器 | 想校验答案是否真有证据支撑 | **LongTracer / verifiable-rag / RagShield / FlashCheck**——本地、NLI、确定性、零额外 LLM 调用；verifiable-rag 带 sentence-level citation + calibrated refusal + audit HTML | **直接借，最成熟借入点之一** |
| thinking 预算 | 想按难度调思考深度 | v1 先做开关和固定上限；动态请求级预算需按当前 llama.cpp 构建验证 | **后做** |

---

## 5. 推荐落地路径（按 GPT 复审重排）

> 初稿的 Phase 顺序（先弃 llama-swap → 上 OpenLIT → 配 Grafana）被 GPT 判为"不能直接实施"。重排如下，先打通中继与正确性，再谈重型观测。

- **Phase 0（正确性 + 真中继，先做）**
  1. 建**真正的 ScrewShell `/v1` 中继**（薄 HTTP 服务，非 llama-swap）：透传 chat/completion、tools、SSE；注入 auth/request_id/run_id；UI、opencode、pi 都只连这个入口。下游直连本机 llama-server，原始 `/lora-adapters` 不对外开放。
  2. 新增 `InferenceCoordinator`：统一维护全局 LoRA 状态、单请求队列、切换锁和流式清理；执行“RouteDecision → 全局切换 → 模型请求 → 释放锁”。从 `chat()` 删除请求级 `payload["lora"]`，v1 只用全局 D 路径，禁止 C+D 混用。
  3. 先让自研网页 Agent 复用同一个 Coordinator；不把 `consult expert` 作为 v1 必需功能。opencode/pi 仍是普通 OpenAI 客户端，每轮请求由中继重新路由；不得直连 :8080 或 llama-swap peers。
  4. 加入最小验收：两个不同 LoRA 连续请求不串专家；SSE `[DONE]`/断开/超时都释放锁；队列满返回明确 429/超时；tools、`response_format`、grammar 不被中继破坏。
- **Phase 1（观测 v1，原生 + 已有）**：开 `--metrics`；复用 `core/metrics.py` 的字段计算，但新增线程安全的 `RequestEvent`（包含 route、adapter、switch、TTFT、timings、KV、thinking、error、run_id）并落 JSONL/SQLite；在**现有 Gradio 面板**渲染。**不**上 OpenLIT/OTel。
- **Phase 2（配置自动化 + 容量规划）**：写 `capacity.py`，按 48GB 自动算 ctx/层数生成启动命令；启动读 `--verbose` 校验实际分配。运行层接管启动/重启。
- **Phase 3（持续调优闭环 = 方向 2）**：在面板做"A/B 前 vs 后"对比（如关 thinking 的 ack 提升、换帽 KV 收益），体感差 → 定位哪层 → 改运行层配置 → 下一轮验证。调优变更必须能记录配置版本并回滚。
- **Phase 4（增强项，指标稳定后再上）**：先做 §1.5 的 S0/S1 多 slot 真机实验；通过后再考虑专家子代理；再考虑并发 LoRA（多实例或接受 C 路径 KV 损失）、OpenLIT（AMD GPU 指标）+ OTel + Grafana、证据校验器、GBNF 结构化证据输出和证据卡式记忆。

---

## 6. 避坑：不要借的 / 不要急着上的

1. **别为"网关"硬上 LiteLLM 全套**（100+ provider、Redis、Postgres、成本追踪）——单本地后端只用其"虚拟 key + 请求日志"子集；**agentgateway** 更轻，或直接自建薄中继（§5 Phase 0）。
2. **别继续用 llama-swap 做 MoL**（错原语 + peers 不暴露 `/lora-adapters` G3）。managed-mode 流式断流、peers 不暴露切专家端点，两条路都死。
3. **v1 别上 OpenLIT + OTel + ClickHouse + Grafana**——对单机 W7900 过重。原生 `timings` + `core/metrics.py` + Gradio 面板先跑通，指标稳定再接。
4. **OpenWebUI Analytics 不够深**——只看 message/token，看不到 prefill/decode/KV/思考耗时；要么配 Grafana，要么用自建面板。
5. **绝对不要混用两条 LoRA 切换路径**（§1.2）——会触发 P0 静默失效，且 HTTP 层无任何错误信号。
6. **AMD 是特殊约束**：多数可观测工具 NVIDIA-first；OpenLIT 是当前候选之一，但必须在 W7900/ROCm 上实测。它属于增强项，v1 不依赖。
7. **不要把原始 `/lora-adapters` 暴露给外部前端**——它是全局控制端点，必须由 `InferenceCoordinator` 私有调用；否则任何客户端都能绕过队列篡改全局 LoRA。
8. **不要把 `RunMetrics` 直接当公共指标库**——它当前是单次运行、非线程安全的内存累加器；公共中继要写 `RequestEvent` 和持久化层。

---

## 7. 参考项目清单（附调研要点）

| 项目 | 类型 | 与第 2 层的关系 | 备注 |
|------|------|----------------|------|
| **llama.cpp（原生能力）** | 推理引擎 | 信号源：`-metrics`/`/metrics`、`/v1/chat/completions` timings、`/slots`、`/lora-adapters`（全局）、请求体 `lora`（请求级）、`--reasoning-budget`、GBNF | 基座，零成本借 |
| **OpenLIT** | 可观测（OTel） | AMD Radeon GPU 指标（rocm-smi）+ 请求级；ClickHouse 自托管 | 当前候选，需在 W7900/ROCm 实测；留增强项 |
| **LiteLLM** | AI 网关 | 虚拟 key / 用量 / 路由回退 | 云导向偏重，单本地后端只用子集 |
| **agentgateway** | AI 网关 | 更轻，front OpenWebUI + auth/audit/rate-limit | 比 LiteLLM 贴，但自建薄中继更可控 |
| **Langfuse / Phoenix / Helicone** | 可观测后端 | trace/eval/面板；本地可自托管 | 与 OTel 配合做"体感"层，增强项 |
| **xgrammar** | 约束解码 | 编译状态机，5–15% 开销 | 与 llama.cpp GBNF 互补 |
| **LongTracer / verifiable-rag / RagShield / FlashCheck** | 引用/幻觉校验 | 本地、NLI、确定性、零额外 LLM 调用 | verifiable-rag 带 sentence-level citation + audit HTML |
| **OpenWebUI** | 前端 + Analytics | 方向 2 的 UI 参照；Admin Analytics 是 token/message 级 | 深度指标不够 |
| **craftrigs VRAM Calculator** | 容量公式 | 权重 + KV + overhead 显存公式 | 公式公开，写成 `capacity.py` |
| **llama-swap** | 本地 alias/peering | **MoL 场景弃用**（错原语 + peers 不暴露 `/lora-adapters`） | managed-mode 流式断流已知坑 |

---

## 8. 本地约束与风险

- **AMD Radeon W7900 = 48GB GDDR6**：Qwen3.6-27B(dense) Q4 权重 ~17GB，KV cache 随 ctx 增长；48GB 给大 ctx 留足余量。容量公式：`总显存 = 参数量 × 量化GB/10亿 × 1.05 + 层数 × 0.00075 × ctx(K) + 3GB(overhead)`。
- **ROCm 生态弱于 CUDA**：可观测/容器化多 NVIDIA-first；OpenLIT 的 Radeon 指标能力需要在本机验证。选型的硬约束，但 v1 不依赖。
- **单基座 + 多 LoRA 是正确抽象**：别把"多专家"理解成"多模型"，否则重蹈进程替换的坑。
- **`/lora-adapters` 是全局端点（G3）**：llama-swap peers 不暴露它（返 404），所以 MoL 切专家必须经自建中继的私有下游连接或直连 :8080；外部客户端不能直接调用。中继方案见 §2/§5 Phase 0。
- **KV 复用的前提**：固定前缀 + 尾部追加（报告 E 组：1347/1660 命中）。滑窗导致前缀每轮变 → 命中掉；"稳定窗口 + 变动后置"方向正确。
- **`RunMetrics` 的适用范围**：现有实现服务于单次 `Orchestrator.run()`，明确非线程安全；统一多入口观测必须由中继生成 `RequestEvent`，再由持久化汇聚层统计。

---

## 9. 给评审者（GPT / 同事）的开放问题

1. **S0/S1 多 slot 实验是否成立**：`POST /lora-adapters` 后 llama.cpp 是否真**不清空其他 slot 的 KV**，以及切换期间 S0 是否必须完全停止解码，需跑 §1.5 的长上下文真机测试。未通过前，v1 保持全局单请求队列。
2. **外部请求的队列语义**：opencode/pi 的多个请求是等待、429 还是超时取消？需要固定公共协议，并确保 SSE 断开后 Coordinator 一定释放锁。
3. **Coordinator 的唯一 owner**：中继只做协议和 RouteDecision，Coordinator 统一持有全局 LoRA、队列和锁；不能让 Orchestrator、HTTP 中继、llama-swap 各自维护一份状态。
4. OpenLIT 的 ClickHouse 自托管对单机是否过重？是否有更轻的 OTel → 文件/SQLite 方案？（v1 已决定走原生 + SQLite，此问仅关乎增强项。）
5. 引用校验器（NLI 模型）在 W7900 上是否与主推理争抢显存？能否同卡小模型？
6. 证据卡式记忆的数据结构，是否复用 verifiable-rag 的 "claim → source span"，还是自定义？

---

## 10. 修订记录

- **2026-08-03**：初稿。核心结论"弃 llama-swap managed → 用 `/lora-adapters`"方向正确，但**误把 `POST /lora-adapters` 当成按请求隔离的切换原语**，并误写"网关你已有""v1 上 OpenLIT/OTel"。
- **2026-08-04（GPT 复审）**：指出四大问题——① 全局 vs 请求级切换写反；②"网关已有"不实（当前仅 llama-swap peers + 客户端薄适配，且 peers 不暴露 `/lora-adapters`）；③ v1 不应上重型观测栈；④ 三平面边界需显式。本修订已逐条采纳，并新增 §1.2/§1.3/§2，重排 §5 落地路径为 6 步。同步核实：当前 `mol_engine_llamacpp.py` 混用两路径 = 实测 P0 静默失效 bug，列为 Phase 0 待修。
- **2026-08-04（本轮复审）**：保留“专家子代理”作为后续实验，不再把它当作 v1 已证实方案；v1 改为 `InferenceCoordinator` 统一全局 LoRA、单请求队列和流式清理。补充外部 opencode/pi 的普通请求路径、`RunMetrics` 非线程安全限制、原始 `/lora-adapters` 不对外开放和 thinking 预算的兼容性边界。
