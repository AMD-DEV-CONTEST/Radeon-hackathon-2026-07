# XAI —— 本地私有超级 Agent（参考实现 + Rust 集成骨架）

> 定位：本地私有 + 开源可改 + 自带推理增强/元认知/安全审批内核 + 自蒸馏进化 的
> 「Agent 操作系统 + 可视化工作流画布」。卡在 2026 行业共识的"编排/中间件层"价值位。
> 设计定稿见 `../xai-final-design.md`，审计报告见 `audit-report.md`。

## 目录结构

```
xai/
├─ core/                  # Python 参考核心（模型无关，可独立运行/测试）
│  ├─ model_backend.py    # 模型后端抽象（接 DeepSeek/Ollama/Grok/任意 的唯一接口）
│  ├─ model_router.py     # 节点级多模型路由（能力/成本/延迟 + fallback，兼容本地量化+各家API）
│  ├─ guardian.py         # P0 安全审批 + OpenClaw Hook + 治理策略 + 审批队列 + 权限分级(痛点3)【加固】
│  ├─ reason.py           # P0.5 思考增强（吸收 GPT 链式推理/多模态；预算/协议/自精炼/多轨迹）
│  ├─ meta.py             # P10 元认知（Brier 在线校准 + L8 四维审计）
│  ├─ runner.py           # 超长任务执行内核（吸收 Claude Fiber5 规划；分步/checkpoint/续跑/质量门）
│  ├─ kb.py               # 本地知识库（RAG，非 IMA）
│  ├─ memory.py           # 全局统一记忆池（四层 + engine 标签 + 跨引擎查询，消除割裂·痛点1）【升级】
│  ├─ skills.py           # 技能注册（SKILL.md frontmatter + 优先级 + 渐进披露）
│  ├─ orchestrator.py     # 调度中台(多 Agent 编排：管线 + 协作两模式)
│  ├─ distill.py          # 自蒸馏 + GEPA 自进化（吸收 Hermes 复盘→技能）
│  ├─ intent_router.py    # 意图路由器（自动识别 办公/代码/长期业务/调研 → 分发·痛点2）【新增·子Agent】
│  ├─ openclaw_gateway.py # 执行网关抽象（OpenClaw：桌面/浏览器/文档/定时/MCP/办公生态）【新增·子Agent】
│  ├─ grok_build_engine.py# 代码引擎抽象（Grok Build：仓库解析/重构/Git/终端/漏洞/单测）【新增·子Agent】
│  └─ control_loop.py     # 中枢单向控制环 + A2UI 事件流
├─ rust/                  # Rust 真集成骨架（独立可编译 crate，零依赖，未来并入 Grok fork）
│  ├─ xai-grok-guardian/  # ✅ cargo test 通过
│  ├─ xai-grok-reason/    # ✅ cargo test 通过
│  ├─ xai-grok-meta/      # ✅ 新增：Brier 校准 + L8 四维审计（8 测通过）
│  └─ xai-grok-runner/    # ✅ 新增：长任务 step/checkpoint/质量门（7 测通过）
├─ frontend/              # 平台化前端（Vite+React+ReactFlow）：统一操作台+四引擎+意图路由+记忆池+权限
├─ tests/                 # 73 个单元测试（test_xai_core 18 + test_xai_v2 15 + test_xai_v3 10 + intent_router 8 + openclaw_gateway 6 + grok_build_engine 8 + workflow_bridge 8，全绿）
├─ examples/smoke.py      # 端到端冒烟验证（5 层串联跑通）
├─ xai-platform-architecture.md  # v2 重构架构总纲（4引擎+中台+网关+记忆池，逐条映射需求/约束/痛点）
├─ xai-unified-architecture.md   # 统一调度台+画布+流程协同 吸收版架构（调研定稿）
├─ xai-final-design.md    # 总体蓝图（前序）
└─ audit-report.md        # 审计 8 条 + 三冲突闭环核查
```

## 快速验证

```bash
# Python 核心测试（无需联网）
/Users/Admin/.workbuddy/binaries/python/envs/default/bin/python -m pytest tests/ -q

# 端到端冒烟
python examples/smoke.py

# Rust crate 编译+测试
cd rust/xai-grok-guardian && cargo test
cd rust/xai-grok-reason   && cargo test
```

## 平台化前端（统一调度台 + 画布）

```bash
cd frontend && npm install && npm run dev   # 默认 http://localhost:5173
```

- 左侧「统一调度台」：数字员工花名册 / 模型路由 / KB·记忆 / **意图识别** / **全局统一记忆池(痛点1)** /
  **权限分级(痛点3)** / 审批队列 / 长任务进度 / 可观测 / 自进化。
- 中央「画布」：React Flow DAG，节点类型含 **意图路由 / 执行网关(OpenClaw) / 代码引擎(Grok Build) /
  记忆大脑(Hermes) / 调度中台 / 全局记忆池 / 人工审批 / 元认知** 等，拓扑即平台架构。
  点「运行工作流」触发拓扑执行 + A2UI 事件流（吸收 superagent-base A2UI 协议）。
- 右侧「检查器」：选中节点详情 + 能力实时状态。
- 设计来源见 `xai-platform-architecture.md` + `xai-unified-architecture.md`（吸收 OpenClaw/Hermes/WorkBuddy+Coze/Grok Build + GPT/Claude Fiber5 能力）。

## 接入真实模型

只需实现 `core/model_backend.py::ModelBackend`（或 Rust 对应 trait）：

```python
class DeepSeekBackend(ModelBackend):
    def complete(self, prompt, **kw): ...   # 调 DeepSeek API
    def complete_with_confidence(self, prompt, **kw): ...
```

上层 Guardian/Reason/Meta/Runner/KB/Orchestrator/Distill/ControlLoop **零改动**。

## 与 Grok fork 的合并路线

Rust crate 已按 Grok 的 crate 命名约定（`xai-grok-*`）写好，未来：

1. 在 `grok-build-src/crates/codegen/` 下新增对应 crate；
2. 在 `xai-grok-pager` 的 agent 主循环外挂 `xai-grok-control`（单向环）；
3. `xai-grok-guardian` 插进 ACP 权限层前；
4. `xai-grok-reason` 作为每步思考脚手架；
5. `xai-grok-meta` 接管置信校准与 L8 审计；
6. 其余（runner/kb/orchestrator/distill）按 P2–P9 顺序落地。

Apache 2.0 合规（Grok 上游协议）。

---

## XAI 统一操作台（可运行交付：`server_xai.py` + `web/`）

> 一个**零依赖、本地优先、模型无关**的超级 Agent 中台：意图路由 → Guardian 审批 → 调度执行 → SSE 流式输出。
> 融合 OpenClaw（执行网关）/ Hermes（推理+GEPA 进化）/ MemOS（7 层记忆）真实适配层。
> 对标 Open-WebUI / dify / LibreChat 的「流式 + 多轮 + 真实能力 + 治理」上市级体验。

### 启动

```bash
# 方式一：脚本（自动注入 DEEPSEEK_API_KEY，双击即用）
./xai_go.sh            # 或双击 启动XAI.command

# 方式二：直接起服务（需 DEEPSEEK_API_KEY 环境变量）
DEEPSEEK_API_KEY=xxx python3 server_xai.py
# → http://localhost:8000
```

桌面 App：`XAI.app`（双击即用）；平台化画布前端：`frontend/`（`npm run dev` → :5173）。

### 核心能力

- **流式对话**：`token` 事件逐字推送，对标 dify / Open-WebUI（通用对话走 DeepSeek 真实推理 + 多轮上下文）。
- **代码开发**：模型生成 → 写盘 → `py_compile` 语法校验（Grok Build 式代码工程）。
- **浏览器联网搜索**：真实 DuckDuckGo + 基于结果作答，绝不编造。
- **7 层本地记忆**：SQLite 持久化 + 跨引擎检索（`/remember` `/recall`）。
- **GEPA Darwinian 进化**：`/evolve` 调用真实模型改写技能 prompt，入人工复审队列（非假变异）。
- **Guardian 治理**：P0/P1/P2 风险分级，高危操作拦截 + 二次确认，**批准后真正重执行**原意图。
- **多会话管理**：SQLite 会话历史，前端会话栏切换 / 新建。
- **16 个斜杠命令**：`/skill /mcp /task /automate /remember /recall /scan /evolve /models /channels /status /diagnose /clear /help /approve /reject`。

### 自测（零依赖，直接跑）

```bash
python3 tests/selftest_e2e.py        # 第一轮：核心流程 13 项
python3 tests/selftest_e2e_round2.py # 第二轮：命令全量 + 边界 + 并发 13 项
```

最新多轮自测结果见 `tests/QA_REPORT.md`：**26/26 通过**，含并发安全与模型驱动进化验证。

### 已知差距（对标成熟开源项目，诚实清单）

| 能力 | 差距 |
|------|------|
| 语义 RAG / 向量检索 | 当前为关键词 SQLite 记忆，无向量语义检索（**待补**） |
| 多模型路由 + fallback | 仅 DeepSeek 真实接入，其余按 key 动态列出（**待补路由**） |
| 企业多用户 / SSO / RBAC | 当前单机单用户（**商业化前提，待补**） |
| 可观测 / 成本追踪 | 仅 `/diagnose` 体检，无成本与调用追踪（**待补**） |
| 画布执行深耦合 | 画布为 OllamaFlow 式前端，未由后端 JSON 驱动执行 |

核心交互已达上市级可用标准；上述为商业化前必须补齐项。
