# XAI Kernel V4 API 契约文档

**服务**: server_xai.py (ThreadingHTTPServer, Python 标准库)  
**监听**: `localhost:8000` (可配置: `XAI_HOST`, `XAI_PORT`)  
**协议**: HTTP/1.1 + SSE (Server-Sent Events)  
**生成日期**: 2026-07-18  
**适用版本**: V3 (v3.0-final) → V4 迁移  

---

## 1. REST API 端点

### 1.1 系统端点

#### `GET /` 
前端入口, 返回 `web/index.html`。

| 维度 | 详情 |
|------|------|
| 状态 | Working |
| V4 | KEEP |

**响应**: `text/html; charset=utf-8`

---

#### `GET /web/<file>`
静态资源服务 (app.js, styles.css)。

| 维度 | 详情 |
|------|------|
| 状态 | Working |
| V4 | KEEP |
| 响应头 | `Cache-Control: no-cache, no-store, must-revalidate` |

**Content-Type 映射**:
- `.js` → `text/javascript`
- `.css` → `text/css`
- 其他 → `application/octet-stream`

---

#### `GET /api/status`
系统完整状态快照。

| 维度 | 详情 |
|------|------|
| 状态 | Working |
| V4 | KEEP (路径可能改为 `/api/v4/status`) |

**响应格式** (200):
```json
{
  "xai_engine": true,
  "model": "deepseek-chat",
  "project": {"id": "...", "name": "默认工作区"},
  "openclaw": {"meta": {"available": true}},
  "hermes": {"available": true},
  "memory": {"adapter_layers": 7, "adapter_total": 42},
  "memory_core_layers": {"working": 3, "short_term": 12, "long_term": 5, ...},
  "grok_build": {"available": false, "reason": "grok binary not found"},
  "models": [{"id": "...", "name": "DeepSeek", "provider": "deepseek", "is_active": true}],
  "pending_approvals": 0,
  "slash_commands": ["/help", "/status", "/scan", "/remember", "/recall", "/models", "/agent", "/diagnose", "/project", "/loop"]
}
```

---

#### `GET /api/health` ❌

| 维度 | 详情 |
|------|------|
| 状态 | NOT IMPLEMENTED (返回 404) |
| V4 | 新增 — Phase 1 独立服务探测 |

---

### 1.2 对话端点

#### `POST /api/chat` (SSE 流式)

| 维度 | 详情 |
|------|------|
| 状态 | Working |
| V4 | MIGRATE (路径可能不变, 内部实现走 V4 执行链) |
| Content-Type | `text/event-stream; charset=utf-8` |
| Connection | `close` |

**请求** (JSON):
```json
{
  "text": "用户输入文本 (必填)",
  "session": "session-id (可选, 默认 \"default\")",
  "attachments": [
    {
      "name": "file.py",
      "content": "base64 编码内容",
      "mime": "text/x-python"
    }
  ]
}
```

**SSE 事件流**: 见 §2.1

**限制**: 
- 斜杠命令 (以 `/` 开头) 不进完整执行链, 直接 `/handle_slash` → `answer` + `done`
- 非 ASCII 内容通过 `ensure_ascii=False` 序列化

---

#### `POST /api/chat/send` (非流式)

| 维度 | 详情 |
|------|------|
| 状态 | Partial (已知缺陷: 普通对话返回空) |
| V4 | MIGRATE (修复缺陷) |

**请求**: 同 `POST /api/chat`

**响应** (200):
```json
{
  "answer": "最终回答文本",
  "session": "session-id",
  "errors": ["错误信息"]  // 可选, 仅在出错时出现
}
```

**已知缺陷**: 只收集 `answer` 事件, 通用对话走 `token` 事件 → 普通聊天永远返回空。V4 修复方案: 累加 `token` + `answer` 两类事件。

---

### 1.3 工作流端点

#### `POST /api/workflow/run` (SSE 流式)

| 维度 | 详情 |
|------|------|
| 状态 | Working |
| V4 | KEEP (内部通过 Planner→ActionBus 管线执行) |
| Content-Type | `text/event-stream; charset=utf-8` |

**请求** (JSON):
```json
{
  "nodes": [
    {
      "id": "node-1",
      "type": "chat|react|router|skill|mcp|exec|file|scan|git|gb_gen|gb_refactor|gb_test|agent_hermes|agent_grok|agent_pm|mem_query|input|output|condition|loop",
      "label": "节点标签",
      "x": 100,
      "y": 200,
      "properties": {}
    }
  ],
  "edges": [
    {"from": "node-1", "to": "node-2"}
  ]
}
```

**SSE 事件流**: 见 §2.2

**执行逻辑**: Kahn 拓扑排序 + 环路检测 + 逐节点执行。仅 `input/scan/mcp/exec/file/git` 6 类节点有真实后端语义, 其余落通用模型推理。

---

### 1.4 记忆端点

#### `GET /api/memory`

| 维度 | 详情 |
|------|------|
| 状态 | Working |
| V4 | MIGRATE (V4 单 Memory 后去除 adapter 字段) |

**响应** (200):
```json
{
  "adapter": {
    "short": 5,
    "long": 12,
    "anchor": 3,
    "total": 20
  },
  "core": {
    "working": 3,
    "short_term": 12,
    "long_term": 5,
    "anchor": 2,
    "reflection": 1,
    "causal": 0,
    "user_profile": 4,
    "failure_correction": 1
  },
  "core_db": "~/.xai/memory.db"
}
```

**已知问题**: 双轨 (adapter + core) 统计并存 — V4 统一后仅保留 core 层。

---

### 1.5 审批端点

#### `GET /api/approvals`

| 维度 | 详情 |
|------|------|
| 状态 | Working |
| V4 | KEEP |

**响应** (200):
```json
{
  "approvals": [
    {
      "id": "uuid",
      "type": "delete_file",
      "detail": "删除文件 /path/to/file",
      "intent": {"type": "code_dev", "task": "..."},
      "reason": "删除文件可能不可逆",
      "status": "pending",
      "session": "session-id"
    }
  ]
}
```

---

### 1.6 Agent 端点

#### `GET /api/agents`

| 维度 | 详情 |
|------|------|
| 状态 | Working |
| V4 | MIGRATE (V4 从 AgentRegistry 读取) |

**响应** (200):
```json
{
  "agents": [
    {
      "name": "Hermes",
      "role": "通用推理",
      "backend": "deepseek",
      "id": "..."
    }
  ],
  "rooms": ["default", "code-review"]
}
```

---

#### `GET /api/coordination/rooms`

| 维度 | 详情 |
|------|------|
| 状态 | Working |
| V4 | KEEP |

**响应** (200):
```json
{
  "rooms": ["default", "code-review", "research"]
}
```

---

#### `POST /api/coordination/chat`

| 维度 | 详情 |
|------|------|
| 状态 | Working |
| V4 | MIGRATE (走 V4 event_bus) |

**请求** (JSON):
```json
{
  "agent": "Hermes",
  "text": "消息内容",
  "room": "default"
}
```

**响应** (200):
```json
{
  "ok": true,
  "msg_id": "uuid",
  "room": "default",
  "history": [
    {"sender": "Hermes", "text": "...", "ts": "2026-07-18T12:00:00"}
  ]
}
```

---

### 1.7 文件端点

#### `POST /api/upload`

| 维度 | 详情 |
|------|------|
| 状态 | Working |
| V4 | KEEP |

**请求** (JSON):
```json
{
  "name": "original-filename.py",
  "mime": "text/x-python",
  "data_base64": "ZGVmIGhlbGxvKCk6IHByaW50KCJoZWxsbyIp"
}
```

**响应** (200):
```json
{
  "ok": true,
  "name": "original-filename.py",
  "stored": "20260718120000_000_original-filename.py",
  "path": "/Users/.../.xai/workspace/uploads/20260718120000_000_original-filename.py"
}
```

---

#### `POST /api/save`

| 维度 | 详情 |
|------|------|
| 状态 | Working |
| V4 | KEEP |

**请求** (JSON):
```json
{
  "name": "my-artifact",
  "content": "保存的文件内容",
  "ext": "md"
}
```

**`ext` 校验**: 仅允许 `[a-zA-Z0-9.]`, 截断 12 字符。  
**`name` 校验**: `isalnum() + ._-`, 其他字符替换为 `_`。

**响应** (200):
```json
{
  "ok": true,
  "stored": "artifacts/my_artifact.md",
  "path": "/Users/.../.xai/workspace/artifacts/my_artifact.md"
}
```

---

#### `GET /api/open?name=<stored>`

| 维度 | 详情 |
|------|------|
| 状态 | Working |
| V4 | KEEP |

**查询参数**: `name` - 文件名 (支持 `name` / `uploads/name` / `artifacts/name` 三种前缀尝试)

**路径安全**: 拒绝 `..` / 绝对路径 / `\` 开头, 所有路径验证在 workspace 内。

**响应** (200):
```json
{
  "ok": true,
  "path": "/Users/.../.xai/workspace/uploads/filename.py"
}
```

**响应** (404):
```json
{
  "ok": false,
  "error": "文件不存在或越界"
}
```

---

### 1.8 会话端点

#### `GET /api/history`

| 维度 | 详情 |
|------|------|
| 状态 | Working |
| V4 | KEEP |

**响应** (200):
```json
{
  "sessions": [
    {"session": "sid-1", "last_role": "assistant", "last_content": "...", "ts": "2026-07-18T12:00:00"}
  ]
}
```

---

#### `GET /api/session/<session_id>`

| 维度 | 详情 |
|------|------|
| 状态 | Working |
| V4 | KEEP |

**响应** (200):
```json
{
  "session": "sid-1",
  "messages": [
    {"role": "user", "content": "..."},
    {"role": "assistant", "content": "..."}
  ]
}
```

**限制**: `limit=200` 条消息。

---

### 1.9 模型端点

#### `GET /api/models/list`

| 维度 | 详情 |
|------|------|
| 状态 | Working (但前端走 /api/status 拉模型列表, 少有直接调用) |
| V4 | KEEP |

**响应** (200):
```json
{
  "models": [
    {
      "id": "uuid",
      "name": "DeepSeek",
      "provider": "deepseek",
      "model": "deepseek-chat",
      "base_url": "https://api.deepseek.com/v1",
      "api_key": "sk-d***fd55",
      "is_active": true,
      "created_at": "2026-07-18T12:00:00"
    }
  ],
  "stats": {"total": 1, "active": 1}
}
```

**安全**: `api_key` 永远返回掩码版本 (`mask_key()` 格式: `sk-前缀***后缀`)。

---

#### `POST /api/models/add`

| 维度 | 详情 |
|------|------|
| 状态 | Working |
| V4 | KEEP |

**请求** (JSON):
```json
{
  "name": "自定义模型名称",
  "provider": "openai|anthropic|deepseek|ollama|custom",
  "model": "gpt-4o",
  "base_url": "https://api.openai.com/v1",
  "api_key": "sk-..."
}
```

**必填**: `model` + `base_url`

**响应** (200):
```json
{
  "ok": true,
  "model": {"id": "uuid", "name": "...", "api_key": "sk-***xxx", ...}
}
```

---

#### `POST /api/models/delete`

| 维度 | 详情 |
|------|------|
| 状态 | Working |
| V4 | KEEP |

**请求** (JSON):
```json
{
  "id": "model-uuid"
}
```

**响应** (200):
```json
{"ok": true}
```

---

#### `GET /api/models/activate/<model_id>` ⚠️

| 维度 | 详情 |
|------|------|
| 状态 | Working (但 GET 产生副作用, 应改为 POST/PUT) |
| V4 | MIGRATE (GET → POST `/api/models/activate` 或 PUT) |

**响应** (200):
```json
{
  "ok": true,
  "active": {"id": "uuid", "name": "...", "model": "deepseek-chat", "is_active": true}
}
```

**副作用**: 调用 `Engine._rebuild_backend()` 重建 HermesAdapter。

---

### 1.10 Loop Safety 端点

#### `GET /api/loop-safety`

| 维度 | 详情 |
|------|------|
| 状态 | Working |
| V4 | KEEP |

**响应** (200):
```json
{
  "config": {
    "max_iterations": 10,
    "max_tokens_per_task": 8000,
    "max_similar_messages": 5,
    "circuit_breaker_threshold": 3,
    "context_overflow_threshold": 8192
  },
  "runtime": {
    "iterations": 0,
    "tokens_used": 0,
    "similar_count": 0,
    "circuit_failures": 0,
    "context_size": 0
  },
  "presets": {
    "recommended": {...},
    "strict": {...},
    "relaxed": {...}
  }
}
```

---

#### `POST /api/loop-safety-update`

| 维度 | 详情 |
|------|------|
| 状态 | Working |
| V4 | KEEP |

**请求格式 A** (Preset 预设):
```json
{"preset": "strict"}
```

**请求格式 B** (Key-Value):
```json
{"key": "max_iterations", "value": 20}
```

**请求格式 C** (扁平字段):
```json
{"max_iterations": 15, "max_tokens_per_task": 10000}
```

**响应** (200):
```json
{
  "ok": true,
  "config": {"max_iterations": 20, ...}
}
```

---

### 1.11 Project 端点

#### `GET /api/projects`

| 维度 | 详情 |
|------|------|
| 状态 | Working |
| V4 | KEEP |

**响应** (200):
```json
{
  "current": {"id": "uuid", "name": "默认工作区"},
  "list": [
    {
      "id": "uuid",
      "name": "项目名",
      "description": "项目描述",
      "workspace": "~/.xai/workspace",
      "created_at": "2026-07-18T12:00:00"
    }
  ]
}
```

---

#### `GET /api/projects/activate/<project_id>`

| 维度 | 详情 |
|------|------|
| 状态 | Working |
| V4 | KEEP (但已知隔离缺口: session/workspace 不随 project 切换) |

**响应** (200):
```json
{"ok": true, "project": "项目名"}
```

---

### 1.12 蒸馏端点

#### `GET /api/distill`

| 维度 | 详情 |
|------|------|
| 状态 | Working (手动触发, 无定时调度) |
| V4 | MIGRATE (纳入 Evolution 自动调度) |

**响应** (200):
```json
{
  "ok": true,
  "distilled": 20,
  "stored_as": "distill:1719129600",
  "sample": [
    "- [hermes] 用户偏好使用 TypeScript...",
    "- [grok] React 组件模式...",
    "- [xai] 项目电商系统..."
  ]
}
```

**逻辑**: 取最近 20 条 short_term 记忆 → 拼接 → 写入 anchor 层。

---

### 1.13 未实现的端点

| 方法 | 路径 | 状态码 | V4 计划 |
|------|------|--------|---------|
| HEAD | any | 501 (未处理) | 新增 `do_HEAD` |
| GET | any | 404 | 不变 |

---

## 2. SSE 事件流

### 2.1 `/api/chat` 事件类型

| event.type | 字段 | 说明 | 频率 |
|------------|------|------|------|
| `start` | `text` — 引擎就绪信号 | 每次对话开始 | 1 次 |
| `intent` | `intent` — 意图类型 (code_dev/office/automation/research/general/browser/memory), `confidence` — 置信度 (0-1), `rationale` — 分类理由 | 意图分类后 | 1 次 |
| `guard` | `level` — P0/P1/P2, `reason` — 风险评估 | 安全审查后 | 0-1 次 |
| `approval` | `id` — 审批卡片 UUID, `level` — P0/P1, `action` — 动作类型, `message` — 用户可读描述, `session` — 会话 ID | P0 被拦截时 | 0-1 次 |
| `progress` | `stage` — 阶段名 (task_plan/code_gen/code_check/search/answer/loop/fallback/attach/gb_fallback/diagnose/evolve), `text` — 进度描述 | 各阶段切换 | 多次 |
| `token` | `text` — 流式片段 (逐 token 推送) | 通用对话流式输出 | 高频 |
| `answer` | `answer` — 最终完整回答 | 命令/非流式结果 | 0-1 次 |
| `deliverable` | `name` — 文件名, `stored` — 存储路径, `lang` — 编程语言, `content` — 代码/JSON 内容 | 代码生成或结构化结果 | 0-N 次 |
| `reset` | `reason` — 重置原因 (如 "fallback") | 模型切换 fallback | 0-N 次 |
| `error` | `error` — 错误信息 | 非静默错误 | 0-N 次 |
| `done` | (无字段) | 对话完成 | 1 次 |
| — | — | 流结束标记 (原始字符串 `[DONE]`) | 1 次 |

**典型流序列** (P0 审批场景):
```
start → intent → guard {"level":"P0"} → approval {...} → done → [DONE]
```

**典型流序列** (普通对话):
```
start → intent → guard {"level":"P2"} → token ×N → done → [DONE]
```

**典型流序列** (代码开发):
```
start → intent → progress {"stage":"task_plan"} → progress {"stage":"code_gen"} → deliverable {...} → done → [DONE]
```

**注意**: 斜杠命令不发送 `intent` / `guard` 事件, 直接走 `answer` + `done`。

---

### 2.2 `/api/workflow/run` 事件类型

| event.type | 字段 | 说明 |
|------------|------|------|
| `wf_start` | `total` — 节点总数 | 工作流开始 |
| `wf_node` | `node_id`, `index`, `total`, `label`, `ntype`, `status` (running/done/error), `output` | 节点状态变化 |
| `progress` | `stage`, `text` | 节点内执行进度 (如"推理中...") |
| `wf_done` | `result` — 最终结果汇总 | 工作流完成 |
| `error` | `error` | 致命错误 (如环路检测) |
| — | — | 流结束 (`[DONE]`) |

---

## 3. HTTP 响应规范

### 通用响应头

| Header | 值 | 适用 |
|--------|-----|------|
| `Content-Type` | `application/json; charset=utf-8` | 所有 JSON 响应 |
| `Access-Control-Allow-Origin` | `*` | 所有响应 |
| `Content-Length` | 实际值 | 所有 JSON 响应 |
| `Cache-Control` | `no-cache, no-store, must-revalidate` | 静态资源 |
| `Connection` | `close` | SSE 流式响应 |

### 错误响应

```json
{
  "error": "错误描述",
  "path": "/请求路径"
}
```

**HTTP 状态码**: 400 (无效输入), 404 (资源不存在), 500 (内部错误)

---

## 4. V4 API 迁移计划

### 保持不变的端点 (KEEP)

| 端点 | 备注 |
|------|------|
| `GET /` | 前端入口 |
| `GET /web/<file>` | 静态资源 |
| `GET /api/status` | 可能加 V4 字段 (planner/verifier/action_bus) |
| `GET /api/memory` | V4 统一 Memory 后去除 adapter 字段 |
| `GET /api/approvals` | 不变 |
| `POST /api/workflow/run` | 内部走 Planner→ActionBus, API 不变 |
| `GET /api/agents` | V4 从 AgentRegistry 读取 |
| `GET /api/coordination/rooms` | 不变 |
| `POST /api/coordination/chat` | 走 V4 event_bus |
| `POST /api/upload` | 不变 |
| `POST /api/save` | 不变 |
| `GET /api/open` | 不变 |
| `GET /api/history` | 不变 |
| `GET /api/session/<id>` | 不变 |
| `GET /api/models/list` | 不变 |
| `POST /api/models/add` | 不变 |
| `POST /api/models/delete` | 不变 |
| `GET /api/loop-safety` | 不变 |
| `POST /api/loop-safety-update` | 不变 |
| `GET /api/projects` | 不变 |
| `GET /api/projects/activate/<id>` | 不变 |
| `GET /api/distill` | 可能改为 POST 调度 |

### 需迁移/修改的端点 (MIGRATE)

| 端点 | 变更 |
|------|------|
| `POST /api/chat` | 内部实现走 V4 执行链, 可能新增字段 (plan/verify/action_bus_log) |
| `POST /api/chat/send` | 修复普通对话返回空缺陷, 累加 token 事件 |
| `GET /api/models/activate/<id>` | GET → POST/PUT `/api/models/activate` (消除 GET 副作用) |
| `GET /api/health` (新增) | Phase 1 新增, 返回 200 + `{"version": "v4", "healthy": true}` |

### 新增端点 (NEW)

| 端点 | Phase | 用途 |
|------|-------|------|
| `GET /api/v4/planner` | Phase 1 | Planner 状态 + 当前执行计划 |
| `GET /api/v4/verifier` | Phase 1 | Verifier 最近验证结果 |
| `GET /api/v4/action-bus` | Phase 1 | ActionBus 动作审计日志 |
| `GET /api/v4/agents/registry` | Phase 2 | Agent 能力注册表 |
| `GET /api/v4/evolution` | Phase 3 | 进化流水线状态 |

---

## 5. 安全约束

### 路径穿越防护

| 端点 | 防护 |
|------|------|
| `POST /api/save` | `ext` 仅允许 `[a-zA-Z0-9.]` (12 字符), `name` 净化 `[a-zA-Z0-9._-]` |
| `POST /api/upload` | `os.path.basename(raw_name)` 剥离路径, 拒绝 `.` / `..` |
| `GET /api/open` | 拒绝 `..` / 绝对路径 / `\` 开头; 所有路径验证在 workspace 内 |
| OpenClawAdapter | `_safe_path` 验证路径以 workspace 为前缀 |

### API Key 保护

- `DEEPSEEK_API_KEY` 存储于 `~/.zshrc` (不落盘项目目录)
- `/api/models/list` 和 `/api/status` 永远返回掩码版 key
- `mask_key()` 掩码格式: `sk-前缀***尾缀`

---

## 6. 已知缺陷

| # | 缺陷 | 影响 | 修复计划 |
|---|------|------|----------|
| 1 | `/api/chat/send` 对普通对话永远返回空 | 前端非流式模式不可用 | Phase 1 修复 |
| 2 | `/api/models/activate/<id>` 用 GET 产生副作用 | REST 语义不正确 | Phase 1 改为 POST/PUT |
| 3 | 缺 `/api/health` + `do_HEAD` | 外部探测 404/501 | Phase 1 新增 |
| 4 | 斜杠命令不发送 `intent` / `guard` 事件 | 审批卡片不完整 | Phase 1 统一链路 |
| 5 | 无 WebSocket 实时通信 | 前端依赖 SSE, 无法双向实时 | 远期 |

---

*API 契约基于 server_xai.py (585 行, 2026-07-18) 源码实证生成。后续修改需同步更新本文档。*
