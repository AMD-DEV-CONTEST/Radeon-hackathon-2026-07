# Track 2 API Harness 完整对比报告

生成时间：2026-07-21T03:34:39.605910+08:00  
实验状态：**已完成记录（含 8 个基础设施未完成单元）**

## 结论

在这次固定 API 条件下，当前排名第一的是 **`mini-original`**。

最终分数是完整隐藏测试通过率，不是 agent 的 `completed`、补丁可应用率或 verifier 接受率。
在并列时，仅用更低 token、再用更低耗时作为工程排序；并列并不代表统计上存在胜负。
本表的严格 E2E 分数把 API 未完成计为端到端失败；`完整任务` 用于区分 harness 能力失败和基础设施缺失。

**本轮推荐：API 阶段使用 `mini-original`。** 它得到最高严格分数 4/10（40%），且 10/10 任务完整、
无 API 错误。Aider 的严格分数为 3/10（30%），但只有 3/10 任务完整，无法据此估计纯能力；
原始未校正主轮中 Aider 为 4/10，与 mini-original 持平，但存在大量 403/超时。

## 最终评分

| Harness | 完整任务 | 通过/任务 | 严格 E2E 分数 | Wilson 95% CI | 总语义调用 | tokens/有回复题 | 平均耗时 | API 错误题 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| mini-original | 10/10 | 4/10 | 40.0% | 16.8%–68.7% | 40 | 8109 | 24.7s | 0 |
| aider-whole | 3/10 | 3/10 | 30.0% | 10.8%–60.3% | 6 | 3865 | 197.8s | 7 |
| mini-json-verifier | 10/10 | 1/10 | 10.0% | 1.8%–40.4% | 38 | 7648 | 39.2s | 0 |
| mini-repograph | 9/10 | 1/10 | 10.0% | 1.8%–40.4% | 37 | 8859 | 107.4s | 2 |
| mini-aider-repomap | 10/10 | 0/10 | 0.0% | 0.0%–27.8% | 40 | 9433 | 56.7s | 0 |

`tokens/有回复题` 只在至少取得一次模型回复的任务上取平均，避免 0-call 基础设施失败把成本虚假压低。

## 逐题结果

| 任务 | mini-original | mini-json-verifier | mini-aider-repomap | mini-repograph | aider-whole |
|---|---:|---:|---:|---:|---:|
| dot-dsl | ❌ | ❌ | ❌ | ❌ | ⚠️ infra |
| beer-song | ✅ | ❌ | ❌ | ❌ | ✅ |
| pig-latin | ✅ | ✅ | ❌ | ✅ | ⚠️ infra |
| zipper | ❌ | ❌ | ❌ | ❌ | ⚠️ infra |
| variable-length-quantity | ✅ | ❌ | ❌ | ❌ | ⚠️ infra |
| bowling | ❌ | ❌ | ❌ | ⚠️ infra | ⚠️ infra |
| robot-name | ❌ | ❌ | ❌ | ❌ | ✅ |
| bottle-song | ✅ | ❌ | ❌ | ❌ | ✅ |
| react | ❌ | ❌ | ❌ | ❌ | ⚠️ infra |
| transpose | ❌ | ❌ | ❌ | ❌ | ⚠️ infra |

图例：✅ 隐藏测试通过；❌ 已完整运行但未通过；⚠️ infra 在用完语义调用预算前耗尽 transport retry。

## 协议层与 Verifier 诊断

| Harness | JSON 合法 | patch apply | verifier 接受 | 假接受 | 假拒绝 | 最终补丁率 |
|---|---:|---:|---:|---:|---:|---:|
| mini-original | — | — | — | 0 | 0 | 80.0% |
| mini-json-verifier | 36/38 (94.7%) | 2/22 (9.1%) | 1/10 | 1 | 1 | 20.0% |
| mini-aider-repomap | 40/40 (100.0%) | 1/33 (3.0%) | 1/10 | 1 | 0 | 10.0% |
| mini-repograph | 36/37 (97.3%) | 4/27 (14.8%) | 3/10 | 2 | 0 | 40.0% |
| aider-whole | — | — | — | 0 | 0 | 40.0% |

关键现象：JSON 合法率很高（94.7%–100%），但 patch apply 仅 3.0%–14.8%。瓶颈不是“输出不是 JSON”，
而是 JSON `patch` 字符串中的 unified diff 仍然不合法。V1 还出现假接受和假拒绝，
所以它只能作为补丁结构门槛，不能替代 targeted/hidden tests。

## 配对统计

- `mini-original` 对 `mini-json-verifier`：最佳独赢 3 题，对方独赢 0 题，McNemar 精确检验 p=0.2500。
- `mini-original` 对 `mini-aider-repomap`：最佳独赢 4 题，对方独赢 0 题，McNemar 精确检验 p=0.1250。
- `mini-original` 对 `mini-repograph`：存在基础设施未完成任务，不计算 McNemar，避免把缺失响应当作模型失败。
- `mini-original` 对 `aider-whole`：存在基础设施未完成任务，不计算 McNemar，避免把缺失响应当作模型失败。

样本量较小，Wilson 区间会较宽；McNemar p 值大于 0.05 时，不应声称差异具有统计显著性。

## 实验设计

- Benchmark：Aider 官方 Polyglot Benchmark 的固定 Python 子集，seed 42；题目列表固化在 `manifest.json`。
- 模型：`Qwen3.6-35B-A3B`；API 主机：`developer.amd.com.cn`。
- 公平预算：每个 harness 每题最多 4 次语义模型调用；每次语义调用最多
  4 次 transport 尝试，网络/403/超时不消耗语义预算；温度由同一模型/服务端契约决定。
- 模型只看到官方自然语言说明与待修改源码。测试文件在候选生成后才复制进隔离环境。
- 判分：完整 `unittest` 测试套件在 `--network none`、只读挂载的 Docker 容器中执行。
- 每个任务和 harness 都从相同原始源码重新初始化，避免补丁污染后续实验。
- API key 从环境变量或 macOS Keychain 读取，不写入代码、命令行结果或报告。

## Harness 定义

- `mini-original`：原始 mini-SWE 控制器，C0/J0/V0。
- `mini-json-verifier`：mini-SWE + 请求 vLLM-style `structured_outputs` 的 J3 JSON action + V1
  确定性 verifier；API 接受请求不等于能证明服务端执行了 grammar constrained decoding。
- `mini-aider-repomap`：上一项再单独加入 Aider Repo Map 初始上下文。
- `mini-repograph`：上一项改为 RepoGraph 图上下文；与 Repo Map 不同时开启。
- `aider-whole`：独立 Aider harness，官方建议的 unknown-model `whole` 编辑格式；失败时可在第二次调用得到测试反馈。
  因此这是完整 harness 的端到端比较，不是只替换 controller prompt 的纯消融。

## 可复现版本

- 本项目代码：工作区当前版本（原始实验文件未强制提交）。
- Polyglot commit：`7e0611e77b54e2dea774cdc0aa00cf9f7ed6144f`。
- Aider commit：`5dc9490bb35f9729ef2c95d00a19ccd30c26339c`。
- RepoGraph commit：`6c3977d87845993bf2c0359b4ac752278d7f3c45`。
- transport-aware 最终记录：`results.jsonl`；汇总：`summary.json`；补丁：`patches/`。
- 首轮 50 单元快照：`results.raw.jsonl`、`summary.raw.json`、`report.raw.zh-CN.md`、`patches.raw/`。

## 解释与 Track 2 建议

这个 benchmark 能客观比较“小模型能否通过 harness 把自然语言需求变成可执行代码”，尤其适合测试
JSON action、编辑协议和测试反馈。但 Python 子集多数是单文件题，因此它对 Repo Map/RepoGraph 的仓库级定位收益
并不敏感。若上下文模块在此处没有提升，不能推出它在 SWE-bench 多文件仓库中无效。

此前 SWE-bench Lite 30 题实验中，`C0-J3-V1` 有 3/30 个确定性 verifier 接受，而原始
`C0-J0-V0` 为 0/30；该数字只是“候选补丁通过廉价门槛”，不是 SWE-bench 官方 resolved 分数，不能与本报告
的隐藏测试分数混合。最终参赛架构应优先采用本报告中测试通过率最高的控制/编辑 harness，再在多文件
SWE-bench 子集上单独复验 Repo Map 与 RepoGraph。

本轮的参赛落地建议是：先把 `mini-original` 作为 AMD API 开发基线；不要直接合并 J3+V1。
先将编辑原语从“JSON 内嵌 unified diff”改为 whole-file/search-replace 或确定性补丁构造，
再独立测 V2 targeted tests。Aider 对照组应迁到 AMD Cloud `localhost` vLLM 后重跑；
它在能取得稳定回复时用更少 token 解决了与 mini 不同的任务，仍有组合价值。

## 局限

1. 固定子集规模有限，置信区间宽；完整 34 题 Python 或多语言 225 题才适合 leaderboard 级结论。
2. 这是 API-only 阶段，不能测 AMD Cloud 本地 vLLM 的 tokens/s、TTFT、显存或 xgrammar 解码开销。
3. Aider/LiteLLM 路径在本轮出现大量 403 与超时；严格分数可代表当时的 API 端到端可用性，
   但不能单独代表 Aider 的纯代码能力。Aider 的 token 数来自 CLI usage 输出，仍应以 API 侧账单复核。
4. 单文件 Exercism 题不能替代 SWE-bench 的大型仓库定位能力评测。
5. API 未提供可验证的随机 seed 契约；固定温度、任务和预算不能完全消除服务端非确定性。
