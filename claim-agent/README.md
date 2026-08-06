# 智能理赔 Agent 系统

> 上传一张发票，自动完成 **多模态识别 → 真伪查验 → 医保药品目录检索 → 理赔金额计算**，并支持多轮对话追问。
> 大模型推理运行在 **AMD Radeon GPU + ROCm** 上，全流程可本地化部署、数据不出域。
>
> AMD Radeon GPU 黑客松 · 赛道二作品。

---

## ✨ 功能特性

- 🖼️ **多模态发票识别**：视觉大模型直接看图提取发票字段 + 药品明细，无需 OCR 模板。
- 🛡️ **官方真伪查验**：对接官方接口，销方/购方/金额逐项比对。
- 📚 **RAG 药品目录检索**：本地向量库 + 三级检索（精确 / 语义 / 阈值判目录外）。
- 🧮 **确定性理赔决策**：甲/乙类/商保创新药三层规则，纯代码计算金额，可复核。
- 💬 **对话式交互 + 多轮记忆**：Gradio Chat，流式进度 + 结论卡片，支持追问。
- ⚡ **AMD ROCm 推理 + 定向优化**：GGUF 量化、全层 offload、图片压缩、`/no_think`、流式、缓存预热，附带压测脚本。

---

## 📦 环境要求

| 项目 | 版本 / 说明 |
|------|-------------|
| 操作系统 | Windows / Linux（客户端） |
| Python | 3.12（推荐 conda 环境） |
| 推理后端 | AMD Radeon GPU（gfx1100）+ ROCm 7.2.4 + llama.cpp `llama-server`（另机或本机） |
| 多模态模型 | Qwen3 多模态 VLM，`Qwen3.6-27B-Q8_0.gguf`（含 vision projector） |
| 网络 | 可访问官方发票查验接口（真伪查验功能）；首次需下载 embedding 模型（走 hf-mirror 镜像） |

> Agent / RAG / 前端跑在客户端 CPU；大模型推理跑在 AMD Radeon GPU。二者通过 **OpenAI 兼容 HTTP 端点**解耦。

---

## 🚀 快速开始（启动指南）

### 步骤 0 · 准备推理后端（AMD Radeon + ROCm）

在装有 AMD Radeon GPU 的机器上，用 llama.cpp 启动 OpenAI 兼容服务：

```bash
./llama-server \
  -m /root/Downloads/Qwen3.6-27B-Q8_0.gguf \
  --mmproj <vision-projector.gguf> \
  -ngl 999 \
  --host 0.0.0.0 --port 8080 \
  --ctx-size 8192
```

### 步骤 1 · 建立到后端的通道

若后端在远程机器，用 SSH 隧道把本地 `8000` 映射到后端 `8080`：

```bash
ssh -N -L 8000:localhost:8080 -p <ssh-port> <user>@<backend-host>
```

> 若后端就在本机 `8080`，可跳过隧道，直接在 `config.py` / 环境变量把 `MODEL_PORT` 设为 `8080`。

验证端点可用（应返回 HTTP 200）：
```bash
curl http://localhost:8000/v1/models
```

### 步骤 2 · 创建环境并安装依赖

```bash
# 建议使用 conda
conda create -n claim-agent python=3.12 -y
conda activate claim-agent

# 用国内镜像加速安装
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### 步骤 3 · 构建药品目录向量库（首次运行一次）

```bash
python -m rag.build_index
```
> 首次会从 HuggingFace 镜像（hf-mirror）下载 `bge-small-zh-v1.5`，构建 24 条药品目录向量到 `data/chroma/`。

### 步骤 4 · 启动应用

```bash
python app.py
```
启动后浏览器打开 **http://localhost:7860**。上传发票图片点击发送即可看到逐阶段进度与理赔结论卡片；随后可直接输入问题追问。

---

## ⚙️ 关键配置（`config.py` / 环境变量）

所有配置集中在 `config.py`，均可用环境变量覆盖：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `MODEL_HOST` / `MODEL_PORT` | `localhost` / `8000` | 推理端点地址（经隧道指向 AMD 后端 8080） |
| `MODEL_BASE_URL` | `http://localhost:8000/v1` | OpenAI 兼容端点 |
| `MODEL_ID` | `/root/Downloads/Qwen3.6-27B-Q8_0.gguf` | 模型标识 |
| `LLM_TEMPERATURE` | `0.1` | 采样温度（低温更稳定） |
| `LLM_TIMEOUT` | `180` | 单次推理超时（秒） |
| `EMBEDDING_MODEL` | `BAAI/bge-small-zh-v1.5` | 本地 embedding 模型 |
| `EMBEDDING_DEVICE` | `cpu` | embedding 设备（`cpu` / `cuda`，ROCm 亦标识为 `cuda`） |
| `HF_ENDPOINT` | `https://hf-mirror.com` | HuggingFace 镜像端点 |
| `RAG_SCORE_THRESHOLD` | `0.6` | 语义检索阈值，低于且非商保创新药 → 目录外 |
| `VERIFY_URL` | `https://inv-veri.com/check` | 官方发票查验接口 |
| `DEFAULT_REIMBURSE_RATIO` | `0.7` | 默认统筹报销比例（目录条目可覆盖） |
| `APP_PORT` | `7860` | 前端端口 |

Windows PowerShell 下运行 Python 建议先设编码，避免中文乱码：
```powershell
$env:PYTHONIOENCODING="utf-8"; $env:PYTHONUTF8="1"
```

---

## 🧪 测试与压测

```bash
# 单元 / 集成测试（分里程碑）
python test_core.py     # M1 后端连通 + 基础 OCR/查验
python test_rag.py      # M2 RAG 三级检索回归
python test_tools.py    # M3 四个业务工具单测
python test_agent.py    # M4 Agent 工具调用 + 多轮记忆 + 确定性流水线

# 推理性能压测（AMD ROCm 后端）
python bench.py --n 5 --concurrency 8 --vision fapiao2.jpg
```

---

## 📁 项目结构

```
fake_ocr_test/
├── app.py                 # Gradio Chat 前端（对话式 + 流式 + 结论卡片）
├── config.py              # 集中配置（端点/模型/RAG/理赔规则参数）
├── bench.py               # AMD ROCm 推理性能压测脚本
├── requirements.txt       # 依赖列表
│
├── tools/                 # 业务工具层（LangChain @tool）
│   ├── ocr_tool.py        # 多模态发票提取
│   ├── verify_tool.py     # 官方真伪查验
│   ├── rag_tool.py        # 药品目录检索封装
│   └── decision_tool.py   # 理赔规则确定性计算
│
├── rag/                   # 检索增强
│   ├── retriever.py       # 三级检索器（精确/语义/阈值）
│   └── build_index.py     # 离线构建 Chroma 向量库
│
├── agent/                 # Agent 编排
│   ├── agent.py           # LLM tool-calling Agent + 记忆追问
│   ├── pipeline.py        # 确定性理赔流水线（主审核，含流式）
│   └── memory.py          # 会话记忆 SessionStore
│
├── underwriting/          # 核保风险 Agent（独立项目，复用根 config 的 LLM 端点）
│   ├── config.py          # 核保专属配置（风险等级/核保建议枚举/风险色块）
│   ├── memory.py          # 会话记忆（单份/批量报告三级回退）
│   ├── pipeline.py        # 单份核保流水线（extract→abnormality→risk→search→报告，流式）
│   ├── batch_pipeline.py  # 批量核保（并发 + 去重 + 失败隔离 + JSON 持久化 + CSV 导出）
│   ├── agent.py           # 核保 Agent + stream_followup（流式追问，思考链/正文分区）
│   ├── backend.py         # FastAPI 后端（端口 8002，SSE 流式）
│   ├── tools/             # 4 个业务工具
│   │   ├── report_extract_tool.py  # 多模态病历/体检报告提取
│   │   ├── abnormality_tool.py     # 异常点识别
│   │   ├── risk_tool.py            # 疾病风险预估
│   │   └── medical_search_tool.py  # 医学研究联网检索（Exa + anysearch 双端并用）
│   └── static/            # 原生前端（HTML + Tailwind，单份/批量两 Tab）
│
├── tools/search/          # 联网检索 vendor（核保 Agent 双端并用）
│   ├── web_search.py      # Exa 神经语义搜索后端
│   └── anysearch_cli.py   # anysearch health/academic 垂直域 + 批量 + 全文抽取
│
├── data/
│   ├── drug_catalog.json  # 医保药品目录（24 条样例）
│   ├── chroma/            # 向量库持久化目录（build_index 生成）
│   └── underwriting_results/  # 核保批量结果 JSON 持久化目录
│
├── test_core.py / test_rag.py / test_tools.py / test_agent.py   # 理赔测试
├── test_underwriting.py / test_underwriting_agent.py / test_underwriting_backend.py  # 核保测试
├── fapiao.jpg / fapiao2.jpg   # 样例发票
├── 项目说明文档.md          # 项目说明（场景/架构/能力/部署/AMD优化）
├── 设计文档.md              # 详细设计文档
└── invoice_verify_api.md    # 官方查验接口说明
```

---

## 📚 依赖列表

见 [`requirements.txt`](./requirements.txt)。实测环境版本（Python 3.12）：

| 包 | 版本 | 用途 |
|----|------|------|
| gradio | 5.44.1 | 前端 Chat 界面 |
| langchain | 1.3.14 | Agent 编排框架 |
| langchain-core | 1.4.9 | 核心抽象（@tool 等） |
| langgraph | 1.2.9 | Agent 运行时 + 记忆 checkpointer |
| langchain-openai | 1.3.5 | 接入 OpenAI 兼容端点 |
| langchain-community | 0.4.2 | 社区集成 |
| chromadb | 1.5.9 | 向量库 |
| sentence-transformers | 5.1.2 | 本地 embedding |
| numpy | 1.26.4 | 数值计算 |
| requests | 2.32.5 | HTTP 调用 |
| pydantic | 2.10.6 | 数据校验 |
| Pillow | 10.4.0 | 图片压缩预处理 |

> 说明：本项目 LangChain 采用 **1.x 新版**（`langchain.agents.create_agent`，基于 langgraph），非 0.2.x 旧版 `AgentExecutor`。

---

## ❓ 常见问题

- **上传非医疗发票（如生活用品）会怎样？** 系统检索发现所有项均不在报销目录（相似度低于阈值），会明确判定为「疑似非医疗发票，不属于理赔范围」，不会误算金额。
- **端点连不上 / 首 token 很慢？** 先 `curl http://localhost:8000/v1/models` 确认隧道与后端正常；确保 `-ngl 999` 已将模型全部 offload 到 GPU。
- **首次上传较慢？** 首次会加载 embedding 模型；`app.py` 已在启动时后台预热，正常情况下打开界面稍等即可。
- **分享链接创建失败（frpc）？** 不影响本地使用，通过 `http://localhost:7860` 访问即可；如需公网分享，按 Gradio 提示手动放置 frpc 文件。

---

## 🏥 核保风险 Agent

> 在理赔系统之上扩展的**独立核保风险 Agent**：对图片格式的**病历 / 体检报告**做
> **多模态提取 → 异常点识别 → 疾病风险预估 → 医学研究联网检索（Exa + anysearch 双端并用）→ 核保报告**，
> 帮助核保人员自动化判断并留痕。复用理赔系统的 LLM 端点（Qwen3.6-27B vision）与 SSE 流式基础设施，
> 独立端口 `8002`，不改动任何理赔代码。

### 流水线与核保建议

固定顺序的确定性流水线（每阶段 SSE 流式推送进度）：

1. **报告多模态提取**（`report_extract_tool`）：图片 base64 + 医学提示词 → 结构化 JSON（report_type/patient/items/diagnoses/summary）。
2. **异常点识别**（`abnormality_tool`）：检验值越界 + 异常诊断 + 危险症状 → abnormalities 列表（含 severity_hint 轻/中/重）。
3. **疾病风险预估**（`risk_tool`）：结合严重度/检验偏离/合并症 → risks 列表 + overall_risk（低/中/高）。
4. **医学研究联网检索**（`medical_search_tool`）：**双端并用**检索最新医学研究（见下节）。
5. **核保报告生成**：汇总为结构化报告 + 报告卡（风险色块 + 异常/风险明细表 + 医学引用列表）。

核保建议枚举（由 overall_risk 映射，风险等级以工具返回为准）：

| 整体风险 | 核保建议 | 色块 |
|----------|----------|------|
| 低 | 标准体 | 绿 |
| 中 | 次标准体-加费 | 黄 |
| 高 | 拒保 | 红 |

完整枚举：`标准体` / `次标准体-加费` / `次标准体-除外` / `延期` / `拒保`。

### 双搜索后端（核心：医学研究检索准确性）

核保建议的可信度直接取决于检索到的医学依据是否准确、是否最新。采用**双端并用策略**：
对每个疾病查询**同时**调用 Exa 与 anysearch（并发线程池，受 `SEARCH_MAX_WORKERS` 约束），
合并结果并按 url 去重，任一端失败用另一端结果兜底。

| 后端 | 端点 | 特点 |
|------|------|------|
| **Exa** | `https://mcp.exa.ai/mcp`（`web_search_exa`） | 神经语义搜索，对医学查询召回准确率高、免费、实测稳定 |
| **anysearch** | `anysearch_cli.py`（subprocess） | `health` 垂直域查疾病医学信息 + `academic` 查研究文献 + `batch_search` 并行 + `extract` 全文抽取；匿名免费，`ANYSEARCH_API_KEY` 可选提额 |

容错：任一端失败 → 用另一端结果兜底（失败端标注 warning）；两端皆失败 → 该疾病 references 为空 + error，不中断流水线；
单疾病失败不影响其他疾病；报告整体无引用时标注「联网检索暂不可用，医学依据仅供参考」。

### 启动（两个服务）

核保 Agent 依赖**两个独立服务**，需分别启动。二者解耦：大模型服务跑在 AMD GPU 机器上，核保后端跑在本地 CPU 机器上，通过 OpenAI 兼容 HTTP 端点通信。

#### 服务 1 · 大模型推理服务（AMD Radeon GPU + ROCm + llama.cpp）

在装有 AMD Radeon GPU 的远程机器上，用 llama.cpp 启动 OpenAI 兼容的多模态推理服务（监听 `0.0.0.0:8080`）：

```bash
./llama-server \
  -m /workspace/models/Qwen3.6-27B-UD-Q8_K_XL.gguf \
  --mmproj <vision-projector.gguf> \
  -ngl 999 \
  --host 0.0.0.0 --port 8080 \
  --ctx-size 262144
```

> 服务端 `--ctx-size` 已开到 256k；客户端 `config.py` 的 `LLM_MAX_TOKENS=8192`（单次生成上限）远小于 ctx-size，不会溢出。

本地机器通过 SSH 隧道把本地 `8000` 映射到远程 `8080`：

```bash
ssh -N -L 8000:localhost:8080 -p 31059 root@36.150.116.206
```

验证端点可用（应返回模型 JSON）：

```bash
curl http://localhost:8000/v1/models
```

> 备选：也可用 Cloudflare Tunnel 暴露为公网 HTTPS 端点，设环境变量
> `MODEL_BASE_URL=https://<tunnel>.trycloudflare.com/v1` 覆盖（临时 URL 重启会变）。

#### 服务 2 · 核保 Agent 后端（本地 CPU，端口 8002）

在本地机器，用 `deepseekocr` conda 环境启动 FastAPI 后端：

```powershell
# Windows PowerShell 需先设编码，避免中文乱码
$env:PYTHONIOENCODING="utf-8"; $env:PYTHONUTF8="1"
& "C:\Users\OKONE\anaconda3\envs\deepseekocr\python.exe" -m underwriting.backend
```

启动后浏览器打开 **http://localhost:8002**：
- **单份 Tab**：上传一张病历/体检报告**图片或 PDF** → 阶段进度 + 思考链折叠区 + 报告卡（风险色块 + 异常/风险明细表 + 医学引用列表）。
- **批量 Tab**：上传多个**图片/PDF** → 逐张进度 + 汇总卡（成功/重复/失败计数 + 风险/建议分布）+ CSV 下载按钮。
- **追问**：基于已生成报告多轮追问，思考链（reasoning）与正文（content）分区实时追加。

端点：`GET /api/health`、`POST /api/underwriting/process`（单份 SSE）、`POST /api/underwriting/batch`（批量 SSE）、
`POST /api/underwriting/followup`（追问 SSE）、`GET /api/underwriting/session/{id}/csv`（UTF-8 BOM CSV 导出）。

#### 启动顺序

1. **先启动服务 1**（大模型服务 + SSH 隧道），确认 `curl http://localhost:8000/v1/models` 返回正常；
2. **再启动服务 2**（核保后端），打开 http://localhost:8002 即可使用。

> 服务 1 未就绪时，服务 2 仍可启动，但提取/异常/风险三阶段会降级（医学检索仍可独立工作）。

#### PDF 处理依赖

PDF 核保需安装 PyMuPDF（`underwriting/tools/pdf_loader.py` 用其提取文本 / 转图片）：

```powershell
& "C:\Users\OKONE\anaconda3\envs\deepseekocr\python.exe" -m pip install PyMuPDF -i https://pypi.tuna.tsinghua.edu.cn/simple
```

未安装时上传 PDF 会返回「PDF 无法提取文本且转图片失败」，图片上传不受影响。

### 配置（环境变量覆盖）

根 `config.py`「八、核保 Agent」配置段，均支持环境变量覆盖（沿用 `_env` 模式）：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `UNDERWRITING_PORT` | `8002` | 核保后端端口（避开理赔 `7860`/VLM `8000`） |
| `EXA_MCP_URL` | `https://mcp.exa.ai/mcp` | Exa MCP 端点 |
| `EXA_NUM_RESULTS` | `5` | Exa 每次返回结果数 |
| `EXA_TIMEOUT` | `30` | Exa 超时（秒） |
| `ANYSEARCH_API_KEY` | （空） | anysearch 可选 API Key，空则匿名调用 |
| `ANYSEARCH_CLI_PATH` | `tools/search/anysearch_cli.py` | anysearch CLI 脚本路径 |
| `SEARCH_MAX_WORKERS` | `4` | 双端并发线程池上限（Exa + anysearch 同时调用） |
| `UNDERWRITING_BATCH_MAX_WORKERS` | `1` | 批量核保并发上限 |
| `UNDERWRITING_PERSIST_DIR` | `data/underwriting_results/` | 批量结果 JSON 持久化目录 |
| `UNDERWRITING_PERSIST_ENABLED` | `true` | 是否持久化批量结果 |

### Python 环境

推荐使用 `C:\Users\OKONE\anaconda3\envs\deepseekocr\python.exe`（Python 3.12，含 `requests` / `langchain_core` / `fastapi` / `uvicorn` / `Pillow`）。
Windows PowerShell 下运行需先设编码，避免中文乱码：

```powershell
$env:PYTHONIOENCODING="utf-8"; $env:PYTHONUTF8="1"
```

### LLM 端点说明

核保 Agent **复用理赔系统的 LLM 端点**（`MODEL_BASE_URL`，默认 `http://localhost:8000/v1`）：
LLM 端点需通过 SSH 隧道指向 **AMD Radeon GPU + ROCm** 上的 **Qwen3.6-27B** 多模态模型
（含 vision projector）。隧道未运行时，提取/异常/风险三阶段会降级，但医学检索（Exa + anysearch）
仍可独立工作；追问会返回 error 事件提示「LLM 流式调用异常」。

### 测试

```powershell
$env:PYTHONIOENCODING="utf-8"; $env:PYTHONUTF8="1"
# 综合集成测试（单份/批量/搜索/流式/配置，含真实联网搜索用例）
& "C:\Users\OKONE\anaconda3\envs\deepseekocr\python.exe" -m unittest test_underwriting -v
# Agent 流式追问单元测试（28 用例）
& "C:\Users\OKONE\anaconda3\envs\deepseekocr\python.exe" -m unittest test_underwriting_agent -v
# FastAPI 后端单元测试（10 用例）
& "C:\Users\OKONE\anaconda3\envs\deepseekocr\python.exe" -m unittest test_underwriting_backend -v
```

> 真实联网搜索用例（`search_medical(["高血压"])`）默认执行；若双端皆不可达则自动 skip，不阻塞测试通过。
> 浏览器端到端验证需 LLM 端点可用（SSH 隧道运行），手动验证步骤见 `test_underwriting.py` 文件顶部注释。

---

## 🔐 安全结构说明（登录鉴权 + 日志脱敏）

> **比赛最小验证**：用「单账号 JWT 登录 + 结构化日志脱敏」撑起「权限控制 + 隐私保护」闭环，
> 不做用户管理系统 / RBAC / OAuth。同一套 `auth` + `log_sanitizer` 模块**同时保护两个 FastAPI 后端**：
> 理赔后端 `backend/main.py`（端口 8001）与核保后端 `underwriting/backend.py`（端口 8002）。
> 已通过端到端鉴权冒烟（TestClient 离线验证 login / 401 / token 链路全绿）。

### 默认登录账号

| 用户名 | 密码 | 备注 |
|--------|------|------|
| `admin` | `claim123` | demo 单账号，跨两个后端通用；可用环境变量覆盖（见下表） |

> 前端登录页右下角已标注 `Demo: admin / claim123` 提示。

### 改动文件清单（供协同 AI 快速定位改动范围）

| 文件 | 类型 | 改动内容 |
|------|------|----------|
| `auth.py` | 🆕 新增 | JWT 签发/校验（HS256，12h）、密码哈希（sha256+salt）、`authenticate()` |
| `log_sanitizer.py` | 🆕 新增 | 日志脱敏 `logging.Filter` + `install_sanitizer()`（幂等挂载） |
| `config.py` | ✏️ 修改 | 追加「九、鉴权与日志脱敏」配置段（`AUTH_*` 共 6 项，第 148–159 行） |
| `backend/main.py` | ✏️ 修改 | 顶部装脱敏 + `logger` + `from auth import`；新增 `LoginReq` + `POST /api/login`；业务路由全部加 `Depends(verify_token)`；增加 `[access]` 访问日志 |
| `underwriting/backend.py` | ✏️ 修改 | 同上（与理赔后端对称）；**曾遗漏 `from auth import`，已补齐** |
| `backend/static/index.html` | ✏️ 修改 | `<body>` 开头插入登录遮罩层（用户名/密码/登录按钮） |
| `backend/static/app.js` | ✏️ 修改 | `getToken/setToken/clearToken` + `apiFetch`（自动带 Authorization，401 弹遮罩）+ `doLogin`；业务 fetch 改 `apiFetch` |
| `underwriting/static/index.html` | ✏️ 修改 | 登录遮罩层（同理赔前端） |
| `underwriting/static/app.js` | ✏️ 修改 | token 工具 + `apiFetch` + `doLogin`（`TOKEN_KEY='underwriting_auth_token'`） |
| `requirements.txt` | ✏️ 修改 | 追加 `pyjwt>=2.8` |

### 鉴权流程（JWT Bearer Token）

```
登录：  POST /api/login {username, password}
         → authenticate() 校验（sha256(salt+password) 比对）
         → 签发 JWT {sub, iat, exp}（HS256，默认 12h）
         → 返回 {token, expires_in, username}

业务请求：前端 apiFetch() 自动附带 Header: Authorization: Bearer <token>
         → 后端 verify_token 依赖解码校验
         → 过期/无效/缺失 → 401 Unauthorized

前端 401：clearToken() + showLoginOverlay() 重新弹登录框
```

**路由保护策略**：

| 路由 | 鉴权 | 说明 |
|------|------|------|
| `GET /api/health` | ❌ 放行 | 健康检查，前端探活用 |
| `POST /api/login` | ❌ 放行 | 登录入口，不能自我保护 |
| `POST /api/invoice/process`、`/api/batch/process`、`/api/followup` | ✅ 保护 | 理赔业务 |
| `GET /api/session/{id}/csv` | ✅ 保护 | 理赔 CSV 导出 |
| `POST /api/underwriting/{process,batch,followup}` | ✅ 保护 | 核保业务 |
| `GET /api/underwriting/session/{id}/csv` | ✅ 保护 | 核保 CSV 导出 |

### 日志脱敏机制（`log_sanitizer.SanitizingFilter`）

**实现要点**：自定义 `logging.Filter` 挂在 **root logger 的所有 handler** 上（非 logger 本身）。
> 关键：Python logging 中子 logger 发出的 record 只检查自身 filters，**不检查祖先 logger 的 filters**；
> 但 record 传到 root handler 时 handler 的 filter 会被检查。故必须挂 handler 才能覆盖所有子 logger。

**脱敏项与执行顺序**（顺序固定，不可调换）：

| 顺序 | 类型 | 正则 | 脱敏规则 | 示例（前 → 后） |
|------|------|------|----------|------------------|
| 1 | 身份证（18位） | `(?<!\d)\d{17}[\dXx](?!\d)` | 前3 + 11个`*` + 后4（位数与原号一致） | `110101199001011234` → `110***********1234` |
| 2 | 手机号（11位） | `(?<!\d)1[3-9]\d{9}(?!\d)` | 前3 + 4个`*` + 后4 | `13812345678` → `138****5678` |
| 3 | 发票号 | 字段名锚定 `fphm/fpdm/invoice_no/发票号` + 数字 | 保留字段名 + 前4 + 4个`*` + 后4 | `fphm=1234567890123456` → `fphm=1234****3456` |
| 4 | 姓名 | 字段名锚定 `patient_name/姓名` + 2-4字汉字 | 保留字段名 + 首字 + `*` | `patient_name=张三` → `patient_name=张*` |

> - 必须先脱身份证再脱手机：否则身份证号会被手机号正则从中截 11 位误匹配。
> - 用负向断言 `(?<!\d)...(?!\d)` 而非 `\b`：汉字与数字都是 `\w`，`\b` 在「身份证110...手机」场景无边界。
> - 发票号/姓名无法用纯正则可靠识别（误伤率高），故依赖「字段名+值」结构化模式。
> - **SSE 流不脱敏**：用户看自己的数据，不应脱敏；只脱敏服务端 access log。

**作用范围**：仅作用于 `logging` 输出（新增的服务端 `[access]` 访问日志）；既有 `print` / SSE 不受影响。

### 配置项（`config.py` 第 148–159 行，均支持环境变量覆盖）

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `AUTH_DISABLED` | `false` | 一键禁用全部鉴权（回退开关）。设 `true` 则 `verify_token` 直接放行，便于答辩演示 |
| `AUTH_USERNAME` | `admin` | 登录用户名 |
| `AUTH_PASSWORD` | `claim123` | 登录密码（明文配置，demo 用） |
| `AUTH_PASSWORD_SALT` | `claim-agent-2026` | 密码哈希 salt（sha256(salt+password)） |
| `AUTH_SECRET_KEY` | `claim-agent-demo-secret-CHANGE-ME` | JWT 签名密钥（生产务必更换） |
| `AUTH_TOKEN_EXPIRE_HOURS` | `12` | Token 过期时间（小时） |

### 启用 / 关闭

默认已开启鉴权。临时关闭（如答辩中途不想反复登录）：

```powershell
# Windows PowerShell
$env:AUTH_DISABLED="true"
# 然后重启后端，所有业务接口放行（verify_token 直接返回 "demo"）
```

```bash
# Linux / macOS
export AUTH_DISABLED=true
```

> 关闭后 `verify_token` 直接返回 `"demo"` 用户名，前端无需登录即可访问。**仅限演示环境**。

### 取舍说明（答辩可主动阐述，体现工程认知）

- **单账号**而非用户管理系统 → 比赛最小验证够用
- **sha256+salt** 而非 bcrypt → 省一个依赖，demo 场景足够
- **Token 存 localStorage** 而非 httpOnly cookie → demo 够用，生产应换 httpOnly cookie 防 XSS
- **脱敏只覆盖结构化日志**（字段名锚定），裸敏感数字无法可靠识别 → 正则固有局限，主动说明比硬吹「全脱敏」更可信
- **`AUTH_DISABLED` 回退开关** → 答辩前若 JWT 出问题可一键放行，业务照常演示

---

## 📄 相关文档

- [`项目说明文档.md`](./项目说明文档.md) — 应用场景、架构图、核心能力、模型部署、AMD 优化说明
- [`设计文档.md`](./设计文档.md) — 完整设计文档
- [`invoice_verify_api.md`](./invoice_verify_api.md) — 官方发票查验接口说明
