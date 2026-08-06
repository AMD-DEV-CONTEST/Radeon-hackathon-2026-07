# ColorGraph Landscape Gold Set 与统一评测协议

> 协议版本：`colorgraph.evaluation/v1`  
> 最后核对：2026-07-30
> 适用范围：镜头/scene、内容感知色彩分析、代表帧、语义与时序蒙版、深度、
> 候选排序、约束修复和工程性能。

## 1. 状态与边界

仓库已经包含可在 CI 运行的程序化 bootstrap Gold Set、严格 manifest、
统一指标 runner、版本化报告、真实来源摄取检查、配额审计和盲测评审工具。
程序化集合只负责冻结公式、文件契约和回归行为，不能替代真实相机、复杂自然运动
和专家审美数据。

完整 Landscape Gold Set 的真实授权素材，以及首轮至少三名专业评审者的结果，
必须在项目外部完成采集和授权后再写入 manifest；不得用虚构素材来源、评审身份
或评分把该外部门禁标记为完成。

当前可复现 bootstrap 位于：

```text
backend/tests/fixtures/evaluation/gold_set_v1/
  manifest.json
  licenses/
  media/
  annotations/
```

真实来源的待标注队列位于
`backend/data/gold_set_intake_v1/`。截至 2026-07-29，队列已有 5 个下载并
哈希的 Wikimedia Commons 原片，以及 1 个从用户获个人商业授权的影视飓风
DJI Mavic 3 Pro Cine 素材无重编码截取的私有评测片段；6 个来源均允许项目内
商业评测，共有 5 个明确相机型号。夜景和项目声明的 DJI D-Log 覆盖已补齐，
FFprobe 与镜头检测产生 19 个机器草稿，6,078 帧精确 PTS 已冻结。私有来源的
容器 BT.709 tag 与项目 Log override 均被保留，且未推断公开再分发权。队列状态
只是 `ready_for_annotation`，尚未形成任何合格人工真值，也尚未进入冻结 Gold
Set；当前仍缺配额规模的独立人工复核。

## 2. 数据规模与覆盖配额

完整 v1 数据集的最低配额如下：

| 任务 | 最低规模 | 强制覆盖 |
| --- | ---: | --- |
| 镜头边界 | 60 段，至少 300 个边界 | 硬切、淡入淡出、叠化、快速摇移、闪光 |
| scene/语义 shot | 40 个 shot | 山体、森林、水面、雪、雾、道路、建筑、unknown |
| 时序 mask/depth | 15 段，每段至少 48 帧 | 细树梢、反光水面、雾、遮挡/显露、大运动、视差 |
| 色彩 | 每个输入 profile 一套冻结信号 | Rec.709、sRGB、Sony Log、DJI Log、HDR、负值和超范围 |
| 候选排序 | 每种核心场景至少 10 对 | 自然、冷调、暖调、雾感及拒绝样本 |
| 工程 | 1080p、4K、短片和至少 30 分钟长片 | 冷/热启动、峰值显存、P95、失败/漂移 |

仓库的 `landscape-p0/v1` 自动审计采用较低但不可豁免的落地门槛：50 个合格
镜头边界 item、30 个合格 scene item、10 个复杂 mask/depth source group，
并要求 mask/depth 真值、至少 3 个明确相机、全部必需标签和三个 split。达到
P0 门槛不等于已经达到上表的完整 v1 目标。

真实素材总体还必须覆盖：

- 至少三类相机/传感器来源、两类镜头焦段；
- Rec.709、至少两种 Log、8/10/12-bit；
- 日间、夜景、雪、水面、雾、树梢、山体；
- CFR/VFR、快速运动、遮挡和显露；
- 明确的 range、primaries、transfer、matrix、bit depth、chroma 元数据。

## 3. 来源、授权和 manifest

所有素材均使用 `colorgraph.gold-set-manifest/v1`。每个 item 必须记录：

- 稳定 `id`、任务、`train/calibration/test` split；
- `source_group_id`，同源连续片段不得跨 split；
- 媒体和标注的相对路径、SHA-256；
- license ID、来源 URL、权利人、用途授权、商业/再分发许可和证据文件；
- 相机、镜头、编码、像素格式、位深、色彩元数据、FPS、尺寸；
- 场景标签和冻结状态。

校验命令：

```powershell
uv run --project backend colorgraph gold-validate `
  backend/tests/fixtures/evaluation/gold_set_v1/manifest.json
```

规则：

1. `source_group_id` 只能属于一个 split，防止连续帧或同一原片泄漏。
2. train 用于训练，calibration 用于阈值和超参数，test 只用于最终报告。
3. test item 必须 `frozen=true`；修改、增删或重标必须提升 manifest 版本。
4. test 结果不得反向用于调参；发生这种情况必须作废当前 test 版本并重新冻结。
5. checksum、许可证据或 capture metadata 缺失时，校验直接失败。

### 3.1 来源摄取与 P0 审计

来源候选、原片、自动探测和人工签核彼此分层，不能用前一步的成功状态代替后一步：

```powershell
# 1. 检查来源许可字段和原片是否已下载；成功只表示“可开始标注”
uv run --project backend colorgraph gold-source-status `
  backend/data/gold_set_intake_v1/source_candidates.json `
  --root backend/data/gold_set_intake_v1

# 2. 冻结 SHA-256、FFprobe 证据和机器镜头草稿；草稿不计作人工真值
uv run --project backend colorgraph gold-source-inspect `
  backend/data/gold_set_intake_v1/source_candidates.json `
  --root backend/data/gold_set_intake_v1 `
  --output backend/data/gold_set_intake_v1/intake-inspection.json

# 3. 冻结逐帧 PTS、帧表哈希和机器草稿对应的 inclusive frame ranges
uv run --project backend colorgraph gold-annotation-pack `
  backend/data/gold_set_intake_v1/intake-inspection.json `
  --root backend/data/gold_set_intake_v1 `
  --output backend/data/gold_set_intake_v1/annotation-work-pack.json

# 4. 人工标注、独立复核并写入 manifest 后，先校验契约，再运行真实/配额审计
uv run --project backend colorgraph gold-validate <manifest.json> `
  --root <dataset-root>
uv run --project backend colorgraph gold-audit <manifest.json> `
  --root <dataset-root> --output gold-set-p0-audit.json
```

`gold-audit` 只把同时满足以下条件的 item 计入配额：

- `camera_original`、`licensed_stock` 或 `published_dataset` 等真实来源；
- 明确且非占位的相机型号，以及 P0 所需的可商用许可；
- `human` 或 `imported_human_ground_truth`；
- provenance 的 guideline version 与 manifest 一致且已冻结；分析、代表帧、
  scene 基线比较、排序和修复必须使用带规范文件哈希的
  `colorgraph.landscape-annotation/v2`；
- 有时间戳的 annotator 与独立 reviewer，双方 ID 不重叠且 `accepted=true`。

程序化 bootstrap 的预期失败报告保存在
`output/evidence/gold-set-p0-audit.json`，它证明 3 个程序化 item 的合格计数
为 0，而不是把 CI fixture 冒充真实 Gold Set。

公开许可候选使用 `annotation-signoff-template.json`。用户自有、没有公开许可页的
相机原片必须先完成 `owner-attestation-template.json`，明确评测、衍生标注、
商业使用和再分发权限，并由独立权属 reviewer 接受；仅有本地路径或相机元数据
不构成授权证据。

## 4. 标注规范

冻结的逐帧标注与复核规则见
[LANDSCAPE_ANNOTATION_V1.md](LANDSCAPE_ANNOTATION_V1.md)，标识符为
`colorgraph.landscape-annotation/v1`。语义改动必须提升标识符并重新冻结
manifest；不能通过备注绕过审计。

内容感知分析、代表帧、scene 基线比较、排序和修复验收使用
[LANDSCAPE_ANNOTATION_V2.md](LANDSCAPE_ANNOTATION_V2.md)，标识符为
`colorgraph.landscape-annotation/v2`。v2 规范按固定 SHA-256 纳入 v1，并新增
专家参考、可用性、接受/回退和意图保持真值；manifest 必须同时绑定规范的相对
路径与规范哈希。修改规范正文必须提升版本并重新冻结 manifest。

### 4.1 镜头与 scene

- 硬切标注第一个属于新镜头的帧号。
- 渐变转场标注首个可见混合帧和最后一个混合帧，端点均包含。
- 每条边界至少两名标注者独立标注；分歧超过 1 帧由第三人裁决。
- scene 边界标注新 scene 的首个 shot；标签来自冻结 taxonomy。
- 无法可靠归类必须标为 `unknown`，不得强行映射到相近类别。

### 4.2 Mask

- 真值保存为无损 16-bit 灰度或 float mask；二值任务同时保留原始软边界。
- 每帧记录尺寸、target、遮挡、显露、困难区域和是否可判定。
- 边界忽略区必须单独保存，不能写成背景。
- 时序序列不得缺帧；frame 0、frame count、FPS 和 source frame ID 必须一致。
- 光流只作为稳定性对齐信息，不能替代人工/解析真值。

### 4.3 Depth

- 保存 float depth/disparity、有效像素、scale/shift 约定和相机运动说明。
- 无绝对尺度时只评估 shot 内相对结构、时间一致性与 scale/shift 漂移。
- 跨硬切不计算时间一致性。

### 4.4 色彩

冻结集包括：

- sRGB、BT.709 OETF、Rec.1886、ACEScct 和 Sony 官方参考点；
- 10-bit/12-bit ramp、24 色 ColorChecker、灰轴、15° hue sweep；
- 负值、超范围和 HDR highlight；
- CFR/VFR 及完整媒体元数据 fixture；
- 已用固定版本 PyOpenColorIO 2.5.2 的官方内置 `cg-config-v4.0.0_aces-v2.0_ocio-v2.5` 冻结 ACES2065-1 → sRGB Display / ACES 2.0 SDR 100 nits reference processor 输出；CI 以保存的 config/processor cache ID 和参考向量重算校验。

当前数值 fixture：

```text
backend/tests/fixtures/color/golden_color_v1.json
```

### 4.5 分析、代表帧、排序与修复

- 内容感知分析由专家给出曝光参考、色温/色调参考、可判定帧、真实变化和裁剪风险。
- 代表帧逐 shot 标注是否可用，并绑定下游 scene 边界；不能只挑选候选成功的素材。
- 排序真值保留每位专家的盲评结果、拒绝原因和 source group，train、
  calibration、test 必须按 source 隔离。
- 修复逐案例标注是否应接受，并独立记录目标改善、硬安全、非目标副作用和意图漂移；
  应回退案例与成功案例都必须进入冻结 test。
- test 的门槛只能来自独立 calibration observation；批准 gate policy 的人员不得
  与 Gold 标注者重叠。

## 5. 统一指标

| 层级 | 指标 |
| --- | --- |
| 镜头 | 边界 precision/recall/F1（默认 ±1 帧）、渐变区间 IoU |
| 内容感知分析 | 曝光 MAE/bias/改善、mired WB MAE/bias/改善、Tint MAE、非切点闪烁 P95、裁剪风险 |
| 代表帧 | 可用率及相对中点基线改善、下游 scene boundary F1、source-cluster bootstrap CI |
| scene | 边界 F1、标签 macro-F1、accuracy、unknown rate、相对基线改善及 source-cluster bootstrap CI |
| mask | 逐类 IoU、Dice、Boundary F-score、运动补偿 temporal stability |
| depth | scale/shift 归一后的 temporal MAE、scale CV、median drift |
| 色彩 | CIEDE2000、ITU-R BT.2124 ΔEITP、灰轴 chroma、hue error、gamut/clipping、banding |
| 排序 | pairwise accuracy、Bradley–Terry log loss、Fleiss κ |
| 修复 | 修复成功率、回退准确率、unsafe/意外接受率、硬安全/副作用/意图违规率、目标改善与意图漂移 |
| 工程 | 1080p/4K FPS、mean/P95/max latency、VRAM、冷/热启动、长片漂移和失败数 |

实现位于 `backend/colorgraph/evaluation/metrics.py`。CIEDE2000 使用
Sharma–Wu–Dalal 补充测试对冻结；ΔEITP 按
[ITU-R BT.2124](https://www.itu.int/rec/R-REC-BT.2124-0-201901-I/en)。

统一报告命令：

```powershell
uv run --project backend colorgraph evaluate `
  <manifest.json> <observations.json> `
  --output evaluation-report.json
```

上面的普通命令用于公式、代码和工程 observation 验证，报告固定为
`evidence_status=engineering_only`、`release_eligible=false`。正式 Gold
判断必须使用：

```powershell
uv run --project backend colorgraph evaluate `
  <manifest.json> <observations.json> `
  --root <dataset-root> `
  --gold-audit <passed-gold-audit.json> `
  --gate-policy <calibration-gate-policy.json> `
  --require-passed-gold `
  --output evaluation-report.json
```

gate policy 所在目录必须同时保存其绑定的 calibration observation。例如：

```json
{
  "schema_version": "colorgraph.gold-calibration-observations/v1",
  "manifest_id": "<manifest-id>",
  "manifest_version": "<manifest-version>",
  "section_material_ids": {
    "analysis": ["<qualified-calibration-material-id>"]
  },
  "gates": {
    "analysis.exposure_mae_improvement_ev": {"minimum": 0.1}
  },
  "test_materials_accessed": false
}
```

对应 `colorgraph.gold-gate-policy/v1` 必须记录同一组 section/material/gate，
并增加 manifest SHA-256、annotation guideline version、上面文件的相对路径与
SHA-256、独立 `approved_by` 及 `test_materials_accessed=false`。runner 会重读
并复核这两个文件，而不是只信任 policy 中手写的哈希字符串。

`colorgraph.evaluation-report/v1` 自动写入：

- evaluator、manifest 和 observation 版本/哈希；
- 完整运行配置；
- OS、Python、PyTorch、CUDA/ROCm/CPU、设备和显存；
- 本次素材 ID、任务、split 和媒体/标注哈希；
- 分层指标、质量门禁和通过状态。

阈值只能在 calibration split 冻结。报告中的 gate 使用
`{"section.metric": {"minimum": x}}` 或 `{"maximum": x}`，不得在看到 test
结果后调整。严格 Gold 模式会重新计算传入的审计报告、验证规范文件与哈希，
要求 observation 对每个指标 section 精确覆盖全部合格冻结 test material，
并要求 gate policy 精确绑定全部合格 calibration material、calibration
observation 的受控相对路径/SHA-256 和同一组门槛。审计 profile 不得低于
`landscape-p0/v1` 的条目、复杂 source group、相机、标签和商业许可下限。
少样、加样、跨 source 泄漏、低配额审计、缺失/篡改 calibration 文件、事后
改门槛、规范篡改或批准者与标注者重叠都会拒绝评测。

`evidence_status=gold_qualified` 只表示证据链合格；只有全部 gate 同时通过时
`release_eligible=true`。当前工程公式证据见
`output/evidence/gold-acceptance-engineering-validation.json`，其门槛虽通过，
但因没有真实人工 Gold，仍明确保持 `engineering_only`。

## 6. 专家主观评审

流程参考当前有效的
[ITU-R BT.500-15](https://www.itu.int/rec/R-REC-BT.500-15-202305-I/en)
和
[ITU-T P.910 (10/2023)](https://www.itu.int/rec/T-REC-P.910-202310-I/en)
的实验设计、观看条件和 paired comparison 方法。

### 6.1 评审资格和环境

- 每个 pair 至少三名有效专家评分；
- reviewer 记录从业年限和角色，并确认色觉筛查；
- 显示器完成校准并记录白点、峰值亮度、黑位、色域、EOTF、环境照度和校准日期；
- 同一 session 使用相同显示链路和播放器，不允许浏览器自动色彩/亮度调整；
- 先进行不计分训练题，正式题中可选择 A、B、tie 或 reject。

### 6.2 盲测与随机化

`build_blinded_review_session()` 使用固定 seed：

- 每位 reviewer 的 pair 顺序独立随机；
- A/B 位置独立随机；
- 公共 session 只包含 blind code，不包含算法身份；
- 身份映射保存在独立 key 文件，评分结束前不得交给 reviewer。

拒绝项必须填写原因，例如解码错误、非同步、错误色彩管理或无法判定。

### 6.3 汇总和复核

`aggregate_review_responses()`：

- 拒绝重复 reviewer/pair；
- 将随机 A/B 位置恢复为真实候选；
- 强制每个 pair 至少三名有效专家；
- 输出候选偏好比例和 Wilson 95% 置信区间；
- 输出 Fleiss κ 评审一致性；
- 保留 tie、reject 数量和拒绝理由。

只有当冻结 test manifest、session seed、公共盲测文件、私有 key 的哈希、
原始 response、聚合报告和显示校准记录都可追溯时，才能声称候选算法有可复核的
“质量提升”。
