# 2026-07 Archive — 核心正确性与评测基础

> [TODO 入口](../../TODO.md) · [任务目录](../README.md)
> 本文件归档 10 个已完成任务；保留原始完成标准和验收证据。

## 色彩与视频 I/O

- [x] **CG-COLOR-001 — 用官方参考修正 Sony S-Log3/S-Gamut3.Cine 变换**
  - 用 ACES/Sony 官方 CSC 或 OCIO processor 替换错误手写矩阵。
  - 同步修正反向变换；明确 scene-linear Rec.709、display Rec.709 和 sRGB 的语义。
  - 新增官方参考点、RGB 原色、灰阶、负值/超范围、色卡和 hue sweep 测试。
  - 完成标准：不再依赖自洽 round-trip 作为唯一依据；参考向量在约定浮点误差内通过。
  - 验收证据（2026-07-28）：
    - 正反向矩阵现由 Sony/ACES 公布的 S-Gamut3.Cine、Rec.709 和 D65 色度坐标生成，不再维护手抄矩阵；错误第三行已修正为约 `[-0.044436, -0.195920, 1.240356]`。
    - S-Log3 解码不再 clamp 到 `0..1`，负值和扩展范围按 Sony 公式保留；接口文档明确输出为 scene-linear Rec.709 D65，而非 display Rec.709/sRGB。
    - `uv run pytest tests\test_color_management.py -q`：当前 `17 passed`，覆盖 Sony CV 95/420/598、固定矩阵参考、RGB 原色、灰阶、负值/超范围、24 色 ColorChecker、15° hue sweep、双向变换和后续加入的标准传递函数参考值。
    - `uv run pytest`：当前 `132 passed`；全仓 Ruff、`npm run typecheck`、`npm run build` 和 `colorgraph doctor` 均通过。

- [x] **CG-COLOR-002 — 真正执行 Input/Working/Output Transform**
  - 在 renderer 中处理 `INPUT_TRANSFORM` 和 `OUTPUT_TRANSFORM`。
  - 正确区分 sRGB、BT.709 OETF、Rec.1886、Linear Rec.709、ACEScct 和 Sony Log。
  - 对未知或未实现的 color space/profile 明确报错。
  - 为 renderer/schema 增加版本字段与兼容策略。
  - 依赖：CG-COLOR-001。
  - 完成标准：graph 声明的空间与实际 processor 一致；不再静默回退 sRGB。
  - 验收证据（2026-07-28）：
    - `colorgraph.renderer/v2` 按图顺序执行唯一的 project-level Input/Output Transform，并校验节点空间、媒体声明、工作空间、输出空间和 Log profile 一致；缺失、重复、错序、未知或尚未实现的组合均明确报错。
    - sRGB、BT.709 OETF、零黑位 Rec.1886、Linear Rec.709 和 ACEScct 使用各自标准分段函数；Sony S-Log3/S-Gamut3.Cine 与 DJI Log profile 经 scene-linear Rec.709 工作空间路由，不再把非 Sony 输入静默当作 sRGB。
    - schema/renderer 同步升级为 v2；持久化 v1 项目自动绑定 legacy renderer，保留旧有 sRGB 解码/编码外观，并拒绝不匹配的版本组合。
    - 相关 5 个测试文件共 `41` 项；后端全量当前 `132 passed`，全仓 Ruff、TypeScript、Vite production build 和 `colorgraph doctor` 均通过。
    - Playwright 实测输入选择、后台重分析、v2 图回读和恢复链路通过；浏览器控制台 `0 errors / 0 warnings`。

- [x] **CG-IO-001 — 完整探测并持久化媒体色彩元数据**
  - 扩展 `MediaInfo`：range、primaries、transfer、matrix、bit depth、chroma subsampling、HDR metadata。
  - 处理缺失/冲突元数据并记录推断来源和置信级别。
  - 增加 ffprobe fixture 和 metadata round-trip 测试。
  - 完成标准：10-bit Log/HDR/Rec.709 fixture 的输入属性可准确回读。
  - 验收证据（2026-07-28）：
    - ffprobe 同时读取首批视频帧 side data；`MediaInfo` 持久化 range、primaries、transfer、matrix、bit depth、chroma subsampling/location、HDR mastering display、MaxCLL/MaxFALL 和 HDR family。
    - 每个字段保存 `stream/container/pixel_format/side_data/user_override/default/missing` 来源、`high/medium/low/unknown` 置信度、原始报告值和冲突状态；stream 声明与容器 tag 冲突时保留 stream 值并显式标记。
    - 旧项目缺少 provenance 时保留原输入空间/profile，并标为低置信 legacy evidence；用户 Log profile 覆盖不兼容 transfer 时同样保留原码流字段和冲突证据。
    - 冻结 FFmpeg 8.1 形态的 8-bit Rec.709、10-bit ProRes Log、10-bit HDR10 和冲突 metadata JSON fixtures；HDR10 mastering/CLL、像素格式位深推断及 ProjectStore JSON round-trip 均有测试。
    - `test_media_probe.py`：`7 passed`；后端全量当前 `132 passed`，全仓 Ruff、TypeScript 和 Vite production build 通过；运行中 API 已回读新增 schema 字段。

- [x] **CG-IO-002 — 建立高位深 decode/render/encode 主链路**
  - 移除最终渲染对 OpenCV 8-bit 帧和 `rgb24` 管道的依赖。
  - 支持至少 10/16-bit 解码、FP32 调色和 10-bit master 输出。
  - 保留 PTS/VFR、音频和色彩标签；8-bit proxy 单独生成并增加 dithering。
  - 对预览和最终质量模式分别定义精度预算。
  - 依赖：CG-IO-001、CG-COLOR-002。
  - 完成标准：10-bit ramp 无额外明显 banding；ffprobe 回读标签正确；CPU/GPU golden image 达标。
  - 验收证据（2026-07-28）：
    - 正式渲染的 decode 和 encode handoff 均固定为 `rgb48le`，调色固定 FP32；即使请求可选 8-bit delivery，也由 FFmpeg 从 16-bit handoff 做误差扩散降位，不再存在最终 `rgb24` 管道。
    - CFR 保留流式管线；VFR 按 ffprobe 的逐帧 best-effort PTS 调色，用 16-bit PPM + ffconcat `duration` 和 `fps_mode=passthrough` 重建非均匀时间轴。输出以零为时间原点，但逐帧间隔、帧数和 A/V 起点受 0.5 ms 硬门禁约束。
    - 音频映射、源 metadata/chapters、BT.709 VUI、limited range、`hvc1`、Main10 与独立 8-bit browser proxy 保留；VFR 临时帧在编码后自动清理。
    - 预览预算为 `colorgraph.precision/preview-v1`（8-bit、允许受控 mixed precision），母版预算为 `colorgraph.precision/master-v1`（16-bit handoff、FP32、至少 10-bit、禁止 mixed precision）。
    - 真实 FFmpeg fixture 的 PTS 为 `0/40/120/200 ms`，Main10 round-trip 未被拉平，音频和 BT.709 标签回读正确；CFR 8-bit delivery 同样验证 16-bit/FP32 handoff。
    - 1024 级 ramp 在 pre-encode 10-bit 投影保持 1024 个码值；CUDA/CPU FP32 golden comparison 在 `0.5/65535` 通道误差预算内通过。
    - `test_video_render.py`：`8 passed`；`test_renderer_color_pipeline.py`：当前 `8 passed`；后端全量 `132 passed`，全仓 Ruff 通过。

## 导出、作用域与资产

- [x] **CG-LUT-001 — 修复多场景 LUT 串联导出**
  - 按 `scene_id` / `look_node_id` 单独导出。
  - project Post Look 独立导出或在 manifest 中明确合并策略。
  - manifest 写入 input/grading/output space、时间范围、LUT size 和 interpolation。
  - 增加单 scene、多 scene、无 Look、带 Post Look 测试。
  - 完成标准：互斥场景 Look 不再出现在同一个 processor/LUT 中。
  - 验收证据（2026-07-28）：
    - 每个 scene/look 生成独立 `.cube`；legacy 无 Scene 的孤立 Look 也逐个导出，多 scene helper 不再允许静默返回第一项。
    - processor 仅含 Input Transform、被选中的一个 Look、project Post Look 和 Output Transform；Post Look 策略明确为 `baked_into_each_lut`。
    - `colorgraph.export-package/v2` 为每个 LUT 写入 scene/look ID、时间范围、input/grading/output space、size、tetrahedral interpolation 和 Post Look 节点清单。
    - `test_export_package.py` 的单 scene、多 scene、无 Look、Post Look 四项回归通过；测试直接断言互斥 Look 从未共存于一个 processor。

- [x] **CG-AGENT-001 — 修复项目级自然语言命令只改一个镜头**
  - 明确 project-level Balance 的数据模型：项目节点或逐 shot 展开。
  - 覆盖所有适用节点、keyframe 和保护目标。
  - 确保 `invalidated_ranges` 与实际改动范围一致。
  - 增加“全片/当前镜头/前后半段/指定 scene/保护区域”的组合测试。
  - 完成标准：“全片变暖/变亮”在多 scene、多 shot 项目中作用完整且可撤销。
  - 验收证据（2026-07-28）：
    - `landscape-grade-grammar/v2` 采用明确的逐 shot 展开模型；project/scene/shot 命令更新全部适用 Balance，并同步偏移同参数关键帧。
    - 部分时间范围创建独立 overlay Balance；全局调整带保护目标时生成 `NOT target` 组合蒙版，不再错误修改未遮罩的基础 Balance。
    - 每个 edit 记录 `affected_range`，`invalidated_ranges` 与 project/scene/shot/半镜头的实际范围一致。
    - `CommandPlan.undo_graph` 保存精确前态；Web 工作台以 `Ctrl/Cmd+Z` 持久化恢复上一条命令。9 项组合回归覆盖多 scene/shot、关键帧、指定 scene 和保护区域。

- [x] **CG-MASK-001 — 修复时序蒙版元数据和资产完整性**
  - 将虚假的 `farneback_bidirectional_reanchor` 改为真实算法描述，或实现真正双向一致性。
  - 缺帧默认报错；如需容错，显式提供 `hold_last` 策略。
  - 校验 frame count、尺寸、fps、target alias、checksum 和解码完整性。
  - 完成标准：损坏/缺失/错尺寸资产不能静默生成零 mask。
  - 验收证据（2026-07-28）：
    - tracking 元数据如实记录 `farneback_backward_flow_warp`、current→previous flow、周期模型重锚定和 `bidirectional_consistency=false`。
    - `colorgraph.mask-asset/v2` 保存 frame/file count、尺寸、FPS、target aliases、PNG sequence/FFV1 SHA-256、完整解码状态和缺帧策略。
    - Resolver 默认对缺帧、损坏、错尺寸、FPS/frame count/alias/checksum 不一致及未知引用抛错；仅显式 `hold_last` 才复用前一帧，frame 0 缺失仍拒绝。
    - 生成后完整扫描 PNG 并逐帧解码 FFV1；`test_mask_assets.py` 7 项损坏与生成回归通过。

## 质量评价基础

- [x] **CG-EVAL-002 — 实现统一质量指标和报告**
  - 镜头：F1±1 帧、渐变转场区间 IoU。
  - scene：边界 F1、标签 macro-F1、unknown。
  - mask：逐类 IoU、Dice、Boundary F-score、运动补偿 temporal stability。
  - depth：shot 内 temporal/scale consistency。
  - 色彩：ΔE2000/ΔEITP、灰轴、hue sweep、gamut/clipping、banding。
  - 排序：pairwise accuracy、Bradley–Terry log loss、评审一致性。
  - 工程：1080p/4K FPS、P95 latency、VRAM、冷/热启动和长视频稳定性。
  - 依赖：CG-EVAL-001。
  - 完成标准：单条命令产出带版本、配置、硬件和素材清单的报告。
  - 验收证据（2026-07-28）：
    - `colorgraph/evaluation/metrics.py` 实现所列镜头、scene、mask、depth、色彩、排序和工程指标；CIEDE2000 通过 Sharma 参考对，ΔEITP 按 BT.2124。
    - `colorgraph evaluate <manifest> <observations> --output <report>` 生成 `colorgraph.evaluation-report/v1`，包含 evaluator/输入哈希、配置、OS/Python/PyTorch/设备、逐素材哈希、指标和 calibration 冻结门禁。
    - manifest、指标、统一 runner 和报告共 9 项回归通过。

- [x] **CG-EVAL-003 — 建立标准色彩 golden fixtures**
  - Sony 官方参考值、sRGB、BT.709、Rec.1886、ACES 2 reference processor。
  - 10-bit/12-bit ramp、ColorChecker、负值/超范围、HDR highlight、VFR/metadata fixture。
  - 完成标准：CI 可运行 CPU 基线；GPU 差异有明确误差预算。
  - 验收证据（2026-07-28）：
    - 已冻结 `golden_color_v1.json`：sRGB/BT.709/Rec.1886/ACEScct、Sony/DJI 点和矩阵、ColorChecker、10/12-bit ramp、灰轴、hue sweep、负值/超范围与 HDR 信号规范。
    - 以固定测试依赖 PyOpenColorIO 2.5.2 的官方内置 `cg-config-v4.0.0_aces-v2.0_ocio-v2.5` 配置冻结 ACES2065-1 → sRGB Display / ACES 2.0 SDR 100 nits 输出；fixture 保存 config/processor cache ID，并由 CI 实时重算 10 组灰阶、原色、HDR、负值和超范围向量。
    - 6 项 fixture 回归、CPU 基线和既有 CUDA 精度门禁通过；VFR/metadata fixtures 已在 I/O 测试冻结。ROCm 实机差异仍由 CG-COLOR-003 单独跟踪，不再阻塞本 fixture 任务。

- [x] **CG-EVAL-004 — 建立专家调色主观评审流程**
  - 参考 ITU-R BT.500 / ITU-T P.910。
  - 每组至少 3 名有经验评审者，记录成对偏好、拒绝原因和一致性。
  - 隐藏算法身份并随机化顺序。
  - 完成标准：候选模型/算法的“质量提升”可以用冻结数据和置信区间复核。
  - 验收证据（2026-07-28）：
    - `evaluation/review.py` 固定 seed 后为每位 reviewer 独立随机顺序与 A/B，公共 session 只暴露 blind code，身份 key 独立保存。
    - schema 强制至少 3 名有经验评审者、色觉筛查、显示校准详情、拒绝原因和置信度；聚合恢复真实候选并输出 Wilson 95% 区间、tie/reject 与 Fleiss κ。
    - 参考当前 ITU-R BT.500-15 / ITU-T P.910 (10/2023) 的完整观看、冻结、留档和复核流程已写入 `docs/EVALUATION_PROTOCOL.md`；盲测与不足 3 人拒绝路径均有回归。
