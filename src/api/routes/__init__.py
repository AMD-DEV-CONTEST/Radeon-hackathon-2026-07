"""HTTP route modules — one per capability.

Each module exports a `router` (APIRouter) with HTTP endpoints for one
generation capability. The main `app` mounts all of them under `/api/...`.
"""
