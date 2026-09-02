# P1 Open — 冻结感知实现与后置模型升级

> [TODO 入口](../TODO.md) · [任务目录](README.md)
> 本文件只包含未归档的 P1 感知任务；是否在提交前投入以每项的 `提交决策` 为准。

- [ ] **CG-ANALYSIS-001 — 内容感知的自动曝光、白平衡和轨道平滑**
  - 提交决策：**`FROZEN`。** 继续使用当前内容排除、不确定性、有效样本比例与鲁棒轨迹平滑实现；提交前不再补人工曝光/WB Gold 真值、专家 reviewer 或统计显著性，也不从 Demo 路径删除该能力。
  - 在曝光/WB 估计前排除天空、雪地、霓虹、单一主色等非中性区域。
  - 替换强制 18% 灰和各通道独立 70 分位，输出估计值、有效样本比例和不确定性。
  - 使用 shot 级状态空间、robust trend filtering 或等价方法，替代固定 3 点中值和平面阈值关键帧。
  - 对夜景、雪景、日落、混合光源、快速曝光变化分别评估。
  - 依赖：CG-COLOR-010、CG-EVAL-001、CG-EVAL-002。
  - 完成标准：专家参考和 Gold Set 上的曝光/WB 偏差、闪烁及裁剪风险优于当前基线。
  - 2026-07-29 进度：
    - 已实现 `colorgraph.content-aware-color-analysis/v1`：曝光与 WB 前显式排除天空、雪地、霓虹和单一主色；曝光改为场景 key 保留的鲁棒 log-luma 软放置，WB 改为联合 log-chromaticity 鲁棒位置估计，不再跨通道选取不同对象。
    - 帧级和 shot 级结果均输出曝光/WB 有效样本比例与不确定性，并将估计、轨迹方法和变化点写入 Balance 节点证据；无可信中性样本时保守收缩而不是伪造高置信修正。
    - 固定三点中值和平面差值门槛已替换为测量不确定性加权的 Huber + L1 robust trend filter、自适应曲线简化和持续变化点检测；孤立 1.2 EV 闪烁被压至约 0.029 EV，持续快速曝光变化仍在 1.5 秒形成单一变化点。
    - 雪景、夜景、日落、混合光源、天空加中性地面和快速曝光变化的确定性回归均已覆盖；`test_color_analysis.py` 当前 `18 passed`，后端全量 `545 passed`，证据见 `output/evidence/content-aware-color-analysis.json`。
    - 统一 evaluator 已补齐曝光/WB 的 MAE、bias、相对基线改善、非切点闪烁 P95 和裁剪风险，并通过 v2 规范、完整冻结 test 绑定及 calibration-only gate policy 防止挑样和事后调门槛；工程公式报告保持 `engineering_only`，见 `output/evidence/gold-acceptance-engineering-validation.json`。
    - 现有 Gold Set 仍缺独立专家曝光/WB 真值与 reviewer 签核，尚不能执行完成标准中的冻结集优越性检验；因此本项保持未勾选，不以合成回归冒充 Gold 验收。

- [ ] **CG-REP-001 — 多帧代表帧与鲁棒 shot embedding**
  - 提交决策：**`FROZEN`。** 继续使用当前 3/5/7 帧质量筛选、CLIP medoid 和统一 API/CLI 路径；提交前不再补人工代表帧 Gold、scene 真值或显著性证明，也不退回固定中点实现。
  - 每 shot 自适应抽 3/5/7 帧，避开头尾转场区域。
  - 过滤模糊、黑帧、低熵、严重 clipping。
  - UI/标签使用 cosine medoid；scene grouping 使用 medoid 或鲁棒均值。
  - 合并 API、CLI 中重复的中点帧实现。
  - 完成标准：Gold Set 代表帧可用率和下游 scene 指标显著优于中点基线。
  - 2026-07-29 进度：
    - 已实现 `colorgraph.representative-frames/v1`：按 shot 时长自适应抽取 3/5/7 帧，并以帧率保护区和 12% shot 边距避开头尾转场；候选逐帧记录清晰度、熵、平均亮度、黑帧比例、clipping 比例和拒绝原因。
    - 启用本地 CLIP 时，UI/标签规范帧 `shot_NNN.jpg` 来自有效候选的 cosine medoid；scene grouping 输入改为围绕 medoid 剔除离群点后的归一化鲁棒均值。视觉模型不可用时退回质量筛选结果，不退回未经检查的固定中点。
    - API、CLI 和 `analyze_media` 已统一调用同一候选抽取/选择实现；候选、质量证据、medoid 相似度和选择方法随 Grade Graph 持久化。
    - 真实 6 秒/3 shot 回归片在 CUDA CLIP 上完成 13×512 候选 embedding 与 3×512 shot 聚合，13/13 候选可用；合成离群中点会把同一 scene 错分为两组，而鲁棒多帧聚合恢复为一组。`test_representative_frames.py` 当前 `8 passed`，后端全量 `545 passed`；证据见 `output/evidence/representative-frame-evaluation.json`。
    - 统一 evaluator 已按 source group 配对比较候选与中点基线的可用率和下游 scene F1，并输出 source-cluster bootstrap CI；严格 Gold 模式要求精确覆盖全部合格 test material，工程公式证据见 `output/evidence/gold-acceptance-engineering-validation.json`。
    - 冻结 Gold Set 尚无独立代表帧可用性标注和完成签核的 scene 真值，不能检验“显著优于”门槛；因此本项保持未勾选。

- [ ] **CG-SCENE-001 — 改造 scene grouping 为校准的全局边界算法**
  - 提交决策：**`DEFERRED`，完整后置。** Demo 保持当前贪心 scene grouping，素材选择 2–4 个清晰硬切镜头；不做全局边界算法的冻结 test 默认切换。
  - 输入多帧 embedding、色彩变化和可选音频变化。
  - 使用 continuous boundary score + hysteresis/动态规划。
  - 在 calibration split 上选择阈值，不硬编码 0.78/0.88。
  - 依赖：CG-REP-001、CG-EVAL-002。
  - 完成标准：冻结 test 的 scene boundary F1 优于当前贪心基线。
  - 2026-07-29 进度：
    - 已实现 `colorgraph.scene-grouping/v2` shadow pipeline：输入鲁棒多帧 shot embedding、曝光/色温/Tint/高光变化、带置信度的地形/光照变化及可选音频 embedding，逐边界保存连续分数和各特征分量。
    - 候选边界使用版本化 calibration 配置和全局动态规划解码；阈值由 `calibrate_scene_grouping` 仅在显式 `calibration` split 上搜索，train/test 输入会被拒绝。默认 bootstrap 配置与来源文件均校验 SHA-256，不再把 0.78/0.88 当作 v2 算法阈值。
    - 在冻结人工 test 尚未就绪前，生产默认 `selection_mode=shadow`：实际 scene 保持旧贪心结果，同时在 Grade Graph 元数据中持久化 v2 分数、候选边界、候选 groups 和 calibration 证据，防止未验收算法静默替换默认行为。
    - 三个确定性 bootstrap 契约样例上，旧贪心为 precision `1.0` / recall `0.5` / F1 `0.6667`，v2 候选为 `1.0 / 1.0 / 1.0`；此结果仅验证代码和校准流程，不是 Gold 结论。`test_scene_grouping.py` 当前 `8 passed`，后端全量 `545 passed`；报告见 `output/evidence/scene-grouping-shadow-evaluation.json`。
    - 统一 evaluator 已加入逐 source 的候选/贪心基线边界 F1 与标签指标比较、source-cluster bootstrap CI、完整 test 绑定和 calibration-only gate policy；工程公式证据见 `output/evidence/gold-acceptance-engineering-validation.json`。
    - 冻结 test 的独立人工 scene 边界仍未完成，因此不能授权默认切换，本项保持未勾选。

- [ ] **CG-DEPTH-001 — Video Depth Anything Small shadow pipeline**
  - 提交决策：**`DEFERRED`，完整后置。** Demo 使用 DA-V2 或已经生成并冻结的深度资产，不现场运行 VDA-S，也不做与 DA-V2 的同域人工 Gold 对测或默认切换。
  - 按 shot/重叠窗口推理，保留 float depth。
  - 使用稳定 scale/shift、shot 级分位数和真实不确定性。
  - 删除逐帧 2/98 重标定和 `confidence=1.0`。
  - 校验 Apache-2.0 Small 权重；不默认使用非商业 Base/Large。
  - 依赖：CG-EVAL-001、CG-EVAL-002。
  - 完成标准：深度时序一致性优于 DA-V2 frame baseline，显存/速度符合 16 GB 目标。
  - 2026-07-30 进度：
    - 默认 DA-V2 Small fallback 已删除逐帧 2/98 重标定和 `confidence=1.0`：首个 anchor 冻结 shot 五分位尺度，后续 anchor 以鲁棒 scale/shift 对齐，并输出有效样本比例、对齐残差、真实测量不确定性及 `confidence_is_accuracy=false`；镜头切换会重置尺度。
    - 已实现可选 `colorgraph.video-depth-shadow/v1`：每 shot 调用官方 VDA-S，官方内部按 32 帧/10 帧重叠窗口对齐；结果保留 float32 inverse-depth NPZ、全 shot 归一化深度、逐帧仿射时序残差不确定性和逐 shot 统计，不接管默认 mask。
    - 冻结 manifest 只允许 Apache-2.0 `vits` Small：锁定官方 repo commit、116,440,756 字节 checkpoint 与 SHA-256；Base/Large 非商业权重不能成为默认。`depth-shadow-audit` 必须同时通过 Git commit、许可证、文件名、大小和哈希，`depth-shadow` 才会启动隔离 bridge。
    - 真实本地回归片上的现有 fallback，逐帧 2/98 时序 MAE `0.0006158542`，shot 尺度为 `0.0005821427`；专项 `7 passed`，后端全量 `545 passed`。实现和阻塞证据见 `output/evidence/video-depth-shadow-audit.json`。
    - 在用户授权下已安装官方 VDA-S repo/checkpoint 并通过固定 revision、文件
      大小、Apache-2.0、checkpoint 文件 SHA-256
      `13379300…609` 与严格加载状态 SHA-256 `da258723…101` 审计。
      真实 150 帧/3-shot CUDA 运行保留 float32 depth 与仿射时序残差：
      inference `0.380 FPS`、cold `0.351 FPS`、峰值 GPU
      `8039.08 MiB`、memory growth `143.26 MiB`，输出 NPZ SHA-256
      `f4e20b3f…d2c`。证据见
      [`depth-001-vda-small-shadow-report.json`](../../output/evidence/depth-001-vda-small-shadow-report.json)。
      模型、许可、checkpoint、16 GB 和真实 runtime 的机器侧门已完成；与 DA-V2
      同域人工 Gold 时序质量比较按当前指令延后，因此不授权默认切换，本项保持
      未勾选。
    - 为生产矩阵另以官方 frame Depth Anything V2 Small exact revision
      `5426e4f0…ef99` 和 state-dict SHA-256 `31bf8a51…14a` 生成完整
      7423 帧 `mask_depth_far`：83 个模型 anchor 间使用 Farneback 传播，
      16-bit FFV1 SHA-256 `cebd1636…a24`，完整解码与来源 SHA 均通过。
      该资产和 Video Depth Anything Small 是两个明确分离的候选，证据见
      [`bench-001-formal-tracked-mask-assets.json`](../../output/evidence/bench-001-formal-tracked-mask-assets.json)；
      它补齐机器资产，不构成人工 Gold 或默认模型授权。
