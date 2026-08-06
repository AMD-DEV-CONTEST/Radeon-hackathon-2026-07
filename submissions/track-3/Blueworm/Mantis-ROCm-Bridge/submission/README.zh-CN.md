# Mantis-ROCm Bridge 框架提交包（中文导航镜像）

> **状态：本地发布候选。** 本地内容与完整性闸门已通过；净室复现、公开 PR/提交、赛事获奖、G3 成功、收敛、鲁棒性、真机安全、原始资产再分发权与任何 AMD 性能优势仍未得到证明。只有在获得独立
> `RELEASE_GO` 后，该候选才可进入经授权的公开 PR。官方提交语言为
> **英文**；本文件仅作为**中文导航镜像**。当两者不一致时，以英文文件
> （`README.md`、`TECHNICAL_REPORT.md` 等）为准。本目录不包含任何原始 Mantis
> 网格、URDF 或其他原始资产载荷、数据集、模型权重、凭证或私有部署载荷；仅有的
> URDF/STL 文件是 `tests/fixtures/` 下的九个合成非 Mantis 测试 fixture。

- 官方赛事：2026 AMD AI DevMaster 黑客松 — Track 3（物理 AI / Physical AI）
- 提交截止：2026-08-06T23:59:00+08:00（提交前请复核官方规则）
- 规则快照：`configs/competition-resources-v1.json`
- 公开权威来源：`docs/FRAMEWORK_STORY_V1.md`、
  `docs/G3_FAILURE_ATTRIBUTION_SUBMISSION_SPRINT.md`、
  `submission/EVIDENCE_MATRIX.md`
- 参赛者：**Zhiwen Su**
- 队伍：**Blueworm**
- 应用：**Mantis-ROCm Bridge**
- 项目许可证：**Apache-2.0**（仅覆盖 Blueworm 有权授权的原创材料）

## 产品主线

Mantis-ROCm Bridge 是一个**合同驱动、证据门控的机器人适配与任务移植
framework**。它显式描述源/目标机器人、状态与动作、相机与时钟、控制器、
安全、数据、策略、评估、运行时、资产和证据晋级边界。

本项目面向 **AMD 具身智能生态**构建基础设施，而不是只完成一次 Mantis
演示。对机器人厂家而言，它提供了一条可复用的接入路径：把定制 URDF、运动学、
相机、状态/动作与控制接口接入 Genesis 仿真、LeRobot 数据与策略工作流，并在
AMD Radeon + ROCm 上分阶段执行。项目提供的 profile 模型、URDF-to-ROCm
编译器、LeRobot adapter 和证据门禁，可以降低更多厂商机器人进入 AMD
生态的工程成本。

Tron/RoboTwin `stack_bowls_three` → Mantis/Genesis/LeRobot/ROCm 是第一个
有证据支撑的**参考（reference）实例**。Mantis 不是产品定义；一个真实参考
实例与一个合成验证 fixture 不能证明通用多机器人运行时支持。

这是一个个人参赛、限时完成的原型，示范数据覆盖和训练时间限制了当前策略质量，
因此策略尚未达到部署标准。本项目的主要贡献是可复用的机器人集成层，以及从厂商
定制机器人到 AMD 硬件的可审计路径，而不是宣称已经解决三碗操作任务。

**提交演示视频：**
[`Mantis_ROCm_Bridge_demo_20260806_v4.mp4`](Mantis_ROCm_Bridge_demo_20260806_v4.mp4)

最小可用框架表面已经完成：可复制但默认阻塞的 profile 模板、Mantis 参考
profile、只用于验证的合成 fixture，以及确定性的只读 `validate/plan` 命令。
证据见 `receipts/framework-mvp-terminal-20260729-v2/`。

## 诚实结果摘要

本提交如实记录一个**闭环负结果（negative result）**。

| 阶段 | 结果 | 证据回执 |
|---|---|---|
| 环境执行（ROCm，单块 Radeon GPU） | 已验证 | `receipts/amd-act-rocm-v2-live-20260726-v1/` |
| AMD 上训练 ACT 模型 | 优化运行完成；第 60,000 步最终 loss 0.023；`exit_code=0` | `receipts/amd-act-rocm-v2-live-20260726-v1/` |
| AMD 上实时开环推理 | 通过——12 个有限动作，满足固定关节限位 | `receipts/amd-act-openloop-inference-20260726-v1/` |
| 闭环 G3 评估（种子 101–110） | **严格成功率 0/10 —— FAIL**（8 次 `timeout`，2 次 `collision_safety`） | `receipts/amd-act-closedloop-g3-multiseed-final-20260726-v1/` |
| G3 失败归因 | CUDA 确定性复演重现 seed 101 超时和 seeds 107/108 右腕碰撞族；ACT 命令目标反事实进入相同碰撞族 | `receipts/g3-r1r2-dynamic-replay-20260727-v2/`、`receipts/g3-commanded-target-counterfactual-20260727-v2/` |
| 单变量纠正 | 六条合格轨迹 / 7,085 帧；CUDA 从头 ACT 训练已完成 60,000 步并通过来源核验 | `receipts/4090-multiseed6-trajectory-correction-20260727-v1/`、`receipts/4090-act-multiseed6-training-final-20260727-v1/` |
| 纠正 CUDA 代表评测 / AMD 晋级 | seeds 101/107/108 已完成，0 成功、2 次安全失败；`COMPLETE_NOT_PROMOTABLE`；官方 AMD 纠正执行未启动 | `receipts/4090-g3-corrective-representative-terminal-20260728-v2/` |

**训练 loss 不等于任务成功。** 优化曲线仅为描述性指标，不能证明收敛、抓取、
堆叠、任务成功、泛化、鲁棒性、真机安全，也不能证明任何 AMD 性能优势。
本项目不声称任何 AMD 性能优势。

## 文档索引

| 文档 | 用途 |
|---|---|
| `TECHNICAL_REPORT.md` | 完整技术报告，覆盖 Track 3 每一项官方要求章节 |
| `EVIDENCE_MATRIX.md` | 每个定量结论映射到已验证回执或 `TODO-evidence` |
| `VIDEO_STORYBOARD.md` | 独立验收通过的 168 秒 720p 英文旁白与字幕视频 |
| `PUBLICATION_CHECKLIST.md` | 公开发布前的密钥、体积、许可、净室、英文、PR 闸门 |
| `README.md` | 英文权威入口（以英文为准） |

## 官方交付物

| 交付物 | 真相来源 | 当前闸门 |
|---|---|---|
| 可复现项目 README | 顶层 `README.md`、`docs/REPRODUCIBILITY.md` | 公开复现命令面完整；净室复现仍未得到证明并作为 `LIMITATION` 明示 |
| 技术报告 | `submission/TECHNICAL_REPORT.md` | 框架优先的证据支撑草案；Zhiwen Su / Blueworm 与 `COMPLETE_NOT_PROMOTABLE` 终态已同步 |
| 源代码 | `src/`、`tools/`、`configs/`、`tests/` | 完整源代码和本地打包政策闸门已通过；公开 PR 仍须获得独立 `RELEASE_GO`；项目 LICENSE 保持 Apache-2.0 / Blueworm / 2026 |
| ROCm 环境 | `docker/`、`requirements/`、官方云指引 | 可用；净室验证 `TODO-evidence` |
| 训练证据 | `receipts/amd-act-rocm-v2-live-20260726-v1/` | 终端审计完成 |
| 开环推理证据 | `receipts/amd-act-openloop-inference-20260726-v1/` | 完成 |
| 闭环评估证据 | `receipts/amd-act-closedloop-g3-multiseed-final-20260726-v1/` | 完成（负结果） |
| G3 静态与动态失败归因 | `receipts/g3-r1r2-dynamic-replay-20260727-v2/` | 代表性超时/碰撞失败族已确定性复演 |
| 演示视频（英文旁白与字幕） | `submission/Mantis_ROCm_Bridge_demo_20260806_v4.mp4`；SHA-256 `220c54c7ca68760db53a5a9d8c80d1d8f39755a7365ee682758d6b5b50952017`；`submission/VIDEO_STORYBOARD.md` | `VIDEO_GO`；H.264 1280x720、168 秒、5,040/5,040 帧完整解码；正确三碗场景；成功脚本专家轨迹与未完成任务的 50-step 策略 smoke 明确区分 |
| 项目 LICENSE | `LICENSE`、`docs/PROJECT_LICENSE_DECISION.md` | Apache-2.0；版权所有者 Blueworm；年份 2026；决定日期 2026-07-29；仅覆盖原创项目材料 |
| 第三方声明 | `third_party/ASSET_LICENSES.md` | 审计更新至 2026-07-27；当前身份权威为 `receipts/asset-license-public-audit-20260727-v2/README.md`（不可变 v1 仅作历史且其身份结论已被取代）；用户允许演示视频中的渲染画面，但 Mantis 原始资产再分发仍被阻断 |
| 向官方仓库提交 Pull Request | `https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07` | `PENDING_EXTERNAL`（尚未创建） |

归档净室 runner 的源码审查仍为 `CLEANROOM_RUNNER_NO_GO`；没有任何 runner
执行，因此净室复现仍未得到证明，并作为 `LIMITATION` 明示，而不是本地包
阻塞项。fork、PR 和提交属于 `PENDING_EXTERNAL` 外部动作，均需要单独授权。

## 资产政策（提交安全边界）

公开提交将 Mantis 视为**外部化（externalized）、按哈希钉版的依赖**，直到其所有者发布可再分发
许可或提供书面提交许可（见 `third_party/ASSET_LICENSES.md`）。用户允许演示
视频展示渲染后的 Mantis 画面；该许可仅覆盖演示画面，不构成一般再分发权、
第三方许可或原始资产发布许可。当前仓库身份
权威为 `receipts/asset-license-public-audit-20260727-v2/README.md`；不可变 v1
`receipts/asset-license-public-audit-20260726-v1/README.md` 仅作历史记录，其
仓库身份结论已被 v2 取代。公开脚本可在
明确致谢后于本地物化 Mantis，但仓库及任何 Docker 镜像**不得**内嵌 URDF、
网格、源资产、派生原始资产文件、派生物化产物或资产载荷。MIT 许可的碗资产（`002_bowl` model 3，Tianxing Chen /
RoboTwin2.0）仅在保留钉版署名与已验证许可文件的前提下可打包。本项目不为
公开发布提议任何凭证、私有部署载荷、数据集、模型权重或超过 100 MB 的文件。
演示画面许可不得外推为 Mantis 源资产或派生原始资产的公开许可。

项目自身的许可证是独立的所有者决策，现已记录：原创项目源代码与文档采用
**Apache License 2.0**，版权所有者 **Blueworm**，版权年份 **2026**，决定日期
**2026-07-29**（见 `LICENSE` 与 `docs/PROJECT_LICENSE_DECISION.md`）。它只
覆盖 Blueworm 有权授权的原创代码与文档，不能重新许可或扩大 Mantis 及其他
第三方资产的权利范围。选定该许可证本身并不证明净室复现、公开仓库、已提交
的 Pull Request、赛事获奖、G3 通过，或第三方授权。

## 结论边界

本包建立一个 Mantis 参考实例的**框架叙事完整性、配置就绪性与证据可追溯
性**。它不证明第二个真实机器人移植、通用运行时执行、纠正策略有效、AMD
纠正训练已执行、净室复现完成、公开仓库或 Pull Request 已提交、
已经提交参赛、G3 通过，或赛事获奖。独立验收通过的 168 秒 v4 视频保持
同样的结论边界。
