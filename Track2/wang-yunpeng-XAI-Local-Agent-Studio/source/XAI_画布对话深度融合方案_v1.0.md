# XAI 画布 × 对话深度融合方案 v1.0

> 日期：2026-07-26 | 触发：老大"先 C 后 B"决策
> 原则：不破坏 App.tsx 布局 / 左侧导航 / 配色 / 玻璃规范 / 亮暗双主题

---

## 一、现状盘点（Multica 对标后的差距）

| 维度 | XAI 现状 | Multica 做得好的 | 差距 |
|------|---------|-----------------|------|
| **任务生命周期** | 画布节点无状态（纯 static 图形） | Issue 流转：Backlog→Todo→In Progress→In Review→Done | 🔴 核心差距 |
| **Agent 可分配** | 无法把节点"分配"给 Agent 执行 | 一个下拉框分配 Agent，WebSocket 实时跟踪 | 🔴 |
| **执行可视化** | 无（GrokConsole 有 running/done 但不在画布上） | 看板上任务状态实时变色 + 进度时间线 | 🔴 |
| **技能积累** | 8 层记忆有，但无 skill 专用层 | frontmatter based skill packages，随使用复合增长 | 🟡 记忆层可用但未对接 |
| **定时自动化** | GEPA scheduler 有，但未接画布 | Autopilots：cron→创建 Issue→分配 Agent→自动执行 | 🟡 scheduler 现货 |
| **看板视图** | 无（仅 DAG 连线图） | Kanban 三列（Todo/Doing/Done）+ 筛选过滤 | 🔴 |
| **对话↔任务闭环** | DemoCanvas 有"同步到画布"但 ChatConsole 隐式 | 从 Issue 打开对话、从对话创建 Issue 双向自然 | 🟡 单向 |
| **执行审批** | Guardian 有（但只接 Grok write） | 无（靠 Agent 自身判断） | 🟢 XAI 更强 |

---

## 二、融合设计：四维升级

### 2.1 画布节点 → 可执行任务（核心变更）

**现状**：画布节点是纯图形，`data: { label, nodeType }`，无生命周期。

**目标**：每个节点 = 一个可执行任务，有状态、可分配、可跟踪。

```
节点 data 结构升级：
{
  label: "搜索云南GDP",
  nodeType: "tool",
  status: "idle",          // idle | pending | running | done | failed
  assignee: null,           // "hermes" | "grok_build" | "openclaw" | null
  tool: "search",           // ToolBus 工具名
  args: { query: "云南GDP" },
  result: null,             // 执行结果
  logs: [],                 // 执行日志
  tokenUsage: null,         // Token 消耗
  createdAt: 1751432600,
  updatedAt: null,
}
```

**视觉**：节点边框颜色随 status 变化（idle=灰 / pending=蓝 / running=琥珀 pulse / done=绿 / failed=红），不动整体配色令牌。

### 2.2 看板模式（画布双视图）

**MiniCanvas 新增 prop**：`viewMode: "dag" | "kanban"`

| 模式 | 用途 | 渲染 |
|------|------|------|
| DAG（默认） | 编辑工作流、连线编排、拖入节点 | 现有 ReactFlow，不动 |
| Kanban | 查看任务泳道、拖拽改状态、执行监控 | 新增：三列布局（Todo/Doing/Done），节点卡片可拖拽跨列 |

**切换按钮**：画布标题栏新增「DAG / 看板」toggle（两个 pill 按钮，走现有 glass-* 规范）。

**Kanban 卡片设计**：
- 标签 + 类型图标（左上）
- 状态角标（右上，用现有 --color-accent 等语义色）
- assignee 名称小字（左下）
- tokenUsage 小字（右下，Phase 0 已落地）
- 点击 → 右侧滑出 NodeConfigPanel（Phase 0 已有，复用）

### 2.3 对话 → 看板（双向闭环）

**① 对话 → 看板（同步到画布升级）**

现有：ChatConsole AI 消息下"同步到画布"→ 创建静态 text 节点。

升级为：
```
AI 消息「📌 转为任务」
  → 自动解析内容提取 type/tool/args
  → ChatConsole 侧弹 mini 表单预览（可手动修正）
  → 确认 → 创建画布节点，status=pending，自动入看板 Todo 列
  → 对话区提示「已创建任务 [搜索云南GDP]，待执行」
```

**② 看板 → 对话**

节点右键"加入对话"→ 节点的完整上下文（type/tool/args/result/logs）注入到下一条用户消息的 system prompt → AI 能看到你正在处理哪个任务。

**③ AI 主动布局升级**

现有的 `/api/canvas/validate?description` 已支持 LLM→DAG 生成。ChatConsole 对话中 AI 检测到"帮我做一个 XX 流程"→ 自动调 validate → DAG 直接落到画布（不再需要用户手动点"同步到画布"）。

### 2.4 节点执行引擎（核心新能力）

**新增** `core/canvas/executor.py` + `POST /api/canvas/execute`（SSE 流式推送执行进度）

```
执行流程：
1. 用户右键节点 → "运行此节点"
2. POST /api/canvas/execute { nodeId, session }
3. 后端：
   a. load 节点 data → 解析 type/tool/args
   b. Guardian 分类（P0/P1/P2）→ P0/P1 弹审批工单
   c. 更新 status → "running"（SSE push 给前端画布）
   d. 通过 ToolBus 调用真实工具：
      - tool/search → web_search(query)
      - tool/exec → openclaw.execute(...)
      - agent → engine._infer_with_fallback(prompt)
      - memory → memory_core.add/search
      - grok → grok_build.run(task)
   e. 捕获 result + usage → 更新节点 data
   f. status → "done"（SSE push）
   g. engine.record_backend_usage(source="canvas_execute")（Phase 0 已就绪）
```

**节点状态动画**：运行时节点边框 pulse 动画（CSS `@keyframes` 走 `effects.css` 已有体系，不动设计令牌）。边也可显示数据流方向（running 时箭头亮）。

### 2.5 技能积累（新记忆层）

**新增记忆层** `skill`（8 层记忆第 9 个 slot，或在 memory_core 新增 skill 层）

```
节点执行成功 → 提示「保存为技能？」→ YES →
  memory_core.add("skill", key=node.tool, value=JSON.stringify({
    task: node.data.task,
    solution: node.data.result,
    usage: node.data.tokenUsage,
    timestamp: ...
  }))
```

后续同类任务 → ChatConsole 对话中 `@记忆:skill` 自动检索相关技能 → AI 直接引用。

---

## 三、前端改动清单（逐项过铁律）

| 改动 | 位置 | 铁律合规 |
|------|------|----------|
| MiniCanvas 加 `viewMode` prop + Kanban 渲染分支 | MiniCanvas.tsx | ✅ 不改布局，组件内部叠加 |
| 画布标题栏加「DAG / 看板」toggle pills | ChatConsole.tsx 画布 header | ✅ 不改 App.tsx/Sidebar/Header |
| 节点 status 着色（border-left 颜色随状态变） | MiniCanvas.tsx 节点 style | ✅ 用现有语义色（var(--color-*)），不造 token |
| 右键菜单加「运行此节点」+「加入对话」 | MiniCanvas.tsx 右键菜单 | ✅ 菜单现有，加 item |
| ChatConsole AI 消息「📌 转为任务」升级 | ChatConsole.tsx 消息操作栏 | ✅ 按钮已有，改行为 |
| 节点执行 pulse 动画 | effects.css | ✅ 不碰 glass-*/theme.css/theme-context |
| Kanban 卡片渲染组件（纯 CSS，零新依赖） | MiniCanvas.tsx 内部组件 | ✅ 走现有颜色变量 |
| 节点执行进度 SSE 流接收 | ChatConsole.tsx useEffect | ✅ 对话 SSE 基础设施复用 |

**汇总**：所有改动都在 MiniCanvas.tsx + ChatConsole.tsx 两个文件内部叠加。**不碰** App.tsx / LeftSidebar / AppHeader / glass-*.css / theme.css / theme-context.tsx。

---

## 四、后端改动清单

| 新增 | 位置 | 性质 |
|------|------|------|
| `core/canvas/executor.py` | 节点执行引擎（拓扑执行 + Guardian 门 + ToolBus 分发 + SSE 推送） | 新文件 |
| `POST /api/canvas/execute` | SSE 流式执行 | 加到 server_routes_canvas.py |
| `POST /api/canvas/save` 支持 status 字段 | 已有路由，无需改动 | 已有 |
| 记忆层 `skill` slot | memory_core 加一层 | 小改动 |

---

## 五、Phase 路线

| 阶段 | 内容 | 时间 | 依赖 |
|------|------|------|------|
| **P0.5**（即刻） | Multica 部署 → 亲身体验 → 确认手感 | 1h | Docker 拉镜像中 |
| **P1**（2天） | 画布节点状态系统 + Kanban 视图 + 节点执行引擎 + 对话↔看板闭环 | 2天 | P0 画布基建已完成 |
| **P2**（1.5天） | 技能积累（skill 记忆层）+ Autopilot（scheduler 接画布）+ AI 主动布局 UI 化 | 1.5天 | P1 |
| **P3**（按需） | Conditional/Loop 节点 + 多节点级联执行 + DAG 批量跑 | — | P2 |

---

## 六、关键设计决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 看板 vs DAG：互斥还是共存？ | **共存**，toggle 切换 | DAG 适合编排，Kanban 适合跟踪——两个场景都需要，不互相替代 |
| 节点执行：单节点还是全 DAG？ | **先单节点**（P1），P3 再全 DAG | 全 DAG 需要条件分支+循环——Multica 也没有全自动化 DAG，它是单 Issue→单 Agent |
| 技能存储：独立表还是复用记忆？ | **复用 8 层记忆**（加 skill 层） | XAI 铁律坚持 SQLite 单数据库，不另起炉灶 |
| 是否引入 Multica 的 WebSocket？ | **不引入**，用现有 SSE | SSE 已覆盖 ChatConsole + canvas validate，执行状态推送复用同一基础设施 |
