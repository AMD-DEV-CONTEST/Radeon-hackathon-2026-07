# 提交说明 — Candy Sticker Generator

> 英文版：[README.md](README.md)
>
> **Track 1 · 多模态内容创作工具开发** ·
> AMD AI DevMaster Hackathon 2026

本 `submission/` 目录是 **Candy Sticker Generator**（糖果番剧 Q 版贴纸生成器）的整合评审包。
完整源码树位于 `../src/`；本文件夹包含评审者 **阅读、运行与核验** 项目所需的全部内容——
严格依据**真实功能架构**撰写（无虚构功能）。

## 真实功能架构（已在代码中验证）

| 模式 | 路径 | 证据 |
|---|---|---|
| **文字 → 贴纸套组** | 输入角色描述 → SDXL Animagine XL 4.0（含自训 `stkstyle` LoRA）→ 8 表情 → floodfill 去底 → EDT 模切白边 → 2×4 拼版 + ZIP（微信 500 / Telegram 512 / 印刷 300dpi+出血） | `../src/webui/gradio_app.py`（mode=`文字`） |
| **图片 → 贴纸套组**（即"图生图"路径） | 上传参考图或草图 → **Qwen2.5-VL-3B-Instruct** 解析角色描述 → 回填提示词框 → 复用文字模式的同一 SDXL 管线 | `../src/multimodal/img2prompt.py`（mode=`参考图`/`草图`） |
| **风格 LoRA** | 自训 `stkstyle` LoRA 适配器（animagine-xl-4.0 基座，rank 32，2000 步）；权重随仓库内置；训练 loss 曲线见证据图 | `../src/lora/models/stkstyle_lora_diffusers/` + `docs/evidence_gpu/fig_lora_training.png` |

**明确不在范围内（已移除）：** 动态 / 动画贴纸生成 —— LTX-Video 原型因 ROCm 兼容性问题已放弃，
**不**属于本次提交。

## 目录内容

```
submission/
├── README.md                          ← 本文件英文版
├── README.zh.md                       ← 本文件中文版
└── docs/
    ├── Project_Profile.md / .pdf      ← 5 要素档案（概览 / 技术栈 / 创新 / AMD / 结果）
    ├── presentation.pptx              ← 演示幻灯片（含 LoRA on AMD ROCm + GPU 证据）
    └── evidence_gpu/                  ← AMD Radeon GPU 证据（见下）

```

## 运行项目

```bash
pip install -r ../requirements.txt
python ../src/webui/gradio_app.py --port 7860
# 打开 http://localhost:7860
```

模型需单独下载 —— 见 `../MODELS.md`。`stkstyle` LoRA 已随仓库内置
（`../src/lora/models/stkstyle_lora_diffusers/`），无需额外下载。

## 评分点映射（各评分项落在何处）

| 评分维度 | 在本包中的位置 |
|---|---|
| 完整端到端工作流 (40) | `../src/webui/gradio_app.py` + `../src/generation/` + `../demo_output/`（8 张贴纸） |
| 图生图 / 多模态闭环 | `../src/multimodal/img2prompt.py`（Qwen-VL on AMD） |
| 风格 LoRA on AMD ROCm（训练 + 推理） | `../src/lora/models/stkstyle_lora_diffusers/` + `docs/evidence_gpu/fig_lora_training.png` |
| 实际价值 (20) — 印刷、微信、Telegram 导出 | `../src/generation/make_sheet_export.py` |
| AMD ROCm 合规（全部 GPU 负载跑在 Radeon 上） | `docs/evidence_gpu/`（四张图 + 设备快照） |
| 多样性 | 8 种情绪表情 + 自定义角色 + 自训风格 |

## AMD ROCm 证据（`docs/evidence_gpu/`）

全部 GPU 证据均于**今日**在同一张运行演示的 AMD Radeon（Navi 31, gfx1100, 48 GB, ROCm 7.2）
上重新生成。`rocm-smi --showuse` 与 sysfs `gpu_busy_percent` 都只统计 GFX（图形）引擎，
在 RDNA3 上对 UNet 计算读数为 0%，因此采样器改用 **板卡功耗 (W)** 经 `rocm-smi --showpower`
记录：空闲约 16 W，推理时跳到 200–300 W，是无可辩驳的「Radeon GPU 在干活」证据。

| 文件 | 证明内容 |
|---|---|
| `fig_sdxl_gpu.png` | SDXL 贴纸生成 —— 三次连续生成期间板卡功耗跳到 ~200–300 W，VRAM 爬升到 ~10 GB |
| `fig_img2prompt_gpu.png` | **图生提示词（Qwen2.5-VL-3B）** —— 图生图多模态环节中板卡功耗持续 ~150–200 W |
| `fig_lora_training.png` | `stkstyle` LoRA 训练 —— 完整 2000 步的 loss 曲线 + 单步耗时（来自 `train.log`） |
| `fig_overview.png` | 三种 ROCm 负载在同一张 AMD Radeon 上对比 |
| `device_info.txt` | 硬件快照（Navi 31, 48 GB, ROCm-smi, torch） |
| `gpu_evidence.json` | 原始 **板卡功耗(W) + VRAM** 时序（机器可读） |
