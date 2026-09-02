---
AIGC:
    Label: "1"
    ContentProducer: 001191440300708461136T1XGW3
    ProduceID: 42a94a45815d4753c46a791703eadf62_3f7b4305838411f180b3525400bff409
    ReservedCode1: m871r9Z38u5u+ssbibO7iEie9ln1z55L8LkLR0DqB78cEq8dv63Xxie71YsotYD99WWnns4TkY1qFK0XBlqi9FCXKkkerXvKYnrlVb4m17x4VD8xjLR00KZ6OxN4cdaZbmo8JqUrS2M3G7m9KqFE31R44LxxtmZ/MrdWX4rp9TB4pD5vqiyjj8sOT1o=
    ContentPropagator: 001191440300708461136T1XGW3
    PropagateID: 42a94a45815d4753c46a791703eadf62_3f7b4305838411f180b3525400bff409
    ReservedCode2: m871r9Z38u5u+ssbibO7iEie9ln1z55L8LkLR0DqB78cEq8dv63Xxie71YsotYD99WWnns4TkY1qFK0XBlqi9FCXKkkerXvKYnrlVb4m17x4VD8xjLR00KZ6OxN4cdaZbmo8JqUrS2M3G7m9KqFE31R44LxxtmZ/MrdWX4rp9TB4pD5vqiyjj8sOT1o=
---

# XAI 接管深度评估报告

> 编写日期：2026-07-19
> 编写者：AI 接管评估（Marvis）
> 用途：向原开发者移交当前状态、发现的问题、未决事项及下一步建议

---

## 一、接手以来已完成的工作

### 1.1 V2 架构设计（未执行重构）

**产出物**：`docs/ARCHITECTURE_V2.md`

基于 V1 `engine_xai.py`（1692 行上帝类）分析，设计了六边形架构方案：
- 核心契约定义：IR 类型系统 / NodeRegistry / Executor / Planner
- 数据流重定义：ChatService → WorkflowExecutor → LLMAdapter
- V1→V2 迁移策略：P0-P3 分 8 阶段，每阶段独立可验证

**注意**：此设计仅作为架构视角参考，**未对代码执行实质性重构**。用户明确表示 Agent 不具备吸收全部工程上下文的深度，不应大规模重构。

### 1.2 三份报告交叉审计 → 25 项真实问题清单

对以下三份报告做了交叉比对与去重：
| 文件 | 日期 | 来源 | 条目数 |
|------|------|------|--------|
| `AUDIT_REPORT.md` | 7/18 | 设计蓝图自检 | 41 项 |
| `docs/audit_20260719.md` | 7/19 | 代码级审计 | 若干 |
| `docs/test_report_final_20260719.html` | 7/19 | 端到端 66 项测试 | 通过 58 项 |

合并去重后，确认 **25 项真实缺口**（P0: 3 / P1: 9 / P2: 11 / P3: 2）。

### 1.3 三波并行修复（18 项已修）

#### 第一波：环境 + 前端（6 项）
| 编号 | 问题 | 修复位置 | 修复内容 |
|------|------|----------|----------|
| #7 | `/loop` 命令崩溃 | `app.js` | ControlLoop 方法名修正 |
| #9 | 群聊治理 Action 字段不匹配 | `app.js` | 接线修正 |
| #10 | 拓扑 Tab SVG 空白 | `app.js` | SVG 渲染修复 |
| #16 | SkillsPage 缺少 edit/learn 按钮 | `SkillsPage` | 补 UI 按钮 |
| #17 | HistoryPage 未注册路由 | `App.tsx` | 路由注册 |
| #22 | psutil 未安装 | `pip install psutil` | 依赖补装 |

#### 第二波：engine_xai.py 后端（5 项）
| 编号 | 问题 | 修复位置 | 修复内容 |
|------|------|----------|----------|
| #5 | `_retrieve_memory_context` 5 处异常吞噬 | `engine_xai.py` | 加 try/except 日志 |
| #6 | `_cmd_approve` 硬编码 session `"pending"` | `engine_xai.py` | 改为动态查找 |
| #7 | LoopSafety 闸门未接线 | `engine_xai.py` | 接线 `_guard_for_coordination()` |
| #8 | 环路检测回归 | `engine_xai.py` | 调用修复 |
| #9 | MemoryAdapter 无线程安全 | `memory.py` | 加 `threading.Lock` |

#### 第三波：server_xai.py + API（6 项）
| 编号 | 问题 | 修复位置 | 修复内容 |
|------|------|----------|----------|
| #1 | 非流式 API 只等 answer 不等 token | `server_xai.py` | 补 token 拼接 |
| #2 | `"".join` 字符串拼接 | `server_xai.py` | 修正 |
| #3 | 路径穿越 `ext` 参数净化 | `server_xai.py` | 加校验 |
| #4 | `/health` 端点缺失 | `server_xai.py` | 新增 |
| #5 | `/memory` 端点缺失 | `server_xai.py` | 新增 |
| #6 | 前端 API 封装不一致 | `api.ts` | 修正 |

### 1.4 三跳过项 + 四剩余项的原因说明

| 编号 | 问题 | 原因 |
|------|------|------|
| #22 psutil | 上次升级已附带 |
| #23 环路检测 | 上次升级已修 |
| #25 _cmd_approve | 修复二中已修 |

**剩余 4 项**：模型切换 / 记忆双轨 / Project 隔离 / XAI.app 启动——均涉及模块间数据流重构，非单文件热修，需要深入设计。

---

## 二、剩余 4 项深度评估

### #6 模型切换假生效 —— P1

**根因**：`_rebuild_backend()` 只替换 `self._backend`，未通知已持有旧引用的 HermesAdapter。

```python
# __init__
self.hermes = HermesAdapter(..., model_backend=self._backend, ...)

# _rebuild_backend
self._backend = DeepSeekBackend(...)   # ✅ 替换
# ❌ self.hermes._backend 仍指向旧对象
```

**修改计划**：将 HermesAdapter 改为不持有 `_backend` 引用，每次推理时从引擎拉取（拉模式），实现单一事实源。

**影响面**：`HermesAdapter` 构造函数 + 2 处 `_backend` 使用点。风险低，改动聚焦。

---

### #11 记忆双轨写入 —— P0

**根因**：MemoryCore（8 层记忆）+ SessionStore（会话历史）各自独立写入，无统一召回层。

**影响**：用户查询"我之前说过什么"时，两套系统可能返回不一致甚至冲突的结果。

**修改计划**（三级递进）：

| 级别 | 做法 | 工时 |
|------|------|------|
| L1 止血 | `_recall()` 同时查两个源，按时间戳合并去重，标注来源 | 0.5h |
| L2 对齐 | 定义 `MemoryStore` 统一接口，SessionStore + MemoryCore 实现同一接口 | 2h |
| L3 根治 | MemoryCore 内嵌 SessionStore 作为 L0 原文快照层，不再双轨 | 4h |

**建议**：先 L1 止血，L2 列入下一轮重构。

---

### #12 Project 隔离 —— P1

**根因**：`project_manager` 已实例化（`core/project.py`，164 行），但 `engine_xai.py` 中**从未调用**。会话/记忆/工作区全部使用全局路径，无 Project 维度隔离。

```python
# 已建但未接线
self.project_manager = default_project_manager()  # 164行的project.py从未被引用
self._sessions = SessionStore(self._mh)             # 全局
self.memory_core = default_memory_core()            # 全局
```

**修改计划**：打通链路 `请求 → 获取 project_id → 注入隔离前缀`

**依赖**：需要前端 Project 选择器将 `project_id` 传入后端。若暂无前端 UI，至少需要 CLI 命令 `/project switch <name>`。

**工时**：2h（后端接线） + 2h（前端 Project 选择器）。

---

### #14 XAI.app 双击假启动 —— P0

**根因**（推测）：`.app` 捆绑包的 `MacOS` 启动脚本路径解析错误。双击时 CWD 不是项目根目录，导致相对路径引用失败。

**修改计划**：排查 `.app` 包结构：

```bash
# 待排查
cat XAI.app/Contents/Info.plist
ls -la XAI.app/Contents/MacOS/
```

修复：在启动脚本开头强制切换到绝对路径的项目根目录。

**工时**：0.5h。

---

## 三、三跳过项的根治评估

### ModelRouterPage（跳过理由：Settings 已够用）

**根因视角**：问题不是页面缺失，而是**模型路由入口碎片化**——Settings 下拉框、`/models` 命令、编排面板各自操作同一 `model_registry`，但 UI 状态不同步。

**根治方案**：不做独立页面，改为将模型选择抽离为可复用 `ModelSelector` 组件，Settings / 对话输入框 / 编排面板 三处嵌入同一组件，状态通过 `model_registry` 同步。

**操作**：删除 ModelRouterPage 独立路由，改为组件化。

---

### 环路检测回归（跳过理由：上次升级已修）

**根治方案**：补全回归测试覆盖：

```
场景 1: 正常对话 20 轮 → 不应触发
场景 2: 3 轮近似重复 → 不应误杀
场景 3: 5 轮连续相同 → 应触发告警
场景 4: 协调模式 → _guard_for_coordination 应跳过
```

输出文件：`core/test_loop_safety_regression.py`。

---

### _cmd_approve 硬编码（跳过理由：已修）

当前的修复是"改为动态查找"。根治还需进一步：审批流程应可配置——白名单模式，用户在 Settings 中设置"允许自动执行的操作类型"。

---

## 四、双核编排面板 —— 最大断裂发现

### 4.1 前端状态

`OrchestratorPage.tsx`（422 行）实现了完整的前端可视化：
- ReactFlow 画布 + 20+ 语义节点类型 + 5 色内核着色
- 3 套预设模板（代码生成/调研报告/自动化定时）
- 节点拖拽 + 点击添加 + 端口连线
- 运行/保存/清空按钮 + 右侧执行日志面板
- SSE 流式执行（`runWorkflowSSE`）

### 4.2 后端状态

`core/orchestrator.py`（81 行）：仅定义了 `Node` + `Graph` + `Orchestrator` 三个类，实现了拓扑排序和两种运行模式（pipeline/collaborative）。

**关键断裂**：
1. `orchestrator.py` 中的 `Orchestrator` 类**从未被 `server_xai.py` 实例化或调用**——没有对应的 API 端点
2. 前端有 20+ 种语义节点（`canvas-nodes.ts`），后端 `Node.kind` 只有 8 种（agent/model/skill/mcp/kb/human/reflect/code/branch）——类型体系不对齐
3. 前端的"保存"按钮调用 `canvasSave`，但后端没有画布持久化逻辑
4. **"运行"按钮点下去会失败**，因为 `runWorkflowSSE` 调用的 API 端点不存在或未接线

### 4.3 视觉与交互评估

| 维度 | 评分 | 说明 |
|------|------|------|
| 布局结构 | 合格 | 三栏（240 / flex / 280），逻辑清晰 |
| 内核着色 | 优秀 | 5 色体系（橙/蓝/紫/绿/灰），一致性高 |
| 节点卡片 | 良好 | 图标 + 标签 + 内核归属，信息完整 |
| 拖拽方式 | 可改进 | 节点库是 click-to-add，非真正的 drag-to-canvas |
| 连线 | 合格 | ReactFlow 原生端口拖拽连线 |
| 响应式 | 缺失 | 固定宽度，小屏无折叠 |
| 深色模式 | 通过 | CSS 变量，自动跟随 |

### 4.4 与其他拖拽的一致性

系统内现有的拖拽场景（CanvasPage 15 节点 DAG）使用 `ReactFlow`，OrchestratorPage 同样使用 `@xyflow/react`（ReactFlow v12），技术栈一致。但：
- CanvasPage 后端有对应 `/api/workflow/run` 端点
- OrchestratorPage 后端无对应端点——**空壳**

---

## 五、整体框架与下一步思路

### 5.1 当前架构全貌

```
server_xai.py (2012行, 所有API)
    │
    ├── engine_xai.py (1692行, 编排引擎, 上帝类)
    │       ├── model_registry   (模型管理)
    │       ├── memory_core      (8层记忆)
    │       ├── memory.py        (MemoryAdapter + 会话)
    │       ├── project.py       (Project管理, 未接线)
    │       ├── provider_fallback (故障轮换)
    │       ├── loop_safety      (循环安全)
    │       ├── planner / verifier (V4认知)
    │       ├── action_bus       (V4执行总线)
    │       ├── orchestrator     (编排引擎, 未接线)
    │       ├── runner           (超长任务, 未接线)
    │       ├── intent_router    (意图路由)
    │       ├── openclaw_gateway (执行网关)
    │       └── grok_build_engine (Grok CLI桥接)
    │
    └── xai-frontend (React + Vite)
            └── pages/
                ├── OrchestratorPage  (编排, 后端未接线)
                ├── CanvasPage        (画布, 15节点DAG)
                ├── XAIChatPage       (对话, 核心)
                ├── DashboardPage     (仪表盘)
                ├── DualKernelPanel   (三核状态)
                └── ... (共 29 页面组件)
```

### 5.2 问题优先级矩阵

| 优先级 | 编号 | 问题 | 影响 | 工时 | 依赖 |
|--------|------|------|------|------|------|
| **P0** | #11 | 记忆双轨写入 | 数据不一致 | 0.5h (L1) | 无 |
| **P0** | #14 | XAI.app 假启动 | 用户无法使用 | 0.5h | 无 |
| **P1** | 编排 | 编排面板后端接线 | 核心功能空壳 | 2h | #6 后 |
| **P1** | #6 | 模型切换假生效 | 切换后仍用旧模型 | 1h | 无 |
| **P1** | #12 | Project 隔离 | 所有项目共存储 | 2h+2h | 需前端 |
| **P2** | 模型 | ModelRouterPage 入口碎片化 | UX 分裂 | 1h | 无 |
| **P2** | 环路 | 环路检测回归测试 | 无测试覆盖 | 0.5h | 无 |
| **P2** | 审批 | _cmd_approve 白名单 | 审批流不可配 | 0.5h | 无 |

### 5.3 建议执行顺序

```
第 1 天：止血（P0）
  [1] #11 记忆双轨 L1 止血（0.5h）
  [2] #14 XAI.app 启动排查（0.5h）
  ── 以上可并行 ──

第 2 天：核心链路（P1）
  [3] #6 模型切换拉模式修复（1h）
  [4] 编排面板后端接线（2h）—— 依赖 #6 完成后验证
  ── 以上顺序执行 ──

第 3 天：补齐（P1/P2）
  [5] #12 Project 隔离后端接线（2h）
  [6] ModelRouterPage 组件化（1h）
  [7] 环路检测回归测试（0.5h）
  [8] _cmd_approve 白名单化（0.5h）
  ── 以上可部分并行 ──
```

---

## 六、未决问题 & 需原开发者确认的事项

### 6.1 阻塞性问题

1. **编排面板的 API 端点**：后端 `orchestrator.py` 从未被调用，`/api/workflow/run` 是否可复用？还是需要新建 `/api/orchestrator/run` 端点？前端的 `runWorkflowSSE` 期望接收什么格式的 SSE 事件？

2. **XAI.app 打包**：`.app` 包是通过什么方式打包的？`py2app` / `Electron` / 手动装配？启动脚本在哪？

3. **Project 隔离的范围**：设计意图中 Project 隔离粒度是什么——仅隔离会话（sessions），还是也包括记忆（memory）和文件（workspace）？

### 6.2 设计意图确认

4. **编排面板 vs CanvasPage 的定位差异**：这两个面板都做 DAG 编排，节点类型完全不同（一个 20+ 语义节点，一个 15 技术节点）。它们的预期使用场景有何不同？是否应该合并？

5. **记忆系统演进方向**：MemoryCore 已有 8 层设计（`memory_core.py`），但 engine_xai.py 中还保留了一个独立的 `memory.py`（MemoryAdapter）。最终目标是完全下线 `memory.py` 只保留 `memory_core.py`，还是两者共存（一个做结构化存储，一个做快速适配）？

6. **模型切换的预期行为**：切换模型后，是否需要重建整个 backend 实例（当前方案），还是仅替换 API key/model name 参数？如果是后者，不需要 `_rebuild_backend` 这种重量级操作。

### 6.3 代码设计的开放性疑问

7. **`engine_xai.py` 的边界**：当前 1692 行，V2 蓝图规划了拆分路径（抽离 IR / Registry / Executor / Planner），但会引入模块间引用断裂风险（如 #12 就是典型案例）。原开发者认为 `engine_xai.py` 的合理体量是多少？是否接受继续追加功能而非拆分？

8. **DualKernelPanel vs OrchestratorPage**：前者是只读三核状态面板（88 行），后者是可交互编排画布（422 行），两个文件都渲染"双核"相关内容。是否有计划统一？

---

## 七、附录：修改文件列表

### 已修改文件

| 文件 | 修改内容 | 行数变化 |
|------|----------|----------|
| `web/app.js` | 斜杠命令/群聊/拓扑/HistoryPage 修复 | +30 |
| `core/engine_xai.py` | 记忆日志/审批/闸门接线/环路修复 | +25 |
| `core/memory.py` | threading.Lock 线程安全 | +8 |
| `server_xai.py` | token拼接/路径净化/health+memory端点 | +45 |
| `xai-frontend/src/.../api.ts` | API 封装修正 | +10 |
| `xai-frontend/src/.../SkillsPage.tsx` | edit/learn 按钮 | +15 |
| `xai-frontend/src/.../App.tsx` | HistoryPage 路由 | +5 |

### 待修改文件（本评估建议）

| 文件 | 计划修改 |
|------|----------|
| `core/engine_xai.py` | #6 模型切换拉模式 / #11 L1 止血 |
| `core/orchestrator.py` | 对接到 server_xai.py |
| `server_xai.py` | 新增 `/api/orchestrator/*` 端点 |
| `XAI.app/Contents/*` | #14 启动脚本修复 |
| `core/memory.py` | 统一召回层 |
| `core/project.py` | 接入执行流程 |

---

> 备份文件：`/Users/Admin/Desktop/mask/xai_backup_20260719_230223.tar.gz`（45MB）
*（内容由AI生成，仅供参考）*
