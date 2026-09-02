# StagePoster Error Codes v1.0

> **⚠️ Historical design spec — not the implemented behaviour.**
>
> This document specifies RFC 9457 `application/problem+json` responses under
> `/api/v1/projects/...`. **Neither exists in the backend.** There is no `/api/v1`
> route namespace, and errors are returned as a plain envelope:
>
> ```json
> { "error": "message" }
> ```
>
> with an appropriate HTTP status (`internal/api/server.go:439`). 500 responses
> deliberately return a generic `{"error":"internal server error"}` and log the
> real cause server-side, so that filesystem paths and driver internals do not
> leak.
>
> For the API the frontend should actually code against, see
> **`docs/frontend-api-handoff.md`** (authoritative).
>
> This file is retained as the original error-taxonomy design. The code names and
> HTTP status mapping below are still a useful reference for what errors the
> system distinguishes; the wire format is not.

Error format: RFC 9457 Problem Details
Content-Type: `application/problem+json`

## 1. Standard Structure

```json
{
  "type": "https://stageposter.example/problems/asset-not-found",
  "title": "Asset not found",
  "status": 404,
  "detail": "Asset does not exist or is not available in this project.",
  "instance": "/api/v1/projects/proj_01K.../generations",
  "code": "ASSET_NOT_FOUND",
  "request_id": "req_01K...",
  "retryable": false,
  "job_id": null,
  "errors": []
}
```

### Required fields

| Field | Purpose |
|---|---|
| `type` | Stable problem type URI |
| `title` | Short error name |
| `status` | HTTP status |
| `detail` | Description of the current request error |
| `instance` | API endpoint or resource that errored |
| `code` | Used by frontend logic |
| `request_id` | Log correlation |
| `retryable` | Whether retry is recommended |
| `errors` | Field-level errors |

### Optional fields

`job_id`, `project_id`, `asset_id`, `retry_after_seconds`

### Never return

- Stack traces
- SQL queries
- Local absolute paths
- Environment variables
- Tokens

---

## 2. Field Validation Error

```json
{
  "type": "https://stageposter.example/problems/validation-error",
  "title": "Request validation failed",
  "status": 422,
  "detail": "The creative brief contains invalid fields.",
  "instance": "/api/v1/projects/proj_01K.../generations",
  "code": "VALIDATION_ERROR",
  "request_id": "req_01K...",
  "retryable": false,
  "errors": [
    {
      "field": "brief.event.date",
      "code": "INVALID_DATE",
      "message": "Use YYYY-MM-DD."
    },
    {
      "field": "brief.output.candidate_count",
      "code": "OUT_OF_RANGE",
      "message": "Candidate count must be between 1 and 4."
    }
  ]
}
```

`field` uses dot-path notation from the request body.

---

## 3. HTTP Status Usage

| Status | Scenario |
|---|---|
| 400 | JSON or multipart cannot be parsed |
| 401 | Authentication failure |
| 403 | Insufficient permissions |
| 404 | Resource not found |
| 409 | State conflict or idempotency conflict |
| 413 | File or request too large |
| 415 | Unsupported media type |
| 422 | Field error or unsupported combination |
| 429 | Rate limited or queue full |
| 500 | Unexpected server error |
| 502 | ComfyUI returned abnormal response |

---

## 4. Common Error Codes

| Code | HTTP | Meaning | Retryable |
|---|---|---|---|
| `ASSET_NOT_FOUND` | 404 | Asset does not exist | No |
| `VALIDATION_ERROR` | 422 | Invalid request fields | No |
| `GENERATION_FAILED` | 502 | ComfyUI generation failed | No |
| `QUEUE_FULL` | 429 | ComfyUI queue is full | Yes |
| `VLM_UNAVAILABLE` | 503 | vLLM is not responding | Yes |
| `SESSION_NOT_FOUND` | 404 | AI session does not exist | No |
| `SESSION_TERMINAL` | 409 | Session is already in terminal state | No |
| `CANDIDATE_NOT_READY` | 409 | Candidate is still generating | No |
| `INTERNAL_ERROR` | 500 | Unexpected server error | Yes |
