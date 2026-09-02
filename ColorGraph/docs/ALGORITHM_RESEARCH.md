# ColorGraph 关键算法审计与替代方案调研

> 调研日期：2026-07-28（Asia/Shanghai）  
> 目标：统计当前关键算法，识别正确性、画质和性能上限，并调研质量优先的可落地替代。  
> 执行清单：见 [TODO.md](TODO.md)。  
> 结论边界：外部论文或官方 benchmark 只用于筛选候选；未经 ColorGraph 真实素材 Gold Set 对测，不视为本项目质量提升已经成立。

## 1. 调研方法与规模

本轮将代码链拆为三个相互独立的专题审查：

1. 色彩科学、调色算子、关键帧、LUT、渲染和导出；
2. 镜头、代表帧、场景理解、语义/深度蒙版和时序传播；
3. 自动曝光/白平衡、自然语言规划、候选排序、质量评估和自动修复。

静态统计结果：

| 项目 | 数量 |
| --- | ---: |
| `backend/colorgraph` Python 文件 | 54 |
| Python 总行数 | 6,196 |
| 算法密集文件 | 18 |
| 算法密集代码行数 | 约 3,290 |
| 算法密集代码占比 | 约 53.1% |
| 归纳后的关键算法组 | 14 |

现有 `pytest` 共 165 项并全部通过，已经加入标准传递函数/Sony 参考、完整 OCIO 2.5.2 / ACES 2 v3 运行时、标准 v3 调色算子、非均匀时间 PCHIP、tetrahedral/shaper/CLF/CTF LUT、CFR/VFR、逐场景 LUT、作用域撤销、mask 资产损坏门禁、统一指标/盲测、跨后端精度报告和 Gold Set 真实/人工审计；但仍没有达到配额的人工视频 Gold Set、分割真值或真实专家偏好，也没有 ROCm 实机报告。因此“测试通过”仍不等于全部色彩与感知质量已经验证。

## 2. 执行摘要

质量优先时，推荐顺序不是先替换大模型，而是：

1. 修复已经可以从代码和标准参考中确认的色彩、位深、LUT 与作用域错误；
2. 建立 Landscape Gold Set，让所有模型替换有统一判定依据；
3. 落地高位深、显式元数据、OCIO/ACES 2 色彩管理；
4. 对镜头、场景、语义、深度和时序蒙版候选进行 shadow benchmark；
5. 最后升级偏好排序、质量评分和自动修复。

审计最初确认的主要质量风险位于色彩基础链路，而不是单个视觉模型；截至 2026-07-28，可由当前仓库和 CUDA 开发机闭环的确定性修复已经完成，P0 只剩 ROCm 实机证据与外部人工数据门槛：

- Sony S-Gamut3.Cine 到 Rec.709 的手写矩阵曾存在确定性错误，现已改为按官方色度坐标生成；
- Grade Graph 中的输入/输出色彩空间节点曾未执行；v2 已修复显式标准变换，v3 进一步以 OCIO 官方 camera input→ACES2065-1→ACEScg/ACEScct→ACES 2 Output Transform 执行并严格校验；
- 输入色彩/HDR 元数据及 provenance 已完整探测并持久化；CFR/VFR 正式链路已使用 `rgb48le`、FP32、逐帧 PTS 与 HEVC Main10；
- 多场景 LUT 串联和“全片”只修改一个镜头的问题均已修复并加入回归；
- mask 资产缺帧补零和虚假 tracking 元数据也已改为严格完整性门禁。
- CPU/CUDA FP32 像素误差、ΔE2000、preview 和重复确定性已由版本化 `precision-gate` 通过；相同门禁仍须在受支持 ROCm 目标机执行。
- Gold Set 已有真实来源摄取、冻结标注规范和人工/配额审计；6 个授权来源已就绪并生成 19 个不计分的机器草稿，6,078 帧逐帧 PTS 工作包已冻结。夜景与项目声明的 DJI D-Log 覆盖已补齐，仍待扩充配额与独立人工签核；私有 Log 片段不声明公开再分发权。

确定性色彩与量化基础现已闭环；更高质量的分割、深度或 VLM 替换仍必须通过真实 Gold Set、许可、显存和稳定性门禁。

## 3. 已确认的 P0 正确性问题

### 3.1 Sony 色域变换矩阵错误（2026-07-28 已修复）

实现位置：[grading/color.py](../backend/colorgraph/grading/color.py)。

修复前 S-Gamut3.Cine 到 Linear Rec.709 矩阵第三行为：

```text
[+0.044436, -0.195919, 1.151483]
```

由官方 S-Gamut3.Cine 原色和参考变换推导的对应行约为：

```text
[-0.044436, -0.195920, 1.240356]
```

原逆矩阵只是错误正矩阵的逆，因此旧有 forward/inverse round-trip 测试仍能自洽通过。当前实现改为从 Sony/ACES 公布的 S-Gamut3.Cine、Rec.709 与 D65 色度坐标生成正反向矩阵，同时移除 S-Log3 输入的 `0..1` clamp，以保留负值和扩展范围。

验收不再只依赖 round-trip：`test_color_management.py` 已冻结正确矩阵，并覆盖 Sony CV 95/420/598、RGB 原色、灰阶、负值/超范围、24 色 ColorChecker、15° hue sweep 和正反向参考比较；后端全量 165 项测试均通过。

参考：

- [Sony S-Log3/S-Gamut3 技术说明](https://download.pro.sony/FNGP/protein/1237494271390/1237494271406.pdf)
- [ACES 官方 Sony S-Log3/S-Gamut3.Cine CSC](https://github.com/aces-aswf/aces-input-and-colorspaces/blob/main/sony/CSC.Sony.SLog3_SGamut3Cine_to_ACES.ctl)

### 3.2 输入/输出色彩空间节点未执行（2026-07-28 已修复）

修复前，Grade Graph 虽声明 `INPUT_TRANSFORM`、`OUTPUT_TRANSFORM`、`ACESCCT` 和 `LINEAR_REC709`，渲染器却跳过色彩节点，并把非 Sony Log 输入和输出固定按 sRGB 处理。当前实现已经：

- 在 [grading/color.py](../backend/colorgraph/grading/color.py) 中实现相互独立的 sRGB、BT.709 OETF、零黑位 Rec.1886、Linear Rec.709、ACEScct 和已注册 Log profile 转换；
- 在 [grading/engine.py](../backend/colorgraph/grading/engine.py) 中按图顺序真实执行 Input/Output Transform，并校验 graph、media 和节点声明一致；
- 将 [domain/grade_graph.py](../backend/colorgraph/domain/grade_graph.py) 升级为配对的 schema/renderer v2；持久化 v1 项目继续使用 legacy sRGB 行为，版本错配明确拒绝；
- 对含混的 legacy `rec709`、未知空间/profile、缺失或重复 transform、错误作用域/顺序，以及尚不支持的 ACEScct working graph 明确报错，不再静默回退。

数值基线来自 ICC sRGB、ITU-R BT.709、ITU-R BT.1886、ACEScct 规范及 PyOpenColorIO 2.5.2 的官方 ACES 2 内置配置；测试冻结了 18% scene-linear gray 的各编码参考值、分段点、负值/扩展范围、双向变换，以及 ACES2065-1 → sRGB Display / ACES 2.0 SDR 100 nits 的 10 组 reference processor 输出。v3 运行时已逐值复用该基线，并加入 Sony/DJI 官方 camera processor、迁移预览和 v1/v2/v3 版本回放测试；后端全量当前 165 项、全仓 Ruff、TypeScript 与生产构建均通过。

参考：

- [ICC sRGB registry](https://registry.color.org/rgb-registry/srgb)
- [ITU-R BT.709](https://www.itu.int/rec/R-REC-BT.709/en)
- [ITU-R BT.1886](https://www.itu.int/dms_pubrec/itu-r/rec/bt/R-REC-BT.1886-0-201103-I%21%21PDF-E.pdf)
- [ACEScct specification](https://docs.acescentral.com/encodings/acescct/)

### 3.3 色彩元数据不完整与 VFR/PTS 未保留（2026-07-28 已修复）

修复前，[media/probe.py](../backend/colorgraph/media/probe.py) 只持久化基础 codec/pixel format 和用户选择的输入 profile。当前 `MediaInfo` 已保存：

- `color_range`
- `color_primaries`
- `color_transfer`
- `color_space` / matrix coefficients
- HDR mastering/content-light metadata；
- 每项元数据的来源、置信度、原始报告值与冲突状态。

[media/metadata.py](../backend/colorgraph/media/metadata.py) 以 stream 声明优先，保留 container tag 冲突，按 pixel format 推断缺失的 sample depth/chroma，并读取首批帧中的 HDR mastering display 与 MaxCLL/MaxFALL；8-bit Rec.709、10-bit ProRes Log、10-bit HDR10 和冲突 fixtures 以及 ProjectStore round-trip 均已冻结测试。旧项目和用户 Log override 也保留 provenance，而不是覆盖原始报告值。

[grading/video.py](../backend/colorgraph/grading/video.py) 的 CFR 正式链路采用流式 `rgb48le`；VFR 路径按 ffprobe 逐帧 PTS 调色，再用 16-bit PPM、ffconcat `duration` 和 `fps_mode=passthrough` 重建时间轴。两条路径都用 PyTorch FP32 和 16-bit encode handoff，并保留音频、BT.709 VUI、limited range、`hvc1` 与独立 8-bit proxy。正式输出以零为时间原点，但帧间 PTS、帧数和 A/V 起点设有 0.5 ms round-trip 门禁。

真实 fixture 的 PTS 为 0/40/120/200 ms，Main10 输出未被拉平；1024 级 ramp 的 pre-encode 10-bit 投影保留全部码值，CPU/CUDA FP32 golden comparison 也在 `0.5/65535` 通道预算内。DJI 4K ProRes 422 HQ 10-bit CFR 实片和小型 VFR/音频 fixture 均已通过。

### 3.4 多场景 LUT 被错误串联（2026-07-28 已修复）

[exports/package.py](../backend/colorgraph/exports/package.py) 现在先建立逐 scene/look 导出计划，每个 processor 只包含唯一选中 Look。项目级 Post Look 采用显式 `baked_into_each_lut` 策略，保证每份 LUT 可直接复现最终场景外观。

- 每个 `scene_id` / `look_node_id` 单独导出；
- `colorgraph.export-package/v2` 写明合并策略及所有空间、时间、size、interpolation 字段；
- 无 Look 输出技术变换，legacy 孤立 Look 仍逐个导出；
- 单/多 scene、无 Look、Post Look 测试直接检查 processor 节点集合。

### 3.5 项目级自然语言作用域错误（2026-07-28 已修复）

[agent/planner.py](../backend/colorgraph/agent/planner.py) 的 v2 grammar 采用逐 shot 展开模型：

- project/scene/shot 命令修改所有适用 Balance 并同步偏移相应 keyframe；
- 半镜头等部分范围创建 scoped overlay；
- 带保护目标的全局调整生成 `NOT target` 组合 mask；
- edit range、失效范围和精确 `undo_graph` 均有 9 项组合回归。

## 4. 十四组关键算法与替代建议

| # | 模块 | 当前实现 | 主要上限 | 质量优先候选 | 建议 |
| ---: | --- | --- | --- | --- | --- |
| 1 | 镜头切分 | 160×90 HSV 直方图与平均亮度；8 FPS；固定阈值与 0.8 秒最短镜头 | 渐变转场漏检；闪光/运动误检；125 ms 量化；短蒙太奇被吞 | TransNetV2、AutoShot；PySceneDetect Adaptive 作为轻量补充 | 在本域硬切/渐变集对测后选择，不直接按公开 F1 替换 |
| 2 | 代表帧 | 每个 shot 取时间中点一帧 | 可能选中模糊、遮挡、曝光异常或转场帧；下游全部受单帧支配 | 3/5/7 帧抽样、异常过滤、embedding medoid/鲁棒均值 | 低风险高收益，优先落地 |
| 3 | 场景理解 | CLIP ViT-B/32、固定英文候选、候选内 softmax | 无 unknown/OOD；粗粒度；分数随候选集合变化；图像重复编码 | SigLIP2；纯视觉分组可另评 DINO 系 embedding | 多标签、独立分数校准、文本缓存；技术风险由确定性像素指标判断 |
| 4 | Scene grouping | 相邻 shot cosine + 固定 0.78/0.88 阈值，贪心切分 | 正反打误切、重复地点误并、阈值跨域不稳 | 多帧 embedding + 色彩/音频变化；hysteresis 或动态规划 | 先改聚合和全局算法，再考虑更重的专用网络 |
| 5 | 曝光/WB/高光 | 320×180；18% 灰假设；RGB 70 分位；3 点中值 | 夜景、雪景、主色场景、混合光源偏差大 | 语义屏蔽后的鲁棒 illuminant/exposure + 状态空间/趋势平滑 | 学习式 AWB 多偏 RAW/相机域，必须本域校准 |
| 6 | 关键帧 | 默认非均匀时间 PCHIP；Fritsch–Butland 切线、缓存 Hermite 区间系数、二分定位；旧 Catmull–Rom 显式兼容 | 当前 max velocity/acceleration 仍是输出包络约束，不是全局最优的真实导数/jerk 约束 | 必要时引入约束五次样条/QP | 默认插值替换已完成；只有创作需求明确后再升级严格动力学约束 |
| 7 | 语义蒙版 | SegFormer-B0 ADE20K，类别概率求和和高斯羽化 | 小目标/边界弱；类别 alias 过宽；逐帧独立 | SegFormer-B5 低迁移升级；OneFormer 质量候选 | 先修 alias，再以逐类 IoU/Boundary-F 决定模型 |
| 8 | 深度蒙版 | Depth Anything V2 Small；每帧 2/98 分位归一；置信度固定 1.0 | 深度呼吸；near/mid/far 阈值不稳定；假置信度 | Video Depth Anything Small | 按 shot/重叠窗口推理，保存 float depth 和稳定 scale/shift |
| 9 | 时序蒙版 | 1.5 秒 anchor + 单向 Farneback warp + 高斯模糊 | 遮挡、显露、大运动和视差漂移；边缘逐次侵蚀 | SAM 2.1、SAM 3.1；Cutie 备选；光流 fallback 可评 SEA-RAFT | SAM 2.1 作为生产候选；SAM 3.1 作为许可/显存/Windows 门禁后的质量试点 |
| 10 | Mask Graph/资产 | shunting-yard fuzzy 逻辑；PNG/FFV1；v2 frame/size/FPS/alias/SHA-256/全解码门禁；缺帧默认报错 | 软边缘仍为 8-bit；几何/形态学/SDF 未实现 | 增加 morphology/SDF/probabilistic 模式、16-bit matte | 资产正确性已修复，下一步提升表示精度 |
| 11 | 色彩管理/调色算子 | renderer v3 固定 OCIO 2.5.2 / ACES 2 Studio Config；官方 camera input→ACES2065-1→ACEScg，CCT+Duv/xy + CAT16/Bradford WB，ASC CDL no-clamp，ACEScct/AP1 creative，ACES 2 Output Transform；v1/v2 保留 | OCIO 边界尚为 CPU processor；ROCm 数值门禁未实测；更完整的 gamut volume 指标待补 | OCIO GPU processor/device cache；必要时评估 GradingPrimary/Tone processor | 标准算子迁移已完成，下一步优化设备缓存和专项指标 |
| 12 | LUT | `.cube` 1D shaper/3D/组合；33³/65³/HDR；PyTorch tetrahedral + trilinear compatibility；CLF/CTF OCIO processor；摘要/device/dtype 缓存 | 大分辨率 tetrahedral 尚可评估融合 kernel；gamut volume/LUT 连续性专项指标待补 | 融合 tetrahedral kernel；CLF/CTF GPU processor | 质量与失效正确性已完成，后续只在基准证明收益时优化 kernel |
| 13 | Planner/候选排序 | 关键词固定增量；4 套 Look；50/30/20 固定权重；规则胜场 | 意图强度/冲突弱；单帧；并非学习到的人类偏好 | typed DSL + 确定性 validator；Pareto 硬筛选；领域 Bradley–Terry | VLM 只生成结构化意图，不直接修改像素 |
| 14 | QA/自动修复 | gamma 域统计、固定阈值、无运动补偿 flicker/jitter、一次固定步长修复 | 内容运动导致误报；分数未校准；无法定位责任节点 | 技术硬指标 + 运动补偿；DOVER/TOPIQ 辅助；节点消融 + 约束局部搜索 | 学习评分只能辅助，不能替代合法范围和色彩硬检查 |

## 5. 替代方案的工程判断

### 5.1 镜头与代表帧

- [TransNetV2](https://github.com/soCzech/TransNetV2) 为 MIT，官方提供 PyTorch 推理，是成熟的首个 shadow candidate。
- AutoShot 公开结果更高，但权重分发和工程成熟度弱于 TransNetV2，必须在本域素材上对测。
- 多帧代表帧聚合对场景标签、分组、缩略图、候选排序同时生效，优先级高于单纯放大 CLIP。

推荐每个 shot：

```text
K = min(7, max(3, ceil(duration_seconds / 2)))
```

避开头尾 5%–10%，过滤模糊、黑帧、严重裁剪和转场，再选择 cosine medoid。

### 5.2 场景 embedding

[SigLIP2](https://arxiv.org/abs/2502.14786) 是当前 CLIP ViT-B/32 的主要候选。迁移时不能沿用“候选 softmax 等于置信度”的逻辑：

- 图像只编码一次；
- 文本 embedding 常驻缓存；
- terrain/lighting 使用多标签；
- 保留 raw cosine/logit；
- 在 Gold Set 上校准 temperature、threshold 和 unknown；
- clipping、曝光、饱和、色域等风险由确定性像素指标计算。

### 5.3 语义与视频对象分割

质量路线建议并行保留两条：

1. SegFormer-B5/OneFormer 生成稳定语义 anchor；
2. SAM 2.1 或 SAM 3.1 负责视频传播和边界一致性。

[SAM 3.1 官方发布](https://github.com/facebookresearch/sam3/blob/main/RELEASE_SAM3p1.md) 报告 VOS 在 7 个 benchmark 中有 6 个提升，Object Multiplex 在 H100、128 对象条件下约 7 倍加速。该数字不能外推到本项目 RTX 5060 Ti。其自定义许可、Windows kernel、CUDA/Triton 依赖和长视频显存必须先验证。

[SAM 2.1](https://github.com/facebookresearch/sam2) 为 Apache-2.0，模型更轻、生态更成熟，适合作为生产首选候选。无文本 prompt，可由语义模型产生首帧/anchor mask。

2026-07-30 的正式来源审计已固化到
[`formal-model-source-registry-v1.json`](formal-model-source-registry-v1.json)：
VDA-S、frame Depth Anything V2 Small、SAM 2.1、SAM 3.1、SEA-RAFT 与
OneFormer 的代码/权重来源和明示使用、按条款再分发许可门通过；当前
SegFormer-B0 与候选 B5 的 NVIDIA 官方条款仅允许非商业研究/评估，不能直接
作为商业默认；Cutie 代码为 MIT，但官方权重未找到独立、明确的公开分发许可。
VDA-S、frame Depth Anything V2 Small、SAM 2.1、SEA-RAFT 与 OneFormer 已安装
内容 SHA-256 并完成本机 runtime；frame Depth Anything V2 Small 与 OneFormer
还生成并完整解码复核了 7423 帧正式性能资产。两个深度候选仍缺同域人工 Gold，
SAM 3.1 代码/许可已就绪但仍被 Hugging Face gated checkpoint 访问阻断。
来源门与机器 runtime 都不替代固定人工 Gold Set。

平台先决条件也由
[`colorgraph.vos-platform-prerequisite-audit/v1`](../output/evidence/vos-platform-prerequisite-audit.json)
单独审计：Windows CUDA 与 WSL2 GPU 可见不等于模型部署通过；当前 Ubuntu 22.04
仍缺 Python 包管理器/torch，且 native Linux、ROCm 与 SAM 3.1 Linux 路径未验收；
Windows CUDA 上的 SAM 2.1、Cutie 和 SEA-RAFT 已有真实推理证据。

### 5.4 视频深度

[Video Depth Anything](https://github.com/DepthAnything/Video-Depth-Anything) 专门针对长视频一致性：

- Small：28.4M，Apache-2.0；
- Base/Large：CC-BY-NC-4.0，不作为商业默认；
- 官方 A100、`1×32×518×518` FP16 数据为 7.5 ms、6.8 GB；
- streaming 模式官方同时报告了精度下降，质量模式不应默认启用。

本项目应选择 Small，并在 RTX 5060 Ti 上重新记录真实速度、峰值显存和长视频稳定性。

### 5.5 色彩管理与 LUT

推荐基础架构：

```text
输入媒体及元数据
→ 官方 Input Transform
→ ACEScg/AP1 scene-linear：曝光、CCT+Duv/xy + CAT16/Bradford 白平衡
→ ACEScct：ASC CDL no-clamp、18% pivot 对比度、AP1 灰轴饱和度和区域 tone
→ ACES 2 Output Transform：tone/chroma/gamut/display encoding
→ 高位深 master / 抖动后的低位深 proxy
```

参考：

- [OpenColorIO 文档](https://opencolorio.readthedocs.io/en/latest/)
- [OCIO Grading Transforms](https://opencolorio.readthedocs.io/en/v2.4.2/api/grading_transforms.html)
- [ACES 2 Output Transform](https://docs.acescentral.com/system-components/output-transforms/)
- [ACES 2 Gamut Compression](https://docs.acescentral.com/system-components/output-transforms/technical-details/gamut-compression/)

OCIO 将 tetrahedral 列为 3D LUT 的最佳插值选项，而默认插值仍是 trilinear：

- [OCIO Interpolation enum](https://opencolorio.readthedocs.io/en/v2.5.0/api/enums.html)

### 5.6 关键帧

默认 Catmull–Rom 已替换为按真实秒数计算的 [PCHIP](https://docs.scipy.org/doc/scipy/reference/generated/scipy.interpolate.PchipInterpolator.html)，并保留旧 `cubic_spline` 值作为显式兼容模式。当前实现具备：

- 支持非均匀横坐标；
- 保持输入数据单调性；
- 非光滑数据不超调；
- 一阶导数连续。
- 预计算 Hermite 区间系数并以二分查找定位。

严格速度、加速度或 jerk 约束属于更重的优化问题，只有实际创作需求明确后再引入。

### 5.7 质量评估与修复

当前质量分数是固定阈值和固定扣分，不是人类感知质量模型。建议保留以下硬指标：

- 信号合法范围、NaN/Inf；
- highlight/shadow clipping；
- 色域越界；
- mask 完整性；
- LUT 连续性；
- 输出元数据；
- 结构严重退化。

增加：

- 运动补偿后的 flicker/mask jitter；
- CAMBI 或等价 banding 指标；
- 区域/时间定位证据；
- [DOVER](https://github.com/VQAssessment/DOVER) 等经本域校准的辅助技术/审美评分；
- 责任节点消融；
- “目标指标改善、硬指标不退化、意图漂移受限”的修复接受条件。

VMAF、LPIPS、DISTS 等只能作为结构或编码辅助，不能单独评价艺术调色是否正确。

## 6. 不牺牲质量的性能优化

以下项目不需要等待模型替换：

1. **光流只计算一次**  
   [vision/video_masks.py](../backend/colorgraph/vision/video_masks.py#L185) 当前按 target 调用 `_propagate_mask`，而 Farneback flow 只依赖前后灰度帧。默认 5 个 target 时约 80% 光流计算冗余。应一次计算 flow，再 remap 全部 mask。

2. **批量编码场景图像和文本**  
   CLIP 当前对 terrain、lighting、risk、look 进行重复编码。改为一次图像编码、批量/缓存文本 embedding。

3. **设备级 LUT 缓存（2026-07-29 已完成）**  
   CPU parse 与设备 tensor 已分层缓存；键包含绝对 path、size、mtime/ctime、SHA-256、device 和 dtype，同一路径文件替换会立即失效。

4. **消除逐帧 Python 渲染循环**  
   [grading/engine.py](../backend/colorgraph/grading/engine.py#L195) 在 batch 内逐帧执行 graph。可按相同 scope/参数区间分组、向量化 keyframe 参数，并融合连续算子。

5. **模型生命周期和显存调度**  
   SigLIP2、语义、深度和 VOS 模型不能在 16 GB 卡上无条件永久常驻。应增加串行调度、显存水位、卸载和缓存淘汰。

6. **蒙版流式/批量读取**  
   减少 PNG 中转、重复 CPU 解码、重复 resize 和逐 mask CPU→GPU 传输。

7. **生产长片基准（2026-07-30 运行器、正式资产与矩阵重跑）**
   `colorgraph.production-video-benchmark/v1` 固定
   `no-mask / Farneback / VDA / current / SAM 2.1 × 1080p proxy /
   4K master × cold / warm` 矩阵，逐行输出真实视频、内容摘要、FPS、batch P95、
   峰值 VRAM、codec/bit-depth/precision 和模型资产版本。至少 120 秒、源 SHA-256、
   20 行全覆盖及 current warm 质量门缺一不可；短 smoke、历史上缺 P95/VRAM 的
   成片和 blocked 模型均不能授权生产性能声明。SAM 2.1、OneFormer 与 frame
   Depth Anything V2 Small 的 7423 帧正式资产现已绑定 exact revision、
   checkpoint/state SHA 和视频 SHA；4 个受资产影响的变体已通过 1 秒冒烟。
   提交冻结前完整矩阵已保存 10/20 行、0 failed 的可恢复 checkpoint，仅复用
   输出 SHA 与不变 variant graph 同时通过的 4 个 no-mask 行；其余生产矩阵
   后置，未授权生产声明。当前提交门槛改为受支持 AMD Radeon/ROCm 上的
   12–25 秒 1080p `no_mask` / `current_combined` 代表性基准，不能由现有
   NVIDIA 长片数据替代。已冻结的 12.5 秒 CC BY-SA 4.0 短片、3 镜头和 5 个
   蒙版资产在 NVIDIA/CUDA 上完成两行工程预检：0 failed、组合行硬质检通过，
   但 `mask_jitter` 仍为感知风险；报告保持 `partial` 且禁止生产声明，仅说明
   输入到硬质检的执行链已就绪。专用 AMD audit 进一步绑定官方支持型号、
   ROCm/HIP、实机驱动、runner 源码摘要及 fresh-render origin，并拒绝跨设备
   checkpoint；当前 CUDA 证据准确停在 11/16 项，不会被自动提升为 AMD 结论。

## 7. Landscape Gold Set 与验收门槛

在宣称任何替代“更好”之前，至少建立以下子集：

| 子集 | 建议规模 | 标注/判断 |
| --- | ---: | --- |
| 镜头边界 | 50–100 段 | hard cut、fade、dissolve、flash、短镜头；边界或转场区间 |
| 代表帧/场景 | 30–50 个 shot | 可用代表帧、terrain、lighting、scene boundary、unknown |
| 语义蒙版 | 30–50 个 shot 的关键帧 | sky、water、vegetation、mountain/rock、building/road 等逐像素标注 |
| 时序蒙版 | 10–20 段复杂视频 | 遮挡、显露、视差、快速运动、树梢、水面、雾气 |
| 深度 | 10–20 段 | shot 内相对顺序和时序一致性；必要时稀疏标尺 |
| 调色偏好 | 每个场景多候选 | 至少 3 名有经验评审者的成对偏好和拒绝理由 |
| 色彩参考 | 标准 ramp/色卡/hue sweep | 官方 CSC/OCIO/ACES 参考输出 |

统一报告：

- 镜头：F1（±1 帧）、渐变转场区间 IoU；
- 代表帧/场景：可用率、标签 macro-F1、scene boundary F1；
- mask：逐类 IoU、Dice、Boundary F-score；
- 时序：运动补偿后的 mask stability、遮挡恢复、anchor 跳变；
- depth：shot 内 temporal consistency、scale/shift stability；
- 色彩：ΔE2000/ΔEITP、灰轴、高光 hue、gamut/clipping、banding；
- 排序：pairwise accuracy、Bradley–Terry log loss、评审一致性；
- 工程：1080p/4K FPS、P95 latency、峰值 VRAM、冷/热启动和长视频稳定性。

主观评审流程参考：

- [ITU-R BT.500-15](https://www.itu.int/rec/R-REC-BT.500-15-202305-I/en)
- [ITU-T P.910 (10/2023)](https://www.itu.int/rec/T-REC-P.910-202310-I/en)

截至 2026-07-29，严格 manifest、程序化 train/calibration/test bootstrap、统一 runner、专家盲测 schema、冻结人工标注规范、真实来源摄取和 `landscape-p0/v1` 审计均已实现，详见 [EVALUATION_PROTOCOL.md](EVALUATION_PROTOCOL.md)。当前摄取队列有 6 个可商用授权来源、5 个明确相机型号和 19 个机器镜头草稿；夜景与项目声明的 DJI D-Log 覆盖已补齐，6,078 帧逐帧 PTS 工作包已冻结。机器草稿不计作真值，配额与独立人工复核尚未完成，因此所有感知模型替换仍只能进入 shadow mode。

## 8. 推荐实施顺序

### 阶段 A：确定性修复（除 ROCm 实机门禁外已完成）

- Sony 官方参考变换；
- 输入/输出节点执行；
- 媒体元数据；
- 高位深 decode/render/encode；
- 逐场景 LUT；
- project-level 命令作用域；
- mask 资产完整性和真实 tracking metadata。

### 阶段 B：Gold Set 和质量门禁（基础设施与初始真实摄取完成，人工数据待补齐）

- 数据/许可清单；
- 标注规范和冻结测试集；
- 指标脚本与可复现报告；
- CPU/CUDA golden image；
- 1080p/4K 性能与显存基线。

### 阶段 C：低风险算法升级

- 多帧代表帧；
- PCHIP；
- 设备 LUT/text embedding 缓存；
- 光流一次计算、多 mask remap；
- SegFormer alias 修复及 B5 shadow；
- VDA-S shadow。

### 阶段 D：重模型试点

- TransNetV2/AutoShot；
- SigLIP2；
- OneFormer；
- SAM 2.1；
- SAM 3.1 许可和兼容性试点；
- DOVER/TOPIQ 辅助评分。

### 阶段 E：偏好和自动优化

- Pareto 候选生成；
- 领域 Bradley–Terry 排序；
- typed VLM planner；
- 节点责任消融；
- 约束局部/Bayesian repair search。

所有具体任务、依赖和完成标准见 [TODO.md](TODO.md)。

## 9. 风险与约束

- 研究候选的转正条件已固化为
  [`colorgraph.research-watch-gate/v1`](research-watchlist-v1.json)：代码与权重分别核验许可和
  不可变 revision/hash，并要求可复现报告、目标机峰值不超过 16 GB、Windows 或 ROCm 实测通过、
  Gold Set 报告通过。论文、公开仓库或上游 benchmark 单独存在都不构成转正证据。
- 当前开发机为 Windows、RTX 5060 Ti 16 GB、CUDA；VDA-S、SigLIP2、
  SegFormer-B0/B5、OneFormer、SAM 2.1、Cutie、SEA-RAFT、TransNetV2 与
  AutoShot 已有本机速度/显存或内存证据，尚未完成的模型必须继续 fail-closed。
- SAM 3.1 使用自定义许可，且对 CUDA/Triton/Linux 路径依赖更重；不能因为公开质量高就直接设为默认。
- Video Depth Anything Base/Large 为非商业权重；默认只评 Small。
- 模型来源和许可证已由
  [`colorgraph.formal-model-source-registry/v1`](formal-model-source-registry-v1.json)
  分代码/权重审计：SegFormer-B0/B5 非商业，VDA-S、frame Depth Anything
  V2 Small、OneFormer、SAM 2.1、SAM 3.1、SEA-RAFT 的来源许可门通过；
  Cutie 权重公共分发许可仍阻断，SAM 3.1 则阻断于 gated checkpoint 和本机
  runtime；两个 Small 深度候选虽已完成本机 runtime，仍不替代人工 Gold Set。
- ACES/OCIO 迁移会改变现有参数手感和已保存项目外观，必须版本化。
- 质量模型的公开相关性来自其训练数据，不代表风景专业调色偏好。
- ROCm 兼容性仍需按 [ROCM_BACKEND.md](ROCM_BACKEND.md) 独立验收。
