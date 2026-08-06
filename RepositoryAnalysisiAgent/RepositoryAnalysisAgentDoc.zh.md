# RepositoryAnalysisAgent — 技术文档

> 版本: 1.0 | 日期: 2025-08-05
> 目标硬件: AMD Radeon PRO W7900 (48GB GDDR6, RDNA3 / gfx1100)
> [English Documentation](RepositoryAnalysisAgentDoc.md)

---

## 1. 系统概述

### 1.1 RAA 做什么

RepositoryAnalysisAgent (RAA) 是一套隐私优先、完全本地化的代码库智能分析系统。它结合 tree-sitter AST 代码索引、向量检索 + 交叉编码器重排序、以及多轮 ReAct 智能体循环，在单张 AMD Radeon PRO W7900 GPU 上回答代码相关问题——全程零数据外泄。

### 1.2 核心能力

| 能力 | 实现 |
|---|---|
| 仓库索引 | tree-sitter AST 解析 → 代码块提取 → 向量编码 → ChromaDB 存储 |
| 语义搜索 | BGE-m3 向量检索 (CPU) → top-20 候选 → bge-reranker (GPU) → top-15 |
| 智能体推理 | ReAct 循环（最多 8 轮），7 个工具 |
| LLM 推理 | vLLM 服务 Qwen2.5-Coder-14B-Instruct (FP16, 32K 上下文) |
| Web 界面 | FastAPI + SSE 流式输出 + 暗色主题单页应用 |

### 1.3 应用场景

1. **新人 onboarding** — "这个代码库是做什么的？结构是什么？"
2. **Bug 定位** — "认证的 bug 在哪？追踪根因。"
3. **跨文件影响分析** — "如果我改了这个函数，什么会受影响？"
4. **代码审查辅助** — "这个 diff 有什么风险？"
5. **安全审计** — "文件访问控制在哪里？有注入风险吗？"

---

## 2. 架构

### 2.1 总体架构

```
┌─────────────────────────────────────────────────────────────┐
│                   用户 (浏览器, localhost)                     │
└──────────────────────────┬──────────────────────────────────┘
                           │ HTTP (127.0.0.1:8080)
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                   FastAPI 应用层                              │
│                                                              │
│  ┌─────────┐  ┌─────────┐  ┌──────────┐  ┌───────────────┐ │
│  │ /chat   │  │ /index  │  │ /health  │  │ /workspace    │ │
│  │ (SSE)   │  │ (异步)  │  │          │  │ /sessions     │ │
│  └────┬────┘  └────┬────┘  └──────────┘  └───────────────┘ │
│       │            │                                         │
│  ┌────▼────────────▼────────────────────────────────────┐   │
│  │              Agent 引擎 (ReAct)                       │   │
│  │  ┌────────────┐  ┌──────────────┐  ┌──────────────┐  │   │
│  │  │ 上下文     │  │ 工具注册表   │  │ LLM 后端     │  │   │
│  │  │ 构建器     │  │ (7 个工具)   │  │ (vLLM HTTP)  │  │   │
│  │  └────────────┘  └──────────────┘  └──────┬───────┘  │   │
│  └───────────────────────────────────────────┼──────────┘   │
│                                              │               │
│  ┌───────────────────────────────────────────▼──────────┐   │
│  │              索引子系统                               │   │
│  │  tree-sitter → BGE-m3 (CPU) → ChromaDB                │   │
│  │                                    bge-reranker (GPU)  │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│              AMD W7900 GPU (48GB GDDR6)                      │
│                                                              │
│  进程 1: vLLM 服务           ~42GB 显存                      │
│    权重 (14B FP16): 28GB | KV 池: 12GB | 运行时: 2GB        │
│                                                              │
│  进程 2: 重排序器 (GPU)      ~1.5GB 显存                     │
│    模型: 0.6GB | HIP context + 分配器: 0.9GB               │
│                                                              │
│  CPU: BGE-m3 向量编码 (仅索引时)                             │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 组件依赖关系

```
server.py
  ├── config.py (配置加载)
  ├── backend.py (LLM HTTP 客户端)
  ├── api/routes.py (FastAPI 路由)
  │   └── api/schemas.py (Pydantic 模型)
  ├── agent/engine.py (ReAct 循环)
  │   ├── agent/context.py (Token 预算管理)
  │   ├── agent/prompts.py (系统 prompt)
  │   └── tool_parser.py (文本格式工具调用提取)
  ├── tools/registry.py (工具注册与分发)
  │   ├── tools/search.py (search_code + grep_code)
  │   ├── tools/files.py (read_file + list_directory)
  │   ├── tools/ast_tools.py (get_symbols + find_references)
  │   └── tools/exec.py (run_tests)
  ├── index/indexer.py (索引管线协调)
  │   ├── index/parser.py (tree-sitter AST)
  │   ├── index/embeddings.py (BGE-m3 CPU)
  │   ├── index/reranker.py (bge-reranker GPU)
  │   └── index/vector_store.py (ChromaDB)
  └── session/manager.py (JSON 持久化)
```

---

## 3. Agent 引擎

### 3.1 ReAct 循环

Agent 使用 ReAct（推理 + 行动）循环，基于文本格式的工具调用：

```
用户提问
    │
    ▼
┌─────────────────┐
│  上下文构建器    │ ── 系统 prompt + 仓库树 + 历史对话
└────────┬────────┘
         │
    ┌────▼─────────────────────────────┐
    │      第 1..8 轮迭代               │
    │                                   │
    │  1. 流式获取 LLM 响应             │
    │  2. 从文本中解析工具调用          │
    │  3. 如果有工具调用:               │
    │     a. 执行每个工具              │
    │     b. 结果作为 user 消息回传    │
    │     c. 继续下一轮                │
    │  4. 如果没有工具调用:            │
    │     → 最终回答，结束             │
    └───────────────────────────────────┘
```

**关键设计决策：文本格式工具调用。**

vLLM 的 hermes parser 不能可靠地为 Qwen2.5-Coder 生成结构化 `tool_calls`。因此：
- 系统 prompt 描述可用工具及其 JSON 格式
- 模型以纯文本输出工具调用（裸 JSON）
- `tool_parser.py` 使用括号匹配提取工具调用（不是正则）
- 工具结果以 `role: "user"` 消息回传（不是 `role: "tool"`）
- 完全绕过 vLLM 的 OpenAI tool_call 验证

### 3.2 工具调用解析器

解析器 (`src/tool_parser.py`) 支持多种格式：

| 格式 | 示例 | 检测方法 |
|---|---|---|
| 裸 JSON | `{"name": "search_code", "arguments": {"query": "auth"}}` | 括号匹配查找含 "name" 键的对象 |
| XML 标签 | `<tool_call>{"name": "..."}</tool_call>` | 正则提取 + JSON 解析 |
| Markdown | ` ```json {"name": "..."} ``` ` | 去除代码围栏 + JSON 解析 |
| 结构化 | OpenAI `tool_calls` 数组 | 直接字典访问 |

`_find_json_objects()` 函数使用递归括号匹配来正确处理嵌套 JSON 大括号——简单正则无法做到这一点。

### 3.3 上下文构建器

管理各消息组件的 token 预算分配：

```python
BUDGET_32K = {
    "system_prompt": 1500,
    "repo_structure": 1000,
    "conversation": 4000,
    "tool_results": 17000,
    "response_margin": 9268,
}
```

当对话增长超过预算时，自动裁剪最旧的非系统消息。

### 3.4 系统 Prompt 策略

系统 prompt 强制执行：
1. **工具优先行为**：模型在回答前必须至少调用一个工具
2. **效率**：每个问题最多 4 次工具调用
3. **证据驱动**：回答必须引用工具结果中的文件路径和行号
4. **语言跟随**：用与用户问题相同的语言回答

---

## 4. 索引子系统

### 4.1 索引管线

```
文件发现 (按扩展名过滤, 排除目录)
    │
    ▼
SHA256 哈希检查 (增量: 跳过未变更文件)
    │
    ▼
tree-sitter AST 解析
    │  提取: 函数、类、方法
    │  元数据: 名称、类型、行范围、docstring、调用
    ▼
代码块创建 (每个 AST 符号一个 chunk)
    │
    ▼
BGE-m3 向量编码 (CPU, batch_size=16)
    │
    ▼
ChromaDB 存储 (余弦相似度, 持久化)
    │
    ▼
符号表 (用于 find_references)
```

### 4.2 AST 解析器

使用 tree-sitter 和 Python 语法。对每个文件：
- 深度优先遍历 AST 树
- 提取 `function_definition` 和 `class_definition` 节点
- 对类方法，构建限定名（如 `ClassName.method_name`）
- 从 body 的第一个表达式语句提取 docstring
- 启发式提取调用表达式以跟踪依赖

回退机制：如果 tree-sitter 不可用，回退到基于行的分块（每 50 行一个 chunk）和基于正则的符号提取。

### 4.3 检索管线

```
search_code("authentication")
    │
    ▼
BGE-m3 查询向量编码 (CPU)
    │
    ▼
ChromaDB 余弦相似度搜索 → top-20 候选
    │
    ▼
bge-reranker-v2-m3 交叉编码器 (GPU)
    │  对 [query, document] 对打分
    │  归一化: sigmoid
    ▼
按分数排序, 返回 top-15
```

**为什么重排序器在 GPU**：对 20 个候选做交叉编码器重排序需要 20 次 forward pass。CPU 上 4-7 秒，GPU 上 <0.5 秒。由于 `search_code` 在 Agent 关键路径上（每次查询调用 2-3 次），CPU 重排序会增加 8-21 秒纯延迟。

### 4.4 增量索引

每个文件的 SHA256 哈希存储在缓存中 (`.raa/index/hash_cache.json`)。重新索引时：
- 变更文件：重新解析、重新编码、更新 ChromaDB
- 未变更文件：跳过（计入 `files_skipped`）
- 删除文件：从 ChromaDB 移除对应 chunk

---

## 5. 工具

### 5.1 工具注册表

所有工具实现异步 handler 模式：

```python
async def handler(**kwargs) -> str:
    # 工具逻辑
    return result_string
```

注册表提供：
- `get_definitions()`：返回 OpenAI 兼容的工具 schema 给 LLM
- `execute(name, arguments)`：分发工具调用，含错误处理
- 参数别名：`path`/`file_path`/`filepath` 均可接受

### 5.2 工具目录

| 工具 | 描述 | 关键参数 |
|---|---|---|
| `search_code` | 语义搜索 + 重排序 | `query`, `top_k` (默认 15) |
| `grep_code` | 精确文本/正则搜索 (ripgrep) | `pattern`, `file_pattern` |
| `read_file` | 读取文件内容（带行号） | `path`/`file_path`, `start_line`, `end_line` |
| `list_directory` | 列出目录内容 | `path` (默认 ".") |
| `get_symbols` | AST 符号提取 | `path`/`file_path` |
| `find_references` | 启发式符号引用查找 | `name`/`symbol`/`query` |
| `run_tests` | 运行 pytest（默认禁用） | `args` |

### 5.3 安全：run_tests

`run_tests` 默认禁用 (`security.run_tests_enabled: false`)。在不可信仓库上运行 pytest 等同于任意代码执行，因为 pytest 在 collection 阶段就会 import 所有 `conftest.py` 和测试模块——在任何测试实际运行之前。

---

## 6. API 规格

### 6.1 端点

| 方法 | 路径 | 描述 |
|---|---|---|
| POST | `/api/chat` | Agent 对话 (SSE 流式) |
| POST | `/api/index` | 触发仓库索引 |
| GET | `/api/index/status` | 索引状态 |
| GET | `/api/health` | 系统健康检查 |
| GET | `/api/workspace/tree` | 目录列表 |
| GET | `/api/workspace/file` | 文件内容 |
| GET | `/api/sessions` | 列出最近会话 |
| GET | `/api/sessions/{id}` | 会话详情 |
| DELETE | `/api/sessions/{id}` | 删除会话 |

### 6.2 Chat SSE 事件

`/api/chat` 端点返回 Server-Sent Events，事件类型如下：

| 事件类型 | 描述 | 字段 |
|---|---|---|
| `text_delta` | LLM 流式 token | `content`, `iteration` |
| `thinking` | Agent 推理文本（工具调用前） | `content`, `iteration` |
| `progress` | 人类可读的工具进度 | `content`, `tool`, `iteration` |
| `tool_call` | 正在调用的工具 | `content` (工具名), `arguments`, `iteration` |
| `tool_result` | 工具执行结果 | `content`, `tool`, `iteration` |
| `text` | 最终回答（完整） | `content` |
| `done` | 会话完成 | `content` |
| `error` | 发生错误 | `content` |

---

## 7. AMD GPU 优化

### 7.1 硬件背景

| 规格 | 数值 |
|---|---|
| GPU | AMD Radeon PRO W7900 |
| 架构 | RDNA3 (gfx1100) |
| 显存 | 48GB GDDR6 |
| 显存带宽 | 864 GB/s |
| FP16 理论算力 | ~45 TFLOPS |

### 7.2 吞吐量分析

**Decode 阶段带宽天花板：**

```
理论最大 tokens/s = 显存带宽 / 模型大小
                  = 864 GB/s / 28 GB (14B FP16)
                  ≈ 31 tok/s
```

这是假设 100% 带宽利用、零开销的物理天花板。实际因素会降低这个值：

| 因素 | 影响 |
|---|---|
| RDNA3 kernel 效率 vs CDNA | GEMM TFLOP 利用率约为 CDNA 的 50% |
| `enforce_eager`（无 HIP graph） | -10 到 -20% 吞吐 |
| AOTriton attention backend | 因 kernel 而异 |
| vLLM 框架开销 | ~5-10% |

**实测结果：**

| 指标 | 数值 | 理论效率比 |
|---|---|---|
| 单请求吞吐 | ~8 tok/s | 27% |
| 4 路并发 | ~27 tok/s | — |
| 8 路并发 | ~57 tok/s | — |
| 首 token 延迟 (TTFT) | 0.26s | — |

### 7.3 enforce_eager

gfx1100 上 HIP graph 捕获经常崩溃或输出异常。`--enforce-eager` 完全跳过 graph 捕获，代价是损失 10-20% 吞吐，但提供可靠的推理。通过环境变量控制：

```bash
ENFORCE_EAGER=true   # 默认，稳定
ENFORCE_EAGER=false  # 仅在验证 graph 模式稳定后使用
```

### 7.4 FP8 状态

FP8 在 gfx1100 上不可用，包括权重量化和 KV cache 两个方面：

- `--quantization fp8`：vLLM ROCm FP8 kernel 为 gfx942 (MI300X) Matrix Core 编写。gfx1100 RDNA3 WMMA 没有等价的 FP8 计算路径。
- `--kv-cache-dtype fp8`：同样的 kernel 依赖。最可能的结果：vLLM 启动时报错 "FP8 KV cache not supported on this backend."

Benchmark 叙事重心放在 "FP16 + 检索策略"——使用重排序的语义搜索在 32K 上下文窗口内达到等效效果，而非依赖 FP8 扩展上下文。

### 7.5 ROCm 稳定性环境变量

```bash
export PYTORCH_ROCM_ARCH=gfx1100     # 编译目标
export HSA_ENABLE_SDMA=0             # RDNA3 SDMA 传输修复
export AMD_SERIALIZE_KERNEL=3        # kernel 竞态修复
export AMD_SERIALIZE_COPY=3          # copy 竞态修复
```

这些变量解决已知的 gfx1100 稳定性问题。不加的话，GPU 推理可能产生 NaN 或跨运行不一致的结果。

### 7.6 flash-attn 卸载

Docker 镜像预装了 CUDA 编译的 `flash-attn`。在 ROCm 上会报 `ModuleNotFoundError: No module named 'flash_attn_2_cuda'`。必须在 vLLM 启动前卸载：

```bash
pip uninstall flash-attn -y
```

`setup.sh` 会自动处理。

### 7.7 GPU 显存预算

```
进程 1: vLLM (gpu_memory_utilization=0.88)
  ├── 模型权重 (14B FP16):     28 GB
  ├── PyTorch 运行时:           2 GB
  └── KV cache 池 (剩余):      12 GB
      支持: ~2 个并发 32K 序列
      或:   ~4 个并发 16K 序列
  总计:                       ~42 GB

进程 2: 重排序器 (独立进程)
  ├── 模型 (bge-reranker-v2-m3):  0.6 GB
  └── HIP context + 分配器:       0.9 GB
  总计:                           ~1.5 GB

总占用: ~43.7 GB / 48 GB (91%)
剩余:   ~4.3 GB
```

### 7.8 KV cache 计算

Qwen2.5-Coder-14B: 48 层, 8 KV heads (GQA), head_dim=128

```
每 token KV cache (FP16):
  2 (K+V) × 48 层 × 8 heads × 128 dim × 2 bytes = 196,608 bytes ≈ 192 KB/token

单序列 32K (FP16): 192KB × 32768 ≈ 6.0 GB
```

---

## 8. 安全模型

### 8.1 网络隔离

- API 默认绑定 `127.0.0.1`（仅本地回环）
- 不接受来自外部机器的入站连接
- 不发起任何外部服务的出站连接
- 可验证：`tcpdump` 显示运行时零流量

### 8.2 文件访问控制

- Agent 工具只能读取配置的仓库根目录内的文件
- 路径遍历防护：解析后的路径必须以仓库根目录开头
- 敏感文件模式从索引中排除：`*.env`、`*.key`、`*.pem`、`credentials*`、`secrets*`

### 8.3 命令执行

- `run_tests` 默认禁用
- 即使启用，也只运行配置的测试命令（`pytest`、`python -m pytest`）
- 强制超时（默认 60s）

### 8.4 只读操作

Agent 不能修改文件。除了 `run_tests` 外，所有工具都是只读的。

---

## 9. 会话管理

会话以独立 JSON 文件持久化到 `.raa/sessions/`。每个会话存储：
- 会话 ID（基于时间戳）
- 创建时间
- 消息历史（角色 + 内容 + 时间戳）
- 自动标题（取自第一条用户消息）

---

## 10. 评估

### 10.1 测试集

20 个问题，覆盖 5 个类别：
- 理解 (5 题)：架构、配置、组件行为
- Bug 定位 (5 题)：安全检查、回退行为、边缘情况
- 跨文件分析 (5 题)：请求流追踪、依赖映射
- 架构 (3 题)：设计理由、预算系统、隐私
- 测试 (2 题)：验证策略

### 10.2 评分

LLM-as-judge 对每个答案评分 0-3：
- 3：正确且完整，引用具体文件/行号
- 2：基本正确，有小遗漏
- 1：部分相关，缺少关键信息
- 0：错误或无关

目标：>70% 的题目得分 >= 2。

---

## 11. 配置参考

```yaml
server:
  host: "127.0.0.1"            # 仅回环（隐私）
  port: 8080

llm:
  backend: "vllm"
  model: "./models/Qwen2.5-Coder-14B-Instruct"
  base_url: "http://127.0.0.1:8000/v1"
  dtype: "float16"
  max_model_len: 32768
  gpu_memory_utilization: 0.88
  enforce_eager: true
  temperature: 0.3
  top_p: 0.9

embedding:
  model: "./models/bge-m3"
  device: "cpu"
  batch_size: 16

reranker:
  model: "./models/bge-reranker-v2-m3"
  device: "cuda"
  candidate_count: 20
  final_count: 15

agent:
  max_iterations: 8
  context_budget: 32768
  temperature: 0.3

security:
  run_tests_enabled: false
```

---

## 12. 部署

### 12.1 Docker

```dockerfile
FROM vllm-dev:rocm7.2.1_navi_ubuntu22.04_py3.10_pytorch_2.9_vllm_0.16.0
# 应用依赖安装到已有的 /opt/venv
# flash-attn 自动卸载
# ROCm 环境变量内嵌
```

### 12.2 启动模式

| 模式 | 命令 | 描述 |
|---|---|---|
| `all` | `docker run ... raa` | 同时启动 vLLM + RAA |
| `vllm` | `docker run ... raa vllm` | 仅 vLLM 服务 |
| `app` | `docker run ... raa app` | 仅 RAA（vLLM 需独立运行） |
| `shell` | `docker run ... raa shell` | 进 bash 调试 |

---

## 13. 测试

```bash
# 单元测试 (25 个)
python -m pytest tests/ -v

# 环境验证
python scripts/verify_rocm.py

# Benchmark
python scripts/benchmark.py --base-url http://127.0.0.1:8000/v1

# 质量评估
python scripts/eval_agent.py --app-url http://127.0.0.1:8080
```

测试覆盖：
- `test_tool_parser.py`：结构化 + 文本格式工具调用解析 (10 个测试)
- `test_parser.py`：tree-sitter AST 代码块提取 (9 个测试)
- `test_config.py`：配置加载、YAML 解析、ROCm 环境 (6 个测试)

---

## 14. 技术栈

| 层 | 技术 |
|---|---|
| 编程语言 | Python 3.10 |
| Web 框架 | FastAPI + Uvicorn |
| LLM 服务 | vLLM 0.16.0 (ROCm 7.2.1) |
| LLM 模型 | Qwen2.5-Coder-14B-Instruct (FP16) |
| AST 解析 | tree-sitter + tree-sitter-python |
| 向量编码 | BAAI/bge-m3 (sentence-transformers / FlagEmbedding) |
| 重排序器 | BAAI/bge-reranker-v2-m3 (FlagEmbedding) |
| 向量存储 | ChromaDB (余弦相似度) |
| 搜索 | ripgrep (grep_code 工具) |
| 前端 | 原生 HTML/CSS/JS + highlight.js |
| 会话存储 | JSON 文件 |
| GPU | AMD Radeon PRO W7900 (ROCm 7.2.1) |
