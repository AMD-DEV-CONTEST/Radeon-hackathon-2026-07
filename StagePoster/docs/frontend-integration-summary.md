# StagePoster 前端对接文档

> 最后更新：2026-08-01 | 服务状态：🟢 运行中（`http://127.0.0.1:8080`）

---

## 一、基础信息

| 项目 | 值 |
|---|---|
| Base URL | `http://127.0.0.1:8080`（本地）/ Cloudflare 隧道 URL（生产） |
| Auth | 当前 `POSTER_API_TOKEN=` 为空，无需认证 |
| CORS | `*`，Headers: `Content-Type, Authorization, X-Poster-Token` |
| 错误格式 | `{"error": "message"}` |
| 所有请求 Content-Type | `application/json`（资产上传除外） |

---

## 二、核心状态机

### 2.1 AI Session 状态

前端**必须**根据 `availableActions` 驱动 UI，不得靠推断状态。

```
collecting_brief
    availableActions: send_message, attach_asset, cancel
    ↓  [填完所有必填字段]
awaiting_plan_selection
    availableActions: send_message, confirm_plan, cancel
    ↓  [confirm_plan]
generating_candidates
    availableActions: refresh, cancel
    ↓  [3 张候选图就绪]
awaiting_candidate_selection
    availableActions: select_candidate, cancel
    ↓  [select_candidate]
looping
    availableActions: refresh, cancel
    ↓  [作曲完成]
succeeded
    availableActions: finalize（未审核时）, download_final
    ↓  [finalize → 审核通过]
completed_with_warnings
    availableActions: download_final
```

### 2.2 Poster 状态（内部，供参考）

```
planning_candidates → generating_candidates → validating_candidates
→ partial_ready → awaiting_selection → selected → composing → succeeded
```

---

## 三、完整对接流程

### Step 1 — 创建 Session

```http
POST /api/ai/sessions
Content-Type: application/json

{
  "brief": {
    "event": {
      "title": "Abyssal Kingdom Festival",
      "artist": "Maverick",
      "date": "2026-08-21",
      "time": "20:00",
      "venue": "Void Arena",
      "presalePrice": "$45",
      "doorPrice": "$60"
    },
    "branding": {},
    "visual": {
      "style": "dark fantasy editorial",
      "theme": "abyssal gothic kingdom",
      "musicGenre": "gothic metal",
      "mood": ["epic", "mysterious", "ritualistic"],
      "preferredColors": ["black", "aged ivory", "deep red"]
    }
  }
}
```

**响应 201：**
```json
{
  "sessionId": "session_xxx",
  "status": "collecting_brief",
  "availableActions": ["send_message", "attach_asset", "cancel"],
  "brief": { ... },
  "missingFields": null,
  "messages": [],
  "assets": null,
  "plans": null,
  "createdAt": "...",
  "updatedAt": "..."
}
```

### Step 2 — 对话填充 Brief

```http
POST /api/ai/sessions/{sessionId}/messages
Content-Type: application/json

{ "content": "用户消息内容" }
```

**响应 200：** `AIMessageResponse`，含 `session`（同上结构）+ `metrics`

- 若 `missingFields` 清空 → 状态自动变为 `awaiting_plan_selection`，`plans` 出现
- 若还有缺失字段 → 状态保持 `collecting_brief`，`plans` 为 `null`

### Step 3 — 查看 Session 状态（主轮询端点）

```http
GET /api/ai/sessions/{sessionId}
```

**响应 200：** `AISessionResponse`

```json
{
  "sessionId": "...",
  "status": "awaiting_plan_selection",
  "availableActions": ["send_message", "confirm_plan", "cancel"],
  "plans": [
    {
      "planId": "abyssal-gate-ritual",
      "name": "深渊之门仪式",
      "description": "...",
      "variants": [ ... ]
    }
  ],
  "missingFields": null,
  "posterId": null,
  ...
}
```

> ⚠️ **重要**：`confirm_plan` 后、`select_candidate` 前，**必须持续轮询此端点**来同步 poster 状态到 session。不要在前端本地缓存 `session.status`。

### Step 4 — 确认设计方案

```http
POST /api/ai/sessions/{sessionId}/plans/{planId}/confirm
```

**响应 202：** `AISessionResponse`（session 状态变为 `generating_candidates`）

> ⚠️ **确认后不要马上 select！** Poster 正在生成候选图（约 123s），需轮询 `GET /api/ai/sessions/{id}` 直到 `status=awaiting_candidate_selection` + `availableActions` 包含 `select_candidate`。

### Step 5 — 轮询等待候选图就绪

```http
GET /api/ai/sessions/{sessionId}   ← 主轮询，每 3s
```

等待 `status = "awaiting_candidate_selection"`

响应中的候选图列表：
```json
{
  "poster": {
    "candidates": [
      {
        "candidateId": "candidate_xxx",
        "variantName": "深渊之门仪式 · Balanced",
        "status": "ready",
        "selected": false,
        "imageUrl": "/api/posters/poster_xxx/candidates/candidate_xxx/image",
        "visualAnalysis": { "hasGeneratedText": false, ... }
      }
    ]
  }
}
```

### Step 6 — 选择候选图

```http
POST /api/ai/sessions/{sessionId}/candidates/{candidateId}/select
```

**响应 200：** `AISessionResponse`（状态进入 `looping`）

> ⚠️ **如果收到 409**：先调 `GET /api/ai/sessions/{id}` 同步状态，等待 `availableActions` 包含 `select_candidate` 再重试。

### Step 7 — 等待作曲完成

继续轮询 `GET /api/ai/sessions/{sessionId}`，直到 `status = "succeeded"`

响应中会出现：
```json
{
  "status": "succeeded",
  "availableActions": ["finalize", "download_final"],
  "poster": {
    "posterId": "poster_xxx",
    "status": "succeeded",
    "selectedCandidateId": "candidate_xxx",
    "resultUrl": "/api/posters/poster_xxx/result",
    "thumbnailUrl": "/api/posters/poster_xxx/thumbnail"
  }
}
```

### Step 8 — 下载最终海报

```http
GET /api/posters/{posterId}/result
```

响应：`image/png`，直接下载，约 947 KB，尺寸 1024×1536

```http
GET /api/posters/{posterId}/thumbnail
```

响应：`image/png`，约 288 KB，尺寸 512×768

### Step 9 — AI 质量审核（可选，仅 succeeded 状态）

```http
POST /api/ai/sessions/{sessionId}/finalize
```

**响应 200：** `AISessionResponse`，含 `reviewSummary`

```json
{
  "status": "succeeded",
  "reviewSummary": {
    "finalized": true,
    "accepted": true,
    "rounds": 1,
    "bestRound": 1,
    "bestScore": 88,
    "latestDecision": "ACCEPT"
  }
}
```

审核决策：
- `ACCEPT`（score ≥ 82）→ 通过
- `RECOMPOSE` → 重新排版（无新 AI 生成）
- `REGENERATE` → 重新生成图像
- `REWRITE_BRIEF` → 需要用户修改需求（session 进入 `needs_user_input`）

---

## 四、所有端点速查

### Auth & System

| 方法 | 路径 | 说明 | 超时 |
|---|---|---|---|
| `GET` | `/health` | 健康检查，无需认证 | 10s |
| `GET` | `/api/system/dependencies` | 依赖状态（DB / ComfyUI / vLLM） | 15s |
| `POST` | `/api/ai/design` | 一次性生成 3 套设计方案（无 session） | 4min |

### AI Session

| 方法 | 路径 | 说明 | 超时 |
|---|---|---|---|
| `POST` | `/api/ai/sessions` | 创建 session | 30s |
| `GET` | `/api/ai/sessions/{id}` | 获取 session 状态 ⭐主轮询 | 60s |
| `POST` | `/api/ai/sessions/{id}/messages` | 发消息填充 brief | 8min |
| `POST` | `/api/ai/sessions/{id}/assets` | 绑定资产 | 30s |
| `POST` | `/api/ai/sessions/{id}/plans/{planId}/confirm` | 确认方案 | 3min |
| `POST` | `/api/ai/sessions/{id}/candidates/{candidateId}/select` | 选择候选图 | 2min |
| `POST` | `/api/ai/sessions/{id}/finalize` | AI 质量审核 | 12min |
| `POST` | `/api/ai/sessions/{id}/cancel` | 取消 session | 30s |

### Poster

| 方法 | 路径 | 说明 | 超时 |
|---|---|---|---|
| `POST` | `/api/posters` | 直接创建 poster（无 AI 对话） | 90s |
| `GET` | `/api/posters/{id}` | 获取 poster 状态 | 60s |
| `POST` | `/api/posters/{id}/select` | 选择候选图（底层接口） | 30s |
| `GET` | `/api/posters/{id}/result` | 下载最终海报 PNG | 60s |
| `GET` | `/api/posters/{id}/thumbnail` | 下载缩略图 PNG | 60s |
| `GET` | `/api/posters/{id}/candidates/{id}/image` | 下载候选图 | 60s |
| `POST` | `/api/posters/{id}/review` | 手动触发 VLM 审核 | 5min |
| `GET` | `/api/posters/{id}/reviews` | 审核记录列表 | 20s |
| `GET` | `/api/posters/{id}/timeline` | 完整时间线+指标 | 60s |
| `POST` | `/api/posters/{id}/cancel` | 取消 poster | 30s |
| `POST` | `/api/posters/{id}/candidates/{id}/retry` | 重试失败候选 | 60s |

### Assets

| 方法 | 路径 | 说明 | 超时 |
|---|---|---|---|
| `POST` | `/api/assets` | 上传资产（multipart/form-data） | 30s |
| `GET` | `/api/assets?limit=N&offset=N` | 资产列表 | 20s |
| `GET` | `/api/assets/{id}` | 资产元数据 | 20s |
| `GET` | `/api/assets/{id}/content` | 下载原始图片 | 60s |
| `GET` | `/api/assets/{id}/process` | 处理状态 | 20s |

### Jobs（底层任务）

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/jobs` | 任务列表 |
| `GET` | `/api/jobs/{id}` | 任务状态 |
| `GET` | `/api/jobs/{id}/result` | 任务结果文件 |

---

## 五、关键数据类型

### CreateAISessionRequest

```json
{
  "brief": {
    "event": {
      "title": "string (必填)",
      "artist": "string (必填)",
      "date": "YYYY-MM-DD (必填)",
      "time": "HH:mm (必填)",
      "venue": "string (必填)",
      "presalePrice": "string",
      "doorPrice": "string"
    },
    "branding": {},
    "visual": {
      "style": "string (必填，当前仅支持 metal-gothic-v1)",
      "theme": "string (必填)",
      "musicGenre": "string (必填)",
      "mood": ["string array (必填)"],
      "preferredColors": ["string array"]
    }
  }
}
```

### SendAIMessageRequest

```json
{ "content": "string (非空)" }
```

### SelectCandidateRequest

```json
{ "candidateId": "string" }
```

### BindAISessionAssetsRequest

```json
{ "assets": [{ "assetId": "string", "purpose": "artist_logo|event_logo|sponsor_logo|reference" }] }
```

---

## 六、生成时间参考（E2E 实测）

| 阶段 | 耗时 |
|---|---|
| 3 张候选图并行生成 | **~123 秒** |
| 作曲合成 | < 1 秒 |
| AI 质量审核（finalize） | ~数秒（VLM 单次调用） |
| **端到端总计** | **~172 秒** |

---

## 七、已知注意事项

### ⚠️ 确认方案后需轮询，不能立即 select

`confirm_plan` 返回后 session 状态为 `generating_candidates`，候选图还没生成。必须轮询 `GET /api/ai/sessions/{id}` 直到 `availableActions` 包含 `select_candidate` 才能调用 select。

### ⚠️ select 前需先 GET 同步状态

`ConfirmPlan()` 只快照一次 poster 状态，Poster reconciler 推进状态时不会写回 session DB。前端**必须在调 select 前先调一次 `GET /api/ai/sessions/{id}`**，让 `Get()` 内部调用 `sessionStatusForPoster()` 同步最新状态。

### ⚠️ `style` 字段当前仅支持 `metal-gothic-v1`

`POST /api/posters` 和 `POST /api/ai/design` 均只接受 `style: "metal-gothic-v1"`，其他值返回 400。

### ℹ️ 资产上传必须用 multipart/form-data

```bash
# 正确
curl -F "file=@image.png;type=image/png" -F "kind=reference" ...

# 错误（不要带 Content-Type: application/json）
curl -H "Content-Type: application/json" -F ...
```

仅接受 `image/png` 和 `image/jpeg`。

### ℹ️ POST /api/generate 是底层接口

单图生成，不走 session 流程。返回 `jobId` 后需轮询 `GET /api/jobs/{jobId}`。

---

## 八、调试接口

```bash
# 健康检查
curl http://127.0.0.1:8080/health

# 依赖状态
curl http://127.0.0.1:8080/api/system/dependencies

# 完整 E2E 测试（约 3 分钟）
bash scripts/e2e-test.sh

# API 集成测试（约 10s）
bash scripts/api-test.sh
```
