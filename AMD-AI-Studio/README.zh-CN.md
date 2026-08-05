# AMD AI Studio — 本地 AI 创作工作室

> **AMD AI DevMaster Hackathon** 参赛作品 | 赛道 1：多模态 AI

基于 **AMD Radeon™ GPU + ROCm™** 的全本地化多模态 AI 创作平台，无需联网、保护隐私、一键创作。

---

## ✨ 功能特色

| 功能 | 说明 |
|------|------|
| 📝 **文生图** | 输入文字描述，生成高质量图像（SDXL Base + Refiner 两阶段） |
| 🔄 **图生图** | 上传参考图，通过提示词变换风格/内容，一键风格迁移 |
| 🎬 **图生视频** | 上传一张图，生成动态视频或 GIF（Stable Video Diffusion） |
| 🖌️ **局部重绘** | 涂抹区域 + 提示词，智能修复/替换图像局部 |
| 🖼️ **图像外延** | 向任意方向扩展画布，AI 自动补全扩展内容 |
| 🚀 **AMD GPU 优化** | 原生 ROCm 支持，FP16 推理，显存自动优化 |

## 🏆 赛道评分加分项

| 评分项 | 本项目实现 |
|--------|-----------|
| **功能完整性与实用价值（80分）** | 5 大功能模块，完整的多模态创作工作流 |
| **AMD Radeon GPU 优化（20分）** | ROCm 检测、FP16 推理、显存优化、CPU offload、GPU 状态监控、基准测试 |

## 🖥️ 系统要求

### 硬件
- **GPU**: AMD Radeon™ RX 6000/7000 系列及以上（推荐 8GB+ 显存）
- **内存**: 16GB+
- **存储**: 30GB+ 可用空间（用于模型下载）

### 软件
- **OS**: Linux（Ubuntu 22.04+ 推荐）
- **ROCm**: ROCm 7.x（本机已安装 ROCm 7.2.3）
- **Python**: 3.12

---

## 🚀 快速开始

### 1. 环境检测

```bash
bash scripts/check_and_install.sh
```

一键检测硬件、ROCm、Python 环境，自动安装缺失依赖。

### 2. 下载模型

```bash
# 默认从国内源 ModelScope 下载
bash scripts/download_models.sh

# 下载指定模型
bash scripts/download_models.sh sdxl-base sdxl-vae-fp16 sdxl-refiner

# 从 Hugging Face 下载（自动使用国内镜像 hf-mirror.com）
bash scripts/download_models.sh -s huggingface

# 列出所有可用模型
bash scripts/download_models.sh -l
```

### 3. 构建

```bash
bash scripts/build.sh
```

### 4. 启动

```bash
# Web UI 模式（默认）
bash scripts/start.sh

# 或手动启动
python app.py
```

打开浏览器访问 **http://localhost:7860**

---

## 📁 项目结构

```
amd-ai-studio/
├── app.py                        # 主入口（Gradio UI，5 个功能 Tab）
├── requirements.txt              # 依赖清单
├── .env                          # 环境配置（由 check_and_install.sh 自动生成）
├── .gitignore
│
├── configs/
│   ├── default_config.py          # 模型ID、推理参数、显存优化配置
│   └── model_paths.yaml           # 模型路径映射注册表（YAML 格式）
│
├── modules/
│   ├── __init__.py
│   ├── rocm_utils.py              # ROCm 检测、GPU 监控、内存优化
│   ├── pipeline_cache.py          # 模型管道缓存（避免重复加载）
│   ├── txt2img.py                 # 文生图（SDXL Base + Refiner）
│   ├── img2img.py                 # 图生图 + 风格迁移
│   ├── img2video.py               # 图生视频 / GIF（SVD-XT）
│   ├── image_edit.py              # 图像修复（Inpainting / Outpainting）
│   ├── model_loader.py            # 模型加载管理器（路径解析、注册、状态查询）
│   └── model_optimizer.py         # 模型优化工具（量化、编译、基准测试、显存建议）
│
├── scripts/
│   ├── check_and_install.sh       # 🔧 一键检测硬件 + ROCm + Python + 依赖安装
│   ├── build.sh                   # 🔨 构建脚本（安装依赖 + 编译 ROCm 内核）
│   ├── start.sh                   # 🚀 启动脚本（web / headless / api 模式）
│   ├── download_models.sh         # 📥 模型下载（支持 ModelScope / HuggingFace 镜像）
│   ├── docker_build.sh            # 🐳 Docker 镜像构建脚本
│   ├── docker_start.sh            # 🐳 Docker 容器启动脚本
│   └── finetune/
│       ├── finetune_lora.py       # 🎓 SDXL LoRA 微调训练脚本
│       └── prepare_dataset.py     # 🗂️ 数据集准备工具（本地/HF/COCO/BLIP 字幕生成）
│
├── Dockerfile                     # 🐳 Docker 镜像构建文件（ROCm 7.2 + Ubuntu 24.04）
├── docker-compose.yml             # 🐳 Docker Compose 一键启动配置
├── .dockerignore                  # 🐳 Docker 构建忽略文件
│
├── docs/
│   ├── 01-环境准备.md              # 环境要求与安装指南
│   ├── 02-模型下载.md              # 模型下载说明
│   ├── 03-模型微调.md              # LoRA 微调训练教程
│   └── 04-性能优化.md              # AMD GPU 性能调优指南
│
├── assets/                        # 静态资源
├── outputs/                       # 生成结果输出目录
│   ├── images/
│   ├── videos/
│   ├── gifs/
│   └── finetune/                  # 微调产出权重
│
└── README.md
```

---

## 🧠 脚本使用指南

### 🔧 `scripts/check_and_install.sh` — 环境检测与安装

检测硬件配置、ROCm/CUDA 版本、Python 环境、PyTorch/Diffusers/Gradio 等依赖，并自动安装缺失项。

```bash
bash scripts/check_and_install.sh
```

检测项：
- ✅ CPU 型号 & 核心数
- ✅ 内存总量 & 可用
- ✅ GPU 型号 & 显存（AMD ROCm / NVIDIA CUDA）
- ✅ Python 版本 & 虚拟环境
- ✅ ROCm / CUDA 版本
- ✅ PyTorch / Diffusers / Gradio 安装状态
- ✅ 自动生成 `.env` 配置文件

### 📥 `scripts/download_models.sh` — 模型下载

```bash
# 下载全部模型（默认从 ModelScope 国内源）
bash scripts/download_models.sh

# 从 Hugging Face 镜像下载
bash scripts/download_models.sh -s huggingface

# 指定模型
bash scripts/download_models.sh sdxl-base sdxl-vae-fp16

# 列出可用模型
bash scripts/download_models.sh -l
```

所有模型下载均通过 `nocache` 工具包装，利用 `posix_fadvise(DONTNEED)` 防止大文件下载冲掉系统页缓存，避免 OOM。

### 🔨 `scripts/build.sh` — 构建

```bash
bash scripts/build.sh              # 全部（安装依赖 + 编译内核）
bash scripts/build.sh deps         # 只安装依赖
bash scripts/build.sh compile      # 只编译 ROCm 优化内核
```

### 🚀 `scripts/start.sh` — 启动

```bash
bash scripts/start.sh              # Web UI 模式（默认）
bash scripts/start.sh headless     # 命令行模式（直接生成）
bash scripts/start.sh api          # API 服务模式
```

### 🎓 `scripts/finetune/finetune_lora.py` — LoRA 微调

```bash
# 准备数据集
python scripts/finetune/prepare_dataset.py \
    --source local \
    --caption_strategy filename \
    --input_path /path/to/images \
    --name my-dataset

# 执行 LoRA 训练
python scripts/finetune/finetune_lora.py \
    --method lora \
    --base_model stabilityai/stable-diffusion-xl-base-1.0 \
    --dataset_dir outputs/datasets/my-dataset \
    --output_dir outputs/finetune/my-lora \
    --max_train_steps 1000 \
    --learning_rate 1e-4 \
    --lora_rank 64 \
    --mixed_precision fp16 \
    --validation_prompt "a cat wearing a hat"
```

---

## 🐳 Docker 部署

### 文件说明

| 文件 | 用途 |
|------|------|
| `Dockerfile` | 基于 `rocm/dev-ubuntu-24.04`，预装 Python 3.12 + PyTorch ROCm + 项目依赖 |
| `docker-compose.yml` | 一键启动配置，含 GPU 透传、卷挂载、健康检查 |
| `.dockerignore` | 构建上下文过滤（排除模型/缓存/输出文件） |
| `scripts/docker_build.sh` | 构建镜像脚本（含前置检查 + 验证） |
| `scripts/docker_start.sh` | 启动容器脚本（支持 web / headless / api / shell 模式） |

### 前置条件

- 装有 AMD ROCm 显卡的 Linux 主机
- Docker 已安装并运行
- 已安装 ROCm 容器运行时（`amdgpu-dkms`、`rocm-hip-libraries`）

### 构建镜像

```bash
# 默认构建
bash scripts/docker_build.sh

# 指定标签，不缓存
bash scripts/docker_build.sh -n amd-ai-studio -t v1.0 --no-cache
```

### 启动容器

```bash
# 方式一：Docker Compose（推荐）
docker compose up -d

# 方式二：启动脚本
bash scripts/docker_start.sh                    # Web UI 模式
bash scripts/docker_start.sh -m headless        # 命令行模式
bash scripts/docker_start.sh -m api             # API 模式
bash scripts/docker_start.sh -m shell           # 进入 Shell

# 方式三：手动 docker run
docker run -d \
    --name amd-ai-studio \
    --device=/dev/kfd --device=/dev/dri \
    --group-add=video --group-add=render \
    --network host \
    -e HOST=0.0.0.0 \
    -e HSA_OVERRIDE_GFX_VERSION=11.0.0 \
    -v amd-ai-studio-hf-cache:/workspace/.cache/huggingface \
    -v amd-ai-studio-outputs:/workspace/amd-ai-studio/outputs \
    amd-ai-studio:latest
```

### 容器内使用

```bash
# 进入容器
docker exec -it amd-ai-studio /bin/bash

# 下载模型
bash scripts/download_models.sh

# 查看日志
docker logs -f amd-ai-studio

# 停止容器
docker stop amd-ai-studio
```

### 国内镜像加速

如果无法拉取 Docker Hub 的 ROCm 基础镜像，可以：

1. 修改 `Dockerfile` 第一行的镜像源为国内镜像
2. 或提前拉取并打标签：
```bash
# 从国内镜像拉取
docker pull registry.docker-cn.com/rocm/dev-ubuntu-24.04:latest
docker tag registry.docker-cn.com/rocm/dev-ubuntu-24.04:latest rocm/dev-ubuntu-24.04:latest
```

---

## 🧠 技术栈

| 组件 | 技术 |
|------|------|
| 推理框架 | Diffusers + PyTorch (ROCm 7.2.3) |
| 文生图 | Stable Diffusion XL (Base + Refiner) |
| 图生视频 | Stable Video Diffusion (SVD-XT) |
| 图像修复 | SDXL Inpainting |
| 微调方法 | LoRA (Low-Rank Adaptation) |
| UI 框架 | Gradio 5 |
| GPU 加速 | ROCm + FP16 + Attention Slicing + VAE Tiling |
| 显存优化 | Sequential CPU Offload / Model Offload / TF32 |
| 模型源 | ModelScope（国内默认）/ Hugging Face 镜像 |

## ⚙️ 性能优化

系统自动检测 AMD GPU 并应用以下优化：

- **FP16 推理**：显存减半，速度翻倍
- **Attention Slicing**：降低显存峰值
- **VAE Tiling**：支持大分辨率图像生成
- **Sequential CPU Offload**：显存不足时自动启用
- **TF32 加速**：CDNA 架构自动启用
- **torch.compile**：24GB+ 显存自动启用 UNet 编译

使用 `model_optimizer.py` 中的基准测试工具评估性能：

```python
from modules.model_optimizer import run_benchmark, format_benchmark
from modules.txt2img import generate_txt2img

result = run_benchmark(generate_txt2img, prompt="a cat", num_runs=5)
print(format_benchmark(result))
```

## 🤝 社区与支持

- **Discord**: [加入 AMD AI 社区](https://discord.gg/zt9caur5B3)
- **Email**: ai_dev_contests@amd.com
- **AMD AI Developer Program**: [https://developer.amd.com/ai-developer-program](https://developer.amd.com/ai-developer-program)

## 📜 License

本项目仅用于 AMD AI DevMaster Hackathon 参赛。