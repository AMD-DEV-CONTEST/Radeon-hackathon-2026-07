# PrivatePlate — 中文详细说明

> 根目录 [`README.md`](../README.md) 为评委可读的英文入口。本文为内部中文补充（产品能力与证据边界）；正式参赛 PR 以英文 README + `submission/` 为准。

PrivatePlate 是一个运行在本地环境中的家庭用餐协调 Agent，参赛方向为 **AMD AI DevMaster 2026 赛道二：私有 AI Agent 开发与本地部署**。

> **提交包总览：** [submission/README.md](submission/README.md)
> **分层架构图（评委口径）：** [submission/PROJECT_SPECIFICATION.md](submission/PROJECT_SPECIFICATION.md) §2 · 英文根 README 同步。

它帮助家庭用餐负责人协调：今天还有多少营养额度、谁吃饭、家里有什么、Agent 选哪些菜、Domain 校验与换算后是否可行、还缺什么，以及如何把「按计划吃完」记入家庭账本。

PrivatePlate 不是医疗助手。模型负责理解自然语言、多轮上下文和用户目标；确定性代码负责营养数字、硬约束、库存、计划版本与最终写入；任何账本写入都必须经用户确认。

## 当前产品能力（协议 v2）

- 三人合成家庭，可选本餐 1–3 位成员；
- 日目标、已摄入、**剩余额度**（日目标 − 当日 completed 摄入）；
- 三名合成成员的最小营养资料（性别、年龄、身高、体重、活动水平、体重目标）与工程估算预算；BMR/TDEE 仅作演示计算，不是医疗诊断或个体化处方；
- 午餐/晚餐默认至少覆盖“主菜或主要蛋白质 + 蔬菜/配菜 + 主食或等价碳水”三类角色；这是最低覆盖，不是固定三道菜，Agent 可按人数和意图选择 1～12 道，多道同 role 菜共享份量；简单餐/一锅餐必须显式声明；
- `mealPortionScale` 直接调整基础份量，剩余额度只做当前餐次上限；正常餐次默认保留 12% 预算余量，避免三人餐被重复缩小或吃到刚好归零；
- 计划摄入 `plannedIntake` 与备餐采购量 `preparedBatch` 分离；后者默认增加 8% 备餐余量，营养账本不把这部分算作已摄入；
- Web 新计划会列出全部菜品、真实角色、每道菜计划克数、参与人数，以及“计划吃掉的量”和含余量的“实际准备/采购量”；备餐余量只覆盖损耗、误差和临时变化，不显示成剩菜；
- 家庭记忆（健康事实 / 偏好）、只读库存与单位换算；
- Agent 在硬过滤候选中**自己选菜**；Domain **不排名、不选 winner**；
- 同 role 多道菜**分享**该 role 总份量；可扩展克数范围（如豆腐）+ 现实采购单位；
- 修订 = Agent 提交新的完整 `selectedDishes`（不是代码自动换菜）；
- 用户确认「本餐已按计划吃完」后写入摄入、扣库存并标记完成。

当前仅使用合成数据；默认不假装已发给真人保姆。

当前约 18 个合成食物和 13 个菜品模板只用于比赛演示，不是权威食物数据库或医疗处方。完整权威食物库、联网营养查询和全部健康知识卡属于比赛后的扩展项。

## 架构

正式分层架构图见 [submission/PROJECT_SPECIFICATION.md](submission/PROJECT_SPECIFICATION.md) §2（与根目录英文 `README.md` 一致）。

模型可见产品工具（九个；无 `commit_*`）：

1. `get_day_context` — 日目标、已摄入、剩余额度、库存、家庭记忆
2. `get_inventory` — 只读库存查询
3. `find_dish_candidates` — 硬过滤候选菜（无排名）
4. `finalize_meal_plan` — Agent 提交完整选菜；Domain 校验、**营养换算**、采购缺口、落盘
5. `retrieve_local_knowledge` — **本地 RAG**（embedding + 余弦检索，带来源路径）
6. `preview_inventory_change` — 预览入库变更（确认前不写库）
7. `preview_member_memory_change` — 预览家庭偏好/事实变更（确认前不写库）
8. `preview_caregiver_task` — 预览任务卡与**采购清单**（不发送；caregiver 为本地模拟收件箱）
9. `preview_meal_completion` — 预览「按计划吃完」的账本写入（不落库）

### 本地 RAG（bge-small + 独立端口）

语料：`fixtures/knowledge/corpus/`。Agent 工具：`retrieve_local_knowledge`。

推荐（与 chat 分离）：

| 端口 | 用途 | 模型 |
|------|------|------|
| `8000` | Agent 对话 / 工具路由 | Gemma 等 chat |
| `8001` | 向量检索 | `BAAI/bge-small-zh-v1.5` |

```bash
# 实例上起 embedding（示例）
bash scripts/rag/serve-bge-small.example.sh
# 自检
npm run rag:check

export PRIVATEPLATE_RAG_MODE=vllm
export PRIVATEPLATE_EMBEDDING_BASE_URL=http://127.0.0.1:8001/v1
export PRIVATEPLATE_EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5
npm run dev:server
```

未设置 `PRIVATEPLATE_RAG_MODE=vllm` 时用离线 hash embedding（测试专用，不算真 RAG 证据）。

确认写入：

- 任务卡：UI / `POST /api/pending-actions/:id/confirm`
- 本餐完成：`POST /api/households/:id/meal-complete`

**仍在 Domain：** 营养计算、采购缺口、任务卡构建与确认发送。Agent 选菜；Domain **不排名、不选 winner**。

## 当前证据边界

| 证据 | 当前结论 |
| --- | --- |
| 本地 TypeScript 与产品测试 | 以工作区最新 `npm run test:eval-v2` / workspace 单测为准 |
| v2 dev seed 与生命周期合同 | 8 条 dev seed、6 条 lifecycle spec；6 条由真实 Agent/Domain/checkpoint runner 执行，Scripted 结果只标 `structure_only` |
| 三栏 v2 scorer | 分开输出 `Model Native`、`Product Resilient`、`Safety`，主 oracle 是状态不变量 |
| Radeon 真实模型（诊断复跑） | `sealed-suite-diag-16k-20260804T161006Z-brfix`：Model 21/21 · Product 17/21 · Safety 21/21；见 [AMD 适配说明](submission/AMD_RADEON_ROCM_ADAPTATION_AND_OPTIMIZATION.md)。诊断复跑，**不是**盲测正式成绩 |

本地结构通过 ≠ 盲测正式通过。当前正式诊断证据见 `benchmarks/c0/stage-b/sealed-suite-diag-16k-20260804T161006Z-brfix/`。

## 环境与依赖

### 运行环境

- Node.js 22.13 或更高（`package.json` → `engines.node`：`>=22.13`）；
- npm；
- macOS 或 Linux（本地开发与结构测试）；
- 正式 Radeon 推理路径：Linux x86_64、AMD Radeon GPU（仓库 pin 为 `gfx1100`）、ROCm、Python 3.12、与 ROCm 匹配的 vLLM wheel。可执行安装计划见 `scripts/c0/stage-b/install-plan.json` 与 `scripts/c0/stage-b/00-install-runtime.sh`；完整适配说明见 [AMD 适配说明](submission/AMD_RADEON_ROCM_ADAPTATION_AND_OPTIMIZATION.md)。

### 依赖列表

根目录 `npm install` 会安装全部 npm workspaces 依赖（`packages/*`、`apps/*`）。下表版本均来自各 `package.json` 或 `scripts/c0/stage-b/runtime-pin.json`，未经 pin 的组件不在此列出。

**Node.js 运行时前提**

| 组件 | 版本 / 要求 |
| --- | --- |
| Node.js | `>=22.13` |
| npm | 随 Node 安装 |
| 操作系统（开发） | macOS 或 Linux |
| 操作系统（Radeon 正式路径） | Linux x86_64 |

**npm 工作区 runtime 依赖**

| 工作区 | 依赖 | 版本 |
| --- | --- | --- |
| `@privateplate/contracts` | `zod` | `^3.24.2` |
| `@privateplate/domain` | `@privateplate/contracts` | `0.1.0` |
| | `zod` | `^3.24.2` |
| `@privateplate/agent-runtime` | `@privateplate/contracts` | `0.1.0` |
| | `@privateplate/domain` | `0.1.0` |
| | `zod` | `^3.24.2` |
| `@privateplate/server` | `@privateplate/agent-runtime` | `0.1.0` |
| | `@privateplate/domain` | `0.1.0` |
| | `express` | `^4.21.2` |
| | `zod` | `^3.24.2` |
| `@privateplate/web` | `react` | `^19.0.0` |
| | `react-dom` | `^19.0.0` |
| `@privateplate/evals` | `@privateplate/agent-runtime` | `0.1.0` |
| | `@privateplate/domain` | `0.1.0` |

**npm 工作区 dev 依赖（构建 / 测试）**

| 工作区 | 依赖 | 版本 |
| --- | --- | --- |
| `@privateplate/contracts` | `typescript` | `^5.8.2` |
| | `vitest` | `^3.0.9` |
| `@privateplate/domain` | `typescript` | `^5.8.2` |
| | `vitest` | `^3.0.9` |
| `@privateplate/agent-runtime` | `typescript` | `^5.8.2` |
| | `vitest` | `^3.0.9` |
| `@privateplate/server` | `tsx` | `^4.19.3` |
| | `typescript` | `^5.8.2` |
| | `vitest` | `^3.0.9` |
| | `supertest` | `^7.0.0` |
| `@privateplate/web` | `vite` | `^6.2.0` |
| | `@vitejs/plugin-react` | `^4.3.4` |
| | `typescript` | `^5.8.2` |
| `@privateplate/evals` | `tsx` | `^4.19.3` |
| | `typescript` | `^5.8.2` |
| | `vitest` | `^3.0.9` |

各工作区还使用对应 major 的 `@types/*`（见各 `package.json`）。

**推理侧 / GPU 依赖（Radeon + vLLM）**

| 组件 | 版本 / 标识 | 说明 |
| --- | --- | --- |
| Python | `3.12.x` | `runtime-pin.json` |
| ROCm | `7.2.3`（首选）；`7.2.1` 可接受 | 镜像自带，见 `runtime-pin.json` |
| vLLM | `0.25.1+rocm723` | ROCm wheel，见 `runtime-pin.json` |
| PyTorch | `2.11.0+gitd0c8b1f` | vLLM 配套 wheel，见 `runtime-pin.json` |
| transformers | `5.14.1` | Gemma 4 QAT 架构支持 |
| compressed-tensors | `0.17.0` | Gemma QAT W4A16 量化 |
| 对话模型 | `google/gemma-4-12B-it-qat-w4a16-ct` | 默认 chat，端口 `8000` |
| 向量模型 | `BAAI/bge-small-zh-v1.5` | 本地 RAG embedding，端口 `8001`；示例脚本 `scripts/rag/serve-bge-small.example.sh` |

RAG 与 chat 分离时的端口约定见上文「本地 RAG」小节。

## 安装

从比赛总仓库克隆后，先进入项目目录：

```bash
cd submissions/track2-privateplate
npm install
```

## 运行 Web Dashboard

默认 Agent Provider 为 **local_vllm**（真实 Agent 路径）。模型未就绪时聊天会禁用。

**演示前最小环境变量（本机已通过 SSH 隧道把 Radeon 的 8000/8001 转到 loopback 时）：**

```bash
export PRIVATEPLATE_RAG_MODE=vllm
export PRIVATEPLATE_VLLM_BASE_URL=http://127.0.0.1:8000/v1
export PRIVATEPLATE_MODEL_ACTIVE=google/gemma-4-12B-it-qat-w4a16-ct
export PRIVATEPLATE_EMBEDDING_BASE_URL=http://127.0.0.1:8001/v1
export PRIVATEPLATE_EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5
```

第一个终端启动 API：

```bash
npm run dev:server
```

第二个终端启动页面：

```bash
npm run dev:web
```

浏览器打开 `http://127.0.0.1:5173`。API 默认 `http://127.0.0.1:8787`。
就绪自检：`curl -s http://127.0.0.1:8787/api/runtime/status` 应见 `"modelReady":true` 与 `"rag":{"mode":"vllm_embedding",...}`。
重置演示数据：`curl -s -X POST http://127.0.0.1:8787/api/demo/reset`。

- Dashboard 默认 DB：`./data/privateplate-demo.sqlite`（跨重启保留家庭记忆）
- 测试使用 `:memory:`
- 「新对话」只清会话，不删 SQLite 家庭数据
- 提交材料导读：[`submission/README.md`](submission/README.md)

### 多模态输入（真实模型路径）

- 聊天输入附近的「语音输入」使用浏览器 `MediaRecorder` 录制短音频；转写结果只填入文本框，用户仍需亲自点击「发送」。
- 家庭库存区域的「拍照识别」只接受 JPEG、PNG、WebP，单张图片上限 5 MB；模型输出可编辑的“识别草稿，需要确认”，不直接写入库存。
- 一张照片识别多项时，用户必须单选一项，再由现有 Agent 生成 `preview_inventory_change` 预览；确认链和库存写入规则不变。
- intake 复用现有 `PRIVATEPLATE_VLLM_BASE_URL` 与 `PRIVATEPLATE_MODEL_ACTIVE`；如 vLLM 开启鉴权，可设置 `PRIVATEPLATE_VLLM_API_KEY`，请求超时沿用 `PRIVATEPLATE_REQUEST_TIMEOUT_MS`。
- 音频和图片默认不落盘；音频限制为 3 MB、15 秒，需要远端 vLLM 的音频依赖。本次验证实例已补齐兼容的 `av==18.0.0`，没有替换定制版 vLLM；依赖缺失时 Web 显示“当前环境暂不可用”，不使用浏览器 Web Speech 或第三方云服务回退。当前 Gemma 4 的中文转写质量仍需人工检查。
- 多模态请求遥测使用 `vision_intake` / `audio_intake` 独立标记，不计入 terminal-finalization A/B benchmark。

## 构建后单端口启动

```bash
npm start
```

由 `127.0.0.1:8787` 同时提供 API 和已构建页面。

## 本机模型与 production 模式

```bash
export PRIVATEPLATE_APP_MODE=production
export PRIVATEPLATE_AGENT_PROVIDER=local_vllm
export PRIVATEPLATE_VLLM_BASE_URL=http://127.0.0.1:8000/v1
export PRIVATEPLATE_MODEL_ACTIVE="REPLACE_WITH_MODEL_ID"
export PRIVATEPLATE_ACCESS_TOKEN="REPLACE_WITH_AT_LEAST_16_CHARACTERS"
npm start
```

访问用户名固定为 `privateplate`，密码是 `PRIVATEPLATE_ACCESS_TOKEN`。Server 与 vLLM 均应只允许本机访问。

## 验证

```bash
npm run typecheck
npm run test:eval-v2
npm run test -w @privateplate/domain
npm run test -w @privateplate/agent-runtime
npm run test -w @privateplate/server
```

或：

```bash
npm run check
```

`check` 通过不等于真实模型在 Radeon 上通过。

`fixtures/evals/public-v2-dev-seed.json` 是当前 8 条开发场景，
`fixtures/evals/stateful-v2-lifecycle-specs.json` 是 6 条正式生命周期规格。
生命周期规格证明 Product Resilient / Safety 结构层（`STRUCTURE_ONLY`），不提供模型能力分。
Radeon 真实模型诊断复跑见上文「当前证据边界」与 `submission/`；**不是**盲测正式成绩。
`npm run check` 含 `test:eval-v2`、typecheck、LocalMock routing smoke，以及 `test:c0-integrity-current`。真正九工具产品路径以 `test:eval-v2` 为准。

## 仓库结构

```text
apps/
  server/             API、SSE、会话、meal-complete、媒体 intake
  web/                React Dashboard、语音与图片草稿交互
packages/
  contracts/          共享数据与校验合同
  domain/             SQLite、日账本、候选过滤、Agent 选菜校验
  agent-runtime/      PrivatePlateAgent、九工具网关、local_vllm / ScriptedProvider
  evals/              v2 schema/scorer、dev seed、生命周期规格
fixtures/             合成家庭与评测输入
benchmarks/           Radeon 正式诊断与 A/B 证据
docs/
  submission/         AMD 适配与提交材料
```

## 项目文档

- [AMD Radeon / ROCm 适配与优化说明](submission/AMD_RADEON_ROCM_ADAPTATION_AND_OPTIMIZATION.md)
- [项目说明（英）](submission/PROJECT_SPECIFICATION.md)
- [提交材料导读](submission/README.md)
- 正式诊断证据：`benchmarks/c0/stage-b/sealed-suite-diag-16k-20260804T161006Z-brfix/`

## 提交材料状态

赛事要求包括项目说明、完整源码、README、3–5 分钟 Radeon 实际演示视频，以及 PPT 或海报二选一。

**提交包入口（对照优秀 Track 2 作品整理）：** [`submission/README.md`](submission/README.md)

| 材料 | 位置 | 状态 |
| --- | --- | --- |
| 项目说明（英，赛道二五项） | [`submission/PROJECT_SPECIFICATION.md`](submission/PROJECT_SPECIFICATION.md) | 已提交 |
| AMD 适配与优化说明（英） | [`submission/AMD_RADEON_ROCM_ADAPTATION_AND_OPTIMIZATION.md`](submission/AMD_RADEON_ROCM_ADAPTATION_AND_OPTIMIZATION.md) | 已提交 |
| 演示视频 | [YouTube (unlisted)](https://youtu.be/2XIZmQV2vQk) | 已链接 |
| 补充 PPT | [`submission/PrivatePlate_Track2_Submission.pptx`](submission/PrivatePlate_Track2_Submission.pptx) | 已提交 |
| 提交材料导读（英） | [`submission/README.md`](submission/README.md) | 已提交 |

官方提交流程：fork [`AMD-DEV-CONTEST/Radeon-hackathon-2026-07`](https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07) → 开 PR，标题形如 `Track 2, <姓名或队名>, PrivatePlate`（评委材料建议英文）。

未经项目所有者明确批准，不启动、连接或操作 Radeon 实例。
