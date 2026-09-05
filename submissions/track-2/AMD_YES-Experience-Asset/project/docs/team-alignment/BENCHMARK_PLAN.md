# Experience Asset P0 — Benchmark 与 ROCm 调优计划

## 目的

这份计划把“本地运行”“性能更快”“Agent 能把任务做完”变成可复查的证据。
它服务于三件事：比赛评分、工程回归、优化决策。正式赛事规则优先于本文件；
演讲截图中的指标被纳入为团队的最低证据标准。

本文件是团队可见、可复现的性能与公开符合性 Benchmark，不包含质量负责人的
隐藏测试代码、私有 Fixture 变体、Gold Answer、精确质量权重或通过分数线。
公开 Benchmark 用于共同优化和比赛举证；隐藏盲测用于防止业务实现针对答案
过拟合，两者不得混为一套。

2026-08-03 批准的可执行工程方案见
[`../kinnyu/SERVING_BENCHMARK_ENGINEERING_PLAN.md`](../kinnyu/SERVING_BENCHMARK_ENGINEERING_PLAN.md)。
该方案冻结两套不同层级的基线：`S0` 用于先行筛选 W7900 模型服务配置，`A0`
用于完整 Agent 的最终业务选择。服务层胜出不等于产品层晋级。

## 先分清三种 Benchmark

| 层级 | 回答的问题 | 不能被什么替代 |
|---|---|---|
| A. 模型服务 | W7900/ROCm/vLLM 本身有多快、多稳、占多少显存？ | 不能用一次完整 Agent 总耗时推断 |
| B. Agent 任务 | 从用户目标到合格交付，系统是否做完、是否恢复错误？ | 不能只报 Token/s |
| C. 打磨体验 | 用户多快得到价值、付出多少澄清成本、是否感到可控？ | 不能只报后端延迟 |

优化必须同时查看三层。A 层变快但 B 层完成率下降，或 B 层减少问题却让 C 层
产生更多错误和返工，都不能直接称为有效优化。

## 冻结测试集

基于同一个匿名办公椅公开案例，建立七个可版本化的文本夹具：

| Fixture | 用途 | 预期重点 |
|---|---|---|
| `chair_public_complete` | 标准闭环 | 五阶段完成；四条路由可用，客户路由不适用 |
| `chair_incomplete` | 缺失信息 | 提问或降级，不能补写事实 |
| `chair_conflicting` | 信息冲突 | 显式冲突并请求确认 |
| `chair_privacy_risk` | 隐私/表述风险 | 公开导出被审查门阻塞 |
| `chair_route_ineligible` | 路由资格 | 给出不可生成的具体原因 |
| `chair_correction` | 用户纠错 | 修正资产并只重算受影响结果 |
| `chair_resume` | 崩溃/跨会话恢复 | 从已保存阶段继续，历史版本仍在 |

夹具与期望结果必须进入 Git；真实私密用户数据、原始私密 Trace 和模型权重不得
进入 Git。

这里的“期望结果”只指组员应当知道的公开业务不变量和示例。质量负责人应在
仓库外保留未公开的文本变体、Gold 标注、对抗样例和评分聚合；不能把完整隐藏
套件放入团队 Agent 上下文。

## 每次运行必须记录的 Manifest

建议每次运行产生 `manifest.json`、`runs.jsonl` 和 `summary.json`。

```json
{
  "run_group_id": "...",
  "timestamp_utc": "...",
  "git_commit": "...",
  "fixture_id": "chair_public_complete",
  "fixture_version": "...",
  "workflow_version": "...",
  "prompt_schema_version": "...",
  "hardware": {
    "gpu": "AMD Radeon PRO W7900",
    "vram_gib": 48,
    "cpu_quota": "...",
    "memory_quota_gib": "..."
  },
  "software": {
    "os_container": "...",
    "driver": "...",
    "rocm": "...",
    "torch": "...",
    "hip": "...",
    "vllm": "..."
  },
  "model": {
    "repository": "...",
    "revision": "...",
    "license": "...",
    "dtype": "bf16",
    "quantization": "none"
  },
  "serving": {
    "context_length": 8192,
    "max_output_tokens": "...",
    "gpu_memory_utilization": "...",
    "max_num_seqs": "...",
    "attention_backend": "default",
    "optimization_level": "...",
    "other_args": []
  },
  "measurement": {
    "warmup_runs": "...",
    "measured_runs": "...",
    "concurrency": "...",
    "temperature": "...",
    "seed": "..."
  }
}
```

模型仓库还应记录来源、固定 revision 或文件哈希和许可证。若某个字段不适用，
明确写 `null` 与原因，不能默默省略关键条件。

## 指标与定义

### A. 模型服务指标

| 指标 | 定义 | 记录方式 |
|---|---|---|
| TTFT | 请求发出到首个输出 Token 的时间 | 每次请求，毫秒 |
| TPOT | 首 Token 后每个输出 Token 的平均时间 | 每次请求，毫秒/Token |
| ITL | 相邻输出 Token 的间隔分布 | 每次流式请求，毫秒及 p95 |
| Output throughput | 解码输出 Token 数 / 解码时间 | tokens/s；注明 tokenizer |
| Request latency | 请求到完整响应结束 | 毫秒 |
| Peak VRAM | 同模型、上下文与并发条件下显存峰值 | `amd-smi`/采样器；GiB |
| Error rate | 超时、OOM、服务端错误占比 | 分类型计数 |
| Concurrency behavior | 不同并发下的吞吐与尾延迟 | 记录 concurrency 和 p95 |
| Goodput | 同时满足质量门和 TTFT/TPOT/E2EL SLO 的请求比例 | 分子/分母；SLO 来源 |

若能可靠拆分，可另报 prefill/input throughput；不要把它和 output tokens/s 混为
一个数字。

### B. Agent 任务指标

| 指标 | 定义 |
|---|---|
| End-to-end latency | 从接受任务到交付、请求调整或安全停止 |
| Task completion rate | 多次运行中满足验收条件的比例 |
| Terminal state | `delivered`、`needs_input`、`safe_stop`、`failed` 等 |
| Model-call count | 每次完整任务的模型调用数 |
| Tool success/recovery | 工具成功、参数拒绝、超时、重试与恢复 |
| Evidence coverage | 需要支持的关键陈述中有来源/状态的比例 |
| Unsupported-claim rate | 被输出为事实但缺少支持的陈述比例 |
| Route/privacy correctness | 与冻结期望策略一致的比例 |
| Retrieval-phase correctness | M4 就绪前跨资产调用拒绝、确认前详细读取拒绝、确认后只读选中资产、无命中可见且当前事实不被历史内容静默改变 |

任务完成必须按验收条件评分，不能把“API 返回了 200”当作任务成功。

### C. 打磨体验指标

| 指标 | 目的 |
|---|---|
| Time to first useful artifact | 检验用户是否很快获得 `Experience Brief v0.1` |
| Question burden | 每次资产的问题总数、轮数和每轮问题数 |
| Milestone completion | 五阶段完成、暂停、放弃和恢复分布 |
| Correction recovery | 用户纠错后恢复正确状态和重算结果所需步骤/时间 |
| Route readiness | 最终 ready/blocked/ineligible 的数量与原因 |
| Clarity / progress / control / trust | 简短量表或演示用户反馈，不宣称心理学效果 |

## 双基线、Profile 命名与比较规则

为了避免把服务速度和产品价值混为一谈，名称固定如下：

| Checkpoint | 固定名称 | 含义 |
|---|---|---|
| E1-A3 | `E1 Compatibility Gate` | BF16 14B/W7900/ROCm/vLLM 必过兼容门；不是性能基线 |
| E2 | `Serving Reference S1` / `Vertical Slice V1` | 已保留的早期服务与业务竖切证据 |
| Stage 1 | `S0 Serving Baseline` | 从 known-good S1 冻结的服务基线，分数定义为 100 |
| Stage 1 | `P*` / `Q*` / `C* Serving Candidate` | 预声明的参数、量化、后端或组合候选；只能晋级 Stage 2 |
| Stage 2 | `A0 Application Baseline` | 首个冻结完整 Agent、业务任务和测量方法的产品基线 |
| Stage 2 | `A1..A3 Application Candidate` | Stage 1 Top 3 在同一完整应用中的候选 |

`S0` 与 `A0` 是不同层级的比较锚点，不能互相替代。Stage 1 可以在完整 UI/Agent
结束前正式筛选服务配置，但结果只能是“服务层晋级”；最终提交配置必须经过
Stage 2 的完整业务、安全与 Agent 闭环验证。

每次正式比较都必须有 `baseline_profile` 和 `candidate_profile`：

- 使用同一任务、输入版本、模型、量化、上下文、生成参数和测量方法；
- 先进行预热，再执行多次测量；
- 保存全部成功和失败记录；
- 延迟报告样本数、mean、median 和 p95；完成率报告分子/分母；
- 同时给出质量、安全和 UX 的变化；
- 禁止只选最好的一次，也禁止在不同上下文或输出长度下直接对比 Token/s；
- 任何配置变化都需要单独命名，便于回滚和复现。

Stage 1 的 exact 工作负载、样本量、硬门槛、计分公式、Top 3 规则和 Builder /
Scorer 分离均由已批准的工程方案冻结。演示报告必须明确样本量，不能把小样本
包装成统计结论。

Stage 1 把相同的 W1–W4 形状拆成两条不可混算的通道：固定 ISL/OSL 的
`performance lane` 负责 TTFT/TPOT/ITL/E2EL/TPS/VRAM；自然停止的
`business-quality lane` 负责结构、Tool Call、事实、边界和可用性。自然回答长度
不同，不得用其原始总延迟直接宣称服务配置更快。快速筛选只运行确定性质量检查；
外部 Judge 仅用于确认阶段的公开/合成/去标识输出。

排名 v1 固定为同一个已缓存 BF16 14B 模型的八个单因素 Profile：`S0`、prefix
cache、`max_num_seqs=2`、显存利用率 0.88、MBT 8192、MBT 16384、
`ROCM_ATTN` 和 `TRITON_ATTN`。最多四个单因素进入确认；若至少两个正交因素在
确认阶段保持质量/可靠性且其目标指标提升至少 5%，按冻结规则最多组合一个
`C1` 并完整复测。最终三个经过完整确认的 Profile 进入 Stage 2。
AWQ/GPTQ 不在 deadline-critical 排名路径；若精确 GGUF 快照、许可证和当前 wheel
支持均已确认，可在总计三小时的独立时间盒内做 `Q0-gguf` 兼容性探针，但不能
阻塞 BF16 主线。

### Stage 1 公开评分摘要

只有先通过 locality、加载/重启/回滚、8K、稳定性、结构化输出、语义质量、
unsupported fact、显存余量和完整证据硬门槛的候选才计算分数。`S0=100`；低值
更优指标使用 `100 * S0 / Candidate`，高值更优指标使用
`100 * Candidate / S0`，单项上限 150。

| Stage 1 指标 | 权重 |
|---|---:|
| 质量保持 | 30% |
| p95 TTFT | 20% |
| p95 TPOT | 10% |
| 中位完整请求延迟 | 10% |
| Output throughput | 10% |
| Peak VRAM | 10% |
| Reliability + Goodput | 10% |

W1–W4 业务形状按 `35/30/25/10` 聚合；并发 1 / 2 按 `70/30` 聚合；并发 4 只
用于压力与安全降级证据，不给排名加分。得分不能覆盖硬门槛。

`Goodput` 的默认 SLO 在独立 S0 运行后、查看 Candidate 得分前冻结：TTFT、TPOT
和 E2EL 各自不得超过 `1.10 × S0 p95`，并且该请求必须通过质量门。启动时间、
预热收敛轮数、cache 状态和 warning/preemption 只做报告与故障诊断，不单独加权。

### Stage 2 公开评分摘要

Stage 2 在同一完整应用、Runtime、数据种子、Prompt 和业务夹具上，以 `A0=100`
评估 Top 3：Experience Asset 质量 35%、完成与恢复 20%、首个产物与问题负担
15%、端到端延迟 15%、纠错/暂停/恢复 10%、显存与模型调用效率 5%。M1–M5、
RAG 阶段门、权限/隐私、事实支持、有效终态和本地推理都是不可加权抵消的硬门。

`A0` 固定为完整 Agent + `S0`，若 S0 也在 Top 3 中不重复计数。每个唯一应用
Profile 先用七类公开 Fixture 各跑一次资格矩阵；通过者再对 complete、correction、
resume 各增加两次干净重复，因此每个通过者有 13 条测量全链路。每次使用独立
数据库种子和产物目录。A0 首尾各做一次 bookend；TTFA/E2E 漂移超过 10% 或确定性
结果变化时，时间比较作废并排查。所有安全/权限/RAG/隐私硬门必须 100% 通过，
语义质量不得低于 A0 的 95%。业务小样本报告中位数、范围和分子/分母，不伪报 p95。

## Benchmark 证据生命周期

每次 Benchmark 都是
[`spec/EVIDENCE_RETENTION.md`](../../spec/EVIDENCE_RETENTION.md) 定义的工程证据
checkpoint。运行开始前创建 `run_group_id` 和 Manifest；运行过程中保留成功与
失败记录；运行结束后生成不可静默覆盖的摘要，并关联准确的 commit SHA。

- E1-A3 保存真实 BF16 14B/W7900/ROCm 的 `E1 Compatibility Gate`，不宣传为
  性能 Baseline；
- E2 分别保存模型服务的 `Serving Reference S1` 和端到端业务的
  `Vertical Slice V1`；
- Stage 1 从 S1 冻结 `S0`，并为每个 `P*`/`Q*`/`C*` 服务候选保存预声明、
  workload/scorer hash、重复运行、全部失败、回滚与分项得分；
- Stage 2 保存不可变的完整 Agent `A0`，再为 Stage 1 Top 3 保存相同业务条件下
  的端到端硬门与得分；
- 服务层结果只能晋级到 Stage 2；只有 Stage 2 能生成最终配置建议；
- E9 从已接受的历史中汇总演示和提交证据，不重新挑选“最好的一次”。

门禁结论生成后，历史结果只允许通过新版本和 supersedes 链接修正。公开的小型
Manifest/摘要进入 Git；大型原始 JSONL、采样和日志留在 `/workspace`。最终报告
必须能从公开条件解释数字，而私有 QA 仍保持在共享仓库和共享 Pod 之外。

## ROCm 优化阶梯

### O0 — 本地证据

- `amd-smi`、`rocminfo`；
- PyTorch 报告 HIP 版本与 W7900 设备；
- vLLM 启动参数和加载日志；
- 应用到 `127.0.0.1` vLLM 的请求 Trace；
- 模型、数据和推理服务位于受控 Pod 的说明。

### O1 — BF16 兼容与参考运行

- 选择经当前 vLLM/ROCm/W7900 验证的模型；
- 固定 8K 等可控上下文和输出上限；
- 完成七个夹具的重复运行；
- 建立 E2 `Serving Reference S1`、`Vertical Slice V1`、known-good 配置和
  回滚命令；此阶段仍不称为正式 Baseline。

### O2 — 低风险探索

- context budget、max output；
- `gpu-memory-utilization`；
- `max-num-seqs`、batch/concurrency；
- warm-up、prefix caching；
- Prompt 裁剪、状态摘要、减少无意义模型调用；
- 对可并行且无依赖的工具进行受控并发。

### O3 — 兼容性敏感实验

- 量化（默认不在 deadline-critical 排名矩阵；当前只允许精确支持证据下的
  独立限时探针，且不得替代 E1-A3 BF16 兼容门，也不得未经 Stage 2 成为
  产品默认）；
- attention backend / FA2 类替换；
- vLLM optimization level；
- 特殊算子或源码构建。

O3 只有在精确版本组合有支持证据和回滚方案时才做。不要把 CUDA 教程或群友
配置直接当作 W7900/ROCm 可用方案。失败的兼容性实验也要记录环境和错误，
但不能占用主路径。

### O4 — 双层接受或回滚

Stage 1 只筛选服务候选。通过固定硬门后，按冻结分数选择最多三个进入 Stage 2；
它们不能直接替换应用默认配置。Stage 2 在 `A0` 的完整业务条件下重新检查任务
完成、证据质量、RAG/权限/隐私、纠错恢复、用户体验、延迟和资源效率。只有
Stage 2 的通过者可以进入最终推荐；若没有候选产生值得接受的质量安全收益，
保留 BF16 known-good 配置就是有效结论。

## Track 2 完整闭环录屏清单

最终演示至少展示一次：

1. 明确用户目标、私有材料、权限和验收标准；
2. M1–M4 只读取当前来源/同资产版本并形成可见计划，证明没有提前跨资产联想；
3. M4 知识卡片就绪后显示摘要候选，记录用户确认/拒绝，再只读取已确认资产的详细证据或显示无命中；
4. W7900 + ROCm 本地推理，并显示版本、TTFT、吞吐和显存证据；
5. 执行受控步骤，核对事实、来源、限制条件和错误恢复；
6. 达标后交付；不达标时请求补充、调整或安全停止；
7. 在同一任务/模型/上下文下展示 baseline 与 optimized 对比。

## 建议产物目录（工程阶段创建）

```text
benchmarks/
├── fixtures/                 # 可公开、可提交的冻结测试夹具
├── expected/                 # 团队可见的路由、证据、隐私和终态不变量
├── profiles/                 # S0/A0 baseline 与 Stage 1/2 candidate 配置
├── manifests/                # 可提交的无秘密运行条件
├── raw/                      # 原始结果；体积/隐私评估后决定是否提交
├── reports/                  # 汇总表、图、失败分析
└── README.md                 # 一键复现与指标定义
```

Radeon Cloud 的完整运行数据先放在
`/workspace/amd-track2-agent/benchmarks`。进入 Git 的只能是无秘密、无私密数据、
体积受控且对复现必要的夹具、配置和摘要。

私有 QA 不使用上述目录。它应由质量负责人保存在共享仓库之外；如需调用 W7900
服务，由本地 Runner 通过私有连接发起，并避免把隐藏 Payload 和评分逻辑写入
共享 Pod 日志。最终对评委展示的性能数字仍必须公开其测试条件，不能用“隐藏
测试”掩盖不可复现的性能声明。

## 设计与技术依据

- [vLLM performance optimization](https://docs.vllm.ai/en/stable/configuration/optimization/)
- [vLLM GPU installation, including ROCm wheels](https://docs.vllm.ai/en/latest/getting_started/installation/gpu/)
- [AMD ROCm vLLM inference documentation](https://rocm.docs.amd.com/projects/ai-ecosystem/en/latest/inference/vllm.html)
- [AMD Radeon release-specific limitations](https://rocm.docs.amd.com/projects/radeon-ryzen/en/docs-7.0.2/docs/limitations/limitationsrad.html)

最后一个链接记录的是特定 ROCm 版本的已知限制，不等于当前 7.2.1 环境存在
相同问题；它说明为什么版本、失败率和重复运行必须进入证据链。
