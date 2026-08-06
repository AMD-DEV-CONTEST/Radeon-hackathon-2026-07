# P2 Open — 提交后置的模型 Shadow、排序与质量闭环

> [TODO 入口](../TODO.md) · [任务目录](README.md)
> 本文件中的 8 项均为 `DEFERRED`，提交前停止模型替换、正式对测和生产验收。创意 Agent 任务见 [active-p2-agent.md](active-p2-agent.md)。

## 模型 shadow benchmark

- [ ] **CG-SHOT-010 — TransNetV2 与 AutoShot 同域对测**
  - 提交决策：**`DEFERRED`，完整后置。** Demo 保留当前 detector/PySceneDetect，并选择 2–4 个清晰硬切镜头；不做 TransNetV2、AutoShot 的完整同域对测或默认切换。
  - 对 hard cut、fade、dissolve、flash、短镜头分别报告。
  - 保留当前 detector 和 PySceneDetect Adaptive 作为 CPU fallback。
  - 记录速度、峰值内存、模型许可和权重来源。
  - 依赖：CG-EVAL-001、CG-EVAL-002。
  - 完成标准：冻结 test 上达到预设提升后才切换默认模型。
  - 2026-07-30 工程进度：
    - 已实现 `colorgraph.shot-model-shadow-evaluation/v1` 与
      `shot-shadow-eval` CLI；固定要求 current detector、PySceneDetect Adaptive、
      TransNetV2、AutoShot 四行完整覆盖，同一冻结输入上逐项记录代码/权重来源、
      商用许可、source revision、checkpoint SHA-256、FPS、CPU/GPU 峰值和逐素材预测。
    - 指标分开报告 hard cut、fade、dissolve、flash 误触发与 short-shot；候选必须
      整体 F1 达到预设提升、各真实转场 recall 不低于门槛/基线回退预算且 flash
      误触发不超限。缺任一模型、许可、哈希、转场覆盖或性能行都保持
      `partial/shadow_only`。
    - 即使四行合成 fixture 全部完成，也只有冻结、真实、独立复核且绑定 Gold
      manifest/audit SHA-256 的 test 才可能给出默认候选；专项 `5 passed`，全量
      `545 passed`。当前状态证据
      [`shot-010-engineering-shadow.json`](../../output/evidence/shot-010-engineering-shadow.json)
      明确将未实测模型标为 blocked，未用论文结果冒充本域实测。
    - PySceneDetect Adaptive CPU fallback 已精确锁定 `scenedetect-headless 0.7.1`：
      BSD-3-Clause、官方 source revision
      `6ebb72392de8acfb6c539bf15d0aa912ce7ab6b2` 与 wheel SHA-256 均持久化；
      显式适配器不会替换当前默认 detector，hard-cut/无切点专项 `3 passed`。
      工程报告的 PySceneDetect 来源冻结 blocker 已消除；适配器 smoke 与后续
      独立采集的工程 observation 分开记录。
    - 新增 `shot-shadow-observe`：只允许 current detector 或 PySceneDetect，
      写 observation 前要求 `ITEM_ID=PATH` 精确覆盖 bundle，并逐项复核真实媒体
      SHA-256、帧数与 FPS；记录真实预测边界、耗时、进程峰值 RSS，输入篡改直接
      拒绝。采集专项 `2 passed`。本机另用 60 帧、10 FPS、内容与标注 SHA-256
      冻结的 FFV1 程序片完成两次真实 CPU 采集；current detector 与
      PySceneDetect Adaptive 均只预测第 30 帧硬切。报告
      [`shot-010-cpu-observation-report.json`](../../output/evidence/shot-010-cpu-observation-report.json)
      保持 `partial/shadow_only`，该单类工程 observation 不冒充完整转场冻结集
      或人工 Gold。
    - 已安装并冻结官方 TransNetV2 代码与两份独立封装但严格加载后状态一致的
      PyTorch checkpoint；真实 hard-cut 推理仅命中第 29 帧，约 `176.77 FPS`。
      AutoShot 官方代码固定为 revision `77c82ff…d081`，经用户授权从官方百度盘
      取得 `ckpt_0_200_0.pth`；本地文件 SHA-256
      `3e852905…1fa6`、加载状态 SHA-256 `8a047787…961a`，官方结构
      `90/90` 参数严格加载通过。真实 hard-cut 推理仅命中第 29 帧，约
      `29.28 FPS`；上游测试阈值 `0.296` 只作为工程观察值，不冒充本域校准。
    - 新增 320 帧无损工程转场矩阵，覆盖 hard cut、fade、dissolve、flash 和
      short-shot entry/exit。四行均为真实本机推理：current detector、
      PySceneDetect、TransNetV2、AutoShot 的整体 F1 分别为
      `0.833/0.800/1.000/0.769`；TransNetV2 为唯一通过工程候选门的行。
      报告与全部模型/媒体身份见
      [`shot-010-transition-matrix-report.json`](../../output/evidence/shot-010-transition-matrix-report.json)。
      该矩阵是程序化 engineering fixture，不是冻结人工 Gold；因此默认切换仍
      禁止，本项保持未勾选。

- [ ] **CG-VLM-010 — SigLIP2 scene/intent shadow pipeline**
  - 提交决策：**`DEFERRED`，完整后置。** Demo 保留当前 CLIP，不下载、切换或现场比较 SigLIP2，也不追加专家 scene/intent Gold 验收。
  - 图像只编码一次，文本批量编码并缓存。
  - terrain/lighting 多标签；增加 unknown/OOD。
  - 保存 raw cosine/logit，并在 calibration split 做温度/阈值校准。
  - 技术 clipping/exposure/saturation 风险移出 VLM。
  - 依赖：CG-REP-001、CG-EVAL-002。
  - 完成标准：标签、检索和候选意图指标优于 CLIP，且 VRAM/延迟可接受。
  - 2026-07-30 工程进度：
    - 已实现 `colorgraph.siglip2-scene-shadow/v1` 与
      `colorgraph.vlm-shadow-calibration/v1`。影子路径复用内容寻址图像缓存，一次
      批量编码所有图像、一次批量编码并缓存冻结文本标签；运行模型 ID、40 位
      revision 和标签定义摘要必须与校准产物精确匹配。
    - 不沿用 CLIP 候选集合 softmax：SigLIP2 路径保存 raw cosine 与 scale/bias
      后的 raw logit，按独立 sigmoid 输出多标签概率；温度、逐标签阈值、unknown
      概率和最低 cosine 只允许从 `calibration` split 拟合，显式报告类别 unknown
      与整帧 OOD。技术 clipping/exposure/saturation 风险继续由
      `colorgraph.content-aware-color-analysis/v1` 提供，不进入 VLM prompt。
    - 本地 VLM runtime/cache 与 calibration 产物现在同时绑定显式 revision、
      实际加载 `state_dict` 的规范 SHA-256 及哈希算法标识；同名模型换权重后旧
      embedding 或校准产物会 fail-closed，不会静默复用。
    - `vlm-shadow-calibrate` 已用纯工程 bootstrap fixture 生成
      [`vlm-010-bootstrap-calibration.json`](../../output/evidence/vlm-010-bootstrap-calibration.json)；
      状态为 `bootstrap_not_gold`，不会授权默认模型切换。
    - 新增 `colorgraph.vlm-shadow-runtime-observation/v1` 与
      `vlm-shadow-observe`：重新计算并绑定校准 source，按 exact revision 强制
      `local_files_only=true`，无论完成、缓存阻塞或运行失败都原子写入报告；同时
      记录输入帧 SHA-256、运行环境、进程生命周期 CPU 峰值、运行段 GPU 峰值、
      FPS 和实际 shadow 输出，且永不授权默认模型。
    - 本机用 CC BY-SA 4.0 的 Sony DSC-RX10 III 原片抽取一张真实 512×288 帧，
      冻结来源、许可、媒体/帧哈希与“非 Gold”限制。随后在用户授权下安装 exact
      SigLIP2 revision 并完成真实 shadow 推理：checkpoint 加载状态 SHA-256、
      输出标签/raw cosine/logit、缓存身份、`0.170 FPS` cold throughput 和
      `1807.23 MiB` 峰值 GPU 全部写入
      [`vlm-010-siglip2-local-runtime-observation.json`](../../output/evidence/vlm-010-siglip2-local-runtime-observation.json)。
      早期 cache-miss 报告保留为可审计过程证据，不再代表当前安装状态。
    - 模型安装、许可、checkpoint 与真实延迟/显存的机器侧缺口已经消除；仍无本域
      calibration/test 人工 Gold 和同矩阵 CLIP 对照。人工 Gold 已按当前项目指令
      延后，故不授权默认切换，本项保持未勾选。

- [ ] **CG-SEM-010 — SegFormer-B5 与 OneFormer 语义对测**
  - 提交决策：**`DEFERRED`，完整后置。** 不完成 B0/B5/OneFormer 本域逐像素人工对测；Demo 使用当前模型或已有 OneFormer 蒙版资产，不据此宣称候选已获默认切换资格。
  - 核验代码和 checkpoint 许可。
  - 报告逐类 IoU、Boundary-F、时序 anchor 稳定性、速度和 VRAM。
  - 先以 B5 作为低迁移候选，OneFormer 作为质量上限候选。
  - 依赖：CG-SEM-001、CG-EVAL-002。
  - 完成标准：按水面、树梢、山体等关键类而非仅 macro 指标选择。
  - 2026-07-30 工程进度：
    - 已实现 `colorgraph.semantic-model-shadow-evaluation/v1` 与
      `semantic-shadow-eval` CLI；固定要求当前 SegFormer-B0、SegFormer-B5、
      OneFormer ADE20K Swin-Large 三行完整覆盖并逐行保存代码/权重许可、
      source revision、checkpoint 与标签映射 SHA-256、操作系统、runtime 和 precision。
    - 同一冻结输入按 water/vegetation/mountain 分开聚合 IoU、Dice、
      Boundary precision/recall/F、运动补偿后的时序稳定性，并同时报告 FPS、
      CPU/GPU 峰值；任一关键类回退都不能被 macro 平均掩盖。B5 为低迁移优先项，
      只有 OneFormer 额外质量收益超过冻结门槛才越过 B5。
    - 纯工程计数 fixture 的专项 `5 passed`；证据
      [`sem-010-engineering-shadow.json`](../../output/evidence/sem-010-engineering-shadow.json)
      为 `partial/shadow_only`。正式来源审计确认当前 B0 与候选 B5 受 NVIDIA
      非商业许可限制；OneFormer 代码/权重为 MIT 且 revision 已冻结，但仍无本机
      checkpoint SHA、标签映射审计、Gold 与 runtime 报告，见
      [`formal-model-source-audit.json`](../../output/evidence/formal-model-source-audit.json)。
    - SegFormer 与 Depth Anything 生产加载器已支持显式 revision，并在移动设备/
      FP16 转换前对实际加载状态生成规范 SHA-256；revision、哈希与算法标识会随
      prediction 提升到 mask 资产顶层元数据。旧资产不做追溯补写，因此正式矩阵
      仍能准确暴露既有资产的 provenance 缺口。
    - 新增 `colorgraph.semantic-runtime-observation/v1` 与
      `semantic-shadow-observe`：正式来源登记、模型 ID/exact revision、
      本地缓存模式、标签映射、state-dict 哈希、真实帧/逐目标 mask 哈希、
      cold load+hash+inference FPS 及 CPU/GPU 峰值全部绑定，完成与缓存阻塞均
      原子写入；无 Gold 与非商业许可会固定禁止质量/商业默认声明。
    - 本机在许可和哈希冻结的 Sony DSC-RX10 III 真实帧上完成当前 B0：
      revision `489d5cd8…77da`、state-dict SHA-256 `ccce07e3…79f9`、
      cold `0.2298 FPS`、峰值 GPU `213.94 MiB`；water/vegetation/mountain
      均有实际 mask 摘要；见
      [`sem-010-current-b0-local-runtime-observation.json`](../../output/evidence/sem-010-current-b0-local-runtime-observation.json)
      。早期 B5 cache-miss 报告保留为过程证据。
    - 在用户授权下又完成 B5 与 OneFormer exact revision 的本机真实推理。
      B5 state-dict SHA-256 `ac39b63e…7ef2`、`0.2291 FPS`、峰值 GPU
      `1001.64 MiB`；OneFormer state-dict SHA-256 `729a949c…8ae`、
      `0.1233 FPS`、峰值 GPU `1288.68 MiB`，两者均保存三个目标的实际 mask
      摘要。OneFormer 适配器按官方 `semantic` task token 与 semantic score-map
      后处理实现，并保留上游兼容性 warning；证据见
      [`sem-010-segformer-b5-local-runtime-observation.json`](../../output/evidence/sem-010-segformer-b5-local-runtime-observation.json)
      和
      [`sem-010-oneformer-local-runtime-observation.json`](../../output/evidence/sem-010-oneformer-local-runtime-observation.json)。
    - 同一冻结 OneFormer revision/state 已用于 123.84 秒、7423 帧 DJI 原片的
      83 个语义 anchor，生成 sky/vegetation/water/mountain 四个完整 16-bit
      FFV1 资产；四个视频 SHA-256、源片 SHA、帧数/FPS/pixel-format 和模型身份
      均通过完整解码复核。报告
      [`bench-001-formal-tracked-mask-assets.json`](../../output/evidence/bench-001-formal-tracked-mask-assets.json)
      SHA-256 为 `b34392ee…f76`。这补齐正式性能矩阵的语义资产，但不替代逐类
      人工 Gold。
    - [`formal-model-source-audit.json`](../../output/evidence/formal-model-source-audit.json)
      现将 OneFormer 标为来源、许可、安装和 runtime 全部 ready；B0/B5 的机器
      运行虽完成，上游 NVIDIA 非商业条款仍如实保留，用户项目授权不改写该条款。
      仍无三模型本域逐像素人工 Gold 和同矩阵 warm latency，因此不做质量默认
      选择，本项保持未勾选。

- [ ] **CG-VOS-010 — SAM 2.1 视频蒙版生产候选**
  - 提交决策：**`DEFERRED`，完整后置。** 不把 SAM 2.1 切成生产默认；Demo 可使用已经生成、哈希冻结并通过硬质检的 SAM 2.1 蒙版资产，不现场做五类失败场景或跨平台矩阵。
  - 使用语义 anchor mask 初始化。
  - 测试遮挡/显露、长程漂移、anchor 跳变、对象消失和重现。
  - 记录 Windows/WSL/Linux、CUDA/ROCm 可用性和峰值显存。
  - 依赖：CG-EVAL-002、CG-SEM-001。
  - 完成标准：时序/边界指标优于 Farneback，长视频在目标显存内稳定完成。
  - 2026-07-30 工程进度：
    - 已实现统一 `colorgraph.video-object-mask-shadow-evaluation/v1` 与
      `vos-shadow-eval` CLI；Farneback、SAM 2.1、SAM 3.1、Cutie、SEA-RAFT
      五行使用同一冻结 item 集，强制覆盖遮挡、显露、长程漂移、anchor 跳变和
      对象消失/重现。
    - 每场景分别报告 temporal IoU、Boundary-F、drift stability、丢失 object-frame
      比例、identity switch 与重现召回，并记录 FPS、CPU/GPU 峰值和长视频
      memory growth。SAM 2.1 还必须证明语义 anchor 初始化、许可/权重哈希、
      平台矩阵与至少一个真实 CUDA/ROCm 部署组合。
    - 专项工程 evaluator 当前
      [`vos-010-012-engineering-shadow.json`](../../output/evidence/vos-010-012-engineering-shadow.json)
      仍为 `partial/shadow_only`，不会把程序化时序指标当成 Gold。
    - 新增 `colorgraph.vos-platform-prerequisite-audit/v1` 与
      `vos-platform-audit` CLI，固定记录 Windows/WSL2/Linux × CPU/CUDA/ROCm，
      并明确禁止把 host prerequisite 当作模型兼容。真实审计确认 Windows CUDA
      与 Ubuntu 22.04 WSL2 内 RTX 5060 Ti/16 GB、Python 3.10 可见，但 WSL
      缺 pip/torch；平台 prerequisite 报告保持 `partial`，见
      [`vos-platform-prerequisite-audit.json`](../../output/evidence/vos-platform-prerequisite-audit.json)。
    - 已在原 DJI 相机源派生的 30 帧真实 clip 上完成 SAM 2.1 Windows CUDA
      推理：官方代码 revision `2b90b9f5…01a4`、checkpoint 文件 SHA-256
      `0a4067b1…bc60`、严格加载状态 SHA-256 `33875f18…0337`，OneFormer
      语义 mountain anchor 初始化成功，传播 `5.848 FPS`、峰值 GPU
      `1288.68 MiB`，逐帧 mask 与总体 NPZ 哈希均已冻结。证据见
      [`vos-010-sam21-real-runtime-observation.json`](../../output/evidence/vos-010-sam21-real-runtime-observation.json)。
    - 同一 123.84 秒、7423 帧 DJI 原片已完成生产长度的有界窗口传播：
      256 个 30 帧窗口以 1 帧重叠且重叠输出只写一次，逐镜头语义重锚定，
      覆盖帧严格为 `0..7422`；传播 `10.005 FPS`、峰值 GPU `1564.26 MiB`。
      640×360 8-bit FFV1 蒙版 SHA-256 为 `285a5f2d…467f`，完整解码、
      frame/FPS/pixel-format 与模型 revision/state identity 均已复核并安装为
      `mask_sam21_mountain`。证据见
      [`bench-001-sam21-full-asset-observation.json`](../../output/evidence/bench-001-sam21-full-asset-observation.json)。
      机器侧生产长度资产已完成；五类失败场景人工 Gold 和其余平台矩阵仍按用户
      要求后置，因此本项保持未勾选。

- [ ] **CG-VOS-011 — SAM 3.1 质量上限试点**
  - 提交决策：**`DEFERRED`，完整后置。** 提交前不再处理 gated checkpoint、WSL/Triton 兼容和约 3.5 GB 权重，也不把 SAM 3.1 放入 Demo 路径。
  - 先完成自定义许可和分发约束审查。
  - 在 WSL2/Linux 进行 CUDA/Triton/kernel 兼容验证。
  - 限制对象数/窗口并记录 memory growth。
  - 与 SAM 2.1 使用相同 Gold Set 对测。
  - 依赖：CG-VOS-010。
  - 完成标准：只有质量收益足以覆盖许可、部署和显存成本时才进入产品化。
  - 2026-07-30 工程进度：统一 VOS evaluator 对 SAM 3.1 额外强制自定义许可与
    权重分发审查摘要、WSL2/Linux CUDA 实测、最大对象数、窗口帧数、16 GB
    峰值与 memory growth；即使优于 Farneback，也必须在同一 Gold Set 上相对
    SAM 2.1 达到额外质量收益才可成为 primary。
  - 已核验 2026-03-27 官方 SAM 3.1 Object Multiplex 发布，安装官方代码
    revision `6dbb02bd…84f6`，并审阅固定版本 `SAM-License-2025-11-19`。
    许可授予使用与按条件分发，用户已授权项目接受和 checkpoint 操作；这不额外
    授权超出上游条款的公开分发。
  - 官方 Hugging Face checkpoint revision 已冻结为
    `daa63191…4460`；`sam3.1_multiplex.pt` 预期
    `3,502,755,717` bytes、LFS SHA-256 `0567debe…cb6`。本机无 HF token，
    gated metadata probe 返回 401，故没有启动 3.5 GB 传输或伪造 runtime。
    机器审计见
    [`vos-011-sam31-access-audit.json`](../../output/evidence/vos-011-sam31-access-audit.json)。
    仍需上游账号授权/本机登录、checkpoint 严格加载、WSL2/Linux 实测与同一
    人工 Gold 质量增益，本项保持未勾选。

- [ ] **CG-VOS-012 — Cutie/SEA-RAFT fallback 评估**
  - 提交决策：**`DEFERRED`，完整后置。** Cutie/SEA-RAFT 只保留为研发与真实 runtime 证据，不进入 Demo 主路径，不补五类失败场景人工 Gold。
  - SAM 集成受阻时评估 Cutie。
  - 仍需光流 fallback 时，以 SEA-RAFT 的 occlusion/uncertainty 替代 Farneback。
  - 完成标准：不得只按论文 benchmark 选择，必须报告本域 mask temporal metrics。
  - 2026-07-30 工程进度：同一 evaluator 将 Cutie 固定为 VOS fallback、
    SEA-RAFT 固定为 flow fallback；二者必须在本域五类失败场景上优于 Farneback，
    SEA-RAFT 还必须输出 occlusion/uncertainty 证据。
  - 已完成两者真实本机运行。Cutie 官方代码 revision
    `ec5cdd4c…125a`，checkpoint 文件 SHA-256 `9c05402e…3023`、
    状态 SHA-256 `de2211a6…db1a`，30 帧传播 `19.438 FPS`、峰值 GPU
    `1288.68 MiB`；逐帧 mask 证据见
    [`vos-012-cutie-real-runtime-observation.json`](../../output/evidence/vos-012-cutie-real-runtime-observation.json)。
    Cutie 代码为 MIT，但官方权重仍无独立明确的公开分发许可；项目本地使用已获
    用户授权，公共分发继续 fail-closed。
  - SEA-RAFT 官方代码 revision `9137517b…3b75`，Spring-M checkpoint 文件
    SHA-256 `cb8cfbf1…6102`、状态 SHA-256 `a5723bfe…d384`，29 对真实帧
    `15.415 FPS`、峰值 GPU `152.75 MiB`，并输出逐对 flow、uncertainty 和
    occlusion 哈希；见
    [`vos-012-sea-raft-real-runtime-observation.json`](../../output/evidence/vos-012-sea-raft-real-runtime-observation.json)。
    安装与真实 runtime 缺口已消除；五类失败场景人工 Gold 和 Cutie 公共权重
    分发依据仍缺，本项保持未勾选。

## 排序、质检与修复

- [ ] **CG-RANK-002 — 训练/校准领域 Bradley–Terry 偏好排序**
  - 提交决策：**`DEFERRED`，完整后置。** 不训练或校准正式专家偏好模型；Demo 继续使用人工 A/B 选择，不宣称自动排序与专家一致。
  - 使用专家成对偏好；保存评审一致性和不确定性。
  - 与当前规则胜场、CLIP、SigLIP2 分别对比。
  - 依赖：CG-EVAL-004、CG-RANK-001。
  - 完成标准：冻结 test 的 pairwise accuracy/log loss 显著优于当前排序。
  - 2026-07-30 工程实现完成：`colorgraph.domain-bradley-terry/v1` 强制按
    source 隔离 train/calibration/test；评审可靠度只从 train 的 leave-one-out
    共识估计，温度只在 calibration 拟合，最终指标与 source-cluster bootstrap
    置信区间只在 test 计算。模型产物保存冻结特征顺序、标准化尺度、系数及其
    置信区间、评审权重、收敛状态、温度、训练摘要和各 split source 摘要。
  - 盲评 session/key/response 可直接解盲成规范训练记录；统一 evaluation runner
    同时报告 pairwise accuracy、Bradley–Terry log loss、Brier、ECE、Fleiss
    kappa，以及相对规则胜场、CLIP、SigLIP2 的配对 bootstrap 差值与显著性。
  - Gold 验收入口现要求按 source 精确绑定 train/calibration/test 的全部合格
    manifest material；门槛只能由内容哈希绑定的 calibration observation 和
    独立批准人冻结，test 少样、未知 source 或事后修改门槛均会失败。
  - 固定种子工程 shadow 含 60 个 source、480 个 pair、5 名程序化 reviewer
    的 2400 条 rating；test accuracy `0.9688 [0.9375, 0.9938]`、log loss
    `0.0288 [0.0175, 0.0424]`，相对三个 baseline 的 accuracy/log-loss
    差值置信区间均越过预设显著性门槛。证据见
    [`output/evidence/rank-002-engineering-shadow.json`](../../output/evidence/rank-002-engineering-shadow.json)。
    该数据不是专家 Gold Set；任务保持未完成，待 `CG-EVAL-004` 的独立专家
    冻结集签核后再给出正式结论。

- [ ] **CG-REPAIR-001 — 责任节点消融和约束局部修复**
  - 提交决策：**`DEFERRED`，完整后置。** 不做 Gold Set 修复成功率、回退率与副作用统计；自动修复保持 feature flag，不进入主演示或生产级声明。
  - 通过节点/时间段/区域消融定位责任源。
  - 按严重度和置信度修改最小作用域。
  - 接受条件：硬指标不退化、目标指标改善、意图漂移受限。
  - 支持多轮有预算搜索，不再只做一次固定步长全局修改。
  - 依赖：CG-QA-001、CG-QA-002。
  - 完成标准：Gold Set 上的修复成功率、回退率和副作用可量化。
  - 2026-07-30 工程实现完成：`colorgraph.responsibility-repair/v1` 先在有限预算内
    禁用候选节点测量 objective loss，再按归因排序进行最多多轮的渐进参数/轨迹
    修复；`temporal_evidence` 只平滑命中时间窗的关键帧，mask target 用于排除
    无关区域节点。每次候选均重新渲染与质检，只有目标改善、硬指标不退化、
    非目标质量不降级且参数/外部意图漂移不过限才接受，否则保留原 graph。
  - render API 新增 `repair_evaluation_budget` 与 `repair_maximum_rounds`，临时候选
    使用 graph digest 隔离，最终只移动已接受的渲染资产；报告记录 evaluations、
    accepted rounds、rollback count、decision 分布与作用域。
  - 固定工程 fixture 的 8 个案例中：4/4 改善候选被安全接受，3/4 在预算内完全
    转为 PASS；4/4 无改善、硬回归、非目标副作用或意图漂移案例正确回滚，
    unsafe acceptance 为 0。报告见
    [`output/evidence/repair-search-engineering-benchmark.json`](../../output/evidence/repair-search-engineering-benchmark.json)。
  - 统一 evaluator 已补齐修复成功率、回退准确率、unsafe/意外接受、硬安全、
    非目标副作用、意图违规、目标改善和意图漂移，并按 source-cluster bootstrap
    汇总；严格 Gold 模式要求成功与应回退案例完整绑定。公式证据见
    [`output/evidence/gold-acceptance-engineering-validation.json`](../../output/evidence/gold-acceptance-engineering-validation.json)。
    该报告明确不是独立签核 Gold Set；任务保持未完成，待 `CG-EVAL-001/002`
    的人工集补齐后报告真实素材成功率、回退率和副作用率。
