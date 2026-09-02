# ColorGraph TODO

> 状态日期：2026-08-02（Asia/Shanghai）
>
> 本文件是稳定、轻量的任务入口。任务正文、依赖、进度与历史验收证据位于 [todo/README.md](todo/README.md)。

## 当前状态

- 未归档：17（`DEMO-GATE` 1、`FROZEN` 2、`DEFERRED` 14）
- Archived：39
- `CG-WATCH-001` 已完成并移入 archive，不再计入未归档任务。
- 提交期目标：证明 ColorGraph 在 AMD Radeon 上真实运行、结果肉眼明显、操作链完整，且核心输出来自真实算法而非静态界面或预制视频；不以“清空 TODO”或生产级统计声明为目标。
- `CG-COLOR-003` 与缩小后的 `CG-BENCH-001` 已于 2026-08-02 在 Radeon Cloud
  实机通过并归档；统一报告为 `status=passed`，报告 SHA-256
  `c7a7e15c…35c195`。完整 20 行长片生产矩阵仍后置。

## 提交冻结决策

| 状态 | 任务 | 当前决策 |
| --- | --- | --- |
| `DEMO-GATE` | `CG-CREATIVE-010` | 冻结一个能稳定生成三种肉眼明显不同方向的场景，人工确认最终方案；正式专家验收后置。 |
| `FROZEN` | `CG-ANALYSIS-001`、`CG-REP-001` | 保留并继续使用当前实现，不再为提交补 Gold Set、专家真值或统计显著性。 |
| `DEFERRED` | `CG-EVAL-001`、`CG-AGENT-EVAL-010`、`CG-RANK-002`、`CG-REPAIR-001` | Gold Set、专家评测、偏好模型与正式修复统计全部提交后再做。 |
| `DEFERRED` | `CG-SCENE-001`、`CG-DEPTH-001`、`CG-SHOT-010`、`CG-VLM-010`、`CG-SEM-010`、`CG-VOS-010`、`CG-VOS-011`、`CG-VOS-012` | 停止候选模型替换与 shadow benchmark；Demo 使用当前默认或已经生成的资产。 |
| `DEFERRED` | `CG-RAG-010`、`CG-CRITIC-010` | 生产知识治理、专家校准和自动选择后置；Critic 仅给建议，保持 `auto_selection_allowed=false`。 |

状态含义：

- `DEMO-GATE`：提交前仍需完成缩小后的可复现门槛。
- `FROZEN`：实现继续用于 Demo，但停止追加正式验收工作。
- `DEFERRED`：完整后置，提交前不再投入开发或验收。

## 冻结 Demo 链路

```text
AMD Radeon / ROCm 设备信息
→ 导入 12–25 秒、1080p、可再分发的风景视频
→ 镜头、曝光/WB、代表帧分析
→ 使用现有语义/深度时序蒙版
→ Agent 生成 faithful / amplified / counterpoint 三个明显不同方向
→ 用户手动选择
→ “压低后半段天空但不改变山体”的自然语言局部修改
→ 真实 4 秒调色播放分片
→ 导出 MP4 + LUT + Grade Graph + 质量报告
```

主演示不展示模型切换、Gold Set、自动 Critic 选优、Reflection、多轮修复、SAM 3.1 或完整 4K 长视频矩阵。

## 未归档任务路由

| 优先级 / 领域 | 文件 | `DEMO-GATE` | `FROZEN` | `DEFERRED` | 合计 |
| --- | --- | ---: | ---: | ---: | ---: |
| P0 | [todo/active-p0.md](todo/active-p0.md) | 0 | 0 | 1 | 1 |
| P1 感知基础 | [todo/active-p1-perception.md](todo/active-p1-perception.md) | 0 | 2 | 2 | 4 |
| P2 Agent | [todo/active-p2-agent.md](todo/active-p2-agent.md) | 1 | 0 | 3 | 4 |
| P2 模型与质量 | [todo/active-p2-models-quality.md](todo/active-p2-models-quality.md) | 0 | 0 | 8 | 8 |
| P3 性能 | [todo/active-p3.md](todo/active-p3.md) | 0 | 0 | 0 | 0 |
| **合计** |  | **1** | **2** | **14** | **17** |

## 提交顺序

1. 修复冻结场景的三方向可见差异并冻结 Demo 工程。
2. 用已通过的 Radeon Cloud 统一报告和 Main10 成片准备设备/播放录屏；仅当代码、
   冻结输入或目标环境变化时才重跑 AMD 门禁。
3. 建立可公开、可复现、英文的提交仓库与 README。
4. 完成 Project Profile PDF、3–5 分钟 Demo 视频和 PPT/Poster。

提交要求依据：[AMD AI DevMaster Hackathon](https://luma.com/amd-4dhi) 与 [Radeon Hackathon 官方 README](https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07/blob/main/README.md)。

## Archive 路由

- [核心正确性与基础设施](todo/archive/2026-07-core-correctness.md) — 10 项
- [色彩质量与工作台](todo/archive/2026-07-color-workbench.md) — 9 项
- [感知与性能](todo/archive/2026-07-perception-performance.md) — 2 项
- [创意 Agent 契约与证据基础](todo/archive/2026-07-agent-foundation.md) — 2 项
- [质量分层与创意约束](todo/archive/2026-07-quality-constraints.md) — 2 项
- [创意 Agent 离线 Shadow Pipeline](todo/archive/2026-07-agent-creative-pipeline.md) — 7 项
- [Runtime 性能、蒙版资产、时序质检与研究观察](todo/archive/2026-07-runtime-performance-quality.md) — 5 项
- [Radeon Cloud AMD/ROCm 实机门禁](todo/archive/2026-08-amd-radeon-cloud.md) — 2 项

## 渐进式加载约定

1. 默认只读取本文件。
2. 开始任务时，仅加载它所在的任务文件，并先检查 `提交决策`。
3. 只有追溯实现原因、历史依赖或验收证据时才加载 archive。
4. 新增、完成、归档任务时遵循 [任务目录维护规则](todo/README.md#维护规则)。
