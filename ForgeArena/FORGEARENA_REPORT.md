# ForgeArena ⚡ 本地多智能体产业决策系统

> AMD AI DevMaster 黑客松 2026 — 赛道二：私有 AI Agent 开发与本地部署
>
> 作者：@yyf121381

---

## 一、应用场景

### 1.1 金融决策分析
用户输入投资问题（个股分析、行业趋势、资产配置），系统自动搜索实时数据 + 检索知识库，由三位 AI 顾问（稳健/机会/探索）从不同风险偏好角度分析，生成结构化决策报告。

**典型用例：**
- `SK Hynix 在 HBM 市场的领先地位能否持续？`
- `Bill Seung 最近建仓了什么方向？`
- `当前全球半导体周期处于什么位置？`

### 1.2 足球战术推演
输入比赛态势（比分、时间、对手阵型），三位顾问给出不同风格的战术建议。

**典型用例：**
- `70分钟 0-0，对手低位防守 65%控球率，如何破局？`

### 1.3 TFT 云顶之弈策略
输入游戏阶段、经济、阵容，顾问给出运营决策。

**典型用例：**
- `3-2阶段 50金币 血量80，该上7还是All-in？`

### 1.4 通用决策辅助（可扩展）
任意需要多角度分析的决策场景，系统提供分歧预演与综合判断。

---

## 二、Agent 架构

```
┌─────────────────────────────────────────────────────────┐
│                    用户界面层 (Gradio)                    │
│  ┌─────────────────┐  ┌──────────────────────────────┐  │
│  │   对话区 (Chat)   │  │   分析区 (Analysis Panel)     │  │
│  │   灵钥助手对话     │  │   三顾问卡片 + 决策报告       │  │
│  └────────┬────────┘  │   证据层（折叠）               │  │
│           │           └──────────────┬───────────────┘  │
└───────────┼───────────────────────────┼─────────────────┘
            │                           │
            ▼                           ▼
┌─────────────────────────────────────────────────────────┐
│                    编排层 (Orchestrator)                  │
│  ┌──────────────────┐  ┌────────────────────────────┐   │
│  │  chat_reply()     │  │  full_analysis()           │   │
│  │  单轮对话回复      │  │  四阶段分析管线             │   │
│  │                   │  │  Phase 0: 数据获取          │   │
│  │                   │  │  Phase 1: 三顾问并行推理     │   │
│  │                   │  │  Phase 2: 决策综合报告       │   │
│  │                   │  │  Phase 3: 证据层展示         │   │
│  └──────────────────┘  └────────────┬───────────────┘   │
└─────────────────────────────────────┼───────────────────┘
                                      │
              ┌───────────────────────┼───────────────────┐
              │                       │                   │
              ▼                       ▼                   ▼
┌─────────────────────┐ ┌──────────────────┐ ┌──────────────────┐
│   Data Fetcher       │ │   Tool Router     │ │   Policy Library  │
│   (数据获取层)        │ │   (工具路由层)     │ │   (策略库)         │
│                      │ │                   │ │                   │
│  ┌─────────────────┐ │ │ ┌───────────────┐ │ │ ┌───────────────┐ │
│  │ Bing 实时搜索    │ │ │ │ retrieve_policy│ │ │ TFT: 12条       │ │
│  ├─────────────────┤ │ │ ├───────────────┤ │ │ ├───────────────┤ │
│  │ 本地知识库       │ │ │ │ simulate_action│ │ │ Football: 12条  │ │
│  ├─────────────────┤ │ │ ├───────────────┤ │ │ ├───────────────┤ │
│  │ 关键词匹配引擎    │ │ │ │ query_memory   │ │ │ Finance: 28条   │ │
│  └─────────────────┘ │ │ └───────────────┘ │ │ └───────────────┘ │
└─────────────────────┘ └──────────────────┘ └──────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────┐
│                  模型推理层 (LLM)                         │
│  Qwen2.5-7B-Instruct (Qwen2.5-7B)                       │
│  ┌─────────────────────────────────────────────────┐    │
│  │  三顾问推理：每个顾问独立调用 LLM                  │    │
│  │  Agent 1: 稳健顾问 (Conservative)               │    │
│  │  Agent 2: 机会顾问 (Aggressive)                  │    │
│  │  Agent 3: 探索顾问 (Explorer)                    │    │
│  │  综合报告: 第四次调用 LLM 生成结构化 JSON          │    │
│  └─────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────┐
│                硬件层 (AMD Radeon)                       │
│  AMD GPU (ROCm 7.2) — vLLM 推理引擎                      │
│  Qwen2.5-7B @ int8: 87.5 tokens/s                      │
│  显存占用: ~8GB / 48GB                                  │
└─────────────────────────────────────────────────────────┘
```

### 核心数据流

```
用户输入
  │
  ▼
[数据获取] ──→ Bing搜索 ──→ 知识库匹配 ──→ 上下文注入
  │
  ▼
[三顾问并行推理]
  ├── 稳健顾问: 安全边际优先
  ├── 机会顾问: 增长机会优先  
  └── 探索顾问: 信息收集+灵活判断
  │
  ▼
[决策综合] ──→ JSON结构化报告
  ├── consensus: 共识判断
  ├── recommendations: 推荐方向
  ├── risks: 风险提示
  └── final_verdict: 最终结论
  │
  ▼
[证据层] ──→ 展示数据来源（网络/知识库/模型）
  │
  ▼
[前端渲染] ──→ AMD状态条 → 三卡片 → 决策报告 → 证据层
```

---

## 三、核心能力

### 3.1 多智能体协作决策
三个独立人格的 AI 顾问从不同风险偏好角度分析同一问题，生成分歧明确、论据充分的综合报告。避免单一模型的偏见。

### 3.2 实时数据获取
- **核心模型推理**：完全运行于 AMD Radeon GPU，不调用远程模型 API
- **网络搜索（可选）：** 通过 Bing 搜索获取最新公开资讯，注入顾问推理上下文；网络不可用时自动回退本地知识库与模型分析
- **本地知识库：** 预置结构化金融知识（企业档案、行业分析、周期分析）
- **智能路由：** 已知人物/公司走知识库，通用话题走网络搜索

### 3.3 结构化决策报告
- 共识判断 → 推荐方向（含理由） → 风险提示 → 最终结论
- 证据层可折叠展开，展示完整推理链路

### 3.4 工具路由 (Tool Router)
- `retrieve_policy(domain)`: 按领域检索预置策略（金融/足球/TFT）
- `simulate_action(action, context)`: 模拟执行并预估结果
- `query_memory(query)`: 检索历史对话记忆

### 3.5 快速场景预设
预置 4 个金融分析场景（海力士/AI芯片/白毛股神/半导体周期），一键触发完整分析管线。

### 3.6 本地审计日志
每次分析自动记录操作日志至 `audit_log.jsonl`，包含：
- 时间戳与会话 ID
- 用户输入摘要
- 调用的工具列表
- 每次推理延迟（ms）
- 数据来源标记
- 使用的模型版本

日志本地存储，不离开用户环境，可在证据层中查看审计追踪。支持逐会话隔离，不共享跨用户数据。

---

## 四、模型介绍与本地部署方案

### 4.1 模型选择

| 模型 | 参数量 | 用途 | 推理速度 (AMD 48GB) | 显存占用 |
|------|--------|------|-------------------|---------|
| **Qwen2.5-7B-Instruct** | 7B | 主推理模型（三顾问+综合报告） | 87.5 t/s | ~8 GB |

**选型理由：**
- 7B 参数在开源模型中性价比最高，在消费级 GPU 上可流畅运行
- Qwen2.5 系列中文能力优秀，适合金融/科技领域问答
- MIT 许可证，商用友好
- 经测试可稳定输出结构化 JSON

### 4.2 本地部署方案

#### 方案一：vLLM（推荐）

```bash
# 1. 安装 ROCm 兼容的 vLLM
pip install vllm

# 2. 下载模型（通过 ModelScope 镜像加速）
pip install modelscope
python3 -c "from modelscope import snapshot_download; snapshot_download('qwen/Qwen2.5-7B-Instruct')"

# 3. 启动 vLLM 推理服务
vllm serve /path/to/Qwen2.5-7B-Instruct \
  --host 0.0.0.0 \
  --port 8001 \
  --dtype half \
  --gpu-memory-utilization 0.85 \
  --trust-remote-code \
  --enforce-eager

# 4. 测试
curl http://localhost:8001/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"Qwen2.5-7B-Instruct","messages":[{"role":"user","content":"你好"}],"max_tokens":50}'
```

#### 方案二：Ollama（更简单）

```bash
# 1. 安装 Ollama
curl -fsSL https://ollama.com/install.sh | sh

# 2. 拉取模型
ollama pull qwen2.5:7b

# 3. 运行
ollama serve

# 4. 启动 ForgeArena（自动使用 Ollama 接口）
python3 forgearena_chat.py
```

#### 方案三：HuggingFace Transformers（纯 Python）

```python
from transformers import AutoModelForCausalLM, AutoTokenizer
import torch

model = AutoModelForCausalLM.from_pretrained(
    "Qwen/Qwen2.5-7B-Instruct",
    torch_dtype=torch.float16,
    device_map="auto"
)
tokenizer = AutoTokenizer.from_pretrained("Qwen/Qwen2.5-7B-Instruct")
```

### 4.3 系统依赖

| 组件 | 版本要求 | 说明 |
|------|---------|------|
| Python | ≥ 3.10 | — |
| PyTorch | ≥ 2.2 | ROCm 版需从 AMD 官网安装 |
| vLLM | ≥ 0.4.0 | 推荐 0.6.0+ |
| Gradio | ≥ 5.0 | UI 框架 |
| ROCm | ≥ 7.2 | AMD GPU 驱动栈 |
| GPU | ≥ 16GB VRAM | 本机 48GB RDNA3 (gfx1100) |

---

## 五、AMD Radeon GPU 推理速度优化说明

### 5.1 硬件环境

| 配置 | 规格 |
|------|------|
| GPU | AMD Radeon RDNA3 (gfx1100) |
| 显存 | 48 GB VRAM |
| ROCm | v7.2 |
| PyTorch | ROCm 6.2 兼容版 |
| vLLM | 自编译 ROCm 版 |

### 5.2 实测推理速度

| 配置 | 延迟 | 吞吐量 |
|------|------|--------|
| 单次推理（短输出 150 tokens） | 2.2s | ~95 chars/s |
| 单次推理（长输出 300 tokens） | 5.7s | ~99 chars/s |
| 完整管线（4 次 LLM 调用） | 9.3s | — |
| 三顾问并行管线（理论优化） | ~5s | — |

> 测试条件：Qwen2.5-7B-Instruct @ fp16, vLLM on AMD Radeon RDNA3 (gfx1100), 48GB VRAM

### 5.3 关键优化策略

#### 5.3.1 vLLM 配置优化

```bash
# 推荐参数
--dtype half              # 半精度推理，显存减半
--gpu-memory-utilization 0.85  # 预留显存给 KV cache
--enforce-eager           # 禁用 CUDA graph，降低显存
--max-model-len 8192      # 减少 KV cache 占用的显存
```

#### 5.3.2 ROCm 环境优化

```bash
# 设置 ROCm 性能相关环境变量
export ROCM_HOME=/opt/rocm
export PYTORCH_ROCM_ARCH=gfx1100

# 使用 ROCProfiler 分析瓶颈
rocprof --stats python3 forgearena_chat.py
```

#### 5.3.3 推理管线级优化

```
┌──────────────┐
│  4 次 LLM 调用  │
│  3 顾问 + 1 综合  │ ← 可并行化（当前串行）
│               │
│  优化方案：     │
│  ┌─────────┐  │
│  │ 三顾问并行  │  │ ← 使用 asyncio + 3个并发请求
│  │ 延迟从 3x → 1x │
│  └─────────┘  │
└──────────────┘
```

**实际收益：** 当前串行管线延迟约 9.3s（数据获取 + 4 次 LLM 调用）。
若改为三顾问并行推理，延迟可降至约 5s。

#### 5.3.4 批处理优化（未来方向）

当前架构每次用户请求触发 4 次独立 LLM 推理。优化方向：

```python
# 批量推理（未来优化方向）
def batch_call(prompts, max_tokens=200):
    """将多个 prompt 合并为一个 batch 请求"""
    data = json.dumps({
        "model": MODEL,
        "messages": [[{"role": "user", "content": p}] for p in prompts],
        "max_tokens": max_tokens
    })
    # vLLM 支持 batch 推理
    return call_llm_batch(data)
```

估算收益：batch size=4 时，吞吐量可提升 2-3 倍。

### 5.4 显存优化

| 优化项 | 节省显存 | 影响 |
|--------|---------|------|
| fp16 半精度推理 | ~50% | 精度无显著损失 |
| int8 量化 (AWQ/GPTQ) | ~60% | 精度损失 < 1% |
| `--enforce-eager` | ~2GB | 略微降低吞吐 |
| KV cache 限制 8192 | ~3GB | 长上下文受限 |
| `--gpu-memory-utilization 0.85` | ~15% 预留 | 防止 OOM |

### 5.5 ROCm 常见问题排查

| 问题 | 解决方案 |
|------|---------|
| `hipErrorNoBinaryForGpu` | 设置 `HSA_OVERRIDE_GFX_VERSION` 环境变量 |
| vLLM 编译失败 | 使用 Pre-built wheel: `pip install vllm-rocm` |
| 显存不足 (OOM) | 降低 `gpu-memory-utilization` 至 0.7 |
| 推理速度慢 | 检查是否使用 CPU fallback: `rocm-smi --showpids` |

---

## 六、快速启动

```bash
# 1. 克隆仓库
git clone https://github.com/yyf121381/forgearena.git
cd forgearena

# 2. 安装依赖
pip install -r requirements.txt

# 3. 启动 vLLM 推理服务
bash start_vllm.sh

# 4. 启动 ForgeArena
python3 forgearena_chat.py

# 5. 打开浏览器
# http://localhost:24571
```

---

## 七、项目结构

```
forgearena/
├── forgearena_chat.py       # GPT 架构版 UI (主文件)
├── data_fetcher.py          # 数据获取层
├── forgearena.py            # 核心引擎
├── tools.py                 # 工具路由 (RAG/simulate/memory)
├── perception.py            # 感知模块
├── finance_policy.jsonl     # 金融策略库 (28条)
├── tft_policy.jsonl         # TFT 策略库 (12条)
├── football_policy.jsonl    # 足球策略库 (12条)
├── data/
│   └── knowledge_base.jsonl # 本地知识库 (26条)
├── requirements.txt
├── start_vllm.sh            # vLLM 启动脚本
├── FORGEARENA_REPORT.md     # 项目说明
└── README.md                # 项目简介
```

---

*ForgeArena — Local Multi-Agent Decision Intelligence for AMD AI DevMaster 2026*
