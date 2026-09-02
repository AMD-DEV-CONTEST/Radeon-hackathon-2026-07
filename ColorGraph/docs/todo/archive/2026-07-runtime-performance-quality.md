# 2026-07 Archive — Runtime 性能、蒙版资产与时序质检

> [TODO 入口](../../TODO.md) · [任务目录](../README.md)
>
> 归档日期：2026-07-30。以下任务已完成实现、自动化回归与工程基准固化；
> 生产 1080p/4K 长片基准仍由 `CG-BENCH-001` 单独跟踪。

- [x] **CG-PERF-002 — 向量化批量渲染和关键帧求值**
  - 按相同 active graph/scope 分组。
  - 向量化参数轨道、避免 batch 内逐帧 Python graph traversal。
  - 评估 `torch.compile`/融合 kernel，但保留 eager fallback。
  - 依赖：CG-KF-001、CG-COLOR-010。
  - 完成标准：1080p 质量模式吞吐提升，golden image 不退化。
  - 2026-07-30 完成：Hold、Linear、PCHIP 和兼容旧项目的 Catmull-Rom
    轨道（含速度/加速度约束）一次批量求值；执行计划在 batch 外解析 active
    graph、scope 和参数。小批/CPU 按完整执行签名分组，大分辨率 GPU 使用已规划
    的流式 eager 路径，避免分组切片导致的负优化；两条路径均消除精确恒等的
    ACES 操作，并保留可切换的旧逐帧参考路径。
  - RTX 5060 Ti、8 帧、FP32 master、真实代表帧派生的 1080p 实测：
    静态图 `18.033 → 19.755 FPS`（`1.095×`），带约束 PCHIP
    `17.818 → 19.730 FPS`（`1.107×`）；最大通道差分别为
    `2.50e-6/2.98e-6`，均低于 master `7.63e-6` 预算。640×360
    分组路径提升 `1.216–1.267×`。
  - Windows/CUDA `torch.compile(fullgraph=True, inductor)` 实际探测因 CCT/Duv
    数据相关分支、缓存追踪及环境无 Triton 被拒绝，因此未用 graph break 或静默
    fallback 冒充融合收益；正式长视频/4K 声明仍归 `CG-BENCH-001`。证据见
    [`output/evidence/batch-rendering-perf-002.json`](../../../output/evidence/batch-rendering-perf-002.json)。

- [x] **CG-PERF-003 — 设备 LUT、文本 embedding 和模型生命周期缓存**
  - LUT cache 包含 device/dtype/mtime。
  - scene 文本 embedding 常驻；图片 embedding 按内容摘要缓存。
  - 增加模型显存预算、LRU/卸载和阶段间释放。
  - 完成标准：连续分析多个项目不 OOM，冷/热启动指标可解释。
  - 2026-07-30 完成：`.cube` 设备缓存以文件签名（mtime/ctime/size/SHA-256）、
    device 和 dtype 分层失效；CLIP 文本 embedding 随模型常驻，图片 embedding
    按模型 revision 与内容 SHA-256 复用；CLIP、SegFormer、Depth Anything 接入
    租约保护的共享 LRU，并支持条目数、估算参数/缓冲区预算和阶段结束主动卸载。
  - `colorgraph doctor` 输出 hits/misses/evictions/releases、当前条目和估算字节；
    API 进入蒙版阶段前释放 CLIP，蒙版生成结束后释放语义/深度模型。
  - 离线 CUDA 实测连续处理两个项目、4 个不同内容摘要，并依次运行三套真实权重：
    峰值分配 `1394.31 MiB`、无 OOM；CLIP 三帧冷/热为
    `3215.118/2.103 ms`，SegFormer 为 `567.477/26.652 ms`，
    Depth Anything 为 `277.508/48.791 ms`；主动释放后模型条目和估算字节均为 0。
    证据见 [`output/evidence/model-lifecycle-cache-benchmark.json`](../../../output/evidence/model-lifecycle-cache-benchmark.json)。

- [x] **CG-MASK-010 — 高精度蒙版资产和批量读取**
  - 评估 gray16、16-bit lossless container 或 float EXR。
  - 批量/异步解码，减少 PNG 中转和 CPU→GPU 复制。
  - 增加边界 banding、feather 精度和存储体积对比。
  - 完成标准：软边界质量提高且长视频存储/吞吐在可接受范围。
  - 2026-07-30 完成：`colorgraph.mask-asset/v3` 默认将临时 uint16 PNG
    编码成 `gray16le` FFV1 后删除中转序列；保留 v2/8-bit 序列与视频读取兼容。
    持久 FFmpeg raw decoder 支持顺序 batch、跳帧和反向随机 seek，完整性校验同时
    核对 SHA-256、帧数、尺寸、FPS 和真实 pixel format。batch 解码后一次转为
    FP32，可用 pinned memory 整批送入 CUDA/ROCm，renderer 不再对每个节点重复
    CPU→GPU 复制；显式保留 PNG 时仍使用 4-worker 并行解码。
  - 640×360 默认 mask 分辨率、120 帧、24 FPS 软边界实测：16-bit 最大量化误差
    `7.66e-6`，较 8-bit 降低 `256×`；软区有效级数 `36,121` 对 `250`。
    五个 16-bit target 预计 `0.63 GiB/min`，含校验与 CUDA 传输的单 target
    `330.17 FPS`，五 target 串行折算 `66.03 FPS`。float32 EXR 预计五 target
    `5.52 GiB/min`，因此未设为默认。
  - 随机帧顺序的 16-bit FFV1 样本逐值精确回归已覆盖；正式 1080p/4K 长片仍归
    `CG-BENCH-001`。证据见
    [`output/evidence/mask-precision-benchmark.json`](../../../output/evidence/mask-precision-benchmark.json)。

- [x] **CG-QA-001 — 运动补偿的时序质检**
  - flicker 和 mask jitter 使用 camera/object motion compensation。
  - 区分真实亮度变化、云水运动、曝光跳变和调色引入闪烁。
  - 输出逐帧/区域证据。
  - 完成标准：运动场景误报率显著低于当前均值差/原始 mask MAE。
  - 2026-07-30 完成：`colorgraph.motion-compensated-temporal/v1` 使用
    phase-correlation 全局配准、前后向 Farneback 一致性和有效像素门禁；在同一
    源视频运动场上分离 source/output delta，以调色贡献的时序残差判定闪烁。
    每个采样转场持久化帧号、时间、曝光 stop、全局/非刚性运动、flow 有效率、
    分类置信度与连通区域框；蒙版按 camera/object 刚性运动补偿并单列边界误差。
  - 分类覆盖 `camera_or_object_motion`、`cloud_or_water_motion`、
    `source_luminance_change`、`source_exposure_jump`、
    `grade_induced_flicker`、stable 与 hard-cut exclusion；v3 FFV1 及保留 PNG
    蒙版均可取样，旧资产失败时显式回退且不冒充运动补偿证据。
  - 固定种子 26 转场回归中，20 个非闪烁运动/曝光样本的旧均值差误报率
    `60% → 0%`；6 个全局/局部调色闪烁召回 `50% → 100%`。11 个蒙版观察的
    原始 MAE 误报率 `54.55% → 0%`；中位处理耗时 `11.33 ms/transition`
    （160×96，Windows/OpenCV CPU）。证据见
    [`output/evidence/qa-001-motion-compensation-benchmark.json`](../../../output/evidence/qa-001-motion-compensation-benchmark.json)。

- [x] **CG-WATCH-001 — 跟踪尚未达到工程门槛的研究方案**
  - 仅论文、无稳定公开代码/权重的镜头或视频模型；
  - 许可为非商业且无商业授权路径的 Base/Large 权重；
  - 默认需要超过目标 16 GB 显存的 VLM/VOS；
  - 缺少 Windows/ROCm 可行路径的 CUDA 专属实现。
  - 完成标准：只有可复现、许可明确并通过 Gold Set 后，才转成正式 TODO。
  - 2026-07-30 完成：
    - 新增版本化
      [`research-watchlist-v1.json`](../../research-watchlist-v1.json) 与
      `colorgraph.research-watch-gate/v1` 审计器/`research-watch-audit` CLI；
      代码与权重的可用性、许可、不可变 revision/SHA-256 分开记录，官方来源超过
      90 天未复核也会阻断。
    - 转正必须同时通过复现报告、目标峰值不超过 16 GB、Windows/ROCm 至少一条实测路径及
      Gold Set；带缺口却提前填写正式 CG 编号会成为审计完整性失败。
    - 当前登记 SAM 3.1、VDA Base/Large、AutoShot、LumiVideo、PhotoAgent 与
      AceTone preview 共 7 项，全部保持 `watch`，0 项可转正式 TODO、0 项提前转正。
      审计证据见
      [`watch-001-research-gate-audit.json`](../../../output/evidence/watch-001-research-gate-audit.json)。
