# XAI 双模编辑器 · API 契约（单一事实源）

> **用途**：前后端对接的契约真源。任何一侧改 API 形状，必须同步本文件并提前通知对侧。
> **维护者**：主AI（后端，混元3）。前端（马维斯，混元3+DeepSeek）只读消费。
> **状态**：草案骨架，标注 `[B-lane]` 的端点由主AI 后端 lane 补齐后冻结。

---

## 0. 通用约定
- Base URL：`http://localhost:8000`
- 鉴权：除明确标注 `公开` 的端点外，均需 `Authorization: Bearer <token>`。
  - **Dev 模式**：主AI 正在定 localStorage token / localhost bypass 策略，定好后在此写明具体 header 形状（见 §6）。
  - 未授权统一返回：`{"error":"未授权"}`（HTTP 401）。
- 响应信封：`{"status":"ok"|"error","data":{},"error":str,"meta":{}}`（部分端点直接返回数组，以实际为准，待冻结）。

---

## 1. 模型列表 `[B0 对齐]`
- `GET /api/models/list`
- 鉴权：需鉴权
- 响应：`{ "models": [ { "id":"mdl:xxx", "name":"DeepSeek V4 Flash", "provider":"deepseek", "model":"deepseek-chat", "is_active":true, "api_key":false } ] }`
- 前端行为：按 `is_active=true` 选默认模型；下拉展示全部，V4 Pro 可选。

---

## 2. 对话发送 `[B0 对齐]`
- `POST /api/chat/send`
- 鉴权：需鉴权
- 请求：`{ "message":"...", "model":"deepseek-chat"（可选，默认 active） }`
- 响应：SSE 或 JSON 流式（以实际实现为准，待冻结）。

---

## 3. 流程从文本生成 `[已存在]`
- `POST /api/workflow/from_text`
- 鉴权：需鉴权
- 请求：`{ "text":"设计搜索+总结流程", "session_id":str }`
- 响应：`{ "plan":[...], "nodes":[...] }` → 前端经 `wf_node_spawn` 增量追加到画布。

---

## 4. 画布校验 / 干跑 `[已存在]`
- `POST /api/canvas/validate`
- 鉴权：需鉴权
- 请求：`{ "dsl":{...} }`
- 响应：`{ "issues":[ { "node_id":"n1", "type":"loop|broken_chain|missing_config", "severity":"red|orange|yellow", "msg":"..." } ], "summary":"..." }`
- 前端：环路红/断链橙/缺配置黄 → 节点高亮 + 点击定位 + 右栏卡片 + L7 复盘。

---

## 5. Guardian 审批 `[B-lane 已落地 ✅]`
> 实时性用**轮询**（非 SSE）以避免脆弱全局广播；节点徽标由 pending 列表驱动。

- `GET /api/guardian/pending` → `{ "pending": [ { "id":"APR-0003", "type":"rm_rf", "detail":"...", "intent":"", "reason":"P0...", "session":"default", "level":0, "level_name":"P0", "status":"pending" } ] }`
  - 前端每 ~1.5s 轮询，按 `id`+`type` 给对应画布节点挂「⏸ 等确认」徽标；空数组即无待确认。
- `POST /api/guardian/approve` → body `{ "ticket_id":"APR-0003", "human_ok":true, "reason":"已确认" }`
  - 返回 `{ "ok":true, "id":"APR-0003", "status":"approved", "type":"rm_rf", "detail":"..." }`；`human_ok:false` 即拒绝（status=rejected）。
- 兼容旧端点 `POST /api/approvals/confirm` → body `{ "id":"APR-0003" }`（已修真可用，等同 human_ok=true）。
- **批量审批（前端侧聚合）**：前端把同一 `type`/`kind` 的 pending 合并成一个确认浮层（"本计划含 N 个 P0 写文件，是否全部批准？"），逐条调用 `/api/guardian/approve` 即可；后端无需单独 batch 端点（保持简单）。

---

## 6. 记忆统计（供 C1 MEM-2 对齐）`[已存在]`
- `GET /api/memory/stats`
- 鉴权：需鉴权
- 响应：`{ "layers": { "working":N, "short_term":N, "long_term":N, "anchor":N, "reflection":N, "causal":N, "user_profile":N, "failure_correction":N } }`
- 前端 `MemoryDashboard` 须以该 8 层真实字段为准（非旧 LAYER_KEYS 分类学）。

---

## 7. 跨会话记忆上下文召回 `[新增 P2-O1]`

- `GET /api/memory/context?text=<query>`
- 鉴权：需鉴权（`X-Auth-Token`）
- 参数：`text` (必填，查询文本)
- 混合召回策略（bridge 层，不改 memory_core.recall 接口）：
  - 子串匹配 40%
  - 关键词加权 40%（纯规则分词，不依赖 jieba 等重 NLP）
  - 时间衰减 20%（衰减因子 0.95^(hours_ago)）
  - 硬限制 ≤10 条
- 返回：

```json
{
  "results": [
    {
      "layer": "short_term",
      "key": "memory_key",
      "value": "记忆全文（截断 500 字符）",
      "score": 0.85
    }
  ],
  "count": 2
}
```

- 示例：`GET /api/memory/context?text=deepseek 接口异常` → 返回与 deepseek 接口异常相关的 top-10 记忆。
- 与现有 `retrieve_memory_context` 的关系：这是对 `retrieve_memory_context` 的加重排版本，上层端点消费结构化结果后自行决定如何注入系统提示词。

---

## 8. 真观测 Tracing Pipeline `[新增]`
- `GET /api/observability/traces?limit=50`
- 鉴权：需鉴权（`X-Auth-Token`）
- 返回：
```json
{
  "spans": [
    {
      "trace_id": "uuid",
      "tool_name": "exec_command",
      "start_ts": 1234567890.0,
      "end_ts": 1234567890.5,
      "success": true,
      "output_size": 1024,
      "error_msg": null,
      "duration_ms": 500.0
    }
  ],
  "stats": {
    "total": 100,
    "success_rate": 0.95,
    "avg_latency_ms": 120.5,
    "p95_latency_ms": 350.0
  }
}
```
- limit 参数：1-200，默认 50。spans 按 end_ts 倒序返回最近 N 条。
- 用途：前端 Dashboard 展示工具调用耗时、成功率、P95 延迟；替代模型自报置信度。

---

## 9. 系统错误追踪 `[P2-O2]`

- `GET /api/system/errors?limit=20`
- 鉴权：需鉴权（`X-Auth-Token`）
- 复用 `core.observability.global_tracer` 中已记录的失败 span，过滤 `success=false` 的条目。
- 返回格式：行式（row-based），每行含 `timestamp` + `component` + `error_type` + `message` + `trace_id`，按时间倒序。

```json
{
  "errors": [
    {
      "timestamp": "2026-07-21T12:34:56Z",
      "component": "read_file",
      "error_type": "IOError",
      "message": "File not found: /path/to/missing.pdf",
      "trace_id": "a1b2c3d4-..."
    }
  ],
  "total": 5,
  "filtered": 5
}
```

- limit 参数：1-100，默认 20。errors 按 timestamp 倒序返回最近 N 条失败记录。
- component 字段对应 tracer span 中的 `tool_name`；error_type 从 `error_msg` 中提取异常类名或首段描述。
- 用途：前端错误追踪面板展示系统级失败诊断信息。

---

## 10. 硬沙箱状态 `[P0-K3b]`

- `GET /api/system/sandbox`
- 鉴权：公开
- 返回：

| 字段 | 类型 | 说明 |
|------|------|------|
| `mode` | `"hard"\|"soft"\|"none"` | `hard`: nsjail/firejail 容器级沙箱；`soft`: setrlimit 进程资源限制；`none`: 无沙箱（不应出现） |
| `backend` | `"nsjail"\|"firejail"\|"setrlimit"\|null` | 当前生效的沙箱后端 |
| `message` | `string` | 人类可读的状态描述 |

- 示例响应：

```json
// Linux + nsjail:
{"mode":"hard","backend":"nsjail","message":"nsjail 可用: /usr/bin/nsjail"}

// macOS（无容器，软退）:
{"mode":"soft","backend":"setrlimit","message":"无容器沙箱，使用 setrlimit 软限制"}
```

- 行为说明：后端启动时检测 `shutil.which('nsjail')` → `firejail` → 回退 `setrlimit`。命令执行路径为四级回退：nsjail → firejail → macOS sandbox-exec → setrlimit（详见 `core/execution/action_bus.py::LocalExecutor.run_hardened`）。

---

## 11. 备份/恢复 `[P3-O3]`

- `POST /api/system/backup`
- 鉴权：需鉴权（`X-Auth-Token`）
- 请求体：无（空 `{}` 或空 POST）
- 响应：`Content-Type: application/gzip`，直接返回 XAI 数据目录（`XAI_HOME`，默认 `~/.xai`）的 **tar.gz 二进制流**。
- **响应头**：`Content-Disposition: attachment; filename="xai-backup-<ISO_DATE>.tar.gz"`，`Content-Type: application/gzip`。
- 用途：前端点击「导出备份」→ 浏览器触发文件下载。允许 `Authorization` 或 `X-Auth-Token` header 任一通过。
- 状态码：成功 200；鉴权失败 401；数据目录不存在 500。

- `POST /api/system/restore`
- 鉴权：需鉴权（`X-Auth-Token`）
- 请求体：`multipart/form-data`，字段名为 `file`，内容为 `.tar.gz` 备份文件。
- 后端行为：接收上传 tar.gz → 解压到临时目录 → 校验 `app.db` 存在（基本合法性）→ 覆盖写入 `XAI_HOME` → 清理临时目录。
- 响应：`{ "ok": true, "restored_files": N, "message": "恢复完成，请重启服务生效" }`
- 状态码：成功 200；鉴权失败 401；缺少文件字段 400；非 gzip 格式 400；解压失败 500；`app.db` 校验失败 400。
- ⚠️ 恢复会**覆盖**现有数据目录，前端必须弹出二次确认弹窗。

---

## 12. 知识管道（下手能力 · S3）`[新增]`

> 防腐层：后端经 `KnowledgeAdapter`（Port/Adapter）接入，引擎只依赖抽象。前端经下列端点消费。

- `POST /api/knowledge/ingest` → body `{ "paths": ["/abs/path/or/dir"] }`
  - 摄入文件/目录（md/txt/py/rs/json/csv/log），返回 `{ "ok":true, "output":"已摄入 N 块", "meta":{ "ingested":N } }`
- `POST /api/knowledge/search` → body `{ "query":"...", "top_k":5 }`
  - 混合检索（BM25 + 稠密向量，稠密不可用时降级 BM25），返回 `{ "ok":true, "hits":[ { "source","text","score" } ] }`
- `GET /api/knowledge/stats` → `{ "ok":true, "stats":{ "total_chunks","sources","dense_available","built" } }`
- `POST /api/knowledge/clear` → `{ "ok":true, "meta":{ "cleared":N } }`

存储：SQLite（`~/.xai/knowledge.db`），重启不丢。稠密向量走本地 llama.cpp `/v1/embeddings`，无 embedding 服务时自动降级为 BM25-only（仍可检索）。

---

## 7. 变更记录
- 2026-07-21：新增 §12 知识管道端点（ingest/search/stats/clear），S3 下手能力，Port/Adapter 防腐层 + SQLite 持久化。
- 2026-07-21：新增 §11 备份/恢复端点（POST /api/system/backup + POST /api/system/restore），P3-O3。
- 2026-07-21：新增 §9 系统错误追踪端点（GET /api/system/errors），P2-O2，复用 global_tracer 失败 span。
- 2026-07-21：新增 §7 跨会话记忆上下文召回端点（GET /api/memory/context），混合召回策略（子串40%+关键词40%+时间衰减20%），P2-O1。
- 2026-07-21：新增 §10 硬沙箱状态端点（GET /api/system/sandbox）。
- 2026-07-21：新增 §8 真观测 Tracing Pipeline 端点（GET /api/observability/traces）。
- 2026-07-21：草案建立。§5 Guardian 端点待 B-lane 补齐；§0 dev 鉴权策略待定。
