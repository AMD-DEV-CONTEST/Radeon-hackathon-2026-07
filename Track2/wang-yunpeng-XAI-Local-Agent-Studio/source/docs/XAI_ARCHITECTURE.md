# XAI 控制台 · 架构宪法与接管文档

> 单一自包含文档。其他 AI（或人）读完即可接管本项目，无需额外上下文。
> 最后更新：2026-07-19 · 老大裁定 Route A（OllamaFlow 液态玻璃）为唯一前端底座。

---

## 0. 项目定位（一句话）

**XAI 控制台 = 通用 AI 操作系统中控台**，把两个内核（Hermes 推理 / Grok Build 工程）与一个执行网关（OpenClaw）统一调度，经 localhost:8000 引擎收口，前端是唯一纯视图层。

⚠️ 它**不是量化/股票系统**。股票、TDX、腾讯自股等属于九章北斗/Alpha Factory 项目，与本项目无关——此前出现过上下文污染，已剔除。

---

## 1. 架构宪法（唯一真源，违反须用户签字）

1. **双内核并列**：Hermes（通用推理·GEPA 自进化）+ Grok Build（代码工程·subagent/goal/apply_patch/dream 蒸馏），均为第一类公民，无层级。
2. **Intent Router 仲裁**：任务分类后自动化分发至最优内核（见 §5 `kernel` 字段）。
3. **认知 Control Loop**：Reason → Meta → Runner → L4 Verify → Distill，两核共享。
4. **Guardian 治理闸门**：P0/P1/P2 风险分级 + 二次确认 + 审批队列，覆盖核心引擎层。
5. **7 层元认知记忆（单一事实源）**：所有模块经 memory_core API 写入，带 engine 标签，禁止自建独立向量库。
6. **Substrate 执行网关 = OpenClaw**：工具路由 + 文件/终端/浏览器/MCP 全栈，卡 Guardian 之下。
7. **控制台为纯视图层**：所有业务逻辑在引擎（Python）；UI 能力由内核能力注册表驱动。
8. **前端底座 = `xai-frontend/`**（OllamaFlow 液态玻璃，亮色默认 + 暗色可切换）。`web/`、`frontend/` 已降级/归档，不再维护。

---

## 2. 技术栈

- 后端：Python 3.13，`server_xai.py`（ThreadingHTTPServer，零框架）+ `core/engine_xai.py` 编排引擎 + `core/app_store.py`（任务/专家/自动化/定时/画布数据）。
- 前端：`xai-frontend/` — React 18 + TypeScript + Vite + Tailwind 3 + zustand + framer-motion + @xyflow/react（画布）。亮色液态玻璃默认，暗色可切换（ThemeContext）。
- 数据：SQLite（`~/.xai/workspace/`），JSON 配置。本地闭环，无主动外传。

---

## 3. 目录结构（关键路径）

```
xai/
├── server_xai.py              # 后端 HTTP 服务（:8000），所有 API 入口
├── core/
│   ├── engine_xai.py          # 编排引擎：chat / run_workflow / status / loop_safety
│   ├── app_store.py           # 资源 CRUD（tasks/teams/automations/schedules/canvas）
│   └── cronutil.py            # 定时调度线程
├── xai-frontend/
│   └── src/renderer/
│       ├── App.tsx            # 外壳：Sidebar + ConsoleTopBar + 主区 + LiveStatus + EventStream
│       ├── pages/             # 7 模块页 + PlanCanvas + GuardianPanel + CognitiveLoopPanel + DualKernelPanel
│       ├── store/             # workspace-store / live-store / xai-store（zustand）
│       └── lib/api.ts         # 所有后端调用的唯一封装
├── docs/
│   ├── PROVENANCE.md          # 每模块 GitHub 对标 + REAL/PARTIAL/STUB
│   └── XAI_ARCHITECTURE.md    # 本文件
└── 启动XAI-Web.command        # 一键启动后端+前端并开浏览器
```

---

## 4. 七大模块 → 后端映射（已验证真实接线）

| 模块 | 前端页 | 后端资源 / 端点 | 状态 |
|------|--------|----------------|------|
| 对话 | `XAIChatPage` | `POST /api/chat`（SSE）· `POST /api/intent`（意图+内核） | ✅ |
| 任务 | `TasksPage` | `/api/tasks` · `/update` · `/delete` · `resource.create` | ✅ 本轮补齐 |
| 专家团 | `TeamPage` | `/api/teams` · `/api/agents` | ✅ |
| 自动化 | `AutomationPage` | `/api/automations` · `/run` | ✅ |
| 定时任务 | `SchedulePage` | `/api/schedules` · `/run` + cronutil | ✅ |
| 画布 | `CanvasPage` | `POST /api/workflow/run`（SSE）· 能力注册表 `/api/capabilities` | ✅ |
| 管理 | `XAIManagePage` | `/api/status` · `/loop-safety` · `/memory` · Guardian/认知环/双核面板 | ✅ |

---

## 5. 6 项升级能力（本轮已打通，端点实测 OK）

| 能力 | 端点 / 机制 | 说明 |
|------|------------|------|
| D1 实时事件总线 | `GET /api/events/stream`（SSE）+ 心跳线程 `_event_heartbeat` | 控制室由 EventSource 推送，不再纯轮询 |
| D2 能力注册表驱动 | `GET /api/capabilities`（15 节点） | 画布/PlanCanvas 从它渲染，单一事实源 |
| D3 后端意图置信度 | `POST /api/intent` → `{intent, confidence, kernel}` | `kernel` ∈ hermes/grok_build/openclaw，驱动双核路由 |
| D4 Guardian 二次确认 | 画布 P0 节点运行前弹确认 + `POST /api/approvals/confirm` | 危险操作前端闸门 |
| D5 计划持久化 | `GET/POST /api/plans` | PlanCanvas 按对话落库 |
| D6 认知控制环视图 | `CognitiveLoopPanel`（前端实时视图） | Reason→Meta→Runner→Verify→Distill |

---

## 6. 后端 API 速查（真实存在）

- 状态：`GET /api/status`（即时，心跳快照）· `GET /api/loop-safety` · `GET /api/memory`
- 对话：`POST /api/chat`（SSE 流式）
- 意图：`POST /api/intent` `{text}` → `{intent, confidence, kernel}`
- 画布：`POST /api/workflow/run` `{nodes, edges}`（SSE 逐节点）
- 资源 CRUD：`/api/tasks` `/api/teams` `/api/automations` `/api/schedules`（list/get/create/update/delete，遵循 `resource` 约定）
- 能力：`GET /api/capabilities`
- 事件：`GET /api/events/stream`（SSE）
- 计划：`GET /api/plans` · `POST /api/plans`
- 审批：`GET /api/approvals` · `POST /api/approvals/confirm`
- 其它：`GET /api/models/list` · `GET /api/agents` · `GET /api/open` · `GET /api/settings`

> CORS：`server_xai.py` 已处理 OPTIONS 预检 + `Access-Control-Allow-Origin: *`，浏览器从 :5180 跨域访问 :8000 正常。

---

## 7. 前端关键约定

- **所有后端调用走 `lib/api.ts`**，禁止页面内裸 fetch。
- **主题**：`ThemeContext` defaultMode='light'；暗色切换已支持。
- **控制室外壳**：`ConsoleTopBar`（快速建任务 + 右/底栏开关）+ `LiveStatusPanel`（右 232px）+ `EventStreamDrawer`（底 196px）。窄屏（≤1024px）侧栏收起为图标、右栏变浮层。
- **路由懒加载**：`App.tsx` 用 React.lazy，各页独立分块。
- **新协作形态 PlanCanvas**：对话页右侧画布，需求→生成执行画布→鼠标增删改→apply 回灌对话 / run 直驱后端。

---

## 8. 启动与验证

```bash
# 一键（推荐）
./启动XAI-Web.command
# 或手动
XAI_PORT=8000 XAI_HOST=localhost python3 server_xai.py &   # 后端
cd xai-frontend && npm run dev -- --port 5180 --host        # 前端
```
- 控制台：http://localhost:5180/
- 后端健康：`curl localhost:8000/api/status`（应 <50ms 返回）
- 构建验证：`cd xai-frontend && npm run build`（通过，无类型错误）

> ⚠️ 后端有 stale-PID 保护：重启前先 `rm -f ~/.xai/server.pid` 并 kill 旧进程，否则报"已有实例在运行"。

---

## 9. 已知限制 / 后续待办

- ✅ 已交付：E0 收口、A 布局、B 七模块按钮全通、C 溯源、D 六能力、E9 懒加载、E7 响应式、E2 双核 UI。
- 🟡 待补：E8 本文档（进行中）；双核融合更深的统一调度编排 UI；移动端 PWA；性能进一步代码分割；端到端自动化测试。

---

## 10. 给其他 AI 的接管指引

1. 先读本文件 §1 宪法 + §4/§5 映射，再读 `docs/PROVENANCE.md` 看每块 GitHub 对标。
2. 改前端：只动 `xai-frontend/src/renderer/`，调用一律经 `lib/api.ts`；改完 `npm run build` 验证。
3. 改后端：只动 `server_xai.py` + `core/`，`py_compile` 验证后重启（注意 §8 的 PID 清理）。
4. 任何架构级改动若违背 §1 宪法，**必须先经用户签字**。
5. 新功能按钮必须"人点击有可见反馈"，且后端有真实逻辑（标 fake 的一律视为未完成）。
