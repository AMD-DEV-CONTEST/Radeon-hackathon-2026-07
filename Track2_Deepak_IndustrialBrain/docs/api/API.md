# API Reference

All protected Spring endpoints require:

```http
Authorization: Bearer <token>
```

## Authentication

### `POST /api/auth/login`

```json
{"username":"admin","password":"Admin@123"}
```

Returns the JWT, display name, and role.

## Documents

- `GET /api/documents` — list metadata and processing state
- `POST /api/documents` — Admin-only multipart upload using field `file`

Supported: PDF, DOCX, TXT, CSV. Maximum size: 25 MB.

## Dashboard

- `GET /api/dashboard`

Returns document, asset, query, recent-question, and service-health data.

## Knowledge assistant

### `POST /api/chat/query`

```json
{
  "question": "Why did Pump P-101 fail repeatedly in 2025?",
  "assetTag": "P-101"
}
```

Returns answer, mode, confidence, and source citations.

## Assets

- `GET /api/assets/{tag}` — connected Asset 360° evidence
- `POST /api/assets/{tag}/rca` — evidence-linked RCA support brief

## Health

- `GET /api/health`
- `GET http://127.0.0.1:8000/ai/health`

FastAPI interactive documentation is available at `http://127.0.0.1:8000/docs`.

