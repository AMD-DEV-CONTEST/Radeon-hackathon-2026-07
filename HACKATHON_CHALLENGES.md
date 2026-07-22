# AMD AI DevMaster Hackathon - Supply Chain DocAgent 挑战集

## 活动概述

**主题**: 基于 AMD Radeon GPU 的供应链单据智能处理 Agent 开发

**目标受众**: AI/ML 开发者、供应链领域工程师、对 ROCm 生态感兴趣的开发者

**前置要求**:
- 基础 Python 编程能力
- 了解 LLM 和 RAG 基本概念
- 有 AMD Radeon GPU (推荐 RX 7900 XTX) 或 ROCm 兼容环境

**技术栈**:
- AMD Radeon GPU + ROCm 6.x
- Python 3.10+
- Llama-3.1-8B / vLLM
- LangChain + LlamaIndex
- BGE Embeddings
- Gradio

---

## 挑战概览

| 挑战 | 标题 | 难度 | 时长 | 核心技能 |
|------|------|------|------|----------|
| 00 | 环境搭建与验证 | Setup | 30 min | ROCm, PyTorch, 环境配置 |
| 01 | LLM 推理服务部署 | Easy | 30 min | vLLM, GPU 推理 |
| 02 | RAG 引擎构建 | Easy | 40 min | LlamaIndex, Embeddings |
| 03 | 单据分类 Agent | Medium | 45 min | LangChain, Prompt Engineering |
| 04 | 字段提取 Agent | Medium | 45 min | JSON 提取, 结构化输出 |
| 05 | 三单校验引擎 | Hard | 60 min | 规则引擎, 交叉验证 |
| 06 | 多 Agent 编排 | Hard | 60 min | Agent 协作, 工作流 |
| 07 | Web UI 集成 | Medium | 45 min | Gradio, 用户交互 |
| 08 | 性能优化与部署 | Expert | 90 min | FP16, 批处理, 生产部署 |

---

## 难度曲线

```
难度
  │
  │                                          ┌───────┐
  │                                    ┌─────┤  08   │ Expert
  │                              ┌─────┤     └───────┘
  │                        ┌─────┤  07 │
  │                  ┌─────┤     └─────┘
  │            ┌─────┤  06 │
  │      ┌─────┤     └─────┘
  │ ┌────┤  05 │
  │ │    └─────┘
  │─┤  04 │
  │─┤  03 │
  │─┤  02 │
  │─┤  01 │
  │─┤  00 │
  └─┴─────┴─────────────────────────────────────→ 时间
    30   60   90  120  150  180  210  240  270  300  330  360 (min)
```

**总时长**: 约 6 小时 (360 分钟)

---

## 快速开始

### 方式一：本地环境

```bash
# 克隆仓库
git clone https://github.com/cyslmsolomon/Radeon-hackathon-2026-07.git
cd Radeon-hackathon-2026-07

# 安装依赖
pip install -r requirements.txt

# 验证 ROCm
python -c "import torch; print(f'CUDA available: {torch.cuda.is_available()}'); print(f'GPU: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else \"None\"}')"
```

### 方式二：Docker

```bash
docker build -t supply-chain-docagent .
docker run --gpus all -p 7860:7860 supply-chain-docagent
```

---

## 提交要求

完成挑战后，提交以下内容：

1. **源代码** - 完整的项目仓库
2. **README** - 包含环境配置、启动指南、依赖列表
3. **技术报告** (PDF) - 项目背景、架构、AMD GPU 适配说明
4. **演示视频** (3-5 分钟) - 展示实际操作流程
5. **补充材料** (可选) - PPT/海报

---

## 赛道信息

本挑战集适用于 **赛道二：私有 AI Agent 开发与本地部署**

**评审标准**:
- AI Agent 功能完整性 (60 分)
  - 场景定位与创意 (20 分)
  - 核心能力 (20 分)
  - 多轮交互 (20 分)
- AMD Radeon GPU / ROCm 适配与优化 (40 分)
  - GPU 推理 (20 分)
  - 推理优化 (20 分)

---

## 教练材料

详见 `coach/` 目录：
- [引导指南](coach/facilitation-guide.md)
- [评分标准](coach/scoring-rubric.md)
