# RepositoryAnalysisAgent (RAA)

> 隐私优先的本地代码库智能助手，专为 AMD Radeon GPU 优化。

[English](README.md)

---

## 项目简介

RAA 完全运行在本地 AMD GPU 上。它通过 tree-sitter AST 解析对代码仓库建立索引，结合向量检索和交叉编码器重排序，使用 ReAct 智能体循环来回答代码相关问题——全程代码不离开本机。

**核心能力：**
- 仓库级代码理解（跨文件分析）
- Bug 定位与根因追踪
- 代码结构与依赖分析
- AST 感知的语义搜索 + GPU 重排序
- 多轮 ReAct 推理 + 工具调用

**不是什么：**
- 不是代码补全工具（无 FIM/自动补全）
- 不是云服务（全部本地运行）

---

## 目标环境

| 组件 | 版本 |
|---|---|
| GPU | AMD Radeon PRO W7900 (48GB GDDR6, RDNA3 / gfx1100) |
| ROCm | 7.2.1 |
| PyTorch | 2.9 (ROCm 版) |
| vLLM | 0.16.0 |
| Python | 3.10 |
| LLM | Qwen2.5-Coder-14B-Instruct (FP16, ~28GB) |
| Embedding | BAAI/bge-m3 (CPU) |
| Reranker | BAAI/bge-reranker-v2-m3 (GPU, ~1.5GB) |

**Docker 镜像（预装 PyTorch + vLLM + ROCm）：**
```
10.5.10.89:1808/xinwei/radeon-cloud/vllm-dev:rocm7.2.1_navi_ubuntu22.04_py3.10_pytorch_2.9_vllm_0.16.0
```

---

## 快速开始

### 1. 进入容器，克隆代码

```bash
source /opt/venv/bin/activate   # 激活 venv（含 PyTorch + vLLM）
cd /workspace
git clone -b Repository-Analysis-Agent https://github.com/xiting-it/Radeon-hackathon-2026-07.git
cd Radeon-hackathon-2026-07/RepositoryAnalysisAgent
```

### 2. 安装应用依赖

```bash
bash setup.sh    # 安装依赖、卸载 flash-attn、设置 ROCm 环境变量
```

### 3. 下载模型

```bash
bash download_models.sh          # 全部模型 (~31GB)
# 或分开下载：
bash download_models.sh --rag-only    # embedding + reranker (~3GB)
bash download_models.sh --llm-only    # Qwen 14B (~28GB)
```

### 4. 验证环境

```bash
python scripts/verify_rocm.py
```

所有检查应通过（gfx1100、PyTorch ROCm、attention backend、推理稳定性、vLLM）。

### 5. 启动 vLLM（终端 1）

```bash
MODEL_PATH=./models/Qwen2.5-Coder-14B-Instruct bash start_llm.sh
```

等待 `Application startup complete`（冷启动约 2-4 分钟）。

### 6. 启动 RAA（终端 2）

```bash
python -m src.server /workspace/Radeon-hackathon-2026-07/RepositoryAnalysisAgent
```

### 7. 打开 Web UI

浏览器访问 `http://127.0.0.1:8080`。先索引仓库，然后提问。

SSH 远程访问：
```bash
ssh -L 8080:127.0.0.1:8080 root@<服务器IP> -p <端口>
```

---

## 架构

```
浏览器 (localhost:8080)
    │
    ▼
FastAPI 服务 (src/server.py)
    │
    ├── /api/chat (SSE 流式)
    │       │
    │       ▼
    │   Agent 引擎 (ReAct 循环, 最多 8 轮)
    │       │
    │       ├── 上下文构建器 (32K token 预算)
    │       ├── 工具注册表
    │       │   ├── search_code  (向量检索 → GPU 重排序 → top-15)
    │       │   ├── grep_code    (ripgrep 精确/正则搜索)
    │       │   ├── read_file    (按行范围读取)
    │       │   ├── get_symbols  (tree-sitter AST 符号提取)
    │       │   ├── find_references (启发式符号引用查找)
    │       │   └── run_tests    (默认禁用)
    │       └── LLM 后端 (vLLM OpenAI 兼容 API)
    │
    ├── /api/index (异步后台索引)
    │       │
    │       ▼
    │   索引管线
    │       ├── tree-sitter AST 代码块提取
    │       ├── BGE-m3 向量编码 (CPU, batch=16)
    │       └── ChromaDB 向量存储 (持久化)
    │
    └── /api/health, /api/sessions, /api/workspace

GPU 显存布局 (总共 48GB):
  vLLM 服务:       ~42GB (权重 28 + KV 池 12 + 运行时 2)
  重排序器 (GPU):   ~1.5GB (模型 0.6 + HIP context 0.9)
  剩余:            ~4.3GB
```

---

## 配置

所有配置在 `config.yaml`。关键选项：

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `server.host` | `127.0.0.1` | 隐私优先：仅绑定本地回环 |
| `llm.max_model_len` | `32768` | 14B 原生支持 128K |
| `llm.gpu_memory_utilization` | `0.88` | 14B FP16 需要约 30GB |
| `llm.enforce_eager` | `true` | gfx1100 HIP graph 不稳定 |
| `embedding.device` | `cpu` | 一次性索引操作 |
| `reranker.device` | `cuda` | 在线查询关键路径 |
| `security.run_tests_enabled` | `false` | pytest = 任意代码执行 |

---

## AMD W7900 优化

**GDDR6 带宽天花板**: 864 GB/s ÷ 28GB (14B FP16) ≈ 31 tok/s 理论上限。

**实测 Benchmark：**

| 指标 | 数值 |
|---|---|
| 单请求吞吐 | ~8 tok/s |
| 8 路并发吞吐 | ~57 tok/s |
| 首 token 延迟 (TTFT) | 0.26s |
| 理论效率比 | ~27% |

**关键决策：**
- `enforce_eager=true`：gfx1100 HIP graph 捕获崩溃；损失 10-20% 吞吐但稳定
- FP8 权重/KV cache：gfx1100 不可用（vLLM ROCm FP8 kernel 为 gfx942/MI300X 编写）
- 重排序器放 GPU：每次查询 ~0.5s vs CPU 4-7s
- Embedding 放 CPU：一次性索引，避免与 vLLM 的显存冲突
- ROCm 稳定性变量：`HSA_ENABLE_SDMA=0`、`AMD_SERIALIZE_KERNEL=3`、`AMD_SERIALIZE_COPY=3`

---

## Benchmark 与评估

```bash
# 吞吐量 benchmark
python scripts/benchmark.py --base-url http://127.0.0.1:8000/v1

# 20 题质量评估（LLM-as-judge）
python scripts/eval_agent.py --app-url http://127.0.0.1:8080
```

---

## 隐私

- API 绑定 `127.0.0.1`，不暴露到网络
- 推理、索引、搜索全部本地完成
- 无遥测、无外部请求
- 可验证：`tcpdump` 显示运行时零出站流量

---

## 常见问题

| 问题 | 解决方案 |
|---|---|
| `torch.cuda.is_available()` = False | 使用 `/opt/venv/bin/activate`；确认 ROCm 版 PyTorch |
| vLLM: `No module named 'flash_attn_2_cuda'` | `pip uninstall flash-attn -y` |
| vLLM: 可用显存 < 42GB | 杀残留进程：`pkill -9 -f vllm`；检查 `rocm-smi` |
| 多轮对话 400 错误 | 更新到最新代码；已加上下文裁剪 |
| 模型用英文回答 | 最新 prompt 强制中文；pull 后重启 |
| 索引无响应 | 确认 venv 里装了 chromadb：`pip install chromadb` |

---

## 许可证

MIT
