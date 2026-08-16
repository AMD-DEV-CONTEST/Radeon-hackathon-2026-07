# Hello E World — 平行宇宙模拟器

> **一句话**：和 AI 聊 5 分钟天，它会比你自己更了解你——然后用你的"人格模型"推演任何选择的三种平行人生。

**Track 2** | AMD Radeon Hackathon 2026 | Team: west-liu

---

## 1. 这是什么

Hello E World 是一个**人格驱动的 What-If 引擎**。

它不是问答机器人，不是心理咨询，不是算命。它是一个**推理工具**——用对话理解你是谁，然后用你的真实人格推演不同选择带来的不同结果。

三个步骤，零门槛：
1. **聊天** — AI 问你 5-10 个问题，像朋友聊天，不是填表
2. **建模** — AI 提取你的人格画像：风险偏好、决策风格、价值观、盲区
3. **推演** — 你输入任何 what-if，AI 推演三个平行宇宙

---

## 2. 为什么这个能赢

### Track 2 评分标准 vs Hello E World

| 标准 | 说明 | Hello E World 怎么做 |
|------|------|----------------|
| **本地部署** | 全程 GPU 推理，不依赖 API | llama.cpp + Qwen2.5-14B 纯本地 W7900 推理 |
| **Agent 属性** | 记忆/规划/工具调用 | 渐进式人格建模、三路径推演规划、对话记忆链 |
| **Tool Calling** | 真实调用工具 | llama.cpp function calling + 人格提取/场景模拟 API |
| **隐私** | 数据不出本地 | 全部对话和模型存 SQLite，无网络外传 |
| **实用性** | 解决真实问题 | 帮人理解自己的决策模式，发现盲区 |

### 0 竞争对手

Track 2 共 57 个项目，分析后：
- 代码审查类：8+ 个（UR-Agent 等）
- 合同审查：5+ 个
- 简历筛选/HR：6+ 个
- 医疗/教育：7+ 个
- 地震/灾害模拟：2+ 个
- **What-If / 平行宇宙 / 人生模拟：0 个**

Hello E World 是 Track 2 里**唯一**做人格驱动模拟的项目。这就是差异化。

---

## 3. 技术架构

```
┌─────────────────────────────────────────────────┐
│  浏览器 (index.html)                              │
│  对话式 UI，一个问题一个问题来                     │
└─────────────────┬───────────────────────────────┘
                  │ HTTP/SSE
┌─────────────────▼───────────────────────────────┐
│  FastAPI Server (helloeworld/source/main.py)        │
│  - 会话管理（内存，MVP）                          │
│  - 对话路由、人格提取、场景推演                   │
└─────────────────┬───────────────────────────────┘
                  │ httpx (OpenAI-compatible)
┌─────────────────▼───────────────────────────────┐
│  llama.cpp Server (port 8000)                         │
│  Qwen/Qwen2.5-14B-Instruct                       │
│  AMD Radeon Pro W7900 · 48GB VRAM · ROCm 7.2.1   │
└─────────────────────────────────────────────────┘
```

### 模型选择：Qwen2.5-14B-Instruct

| 对比项 | Qwen2.5-14B | Qwen2.5-32B | Qwen3.6-35B-A3B |
|--------|-------------|-------------|------------------|
| VRAM | ~28GB ✅ | ~64GB ❌ | ~70GB ❌ |
| W7900 可用 | 是，留 20GB 余量 | 否，超出 48GB | 否 |
| 推理速度 | 40-60 tok/s | N/A | N/A |
| 中文能力 | 优秀 | 优秀 | 优秀 |
| 英文能力 | 良好 | 优秀 | 优秀 |

唯一能在 W7900 48GB 上跑且质量足够的模型。

---

## 4. 文件结构

```
helloeworld/
├── PRODUCT.md              ← 你正在看的这个
├── frontend/
│   └── index.html          ← 聊天 UI（单文件，零依赖）
├── source/
│   ├── __init__.py
│   ├── main.py             ← FastAPI 服务器（12 个端点）
│   ├── agent.py            ← 核心 Agent（对话/建模/推演）
│   ├── tools.py            ← 数据结构 + 16 道预设问题
│   ├── llama_client.py      ← llama.cpp OpenAI 兼容客户端
│   └── requirements.txt    ← fastapi, uvicorn, httpx, pydantic
├── deploy.sh               ← 一键部署脚本（待写）
└── README.md               ← 英文说明（待写）
```

---

## 5. API 端点

### 前端
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 聊天 UI |

### 状态
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | GPU 状态、Q&A 数量、是否已提取人格 |

### 对话（Onboarding）
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/onboard/next-question` | 获取下一个问题 |
| POST | `/onboard/answer` | 提交回答 `{"answer": "..."}` |
| GET | `/onboard/history` | 查看全部对话历史 |

### 人格
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/personality/extract` | 从对话提取人格画像 |
| GET | `/personality` | 查看当前人格 |

### 推演
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/simulate` | 运行推演 `{"scenario": "What if..."}` |
| POST | `/simulate/stream` | SSE 流式推演 |

### 工具
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/reset` | 清除会话 |
| POST | `/demo/quick-start` | 预载 6 组对话，直接跳推演 |

---

## 6. Demo 演示流程（视频用，3-5 分钟）

### 开场（30 秒）
> "I'm going to show you Hello E World — a parallel universe simulator that builds your personality model in 5 minutes, then shows you three versions of yourself for any life decision."

### Step 1: 对话（60 秒）
- 点击 Demo 按钮，预载 6 组对话
- 展示 AI 问了什么问题（"What's a decision that changed everything?"）
- 展示 AI 如何根据回答追问（自然的对话流）

### Step 2: 人格提取（30 秒）
- 点击 "Extract My Personality"
- 查看人格画像：Risk tolerance, Decision style, Values, Strengths, Blind spots
- 强调："This is extracted from conversation, not a questionnaire."

### Step 3: What-If 推演（90 秒）
- 输入: "What if I had never left my corporate job?"
- 展示 Path A (Most Likely): 可能发生了什么
- 展示 Path B (Optimal): 最优可能
- 展示 Path C (Shadow): 盲区可能
- 展示 Bias Analysis + Closing Insight

### 结尾（30 秒）
> "Hello E World runs entirely on AMD Radeon Pro W7900 with llama.cpp. No API calls, no data leaves this machine. Your personality stays yours. Thank you."

---

## 7. 部署步骤（明天早上就能用）

### 前置条件
- AMD 服务器：36.150.116.206:31285
- GPU: Radeon Pro W7900, 48GB VRAM
- OS: Ubuntu 24.04, ROCm 7.2.1

### 部署 checklist

```
[ ] SSH 到服务器
[ ] 安装 llama.cpp (pip install llama-cpp-python)
[ ] 下载 Qwen2.5-14B-Instruct
[ ] 启动 llama.cpp 服务
[ ] 部署 Hello E World 代码
[ ] pip install -r requirements.txt
[ ] 启动 FastAPI (uvicorn main:app --host 0.0.0.0 --port 8080)
[ ] 测试 GET /health
[ ] 测试 POST /demo/quick-start
[ ] 测试 POST /simulate
[ ] 浏览器访问 http://36.150.116.206:8080
```

### llama.cpp 启动命令
```bash
llama-server Qwen/Qwen2.5-14B-Instruct \
  --host 0.0.0.0 \
  --port 8000 \
  --max-model-len 8192 \
  --gpu-memory-utilization 0.90 \
  --dtype auto
```

### FastAPI 启动命令
```bash
cd /workspace/persistent/helloeworld/source
LLAMA_BASE=http://127.0.0.1:8000/v1 uvicorn main:app --host 0.0.0.0 --port 8080
```

---

## 8. 为什么叫 Hello E World

**Parallax** (视差) + **Parallel** (平行) = **Hello E World**

视差效应：从不同角度观察同一物体，看到不同的图像。
Hello E World 让你从不同平行宇宙的角度观察同一个自己。

---

## 9. 当前状态（8/5 晚间）

| 组件 | 状态 |
|------|------|
| 后端代码 (agent.py, main.py, tools.py, llama_client.py) | ✅ 完成 |
| 前端 UI (index.html) | ✅ 完成 |
| 产品文档 (PRODUCT.md) | ✅ 完成 |
| SSH 连接 | ❌ 密钥格式问题 |
| llama.cpp 安装 | ❌ 待 SSH |
| 模型下载 | ❌ 待 llama.cpp |
| 端到端测试 | ❌ 待部署 |
| README (英文) | ❌ 待写 |
| Demo 视频 | ❌ 待录 |

**下一步**：解决 SSH → 部署 llama.cpp + 模型 → 部署 Hello E World → 测试 → 录视频
