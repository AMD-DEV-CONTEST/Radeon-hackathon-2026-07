# Private RAG Agent — 本地私有 AI 智能体

> **2026 AMD AI DevMaster 黑客松 · 赛道 2（本地私有 AI Agent / Agentic AI 本地部署）**
> 完全离线 · 本地推理 · 数据不出本机 · AMD Radeon GPU / ROCm 优化

---

## 📌 项目简介

一个**全离线、本地私有化**的多 Agent RAG 智能体：导入私有文档，通过"分解 → 并行研究 → 事实核查 → 综合"的协作管线回答复杂问题，全程不依赖任何云端 API。

**核心卖点：**
- 🔒 **数据不出本机** —— 切片、向量化、检索、推理全部本地完成
- ⚡ **AMD GPU 本地推理** —— 多后端（llama.cpp HIP / Ollama ROCm / vLLM），支持 Radeon Cloud
- 🧠 **多 Agent 协作** —— Decomposer / 并行 Researchers / Fact-Checker / Synthesizer
- ✅ **可追溯 + 可核查** —— 混合检索 → cross-encoder 重排 → groundedness 事实核查 → 引用即点即查
- 📄 **多格式文档** —— PDF / Word / Markdown / Excel / PPT 全部支持

---

## ✨ 快速开始

### 环境要求
- **AMD Radeon GPU**（推荐 RX 7900 XTX / W7900，16GB+ 显存；或 Radeon Cloud）
- ROCm 6.x（AMD Linux）/ Ollama（Windows）
- Python 3.10+

### 1. 安装
```bash
git clone https://github.com/你的账号/private-rag-agent
cd private-rag-agent
pip install -r requirements.txt
```

### 2. 启动本地推理服务
```bash
# 方式 A：Ollama（最简单）
ollama pull qwen3:8b        # LLM
ollama pull bge-m3          # Embedding
ollama serve

# 方式 B：llama.cpp + ROCm（AMD GPU 原生）
# CMAKE_ARGS="-DGGML_HIP=ON" pip install llama-cpp-python
```

### 3. 导入文档 + 启动网页
```bash
python main.py ingest data/docs/   # 批量导入
python main.py ui                  # http://localhost:7860
```

### 🐳 一键容器化部署
```bash
docker compose up -d --build
docker exec -it private-rag-ollama ollama pull qwen3:8b
docker exec -it private-rag-ollama ollama pull bge-m3
```
在 AMD + ROCm 主机上取消 `docker-compose.yml` 中 ollama 的 `devices` 注释即可让 GPU 进容器。

---

## 🏗️ 架构

### 端到端链路

```
┌──────────────────────────────────────────────────────────────┐
│  UI（FastAPI + SSE + 原生 HTML/CSS/JS）                        │
│  ├── 流式对话（打字机效果 + 活动时间线）                         │
│  ├── 运行轨迹面板（实时工具/核查事件）                           │
│  ├── GPU 监控面板（利用率/显存/温度/时钟）                       │
│  └── 来源深潜抽屉（点引用看原文 + 查询高亮）                     │
├──────────────────────────────────────────────────────────────┤
│  Agent 层                                                      │
│  ├── Agent 主循环   感知→规划→工具→回答→引用校验                 │
│  ├── MultiAgent    分解→并行研究→事实核查→综合                  │
│  ├── Planner       任务规划（复杂问题自动触发）                  │
│  ├── Memory        多轮 + 长期记忆                              │
│  └── Tools         rag_search / read_doc / list_docs 工具        │
├──────────────────────────────────────────────────────────────┤
│  RAG 检索管线（混合检索 + 重排 + 压缩）                          │
│  ├── parser.py     PDF/Word/MD/Excel/PPT 解析                  │
│  ├── chunk_text    智能切片（512 字符 + 64 重叠）               │
│  ├── 查询改写       LLM 生成同义检索词                           │
│  ├── 向量检索        ChromaDB（bge-m3, cosine）                │
│  ├── BM25           关键词精确召回（专有名词/缩写）              │
│  ├── RRF 融合        Reciprocal Rank Fusion                   │
│  ├── cross-encoder  bge-reranker-v2-m3 重排（Top-k 精度）       │
│  ├── 近重复去重      >95% 字符级相同片段剔除                     │
│  ├── 自适应候选池    弱分填充剔除（只留真正相关的证据）            │
│  └── 上下文压缩      每片段裁剪到与查询相关的句子（更聚焦）         │
├──────────────────────────────────────────────────────────────┤
│  可信度验证                                                     │
│  ├── groundedness   回答句子 vs 检索原文 3-gram 重叠             │
│  ├── citation       引用文件名真实存在性校验                     │
│  └── LLM-as-judge   逐事实陈述判定（多 Agent 模式）              │
├──────────────────────────────────────────────────────────────┤
│  推理后端（llm.py）                                             │
│  ├── ollama / llama.cpp（GGUF + ROCm）                        │
│  └── vLLM（Radeon Cloud / ROCm 高并发）                        │
└──────────────────────────────────────────────────────────────┘
```

### 多 Agent 协作管线（"严谨性"叙事核心）

```
用户问题
   │
   ▼
① Decomposer ── 拆成 n 个相互独立的子问题
   │
   ▼
② Researchers（n 个并行子 Agent）── 各自检索知识库，产出子报告
   │  （每个子 Agent 实时转发工具/检索事件到 UI 活动面板）
   ▼
③ Fact-Checker ── 对每份子报告做两级核查
   │   · groundedness：句子 vs 检索原文 3-gram 重叠
   │   · LLM-as-judge：逐事实陈述判定
   ▼
④ Synthesizer ── 只依据"通过核查"的内容综合成最终答案
   │
   ▼
⑤ 总校验 ── 对最终答案再跑一遍 groundedness + citation
```

**并行动机（AMD 特色）**：本地 GPU 上多个推理并发排队，串行 → 并行使多步
研究任务的墙钟时间大幅下降；n 个子 Agent 共用一份 embedding / reranker 模型
（模块级单例），显存占用只加一份。

---

## 🎯 AMD / ROCm 优化（赛道评分 40 分）

### 1. 多后端推理
| 方案 | 场景 | 说明 |
|---|---|---|
| **llama.cpp (HIP)** | 单机单卡 | `CMAKE_ARGS="-DGGML_HIP=ON"`，GGUF 全 GPU offload |
| **Ollama (ROCm)** | 开箱即用 | Linux 下自动 ROCm 后端，`ollama ps` 验证 100% GPU |
| **vLLM (ROCm)** | 高并发 / Radeon Cloud | Docker: `rocm/vllm`，本项目已内置对接 |

### 2. 量化（GGUF）
| 量化 | 显存 | 速度 | 推荐 |
|---|---|---|---|
| Q8_0 | ~8.2GB | 快 | 追求精度 |
| **Q4_K_M** | ~4.6GB | 最快 | ✅ 均衡推荐 |

### 3. GPU 资源节流（小模型共享）
- embedding / reranker 用**模块级单例**，多 Agent 并行时全局只加载一份
- 检索重排按需懒加载，避免启动即占满显存

### 4. 验证与监控
```bash
rocminfo                  # 确认 ROCm 设备
rocm-smi                  # 监控 GPU 显存/温度/利用率
ollama ps                 # 确认模型 100% GPU 加载
python benchmarks/bench_amd.py   # 自动检测并输出 tokens/s
```

**开发机估算（NVIDIA RTX 4070 Laptop，Ollama qwen3:8b，CPU 推理）：** 0.2~11 token/s
（视输出长度波动，实测工件见 `benchmarks/results/bench_local_20260806.txt`）。
切换到 Radeon Cloud（RX 7900 / ROCm）后，GGUF Q4_K_M + 全层 GPU offload
预计吞吐提升 **5~10 倍**，正式提交的 `benchmarks/` 会补上实测对比数据。

---

## 📁 目录结构
```
private-rag-agent/
├── agent/
│   ├── agent.py        # Agent 主循环（规划/工具/记忆/引用校验）
│   ├── multi_agent.py  # 多 Agent 协作（分解→并行研究→核查→综合）
│   ├── rag.py          # 混合检索（向量∪BM25 → RRF → rerank）
│   ├── verify.py       # groundedness + citation 校验
│   ├── llm.py          # 推理封装（ollama / llama.cpp / vLLM）
│   ├── parser.py       # 多格式文档解析 + 智能切片
│   ├── tools.py        # 工具注册
│   ├── memory.py       # 记忆管理
│   └── planner.py      # 任务规划
├── ui/
│   ├── server.py       # FastAPI + SSE 流式接口
│   └── static/         # 原生 HTML/CSS/JS（专业级暗色界面，中英文可切换）
├── benchmarks/         # AMD ROCm 基准测试
├── config.yaml         # 配置（检索/切块/量化参数）
├── main.py             # 入口
├── deploy_rc.sh        # Radeon Cloud 部署脚本
└── requirements.txt
```

---

## 📄 提交信息（Track 2）
- **赛道**：Track 2（私有 AI 智能体本地部署）
- **队伍**：__________
- **演示视频**：__________（B站/油管链接）
- **提交截止**：2026-08-06 23:59（北京时间）

## 📌 免责声明
本项目为黑客松参赛作品，所有模型权重与文档数据均本地存储，不收集任何用户数据。
