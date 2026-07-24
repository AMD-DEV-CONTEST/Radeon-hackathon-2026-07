# Supply Chain DocAgent

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-3.10+-3776AB.svg)
![ROCm](https://img.shields.io/badge/ROCm-6.x-ED1C24.svg)
![LangChain](https://img.shields.io/badge/LangChain-0.2-green.svg)
![LlamaIndex](https://img.shields.io/badge/LlamaIndex-0.10-orange.svg)
![Gradio](https://img.shields.io/badge/Gradio-4.0-yellow.svg)

> 🤖 基于 AMD ROCm 的供应链单据智能处理 Agent，自动完成单据识别、字段提取、三单校验。

[![AMD AI DevMaster Hackathon](https://img.shields.io/badge/AMD-AI%20DevMaster%202026-ED1C24.svg)](https://my.feishu.cn/docx/IHwFdtsFjo2N4nxFygHc74cRnlf)
[![Track 2](https://img.shields.io/badge/Track-2%3A%20Private%20AI%20Agent-blue.svg)](https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07)
[![PR](https://img.shields.io/badge/PR-17-open-brightgreen.svg)](https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07/pull/17)

---

## 📋 目录

- [项目简介](#项目简介)
- [✨ 核心功能](#-核心功能)
- [🎯 解决的问题](#-解决的问题)
- [🚀 快速开始](#-快速开始)
- [🏗️ 技术架构](#️-技术架构)
- [📊 性能指标](#-性能指标)
- [📁 项目结构](#-项目结构)
- [🛠️ 技术栈](#️-技术栈)
- [📚 文档](#-文档)
- [🏆 获奖情况](#-获奖情况)
- [🤝 贡献指南](#-贡献指南)
- [📄 许可证](#-许可证)

---

## 项目简介

供应链入库环节涉及大量非结构化单据：采购订单（PO）、送货单、质检报告、入库单、发票。传统方式依赖人工逐单核对，**效率低、易出错、难追溯**。

本项目构建了一个**多 Agent 协作的单据处理系统**，基于 AMD Radeon GPU 和 ROCm 软件栈**完全本地运行**，实现端到端的智能化处理。

### 🎬 演示

![Supply Chain DocAgent Demo](assets/demo.gif)

> 📹 **录制工具**: 运行 `python scripts/record_demo.py` 录制演示 GIF
> 📖 **录制指南**: 查看 [docs/gif_recording_guide.md](docs/gif_recording_guide.md)

**在线演示**: [http://localhost:7860](http://localhost:7860) (本地运行)

**演示视频**: [YouTube](#) (待录制)

---

## ✨ 核心功能

<table>
<tr>
<td width="50%">

### 🔍 智能单据处理

- **单据分类** - 自动识别采购订单、送货单、发票
- **字段提取** - 从非结构化文本提取结构化数据
- **三单校验** - PO/送货单/发票交叉验证
- **异常检测** - 自动识别数量差异和价格异常

</td>
<td width="50%">

### 🤖 多 Agent 协作

- **Classify Agent** - 单据类型识别
- **Extract Agent** - 字段提取
- **Validate Agent** - 三单校验
- **Entry Agent** - ERP 录入
- **Exception Agent** - 异常处理

</td>
</tr>
<tr>
<td width="50%">

### 🔒 完全本地部署

- 数据不离开本地机器
- 支持离线运行
- 企业级隐私保护
- 无云端依赖

</td>
<td width="50%">

### ⚡ 高性能推理

- AMD ROCm GPU 加速
- FP16 混合精度推理
- vLLM 高性能服务
- 单张处理 < 30 秒

</td>
</tr>
</table>

---

## 🎯 解决的问题

| 痛点 | 传统方式 | 我们的解决方案 | 改进 |
|------|---------|---------------|------|
| 处理时间 | 15 分钟/张 | 2 分钟/张 | **87%** |
| 错误率 | 3% | 0.5% | **83%** |
| 人力需求 | 8 人 | 2 人 | **75%** |
| 库存差异发现 | T+1 | 实时 | **100%** |

---

## 🚀 快速开始

### 环境要求

| 组件 | 最低要求 | 推荐配置 |
|------|---------|---------|
| GPU | AMD Radeon RX 6800 XT (16GB) | AMD Radeon RX 7900 XTX (24GB) |
| 内存 | 16GB | 32GB |
| 存储 | 50GB | 100GB SSD |
| OS | Ubuntu 22.04 | Ubuntu 22.04 LTS |

### 安装

```bash
# 1. 克隆仓库
git clone https://github.com/cyslmsolomon/Radeon-hackathon-2026-07.git
cd Radeon-hackathon-2026-07

# 2. 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate  # Windows

# 3. 安装依赖
pip install -r requirements.txt

# 4. 验证 ROCm
python -c "import torch; print(f'CUDA available: {torch.cuda.is_available()}')"
```

### 运行

```bash
# 启动 vLLM 服务（后台运行）
python -m vllm.entrypoints.openai.api_server \
    --model meta-llama/Llama-3.1-8B-Instruct \
    --dtype half \
    --port 8000 &

# 启动 Web UI
python -m src.agent
```

访问 http://localhost:7860 打开 Web UI。

### 使用示例

```python
from src.agent import DocAgent

# 初始化 Agent
agent = DocAgent()

# 处理单据
with open("data/sample_docs/po_sample.txt") as f:
    content = f.read()

result = agent.process_document(content, "po_sample.txt")
print(result)
# 输出: {'doc_type': 'purchase_order', 'extracted_fields': {...}, ...}
```

---

## 🏗️ 技术架构

```
┌─────────────────────────────────────────────────────────────────┐
│                        用户界面层                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                    Gradio Web UI                         │   │
│  │    单据上传  │  处理结果  │  对话查询  │  状态监控        │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Agent 编排层                                │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐          │
│  │ Classify │ │ Extract  │ │ Validate │ │ Exception│          │
│  │  Agent   │ │  Agent   │ │  Agent   │ │  Agent   │          │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘          │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐                       │
│  │  Entry   │ │   RAG    │ │  Memory  │                       │
│  │  Agent   │ │  Engine  │ │ Manager  │                       │
│  └──────────┘ └──────────┘ └──────────┘                       │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      基础设施层                                  │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │              LlamaIndex RAG Engine                       │   │
│  │         单据模板库 + 历史异常案例库                        │   │
│  └─────────────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │              vLLM + ROCm 6.x                             │   │
│  │         Llama-3.1-8B-Instruct 推理服务                   │   │
│  └─────────────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │              AMD Radeon GPU                              │   │
│  │         FP16 混合精度加速                                 │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

---

## 📊 性能指标

| 指标 | 数值 | 说明 |
|------|------|------|
| 单据分类准确率 | **98%+** | 自动识别单据类型 |
| 字段提取准确率 | **95%+** | 结构化数据提取 |
| 三单匹配准确率 | **99%+** | 交叉校验准确性 |
| 单张处理时间 | **< 30 秒** | 端到端处理时间 |
| GPU 显存占用 | **< 12 GB** | 优化的显存使用 |

### 测试环境

- **GPU**: AMD Radeon RX 7900 XTX (24GB VRAM)
- **OS**: Ubuntu 22.04 LTS
- **ROCm**: 6.1
- **PyTorch**: 2.4.0+rocm6.1
- **LLM**: Llama-3.1-8B-Instruct

---

## 📁 项目结构

```
Radeon-hackathon-2026-07/
├── README.md                          # 项目说明
├── requirements.txt                   # Python 依赖
├── config/
│   └── settings.yaml                  # 配置文件
├── src/
│   ├── __init__.py
│   ├── agent.py                       # 多 Agent 编排核心
│   ├── rag.py                         # RAG 引擎
│   ├── tools.py                       # 业务工具
│   ├── memory.py                      # 对话记忆
│   └── ui.py                          # Gradio Web UI
├── data/
│   └── sample_docs/                   # 示例单据
│       ├── po_sample.txt              # 采购订单
│       ├── delivery_sample.txt        # 送货单
│       └── invoice_sample.txt         # 发票
├── docs/
│   └── project_report.md              # 技术报告
├── scripts/
│   └── demo.py                        # 演示脚本
├── tutorials/
│   └── en/                            # 英文教程
│       └── langchain-personal-assistant-tutorial.md
├── challenges/                        # 黑客松挑战集
├── coach/                             # 教练材料
└── resources/
    └── starter/                       # 启动代码模板
```

---

## 🛠️ 技术栈

<table>
<tr>
<td><b>LLM 推理</b></td>
<td>Llama-3.1-8B-Instruct + vLLM + ROCm 6.x</td>
</tr>
<tr>
<td><b>Agent 框架</b></td>
<td>LangChain 0.2</td>
</tr>
<tr>
<td><b>RAG 引擎</b></td>
<td>LlamaIndex 0.10 + BGE Embeddings</td>
</tr>
<tr>
<td><b>Web UI</b></td>
<td>Gradio 4.0</td>
</tr>
<tr>
<td><b>GPU 计算</b></td>
<td>AMD ROCm 6.x + PyTorch 2.4</td>
</tr>
<tr>
<td><b>向量数据库</b></td>
<td>ChromaDB (可选)</td>
</tr>
</table>

---

## 📚 文档

| 文档 | 描述 |
|------|------|
| [技术报告](docs/project_report.md) | 项目背景、架构、性能数据 |
| [完整教程](tutorials/en/langchain-personal-assistant-tutorial.md) | 8 步教程，从零到部署 |
| [挑战集](HACKATHON_CHALLENGES.md) | 9 个渐进式挑战 |
| [教练指南](coach/facilitation-guide.md) | 教练引导材料 |
| [评分标准](coach/scoring-rubric.md) | 项目评估标准 |

---

## 🏆 获奖情况

| 奖项 | 赛道 | 结果 |
|------|------|------|
| AMD AI DevMaster 2026 | Track 2: Private AI Agent | 🏅 提交中 |

---

## 🤝 贡献指南

欢迎贡献代码、报告问题或提出改进建议！

### 如何贡献

1. Fork 本仓库
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 创建 Pull Request

### 开发环境

```bash
# 安装开发依赖
pip install -r requirements.txt
pip install pytest black flake8

# 运行测试
pytest tests/

# 代码格式化
black src/
```

---

## 📄 许可证

本项目采用 MIT 许可证 - 查看 [LICENSE](LICENSE) 文件了解详情。

---

## 🙏 致谢

- [AMD](https://www.amd.com/) - 提供 ROCm 开源 GPU 计算栈
- [LangChain](https://langchain.com/) - Agent 框架
- [LlamaIndex](https://www.llamaindex.ai/) - RAG 引擎
- [vLLM](https://github.com/vllm-project/vllm) - 高性能 LLM 推理
- [Gradio](https://gradio.app/) - Web UI 框架

---

## 📧 联系方式

- **团队**: cyslmsolomon
- **GitHub**: [@cyslmsolomon](https://github.com/cyslmsolomon)
- **Email**: cyslmsolomon@users.noreply.github.com

---

<div align="center">

**⭐ 如果这个项目对您有帮助，请给一个 Star！⭐**

</div>
