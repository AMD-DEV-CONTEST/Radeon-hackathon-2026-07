---
# 详细文档见 https://modelscope.cn/docs/%E5%88%9B%E7%A9%BA%E9%97%B4%E5%8D%A1%E7%89%87
domain: #领域：cv/nlp/audio/multi-modal/AutoML
# - cv
tags: #自定义标签
-
datasets: #关联数据集
  evaluation:
  #- iic/ICDAR13_HCTR_Dataset
  test:
  #- iic/MTWI
  train:
  #- iic/SIBR
models: #关联模型
#- iic/ofa_ocr-recognition_general_base_zh
- Qwen/Qwen-Image-Edit-2511

## 启动文件(若SDK为Gradio/Streamlit，默认为app.py, 若为Static HTML, 默认为index.html)
# deployspec:
#   entry_file: app.py
license: Apache License 2.0
---
#### Clone with HTTP
```bash
 git clone https://www.modelscope.cn/studios/xihuyisheng/Qwen-Image-Edit-2511-AMD-MI308X.git
```

## 项目简介

基于 **Qwen-Image-Edit-2511**（通义千问最新图生图编辑模型）的图像编辑应用，专为 **AMD MI308X** GPU 优化。

- **模型**: Qwen/Qwen-Image-Edit-2511（图像编辑 MMDiT 扩散模型）
- **功能**: 图生图 / 图像编辑（背景替换、风格转换、人物换装等）
- **硬件**: AMD Instinct MI308X / MI300X（ROCm 环境）
- **精度**: bfloat16
- **注意力**: Flash Attention 2 / PyTorch SDPA（AMD ROCm 原生优化）
- **内存**: 全量 GPU 加载（MI308X 192GB HBM3 无压力）

## 环境要求

- ROCm >= 6.3.0
- PyTorch (ROCm 版本)
- 显存 >= 64GB（推荐 192GB MI308X）

## 安装

```bash
pip install -r requirements.txt
```

## 运行

```bash
python app.py
```

启动后访问 `http://localhost:7860` 即可使用。

## 使用说明

1. 上传一张输入图像（或点击界面中的示例图片一键加载）
2. 输入编辑指令（如：将背景替换为海滩、换成油画风格等）
3. 可选调整推理步数 / CFG / 种子后点击生成

## 生成参数

| 参数 | 说明 | 推荐值 |
|---|---|---|
| 推理步数 | 步数越多质量越高 | 25-50 |
| CFG 引导系数 | 值越高越贴合指令 | 4.0 |
| 随机种子 | -1 为随机 | -1 |

## 免责声明

本工具仅供学习研究使用。用户需遵守法律法规及平台规范，严禁生成违法违规内容。用户对生成内容负全部责任。
