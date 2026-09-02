# CG-BENCH-001 AMD Demo 基准

本流程只验收最新 TODO 缩小后的 AMD Demo 门槛，不替代已经后置的
`>=120 s × 5 variants × 1080p/4K × cold/warm` 20 行生产矩阵。

## 推荐的完整验收入口

最终使用：

```powershell
.\scripts\run-amd-full-pipeline.ps1
```

Radeon Cloud / Linux 使用：

```bash
COLORGRAPH_AMD_OUTPUT_ROOT="$PWD/output/evidence/amd-full-rocm-linux-radeon-cloud" \
  bash scripts/run-amd-full-pipeline-linux.sh
```

它是 `CG-COLOR-003 + CG-BENCH-001` 的 fail-closed 入口，顺序固定为：

1. 同一 Radeon/ROCm 环境的 `doctor`；
2. 三次 FP32 `precision-gate`；
3. 在 PyTorch ROCm 上实跑 CLIP、SegFormer-B0 和 Depth Anything V2 Small；
4. 逐模型释放 PyTorch 显存；
5. fresh-load `colorgraph-qwen3.5:9b`，验证固定 digest、`Q4_K_M`、至少
   99% GPU offload，以及请求后显存释放；
6. 从本次请求后新增的 Ollama `server.log` 字节区间验证
   `library=ROCm`，并冻结区间和匹配行 SHA-256；
7. fresh 渲染 `no_mask` / `current_combined` 两行 1080p AMD Demo；
8. 额外导出完整 12.5 秒 HEVC Main10 最终成片；
9. 验证每个调色 batch 都在 ROCm、ACES 2 输出变换没有逐帧 CPU
   round-trip、编码器为 AMD 硬件路径（Windows AMF / Linux VAAPI），最后运行
   硬技术质检；质检必须从 v3
   `gray16le` FFV1 主资产实际解码蒙版，并取得非零时序、天空边界和天空色带
   样本，不能在临时 PNG 已删除后把缺失证据静默记为 0；
10. 写入统一报告及 SHA-256 sidecar。

`run-amd-demo-benchmark.ps1` 仍可单独复核缩小后的两行性能门槛，但它不包含
AI/Ollama/Main10 全链路，因此不能替代上述完整入口。

## 冻结输入

- 项目：`amd-demo-snowdonia-12-5s-bd7a0a7dd9`
- 素材：12.5 秒、1920×1080、30 FPS、375 帧
- 镜头：两个清晰硬切、三个镜头
- 许可：Wikimedia Commons `Snowdonia by drone`，CC BY-SA 4.0
- 变体：`no_mask`、`current_combined`
- profile / thermal：`proxy_1080p` / `warm`
- 源 manifest：
  `output/evidence/bench-001-amd-demo-source/manifest.json`

正式 runner 强制整段 fresh render，不接受 checkpoint 复用。这样可避免把 CUDA、
旧驱动或其他设备生成的 sidecar 误当作 AMD 实测。

## 2026-08-02 Radeon Cloud 实机结果

缩小后的 `CG-COLOR-003 + CG-BENCH-001` 门槛已在 Radeon Cloud 实机通过。
本地复制的完整证据位于：

```text
output/evidence/amd-full-rocm-linux-radeon-cloud-20260802-v6/
```

关键结果：

- Ubuntu 24.04，AMD `gfx1100`，96 CU，49136 MiB 显存；ROCm 7.2.1，
  amdgpu 6.16.13，AMD SMI 26.2.2；
- PyTorch `2.9.1+gitff65f5b`、torchvision `0.24.1+d801a34`、HIP
  `7.2.53211-e1a6bc5663`；三次 FP32 precision gate 通过；
- CLIP、SegFormer-B0、Depth Anything V2 Small 和正式 renderer 均取得真实
  ROCm tensor evidence，四个阶段边界释放后的 allocated/reserved bytes 均为 0；
- Ollama `colorgraph-qwen3.5:9b` 固定 digest/Q4_K_M，GPU offload ratio
  `1.0`，fresh log 区间确认 `library=ROCm`，请求后 VRAM 释放；
- `no_mask` warm：`19.3799 FPS / 43.9026 ms P95`；
  `current_combined` warm：`15.1638 FPS / 77.2078 ms P95`；两行均为
  1920×1080、375 帧、H.264 `h264_vaapi`；
- 最终 HEVC Main10 `hevc_vaapi` 成片为 12.5 秒、375 帧、
  `13.0158 FPS`；硬技术质检通过，实际解码 940 个蒙版采样帧并取得非零时序、
  天空边界和天空色带观察；
- [统一报告](../output/evidence/amd-full-rocm-linux-radeon-cloud-20260802-v6/amd-full-pipeline-report.json)
  为 `status=passed`，SHA-256
  `c7a7e15c265ac8a33a9286125059b67d6ee4b7df90827caa02be53337235c195`；
- [短基准 audit](../output/evidence/amd-full-rocm-linux-radeon-cloud-20260802-v6/amd-demo-benchmark-audit.json)
  SHA-256 `4cdf0b7854d4bc6fe0ab815588b0bfcae92c949c56e96dd9163185bc9ac21502`；
  [Main10 成片](../output/evidence/amd-full-rocm-linux-radeon-cloud-20260802-v6/final-master-main10.mp4)
  SHA-256 `6caec4ed2e6f32e22e3171654df225bac5ef6cb22c44565e6009dc7fbd2eadb5`。

原始短 benchmark 仍按契约保持 `status=partial` /
`production_claim_allowed=false`；它只完成缩小后的两行提交门槛，不冒充完整
20 行生产矩阵。

## Radeon Cloud / Linux ROCm 7.2.1 环境

Radeon Cloud 当前可选的预热基础镜像为
`AMD OneClick Base (amd-oneclick-base:rocm7.2.1-py3.12-v20260416)`。Template
逐字段填写、公钥和 SSHD 初始化见
[`tmp/radeon-cloud-template-amd-environment.md`](../tmp/radeon-cloud-template-amd-environment.md)。

平台的 `SSH Access` 只映射端口；镜像没有安装或启动 `sshd` 时仍会得到
`Connection refused`。临时修复见
[`tmp/radeon-cloud-sshd-setup.md`](../tmp/radeon-cloud-sshd-setup.md)。这与本机
VPN 没有直接关系。

AMD 的 Linux Radeon 兼容表和 PyTorch 安装说明：

- [AMD Linux Radeon 兼容表](https://rocm.docs.amd.com/projects/radeon-ryzen/en/docs-7.2/docs/compatibility/compatibilityrad/native_linux/native_linux_compatibility.html)
- [AMD Linux PyTorch 安装](https://rocm.docs.amd.com/projects/radeon-ryzen/en/latest/docs/install/installrad/native_linux/install-pytorch.html)

仓库提供两份 Linux 冻结依赖：通用
`backend/requirements-amd-rocm-linux-7.2.1.txt`，以及与成功 Radeon Cloud
平台镜像精确匹配的
`backend/requirements-amd-rocm-linux-radeon-cloud-7.2.1.txt`。初始化：

```bash
bash scripts/setup-amd-demo-rocm-linux.sh
```

正式环境使用 `/root/colorgraph/.venv-rocm`，模型缓存分别使用
`/root/colorgraph-model-cache/huggingface` 与
`/root/colorgraph-model-cache/ollama`。Ollama 仅绑定 `127.0.0.1:11434`；不要
把 11434 暴露为公网端口。Linux 硬件编码使用 `radeonsi` VAAPI，并在运行时
自动探测 `/dev/dri/renderD*`，不把某次实例的 `renderD130` 写死到 Template。

## Windows ROCm 7.2.1 环境

AMD 当前 Windows 7.2.1 文档要求 Python 3.12 与 AMD Software 26.2.2，并发布
独立的 ROCm SDK、PyTorch 2.9.1 和 torchvision 0.24.1 wheel：

- [AMD Windows PyTorch 安装](https://rocm.docs.amd.com/projects/radeon-ryzen/en/latest/docs/install/installryz/windows/install-pytorch.html)
- [AMD Windows Radeon 兼容表](https://rocm.docs.amd.com/projects/radeon-ryzen/en/latest/docs/compatibility/compatibilityrad/windows/windows_compatibility.html)
- [AMD Windows Ryzen 兼容表](https://rocm.docs.amd.com/projects/radeon-ryzen/en/latest/docs/compatibility/compatibilityryz/windows/windows_compatibility.html)

仓库默认 `uv.lock` 仍使用 CUDA 13.0 wheel；不要在 AMD 目标机直接复用默认
`.venv`。专用脚本会建立隔离环境并使用 AMD 官方 wheel：

```powershell
.\scripts\setup-amd-demo-rocm-windows.ps1
```

依赖冻结文件为
`backend/requirements-amd-rocm-windows-7.2.1.txt`。项目的 torch 元数据范围同时
允许官方 ROCm 2.9.1 与开发机 CUDA 2.12.1，但默认 lock 不会被 AMD 环境使用。
ROCm 文件中的直接运行依赖均固定到 2026-07-31 已验证版本，统一报告会记录
该文件的 SHA-256，避免目标机安装时解析到另一组未来版本。

完整入口还要求以下本地资产已经位于目标机：

- `openai/clip-vit-base-patch32`，revision
  `3d74acf9a28c67741b2f4f2ea7635f0aaf6f0268`，state-dict SHA-256
  `c6ece25cb6d105a3e93bd8c06bc89990a83725dd82bfeddee62bba803d045ca4`；
- `nvidia/segformer-b0-finetuned-ade-512-512`，revision
  `489d5cd81a0b59fab9b7ea758d3548ebe99677da`，state-dict SHA-256
  `ccce07e3f07157bbb9d9e60a01e7b2df1c2de197594b7455bd5caa374c4279f9`；
- `depth-anything/Depth-Anything-V2-Small-hf`，revision
  `5426e4f0f36572d16453bbda7a8389317b1bef99`，state-dict SHA-256
  `31bf8a51525cf691e1ee69e76729183b0b8392b569099fc849cb75a7956b114a`；
- Ollama `colorgraph-qwen3.5:9b`，digest
  `a2845456d7ad1e2100f620eaad82c3e63860a24330948111f6ad5d8202fd3634`，
  quantization `Q4_K_M`；
- Ollama 0.20.6 服务和可读的 `%LOCALAPPDATA%\Ollama\server.log`；
- 同时列出 `h264_amf`、`hevc_amf` 的 FFmpeg build。

Hugging Face 路径由 `backend/models/huggingface.redirect` 或
`COLORGRAPH_HUGGINGFACE_CACHE_DIR` 指定。正式入口设置
`HF_HUB_OFFLINE=1` / `TRANSFORMERS_OFFLINE=1`，不会在验收期间临时下载或漂移
checkpoint。

## 两行基准入口

```powershell
.\scripts\run-amd-demo-benchmark.ps1
```

脚本按顺序执行：

1. `colorgraph doctor`；
2. 三次 ROCm `precision-gate`；
3. AMD Demo 两行 fresh render；
4. 组合行硬质检；
5. 输出、质量报告、原始 benchmark 和最终 audit 的 SHA-256 绑定。

默认输出目录：

```text
output/evidence/amd-demo-rocm/
  precision-gate-rocm.json
  amd-demo-raw-benchmark.json
  amd-demo-raw-benchmark-artifacts/
  amd-demo-benchmark-audit.json
  amd-demo-benchmark-audit.json.sha256
```

完整入口默认另写入：

```text
output/evidence/amd-full-rocm/
  precision-gate-rocm.json
  amd-demo-raw-benchmark.json
  amd-demo-benchmark-audit.json
  final-master-main10.mp4
  final-master-main10.quality.json
  amd-full-pipeline-report.json
  amd-full-pipeline-report.json.sha256
```

也可以直接运行 CLI：

```powershell
colorgraph amd-demo-benchmark `
  amd-demo-snowdonia-12-5s-bd7a0a7dd9 `
  --source-manifest ..\output\evidence\bench-001-amd-demo-source\manifest.json `
  --benchmark-output ..\output\evidence\amd-demo-rocm\amd-demo-raw-benchmark.json `
  --output ..\output\evidence\amd-demo-rocm\amd-demo-benchmark-audit.json
```

## Fail-closed 门槛

最终 `status=passed` 同时要求：

- manifest 的许可、可再分发、完整解码、时长、1080p 和 2–4 镜头门全部通过；
- 项目源文件 SHA-256 与 manifest clip 完全一致；
- source、Grade Graph 和全部代表帧在运行前后哈希一致，三个 AI 阶段共同绑定
  同一代表帧集合摘要；
- 请求范围严格等于两个 warm 1080p 变体，无缺失、blocked、failed、重复或额外行；
- 两行都有 FPS、P95、峰值 allocated/reserved VRAM、codec 与 encoder；
- 两行的每个调色 batch 都有 ROCm/AMD/HIP tensor placement、峰值显存和证据
  hash，且 FFmpeg 预检确认对应 OS 的 AMD 硬件 encoder 可用（Windows AMF / Linux VAAPI）；
- 两个输出的尺寸、时长、帧数和文件 SHA-256 独立复核通过；
- `current_combined` 的硬质检通过且质量报告 SHA-256 匹配；
- Main10 最终成片报告中的 `mask_frames_decoded`、
  `mask_transition_samples`、`mask_temporal_observations` 均大于 0；存在天空
  蒙版时，`sky_mask_samples`、`sky_boundary_samples`、
  `sky_banding_samples` 也必须全部大于 0；
- 所有活动蒙版的模型 revision、checkpoint 与资产 provenance 完整；
- backend 报告 `runtime=rocm`、`vendor=AMD`，并使用对应平台冻结文件中允许的
  PyTorch/torchvision build；HIP runtime 必须为 ROCm 7.2.1 系列，具体完整
  build string 写入统一报告并与目标环境 policy 一致；
- 设备名匹配冻结的 AMD ROCm 7.2.1 生产 Radeon 支持表；
- AMD 驱动版本由 Windows CIM、`rocm-smi`、AMD SMI 或 `modinfo amdgpu`
  实机探测得到；
- 原始短片报告保持 `status=partial` 和
  `production_claim_allowed=false`，避免冒充完整生产矩阵。

状态语义：

- `passed`：缩小后的 AMD Demo 门槛通过；
- `engineering_preflight_only`：内容链路通过，但运行时/设备不是受支持 AMD ROCm；
- `blocked`：AMD 身份成立，但 HIP 或驱动证据缺失；
- `failed`：素材、覆盖、输出、哈希、provenance 或硬质检失败。

已有报告可用审计命令复核：

```powershell
colorgraph amd-demo-benchmark-audit `
  --source-manifest <manifest.json> `
  --benchmark-report <raw-benchmark.json> `
  --output <audit.json>
```

该命令不会把 CUDA 数字改写为 AMD 数字；当前 RTX 5060 Ti 工程预检只会得到
`engineering_preflight_only`。

## GPU 与 CPU 边界

统一报告只把以下计算称为 AMD GPU 计算：

- CLIP、语义分割、深度和 Qwen3.5 VLM 推理；
- Grade Graph、LUT、蒙版混合与原生 PyTorch ACES 2 输出变换；
- H.264/HEVC AMD 硬件编码（Windows AMF / Linux VAAPI）。

FFmpeg demux/RGB48 解码、GPU 输出交给 FFmpeg 前的一次 host transfer、音频/
容器 mux、文件哈希以及渲染后的 OpenCV/FFmpeg 质量测量仍是 CPU/media-I/O
边界。它们会在报告中明确列出，不会冒充 GPU 推理或 GPU 调色。本地开发机的
PyTorch 仍是 CUDA，`amd-full-pipeline` 会在任何 AI、Ollama 或渲染开始前直接
拒绝运行；上面的 `passed` 结论来自 Radeon Cloud 实机报告，不是把本机 CUDA
结果改写成 AMD 数字。

CLIP、SegFormer、Depth Anything 和 Qwen3.5 在这里是代表帧级 AMD 设备执行
证明；它们不会假装重新生成整段视频的蒙版。最终调色明确读取已经冻结并带
revision/checkpoint/资产哈希的 FFV1 蒙版。这一数据流会写入统一报告，避免把
“模型能在 AMD 上实跑”误写成“本轮已在 AMD 上重做全部时序资产”。

## 目标机执行包

如目标机已经准备好本地模型缓存，可生成并传输冻结执行包：

```powershell
.\scripts\package-amd-demo-benchmark.ps1
```

默认产物为
`output/evidence/colorgraph-amd-full-execution-package-v3.zip` 及同名
`.sha256`。包内包含完整 `backend/colorgraph` 运行源码、冻结短片项目、执行脚本
、Radeon Cloud Template/SSHD 指南和前置证据；会排除 `__pycache__` / `.pyc`，
也不包含模型权重或复制的 AMD 结果。目标机应先校验 sidecar，再解压到
ColorGraph 仓库根目录，并使用本机已冻结的 Hugging Face/Ollama 模型缓存 fresh
执行完整入口；历史实机通过不替代每台新目标机自己的 fresh audit。
