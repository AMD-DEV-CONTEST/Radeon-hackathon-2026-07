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
- Qwen/Qwen-Image-2512

## 启动文件(若SDK为Gradio/Streamlit，默认为app.py, 若为Static HTML, 默认为index.html)
# deployspec:
#   entry_file: app.py
license: Apache License 2.0
---
#### Clone with HTTP
```bash
 git clone https://www.modelscope.cn/studios/xihuyisheng/Qwen-Image-2512-AMD-MI308X.git
```

## 项目简介

基于通义千问最新文生图模型 **Qwen-Image-2512**（20B MMDiT 扩散模型）构建的本地化文本生成图像应用，专为 **AMD Instinct MI308X / MI300X** GPU（ROCm 环境）深度优化，开箱即用。

### 核心特性

- 🎨 **文生图推理**：基于 Qwen/Qwen-Image-2512（20B MMDiT 扩散模型），支持中英文双语提示词，自动追加质量后缀（超清 4K、电影级构图）
- ⚡ **AMD ROCm 加速**：bfloat16 精度 + Flash Attention 2 注意力机制，AOTriton 后端加速，TF32 矩阵乘法优化
- 💾 **全量 GPU 加载**：模型完整载入 MI308X 192GB HBM3 显存，零换页、低延迟
- 🖼️ **7 种官方推荐分辨率**：覆盖 1:1 / 16:9 / 9:16 / 4:3 / 3:4 / 3:2 / 2:3 多种画幅比例
- 🎯 **精细化参数控制**：可调推理步数（10-100）、CFG 引导系数（1.0-10.0）、随机种子（支持复现）
- 🌟 **8 个一键示例**：涵盖风光、赛车、街景、美食、宇宙、古风、萌宠等场景，点击即填提示词
- 📝 **正负向提示词双向控制**：内置默认负向提示词，规避低画质、肢体畸形、AI 感等问题
- 💻 **实时运行日志**：流式输出模型加载、推理耗时、显存占用等过程信息，全程可见
- 🔌 **MCP 服务器模式**：每个 API 端点自动映射为 MCP 工具，支持智能体调用

### 技术栈

| 类别 | 选型 |
|---|---|
| 模型 | Qwen/Qwen-Image-2512（20B MMDiT） |
| 硬件 | AMD Instinct MI308X / MI300X（ROCm ≥ 6.3.0） |
| 精度 | bfloat16（ROCm 原生支持） |
| 注意力 | Flash Attention 2（AOTriton 后端） |
| 推理框架 | PyTorch (ROCm 版) + ModelScope DiffusionPipeline |
| Web 界面 | Gradio 6.0+ |

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

## 生成参数

| 参数 | 说明 | 推荐值 |
|---|---|---|
| 推理步数 | 步数越多质量越高 | 50 |
| CFG 引导系数 | 值越高越贴合提示词 | 4.0 |
| 分辨率 | 7 种官方推荐比例 | 1328×1328 |

## 免责声明

本工具仅供学习研究使用。用户需遵守法律法规及平台规范，严禁生成违法违规内容。用户对生成内容负全部责任。
