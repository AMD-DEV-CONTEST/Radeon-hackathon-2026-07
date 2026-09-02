# 2026-08 Archive — Radeon Cloud AMD/ROCm 实机门禁

> [TODO 入口](../../TODO.md) · [任务目录](../README.md)
>
> 归档日期：2026-08-02。以下两个缩小后的提交门槛已在 Radeon Cloud 的
> Radeon PRO W7900D/W7900 48 GB 档实机上完成。完整 120 秒以上、5 variants、
> 1080p/4K、cold/warm 的 20 行生产矩阵仍明确后置，不在本次归档范围内。

- [x] **CG-COLOR-003 — ROCm/FP32 精度门禁**
  - 提交决策：**`DEMO-GATE`，已通过。** 目标是取得受支持 AMD Radeon 环境、
    解决兼容问题并形成真实设备证据，不扩展算法。
  - 提交门槛：
    1. `colorgraph doctor` 显示真实 `runtime=rocm`、AMD 型号和 HIP 版本；
    2. 在同一设备执行三次 FP32 `precision-gate` 并通过；
    3. 至少一个模型推理阶段和正式调色 renderer 明确运行在 Radeon；
    4. 冻结设备、耗时、峰值显存、输出摘要和报告哈希。
  - 色彩空间转换、LUT、pow/log、输出变换和关键质量统计固定 FP32；仅允许预览
    模式使用经误差验证的 mixed precision。
  - 完成标准：质量模式 CPU/CUDA/ROCm 目标间的 ΔE/像素误差不超过既定门槛。
  - 实现与前置进展：
    - `render_output_batch` 默认关闭 mixed precision，transfer/log/ACEScct、
      CDL/contrast/soft clip、`.cube` LUT 和母版输出路径均显式保持 FP32；
    - `precision-gate` 固定输入、图和 LUT 哈希，覆盖 Input/Output Transform、
      CDL/pow、曲线、3D LUT、负值与超范围，并绑定三次确定性哈希；
    - `colorgraph.torch-stage-evidence/v1` 为 CLIP、SegFormer、Depth Anything
      与 renderer 冻结 model/input/output tensor device、HIP、峰值显存和证据
      hash；任何 CPU/CUDA stage 都不能满足本门禁；
    - accelerator 路径以原生 PyTorch FP32 执行 OCIO 2.5.2 生成的输入变换和
      ACES 2 Output Transform，不逐帧回到 CPU；
    - 阶段调度器会卸载模型、清理 ROCm BLAS workspace 并验证残余 allocated
      bytes，不以放宽 64 MiB 门槛掩盖释放问题。
  - 2026-08-02 Radeon Cloud 实机完成：
    - 主机为 Ubuntu 24.04、AMD `gfx1100`、96 CU、49136 MiB 显存；机器探测
      amdgpu `6.16.13`、ROCm `7.2.1`、AMD SMI `26.2.2`；
    - 正式隔离环境为 Python 3.12、PyTorch `2.9.1+gitff65f5b`、torchvision
      `0.24.1+d801a34`、HIP `7.2.53211-e1a6bc5663`；
    - 三次 ROCm FP32 precision gate 通过，master/preview/determinism 全部
      `passed`，峰值 accelerator memory 35 MiB；
    - CLIP、SegFormer-B0、Depth Anything V2 Small 均在 `cuda:0`（PyTorch
      对 HIP 的设备命名）实跑，并分别精确绑定 revision 与 state-dict SHA-256；
    - `clip-to-semantic`、`semantic-to-depth`、`analysis-to-ollama`、
      `ollama-to-render` 四次释放后的 allocated/reserved bytes 均为 0；
    - Ollama `colorgraph-qwen3.5:9b` 为固定 digest、`Q4_K_M`，
      `8,861,614,208 / 8,861,614,208` bytes 在 GPU，offload ratio `1.0`，
      fresh 日志区间确认 `library=ROCm`，请求后 VRAM 释放通过；
    - 最终 renderer 的 94 个 batch 全部取得 ROCm tensor evidence，原生 GPU
      ACES 2 和 FP32 master 门通过；峰值 allocated/reserved 为
      `2232.78 / 2602.00 MiB`。
  - 统一报告：
    [`amd-full-pipeline-report.json`](../../../output/evidence/amd-full-rocm-linux-radeon-cloud-20260802-v6/amd-full-pipeline-report.json)，
    `status=passed`，SHA-256
    `c7a7e15c265ac8a33a9286125059b67d6ee4b7df90827caa02be53337235c195`。

- [x] **CG-BENCH-001 — AMD 代表性短视频基准（完整长视频矩阵后置）**
  - 提交决策：**`DEMO-GATE`，缩小范围后已通过。** 不等待 123.84 秒全片、
    5 种 mask × 1080p/4K × cold/warm 的 20 行矩阵或全部 4K 重渲染。
  - 提交门槛：
    1. 素材固定为 12–25 秒、1080p、2–4 个清晰硬切镜头且可再分发；
    2. `no_mask` 与 `current_combined` 各一行，至少记录一次 warm；
    3. 在受支持 AMD Radeon 上记录 FPS、P95、峰值显存、输出编码、硬质检、
       设备/驱动/runtime 和报告哈希；
    4. 保留可用于 GUI 播放的真实调色分片与已经完成的导出成片。
  - 后置范围：123.84 秒全片、完整 20 行矩阵、所有资产组合 SHA 复核及 4K 长
    视频全部重渲染仍为生产级验收，不阻塞提交。
  - 冻结输入：
    - 项目 `amd-demo-snowdonia-12-5s-bd7a0a7dd9`；
    - Wikimedia Commons `Snowdonia by drone` 的 CC BY-SA 4.0 衍生片，
      12.5 秒、1920×1080、30 FPS、375 帧；
    - `4.166667 / 8.366667` 秒两个清晰硬切形成 3 个镜头；
    - clip SHA-256 `04ca4701…aca5e`，manifest SHA-256 `4e291b30…a0a1`；
    - 五个冻结 16-bit FFV1 蒙版已全帧解码复核，revision/checkpoint/资产
      provenance 完整。
  - 实现与前置进展：
    - `colorgraph.production-video-benchmark/v1` 继续保留完整 20 行生产协议；
      提交冻结前已完成 10/20 行、0 failed，剩余生产矩阵后置；
    - `amd-demo-benchmark` / audit 强制受支持 Radeon/ROCm、HIP、机器探测驱动、
      两行 fresh render、逐 batch 设备证据、硬件编码和输出/质量 SHA，禁止跨
      设备 checkpoint 复用；
    - `amd-full-pipeline` 进一步绑定三次精度门禁、三类本地模型、Ollama ROCm、
      两行短基准、完整 Main10 成片和硬技术质检；
    - Linux 路径使用 VAAPI `h264_vaapi` / `hevc_vaapi`，Windows 路径使用
      AMD AMF；两者均要求硬件编码器预检成功，不能静默回退软件编码。
  - 2026-08-02 Radeon Cloud 实机完成：
    - `no_mask:proxy_1080p:warm`：375 帧，`19.3799 FPS`，P95
      `43.9026 ms`，峰值 allocated/reserved `1663.48 / 2594.00 MiB`，
      H.264 `h264_vaapi`；
    - `current_combined:proxy_1080p:warm`：375 帧，`15.1638 FPS`，P95
      `77.2078 ms`，峰值 allocated/reserved `1676.66 / 2602.00 MiB`，
      H.264 `h264_vaapi`；
    - 两行均 fresh completed、0 failed，每个 batch 均通过 ROCm/AMD/HIP
      证据，硬件 encoder 可用性验证通过；
    - 完整最终成片：HEVC Main10、`yuv420p10le`、1920×1080、30 FPS、375 帧、
      12.5 秒，`hevc_vaapi`，处理速度 `13.0158 FPS`；硬技术检查通过，质量分
      86；
    - QA 实际解码 940 个蒙版采样帧，取得 915 个 transition、300 个 temporal、
      12 个 sky mask、8 个 sky boundary 和 8 个 sky banding 观察；
    - 统一报告的 8 项检查
      (`supported_rocm_host`、`frozen_inputs`、`precision_gate`、
      `local_ai_gpu`、`ollama_rocm`、`amd_demo_benchmark`、
      `final_main10_render`、`hard_quality`) 全部通过。
  - 证据：
    - [统一报告](../../../output/evidence/amd-full-rocm-linux-radeon-cloud-20260802-v6/amd-full-pipeline-report.json)，
      SHA-256 `c7a7e15c265ac8a33a9286125059b67d6ee4b7df90827caa02be53337235c195`；
    - [短基准 audit](../../../output/evidence/amd-full-rocm-linux-radeon-cloud-20260802-v6/amd-demo-benchmark-audit.json)，
      SHA-256 `4cdf0b7854d4bc6fe0ab815588b0bfcae92c949c56e96dd9163185bc9ac21502`；
    - [Main10 成片](../../../output/evidence/amd-full-rocm-linux-radeon-cloud-20260802-v6/final-master-main10.mp4)，
      SHA-256 `6caec4ed2e6f32e22e3171654df225bac5ef6cb22c44565e6009dc7fbd2eadb5`。
    - v3 目标机包 `colorgraph-amd-full-execution-package-v3.zip` 含 184 个 payload
      文件，独立 ZIP 流式校验 0 missing / 0 mismatched；package SHA-256
      `d1a86198577edf09c8462c3392375985eb41d9431cbdacc7f10b171a723ef271`，
      manifest SHA-256
      `d53f3a5af82aac61083698c40697df114c1dd73eec4053cf830714bb8bd8d4a8`。

## 归档边界

- 本次归档只证明缩小后的比赛提交门槛和代表性短片链路通过。
- 原始 benchmark 仍按契约保持 `status=partial` /
  `production_claim_allowed=false`，避免冒充完整生产矩阵。
- 人工 Gold、专家签核、模型候选替换、Agent 正式上线与完整 20 行生产矩阵继续按
  active TODO 中的 `FROZEN` / `DEFERRED` 决策执行。
