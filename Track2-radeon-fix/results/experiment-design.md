# Track 2 harness 重设计与复验报告（v1）

生成日期：2026-07-23

## 结论

历史上的“mini-SWE + Aider Repo Map 一个任务都没完成”不能用来证明 Repo Map 无效，旧实验同时存在配置混杂和 harness 基础设施缺陷。修复后得到的结论是：

1. 在 5 个 Polyglot Python 任务、2 次重复的轻量实验中，9 个基础设施完整的配对单元上，C0 通过 4 个、C1 通过 5 个；C0-only 胜 1 个，C1-only 胜 2 个，McNemar exact p=1.0。只有一个净成功差，不能声称 Repo Map 有统计显著收益。
2. 在正式 SWE-bench Lite 任务 `django__django-15781` 上，修复后的 C0 与 C1 均完成 12 次语义调用，但都没有生成补丁。官方 evaluator 将两者均分类为 `empty_patch`，不是 evaluator error。
3. C1 已把相关文件 `django/core/management/base.py` 放进实际可见上下文，但模型仍无法从检查阶段切换到编辑阶段。因此当前首要瓶颈是动作/编辑协议，不是代码定位。
4. API-only 的 J2 JSON 实验连续两次生成合法 JSON，但动作值为不在 schema 中的 `command`，而不是 `execute`；0/2 schema-valid。Prompt-only JSON 不能替代 vLLM/xgrammar 的 constrained decoding。
5. Aider whole 在该 AMD endpoint 上 3/3 任务均为 0 semantic calls，出现 403/timeout。关闭 URL 自动抓取后仍有 0-call timeout。这个结果只能判为 adapter/infrastructure incompatible，不能用于和 mini-SWE 排名。

当前可运行的主 harness 是 mini-SWE，但当前模型 + 自由 tool calling 的编辑可靠性不足。下一步应先在 AMD Cloud 本地 vLLM 上验证 J3 constrained JSON action，再继续 C1/C2 上下文消融。

## 被发现并修复的 harness 问题

### 1. 旧 Repo Map 对比不是单因素实验

旧的 `mini-original` 是 C0/J0/V0，而历史 `mini-aider-repomap` 是 C1/J3/V1，同时改变了上下文、输出协议和 verifier。现在使用：

- `mini-original`：C0/J0/V0；
- `mini-repomap`：C1/J0/V0；
- `mini-repograph-clean`：C2/J0/V0。

### 2. Aider comparator 曾获得隐藏测试反馈

旧 Aider runner 在候选生成过程中运行隐藏测试，并把输出返回给 Aider；mini-SWE 没有相同信息。现在所有 harness 都只能在最终候选冻结后运行一次隐藏测试，模型永远看不到测试名称和输出。

### 3. Repo Map 实际上下文被截断

Aider 在没有 chat files 时默认把 map budget 放大 8 倍。旧正式任务 map 为 57,338 字符，而 controller 只保留前 16,000 字符；关键文件位于第 27,123 字符，模型实际看不到。

修复后：

- 固定 `map_mul_no_files=1`；
- 固定 2,048-token map budget；
- 清除扫描进度 UI 噪声；
- map 为 6,681 字符；
- 关键文件位于第 3,087 字符，进入模型可见上下文。

### 4. partial clone 产生缺文件工作区

仓库缓存是 `blob:none` partial clone。旧 prepare 流程可能在 checkout 后留下 51 个已跟踪但未物化的文件。现在先用 `git archive` 强制缓存物化目标 commit 的全部 blob，并设置以下硬门槛：

- `git ls-files --deleted` 必须为空；
- `git status --short` 必须为空；
- 否则任务标记为 infrastructure failure，不启动模型。

### 5. `clone --shared` 破坏容器内 Git

旧工作区的 `.git/objects/info/alternates` 指向宿主机绝对路径。隔离容器只挂载任务工作区，无法访问该对象目录，导致容器内 `git diff` 返回 128，阶段门控和最终补丁捕获都失效。

现在改为从已物化缓存执行 self-contained depth-1 fetch。真实容器校准结果：

- alternates 文件不存在；
- `git diff --quiet` 返回 0；
- 目标文件存在；
- 工作区状态干净。

### 6. 小模型阶段切换只靠 prompt，实际无效

旧 controller 只在一半预算时用文字要求模型停止检查。Qwen3.6-35B-A3B 在 12 次调用中仍可全部用于 grep/cat/小实验。

现在增加确定性 inspection gate：当一半调用预算已经消耗且工作区仍无 diff 时，只读命令会返回 `INSPECTION_BUDGET_EXHAUSTED`；产生 diff 后重新允许检查和测试。正式 v5 中 C0/C1 各触发 6 次拒绝，证明门控在真实容器生效；但模型仍重复只读命令，说明需要更可靠的 edit action 协议。

### 7. SWE-bench 路径别名

模型经常使用训练轨迹中的 `/testbed`。runner 现在把该别名限制性映射到当前仓库 `.`，不会扩大文件系统权限；容器仍然使用 `--network none` 且只挂载任务工作区。

## 有效实验结果

### A. Polyglot C0/C1 轻量配对实验

结果目录：`runs/repomap-ablation-v4/`

| 指标 | mini-original C0 | mini-repomap C1 |
|---|---:|---:|
| 原始通过 | 4/10 | 5/10 |
| 基础设施完整运行 | 9/10 | 10/10 |
| 总 tokens | 88,667 | 89,516 |
| 最终补丁率 | 80% | 70% |

只比较双方都完整的 9 个配对单元：C0=4，C1=5；C0-only=1，C1-only=2，p=1.0。样本不足，结论是“值得继续测”，不是“Repo Map 已经提升”。这些小型题的 map 只有 42–247 字符，不受大型 Django map 截断缺陷影响。

### B. 正式 SWE-bench Lite pilot

结果目录：`runs/swebench-repomap-pilot-v5/`

任务：`django__django-15781`；模型：`Qwen3.6-35B-A3B`；每个 harness 12 semantic calls；C0/J0/V0 对 C1/J0/V0。

| 指标 | C0 | C1 |
|---|---:|---:|
| semantic calls | 12 | 12 |
| transport attempts | 13 | 13 |
| transport errors | 1 timeout | 1 timeout |
| input + output tokens | 70,338 | 96,151 |
| inspection gate 拒绝 | 6 | 6 |
| patch bytes | 0 | 0 |
| official evaluator | empty_patch | empty_patch |

这是有效的失败样本，但只有一题，不能产生 C0/C1 胜负结论。C1 成本更高且没有产生补丁，说明在修复 edit reliability 之前扩大 Repo Map 评测没有性价比。

### C. API-only JSON J2 pilot

结果目录：`runs/swebench-json-pilot-v1/`

- 2 次 semantic calls；
- 2 次均返回可解析 JSON；
- 两次均使用 `{"action":"command", ...}`；
- schema 要求 `inspect|search|edit|execute|finish|recover`；
- schema-valid 0/2，最终无补丁。

这里不应把 JSON 文本合法率误报成 structured-action 合法率。J3 必须在自部署 vLLM 上用 grammar backend 复测。

### D. 强 harness comparator

结果目录：`runs/strong-harness-pilot-v1/` 与 `runs/aider-adapter-calibration-v1/`

- mini-original：3 题中 2 个完整运行、1 个 transport incomplete，0 resolved；至少产生 8 semantic calls 和 1 个补丁。
- Aider whole：3/3 都是 0 semantic calls，API error；关闭 URL detection 后单题重测仍在 0 calls 时 timeout。

因此不存在有效强基线排名。报告中的任何“0% vs 0%”都不能解释为 harness 能力相等。Aider 需要单独解决 LiteLLM/AMD endpoint 适配，或者改用 OpenHands 的 OpenAI-compatible client 作为下一强基线。

## 新的实验顺序

1. **API transport gate**：同一 32-token 请求连续 20 次；成功率低于 95% 时不启动 expensive benchmark。
2. **Edit-protocol gate**：5 个小题，只测试 C0-J0-V0、C0-J2-V0；目标是 patch rate，而不是先看 resolve rate。
3. **AMD Cloud J3**：本地 vLLM + xgrammar，动作 schema 强制解码；要求 action schema valid rate ≥99%，edit action rate 显著高于 J0。
4. **Verifier 单因素**：冻结最优动作协议后测试 V0→V1→V2。
5. **上下文单因素**：只在 patch rate 已稳定后测试 C0/C1/C2，每次保持 J/V 相同。
6. **强基线**：先做 1 题 API compatibility calibration；0-call 或 transport incomplete 的 harness 不进入排名。
7. **规模扩大**：5 题校准 → 30 题 smoke → 100 题确认 → SWE-bench Lite/Verified。

每个汇总必须同时报告：complete-task rate、resolve rate、patch rate、schema-valid rate、transport attempts/errors、tokens、latency。存在 infrastructure-incomplete 配对时，不产生 harness 胜负排名。

## 当前建议的参赛架构

```text
SWE-bench public task allowlist
  -> self-contained clean workspace + integrity gate
  -> issue-aware context provider (C0/C1/C2 single choice)
  -> mini-SWE controller + deterministic inspection budget
  -> vLLM constrained JSON action (优先 J3/xgrammar)
  -> edit/apply/check dispatcher
  -> deterministic V1/V2 verifier
  -> freeze candidate patch
  -> official SWE-bench evaluator (gold fields evaluator-only)
```

Repo Map 仍保留为候选，但当前不应直接放进最终方案。先解决 constrained edit；之后只有 C1 在至少 30 个固定 SWE-bench 任务上带来可重复的净 resolve 提升，才进入参赛组合。
