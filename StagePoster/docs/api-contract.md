# StagePoster API Contract v1.0

**Status:** Hackathon MVP API contract

**Backend:** Go + SQLite + local filesystem + ComfyUI

**Collaboration:** Contract First, async tasks, mock-first integration

## 1. Document Purpose

This document defines the public HTTP API between the StagePoster frontend and
backend.

**The frontend is responsible for expressing:**
- What the user wants to create
- Which assets the user has uploaded
- What design style is selected
- What output specifications are needed

**The frontend does NOT need to know:**
- ComfyUI node IDs
- Workflow JSON structure
- Model paths
- Prompt templates
- Seed values
- Samplers
- ComfyUI queue and WebSocket protocols

**The backend is responsible for:**
- Asset ingestion and management
- Creative Brief validation
- Style interpretation
- Prompt construction
- Workflow selection
- ComfyUI scheduling
- Task status management
- Logo and text composition
- Output file management

## 2. Operation Modes

StagePoster supports two operation modes with the same API.

| Mode | Inference | Use Case |
|---|---|---|
| `mock` | Simulated generation | Local frontend dev, API integration, demo fallback |
| `comfy` | Real ComfyUI calls | GPU server integration, competition demo |

Switching from mock to ComfyUI requires changing only the API address. No
frontend code changes needed.

## 3. Recommended Hackathon Deployment

### 3.1 Real Integration

Backend and ComfyUI run on the GPU server.

```
Frontend
   ↓ HTTPS
StagePoster Go Backend
   ↓ localhost / private network
ComfyUI
   ↓
GPU
```

Frontend only needs to configure:

```
API_BASE_URL=https://your-backend-address/api
```

> The base path is `/api`, **not** `/api/v1`. No `/api/v1` namespace is
> registered in the backend. Earlier revisions of this document said `/api/v1`
> throughout; a frontend configured that way 404s on every call.

With this setup, the frontend developer does NOT need to:
- Install ComfyUI
- Download models
- Configure ROCm
- Access SQLite database
- Sync upload files
- Run GPU workers

### 3.2 Local Mock

The repository must support local mock mode so frontend development can
continue when the backend server is unavailable.

Recommended config:

```
APP_MODE=mock
DATABASE_PATH=./data/stageposter.db
STORAGE_ROOT=./outputs
SERVER_PORT=8080
```

On first start, the backend should:
- Create `data/` directory
- Create `outputs/` directory
- Create SQLite database
- Run database migrations
- Initialize base styles and output specs
- Load mock posters
- Start the same API

### 3.3 Environment Variable Naming

All config uses `UPPER_SNAKE_CASE`. Use `.env` files. No hardcoded paths.

## 4. GitHub Commit Rules

**Should commit:**
- Database migration definitions
- Initialization data definitions
- `.env.example`
- Mock example posters
- Config templates
- API documentation
- Workflow manifest
- Startup instructions
- Local run scripts

**Should NOT commit:**
- `data/*.db`
- `data/*.db-wal`
- `data/*.db-shm`
- `outputs/projects/`
- `logs/`
- `.env`
- `*.safetensors`
- `*.ckpt`
- `*.pt`
- `*.pth`
- `ComfyUI/output/`

SQLite databases are runtime files, not project source code.

## 5. Public Exposure Rules

Only the StagePoster Go API may be exposed publicly.

ComfyUI must remain private:
- `127.0.0.1:8188`
- Or accessible only from the backend's private network

**Prohibited:**
- Browser → ComfyUI API

**Required:**
- Browser → StagePoster API → ComfyUI

The backend hides ComfyUI node IDs, paths, error details, and queue protocol
from the frontend.

## 6. API Conventions

### 6.1 Base URL

Local:
```
http://localhost:8080/api
```

Remote:
```
https://<backend-host>/api
```

### 6.2 Content-Type

| Scenario | Content-Type |
|---|---|
| Standard request | `application/json` |
| Asset upload | `multipart/form-data` |
| Standard error | `application/json` |
| Image output | Corresponding image MIME type |

> Errors are a plain `{"error": "message"}` envelope with an appropriate HTTP
> status, **not** RFC 9457 `application/problem+json`. The problem+json taxonomy
> in `docs/error-codes.md` is an unimplemented design spec. 500 responses return
> a generic `{"error":"internal server error"}` and log the real cause
> server-side.


### 6.3 Request Headers

| Header | Required | Purpose |
|---|---|---|
| `Accept` | Recommended | Specify response format |
| `Content-Type` | Required when body present | Request format |
| `X-Request-ID` | Optional | Frontend-backend log tracing |
| `Idempotency-Key` | Required for create operations | Prevent duplicate submissions |
| `Authorization` | Depends on deployment | Demo access restriction |

If the frontend does not submit `X-Request-ID`, the backend generates one and
returns it in the response.

### 6.4 Time and IDs

- Times use UTC RFC 3339.
- IDs are opaque strings.
- The frontend must not parse ID structure.
- The frontend must not depend on database auto-increment numbers.
- The frontend must ignore unknown optional response fields.

## 7. Core Resource Relationships

```
Project
 ├── Assets
 ├── Creative Brief Snapshots
 ├── Generation Jobs
 └── Output Assets
```

| Resource | Description |
|---|---|
| `Project` | Represents an event or campaign project |
| `Asset` | User-uploaded person, logo, or reference image |
| `Creative Brief` | Complete requirements snapshot at generation time |
| `Generation Job` | Async generation task |
| `Output Asset` | Final poster, preview, or subsequent video/VJ file |

## 8. API Reference

### 8.1 Health Check

```
GET /health
```

Response:

```json
{
  "status": "ok",
  "comfy": "connected",
  "tokenRequired": false,
  "bindings": {
    "prompt": { "nodeId": "57:27", "inputKey": "text" },
    "seed":   { "nodeId": "57:3",  "inputKey": "seed" }
  }
}
```

### 8.2 Create Generation Task

Core endpoint.

```
POST /api/generate
Headers:
  Content-Type: application/json
  X-Poster-Token: <token> (if configured)
  Idempotency-Key: <unique-key>
```

Body:

```json
{
  "prompt": "A futuristic live concert poster, cinematic stage light, premium fashion editorial composition",
  "seed": 88
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `prompt` | string | ✅ | Generation description |
| `seed` | number | ❌ | Random seed |

Response:

```json
{
  "jobId": "39581fad-fda9-46ca-9c30-fbfc03e7555e",
  "promptId": "39581fad-fda9-46ca-9c30-fbfc03e7555e",
  "status": "queued",
  "seed": 88
}
```

### 8.3 Query Task Result

```
GET /api/generate/{jobId}
```

Response:

```json
{
  "jobId": "job_xxx",
  "status": "succeeded",
  "prompt": "futuristic concert poster",
  "seed": 88,
  "createdAt": "2026-07-21T06:45:00Z",
  "thumbnailUrl": "/api/jobs/job_xxx/outputs/thumbnail"
}
```

### 8.4 List Jobs

```
GET /api/jobs?status=succeeded&limit=20&cursor=xxx
```

Response:

```json
{
  "items": [...],
  "nextCursor": null
}
```

### 8.5 Asset Upload

```
POST /api/assets
Content-Type: multipart/form-data
```

Body: `file` (binary) + `type` (string)

### 8.6 Get Asset

```
GET /api/assets/{assetId}
```

Returns the asset file with appropriate MIME type.

## 9. Error Handling

Errors are returned as a plain JSON envelope with an appropriate HTTP status:

```json
{ "error": "asset not found" }
```

500 responses return a generic `{"error":"internal server error"}` and log the
real cause server-side — filesystem paths and driver internals must not leak to
the client.

> **The RFC 9457 shape below is an unimplemented design proposal**, kept for
> reference. The backend has never emitted `application/problem+json`, and there
> is no `/api/v1` namespace. Do not code the frontend against it.

```json
{
  "type": "https://stageposter.example/problems/asset-not-found",
  "title": "Asset not found",
  "status": 404,
  "detail": "...",
  "instance": "/api/v1/...",
  "code": "ASSET_NOT_FOUND",
  "request_id": "req_01K...",
  "retryable": false
}
```

The code names below remain a useful reference for which conditions the system
distinguishes, even though they are not returned on the wire in this form.

Common error codes:

| Code | HTTP | Meaning |
|---|---|---|
| `ASSET_NOT_FOUND` | 404 | Asset does not exist |
| `VALIDATION_ERROR` | 422 | Invalid request fields |
| `GENERATION_FAILED` | 502 | ComfyUI generation failed |
| `QUEUE_FULL` | 429 | ComfyUI queue full |
| `VLM_UNAVAILABLE` | 503 | vLLM not responding |
