# XAI 双核融合架构 蓝图 v2.0

> 基准：蓝图 v1.1（4 层：A 交互 / B 引擎 / C 执行 / D 基础设施）
> 升级来源：v1.1 落地后全系统实测、三核真实验证、7 项用户需求追加
> 撰写时间：2026-07-19 · 状态：分析完成、待老大裁定后执行
> 继承关系：本文件继承并扩展 `XAI_ARCHITECTURE.md` §1-10，不覆盖不冲突

---

## 一、v1.1 → v2.0 升级概述

### v1.1 回顾（已落地）
```
A. 用户交互层 ── 对话 / 画布 / 成果
B. 核心引擎层 ── Intent Router + Hermes + Grok Build + Control Loop + Guardian
C. Substrate ──── OpenClaw 本体
D. 基础设施 ──── 8层记忆（含失败修正层·我们特有） / 模型路由 / 本地KB / 自蒸馏
```

### v2.0 核心变化（5 项）
| 编号 | 变化 | 理由 |
|------|------|------|
| **V1** | 宪法从 8 条→10 条（增 Chat-Canvas 共創、Connector Hub） | 用户新需求 + 能力发现 |
| **V2** | 7 层记忆→8 层（+失败修正层） | 代码已落 `memory_core.py` FAILURE_CORRECTION |
| **V3** | 三核状态矩阵（Hermes/GrokBuild/OpenClaw 各 real/stub/broken）| 实测驱动：Grok 一行 bug 未修 |
| **V4** | D 层新增 2 子项：Connector Hub（MCP 管理）+ Output Scaffolding（回答交付系统） | 对标 WorkBuddy 成熟交互 |
| **V5** | 状态标记体系：每条能力标注 ✅已通 / ⚠️待修 / 🔲未建 / ❌空缺 | 从"全绿叙述"升级为"真实审计" |

---

## 二、宪法 v2.0（10 条）

> 违反以下任何一条的重大改动，须先经用户签字。

1. **双内核并列**：Hermes（通用推理·GEPA 自进化）+ Grok Build（代码工程·二进制桥接），均为第一类公民，无层级。
2. **Intent Router 仲裁**：任务分类后自动化分发至最优内核；code_dev→Grok、file/automation→OpenClaw、research/chat→Hermes。
3. **认知 Control Loop**：Reason → Meta → Runner → L4 Verify → Distill，两核共享。**v2.0 要求：ControlLoop 必须串入主 chat() 流，不得孤立运行**。
4. **Guardian 治理闸门**：P0/P1/P2 风险分级 + 二次确认 + 审批队列，覆盖核心引擎层全区域。
5. **8 层元认知记忆（单一事实源）**：工作 / 短期 / 长期 / 锚点 / 反思 / 因果链 / 用户画像 / **失败修正**。所有模块经 `memory_core` API 写入，带 `engine` 标签，禁止自建独立向量库。
6. **Substrate 执行网关 = OpenClaw**：工具路由 + 文件/终端/浏览器/MCP/技能/频道 全栈，卡 Guardian 之下。
7. **控制台为纯视图层**：所有业务逻辑在引擎（Python）；UI 能力由内核能力注册表 `/api/capabilities` 驱动。
8. **前端底座 = `xai-frontend/`**（OllamaFlow 液态玻璃，亮色默认 + 暗色可切换）。`web/`、`frontend/` 已归档。
9. **【v2.0 新增】Chat-Canvas 共創**：对话页右面板（PlanCanvas→升级为 Generic Thinking Canvas）支持 AI 思考结构实时渲染 + 用户拖拽编辑 + 修改反馈给 AI。对话题和画布双向同步。
10. **【v2.0 新增】Connector Hub**：管理页内 MCP/API/IM 连接器可视化管理（新增/测试/启停/日志），对标 WorkBuddy 的「自定义连接器」交互模式。

---

## 三、四层架构 v2.0 全状态矩阵

### A · 用户交互层（纯视图，零业务逻辑）

| 子项 | 状态 | 说明 |
|------|------|------|
| 对话（流式+附件） | ✅ | `XAIChatPage` + SSE |
| 画布（DAG 工作流编辑器） | ✅ | `CanvasPage` / `OrchestratorPage`（ReactFlow） |
| 成果（交付物+本地打开） | ✅ | SSE `deliverable` + `/api/open` |
| PlanCanvas（计划画布） | ✅ | 对话右面板，生成→编辑→apply |
| 对话历史（多会话管理） | 🔲 | `SessionStore` 已有后端，前端无列表/恢复界面 |
| 任务历史（完成/失败列表） | 🔲 | TasksPage 无"历史"视图 |
| Output Scaffolding（结构化回答） | 🔲 | 回答格式改革：system prompt 层注入结构模板，前端渲染卡片 |
| **Chat-Canvas 共創（v2.0 核心新功能）** | 🔲 | PlanCanvas→Generic Thinking Canvas |

### B · 核心引擎层（Guardian 覆盖全域）

| 子项 | 状态 | 说明 |
|------|------|------|
| Intent Router（意图路由） | ✅ | `_classify_intent()` 启发式，三核命中，`/api/intent` |
| Hermes（通用推理核） | ✅ | real v0.18.0，GEPA 自进化类存在，DeepSeek 驱动 |
| **Grok Build（代码工程核）** | ⚠️ | 二进制在、桥接在、路由在；`grok_build_engine.py` L344 一行参数顺序错误导致每次回退 Hermes。**修复：`cmd = [grok, "--single", task, "--output-format", "json"]`** |
| Control Loop（认知控制环） | ⚠️ | `ControlLoop` 类存在但**未串入 `chat()` 主流程**。孤立运行，Reason→Meta→Runner 链路断。 |
| Guardian（治理闸门） | ✅ | P0/P1/P2 + `/api/approvals/confirm` |
| GEPA 自进化（技能进化） | ⚠️ | `GepaEvolver` 类存在，**零触发机制**（无自动/无手动入口） |
| 子工作流（Subflow） | ✅ | `run_workflow()` 支持嵌套（Kahn 拓扑排序） |
| 条件分支（Condition） | ✅ | 后端 `condition` 类型，前端节点 `conditional`（命名待对齐） |

### C · Substrate 执行网关 = OpenClaw 本体

| 子项 | 状态 | 说明 |
|------|------|------|
| OpenClaw 本体 | ✅ | real 2026.6.11 (e085fa1)，本地 CLI 桥接 |
| 文件读/写/删 | ✅ | `_file_read/write/delete`（安全路径校验） |
| 终端执行 | ✅ | `_exec_command`（dry-run 优先） |
| 浏览器/截图 | ✅ | `browse / screenshot` |
| MCP 工具 | ✅ | `call_tool`（server→tool→args） |
| 定时任务 | ✅ | `add_job / list_jobs`（cron） |
| 技能系统 | ✅ | `load_skill / list_skills` |
| 消息分发（IM/邮件） | ✅ | `send(platform, to, content)` |
| PermissionBridge（安全执行管道） | ✅ | 类存在，前端缺工具执行可视化 |
| 工具执行前端可视化 | 🔲 | OpenClaw 工具调用时实时显示在事件流 |

### D · 基础设施

| 子项 | 状态 | 说明 |
|------|------|------|
| 8 层元认知记忆 | ✅ | `memory_core.py` L31-39：working / short_term / long_term / anchor / reflection / causal / user_profile / failure_correction |
| 单一事实源 | ✅ | 所有模块经 `MemoryCore` SQLite 写入 |
| 模型注册表 | ✅ | `model_registry`，DeepSeek 激活，Ollama 检测 |
| **模型路由（三源）** | ⚠️ | DeepSeek 接通；Ollama 已检测未实际可切换；**Grok 未进路由**（仅作代码子核 binary 调用） |
| 本地知识库（RAG） | ✅ 基础 | `kb.py` 词袋+余弦检索，无 embedding |
| 本地知识库 embedding 升级 | 🔲 | Chunk→Embed→余弦→RAG |
| 自蒸馏（技能提炼） | ⚠️ | `Distiller` 类存在，**零触发** |
| GEPA 自进化触发 | ⚠️ | `GepaEvolver` 类存在，**零触发** |
| MemOS 外部源桥接 | 🔲 | 蓝图原列 MemOS+TrueAgent 双源，实际未接入 |
| **Connector Hub（MCP/API 连接器管理）** | 🔲 | v2.0 新增：管理页内可视化管理面板 |
| 实时事件总线（SSE） | ✅ | `/api/events/stream` + 心跳线程 |
| 能力注册表 | ✅ | `/api/capabilities` 15 节点 |
| **Output Scaffolding（结构化回答系统）** | 🔲 | v2.0 新增：system prompt 注入结构模板 + 前端卡片渲染 |
| 对话历史持久化 | ✅ | `SessionStore` SQLite |
| 任务持久化 | ✅ | `app_store.py` SQLite |

---

## 四、v2.0 新增组件详述

### 4-1 · Chat-Canvas 共創（Conversational Visual Co-creation）

**这是什么**：对话页右面板从「PlanCanvas（计划专用）」升级为「Generic Thinking Canvas（通用思考画布）」。

**与现 PlanCanvas 的关系**：PlanCanvas 是基础，v2.0 将其扩展为：
| 新增 node 类型 | 用途 |
|---------------|------|
| concept（概念节点） | AI 头脑风暴输出的论点/分类/层级 |
| reasoning（因果链） | AI 推理的 A→B→C 链路，可拖拽断连/改方向 |
| architecture（架构节点） | AI 生成的系统结构图，可增删模块 |
| dependency（依赖图） | AI 扫描代码/文件后输出的依赖关系 |
| file_ref（文件节点） | 引用的文件，双击在本地打开 |
| memory（记忆节点） | 从 8 层记忆检索到的相关知识点，drag-in 到画布 |

**双向同步机制**：
1. AI 回答结束 → 自动提取结构化内容 → 渲染到画布
2. 用户在画布上拖拽、增删、重连 node → 触发 `onCanvasChange` → **注入到对话上下文**（"用户修改了思考结构：..."）
3. 用户发下一句话时，AI **基于修改后的画布结构**作答

**对标产品**：Flowith（2D Canvas + Chat Co-creation），但我们是**双栏非无限画布**（更紧凑）。

### 4-2 · Connector Hub（MCP 连接器管理面板）

**这是什么**：管理页（XAIManagePage）内新增「连接器」标签页。

**功能清单**：
| 功能 | 说明 |
|------|------|
| 连接器列表 | 名称、类型（stdio/SSE/HTTP）、状态开关、最后连接时间 |
| 新增连接器 | 表单：名称 + 类型 + 命令/URL + args + 环境变量 |
| 测试连接 | 点击按钮 → 调用后端 `health_check` → 显示结果 |
| 日志查看 | 点击行 → 展开最近 N 条调用日志 |
| 工具列表 | 每个连接器下展示其暴露的 MCP Tool 列表 |

**对标产品**：WorkBuddy 的「自定义连接器」管理面板。

**数据流**：前端 `ConnectorHub` → `lib/api.ts` → `POST /api/connectors/*` → 后端 `mcp_registry` → 更新 OpenClaw MCP 插件列表 → 状态实时回到事件总线。

### 4-3 · Output Scaffolding（结构化回答系统）

**这是什么**：AI 的 system prompt 注入结构模板，强制回答以"可扫描→可检索→可直接行动"的三段式产出。

**模板**：
```
回答要求（不可违反）：
1. 【结论】：1-2 句核心摘要
2. 【结构化要点】：每条以 "→" 开头，独立一行
3. 【下一步行动】：具体、可执行、含目标
禁止：超过 4 段连续平铺文本、无标题长段落、模糊建议
```

**前端渲染**：收到 SSE `answer` 事件时，根据内容自动识别结构块并渲染为卡片/折叠/要点列表（不改 SSE 协议，纯前端解析）。

### 4-4 · 对话历史 & 任务历史

**对话历史**：
- 前端：`XAIChatPage` 顶栏新增「历史」图标 → 点击展开下拉（会话列表：标题预览 + 日期 + N 条消息） → 点击恢复会话
- 后端：已就绪（`SessionStore.session_list`）

**任务历史**：
- 前端：`TasksPage` 新增「历史」标签页 → 状态筛选 + 日期范围 + 搜索 → 点击查看执行日志
- 后端：已就绪（`app_store.py` CRUD）

---

## 五、v2.0 优先级路线图（三阶段）

### 第一阶段：修复型（1~3 小时，P0）

| 序号 | 任务 | 影响 |
|------|------|------|
| 1 | **修 Grok Build 一行**（`grok_build_engine.py` L344） | 整个工程核从虚设→真实可用 |
| 2 | **ControlLoop 串入 chat()**（`engine_xai.py` 主流程） | 蓝图 v1.1 就要求但一直断的链路 |
| 3 | **模型路由三源补齐**（Grok 注册进 `model_registry`） | 蓝图明列 DeepSeek·Ollama·Grok，目前只通 1 源 |

### 第二阶段：能力型（1~2 天，P1）

| 序号 | 任务 | 影响 |
|------|------|------|
| 4 | **GEPA 自进化触发**（chat 结束/Guardian 拦截/用户手动 三入口） | 技能进化从空壳→自运行 |
| 5 | **对话历史前端**（XAIChatPage 顶栏历史下拉） | 解决"找不到刚才说的话" |
| 6 | **任务历史前端**（TasksPage 历史标签） | 任务闭环 |
| 7 | **Connector Hub**（管理页 MCP 面板） | 对标 WorkBuddy 交互成熟度 |
| 8 | **Output Scaffolding**（system prompt 模板 + 前端解析） | 所有回答质量根本性提升 |

### 第三阶段：演进型（3~7 天，P2）

| 序号 | 任务 | 影响 |
|------|------|------|
| 9 | **Chat-Canvas 共創**（PlanCanvas→Generic Thinking Canvas 升级） | v2.0 标志性功能 |
| 10 | 本地 KB embedding 升级 | 检索精度 |
| 11 | MemOS 外部源桥接 | 知识扩展 |
| 12 | 工具执行前端可视化 | 治理透明度 |
| 13 | 端到端自动化测试 | 回归保护 |

---

## 六、决策点（待老大裁定）

1. **v2.0 宪法 10 条是否通过？** —— 特别是第 9 条（Chat-Canvas 共創）、第 10 条（Connector Hub）是否足够重要到进宪法层级？
2. **第一阶段（P0 三项）是否立即执行？** —— 都是修复型工作，零风险、高影响
3. **"Output Scaffolding" 的激进程度？** —— 全量改为三段式 vs 可选开关 vs 场景判断？
4. **Chat-Canvas 共創的优先级？** —— P2 或应提前到 P1？（用户反复提及这个需求）
5. **蓝图 v2.0 文档是否作为新的「单一事实源」？** —— 替换或与 v1.1 并存？

---

> 本文件 v2.0 全文 = 分析阶段输出。所有改动待老大裁定后执行。
