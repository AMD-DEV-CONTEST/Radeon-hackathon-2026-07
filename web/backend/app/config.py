"""Runtime paths and settings for the Live-Science backend."""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Repo root (Live-Science/) so backend can import modules/...
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

BACKEND_DIR = Path(__file__).resolve().parents[1]
WEB_DIR = BACKEND_DIR.parent
FRONTEND_DIST = WEB_DIR / "frontend" / "dist"

DATA_DIR = Path(os.getenv("LIVE_SCIENCE_DATA_DIR", BACKEND_DIR / "data")).resolve()
OUTPUTS_DIR = DATA_DIR / "outputs"
JOBS_DIR = DATA_DIR / "jobs"
DB_PATH = DATA_DIR / "live_science.db"

HOST = os.getenv("LIVE_SCIENCE_HOST", "127.0.0.1")
PORT = int(os.getenv("LIVE_SCIENCE_PORT", "8000"))

# How many jobs render in parallel (each runs in its own worker thread).
WORKER_COUNT = int(os.getenv("LIVE_SCIENCE_WORKERS", "2"))

# Comma-separated list of allowed CORS origins; "*" allows all.
CORS_ORIGINS = [
    o.strip() for o in os.getenv("LIVE_SCIENCE_CORS_ORIGINS", "*").split(",") if o.strip()
]

# When set, serve the built frontend (web/frontend/dist) from the same port.
SERVE_FRONTEND = os.getenv("LIVE_SCIENCE_SERVE_FRONTEND", "0") == "1"

# ---- Phase 1 (program video) via DeepSeek (OpenAI-compatible API) ----
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

# ---- Local model generation (FLUX / LTX) via ComfyUI ----
COMFYUI_URL = os.getenv("COMFYUI_URL", "http://127.0.0.1:8188").rstrip("/")

# ---- Re_0 three-phase pipeline (phase1 specs + phase2/3 tools) ----
RE_0_DIR = Path(os.getenv("RE_0_DIR", REPO_ROOT / "modules/video_model/Re_0")).resolve()
PHASE1_DIR = RE_0_DIR / "phase1"
PHASE2_DIR = RE_0_DIR / "phase2"
PHASE3_DIR = RE_0_DIR / "phase3"

for _d in (DATA_DIR, OUTPUTS_DIR, JOBS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ---- Authentication (required for public deployment) ----
# Radeon Cloud's rc-tunnel assigns a public URL reachable from the internet;
# per the official guide, the app itself must enforce login. All /api/*
# endpoints except /api/v1/auth/login require the access token below.
AUTH_TOKEN_FILE = DATA_DIR / "auth_token.txt"
AUTH_ENABLED = os.getenv("LIVE_SCIENCE_AUTH_DISABLED", "0") != "1"


def _load_or_create_auth_token() -> str:
    """Token from env, else persisted file, else generate & persist."""
    env_token = os.getenv("LIVE_SCIENCE_AUTH_TOKEN", "").strip()
    if env_token:
        return env_token
    if AUTH_TOKEN_FILE.exists():
        existing = AUTH_TOKEN_FILE.read_text().strip()
        if existing:
            return existing
    import secrets

    token = secrets.token_urlsafe(24)
    AUTH_TOKEN_FILE.write_text(token + "\n")
    try:
        AUTH_TOKEN_FILE.chmod(0o600)
    except OSError:
        pass
    return token


AUTH_TOKEN = _load_or_create_auth_token()
