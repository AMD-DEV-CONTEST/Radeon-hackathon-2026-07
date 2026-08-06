# XAI 控制台 · 项目移交说明书

> 写给马维斯，或任何新对话。
> 读完本文 + `docs/XAI_ARCHITECTURE.md` 即可完全接管此项目。
> 最后更新：2026-07-19

---

## 一、快速启动

```bash
# 后端（Python 3.13+）
cd /Users/Admin/Desktop/mask/xai && python3 server_xai.py &

# 前端（Node 22+）
cd /Users/Admin/Desktop/mask/xai/xai-frontend && npm run dev -- --port 5180 --host

# 打开
open http://localhost:5180
```

如果报"已有实例在运行"，先：`rm -f ~/.xai/server.pid && pkill -f server_xai.py`

---

## 二、项目结构速览

```
xai/
├── server_xai.py              # 后端 HTTP :8000（ThreadingHTTPServer）
├── core/
│   ├── engine_xai.py          # 编排引擎：chat / workflow / ControlLoop
│   ├── grok_build_engine.py   # Grok Build headless CLI 桥接
│   ├── substrate_port.py      # Port/Adapter 合约层 (v2.0 新)
│   ├── control_loop.py        # 认知控制环 Reason→Meta→Verify
│   ├── distill.py             # GEPA 自进化 / Distiller
│   ├── memory_core.py         # 8 层记忆（SQLite 单一事实源）
│   ├── model_registry.py      # 模型注册（DeepSeek/Ollama/Grok）
│   ├── guardian.py            # P0/P1/P2 治理闸门
│   ├── app_store.py           # 任务/专家/自动化 CRUD
│   ├── kb.py                  # 本地 RAG（词袋+余弦）
│   └── adapters/              # OpenClaw / Hermes / Memory 适配器
├── xai-frontend/
│   └── src/renderer/
│       ├── App.tsx            # 外壳：Sidebar + TopBar + 主区
│       ├── pages/             # 12 个页面（见下方）
│       ├── store/             # zustand：workspace / live / xai-chat
│       ├── lib/api.ts         # 唯一 API 封装（:8000）
│       └── styles/            # 液态玻璃设计系统
├── docs/
│   ├── XAI_ARCHITECTURE.md    # ★ 架构宪法（必读）
│   ├── XAI_BLUEPRINT_v2.0.md  # 蓝图 v2.0 全状态矩阵
│   ├── FRONTEND_BASELINE.md   # 前端 UI 固化基准
│   ├── PROVENANCE.md          # GitHub 对标清单
│   └── SYSTEM_VERIFICATION_2026-07-19.md
├── SYSTEM_OVERVIEW.html       # 自包含架构概览（双击打开，自动刷新）
└── HANDOFF.md                 # 本文件
```

---

## 三、12 个前端页面

| 页面 | 路径 | 状态 | 说明 |
|------|------|------|------|
| 对话 | XAIChatPage | ✅ | SSE 流式 + Grok Build 路由 + 意图预判 |
| 仪表盘 | DashboardPage | ✅ | 引擎/模型/三核/审批 卡片 + 记忆/任务/事件 |
| 任务 | TasksPage | ✅ | 任务 CRUD |
| 专家团 | TeamPage | ✅ | Agent 列表 |
| 技能库 | SkillsPage | ✅ | 3 个种子技能（CRUD） |
| 连接器 | ConnectorHubPage | ✅ | MCP 管理（2 个种子连接器） |
| 自动化 | AutomationPage | ✅ | 自动化配置 |
| 定时任务 | SchedulePage | ✅ | Cron 调度 |
| 画布 | CanvasPage | ✅ | 15 节点 DAG 拖拽（SSE 执行） |
| 编排 | OrchestratorPage | ✅ | 三核可视化编排 |
| 管理 | XAIManagePage | ✅ | Guardian/认知环/双核/模型管理 |
| 设置 | SettingsPage | ✅ | 系统配置 |

---

## 四、核心后端 API（:8000）

| 端点 | 方法 | 说明 |
|------|------|------|
| /api/status | GET | 三核状态（grok_build / hermes / openclaw） |
| /api/chat | POST SSE | 流式对话（意图→Guardian→ControlLoop→执行） |
| /api/intent | POST | 意图分类 + 内核路由 |
| /api/workflow/run | POST SSE | DAG 工作流逐节点执行 |
| /api/capabilities | GET | 15 项能力注册表 |
| /api/dashboard | GET | 仪表盘聚合数据 |
| /api/skills | GET/POST | 技能 CRUD（~/.xai/skills/） |
| /api/connectors | GET/POST | MCP 连接器 CRUD（~/.xai/connectors.json） |
| /api/sessions | GET | 对话历史列表 |
| /api/approvals/confirm | POST | Guardian P0 审批确认 |
| /api/models/list | GET | 模型注册表 |
| /api/loop-safety | GET | 循环安全状态 |

---

## 五、Grok Build 当前状态（重要）

### 已通
- 二进制：`~/.grok/bin/grok`（grok 0.1.220-alpha.4）
- 桥接：`GrokBuildBridge.run(task, extra_flags="")`
- 路由：`code_dev` 意图 → `_execute_code()` → Grok
- 参数修正：`--single task --output-format json`（非 `--single --output-format json task`）
- 行为参数：`--check`（自验证）、`--best-of-n 3`（并行探索）
- 事后记忆：`_reflect_grok_result()` 写入 `memory_core`
- code_dev 关键词：38 个（def/class/import/函数/类/编写/开发/API/架构/数据库/前端/后端...）

### 未通
- 没有 agent/goal/apply/dream 四种分类器（那是之前的错误设计，已删除）
- Grok 只作为一个整体框架调用，内部自规划、自执行、自验证

---

## 六、三核状态颜色约定

| 颜色 | 含义 | 色值 |
|------|------|------|
| 绿色 | 正常运行 | `#22c55e` |
| 灰色 | 未启动/未连接 | `#9ca3af` |
| 红色 | 报错/异常 | `#ef4444` |

---

## 七、未完成项（按优先级）

### P0（核心链路）
- [ ] ControlLoop 完整闭环（当前只做了浅层 reason+meta 包装）

### P1（功能补齐）
- [ ] GEPA 自进化触发机制
- [ ] PlanCanvas 升级为 Generic Thinking Canvas（6 新节点类型）
- [ ] TeamPage 能力组合画布（拖拽技能/工具到 Agent）
- [ ] TasksPage 自动化轻量画布
- [ ] 对话历史前端列表/恢复界面
- [ ] 任务历史视图

### P2（新页面）
- [ ] AgentHub 群聊+看板
- [ ] 记忆可视化页面（8 层水位）
- [ ] 技能库独立页面
- [ ] 工具执行前端可视化（OpenClaw 调用实时显示）

---

## 八、当前运行状态

- 前端 :5180 = HTTP 200 ✅
- 后端 :8000 = HTTP 200 ✅
- Grok Build = available ✅
- Hermes = real v0.18.0 ✅
- OpenClaw = real 2026.6.11 ✅
- 种子数据 = 3 技能 + 2 连接器 ✅
- 前端构建 = npm run build 1.71s 通过 ✅

---

## 九、接管指引

1. **先绑定本地上下文**：读 `docs/XAI_ARCHITECTURE.md`（宪法）+ 本文 §二~§六
2. **前端**：所有页面在 `xai-frontend/src/renderer/pages/`，路由在 `App.tsx`
3. **后端**：所有 API 在 `server_xai.py`，编排逻辑在 `core/engine_xai.py`
4. **样式**：液态玻璃设计系统在 `styles/liquid-glass.css`（CSS 变量），禁止硬编码色值
5. **API 调用**：前端所有调用走 `lib/api.ts`，禁止页面内裸 fetch
6. **改完前端**：`npm run build` 验证（必须通过）
7. **改完后端**：重启前先 `rm -f ~/.xai/server.pid`
8. **系统概览**：双击 `SYSTEM_OVERVIEW.html` 查看架构全景（自动 15 秒刷新三核状态）
