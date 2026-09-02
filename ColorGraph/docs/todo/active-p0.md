# P0 Open — 后置评价基础

> [TODO 入口](../TODO.md) · [任务目录](README.md)
> 本文件只包含未归档的 P0 任务；是否在提交前投入以每项的 `提交决策` 为准。

`CG-COLOR-003` 已于 2026-08-02 在 Radeon Cloud 实机通过并移入
[2026-08 AMD/ROCm archive](archive/2026-08-amd-radeon-cloud.md)。

## 质量评价基础

- [ ] **CG-EVAL-001 — 建立 Landscape Gold Set 规范和冻结测试集**
  - 提交决策：**`DEFERRED`，完整后置。** 提交前停止扩充 50–100 段正式 Gold Set、train/calibration/test 人工签核和 reviewer 组织；现有 manifest、规范与 intake 继续保留，但不得用于生产级质量声明。
  - 收集不同相机、Rec.709/Log、昼夜、雪、水面、雾、树梢、山体、快速运动和遮挡素材。
  - 建立数据来源、授权、相机/镜头/编码和色彩元数据清单。
  - 划分 train/calibration/test；test 一经冻结不得用于调参。
  - 建议规模：50–100 段镜头边界、30–50 个语义 shot、10–20 段复杂时序 mask/depth。
  - 完成标准：标注规范、版本、manifest、拆分和 reviewer 流程均可复现。
  - 2026-07-28 进度：
    - 已实现严格 `colorgraph.gold-set-manifest/v1`、license/capture metadata、source-group 防泄漏、冻结 test、路径和 SHA-256 校验；另有 `landscape-p0/v1` 审计，强制真实来源、可商用许可、版本化人工标注、独立 reviewer、配额、相机和内容覆盖。
    - 已冻结 `colorgraph.landscape-annotation/v1` 标注规范，并提供 `gold-source-status`、`gold-source-inspect`、`gold-annotation-pack`、`gold-audit`、人工签核和自有素材权属声明模板。程序化 train/calibration/test bootstrap 只用于 CI 契约回归；`output/evidence/gold-set-p0-audit.json` 证明它会被真实/人工门禁拒绝。
    - `backend/data/gold_set_intake_v1/` 现有 6 个已哈希真实相机来源：5 个可商用 Creative Commons 原片，以及从用户获影视飓风个人商业授权的 DJI Mavic 3 Pro Cine 素材无重编码截取的 5 秒 10-bit ProRes D-Log 私有评测片段；共 5 个明确相机型号。私有授权证据保留用户原话，并明确不推断原片/片段公开再分发权。
    - FFprobe 与镜头草稿检查得到 19 个机器草稿；`annotation-work-pack.json` 冻结 6,078 个逐帧 `best_effort_timestamp_time`、帧表哈希、inclusive 草稿范围和 inspection 哈希。Log 声明与容器 BT.709 tag 冲突均被并列保留，没有改写码流元数据。
    - 现仍缺少达到配额的独立人工标注/reviewer 签核；因此本项保持未勾选，不得把 `ready_for_annotation`、工作包、用户授权声明或机器草稿冒充 Gold Set 通过。
