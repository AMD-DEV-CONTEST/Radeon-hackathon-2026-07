# StagePoster Backend Storage Specification v0.2

## Goal

Give the backend ownership of the full lifecycle: metadata, assets, jobs,
workflows, composition, and the public API.

```
Frontend
   ↓
Go API
   ├── SQLite Metadata
   ├── Asset Storage
   ├── Job Queue
   ├── Workflow Registry
   ├── Poster Composer
   ↓
ComfyUI
   ↓
AMD W7900 GPU
```

ComfyUI handles visual generation. The Go backend owns product logic, tasks,
files, versioning, composition, and the API.

### Job Lifecycle

```
POST /generate
  ↓
INSERT jobs(status=queued)
  ↓
Submit to ComfyUI
  ↓
UPDATE jobs(comfy_prompt_id, status=running)
  ↓
Background worker polls for result
  ↓
Copy file to storage/jobs/{jobId}
  ↓
INSERT outputs
  ↓
UPDATE jobs(status=succeeded)
```

### Backend Restart Recovery

On restart, the backend:
1. Queries `queued` / `running` jobs
2. Reconciles state with ComfyUI
3. Recovers to the correct status

### Job API

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/jobs` | List jobs |
| `GET` | `/api/jobs/{jobId}/outputs` | Get job outputs |
| `POST` | `/api/jobs/{jobId}/cancel` | Cancel a job |
| `POST` | `/api/jobs/{jobId}/retry` | Retry a failed job |

List with pagination:

```
GET /api/jobs?status=succeeded&limit=20&cursor=xxx
```

Response:

```json
{
  "items": [
    {
      "jobId": "job_xxx",
      "status": "succeeded",
      "prompt": "futuristic concert poster",
      "seed": 88,
      "createdAt": "2026-07-21T06:45:00Z",
      "thumbnailUrl": "/api/jobs/job_xxx/outputs/thumbnail"
    }
  ],
  "nextCursor": null
}
```

### Phase 2: Asset Pipeline

After persistence, add asset upload:

```
POST /api/assets
GET  /api/assets/{assetId}
```

Frontend uploads assets first:

```
person photo → asset_person_01
Logo         → asset_logo_01
reference    → asset_reference_01
```

Generation requests reference assets by ID:

```json
{
  "workflow": "poster-reference",
  "prompt": "cinematic live concert poster",
  "seed": 88,
  "assets": {
    "person": "asset_person_01",
    "logo": "asset_logo_01",
    "reference": "asset_reference_01"
  }
}
```

The backend uploads assets to ComfyUI and writes to the corresponding
`LoadImage` nodes.

### Phase 3: Workflow Registry

Support multiple workflows:

```json
{
  "workflow": "poster-text",
  "version": "1.0.0",
  "prompt": "...",
  "seed": 88
}
```

Backend maintains a binding map:

```json
{
  "prompt": { "nodeId": "57:27", "inputKey": "text" },
  "seed":   { "nodeId": "57:3",  "inputKey": "seed" },
  "width":  { "nodeId": "57:13", "inputKey": "width" },
  "height": { "nodeId": "57:13", "inputKey": "height" }
}
```

Auto-detection is suitable for initial smoke testing only. Production
systems should use explicit bindings.

Current bindings already available:

| Field | Node ID | Input Key |
|---|---|---|
| Prompt | `57:27` | `text` |
| Seed | `57:3` | `seed` |
| Width | `57:13` | `width` |
| Height | `57:13` | `height` |

No ComfyUI changes needed — the API can already accept `width` and `height`.
