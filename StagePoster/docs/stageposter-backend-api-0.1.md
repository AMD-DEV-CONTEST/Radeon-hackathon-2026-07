# StagePoster Backend API Reference v0.1

## Public Address

```
Backend: 8080
```

Architecture:

```
Frontend
   ↓ HTTPS
Cloudflare Tunnel
   ↓
Go Poster API
   ↓ localhost / private network
ComfyUI API
   ↓
AMD Radeon W7900 GPU
   ↓
Z-Image Turbo
```

## Health Check

Check if services are online.

**Request**

```
GET /health
```

**Response**

```json
{
  "status": "ok",
  "comfy": "connected",
  "tokenRequired": true,
  "bindings": {
    "prompt": { "nodeId": "57:27", "inputKey": "text" },
    "seed":   { "nodeId": "57:3",  "inputKey": "seed" }
  }
}
```

| Field | Meaning |
|---|---|
| `status` | Backend health |
| `comfy` | ComfyUI GPU service status |
| `prompt node` | Prompt node ID |
| `seed node` | Random seed node |

## Create Generation Task

Core interface.

**Request**

```
POST /api/generate
Headers:
  Content-Type: application/json
  X-Poster-Token: <token> (if configured)
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

**Response**

```json
{
  "jobId": "39581fad-fda9-46ca-9c30-fbfc03e7555e",
  "promptId": "39581fad-fda9-46ca-9c30-fbfc03e7555e",
  "status": "queued",
  "seed": 88
}
```

## Query Task Result

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
