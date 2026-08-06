# XAI Kernel V4.0 Architecture Reference

**版本**: V4.0 Architecture Consolidation Release  
**生成日期**: 2026-07-18  
**状态**: Phase 0 架构冻结  
**基准文档**: XAI_Kernel_V4_Architecture_Consolidation_Manual.md / XAI_Kernel_V4_Final_Execution_Manual.md  

---

## 1. 系统架构图

```
                                      ┌─────────────────────────────────────────────┐
                                      │              User / 控制台 (web/)            │
                                      │   对话 chat │ 画布 canvas │ 群聊 room │ 设置  │
                                      └──────────────────────┬──────────────────────┘
                                                             │ HTTP / SSE (localhost:8000)
                                ┌────────────────────────────┴────────────────────────────┐
                                │                    server_xai.py                       │
                                │              (ThreadingHTTPServer · 瘦入口)              │
                                └────────────────────────────┬────────────────────────────┘
                                                             │
        ┌────────────────────────────────────────────────────┴───────────────────────────────────────────────────┐
        │                           kernel/engine.py  (唯一引擎入口)                                              │
        │                                                                                                        │
        │   User Input ──► IntentRouter ──► Planner ──► ControlLoop ──► Guardian ──► ActionBus ──► Executor      │
        │                                           │                                        │                   │
        │                                           ▼                                        ▼                   │
        │                                      Verifier                                 Verifier                │
        │                                           │                                        │                   │
        │                                           └──────────────┬─────────────────────────┘                   │
        │                                                          ▼                                             │
        │                                                     MemoryCore                                         │
        │                                                          │                                             │
        │                                                          ▼                                             │
        │                                                   Evolution Engine                                     │
        └────────────────────────────────────────────────────────────────────────────────────────────────────────┘
                                                             │
        ┌────────────────────────────────┬───────────────────┼───────────────────┬────────────────────────────────┐
        │                                │                   │                   │                                │
        ▼                                ▼                   │                   ▼                                ▼
┌───────────────────┐    ┌───────────────────────┐           │    ┌───────────────────────┐    ┌───────────────────────┐
│   Hermes Agent    │    │   Grok Build Agent    │           │    │   Reviewer Agent      │    │   Model Gateway       │
│   (Reasoning)     │    │   (Engineering)       │           │    │   (Quality/Risk)      │    │                       │
│                   │    │                       │           │    │                       │    │  Router → Local/Ollama│
│   · 任务理解      │    │   · 编码              │           │    │   · 质量验证           │    │         → Cloud(GPT/  │
│   · 推理          │    │   · 文件操作          │           │    │   · 风险检查           │    │           Claude/     │
│   · 规划          │    │   · 工程修改          │           │    │   · 安全审计           │    │           DeepSeek)  │
│   · 研究          │    │   · 测试执行          │           │    │                       │    │                       │
│   · 决策          │    │                       │           │    │                       │    │                       │
└───────────────────┘    └───────────────────────┘           │    └───────────────────────┘    └───────────────────────┘
                                                             │
        ┌────────────────────────────────────────────────────┴────────────────────────────────────────────────────┐
        │                                         MemoryCore (单一事实源)                                          │
        │                                                                                                         │
        │   ┌─────────────┐  ┌──────────────┐  ┌──────────────┐  ┌─────────────┐  ┌──────────────┐  ┌────────────┐│
        │   │ Working     │  │ Episodic     │  │ Semantic     │  │ Skill       │  │ Failure      │  │ User       ││
        │   │ Memory      │  │ Memory       │  │ Memory       │  │ Memory      │  │ Memory       │  │ Profile    ││
        │   └─────────────┘  └──────────────┘  └──────────────┘  └─────────────┘  └──────────────┘  └────────────┘│
        └─────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### 执行链（完整生命周期）

```
User Input
    │
    ▼
[IntentRouter] ── 5 类意图分类 (code_dev/office/automation/research/general)
    │
    ▼
[Task Planner] ── 目标 → 步骤 → Agent 分配 → 复杂度评分 (0-100)
    │
    ▼
[Control Loop] ── 简单任务(0-30): 快速回答 ── 复杂任务(70+): 完整 Loop
    │
    ▼
[Guardian] ── P0 拦截 / P1 记录 / P2 放行
    │
    ▼
[ActionBus] ── 统一动作入口 → Guardian → Executor
    │
    ▼
[Executor] ── 文件/命令/网络/模型/Agent 调度
    │
    ▼
[Verifier] ── 目标完成度 / 输出质量 / 安全风险 / 逻辑错误 → Pass / Retry
    │
    ▼
[MemoryCore] ── 工作记忆 → 长期记忆 → 失败记忆 → 固化
    │
    ▼
[Evolution] ── 失败分析 → Skill 生成 → 测试 → 上线
```

---

## 2. Dual-Kernel 双核心设计

### 原则三：双核心平等协作

```
                  Task
                    |
             Intent Router
             /          \
         Hermes        Grok Build
       Reasoning       Engineering
             \          /
               Reviewer
                    |
                 Memory
```

### Hermes (通用推理)

| 职责 | 描述 |
|------|------|
| 任务理解 | 解析用户意图，分析任务上下文 |
| 推理 | 多轨迹思考 (multi_trajectory)，thinking_protocol |
| 规划 | 目标拆解，步骤生成，Agent 分配 |
| 研究 | 联网搜索，资料分析，报告生成 |
| 决策 | Brier 置信度校准，L8 审计 |

### Grok Build (代码工程)

| 职责 | 描述 |
|------|------|
| 编码 | 生成/修改代码文件 |
| 文件操作 | 读写/删除/移动文件 |
| 工程修改 | 重构、补丁、Git 操作 |
| 测试执行 | 运行测试，验证代码正确性 |

### Reviewer (质量验证)

| 职责 | 描述 |
|------|------|
| 质量验证 | 检查输出质量、正确性 |
| 风险检查 | 评估代码/文档安全风险 |
| 一致性检查 | 确保 Hermes 和 Grok 输出一致 |

---

## 3. V4 目录结构

```
xai/
├── server_xai.py                      # 瘦入口 (~20行) 
│
├── core/
│   ├── kernel/                        # 内核层
│   │   ├── __init__.py
│   │   ├── engine.py                  # 唯一引擎入口
│   │   ├── lifecycle.py               # 生命周期 + HTTP + SSE
│   │   └── event_bus.py               # 事件总线
│   │
│   ├── cognition/                     # 认知层
│   │   ├── __init__.py
│   │   ├── intent_router.py           # 意图路由
│   │   ├── planner.py                 # 任务规划器 [NEW]
│   │   ├── reasoner.py                # 思考增强
│   │   └── verifier.py                # 验证器 [NEW]
│   │
│   ├── agents/                        # 智能体层
│   │   ├── __init__.py
│   │   ├── agent_registry.py          # Agent 注册表 [NEW]
│   │   ├── hermes_agent.py            # Hermes 推理 Agent
│   │   ├── grok_agent.py              # Grok 工程 Agent
│   │   └── reviewer_agent.py          # 评审 Agent [NEW]
│   │
│   ├── execution/                     # 执行层
│   │   ├── __init__.py
│   │   ├── executor.py                # 动作执行器
│   │   ├── action_bus.py              # 统一动作总线 [NEW]
│   │   └── tools.py                   # 工具注册/实现
│   │
│   ├── memory/                        # 记忆层
│   │   ├── __init__.py
│   │   ├── memory_core.py             # 单一记忆内核
│   │   ├── retrieval.py               # 检索 [NEW]
│   │   └── consolidation.py           # 巩固 [NEW]
│   │
│   ├── evolution/                     # 进化层
│   │   ├── __init__.py
│   │   ├── evaluator.py               # 进化评估
│   │   ├── distiller.py               # 技能蒸馏
│   │   └── skill_builder.py           # 技能构建 [NEW]
│   │
│   ├── governance/                    # 治理层
│   │   ├── __init__.py
│   │   ├── guardian.py                # 安全闸门
│   │   └── approval.py                # 审批队列
│   │
│   └── models/                        # 模型层
│       ├── __init__.py
│       ├── router.py                  # 模型路由 + 注册表
│       ├── ollama.py                  # Ollama 后端 [NEW]
│       └── cloud.py                   # 云后端抽象 + DeepSeek
│
└── web/                               # 前端（结构不变）
    ├── index.html
    ├── app.js
    └── styles.css
```

---

## 4. 关键设计决策

### 决策 1：唯一执行链

所有任务必须经过统一生命周期，禁止模块绕过 Planner、工具绕过 Guardian、Agent 直接修改系统状态或创建第二执行入口。

执行链：`IntentRouter → Planner → ControlLoop → Guardian → ActionBus → Executor → Verifier → MemoryCore → Evolution`

### 决策 2：单一记忆内核

系统只能存在一个 Memory Kernel。删除 MemoryAdapter 双轨和旧 MemorySystem，统一为 MemoryCore（7 层：Working Memory / Episodic Memory / Semantic Memory / Skill Memory / Failure Memory / Project Memory / User Profile）。

### 决策 3：ActionBus 作为唯一执行网关

所有系统动作（文件/命令/网络/模型/Agent）统一通过 ActionBus 入口，禁止模块直接写文件、执行命令、调网络。

```
Action Request (file/exec/network/model/agent)
    │
    ▼
ActionBus
    │
    ▼
Guardian (P0/P1/P2 分级)
    │
    ▼
Executor
    │
    ▼
Result (记录 action/source/time/approval/result)
```

### 决策 4：双核心平等协作

Hermes 和 Grok Build 不再是调用关系，而是通过 IntentRouter 仲裁、Reviewer 验证的平等伙伴。每个任务由 Planner 决定分配哪个 Agent。

### 决策 5：复杂度驱动的 Control Loop

- **复杂度 0-30**：普通回答，不进入 Loop
- **复杂度 30-70**：轻量 Loop（Reason → Execute → Verify）
- **复杂度 70+**：完整 Loop（Intent → Plan → Reason → Execute → Verify → Reflect → Memory）

### 决策 6：零外部依赖 + 本地优先

仅使用 Python 标准库（无 Flask/FastAPI/requests），记忆/会话/项目全部 SQLite 本地存储，除模型端口外无主动上传。

### 决策 7：Guardian 全覆盖

P0（致命）拦截入审批队列，P1（高危）记录+留痕，P2（常规）自动放行。内容级识别：`rm -rf` / `force push` / `exec` / `network` 等模式自动升级。

---

## 5. 前端架构

### 总体布局：三栏结构

```
------------------------------------------------
左侧 (AI Team)    │  中间 (Workspace)  │  右侧 (Status)
                  │                    │
· AI 团队         │  · 聊天            │  · 实时状态
· 任务            │  · 任务画布        │  · 思考过程
· 项目            │  · 执行结果        │  · 工具调用
· 记忆            │  · 交付物          │  · 审批
                  │                    │
------------------------------------------------
```

### 页面规划

| 页面 | 功能 | V4 适配 |
|------|------|---------|
| **Dashboard** | AI 生命状态：当前任务、Agent 状态、思考/执行/学习进度 | 新增 Planner 状态面板 |
| **Task Canvas** | 可视化任务 DAG：Goal → Plan → Agent → Result → Memory，支持拖拽/重试/修改节点 | 集成 Visual DAG 执行器 |
| **Agent Team** | AI 员工面板：Hermes(状态/能力) / Grok(状态/能力) / Reviewer(审核结果) | 新增 Reviewer Agent 面板 |
| **Memory** | 记忆可视化：用户偏好/项目知识/历史经验/错误经验，支持查看/修改/删除/批准 | 合并双轨为单一 Memory 视图 |
| **Guardian** | 审批界面：危险操作展示 + [批准]/[拒绝]，风险等级指示 | 接入 ActionBus 审批流 |
| **Evolution** | AI 成长面板：错误→原因→学习→应用，进化状态 | 新增 Failure→Skill 流水线视图 |

### 技术栈

- **框架**: React + Next.js + TypeScript
- **样式**: Tailwind + shadcn/ui
- **状态**: Zustand
- **通信**: WebSocket 实时通信
- **动画**: Framer Motion
- **图形**: React Flow (任务画布)

### 当前可交付 Web 界面（web/）

| Tab | 功能 | 状态 |
|-----|------|------|
| **对话 chat** | 三栏工作台：会话栏/对话/成果区，SSE 流式渲染，附件上传，模型选择器 | Working |
| **画布 canvas** | 20 种可拖节点 + DAG 编辑器 + Kahn 拓扑排序执行 | Working |
| **群聊 room** | 多 Agent 群聊室：Agent 列表 + 消息流 | Working |
| **管理 settings** | 9 个 settings-card：技能/MCP/记忆/自动化/安全/进化/治理/模型/Loop | Working |

---

## 6. V4 新增模块

### 6.1 Task Planner (P0 - 最大缺失)

```
输入: "开发一个电商网站"
输出: {
  "goal": "电商网站",
  "steps": [
    {"agent": "hermes", "task": "需求分析"},
    {"agent": "grok", "task": "代码开发"},
    {"agent": "reviewer", "task": "测试"}
  ],
  "complexity_score": 65
}
```

### 6.2 Verifier (P0)

执行完成后的门控检查：目标完成度 → 输出质量 → 安全风险 → 逻辑错误 → Pass / Retry。

### 6.3 ActionBus (P0)

所有系统动作的统一入口：dispatch(action) → Guardian → Executor → Result。

### 6.4 Agent Registry (P1)

集中管理 Agent 能力注册（name/capability/backend），消除硬编码，前端画布/MCP/Router/Planner 均读取注册表。

### 6.5 Reviewer Agent (P1)

验证 Hermes 推理正确性 + Grok 代码正确性/安全性，输出质量评分和风险评估。

### 6.6 Ollama Backend (Phase 4)

本地模型后端，与云模型（GPT/Claude/DeepSeek）形成双选，按隐私/成本/难度三维自动路由。

---

## 7. V4 验收标准

### 架构验收

- [x] 单执行链（已设计）
- [ ] 单 Memory Kernel（Phase 1）
- [ ] Planner 存在（Phase 1）
- [ ] Verifier 存在（Phase 1）
- [ ] ActionBus 存在（Phase 1）
- [ ] Agent Registry 存在（Phase 2）

### 能力验收

| 测试 | 场景 | 要求 |
|------|------|------|
| 测试 1 | 开发应用 | 需求→设计→代码→测试→修改 |
| 测试 2 | 研究任务 | 搜索→分析→报告 |
| 测试 3 | 长任务 2 小时 | 可恢复/可审计/不丢状态 |

---

## 8. 实施路线

| Phase | 周期 | 目标 |
|-------|------|------|
| **Phase 0** | 第 1 周 | 架构冻结：v3.0-final 标签、迁移地图、依赖分析、清理废弃 |
| **Phase 1** | 2-4 周 | 核心闭环：Intent Router → Planner → Verifier → ActionBus → Memory 统一 → Guardian 全覆盖 |
| **Phase 2** | 第 2 月 | Agent 协作：Hermes + Grok + Reviewer AI 团队模式 |
| **Phase 3** | 第 3 月 | 自进化：Failure → Analysis → Skill → Test → Deploy |
| **Phase 4** | 远期 | 模型层：Ollama 本地后端 + 三维自动路由 |

---

## 9. 开发执行纪律

### 禁止事项

1. 新增无调用模块
2. 创建第二套系统
3. 保留重复入口
4. 为兼容旧代码破坏新架构
5. 一次性重写 engine_xai.py
6. 推倒现有系统重新开发
7. 测试未通过进入下一阶段
8. 删除数据和历史记忆

### 阶段输出要求

每个阶段必须提交：
1. 修改文件列表
2. 修改原因
3. 架构影响
4. 测试结果
5. 风险说明
6. 下一阶段计划

---

## 10. 最终目标

XAI V4 不追求成为聊天机器人，目标是成为：

> **一个具备推理、规划、执行、验证、记忆、治理、自我进化能力的个人 AI 操作系统 + AI 团队管理平台 + 自进化智能助手。**

核心评价标准：是否形成 `理解 → 规划 → 执行 → 验证 → 记忆 → 成长` 完整智能闭环。

---

*本文档为 V4 架构宪法，所有后续开发须以此为准。与 `~/.workbuddy/memory/MEMORY.md` 中的 Dual-Kernel Fusion 架构段保持一致。*
