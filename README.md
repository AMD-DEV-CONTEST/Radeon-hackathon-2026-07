# Supply Chain DocAgent — 供应链单据智能处理 Agent

> 基于 AMD Radeon GPU + ROCm 的本地私有 AI Agent，自动完成供应链入库单据的识别、提取、校验与录入。

## AMD AI DevMaster 黑客松提交

**赛道**: 赛道二：私有 AI Agent 开发与本地部署  
**团队**: cyslmsolomon  
**项目**: Supply Chain DocAgent

## 项目简介

供应链入库环节涉及大量非结构化单据：采购订单（PO）、送货单、质检报告、入库单、发票。传统方式依赖人工逐单核对，效率低、易出错、难追溯。

本项目构建了一个**多 Agent 协作的单据处理系统**，基于 AMD Radeon GPU 和 ROCm 软件栈完全本地运行，实现：

- **单据智能识别**：多模态 LLM 自动识别单据类型（PO/送货单/质检报告/发票）
- **信息结构化提取**：从非结构化文档中提取关键字段（物料编码、数量、单价、日期）
- **三单交叉校验**：自动核对 PO vs 送货单 vs 发票，检测数量差异和价格异常
- **异常智能处理**：异常单据自动分类并推送给对应负责人审批
- **ERP 自动录入**：校验通过的数据自动写入企业系统

## 技术架构

```
[单据输入] 拍照/扫描 | PDF/Excel | 邮件附件
       ↓
┌─────────────────────────────────────────────┐
│         Multi-Agent Orchestrator             │
│  ┌──────────┐ ┌──────────┐ ┌──────────────┐ │
│  │ Classify │ │ Extract  │ │ Validate     │ │
│  │ Agent    │ │ Agent    │ │ Agent        │ │
│  └──────────┘ └──────────┘ └──────────────┘ │
│  ┌──────────┐ ┌──────────┐                  │
│  │录入 Agent│ │异常 Agent│                  │
│  └──────────┘ └──────────┘                  │
├─────────────────────────────────────────────┤
│         RAG Engine (LlamaIndex)              │
│  单据模板知识库 + 历史异常案例库              │
├─────────────────────────────────────────────┤
│      LLM Inference (vLLM + ROCm)            │
│         AMD Radeon GPU Acceleration          │
└─────────────────────────────────────────────┘
       ↓
[输出] 核对通过 → 自动入库 | 异常 → 推送审批
```

## 核心能力（对应赛事评分）

| 能力 | 实现方式 | 评分项 |
|---|---|---|
| 本地知识检索（RAG） | 单据模板库 + 历史案例检索 | Agent 功能完整性 |
| 工具调用 | ERP API、邮件发送、文件操作 | 工具调用与工作流编排 |
| 多步骤任务规划 | 识别→提取→校验→录入→异常处理 | 多步骤任务规划 |
| 本地多轮记忆 | 对话历史 + 处理记录持久化 | 本地多轮记忆 |
| 权限控制 | 按角色分权（录入员/审批人/管理员） | 隐私保护机制 |

## 快速开始

### 环境要求

- AMD Radeon GPU（推荐 RX 7900 XTX 或更高，24GB VRAM）
- ROCm 6.x+
- Python 3.10+
- Ubuntu 22.04（推荐）

### 安装

```bash
git clone https://github.com/your-username/supply-chain-docagent.git
cd supply-chain-docagent

python -m venv venv
source venv/bin/activate

pip install -r requirements.txt

# 验证 ROCm
python -c "import torch; print(f'ROCm: {torch.cuda.is_available()}')"
```

### 运行

```bash
python -m src.agent
```

访问 http://localhost:7860 打开 Web UI。

## 项目结构

```
supply-chain-docagent/
├── README.md
├── requirements.txt
├── config/
│   └── settings.yaml
├── src/
│   ├── __init__.py
│   ├── agent.py              # 多 Agent 编排核心
│   ├── rag.py                # 单据模板 RAG 引擎
│   ├── tools.py              # 业务工具（ERP/邮件/校验）
│   ├── memory.py             # 处理记录记忆
│   └── ui.py                 # Gradio Web UI
├── data/
│   └── sample_docs/          # 示例单据（PO/送货单/发票）
├── docs/
│   └── project_report.md     # 技术报告
└── scripts/
    └── demo.py               # 演示脚本
```

## 提交清单

- [x] 项目源代码
- [x] README（含环境配置、启动指南、依赖列表）
- [x] 项目说明文档（docs/project_report.md）
- [ ] 演示视频（3-5 分钟）
- [ ] 补充材料（PPT/海报，可选）

## License

MIT
