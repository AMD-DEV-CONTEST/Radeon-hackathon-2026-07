# docs/E2E_OPTIMIZATION_REVIEW.md

> 从属 `docs/TRUTH.md`(唯一信源)。本文记录 2026-07-31 一次独立审阅的结论:**autotune 三层系统已覆盖"部署 / 推理服务层"优化,而"agent 编排层"的 e2e 优化尚未启动**;并给出编排层的具体方向清单。代码冲突时以 `screwshell/` 为准。
>
> **互补文档**：`docs/E2E_OPTIMIZATION_FRAMEWORK.md` —— 框架叙事评估 + 双视角(A 工程框架 / B 本地小模型)独立判断 + 0.65ms 叙事风险 + Mixture 待决 + KV 缓存地雷。本文给"做什么",该文给"为什么 + 叙事风险",正交互补。

## 0. 背景与前提纠正

本次审阅基于 `D:\git\screwshell`(TRUTH v6)代码,而非早期 `D:\ai\screwshell-v2`(TRUTH v1)快照。早期审阅(对话历史)所依据的 v1 事实已翻转:

| 早期(v1)以为 | 当前(v6)事实 |
|---|---|
| e2e 从未跑通 | tight 模式真机端到端 EXIT=0(2026-07-29) |
| 阵容待转 GGUF(T1) | 四专家全部已转化✓,有真机 reload 数字 |
| 9 passed / 1 skipped | 42 passed / 1 skipped |
| 默认 backend=peft(9B 旧栈) | 已接 autotune + L3 双档治理,VRAM bug 已修 |
| 0.65ms 双路径冲突未解 | L3 显式设计为 roomy(热切)/ tight(重启换装)双档 |

**结论:早期针对 v1 的"e2e 未跑通 → 不该做 autotune"判断已作废。autotune 方案本身成立,且已落地验证。**

## 1. 两层优化正交:部署层 vs 编排层

- **部署 / 推理服务层(autotune 已覆盖)**:硬件探测、阵容容量决策、KV 量化权衡、双档换装策略、保守档位机。回答"装得下几个专家 / 装不下怎么办 / 怎么换装"。
- **agent 编排层(尚未优化)**:plan → 路由 → RAG → 工具 → 证据 → 答案 的串行链路。回答"一次调查为什么慢 / 怎么少调 LLM / 怎么不幻觉引用"。

autotune 解决前者,不触及后者。前者占"能不能跑",后者占"跑得快不快 + 答案可不可信"。

## 2. 编排层 e2e 优化方向(基于 v6 重新评估)

时间分布真相:一次 4 步调查 ≈ 17 次串行 LLM 调用,LLM 生成占 ~95% 时间,prefill 是被忽略的隐性大头(每次 ReAct 重发全量工具 spec + evidence + 3×1800 字符 observations,单次 prompt 2000-3000 token,prefill 20-30s)。

| 方向 | 说明 | 当前状态(v6) | 优先级 |
|---|---|---|---|
| 引用验证器 + 修 `citations=[]` 死代码 | orchestrator 最终答案引用恒为空,全靠 LLM 自觉;27B Q4 会幻觉。加程序校验引用文件/行号真实存在 | 未做,大概率为当前最大裂缝 | **P0** |
| GBNF 约束解码 | llama.cpp 原生 `response_format: json_schema`,零成本压 JSON 翻车率,展示工程深度 | 未做 | P1 |
| prefill 瘦身 | 工具 spec 按 step skill 裁剪 + 固定前缀 KV 复用 | 未做,隐性大头 | P1 |
| 工具并行 + 调用预算 | max_actions=5 串行往返移植自云端习惯;本地每次 30-45s,应并行工具调用 + 单步 1-2 次预算 | 未做,改动循环风险中 | P2 |
| 证据前置 RAG preflight | plan 前先跑 RAG 把证据喂 planner,减 LLM 调用 | 未做 | P2 |

## 3. 不做项(明确排除)

- Mixture 多专家 scale 组合:需 G3 式混合行为实测,赌输成本高,进 PPT future work。
- VRAM-aware 自适应:autotune governor 已覆盖。
- 结构化 trace 导出:锦上添花。

## 4. 提交前硬伤(P0,阻塞)

- **README.md 与 TRUTH v6 不同步**:README §4 仍写"待转化 T1"、§5 引旧 18.9GB、Repository Layout 缺 `autotune/` 与 `ui/`、架构图无 L3 治理。提交前须从 TRUTH v6 反向同步(同 §4 SPEC.md 处理原则)。

## 5. 待确认

- Q1:工作副本确认为 `D:\git\screwshell`(GitHub `1105s110martin-art/screwshell`),后续改动只落此。
- Q2:v6 orchestrator 编排层是否仍串行 / `citations=[]` 死代码是否仍在 / max_actions 是否仍=5,需读全文确认 P1 改造真实内容。
