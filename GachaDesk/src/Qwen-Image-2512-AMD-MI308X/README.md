---
# 详细文档见 https://modelscope.cn/docs/%E5%88%9B%E7%A9%BA%E9%97%B4%E5%8D%A1%E7%89%87
domain: # domain: cv/nlp/audio/multi-modal/AutoML
# - cv
tags: # custom tags
-
datasets: # linked datasets
  evaluation:
  #- iic/ICDAR13_HCTR_Dataset
  test:
  #- iic/MTWI
  train:
  #- iic/SIBR
models: # linked models
#- iic/ofa_ocr-recognition_general_base_zh
- Qwen/Qwen-Image-2512

## Entry file (defaults to app.py for Gradio/Streamlit SDK, index.html for Static HTML)
# deployspec:
#   entry_file: app.py
license: Apache License 2.0
---
#### Clone with HTTP
```bash
 git clone https://www.modelscope.cn/studios/xihuyisheng/Qwen-Image-2512-AMD-MI308X.git
```

## Introduction

A localized text-to-image application built on the latest Tongyi Qianwen text-to-image model **Qwen-Image-2512** (20B MMDiT diffusion model), deeply optimized for **AMD Instinct MI308X / MI300X** GPUs (ROCm environment), ready to use out of the box.

### Core Features

- 🎨 **Text-to-Image Inference**: Powered by Qwen/Qwen-Image-2512 (20B MMDiT diffusion model), supports bilingual (Chinese/English) prompts, automatically appends quality suffixes (4K ultra-HD, cinematic composition)
- ⚡ **AMD ROCm Acceleration**: bfloat16 precision + Flash Attention 2, AOTriton backend acceleration, TF32 matrix multiplication optimization
- 💾 **Full GPU Loading**: The model is loaded entirely into the MI308X 192GB HBM3 VRAM, zero paging, low latency
- 🖼️ **7 Official Recommended Resolutions**: Covers 1:1 / 16:9 / 9:16 / 4:3 / 3:4 / 3:2 / 2:3 aspect ratios
- 🎯 **Fine-Grained Parameter Control**: Adjustable inference steps (10-100), CFG scale (1.0-10.0), random seed (reproducible)
- 🌟 **8 One-Click Examples**: Covers landscapes, racing cars, street scenes, food, cosmos, traditional Chinese style, cute pets and more — click to fill the prompt
- 📝 **Positive / Negative Prompt Dual Control**: Built-in default negative prompt to avoid low quality, malformed limbs, AI artifacts, etc.
- 💻 **Real-Time Runtime Log**: Streaming output of model loading, inference latency, VRAM usage — fully visible
- 🔌 **MCP Server Mode**: Each API endpoint is automatically mapped to an MCP tool, ready for agent invocation

### Tech Stack

| Category | Choice |
|---|---|
| Model | Qwen/Qwen-Image-2512 (20B MMDiT) |
| Hardware | AMD Instinct MI308X / MI300X (ROCm ≥ 6.3.0) |
| Precision | bfloat16 (native ROCm support) |
| Attention | Flash Attention 2 (AOTriton backend) |
| Inference Framework | PyTorch (ROCm build) + ModelScope DiffusionPipeline |
| Web UI | Gradio 6.0+ |

## Environment Requirements

- ROCm >= 6.3.0
- PyTorch (ROCm build)
- VRAM >= 64GB (192GB MI308X recommended)

## Installation

```bash
pip install -r requirements.txt
```

## Run

```bash
python app.py
```

Once launched, open `http://localhost:7860` in your browser to use the app.

## Generation Parameters

| Parameter | Description | Recommended Value |
|---|---|---|
| Inference Steps | More steps yield higher quality | 50 |
| CFG Scale | Higher value follows the prompt more strictly | 4.0 |
| Resolution | 7 official recommended ratios | 1328×1328 |

## Disclaimer

This tool is for research and educational purposes only. Users must comply with applicable laws, regulations, and platform policies, and are strictly prohibited from generating illegal or harmful content. Users bear full responsibility for the content they generate.
