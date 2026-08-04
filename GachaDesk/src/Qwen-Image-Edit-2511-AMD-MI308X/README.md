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
- Qwen/Qwen-Image-Edit-2511

## Entry file (defaults to app.py for Gradio/Streamlit SDK, index.html for Static HTML)
# deployspec:
#   entry_file: app.py
license: Apache License 2.0
---
#### Clone with HTTP
```bash
 git clone https://www.modelscope.cn/studios/xihuyisheng/Qwen-Image-Edit-2511-AMD-MI308X.git
```

## Introduction

An image editing application based on **Qwen-Image-Edit-2511** (the latest image-to-image editing model from Tongyi Qianwen), optimized for **AMD MI308X** GPU.

- **Model**: Qwen/Qwen-Image-Edit-2511 (image-editing MMDiT diffusion model)
- **Features**: Image-to-image / image editing (background replacement, style transfer, character outfit swap, etc.)
- **Hardware**: AMD Instinct MI308X / MI300X (ROCm environment)
- **Precision**: bfloat16
- **Attention**: Flash Attention 2 / PyTorch SDPA (native AMD ROCm optimization)
- **Memory**: Full GPU loading (MI308X 192GB HBM3 is more than sufficient)

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

## Usage

1. Upload an input image (or click one of the example images in the UI to load it instantly)
2. Enter an editing instruction (e.g. replace the background with a beach, convert to oil-painting style, etc.)
3. Optionally adjust inference steps / CFG / seed, then click Generate

## Generation Parameters

| Parameter | Description | Recommended Value |
|---|---|---|
| Inference Steps | More steps yield higher quality | 25-50 |
| CFG Scale | Higher value follows the instruction more strictly | 4.0 |
| Random Seed | -1 for random | -1 |

## Disclaimer

This tool is for research and educational purposes only. Users must comply with applicable laws, regulations, and platform policies, and are strictly prohibited from generating illegal or harmful content. Users bear full responsibility for the content they generate.
