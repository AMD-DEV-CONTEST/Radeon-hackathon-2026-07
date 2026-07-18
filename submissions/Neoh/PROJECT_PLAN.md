# AMD Radeon 本地智能体系统 - 项目规划与技术报表

---

## 一、项目概述

### 1.1 项目定位

本项目是一个**完全本地化部署**的 AI Agent 系统，基于 **AMD Radeon GPU** 与 **ROCm** 软件栈构建。所有推理计算均在本地 GPU 上完成，确保数据隐私与低延迟响应。

**项目名称**：Radeon-Assistant  
**团队名称**：Neoh  
**赛道**：Track 2 - 私有 AI Agent 开发与本地部署

### 1.2 核心价值

| 维度 | 说明 |
|------|------|
| 🎯 隐私保护 | 100% 数据本地处理，零外部 API 调用 |
| ⚡ 高性能 | 基于 ROCm + llama.cpp 的 GPU 加速推理 |
| 🔧 可扩展 | 模块化架构，支持工具扩展和模型切换 |
| 📚 知识驱动 | 内置 RAG 系统，支持私有文档问答 |

---

## 二、模型功能说明

### 2.1 模型选型

| 组件 | 选型 | 版本 | 用途 |
|------|------|------|------|
| 基础大模型 | Qwen2.5-7B-Instruct | GGUF Q4_K_M | 核心推理、任务规划、工具调用决策 |
| Embedding 模型 | all-MiniLM-L6-v2 | - | 文档向量化、语义检索 |
| 向量数据库 | FAISS | 1.8.0 | 本地向量存储与相似度检索 |

### 2.2 模型功能矩阵

| 功能 | 实现方式 | GPU加速 | 说明 |
|------|---------|---------|------|
| 自然语言理解 | Qwen2.5-7B | ✅ | 理解用户意图和上下文 |
| 多步骤任务规划 | LLM 链式推理 | ✅ | 将复杂任务分解为可执行步骤 |
| 工具调用决策 | ReAct 模式 | ✅ | 判断何时调用工具及调用哪个 |
| 文档向量化 | all-MiniLM-L6-v2 | ✅ | 将文本转为向量表示 |
| 相似度检索 | FAISS | ✅ | Top-K 最相似文档检索 |
| 结果反思与修正 | LLM 自我评估 | ✅ | 检查执行结果并优化 |

### 2.3 模型配置参数

```yaml
model:
  path: "./models/qwen2.5-7b-instruct-q4_k_m.gguf"
  n_gpu_layers: -1        # 全部加载到 GPU
  n_ctx: 8192             # 上下文窗口大小
  n_batch: 512            # 批处理大小
  temperature: 0.7        # 创造性控制
  max_tokens: 4096        # 最大生成长度
```

---

## 三、实现流程详解

### 3.1 系统启动流程

```
┌─────────────────────────────────────────────────────────────────┐
│                      系统启动流程                                 │
├─────────────────────────────────────────────────────────────────┤
│  Step 1: 环境检查                                                │
│  ├─ rocm-smi --showproductname → 验证 GPU                        │
│  ├─ 检查 ROCm 版本 ≥ 7.0                                        │
│  └─ 验证 CUDA_VISIBLE_DEVICES / HIP_VISIBLE_DEVICES             │
│                                                                 │
│  Step 2: 配置加载                                                │
│  ├─ 读取 config.yaml                                            │
│  ├─ 解析模型路径和参数                                           │
│  └─ 加载工具列表                                                 │
│                                                                 │
│  Step 3: 模型初始化                                              │
│  ├─ 加载 GGUF 模型到 GPU                                        │
│  ├─ 设置 n_gpu_layers=-1 (全量 offload)                         │
│  └─ 初始化 KV 缓存                                               │
│                                                                 │
│  Step 4: 组件初始化                                              │
│  ├─ 初始化 FAISS 向量数据库                                     │
│  ├─ 加载 Embedding 模型 (GPU 加速)                              │
│  ├─ 注册工具到工具中心                                           │
│  └─ 初始化记忆管理器                                             │
│                                                                 │
│  Step 5: 服务启动                                                │
│  ├─ 启动 Streamlit Web 服务                                     │
│  └─ 监听端口 7860                                                │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 RAG 文档处理流程（离线阶段）

```
用户上传文档 → 文档解析 → 文本分块 → 向量化 → 存入 FAISS → 持久化
     │              │           │          │             │
     │         PDF/DOCX/MD    chunk_size  GPU 加速     本地磁盘
     │         提取纯文本      = 512      384维向量    index.faiss
     └─────────────────────────────────────────────────────────────┘
```

### 3.3 RAG 问答流程（在线阶段）

```
用户提问 → 问题向量化 → FAISS 检索 → 构建上下文 → LLM 生成 → 返回答案
     │              │            │            │           │          │
     │           GPU 加速     Top-K=5      拼接参考    GPU 推理   带引用来源
     └───────────────────────────────────────────────────────────────────┘
```

### 3.4 多步骤任务规划与执行流程

```
┌─────────────────────────────────────────────────────────────────┐
│                   Plan-and-Execute 循环                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  用户输入 → [Planner] → 任务分解 → [Executor] → 工具调用        │
│                                     ↓                           │
│                              [Reflector] → 结果评估             │
│                                     ↓                           │
│                              成功？→ 是 → 返回最终结果           │
│                              ↓ 否                               │
│                         [Reviser] → 修正计划 → 回到 Executor     │
│                                                                 │
│  最大迭代次数: max_iterations = 10                              │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 3.5 ReAct 推理-行动循环

```
Thought (思考): "用户想分析 git 提交记录，我需要先获取提交日志"
  ↓
Action (行动): execute_command("git log --since=2026-06-01")
  ↓
Observation (观察): "获取到 45 条提交记录，涉及 5 位开发者"
  ↓
Thought (思考): "有了提交记录，现在需要统计每位开发者的提交数量"
  ↓
Action (行动): code_interpreter("统计代码...")
  ↓
... 循环直到完成 ...
```

---

## 四、模块划分与职责

### 4.1 项目目录结构

```
submissions/Neoh/
├── app.py                 # 应用入口
├── config.yaml            # 全局配置
├── requirements.txt       # 依赖列表
├── agent/                 # Agent 核心编排层
│   ├── core.py            # Agent 主循环
│   ├── planner.py         # 任务规划器
│   ├── executor.py        # 任务执行器
│   ├── reflector.py       # 结果反思器
│   └── reviser.py         # 计划修正器
├── inference/             # 推理引擎层
│   ├── engine.py          # llama.cpp 封装
│   └── model_loader.py    # 模型加载管理
├── tools/                 # 工具层
│   ├── registry.py        # 工具注册中心
│   ├── file_tools.py      # 文件操作工具
│   ├── shell_tools.py     # 命令行执行工具
│   ├── email_tools.py     # 邮件工具
│   ├── code_tools.py      # 代码解释器
│   └── system_tools.py    # 系统信息工具
├── memory/                # 记忆层
│   ├── manager.py         # 记忆管理器
│   ├── short_term.py      # 短期对话记忆
│   └── long_term.py       # 长期向量记忆
├── ui/                    # 前端界面
│   └── web_app.py         # Streamlit Web 界面
├── scripts/               # 辅助脚本
│   ├── download_model.py  # 模型下载脚本
│   └── init_rag.py        # RAG 初始化脚本
├── models/                # 模型文件目录
└── data/                  # 数据存储目录
    ├── faiss_index/       # FAISS 向量索引
    └── documents/         # 上传的文档
```

### 4.2 模块职责详解

| 模块 | 文件 | 职责 | 依赖 |
|------|------|------|------|
| **agent** | core.py | Agent 主循环，协调各组件 | langgraph, inference |
| | planner.py | 将用户任务分解为步骤列表 | inference |
| | executor.py | 执行单个步骤，调用工具 | tools, inference |
| | reflector.py | 评估执行结果，判断是否完成 | inference |
| | reviser.py | 根据评估结果修正计划 | inference |
| **inference** | engine.py | llama.cpp 推理引擎封装 | llama-cpp-python |
| | model_loader.py | 模型加载和配置管理 | engine.py |
| **tools** | registry.py | 工具注册和发现机制 | - |
| | file_tools.py | 文件读写、目录管理 | - |
| | shell_tools.py | 安全沙箱内执行命令 | psutil |
| | email_tools.py | 邮件发送（需用户配置） | - |
| | code_tools.py | Python 代码解释执行 | - |
| | system_tools.py | 系统状态查询 | psutil |
| **memory** | manager.py | 统一记忆管理接口 | short_term, long_term |
| | short_term.py | 会话内上下文保持 | langchain |
| | long_term.py | 跨会话向量记忆 | FAISS |
| **ui** | web_app.py | Streamlit 前端界面 | streamlit |
| **scripts** | download_model.py | 模型下载脚本 | - |
| | init_rag.py | RAG 数据初始化 | memory |

---

## 五、数据集与微调策略

### 5.1 数据集说明

**本项目不需要训练数据集，也不涉及模型微调。**

| 数据类型 | 来源 | 用途 | 存储方式 |
|----------|------|------|---------|
| 用户私有文档 | 用户上传 | RAG 知识检索 | 本地磁盘 (data/documents/) |
| 向量索引 | 文档向量化生成 | 相似度检索 | FAISS 索引文件 |
| 对话历史 | 用户交互生成 | 短期记忆 | 内存 + 可选持久化 |
| 用户偏好 | 系统学习生成 | 个性化响应 | JSON 文件 |

### 5.2 为什么不做微调

| 原因 | 说明 |
|------|------|
| 时间限制 | 黑客松时间短，微调需要数天训练 |
| 资源限制 | 单个 GPU 微调 7B 模型效率低 |
| RAG 替代 | 通过 RAG 注入领域知识，效果接近微调 |
| 灵活性 | RAG 知识可随时更新，无需重新训练 |
| 隐私保护 | 微调需要上传数据到训练环境，违背隐私原则 |

### 5.3 知识注入策略

```
预训练模型 (Qwen2.5-7B) + RAG (私有文档) → 领域专家 Agent
     │                    │
     │              用户上传文档
     │              (PDF/Word/MD/TXT)
     │                    │
     └────────────────────┘
              GPU 向量化 + FAISS 存储
```

---

## 六、API 调用决策表

### 6.1 完整决策矩阵

| 功能模块 | 功能点 | 是否使用外部 API | 使用的服务 | 隐私合规性 | 说明 |
|----------|--------|------------------|-----------|-----------|------|
| **核心推理** | LLM 对话生成 | ❌ | llama.cpp (本地) | ✅ 完全合规 | 所有推理在本地 GPU 执行 |
| | 任务规划 | ❌ | llama.cpp (本地) | ✅ 完全合规 | 同上 |
| | 工具调用决策 | ❌ | llama.cpp (本地) | ✅ 完全合规 | 同上 |
| **RAG 系统** | 文档向量化 | ❌ | sentence-transformers (本地) | ✅ 完全合规 | 使用 all-MiniLM-L6-v2 |
| | 相似度检索 | ❌ | FAISS (本地) | ✅ 完全合规 | 向量数据库本地运行 |
| **文件操作** | 读写文件 | ❌ | Python 标准库 | ✅ 完全合规 | 本地文件系统操作 |
| | 目录管理 | ❌ | Python 标准库 | ✅ 完全合规 | 同上 |
| **命令执行** | Shell 命令 | ❌ | subprocess (本地) | ✅ 完全合规 | 安全沙箱内执行 |
| **代码解释** | Python 执行 | ❌ | exec/eval (本地) | ✅ 完全合规 | 受限环境执行 |
| **系统信息** | CPU/GPU/内存 | ❌ | psutil/rocm-smi | ✅ 完全合规 | 本地系统调用 |
| **邮件服务** | 邮件发送 | ⚠️ 可选 | SMTP (用户配置) | ⚠️ 需用户确认 | 用户可选择启用/禁用 |
| | 邮件接收 | ❌ | 不支持 | ✅ 完全合规 | 未实现 |
| **日历管理** | 日程查询 | ❌ | 不支持 | ✅ 完全合规 | 未实现 |
| | 日程创建 | ❌ | 不支持 | ✅ 完全合规 | 未实现 |
| **Web 搜索** | 网络搜索 | ❌ | 不支持 | ✅ 完全合规 | 离线优先设计 |

### 6.2 隐私保护设计原则

| 原则 | 实现方式 |
|------|---------|
| 零数据外泄 | 所有 LLM 调用在本地执行，不发送数据到云端 |
| 用户可控 | 邮件等外部服务需要用户主动配置和授权 |
| 审计日志 | 记录所有高危操作，便于追溯 |
| 操作审批 | 删除文件、执行命令等高危操作需用户确认 |

### 6.3 支持的外部 API（可选）

用户可根据需要在 `config.yaml` 中配置以下外部服务：

```yaml
external_services:
  email:
    enabled: false
    smtp_server: "smtp.example.com"
    smtp_port: 587
    username: ""
    password: ""
```

---

## 七、实施计划

### 7.1 阶段划分

| 阶段 | 时间 | 目标 | 交付物 |
|------|------|------|--------|
| **Phase 1** | Day 1-2 | 环境搭建与核心推理 | inference 模块、模型下载脚本 |
| **Phase 2** | Day 3-4 | RAG 系统实现 | memory 模块、文档处理 |
| **Phase 3** | Day 5-6 | Agent 核心编排 | agent 模块、工具层 |
| **Phase 4** | Day 7-8 | 前端界面 | ui 模块、Web 交互 |
| **Phase 5** | Day 9-10 | 优化与测试 | ROCm 优化、性能测试 |
| **Phase 6** | Day 11-12 | 文档与提交 | README、PDF、PPT、Demo 视频 |

### 7.2 详细任务列表

```
Phase 1: 环境搭建与核心推理
├── [x] 创建项目目录结构
├── [x] 创建 requirements.txt 和 config.yaml
├── [ ] 实现 inference/engine.py (llama.cpp 封装)
├── [ ] 实现 inference/model_loader.py (模型加载)
└── [ ] 创建 scripts/download_model.py (模型下载)

Phase 2: RAG 系统实现
├── [ ] 实现 memory/vector_store.py (FAISS 封装)
├── [ ] 实现 memory/manager.py (记忆管理)
├── [ ] 实现文档解析器 (PDF/Word/MD)
└── [ ] 创建 scripts/init_rag.py (RAG 初始化)

Phase 3: Agent 核心编排
├── [ ] 实现 tools/registry.py (工具注册)
├── [ ] 实现 tools/file_tools.py (文件操作)
├── [ ] 实现 tools/shell_tools.py (命令执行)
├── [ ] 实现 tools/code_tools.py (代码解释)
├── [ ] 实现 tools/system_tools.py (系统信息)
├── [ ] 实现 tools/email_tools.py (邮件服务)
├── [ ] 实现 agent/planner.py (任务规划)
├── [ ] 实现 agent/executor.py (任务执行)
├── [ ] 实现 agent/reflector.py (结果反思)
└── [ ] 实现 agent/core.py (Agent 主循环)

Phase 4: 前端界面
├── [ ] 实现 ui/web_app.py (Streamlit)
└── [ ] 创建 app.py (应用入口)

Phase 5: 优化与测试
├── [ ] ROCm GPU 优化 (量化、批处理)
├── [ ] 性能基准测试
├── [ ] 功能完整性测试
└── [ ] Bug 修复

Phase 6: 文档与提交
├── [ ] 完善 README.md
├── [ ] 创建 Project Specification Document (PDF)
├── [ ] 录制 Demo Video (3-5 min)
├── [ ] 创建 PPT 演示文稿
└── [ ] 提交 PR
```

### 7.3 优先级标记

| 优先级 | 标记 | 说明 |
|--------|------|------|
| 🔴 高 | 必须完成，阻塞后续工作 | 推理引擎、Agent 核心、RAG |
| 🟡 中 | 重要功能，提升体验 | 前端界面、邮件工具 |
| 🟢 低 | 可选优化，锦上添花 | 性能调优、额外工具 |

---

## 八、技术风险与应对

### 8.1 风险矩阵

| 风险 | 概率 | 影响 | 应对策略 |
|------|------|------|---------|
| ROCm 环境配置复杂 | 高 | 高 | 提供 Docker 一键部署方案 |
| llama.cpp GPU 加速问题 | 中 | 高 | 提供 CPU 降级方案 |
| 模型下载缓慢 | 中 | 中 | 提供模型镜像下载链接 |
| GPU 显存不足 | 低 | 高 | 使用 Q4_K_M 量化，支持模型分片 |
| 工具调用安全性 | 中 | 中 | 高危操作审批机制 |

### 8.2 降级方案

```
GPU 不可用 → 自动切换到 CPU 模式 (速度下降但功能完整)
模型文件不存在 → 提示用户运行下载脚本
FAISS 初始化失败 → 跳过 RAG，仅使用基础对话
```

---

## 九、验收标准

### 9.1 功能验收

| 验收项 | 通过条件 | 测试方法 |
|--------|---------|---------|
| 模型加载 | 成功加载 Qwen2.5-7B 到 GPU | 检查 llama.cpp 输出 |
| RAG 问答 | 基于上传文档准确回答问题 | 上传测试文档并提问 |
| 工具调用 | 正确识别并调用工具 | 测试文件读写、命令执行 |
| 任务规划 | 分解复杂任务并执行 | 测试多步骤任务 |
| 隐私保护 | 无外部 API 调用 | 监控网络流量 |

### 9.2 性能验收

| 指标 | 目标值 | 测试平台 |
|------|--------|---------|
| 首 Token 延迟 | < 1.5s | Radeon RX 7900 XT |
| 生成速度 | > 50 tokens/s | Radeon RX 7900 XT |
| GPU 利用率 | > 70% | 推理时监控 |
| RAG 检索延迟 | < 200ms | 10k 文档 |

---

## 十、提交材料清单

### 10.1 必须提交

| 材料 | 格式 | 要求 |
|------|------|------|
| Project Specification Document | PDF | 包含架构图、功能介绍、优化说明 |
| 源代码 | GitHub | 完整代码仓库，含 README |
| Demo Video | MP4 | 3-5 分钟，演示实际操作 |
| PPT / Poster | PPT/PDF | 项目介绍 |

### 10.2 PR 标题格式

```
Track 2, Neoh, Radeon-Assistant
```

---

**文档版本**：v1.0  
**创建日期**：2026-07-18  
**团队**：Neoh