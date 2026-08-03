# StagePoster Asset Contract v1.0

## Goal

Define how assets are uploaded, validated, stored, preprocessed, and managed.
Storage: server local filesystem + SQLite metadata.

## 1. Core Rules

- Assets are uploaded **once**.
- The backend returns an `asset_id` after upload.
- Generation requests reference `asset_id`.

The frontend **must not** submit:
- Base64-encoded images
- Local file paths
- Server absolute paths
- ComfyUI input paths
- External URLs not imported through the backend

## 2. Asset Types

| Type | Meaning | Formats | Usage |
|---|---|---|---|
| `artist_image` | Person or band photo | PNG, JPEG, WebP | Identity / face control |
| `logo` | Event, brand, or band logo | PNG, WebP, SVG | Final composition |
| `style_reference` | Style reference image | PNG, JPEG, WebP | Style analysis or image conditioning |
| `background_reference` | Background / location reference | PNG, JPEG, WebP | Composition or background conditioning |

Reserved for future use: `audio`, `video`, `mask`, `font`, `document`

## 3. Upload Protocol

**Old approach (deprecated):**

```
POST /api/v1/projects/{project_id}/assets
Content-Type: multipart/form-data
```

**Current approach:**

```
POST /api/assets
Content-Type: multipart/form-data
```

Request body:

```
file: <binary>
type: artist_image | logo | style_reference | background_reference
name: optional display name
```

Response:

```json
{
  "assetId": "asset_01K...",
  "type": "artist_image",
  "filename": "artist.png",
  "sizeBytes": 2048000,
  "mimeType": "image/png",
  "createdAt": "2026-07-29T04:00:00Z"
}
```

## 4. Asset Limits

| Constraint | Value |
|---|---|
| Max file size | 20 MB |
| Accepted formats | PNG, JPEG, WebP, SVG (logos only) |
| Max assets per session | 10 |
| Storage root | `backend/storage/assets/{YYYY}/{MM}/` |

## 5. Asset Lifecycle

```
Upload → Validate → Store → Available for binding
                                        ↓
                              Referenced by poster
                                        ↓
                              Persisted with poster
                                        ↓
                              Retained indefinitely
```

Assets are never deleted during normal operation. If asset cleanup is needed,
implement a separate admin endpoint.

## 6. Frontend Checklist

- [ ] Upload via `POST /api/assets` with `multipart/form-data`
- [ ] Store returned `assetId` in session state
- [ ] Include `assetId` list when creating session or binding assets
- [ ] Never embed image data directly in JSON request bodies
- [ ] Handle 413 (file too large) with user-friendly message
