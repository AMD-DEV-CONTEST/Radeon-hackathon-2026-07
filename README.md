# 🎬 AMD Radeon Studio — AI 多模态创作工坊

> 基于 **AMD Radeon GPU + ROCm** 的多模态 AI 内容创作工具
> 参赛作品：AMD 开发者挑战赛 · **Track 1 Multimodal AI**

![status](https://img.shields.io/badge/status-WIP-yellow) ![pytorch](https://img.shields.io/badge/PyTorch-ROCm-red) ![python](https://img.shields.io/badge/python-3.10%2B-blue)

---

## ✨ 项目简介

面向**新媒体内容创作者**的一站式 AI 创作工坊。一句文案 + 几张参考图 → 一条 15–30 秒的完整风格化短片（图 + 视频 + 配乐 + 字幕）。

### 核心能力

| 模块 | 说明 | 状态 |
|------|------|------|
| 🎨 文生图 / 图编辑 | FLUX.1 / SDXL + InstructPix2Pix | 规划中 |
| 🖌️ 风格迁移 | IP-Adapter + LoRA | 规划中 |
| 🎬 图生视频 | Wan2.1 / AnimateDiff（ROCm 优化）| 规划中 |
| ✨ 画质增强 | Real-ESRGAN（AMD 优化版） | 规划中 |
| 🎞️ 一键短片 | LLM 拆解分镜 + 全链路编排 | 规划中 |
| 🖥️ Web UI | Gradio / FastAPI | 规划中 |

---

## 🛠️ 环境要求

| 项 | 要求 |
|----|------|
| GPU | AMD Radeon（推荐 16GB+ 显存，MI300X / RX 7900 XTX / Radeon PRO W7900 等）|
| ROCm | 6.1+ |
| PyTorch | 2.4+（**必须装 ROCm 版**）|
| Python | 3.10+ |
| 内存 | 32GB+ 推荐 |
| 硬盘 | 50GB+（模型占大头）|

> ⚠️ **关键**：PyTorch 不能用 `pip install torch`，必须走 ROCm 专用索引。

---

## 🚀 快速开始（以 Linux / Ubuntu 22.04 为例）

### 1. 安装 ROCm 驱动

参考 [AMD 官方文档](https://rocm.docs.amd.com/projects/install-on-linux/en/latest/install-quick-start.html)。

```bash
# 验证 ROCm 是否装好
rocminfo | grep "Marketing Name"
# 应输出类似：  Marketing Name:  AMD Instinct MI300X VF
```

### 2. 安装 ROCm 版 PyTorch

```bash
pip install --upgrade pip
pip install torch torchvision --index-url https://download.pytorch.org/whl/rocm6.1
```

验证：
```python
import torch
print(torch.__version__, torch.version.hip)  # 应输出 ROCm 版本号
print(torch.cuda.is_available())             # 应为 True
```

### 3. 克隆/上传本仓库到 VM

把整个 `AMD_Radeon_Studio/` 文件夹上传到 JupyterLab VM（拖拽即可）。

```bash
cd AMD_Radeon_Studio
pip install -r requirements.txt
```

### 4. 跑环境验证

打开 JupyterLab：
```bash
jupyter lab
```

依次执行 `notebooks/00_env_check.ipynb` 全部 cells。
**通过标志**：最后一个 cell 打印 `🎉 ALL CHECKS PASSED` 并在 `outputs/00_env_check.png` 生成一张图。

### 5. 国内加速（可选）

如果 HF 拉模型慢，在 notebook 第一个 cell 加：
```python
import os
os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'
```

---

## 📁 项目结构

```
AMD_Radeon_Studio/
├── README.md                 ← 你正在看
├── requirements.txt          ← Python 依赖
├── .gitignore
├── notebooks/                ← Jupyter 开发笔记（按 00→01→02 顺序）
│   ├── 00_env_check.ipynb
│   ├── 01_text2image.ipynb   （待写）
│   ├── 02_image_edit.ipynb   （待写）
│   ├── 03_style_transfer.ipynb（待写）
│   ├── 04_img2video.ipynb    （待写）
│   ├── 05_enhance.ipynb      （待写）
│   └── 06_one_click_reel.ipynb（待写）
├── src/                      ← 生产代码
│   ├── __init__.py
│   ├── config.py             ← 全局配置
│   ├── models/               ← 各模态模型封装
│   ├── api/                  ← FastAPI 后端
│   └── utils/                ← 视频合成、工具函数
├── comfyui_workflows/        ← ComfyUI 工作流 JSON
├── data/                     ← 输入素材
├── outputs/                  ← 生成结果（git ignored）
└── docs/                     ← 项目文档 / PPT / 海报
```

---

## 🧪 开发路线（7 天冲刺版）

| Day | 目标 | 交付物 |
|-----|------|--------|
| D1 | 环境验证 + 文生图跑通 | `00_env_check` ✅ / `01_text2image` |
| D2 | 图像编辑 + 风格迁移 | `02` / `03` |
| D3 | 画质增强（Real-ESRGAN） | `05` |
| D4 | 图生视频（Wan2.1） | `04` |
| D5 | Agent 调度 + 一键短片 | `06` |
| D6 | Web UI + 性能压测 | FastAPI + Gradio |
| D7 | 录演示视频 + 写文档 | 项目简介 PDF + README |

---

## 🤝 致谢

- AMD ROCm 团队 — 提供开源 GPU 算力栈
- HuggingFace Diffusers — 模型生态
- ComfyUI — 工作流编排灵感

## 📄 License

Apache 2.0
