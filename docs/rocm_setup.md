# ROCm 环境配置指南

目标平台：**AMD Radeon GPU 48GB + ROCm 6.2**。本指南覆盖从系统验证到模型下载的完整流程。

## 1. 前置检查

### 1.1 确认 GPU 与 ROCm 可见

```bash
# 列出 ROCm 可见 GPU
rocm-smi --showproductname

# 期望输出含 "AMD Radeon" 且显存 ≈ 48GB
```

### 1.2 系统依赖

```bash
# Ubuntu 22.04 / 24.04 示例
apt update && apt install -y \
    build-essential git ffmpeg \
    libgl1 libglib2.0-0 \
    rocm-smi-lib
```

## 2. Python 环境

```bash
# 1. 创建 conda 环境
conda create -n frameforge python=3.10 -y
conda activate frameforge

# 2. 安装 ROCm 版 PyTorch (ROCm 6.2)
pip install torch torchvision torchaudio \
    --index-url https://download.pytorch.org/whl/rocm6.2

# 3. 验证 GPU 可见 (ROCm 走 cuda 接口)
python -c "import torch; print('CUDA available:', torch.cuda.is_available()); \
           print('Device:', torch.cuda.get_device_name(0)); \
           print('VRAM:', torch.cuda.get_device_properties(0).total_memory / 1e9, 'GB')"
```

期望输出：
```
CUDA available: True
Device: AMD Radeon RX ...
VRAM: 47.x GB
```

> **排错**：若 `cuda.is_available()` 为 False，检查 `HSA_OVERRIDE_GFX_VERSION`。部分 GPU 需设置：
> ```bash
> export HSA_OVERRIDE_GFX_VERSION=11.0.0  # 按实际架构调整
> ```

## 3. 安装 ComfyUI

```bash
cd /root  # 或你的工作目录
git clone https://github.com/comfyanonymous/ComfyUI.git
cd ComfyUI
pip install -r requirements.txt
```

### 启动 ComfyUI

```bash
cd /root/ComfyUI
python main.py --listen 0.0.0.0 --port 8188 --preview-method auto
```

验证：浏览器打开 `http://localhost:8188`，能看到 ComfyUI 界面即成功。

## 4. 安装 FrameForge

```bash
cd /root/FrameForge
pip install -r requirements.txt
```

## 5. 下载模型

所有 ComfyUI 模型放到 `/root/ComfyUI/models/` 对应子目录，FrameForge 本地模型放到 `/root/FrameForge/models/`。

### 5.1 Wan2.1 Image-to-Video 14B

```bash
# FP8 量化版 (推荐, 省显存)
cd /root/ComfyUI/models/diffusion_models/
# 从 HuggingFace 下载: Wan-AI/Wan2.1-I2V-14B-480P
# 文件: wan2.1_i2v_14B_fp8.safetensors (≈ 14GB)

# CLIP 视觉编码器
cd /root/ComfyUI/models/clip_vision/
# 文件: clip_vision_h.safetensors

# VAE
cd /root/ComfyUI/models/vae/
# 文件: wan_2.1_vae.safetensors
```

> 工作流 `wan21_i2v.json` 中节点 1 的 `ckpt_name` 需与实际文件名一致，不同则改 JSON 或重命名文件。

### 5.2 SDXL Inpainting

```bash
cd /root/ComfyUI/models/checkpoints/
# 推荐: stabilityai/stable-diffusion-xl-base-1.0 的 inpaint 变体
# 或 sdxl_inpaint.safetensors

cd /root/ComfyUI/models/vae/
# sdxl_vae.safetensors (若 SDXL 自带 VAE 可省略)
```

### 5.3 ControlNet

```bash
cd /root/ComfyUI/models/controlnet/
# Canny
# controlnet-canny-sdxl-1.0.safetensors
# Depth
# controlnet-depth-sdxl-1.0.safetensors
```

### 5.4 SAM2（可选，MVP 可跳过）

```bash
cd /root/ComfyUI/models/sams/
# sam2_hiera_large.pt
```

### 5.5 RAFT 光流模型

```bash
cd /root/FrameForge/models/
# torchvision 内置 RAFT 会自动下载权重, 无需手动操作
# 若需离线, 放置 raft-things.pth 到此目录
```

## 6. 安装 ComfyUI 自定义节点（按需）

部分工作流节点（如 `VHS_VideoCombine`）需要 ComfyUI-VideoHelperSuite：

```bash
cd /root/ComfyUI/custom_nodes/
git clone https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite.git
cd ComfyUI-VideoHelperSuite
pip install -r requirements.txt
```

重启 ComfyUI 使自定义节点生效。

## 7. 启动完整系统

两个终端：

```bash
# 终端 1: ComfyUI 后端
conda activate frameforge
cd /root/ComfyUI
python main.py --listen 0.0.0.0 --port 8188

# 终端 2: FrameForge Web UI
conda activate frameforge
cd /root/FrameForge
python app.py
```

浏览器打开 `http://localhost:7860`，界面顶部状态条应显示「GPU: AMD Radeon ...」与「ComfyUI: 已连接」。

## 8. 常见问题

### Q1: `torch.cuda.is_available()` 返回 False
- 确认 ROCm 驱动已安装：`rocm-smi` 能否输出
- 尝试设置 `HSA_OVERRIDE_GFX_VERSION`（见第 2 节）
- 确认 PyTorch 是 ROCm 版而非 CUDA 版：`pip show torch | grep Location` 应含 `rocm`

### Q2: Wan2.1 推理 OOM
- 改用 FP8 量化版模型
- 降低分辨率到 832×480
- 减少 `num_frames`（保持 `4k+1`，如 33、49）
- 关闭其他占用显存的进程

### Q3: ComfyUI 显示节点缺失
- 缺 `VHS_VideoCombine`：安装 ComfyUI-VideoHelperSuite（第 6 节）
- 缺 `WanImageToVideo`：升级 ComfyUI 到最新版

### Q4: RAFT 光流报错
- 确认 torchvision 版本 ≥ 0.16（含 RAFT）
- 首次运行会下载权重，需联网

### Q5: Gradio ImageEditor 涂层无法提取 mask
- FrameForge 已处理 `{"background","layers"}` 字典格式
- 若 Gradio 版本 < 4.44，升级：`pip install gradio==4.44.0`

## 9. 降级方案

| 问题 | 降级方案 |
|------|---------|
| Wan2.1 在 ROCm 失败 | 改用 CogVideoX-5B（更轻量，兼容性更稳） |
| RAFT 传播效果差 | 缩小传播范围到前后各 3 帧 |
| 时间不足 | 走 MVP：跳过 SAM2、二次修复、音轨，传播 3 帧 |
| SAM2 不可用 | 跳过自动分割，用户直接涂抹（`EditConfig.use_sam2_refine=False`，已默认关闭） |
