# ColorGraph AMD Radeon / ROCm 迁移方案

> 状态：已保留运行时抽象与迁移路径，**尚未在 AMD Radeon 实机验证**。  
> 当前开发基线：Windows 11、NVIDIA GeForce RTX 5060 Ti、PyTorch CUDA 13.0。

本文只描述工程迁移边界，不把 CUDA 开发结果冒充 ROCm 结果。最终版本必须在比赛指定 Radeon 环境重新安装 PyTorch、运行模型和视频链路，并记录真实设备、显存、耗时、稳定性与输出质量。

## 1. 已落地的可迁移边界

### 1.1 统一计算后端

`backend/colorgraph/devices/` 定义 `ComputeBackend`，业务模块只依赖：

- `torch_device`
- `inference_context()`
- `synchronize()`
- `empty_cache()`
- 结构化 `DeviceInfo`

`TorchComputeBackend` 通过 `torch.version.hip` 区分 ROCm 与 CUDA。PyTorch 在 ROCm 构建中仍通过 `torch.cuda` 命名空间暴露设备，因此模型和张量代码不按 AMD/NVIDIA 分叉。

### 1.2 不依赖 CUDA 专属扩展

当前关键计算只使用标准 PyTorch / Transformers 算子：

- CLIP 场景理解；
- SegFormer 语义分割；
- Depth Anything V2 深度估计；
- Exposure、白平衡、CDL、曲线、3D LUT 和蒙版合成；
- 批量张量渲染。

仓库没有 Triton/CUDA 自定义 kernel、FlashAttention、xFormers 或 `.cu` 扩展。OpenCV 光流、FFprobe、质量统计和 ZIP 打包为 CPU 工具链，不影响“关键推理在 Radeon GPU 本地执行”的边界。

### 1.3 编码器隔离

`grading/video.py::select_encoder()` 只在编码层选择：

| 当前运行时 | 8-bit 代理/兼容输出 | 10-bit 正式成片 |
| --- | --- | --- |
| CUDA | `h264_nvenc` | `hevc_nvenc` Main10 |
| ROCm + Windows | `h264_amf` | `hevc_amf` Main10 |
| 其他 | `libx264` | `libx265` Main10 |

调色与模型推理不依赖 NVENC。若指定 AMD 环境不提供 AMF，可通过
`COLORGRAPH_VIDEO_ENCODER_10BIT=libx265` 使用软件编码，关键 AI 推理和 FP32
正式调色仍在 Radeon GPU 上执行。

### 1.4 API 与 UI 不硬编码厂商

`GET /api/system/device` 返回：

```json
{
  "runtime": "cuda | rocm | cpu",
  "vendor": "NVIDIA | AMD | Generic",
  "name": "由 PyTorch 运行时读取",
  "total_memory_mb": 0,
  "torch_version": "由运行时读取",
  "runtime_version": "CUDA 或 HIP 版本"
}
```

前端设备名称、运行时、FPS、模型阶段和导出编码均来自真实 API，不再显示静态 Radeon 占位值。

## 2. 当前 CUDA 开发配置

`backend/pyproject.toml` 当前显式锁定：

```text
torch 2.12.1 + cu130
torchvision 0.27.1 + cu130
```

这保证本机 NVIDIA 开发环境可复现，但该锁文件不能直接用于 ROCm 环境。迁移时必须建立独立虚拟环境并安装与比赛 ROCm 驱动匹配的官方 PyTorch wheel；不要在同一环境混装 CUDA 和 ROCm wheel。

仓库提供 `backend/requirements-runtime.txt` 保存厂商无关依赖。ROCm 环境建议按以下顺序创建：

```bash
python3 -m venv backend/.venv-rocm
source backend/.venv-rocm/bin/activate
python -m pip install --upgrade pip
python -m pip install -r backend/requirements-runtime.txt

# 使用比赛环境指定或 PyTorch 官方安装选择器给出的 ROCm index/version：
python -m pip install torch torchvision --index-url <MATCHING_ROCM_WHEEL_INDEX>

# 项目本体不再解析 CUDA 依赖
python -m pip install --no-deps -e backend
```

具体 ROCm、PyTorch、操作系统和显卡支持矩阵以比赛指定环境为准，本文不预填未经验证的版本号。

### 2.1 本机 AMD 设备资格审计

本机除 NVIDIA 开发卡外还能枚举到 Ryzen 7 7800X3D 的
`AMD Radeon(TM) Graphics`（Raphael 集成显卡，PCI `1002:164E`）。截至
2026-07-28，AMD 官方
[Windows Ryzen APU 支持矩阵](https://rocm.docs.amd.com/projects/radeon-ryzen/en/latest/docs/compatibility/compatibilityryz/windows/windows_compatibility.html)
列出的 ROCm 7.2.1 目标是 Ryzen AI `gfx1150/gfx1151` 系列，并未列出该
Raphael 设备；离散 Radeon 目标则应另查
[Windows Radeon 支持矩阵](https://rocm.docs.amd.com/projects/radeon-ryzen/en/latest/docs/compatibility/compatibilityrad/windows/windows_compatibility.html)。

因此本机不会安装不受支持的 ROCm wheel，也不会把“能枚举到 AMD 显卡”写成
ROCm 通过。结构化审计证据保存在
`output/evidence/rocm-local-hardware-audit.json`；下一步需要受支持的 AMD
目标机或经授权的 AMD GPU runner。

## 3. 迁移步骤

### 3.1 系统层

1. 在比赛指定操作系统安装官方 Radeon 驱动和 ROCm；
2. 用系统工具确认 GPU、HIP 和显存可见；
3. 确认 FFmpeg 至少有 `libx264`，有 AMF 时额外记录；
4. 创建全新的 `.venv-rocm`，不要复用 `.venv`；
5. 安装匹配版本的 ROCm PyTorch 与 torchvision。

### 3.2 ColorGraph 自检

```bash
export COLORGRAPH_DEVICE=rocm
backend/.venv-rocm/bin/colorgraph doctor
```

必须满足：

- `device.runtime == "rocm"`；
- `device.vendor == "AMD"`；
- `device.name` 为真实 Radeon 型号；
- `torch.version.hip` 非空；
- FFmpeg 与 FFprobe 可执行。

若 `COLORGRAPH_DEVICE=rocm` 但 PyTorch 实际为 CUDA 或 CPU，后端会直接报错，不静默伪装为 ROCm。

### 3.3 FP32 数值门禁

先运行不依赖业务素材的确定性 stress gate：

```bash
mkdir -p output/evidence
COLORGRAPH_DEVICE=rocm backend/.venv-rocm/bin/colorgraph precision-gate \
  --require-runtime rocm \
  --output output/evidence/rocm-precision-gate.json \
  --repeats 3
```

`colorgraph.precision-gate-report/v1` 会记录设备、PyTorch/HIP 版本、输入/图/LUT
哈希、CPU 与 accelerator FP32 输出差异、CIEDE2000、preview mixed-precision
请求差异、三次输出哈希、漂移、耗时和峰值显存。运行时必须真实为 ROCm；在 CUDA
或 CPU wheel 上请求 `--require-runtime rocm` 会立即失败。

固定门槛：

| 路径 | 最大归一化通道误差 | 最大 ΔE2000 | 其他 |
| --- | ---: | ---: | --- |
| 母版 CPU FP32 → accelerator FP32 | `0.5 / 65535` | `0.01` | 禁止 mixed precision |
| 预览 accelerator FP32 → mixed request | `2 / 255` | `1.0` | 只允许经门禁的预览 |
| 重复运行漂移 | `0.5 / 65535` | — | 至少 3 次 |

同一命令已在当前 CUDA 开发卡通过，证据为
`output/evidence/cuda-precision-gate.json`。该 CUDA 报告只证明门禁与本机
CUDA 路径有效，不能替代 ROCm 报告。

### 3.4 单模块验证顺序

按风险从低到高验证：

1. 标量和小张量调色算子；
2. 3D LUT 与关键帧插值；
3. CLIP 单代表帧；
4. SegFormer 单帧；
5. Depth Anything 单帧；
6. 5 类蒙版的完整短视频传播；
7. 无蒙版 GPU 视频渲染；
8. 带 FFV1 时序蒙版的 GPU 视频渲染；
9. 质检失败后的第二次渲染；
10. Web UI 完整上传到 ZIP 下载。

出现算子兼容问题时应优先替换为等价原生 PyTorch 实现，不在业务层添加“如果 AMD 就跳过”的分支。

## 4. 已知兼容风险与预留方案

| 风险 | 当前实现 | ROCm 处理方案 |
| --- | --- | --- |
| 模型 FP16 支持差异 | 模型推理可使用 FP16；正式调色固定 FP32 | 首轮验证加入 FP32 基线；必要时为模型暴露精度配置 |
| Transformers 个别算子回退 | 使用标准 AutoModel | 逐模型记录 GPU 利用率并检查是否发生 CPU fallback |
| 显存容量不同 | 默认小模型、640 边长、batch=4 | 下调 batch/最大边长；不改变 Grade Graph |
| NVENC 不可用 | 编码器选择器隔离 | AMF 或 libx264 |
| Windows/Linux 路径差异 | 全部使用 `pathlib` | 在 Linux 运行存储与导出测试 |
| FFV1 蒙版解码吞吐 | OpenCV 顺序读取 | 保留 PNG 回退；必要时改 FFmpeg 管道 |
| 半精度数值差异 | 母版 FP32；仅 preview 可请求 mixed precision | ROCm 上执行同一 `precision-gate`，不得看到 test 结果后放宽门槛 |
| 4K 显存与吞吐 | 当前仅小样本实测 | 分块/降 batch，建立 1080p 与 4K 基准 |

## 5. ROCm 实机验收清单

以下全部通过后，才能把状态改为“AMD/ROCm 已完成”：

- [ ] `colorgraph doctor` 输出真实 Radeon 和 HIP 版本；
- [ ] 单元测试全部通过；
- [ ] `precision-gate --require-runtime rocm --repeats 3` 通过并保存完整报告；
- [ ] CLIP、SegFormer、Depth Anything 的输出张量位于 ROCm GPU；
- [ ] 语义/深度模型各完成至少一次本地推理；
- [ ] 20–45 秒、3–8 镜头视频完成分析；
- [ ] Typed Grade Graph 驱动完整视频渲染；
- [ ] 天空、植被、水面、山体和深度蒙版无明显抖动；
- [ ] 质检与一次定向修复能够闭环；
- [ ] ZIP 包中的 MP4、LUT、JSON、报告和蒙版均可打开；
- [ ] 前端显示的数据与终端同一任务一致；
- [ ] 记录 CPU / Radeon 的相同素材、相同分辨率、相同参数对比；
- [ ] 记录冷启动、预热后 FPS、峰值显存和模型版本；
- [ ] 连续运行至少 3 次，无崩溃、OOM 或输出漂移；
- [ ] 1080p 正式演示素材通过；若宣称 4K，再单独完成 4K 验证。

## 6. 需要保留的证据

AMD 环境阶段应保存：

- `colorgraph doctor` JSON；
- `colorgraph.precision-gate-report/v1` JSON；
- `pip freeze` 或锁文件；
- PyTorch、HIP、模型 ID、精度和输入尺寸；
- FFmpeg 编码器列表；
- 每阶段开始/结束时间和峰值显存；
- CPU/GPU 对照命令；
- 质量报告；
- 输出文件哈希；
- 同一次任务的前端截图与终端日志。

这些证据将用于后续提交材料，但不在当前 NVIDIA 开发阶段伪造或预填。
