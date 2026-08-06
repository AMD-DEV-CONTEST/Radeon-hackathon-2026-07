"""MedGlass FastAPI server.

Endpoints
---------
GET  /health           server + GPU status
GET  /models           list available LLM models (OpenRouter/Ollama)
GET  /backends         list backend status (active + availability)
WS   /ws/audio         receive 16kHz PCM chunks, stream back transcripts
WS   /ws/video         receive frames (MJPEG/JPEG), return detections/OCR
POST /generate_note    trigger SOAP note generation from session context
POST /hud/update       push a HUD payload to connected clients
GET  /session/note     current built note for this session
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import re

# Redact API keys / tokens in log output so secrets never leak.
_SENSITIVE = ("api_key", "token", "password", "secret")
_REDACT_RE = re.compile(r"""(?i)(["']?(?:api_key|token|password|secret)["']?\s*[:=]\s*["']?)([^"',}\s]+)(["'}],?)""")
import os
import secrets
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from audio_handler import ChunkBuffer, WhisperTranscriber
from config import CONFIG
from context_builder import sanitize_phi
from ehr_export import export
from hud_output import HUDOutput, split_soap
from llm_handler import LLMHandler
from notes_store import delete_note, get_note, list_notes, mirror_latest, save_note
from photo_store import photo_mime, photo_path, read_photo, save_photo
from retention import purge_old
from tasks_store import assign as tasks_assign
from tasks_store import list_tasks as tasks_list
from tasks_store import set_done as tasks_set_done
import totp as totp_lib
from users import create_user as users_create
from users import delete_user as users_delete
from users import get_user as users_get
from users import list_users as users_list
from users import record_failure as users_record_failure
from users import seed as seed_users
from users import set_role as users_set_role
from users import set_totp as users_set_totp
from users import set_totp_pending as users_set_totp_pending
from users import confirm_totp as users_confirm_totp
from users import cancel_totp_pending as users_cancel_totp_pending
from users import verify as verify_user
import audit as audit_log
from utils import MedGlassError, detect_gpu, random_patient_name, setup_logging
from video_handler import FrameResult, VideoProcessor

setup_logging()
LOG = logging.getLogger("medglass.server")

STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="MedGlass", version="1.0.0", docs_url="/docs")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# --- Browser login (cookie session) ---------------------------------------
# The notes dashboard is the default page and sits behind per-user
# username/password login. Passwords are scrypt-hashed (output/users.json),
# sessions are random tokens (persisted to output/.sessions.json so restarts
# don't orphan the browser's cookie), and TOTP MFA is optional per user.

LOGIN_USER = CONFIG.get("login_user") or "clinician"
LOGIN_PASSWORD = CONFIG.get("login_password") or ""
SESSION_IDLE = int(CONFIG.get("session_idle_minutes") or 30) * 60
SESSION_MAX = 12 * 3600
MAX_ATTEMPTS = int(CONFIG.get("max_login_attempts") or 5)
LOCK_MINUTES = int(CONFIG.get("lock_minutes") or 15)
_LOGIN_RATE_WINDOW = 15 * 60
_LOGIN_RATE_LIMIT = 30
_MFA_TTL = 5 * 60
ALLOWED_IPS = [ip.strip() for ip in str(CONFIG.get("allowed_ips") or "").split(",")
               if ip.strip()]
SESSION_FILE = Path("output") / ".sessions.json"

# token -> {"expires": float, "last": float, "user": str, "csrf": str}
_sessions: dict[str, dict] = {}
# ip -> [timestamps of recent login attempts]
_login_attempts: dict[str, list[float]] = {}
# pending-id -> {"user": str, "expires": float} for MFA second stage
_pending_mfa: dict[str, dict] = {}


def _load_sessions() -> None:
    global _sessions
    try:
        if SESSION_FILE.exists():
            data = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
            now = time.time()
            _sessions = {k: v for k, v in data.items()
                         if v.get("expires", 0) > now and v.get("last", 0) > now}
            if len(_sessions) < len(data):
                _save_sessions()
    except Exception as exc:
        LOG.warning("session persistence load failed: %s", exc)
        _sessions = {}


def _save_sessions() -> None:
    try:
        SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
        SESSION_FILE.write_text(json.dumps(_sessions), encoding="utf-8")
        SESSION_FILE.chmod(0o600)
    except Exception as exc:
        LOG.warning("session persistence save failed: %s", exc)


def _client_ip(request: Request) -> str:
    """Client IP, honouring the proxy (ngrok -> Mentra -> edge)."""
    fwd = request.headers.get("X-Forwarded-For") or ""
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else ""


def _ip_allowed(request: Request) -> bool:
    if not ALLOWED_IPS:
        return True
    return _client_ip(request) in ALLOWED_IPS


def _issue_session(user: str) -> str:
    token = secrets.token_hex(32)
    _sessions[token] = {
        "expires": time.time() + SESSION_MAX,
        "last": time.time() + SESSION_IDLE,
        "user": user,
        "csrf": secrets.token_hex(16),
    }
    _save_sessions()
    return token


def _session_user(request: Request) -> str | None:
    token = request.cookies.get("mg_session") or ""
    rec = _sessions.get(token)
    if not rec:
        return None
    now = time.time()
    if rec["expires"] < now or rec["last"] < now:
        _sessions.pop(token, None)
        _save_sessions()
        return None
    rec["last"] = now + SESSION_IDLE
    return rec["user"]


def _is_logged_in(request: Request) -> bool:
    return _session_user(request) is not None


def _csrf_for(request: Request) -> str | None:
    token = request.cookies.get("mg_session") or ""
    rec = _sessions.get(token)
    return rec["csrf"] if rec else None


def _dashboard_authorized(request) -> bool:
    """Token gate for patient data on the dashboard/notes API.

    No token configured -> open (localhost convenience). With
    MEDGLASS_DASHBOARD_TOKEN set, require ?token= or X-Dashboard-Token.
    """
    token = CONFIG.get("dashboard_token") or ""
    if not token:
        return True
    supplied = (request.query_params.get("token")
                or request.headers.get("X-Dashboard-Token") or "")
    return supplied == token


def _actor(request: Request) -> str:
    return _session_user(request) or "service"


def _authorized(request: Request) -> bool:
    """Browser cookie login OR the legacy dashboard token (Mentra app)."""
    return _is_logged_in(request) or _dashboard_authorized(request)


def _role(request: Request) -> str:
    """Current user's role: admin | clinician | '' (not authenticated)."""
    user = _session_user(request)
    if user:
        rec = users_get(user)
        return (rec or {}).get("role", "clinician")
    if _dashboard_authorized(request):
        return "admin"
    return ""


def _require_admin(request: Request):
    return JSONResponse({"error": "admin role required"}, status_code=403)


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    """IP allow-list + CSRF double-submit for browser sessions."""
    if not _ip_allowed(request):
        audit_log.log("blocked_ip", actor=_actor(request) or "unknown",
                      ip=_client_ip(request))
        return JSONResponse({"error": "not allowed from this network"},
                            status_code=403)
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        if request.url.path != "/login":
            user = _session_user(request)
            if user and not _dashboard_authorized(request):
                supplied = request.headers.get("X-CSRF-Token") or ""
                expected = _csrf_for(request) or ""
                if not supplied or not secrets.compare_digest(supplied, expected):
                    return JSONResponse({"error": "invalid or missing CSRF token"},
                                        status_code=403)
    response = await call_next(request)
    # Never let the browser cache PHI pages/APIs: no-store is what stops the
    # back/forward cache from showing the dashboard after logout (backdoor).
    if request.url.path.startswith("/static"):
        # Always revalidate static assets (ETag) so UI fixes are picked up
        # instead of the browser serving a stale cached .js/.html forever.
        response.headers["Cache-Control"] = "no-cache"
    else:
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
    return response


@app.get("/")
async def root(request: Request) -> FileResponse:
    if not _authorized(request):
        return FileResponse(STATIC_DIR / "login.html")
    # Default landing page is the notes dashboard (healthcare IT style).
    return FileResponse(STATIC_DIR / "dashboard.html")


@app.get("/dashboard")
async def dashboard(request: Request) -> FileResponse:
    if not _authorized(request):
        return FileResponse(STATIC_DIR / "login.html")
    return FileResponse(STATIC_DIR / "dashboard.html")


@app.get("/live")
async def live(request: Request) -> FileResponse:
    if not _authorized(request):
        return FileResponse(STATIC_DIR / "login.html")
    return FileResponse(STATIC_DIR / "index.html")


def _login_response_ok(user: str, request: Request, resp: JSONResponse) -> JSONResponse:
    ip = _client_ip(request)
    audit_log.log("login_ok", actor=user, ip=ip)
    _login_attempts.pop(ip, None)
    csrf = _issue_session(user)
    resp.set_cookie("mg_session", csrf, max_age=SESSION_MAX,
                    httponly=True, samesite="lax")
    resp.set_cookie("mg_csrf", _sessions[csrf]["csrf"], max_age=SESSION_MAX,
                    httponly=False, samesite="lax")
    return resp


@app.post("/login")
async def login(request: Request):
    if not _ip_allowed(request):
        return JSONResponse({"error": "not allowed from this network"}, status_code=403)
    ip = _client_ip(request)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid request"}, status_code=400)
    username = str(body.get("username") or "")
    password = str(body.get("password") or "")
    code = str(body.get("code") or "")
    pending = str(body.get("pending") or "")

    # MFA second stage: verify the one-time code for a pending login.
    if code or pending:
        rec = _pending_mfa.get(pending) if pending else None
        if not rec or rec["expires"] < time.time():
            return JSONResponse({"error": "session expired, sign in again"},
                                status_code=400)
        user = rec["user"]
        stored = users_get(user) or {}
        if not stored.get("totp_secret") or not totp_lib.verify(
                stored["totp_secret"], code):
            audit_log.log("login_mfa_failed", actor=user, ip=ip)
            await asyncio.sleep(0.3)
            return JSONResponse({"error": "invalid two-factor code"},
                                status_code=401)
        audit_log.log("login_mfa_ok", actor=user, ip=ip)
        _pending_mfa.pop(pending, None)
        return _login_response_ok(user, request, JSONResponse({"ok": True}))

    # Stage 1: password. Rate limit per real client IP.
    now = time.time()
    stamps = [t for t in _login_attempts.get(ip, []) if now - t < _LOGIN_RATE_WINDOW]
    if len(stamps) >= _LOGIN_RATE_LIMIT:
        retry = int(_LOGIN_RATE_WINDOW - (now - stamps[0])) or 1
        audit_log.log("login_rate_limited", actor=username or "unknown", ip=ip)
        return JSONResponse({"error": "too many attempts",
                             "rate_limited": True,
                             "retry_after": retry}, status_code=429)
    stamps.append(now)
    _login_attempts[ip] = stamps[-_LOGIN_RATE_LIMIT:]

    result = verify_user(username, password)
    if result is None:
        await asyncio.sleep(0.5)
        audit_log.log("login_failed", actor=username, detail="unknown user", ip=ip)
        return JSONResponse({"error": "invalid credentials"}, status_code=401)
    if result.get("locked"):
        audit_log.log("login_blocked", actor=username, detail="account locked", ip=ip)
        return JSONResponse({"error": "account temporarily locked",
                             "locked": True}, status_code=403)
    if result.get("failed"):
        users_record_failure(username, MAX_ATTEMPTS, LOCK_MINUTES)
        audit_log.log("login_failed", actor=username, detail="wrong password", ip=ip)
        return JSONResponse({"error": "invalid credentials"}, status_code=401)

    if result.get("totp_enabled"):
        pid = secrets.token_hex(12)
        _pending_mfa[pid] = {"user": username, "expires": time.time() + _MFA_TTL}
        audit_log.log("login_password_ok", actor=username, detail="mfa pending", ip=ip)
        return JSONResponse({"ok": False, "mfa_required": True, "pending": pid})

    return _login_response_ok(username, request, JSONResponse({"ok": True}))


@app.post("/logout")
async def logout(request: Request):
    token = request.cookies.get("mg_session")
    user = ""
    if token:
        rec = _sessions.get(token)
        user = rec["user"] if rec else ""
        _sessions.pop(token, None)
        _save_sessions()
    audit_log.log("logout", actor=user, ip=_client_ip(request))
    resp = JSONResponse({"ok": True})
    resp.delete_cookie("mg_session")
    resp.delete_cookie("mg_csrf")
    return resp


# --- User / MFA management (admin) ----------------------------------------

@app.get("/users")
async def users_index(request: Request) -> dict:
    if _role(request) != "admin":
        return _require_admin(request)
    audit_log.log("users_list", actor=_actor(request), ip=_client_ip(request))
    return {"users": users_list()}


@app.post("/users")
async def users_upsert(request: Request) -> dict:
    """Create / update an account. Body: {username, password?, role?}."""
    if _role(request) != "admin":
        return _require_admin(request)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid JSON"}, status_code=400)
    username = str(body.get("username") or "").strip()
    if not username or not username.replace("_", "").replace("-", "").isalnum():
        return JSONResponse({"error": "invalid username"}, status_code=400)
    role = str(body.get("role") or "clinician")
    password = str(body.get("password") or "")
    existing = users_get(username)
    if existing and not password:
        if not users_set_role(username, role):
            return JSONResponse({"error": f"invalid role {role!r}"}, status_code=400)
        return {"ok": True, "users": users_list()}
    if not password or len(password) < 4:
        return JSONResponse({"error": "password required (min 4 chars)"},
                            status_code=400)
    users_create(username, password, role)
    audit_log.log("user_upsert", actor=_actor(request), target=username,
                  detail=f"role={role}", ip=_client_ip(request))
    return {"ok": True, "users": users_list()}


@app.delete("/users/{username}")
async def users_remove(username: str, request: Request) -> dict:
    if _role(request) != "admin":
        return _require_admin(request)
    if username == _session_user(request):
        return JSONResponse({"error": "cannot delete your own account"},
                            status_code=400)
    if not users_delete(username):
        return JSONResponse({"error": f"user {username!r} not found"},
                            status_code=404)
    audit_log.log("user_delete", actor=_actor(request), target=username,
                  ip=_client_ip(request))
    return {"ok": True, "users": users_list()}


@app.get("/me")
async def me(request: Request) -> dict:
    user = _session_user(request)
    if not user:
        return _auth_response()
    rec = users_get(user) or {}
    return {"username": user, "role": rec.get("role", "clinician"),
            "totp_enabled": bool(rec.get("totp_enabled", False))}


@app.post("/me/mfa/enable")
async def mfa_enable(request: Request) -> dict:
    """Stage a new TOTP secret; it becomes active only after confirm."""
    user = _session_user(request)
    if not user:
        return _auth_response()
    secret = totp_lib.generate_secret()
    users_set_totp_pending(user, secret)
    audit_log.log("mfa_enable", actor=user, ip=_client_ip(request))
    return {"ok": True, "secret": secret,
            "otpauth_uri": totp_lib.otpauth_uri(secret, user)}


@app.post("/me/mfa/confirm")
async def mfa_confirm(request: Request) -> dict:
    """Verify a code from the authenticator app; activates TOTP on success."""
    user = _session_user(request)
    if not user:
        return _auth_response()
    try:
        body = await request.json()
    except Exception:
        body = {}
    code = str(body.get("code") or "")
    rec = users_get(user) or {}
    pending = rec.get("totp_pending") or ""
    if not pending or not totp_lib.verify(pending, code):
        audit_log.log("mfa_confirm_failed", actor=user, ip=_client_ip(request))
        return JSONResponse({"error": "invalid two-factor code"}, status_code=400)
    users_confirm_totp(user)
    audit_log.log("mfa_confirmed", actor=user, ip=_client_ip(request))
    return {"ok": True, "totp_enabled": True}


@app.post("/me/mfa/cancel")
async def mfa_cancel(request: Request) -> dict:
    user = _session_user(request)
    if user:
        users_cancel_totp_pending(user)
    return {"ok": True}


@app.post("/me/mfa/disable")
async def mfa_disable(request: Request) -> dict:
    user = _session_user(request)
    if not user:
        return _auth_response()
    users_set_totp(user, None)
    audit_log.log("mfa_disable", actor=user, ip=_client_ip(request))
    return {"ok": True}


@app.post("/admin/purge")
async def admin_purge(request: Request) -> dict:
    """Manually run the retention purge (admin only)."""
    if _role(request) != "admin":
        return _require_admin(request)
    days = int(request.query_params.get("days") or 0) or int(CONFIG.get("retention_days") or 365)
    result = purge_old(days)
    audit_log.log("admin_purge", actor=_actor(request), detail=f"days={days}",
                  ip=_client_ip(request))
    return {"ok": True, "result": result}


class SessionState:
    """Per-connection working state: transcript buffer + visual findings."""

    def __init__(self) -> None:
        self.audio = ChunkBuffer(CONFIG["sample_rate"],
                                 CONFIG["chunk_seconds"],
                                 CONFIG["overlap_seconds"])
        self.transcript: list[str] = []
        self.visual_findings: list[dict] = []
        self.photos: list[dict] = []
        self.note: str = ""
        self.patient_name: str = ""
        self.last_processed_window: bytes = b""
        self.last_transcribed_window: bytes = b""
        self.last_transcribe_ts: float = 0.0


class SessionManager:
    def __init__(self) -> None:
        self.sessions: dict[str, SessionState] = {}

    def get(self, sid: str) -> SessionState:
        return self.sessions.setdefault(sid, SessionState())

    def reset(self, sid: str) -> None:
        self.sessions[sid] = SessionState()


manager = SessionManager()
hud = HUDOutput()

# Lazy singletons so the server boots without models present.
_whisper: WhisperTranscriber | None = None
_vision: VideoProcessor | None = None
_llm: LLMHandler | None = None


def get_whisper() -> WhisperTranscriber:
    global _whisper
    if _whisper is None:
        _whisper = WhisperTranscriber(CONFIG)
    return _whisper


def get_vision() -> VideoProcessor:
    global _vision
    if _vision is None:
        _vision = VideoProcessor(CONFIG)
    return _vision


def get_llm() -> LLMHandler:
    global _llm
    if _llm is None:
        _llm = LLMHandler(CONFIG)
    return _llm


# ---------------------------------------------------------------------------
# REST
# ---------------------------------------------------------------------------

@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "gpu": detect_gpu(),
        "ollama": _ollama_status(),
        "models": {
            "whisper": bool(Path(CONFIG["whisper_model"]).exists()),
            "yolo": _vision_model_exists(),
            "llm": _llm_model_exists(),
        },
        "backends": {
            "whisper": _whisper_backend_name(),
            "llm": _llm_backend_name(),
            "vision": _vision_backend_name(),
        },
        "model_list": await _model_list(),
        "hud_endpoint": bool(CONFIG["hud_endpoint"]),
    }


def _openrouter_models() -> list[dict]:
    """Fetch available models from OpenRouter's API."""
    api_key = CONFIG.get("openrouter_api_key") or os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        raise MedGlassError("No OpenRouter API key configured")
    url = CONFIG.get("openrouter_url", "https://openrouter.ai/api/v1")
    req = urllib.request.Request(
        f"{url}/models",
        headers={
            "Authorization": f"Bearer {api_key}",
            "HTTP-Referer": CONFIG.get("openrouter_referer", "http://localhost:8100"),
            "X-Title": CONFIG.get("openrouter_title", "MedGlass"),
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    models = []
    for m in data.get("data", []):
        models.append({
            "id": m.get("id"),
            "name": m.get("name"),
            "context_length": m.get("context_length"),
            "pricing": m.get("pricing"),
            "architecture": {
                "modality": m.get("architecture", {}).get("modality"),
                "tokenizer": m.get("architecture", {}).get("tokenizer"),
            },
            "created": m.get("created"),
        })
    return sorted(models, key=lambda x: x.get("id", ""))


def _ollama_models() -> list[dict]:
    """List models available in local Ollama."""
    ollama = shutil.which("ollama")
    if ollama is None:
        return []
    try:
        out = subprocess.run(
            [ollama, "list"], capture_output=True, text=True, timeout=10,
        )
        if out.returncode != 0:
            return []
        models = []
        lines = out.stdout.splitlines()[1:]  # skip header
        for line in lines:
            parts = line.split()
            if len(parts) >= 2:
                models.append({
                    "id": parts[0],
                    "name": parts[0],
                    "size": parts[1] if len(parts) > 1 else None,
                    "modified": parts[2] if len(parts) > 2 else None,
                })
        return sorted(models, key=lambda x: x.get("id", ""))
    except (OSError, subprocess.SubprocessError):
        return []


async def _model_list() -> list[dict]:
    """List available LLM models for the active backend."""
    backend = CONFIG.get("llm_backend", "auto")
    if backend == "openrouter" or backend == "auto":
        try:
            return _openrouter_models()
        except Exception as exc:
            LOG.warning("Failed to list OpenRouter models: %s", exc)
            return []
    if backend == "ollama" or backend == "auto":
        models = _ollama_models()
        if models:
            return models
    # For other backends (cli, template), no remote model list available.
    return []


def _ollama_status() -> dict:
    """Report whether local Ollama is up and whether it runs on the GPU."""
    status = {"reachable": False, "gpu": False, "model": None}
    ollama = shutil.which("ollama")
    if ollama is None:
        return status
    try:
        out = subprocess.run(
            [ollama, "ps"], capture_output=True, text=True, timeout=10,
        )
        if out.returncode != 0:
            return status
        lines = out.stdout.splitlines()
        status["reachable"] = True
        if len(lines) >= 2:
            header = lines[0].split()
            vals = lines[1].split()

            def col(name: str, default: str = "") -> str:
                return vals[header.index(name)] \
                    if name in header and header.index(name) < len(vals) \
                    else default

            status["model"] = col("NAME") or None
            try:
                ip = header.index("PROCESSOR")
                processor = " ".join(vals[ip:ip + 2])
            except ValueError:
                processor = ""
            status["gpu"] = "gpu" in processor.lower()
    except (OSError, subprocess.SubprocessError):
        pass
    return status


def _whisper_backend_name() -> str:
    if Path(CONFIG["whisper_bin"]).exists():
        return "whisper.cpp (ROCm)"
    try:
        import pywhispercpp  # noqa: F401
        return "pywhispercpp (CPU)"
    except ImportError:
        return "none"


def _llm_model_exists() -> bool:
    if CONFIG.get("ollama_model"):
        return True
    return Path(CONFIG["llama_model"]).exists()


def _llm_backend_name() -> str:
    if CONFIG.get("llm_backend") == "ollama":
        return f"ollama {CONFIG['ollama_model']} (local)"
    try:
        from llm_handler import build_backend
        backend = build_backend()
        return type(backend).__name__.strip("_")
    except Exception:
        return "template (no model)"


def _vision_backend_name() -> str:
    if _vision_model_exists():
        return "yolov8n-seg"
    return "none"


def _vision_model_exists() -> bool:
    from pathlib import Path
    return Path(CONFIG["yolo_model"]).exists()


@app.get("/models")
async def models() -> dict:
    """List available LLM models for the active backend."""
    return {
        "backend": _llm_backend_name(),
        "models": await _model_list(),
    }


@app.get("/backends")
async def backends() -> dict:
    """List all available backend types and their status."""
    return {
        "active": CONFIG.get("llm_backend", "auto"),
        "configured": {
            "whisper": _whisper_backend_name(),
            "llm": _llm_backend_name(),
            "vision": _vision_backend_name(),
        },
        "ollama_reachable": _ollama_status()["reachable"],
        "openrouter_key_set": bool(
            CONFIG.get("openrouter_api_key") or
            os.environ.get("OPENROUTER_API_KEY")
        ),
    }


class GenerateRequest(BaseModel):
    session_id: str = "default"
    stream: bool = False
    source: str | None = None        # web | mentra | simulator | api
    patient_id: str = ""
    provider: str = ""


def _infer_source(session_id: str) -> str:
    if session_id == "web":
        return "web"
    if session_id.startswith(("mentra", "sim")):
        return session_id.split("_")[0] if "_" in session_id else "mentra"
    return "mentra"


@app.post("/generate_note")
async def generate_note(req: GenerateRequest) -> Any:
    state = manager.get(req.session_id)
    # Ensure the tail of captured speech is transcribed before saving so a
    # session never loses the last words (streaming is rate-limited).
    await _flush_audio(state)
    transcript = "\n".join(state.transcript)
    has_visual = bool(state.visual_findings) or bool(state.photos)
    if not transcript.strip() and not has_visual:
        return JSONResponse({"error": "no transcript or photos for session"},
                            status_code=400)
    try:
        llm = get_llm()
    except MedGlassError as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)

    try:
        note = llm.generate(transcript, state.visual_findings,
                            patient_name=(req.patient_id or None) or None)
    except MedGlassError as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)
    state.note = note
    _store_note(state, note, req)
    sections = split_soap(note)
    hud.note_complete(note)
    return {"note": note, "sections": sections}


class TranscriptIngest(BaseModel):
    session_id: str = "default"
    text: str
    confidence: float | None = None
    speaker: str | None = None


@app.get("/session/name")
async def session_name(session_id: str = "default") -> dict:
    """Assign/return a stable synthetic patient name for the demo session.

    Used by the live glasses page so it can announce the patient name over TTS
    ("Session started. Patient Emma Wilson.") at the same name the SOAP note
    records. The name is a random synthetic patient (never a real person) and
    becomes that session's patient_id when the note is stored.
    """
    state = manager.get(session_id)
    if not state.patient_name:
        state.patient_name = random_patient_name()
    return {"patient_id": state.patient_name}


@app.post("/ingest/transcript")
async def ingest_transcript(req: TranscriptIngest) -> dict:
    """Append a transcript line (e.g. from MentraOS cloud STT) to a session."""
    text = req.text.strip()
    if not text:
        return {"ok": False, "error": "empty text"}
    state = manager.get(req.session_id)
    if state.transcript:
        text = _dedup_new(state.transcript[-1], text)
    if text:
        state.transcript.append(text)
    hud.status("Note building...", confidence=req.confidence)
    return {"ok": True, "lines": len(state.transcript)}


class VisionIngest(BaseModel):
    session_id: str = "default"
    image_b64: str
    size: str = "medium"       # ignored; server uses frame as-is


class AudioIngest(BaseModel):
    session_id: str = "default"
    pcm_b64: str
    sample_rate: int = 16000
    final: bool = False


@app.post("/ingest/audio")
async def ingest_audio(req: AudioIngest) -> dict:
    """Accept raw 16-bit PCM (base64) from the MentraOS app for on-device
    whisper transcription (MEDGLASS_USE_OWN_WHISPER=1)."""
    pcm = base64.b64decode(req.pcm_b64)
    if req.sample_rate != CONFIG["sample_rate"]:
        return {"ok": False, "error": f"expected 16 kHz, got {req.sample_rate}"}
    state = manager.get(req.session_id)
    state.audio.push(pcm)
    window = state.audio.window_bytes()
    now = time.monotonic()
    gap = CONFIG.get("whisper_min_gap_seconds", 1.0)
    if (window == state.last_processed_window or len(window) == 0
            or now - state.last_transcribe_ts < gap):
        return {"ok": True, "queued": False}
    state.last_processed_window = window
    state.last_transcribe_ts = now

    async def job():
        await _transcribe_window(state, window)

    asyncio.get_running_loop().create_task(job())
    return {"ok": True, "queued": True}


@app.post("/vision/process")
async def vision_process(req: VisionIngest) -> Any:
    """Run the vision / OCR pipeline on a photo (base64 JPEG) from glasses.

    The photo is saved and tied to the session so the note's dashboard can
    show the pictures belonging to the case, and a visual finding is recorded
    so captured photos appear under the note's Objective section.
    """
    try:
        result = _process_frame_message(req.image_b64)
    except MedGlassError as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)
    payload = asdict(result)
    findings = []
    for det in result.detections:
        if det.kind == "medication" and det.ocr_text:
            findings.append({"kind": "medication", "detail": det.ocr_text})
            manager.get(req.session_id).visual_findings.append(findings[-1])

    photo = None
    try:
        photo = save_photo(
            session_id=req.session_id,
            original_jpeg=base64.b64decode(req.image_b64),
            detections=findings,
        )
        state = manager.get(req.session_id)
        state.photos.append(photo)
        photo_finding = {
            "kind": "photo",
            "detail": (f"{len(findings)} medication item(s) detected"
                       if findings else "photo captured"),
            "original": photo["original"],
        }
        findings.append(photo_finding)
        state.visual_findings.append(photo_finding)
    except Exception as exc:
        LOG.warning("failed to store photo: %s", exc)

    payload["findings"] = findings
    payload["photo"] = photo
    payload["session_id"] = req.session_id
    return payload


@app.get("/generate_note/stream")
async def generate_note_stream(session_id: str = "default"):
    """SSE stream of the SOAP note as tokens arrive from the GPU."""
    from fastapi.responses import StreamingResponse
    state = manager.get(session_id)
    transcript = "\n".join(state.transcript)

    async def gen():
        try:
            llm = get_llm()
        except MedGlassError as exc:
            yield f"data: {json.dumps({'error': str(exc)})}\n\n"
            return
        chunks: list[str] = []
        try:
            for token in llm.generate_stream(transcript,
                                             state.visual_findings,
                                             patient_name=(req.patient_id or None) or None):
                chunks.append(token)
                yield f"data: {json.dumps({'token': token})}\n\n"
            note = "".join(chunks)
            state.note = note
            _store_note(state, note, GenerateRequest(
                session_id=session_id, source="mentra"))
            hud.note_complete(note)
            yield f"data: {json.dumps({'done': True, 'note': note})}\n\n"
        except MedGlassError as exc:
            yield f"data: {json.dumps({'error': str(exc)})}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.post("/hud/update")
async def hud_update(payload: dict) -> dict:
    from hud_output import HUDMessage
    hud._send(HUDMessage(kind=payload.get("kind", "status"),
                         title=payload.get("title", "MedGlass"),
                         body=payload.get("body", "")))
    return {"ok": True}


@app.get("/session/{session_id}/note")
async def get_session_note(session_id: str = "default") -> dict:
    state = manager.get(session_id)
    return {"note": state.note,
            "transcript": "\n".join(state.transcript),
            "visual_findings": state.visual_findings}


@app.post("/session/{session_id}/reset")
async def reset_session(session_id: str = "default") -> dict:
    manager.reset(session_id)
    return {"ok": True}


# ---------------------------------------------------------------------------
# WebSockets
# ---------------------------------------------------------------------------

@app.websocket("/ws/audio")
async def ws_audio(websocket: WebSocket) -> None:
    await websocket.accept()
    sid = websocket.query_params.get("session_id", "default")
    state = manager.get(sid)
    LOG.info("audio ws open: %s", sid)
    rx_bytes = 0
    try:
        while True:
            raw = await websocket.receive_bytes()
            if rx_bytes == 0:
                LOG.info("audio ws %s: first audio bytes received (%d)",
                         sid, len(raw))
            rx_bytes += len(raw)
            _handle_audio_chunk(websocket, state, raw)
    except WebSocketDisconnect:
        LOG.info("audio ws closed: %s (received %d bytes total)",
                 sid, rx_bytes)


# Serialize whisper runs: concurrent whisper-cli subprocesses on one GPU
# contend and can hang. Windows arriving while a transcription is in flight
# are skipped — the next window includes this audio, so nothing is lost.
_whisper_lock = asyncio.Lock()


async def _transcribe_window(state: SessionState, window: bytes,
                             wait: bool = False) -> str | None:
    """Transcribe one audio window (off the event loop, serialized) and
    append any new text to the session transcript. Returns the added text,
    or None if nothing new was transcribed."""
    if wait:
        await _whisper_lock.acquire()
    else:
        try:
            await asyncio.wait_for(_whisper_lock.acquire(), timeout=0.05)
        except asyncio.TimeoutError:
            return None
    try:
        if window == state.last_transcribed_window:
            return None
        try:
            text = await asyncio.to_thread(get_whisper().transcribe, window)
        except MedGlassError as exc:
            LOG.warning("whisper transcription failed: %s", exc)
            return None
    finally:
        _whisper_lock.release()
    LOG.info("transcribe: window=%d bytes -> %r", len(window),
             (text or "")[:80])
    if not text:
        return None
    text = _dedup_new(state.transcript[-1] if state.transcript else "", text)
    if not text:
        return None
    state.transcript.append(text)
    state.last_transcribed_window = window
    hud.status("Note building...", confidence=_estimate_confidence(text))
    return text


def _handle_audio_chunk(websocket: WebSocket, state: SessionState,
                        raw: bytes) -> None:
    """Append PCM, transcribe when a new window is available."""
    state.audio.push(raw)
    window = state.audio.window_bytes()
    now = time.monotonic()
    gap = CONFIG.get("whisper_min_gap_seconds", 1.0)
    if (window == state.last_processed_window or len(window) == 0
            or now - state.last_transcribe_ts < gap):
        return
    state.last_processed_window = window
    state.last_transcribe_ts = now

    async def job():
        added = await _transcribe_window(state, window)
        if added:
            try:
                await websocket.send_json({
                    "type": "transcript",
                    "text": added,
                    "cumulative": "\n".join(state.transcript),
                })
            except Exception:
                pass  # socket closed mid-transcribe; transcript is kept

    asyncio.get_running_loop().create_task(job())


async def _flush_audio(state: SessionState) -> None:
    """Final transcription pass before saving: transcribe whatever audio is
    buffered if it hasn't been transcribed yet, so the tail of a recording
    is never lost when the session is saved."""
    window = state.audio.window_bytes()
    if not window or window == state.last_transcribed_window:
        return
    added = await _transcribe_window(state, window, wait=True)
    if added:
        LOG.info("flush transcription added %d chars", len(added))


def _dedup_new(prev: str, new: str) -> str:
    """Strip the overlapping prefix of `new` already present at the tail of
    `prev` (whisper windows overlap by ~1s)."""
    prev_tail = prev[-80:].rstrip()
    max_match = min(len(prev_tail), len(new))
    for n in range(max_match, 0, -1):
        if prev_tail[-n:] == new[:n]:
            result = new[n:]
            # trim to a word boundary
            i = result.find(" ")
            return result[i + 1:] if i >= 0 else result
    return new


def _estimate_confidence(text: str) -> float:
    """Placeholder confidence heuristic based on transcript length."""
    words = len(text.split())
    if words < 8:
        return 0.5
    return min(0.98, 0.5 + words * 0.02)


@app.websocket("/ws/video")
async def ws_video(websocket: WebSocket) -> None:
    await websocket.accept()
    sid = websocket.query_params.get("session_id", "default")
    state = manager.get(sid)
    LOG.info("video ws open: %s", sid)
    try:
        while True:
            message = await websocket.receive_json()
            if message.get("type") == "frame":
                result = _process_frame_message(message["data"])
                payload = asdict(result)
                await websocket.send_json(payload)
                for det in result.detections:
                    if det.kind == "medication" and det.ocr_text:
                        state.visual_findings.append({
                            "kind": "medication",
                            "detail": det.ocr_text,
                        })
                        hud.alert("Medication detected: "
                                  + det.ocr_text[:80])
            elif message.get("type") == "event":
                # e.g. {"event": "capture", "reason": "rash"}
                state.visual_findings.append({
                    "kind": message.get("reason", "capture"),
                    "detail": message.get("note", ""),
                })
                await websocket.send_json({"ok": True})
    except WebSocketDisconnect:
        LOG.info("video ws closed: %s", sid)


def _process_frame_message(data: str) -> FrameResult:
    """Decode a base64 JPEG frame and run the vision pipeline."""
    try:
        jpeg = base64.b64decode(data)
        frame = np.frombuffer(jpeg, dtype=np.uint8)
        img = cv2_imdecode(frame)
    except Exception as exc:
        LOG.warning("frame decode failed: %s", exc)
        return FrameResult(metadata={"error": str(exc)})
    return get_vision().process_frame(img)


def cv2_imdecode(buf: np.ndarray):
    import cv2
    return cv2.imdecode(buf, cv2.IMREAD_COLOR)


# ---------------------------------------------------------------------------
# Notes dashboard (history + EHR export)
# ---------------------------------------------------------------------------

def _auth_response():
    return JSONResponse({"error": "unauthorized"},
                        status_code=401)


@app.get("/notes")
async def notes_index(request: Request) -> dict:
    """List all archived notes, newest first."""
    if not _authorized(request):
        return _auth_response()
    audit_log.log("notes_list", actor=_actor(request), ip=_client_ip(request))
    return {"notes": list_notes()}


@app.get("/notes/{note_id}")
async def notes_get(note_id: str, request: Request) -> dict:
    if not _authorized(request):
        return _auth_response()
    audit_log.log("note_view", actor=_actor(request), target=note_id,
                  ip=_client_ip(request))
    record = get_note(note_id)
    if record is None:
        return JSONResponse({"error": f"note {note_id!r} not found"},
                            status_code=404)
    return record


@app.get("/notes/{note_id}/download")
async def notes_download(note_id: str, request: Request, fmt: str = "md"):
    """Download a note as txt / md / json / fhir / ccda for EHR import."""
    if not _authorized(request):
        return _auth_response()
    audit_log.log("note_export", actor=_actor(request), target=note_id,
                  detail=f"fmt={fmt}", ip=_client_ip(request))
    record = get_note(note_id)
    if record is None:
        return JSONResponse({"error": f"note {note_id!r} not found"},
                            status_code=404)
    try:
        media_type, filename, content = export(record, fmt)
    except KeyError:
        return JSONResponse({"error": f"unknown format {fmt!r}"},
                            status_code=400)
    from fastapi.responses import Response
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition":
                 f'attachment; filename="{filename}"'},
    )


@app.delete("/notes/{note_id}")
async def notes_delete(note_id: str, request: Request) -> dict:
    if not _authorized(request):
        return _auth_response()
    if _role(request) != "admin":
        return _require_admin(request)
    audit_log.log("note_delete", actor=_actor(request), target=note_id,
                  ip=_client_ip(request))
    if not delete_note(note_id):
        return JSONResponse({"error": f"note {note_id!r} not found"},
                            status_code=404)
    return {"ok": True}


@app.get("/tasks")
async def tasks_index(request: Request) -> dict:
    """All care-team task assignments {note_id: {item_index: {role,...}}}."""
    if not _authorized(request):
        return _auth_response()
    return {"tasks": tasks_list()}


@app.post("/tasks")
async def tasks_set(request: Request) -> dict:
    """Assign (role in nurse|provider), clear (role null) or complete
    (done true/false) one next-step item.

    Body: {"note_id": str, "item": int, "role": "nurse"|"provider"|null,
           "done": bool|undefined}
    """
    if not _authorized(request):
        return _auth_response()
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid JSON"}, status_code=400)
    note_id = str(body.get("note_id") or "")
    item = body.get("item")
    role = body.get("role")
    done = body.get("done")
    if not note_id or not isinstance(item, int) or item < 0:
        return JSONResponse({"error": "note_id and item (int) are required"},
                            status_code=400)
    if done is not None and not isinstance(done, bool):
        return JSONResponse({"error": "done must be a boolean"}, status_code=400)
    if role is not None and role not in ("nurse", "provider"):
        return JSONResponse(
            {"error": "role must be 'nurse', 'provider' or null"},
            status_code=400)
    if role is not None:
        tasks_assign(note_id, item, role)
    if done is not None:
        tasks_set_done(note_id, item, done)
    audit_log.log("task_update", actor=_actor(request), target=note_id,
                  detail=f"item={item} role={role} done={done}",
                  ip=_client_ip(request))
    return {"tasks": tasks_list()}


@app.get("/photos/{filename}")
async def photos_get(filename: str, request: Request):
    """Serve a stored photo for the dashboard."""
    if not _authorized(request):
        return _auth_response()
    audit_log.log("photo_view", actor=_actor(request), target=filename,
                  ip=_client_ip(request))
    path = photo_path(filename)
    if path is None:
        return JSONResponse({"error": f"photo {filename!r} not found"},
                            status_code=404)
    return Response(content=read_photo(path),
                    media_type=photo_mime(filename))


# --- Local TTS (no cloud) -------------------------------------------------

@app.get("/tts")
async def tts(request: Request, text: str = "", voice: str = "en"):
    """Synthesize text to WAV locally with espeak-ng (PHI stays on-box).

    Returns 501 if espeak-ng is not installed. Requires an authenticated
    session (browser cookie or dashboard token) and is audited.
    """
    if not _authorized(request):
        return _auth_response()
    text = (text or "").strip()
    if not text:
        return JSONResponse({"error": "text is required"}, status_code=400)
    if len(text) > 2000:
        text = text[:2000]
    bin_path = shutil.which("espeak-ng")
    if not bin_path:
        return JSONResponse({"error": "espeak-ng not installed"}, status_code=501)
    audit_log.log("tts", actor=_actor(request), detail=f"chars={len(text)}",
                  ip=_client_ip(request))
    try:
        proc = subprocess.run(
            [bin_path, "--stdout", "-v", voice, "-s", "170", "--", text],
            capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        LOG.warning("tts failed: %s", exc)
        return JSONResponse({"error": "tts failed"}, status_code=500)
    if proc.returncode != 0 or not proc.stdout:
        return JSONResponse({"error": "tts failed"}, status_code=500)
    return Response(content=proc.stdout,
                    media_type="audio/wav",
                    headers={"Cache-Control": "no-store"})


# --- Storage -----------------------------------------------------------------

def _store_note(state: SessionState, note: str,
                req: GenerateRequest | None = None) -> None:
    from pathlib import Path
    if CONFIG["strip_phi_on_store"]:
        transcript = sanitize_phi("\n".join(state.transcript))
        note = sanitize_phi(note)
    else:
        transcript = "\n".join(state.transcript)

    record = save_note(
        note=note,
        session_id=req.session_id if req else "default",
        source=(req.source if req and req.source
                else _infer_source(req.session_id if req else "default")),
        sections=split_soap(note),
        transcript=transcript,
        visual_findings=state.visual_findings,
        photos=state.photos,
        patient_id=(req.patient_id if (req and req.patient_id)
                    else random_patient_name()),
        provider=req.provider if req else "",
    )
    mirror_latest(record)
    LOG.info("note saved to output/soap_note.txt (archived: %s)", record["id"])


@app.on_event("startup")
async def on_startup() -> None:
    _load_sessions()
    seed_users(LOGIN_USER, LOGIN_PASSWORD)
    retention_days = int(CONFIG.get("retention_days") or 0)
    if retention_days > 0:
        try:
            result = purge_old(retention_days)
            LOG.info("retention purge ran (days=%s): %s", retention_days, result)
        except Exception as exc:
            LOG.warning("retention purge failed: %s", exc)
    LOG.info("MedGlass server starting; gpu=%s", detect_gpu()["available"])


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host=CONFIG["host"], port=CONFIG["port"],
                log_level="info")
