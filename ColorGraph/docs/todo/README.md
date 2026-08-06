# ColorGraph TODO 工作区

> 状态日期：2026-08-02（Asia/Shanghai）
> 当前任务：17 个未归档（1 个 `DEMO-GATE`、2 个 `FROZEN`、14 个 `DEFERRED`），39 个 archived。

这里是 [根 TODO 入口](../TODO.md) 的分层任务目录。默认只加载入口页和当前工作所属的一个任务文件；只有追溯决策、验收证据或历史测试数时才读取 archive。`active-*` 是现有文件名，不再代表其中每项都应在提交前投入；每项以显式 `提交决策` 为准。

## 渐进式加载

1. 从 [docs/TODO.md](../TODO.md) 获取当前重点和文件路由。
2. 只打开与任务领域对应的文件，先读取 `提交决策`，再决定是否继续。
3. 跨领域依赖只按任务 ID 跳转，不预加载所有文件。
4. 需要历史原因或验收数字时，再打开对应 archive 文件。

## 未归档任务

| 文件 | 范围 | `DEMO-GATE` | `FROZEN` | `DEFERRED` | 合计 |
| --- | --- | ---: | ---: | ---: | ---: |
| [active-p0.md](active-p0.md) | Gold Set | 0 | 0 | 1 | 1 |
| [active-p1-perception.md](active-p1-perception.md) | 曝光/WB、代表帧、scene、depth | 0 | 2 | 2 | 4 |
| [active-p2-agent.md](active-p2-agent.md) | 创意 Director、RAG、Critic、评测 | 1 | 0 | 3 | 4 |
| [active-p2-models-quality.md](active-p2-models-quality.md) | 模型 shadow、排序、repair | 0 | 0 | 8 | 8 |
| [active-p3.md](active-p3.md) | 当前无未归档任务 | 0 | 0 | 0 | 0 |
| **合计** |  | **1** | **2** | **14** | **17** |

## Archive

| 文件 | 范围 | 任务数 |
| --- | --- | ---: |
| [archive/2026-07-core-correctness.md](archive/2026-07-core-correctness.md) | P0 色彩/I/O、作用域、资产、评测基础 | 10 |
| [archive/2026-07-color-workbench.md](archive/2026-07-color-workbench.md) | ACES、算子、关键帧、LUT、播放器与工作台 | 9 |
| [archive/2026-07-perception-performance.md](archive/2026-07-perception-performance.md) | 语义映射、共享光流优化 | 2 |
| [archive/2026-07-agent-foundation.md](archive/2026-07-agent-foundation.md) | 创意 Agent 契约与证据基础 | 2 |
| [archive/2026-07-quality-constraints.md](archive/2026-07-quality-constraints.md) | 质量分层与创意约束 | 2 |
| [archive/2026-07-agent-creative-pipeline.md](archive/2026-07-agent-creative-pipeline.md) | 创意 Agent 离线及真实 Provider Shadow Pipeline | 7 |
| [archive/2026-07-runtime-performance-quality.md](archive/2026-07-runtime-performance-quality.md) | Runtime 性能、蒙版资产、时序质检与研究观察 | 5 |
| [archive/2026-08-amd-radeon-cloud.md](archive/2026-08-amd-radeon-cloud.md) | Radeon Cloud AMD/ROCm 精度与代表性短片门禁 | 2 |

## 当前关键路径

```text
CG-CREATIVE-010：冻结三方向可见差异与人工选择
→ 英文公开仓库与 README
→ Project Profile PDF + 3–5 分钟视频 + PPT/Poster
```

`CG-COLOR-003` 与 `CG-BENCH-001` 已在 Radeon Cloud 实机通过，统一报告见
[`amd-full-pipeline-report.json`](../../output/evidence/amd-full-rocm-linux-radeon-cloud-20260802-v6/amd-full-pipeline-report.json)。

## 维护规则

- 优先级：`P0` 确定性错误/质量门禁，`P1` 质量基础，`P2` 模型与 Agent shadow，`P3` 性能与长期增强。
- 未归档任务必须声明一种提交状态：`DEMO-GATE` 表示提交前仍需完成缩小门槛；`FROZEN` 表示继续使用当前实现但停止补正式验收；`DEFERRED` 表示完整提交后置。
- 任务 ID 全局唯一；依赖可以跨文件，但不能复制任务正文。
- `active-*` 文件只保留未完成任务及其当前阻塞/进度；文件名是历史兼容入口，是否投入由 `提交决策` 决定。
- 完成时将整个任务块和验收证据移动到对应月份的 archive 文件，不在 active 留摘要副本。
- 每项必须有测试或可重复报告；“代码可运行”不能替代质量验收。
- 外部模型先进入 shadow mode，未通过 Gold Set、许可、显存和稳定性门禁前不得替换默认实现。
- 完成任务后同步更新 [PROJECT_STATUS.md](../PROJECT_STATUS.md) 和相关测试数量/性能数据。
- 归档或新增任务后，更新本页文件表和 [根 TODO 入口](../TODO.md)；运行任务 ID、依赖和 Markdown 链接检查。
