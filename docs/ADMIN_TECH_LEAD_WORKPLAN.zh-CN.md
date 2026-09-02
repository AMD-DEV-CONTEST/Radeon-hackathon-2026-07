# ProjectPack Office Agent：管理员 / 技术负责人工作计划

## 1. 角色定位

你是项目管理员和技术负责人，不承担所有功能编码；你的职责是让项目**可运行、可集成、可验收、可提交**。

你拥有以下最终决策权：

- GitHub `main` 分支、分支保护规则和 PR 合并；
- 云端 AMD GPU 实例、模型服务、密钥与环境变量；
- 产品范围、接口 Schema、项目数据落点和安全边界；
- 演示验收、性能证据和比赛最终 PR。

## 2. 你的交付目标

在队友提交应用功能时，你应始终能回答：

1. 代码是否能从 GitHub fork 复现？
2. 是否能调用云端 `qwen3.6-office-agent`？
3. 资料是否只落在当前项目的受控目录？
4. 每个结论是否能回到来源文件、页码、章节或 Sheet？
5. 失败时是否能定位到文件解析、检索、规则判定、模型调用或报告生成？

## 2.1 你亲自开发的代码模块

你不是只负责 GitHub 和云端。你应亲自完成“应用骨架、模型接入、受控编排和集成 API”，这是队友的 RAG/报告功能能落地的前提。

| 优先级 | 你要开发的模块 | 主要文件建议 | 完成标准 |
| --- | --- | --- | --- |
| P0 | 应用配置与启动 | `app/config.py`、`app/main.py`、`.env.example` | 应用能启动；配置缺失有明确报错；目录自动检查 |
| P0 | 模型网关 | `app/llm/client.py`、`app/llm/metrics.py` | 调用 `qwen3.6-office-agent` 成功；可读取健康状态、模型名、响应耗时 |
| P0 | 公共数据 Schema | `app/schemas/project.py`、`task.py`、`evidence.py`、`report.py` | 队友可直接导入；非法输入被 Pydantic 拒绝 |
| P1 | 项目与路径安全 | `app/services/projects.py`、`app/security/paths.py` | 每个项目只能访问自己的 `source/`、`derived/`、`outputs/` |
| P1 | FastAPI 骨架 | `app/api/projects.py`、`runs.py`、`health.py` | 可创建项目、触发导入/运行、查询运行状态；接口有测试 |
| P1 | 受控周报编排器 | `app/agent/runner.py`、`rules.py`、`state.py` | 固定执行“检索→规则判断→模型解释→报告”；最多 8 步；禁止自由 Shell |
| P2 | 确认、日志与集成 | `app/services/confirmations.py`、`app/observability/audit.py` | 覆盖/修改操作必须确认；每次运行有 run_id 和 JSONL 日志 |
| P2 | 云端启动与诊断脚本 | `scripts/start_api.sh`、`start_ui.sh`、`diagnose.sh` | 新实例按 README 可启动、诊断并验证模型服务 |

## 2.2 你的首周编码顺序

### Day 1：可启动骨架

- [ ] 建立 Python 项目依赖、`app/` 目录和 `.env.example`。
- [ ] 编写 `Settings`，集中管理 LLM、项目路径、SQLite、输出和最大步骤配置。
- [ ] 编写 `GET /health`：同时报告 API 自身状态和 llama-server 连接状态。
- [ ] 编写最小测试：缺失配置、非法端口、模型服务不可达。

**当天验收**：本地/云端执行启动命令后，`curl http://127.0.0.1:9000/health` 返回 JSON；模型离线时返回受控错误而非崩溃。

### Day 2：模型客户端与公共契约

- [ ] 实现 OpenAI 兼容 `LLMClient`，默认调用 `qwen3.6-office-agent`。
- [ ] 提供两种固定调用：普通文本生成与低温度结构化 JSON 生成。
- [ ] 建立 `Project`、`Task`、`Evidence`、`TaskEvaluation`、`RunState`、`ReportDraft` Schema。
- [ ] 和队友确定这些 Schema 后冻结字段；新增字段通过 PR 评审。

**当天验收**：用模型生成一个 `TaskEvaluation` JSON；非法 JSON 能被重试一次并最终返回结构化错误。

### Day 3：项目 API 与路径边界

- [ ] `POST /api/projects` 创建 `project_id` 和受控目录。
- [ ] `GET /api/projects/{project_id}` 返回项目元数据和导入状态。
- [ ] 实现 `ensure_project_path()`，拒绝 `..`、绝对路径、符号链接逃逸和项目目录外路径。
- [ ] 交给队友的接口：传入 `project_id` 获得合法 `source/` 路径，而不是传入任意文件系统路径。

**当天验收**：正常项目路径可用；`../../etc/passwd`、其他项目 ID、绝对路径都被拒绝。

### Day 4–5：受控编排器

- [ ] 定义固定步骤和状态：`scanning`、`indexing`、`retrieving`、`evaluating`、`drafting`、`waiting_confirmation`、`completed`、`failed`。
- [ ] 编排器只调用已注册的队友工具，不让模型任意选择 Python/Shell 函数。
- [ ] 先运行规则层，再让模型解释；缺证据统一输出 `needs_confirmation`。
- [ ] 保存 run 状态和 JSONL 审计日志。

**当天验收**：给定 fake 工具结果，可稳定跑出完整状态流；重复步骤、未知工具、超过 8 步均会失败并记录原因。

## 2.3 你与队友的接口约定

你向队友提供：

```python
project_root(project_id) -> Path
llm_client.generate_json(schema, prompt) -> BaseModel
run_context(run_id, project_id) -> RunContext
audit_event(run_id, event, payload) -> None
```

队友向你提供：

```python
scan_project(project_id) -> ScanResult
index_project(project_id) -> IndexResult
retrieve(project_id, query) -> list[Evidence]
load_tasks(project_id) -> list[Task]
evaluate_tasks(tasks, evidence) -> list[TaskEvaluation]
render_reports(evaluations) -> ReportDraft
```

接口先以 Pydantic Schema 固定；内部实现可以迭代，但不能让双方依赖未约定的字典字段。

## 3. 阶段任务

### 阶段 A：项目基础与契约（优先完成）

- [ ] 保持 `main` 受保护；只合并通过 required checks 的 PR。
- [ ] 维护 GitHub fork：`origin` 为个人仓库，`upstream` 为官方仓库。
- [ ] 建立项目根目录、`.env.example`、`.gitignore`、依赖文件和启动说明。
- [ ] 固定模型调用配置：

  ```text
  LLM_BASE_URL=http://127.0.0.1:8000/v1
  LLM_MODEL=qwen3.6-office-agent
  ```

- [ ] 固定云端数据落点，禁止应用访问项目目录外文件：

  ```text
  /workspace/office-agent/data/projects/<project_id>/source/
  /workspace/office-agent/data/projects/<project_id>/derived/
  /workspace/office-agent/data/vector_db/
  /workspace/office-agent/data/sqlite/
  /workspace/office-agent/outputs/
  /workspace/office-agent/logs/
  ```

- [ ] 提供最小 `LLMClient` 和 `/health` 检查，能调用本地 llama-server。
- [ ] 与队友确认并提交数据契约：`Project`、`Task`、`Evidence`、`TaskEvaluation`、`Report`。

**验收标准**：空项目可启动；API 能返回模型列表/健康状态；无资料、无模型、非法路径都有清楚错误信息。

### 阶段 B：集成与受控编排

- [ ] 负责项目导入后的端到端流程编排，而不是让模型自由执行工具。
- [ ] 固定工作流：扫描 → 解析/索引 → 读任务 → 检索证据 → 规则判断 → 模型解释 → 报告草稿。
- [ ] 设置安全边界：工具白名单、Pydantic 参数校验、项目路径校验、最多 8 步、重复调用检测。
- [ ] 定义确认策略：只有覆盖、修改、删除已有文件或任务数据时阻断并要求确认；证据不足只标记“待确认”。
- [ ] 统一 JSONL 日志字段：`run_id`、步骤、工具、参数摘要、耗时、状态、错误、来源数量。

**验收标准**：一条周报请求的每一步都可查看，失败能定位，报告不会把“证据不足”写成“已完成”。

### 阶段 C：云端验证与比赛材料

- [ ] 用 Git 拉取代码到 PVC 工作区；云端不作为代码唯一来源。
- [ ] 验证 llama-server：`/health`、`/v1/models`、一次中文对话、GPU 显存和 Tokens/s。
- [ ] 维护演示资料集，确保不含真实敏感项目数据。
- [ ] 执行完整冒烟：导入 → 问答带引用 → 任务核验 → 周报/风险表/下周计划。
- [ ] 收集 AMD 适配证据：GPU 型号 gfx1100、ROCm、llama.cpp HIP、模型量化格式、上下文、Prompt/Generation Tokens/s。
- [ ] 组织英文 README、架构图、项目说明、3–5 分钟演示视频和最终比赛 PR。

**验收标准**：在新的云端实例中，按 README 可重建服务并完整演示；项目输出和性能证据可追溯。

## 4. 每日工作节奏

### 开始前（10 分钟）

- 查看 GitHub Issues/PR、当前 `main` 和待集成分支。
- 与队友确认当天唯一可验收目标和输入/输出契约。
- 明确该任务是 `S0`、`S1`、`S2` 还是 `S3`；S1 以上先建立 Spec。

### 集成前（15 分钟）

- 先阅读 PR 的范围、Spec ID、测试证据和风险说明。
- 本地拉取分支并查看 `git diff --stat`，拒绝无关重构或大文件。
- 验证接口/数据模型是否与已约定 Schema 一致。

### 合并前（20–40 分钟）

- required checks 必须通过；检查 PR 标题符合官方格式。
- 运行与改动相符的最小检查，而非盲目全量检查。
- 涉及模型/RAG/报告的 PR，必须至少做一次云端或可复现集成验证。
- 以 Squash merge 合并，并在 PR 中记录结论或后续风险。

## 5. 你不应该做的事

- 不直接在 `main` 写代码或直接 push。
- 不把 GGUF、私钥、`.env`、真实项目资料、向量库或运行日志提交到 Git。
- 不让队友共享你的 SSH 私钥、GitHub Token 或云端账户密码。
- 不在没有来源证据时宣称任务完成。
- 不为赶进度同时更换模型、推理框架和 Agent 框架。

## 6. 你的 PR 模板补充内容

除默认模板外，涉及集成/云端的 PR 必须写：

```md
## Integration evidence

- Model endpoint tested:
- Cloud instance / environment:
- Input fixture:
- Output files:
- GPU / performance evidence:
- Known limitation:
- Rollback:
```

## 7. 与队友的交接清单

队友交付前必须提供：

- PR 链接和 Spec ID（或 `S0/no-spec` 原因）；
- 修改模块、输入/输出 Schema；
- 最小样例资料；
- 运行命令和测试结果；
- 失败场景与当前已知限制；
- 是否需要云端模型、哪些环境变量、是否新增依赖。

你合并后必须反馈：

- 是否已合并；
- 云端验证结论；
- 是否需要修复、补测试或补文档；
- 下一步集成任务。
