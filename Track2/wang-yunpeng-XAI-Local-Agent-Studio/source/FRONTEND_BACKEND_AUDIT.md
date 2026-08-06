# XAI 控制台前端 → 后端依赖审计

方法：Grep/Read 真实代码，`pages/*.tsx` 的 `onClick`/handler 与 `lib/api.ts`，对照 `server_xai.py` 的 80+ 路由。后端为 stdlib `http.server`，路由在 `do_GET/do_POST/do_PUT/do_DELETE` 中以 `path ==` 硬匹配。风险：OK / 死按钮(不可达或占位) / 缺端点 / 契约错位。

## 一、按页面清单

| 页面 | 可点击元素 | handler | API 端点 | 期望字段 | 风险 |
|---|---|---|---|---|---|
| DashboardPage | 刷新/自动轮询 | reload | `GET /api/dashboard` | status/engine/active_model/tri_code/pending_approvals/memory_layers/recent_tasks/recent_events | OK |
| XAIChatPage | 渠道加载、意图识别 | getSettings / classifyIntentAPI | `GET /api/settings`、`POST /api/intent` | {intent,confidence,kernel} | OK |
| XAIManagePage | 状态/记忆/安全 | getStatus / getMemory / getLoopSafety | `/api/status`、`/api/memory`、`/api/loop-safety` | {adapter,core,core_db} | OK |
| SystemDashboard | 刷新 | systemStatus / workflowHistory | `/api/system/status`、`/api/workflow/history` | cpu_percent/memory{}/disk{}/process_count | OK |
| MemoryDashboard | 刷新 | memoryStats | `GET /api/memory/stats` | layers[{count,hit_rate,health,capacity}], summary{total_capacity,avg_hit_rate}, trends,heatmap,funnel,scatter | **契约错位** |
| CanvasPage | 加载/保存/运行/能力 | canvasGet/canvasSave/runWorkflowSSE/getCapabilities | `/api/canvas/{id}`、`/api/canvas/save`、`/api/workflow/run`、`/api/capabilities` | {id,nodes,edges} | OK |
| OrchestratorPage | 运行/保存 | runWorkflowSSE/canvasSave | `/api/workflow/run`、`/api/canvas/save` | — | OK |
| PlanCanvas | 生成计划/保存/运行 | plansList/plansSave/chatComplete/runWorkflowSSE | `/api/plans`、`/api/chat`、`/api/workflow/run` | — | **死按钮**(整页未路由) |
| TasksPage | 新建/编辑/删除/状态/运行 | resource.*('tasks')/runWorkflowSSE | `GET/POST /api/tasks`、`/api/tasks/update`、`/api/tasks/delete` | — | **缺端点** |
| AutomationPage | 新建/编辑/删除/启用/运行 | resource.*('automations')/runAutomation/aiGenerateCron | `/api/automations*`(CRUD)、`/api/automations/run`、`/api/chat` | — | **缺端点**(仅 run 在) |
| SchedulePage | 新建/编辑/删除/开关/运行一次/AI | resource.*('schedules')/runSchedule/aiGenerateCron | `/api/schedules*`(CRUD)、`/api/schedules/run`、`/api/chat` | — | **缺端点**(仅 run 在) |
| TeamPage | 列表/邀请/对话/增删团队 | agentsList/teamInvite/coordChat/resource.*('teams') | `/api/agents`、`/api/team/invite`、`/api/coordination/chat`、`/api/teams*` | — | **缺端点**(teams CRUD) |
| TeamPage | 成员面板 | teamMembers | `GET /api/team` | {members:[...]} | **契约错位**(恒返回 {members:[]}) |
| AgentHubPage | 房间列表/建房间/发消息/读消息 | hubRooms/hubCreate/hubSend/hubMessages/agentsList | `/api/hub/rooms`、`/api/agents`、`/api/hub/rooms/{id}/send`、`/api/hub/rooms/{id}/messages` | {rooms:[...]} | **缺端点**(messages/send) |
| SessionPage | 列表/删除会话 | sessionList / sessionDelete | `GET /api/sessions`、`DELETE /api/sessions/{id}` | — | **缺端点**(DELETE 无路由) |
| ConversationPage | 读消息 | sessionMessages | `GET /api/sessions/{id}/messages` | — | **缺端点**(后端仅 `/api/session/{id}`) |
| SkillManager | 列表/增/改/删/学/导入 | skillList/skillCreate/skillUpdate/skillDelete/skillLearn/skillImport | `/api/skill/*`(全部) | {id,name,description,...} | OK |
| SkillsPage | 列表/添加/学习 | resource.list('skills')/create/learn | `GET /api/skills`、`/api/skills/create`、`/api/skills/learn` | — | OK |
| SkillsPage | 编辑(保存) | `PUT /api/skills/update/${id}` | `/api/skills/update/{id}` | — | **缺端点**(后端为 `/api/skill/update/`) |
| SkillsPage | 删除 | `POST /api/skills/delete {id}` | `/api/skills/delete` | — | **契约错位**(列表项无 id，后端要 {name}) |
| McpManager | 列表/增/改/删/学/导入 | mcpList/mcpCreate/mcpUpdate/mcpDelete/mcpLearn/mcpImport | `/api/mcp/*`(全部) | — | OK |
| ConnectorHubPage | 列表/添加/删除/测试 | resource.list('connectors')/create/delete/test | `/api/connectors`、`/api/connectors/create`、`/api/connectors/delete`、`/api/connectors/test` | {id,status,last_active} | OK(列表) |
| ConnectorHubPage | 删除/测试 | `POST ... {id:c.id}` | `/api/connectors/delete`、`/api/connectors/test` | — | **契约错位**(列表项无 id，后端要 {name}) |
| SettingsPage | 刷新/保存/模型/连接/技能 | getSettings/saveSettings/modelsList/mcpList/skillList | `/api/settings`、`/api/models/list`、`/api/mcp/list`、`/api/skill/list` | — | OK |
| GuardianPanel | 列表/确认 | listApprovals/confirmApproval | `/api/approvals`、`/api/approvals/confirm` | — | OK |
| CognitiveLoopPanel | 加载 | getLoopSafety/getStatus | `/api/loop-safety`、`/api/status` | — | OK |
| AgentPage | 全部按钮 | (无路由引用) | — | — | **死按钮**(整页不可达) |
| Welcome / Editor / NewProjectWizard | 全部按钮 | (无路由引用) | — | — | **死按钮**(整页不可达) |
| ModulePlaceholder | 无 | (占位) | — | — | **死按钮**(多模块回退至此) |
| HistoryPage | 渲染面板 | AgentExecutionHistoryPanel(经 store) | 无直接 /api 调用 | — | OK |

## 二、汇总

**死按钮（不可达/占位）**：5 个整页未被 `App.tsx` switch 引用 → `AgentPage`、`PlanCanvas`、`Welcome`、`Editor`、`NewProjectWizard`；以及 `ModulePlaceholder` 接管的若干未接入模块（所有未匹配 `page` key 的模块回退到此，纯展示 `module.api` 字符串，无任何按钮）。

**缺端点清单**（后端 `do_*` 无对应路由）：
- `GET/POST /api/tasks`、`/api/tasks/update`、`/api/tasks/delete` ← TasksPage
- `GET/POST /api/automations`、`/api/automations/update`、`/api/automations/delete` ← AutomationPage（仅 `/api/automations/run|trigger` 在）
- `GET/POST /api/schedules`、`/api/schedules/update`、`/api/schedules/delete` ← SchedulePage（仅 `/api/schedules/run` 在）
- `GET/POST /api/teams`、`/api/teams/delete` ← TeamPage
- `GET /api/hub/rooms/{id}/messages`、`POST /api/hub/rooms/{id}/send` ← AgentHubPage
- `DELETE /api/sessions/{id}` ← SessionPage（`do_DELETE` 仅处理 mcp/skill）
- `GET /api/sessions/{id}/messages` ← ConversationPage（后端为单数 `/api/session/{id}` 且字段不同）
- `PUT /api/skills/update/{id}` ← SkillsPage（后端仅 `/api/skill/update/`）

**契约错位清单**（端点存在但字段/路径不符）：
- `MemoryDashboard` ← `/api/memory/stats`：后端只回 `layers[{count}]` + `summary{total_memories,last_updated}`，缺 `hit_rate/health/capacity`、`total_capacity/avg_hit_rate` 及 `trends/heatmap/funnel/scatter` → 图表全空。
- `SkillsPage 删除` & `ConnectorHubPage 删除/测试`：列表项无 `id`，前端传 `{id}`（undefined），后端按 `name` 查找 → 操作必失败。
- `TeamPage 成员面板` ← `/api/team`：恒返回 `{members:[]}`，成员列表永远空。
- `ConnectorHubPage`：后端列表不含 `status/last_active`，状态点恒为「inactive」。

**建议**：为 schedules/automations/tasks/teams 补齐通用 CRUD 路由（或改走 `/api/plans` 式专用资源）；为 hub 增加 messages/send 子路由；为 skills/connectors 列表补 `id` 字段并统一 delete/test 入参为 `name`；`/api/memory/stats` 回填可视化所需字段；把 5 个孤页接入路由或移除。
