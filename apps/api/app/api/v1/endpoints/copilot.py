"""BotverseX Copilot — diagnostic agent endpoint (v1).

Two endpoints:

  POST /api/v1/copilot/diagnose
      Deterministic cloud-side diagnostics.  Works even when the LLM
      provider is disabled.

  POST /api/v1/copilot/chat
      Accepts a user question + browser-side diagnostics + page context,
      runs the server-side checks, builds a grounded prompt, and streams
      (or returns) an LLM answer.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.api.deps import get_db
from app.core.config import settings
from app.core.security import decode_access_token
from app.models.user import User
from app.services.copilot_agent_service import plan_client_actions
from app.services.copilot_knowledge_service import load_site_knowledge, page_knowledge_snippet
from app.services.copilot_playbook_service import (
    format_playbook_answer,
    match_playbooks,
    safe_diagnostic_summary,
)

logger = logging.getLogger(__name__)

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)

# ---------------------------------------------------------------------------
# Config (from pydantic Settings / .env)
# ---------------------------------------------------------------------------
def _copilot_provider() -> str:
    return settings.COPILOT_PROVIDER or "disabled"


def _copilot_model() -> str:
    return settings.COPILOT_MODEL or ""


def _copilot_api_key() -> str:
    return settings.COPILOT_API_KEY or ""


def _copilot_base_url() -> str:
    return settings.COPILOT_BASE_URL or ""


def _llm_enabled() -> bool:
    return _copilot_provider() != "disabled" and bool(_copilot_api_key())


def _user_from_bearer(authorization: str | None, db: Session) -> User | None:
    """Resolve optional Bearer token to User (None if missing/invalid)."""
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    token = authorization.split(" ", 1)[1].strip()
    payload = decode_access_token(token)
    if not payload:
        return None
    user_id = payload.get("sub")
    if not user_id:
        return None
    try:
        uid = uuid.UUID(str(user_id))
    except ValueError:
        return None
    user = db.query(User).filter(User.id == uid).first()
    if not user or not user.is_active:
        return None
    return user

# ---------------------------------------------------------------------------
# Deterministic probes
# ---------------------------------------------------------------------------

async def _probe_health(url: str, timeout: float = 2.0) -> Dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as c:
            r = await c.get(url)
            return {"ok": r.status_code == 200, "status": r.status_code, "error": None}
    except Exception as exc:
        return {"ok": False, "status": None, "error": str(exc)}


async def _probe_cloud_api() -> Dict[str, Any]:
    return await _probe_health(f"http://127.0.0.1:8000/health")


async def _probe_realtime() -> Dict[str, Any]:
    base = settings.REALTIME_SERVICE_URL.rstrip("/")
    candidates = [base]
    if base != "http://127.0.0.1:8002":
        candidates.append("http://127.0.0.1:8002")
    if "realtime:8002" in base:
        candidates.append("http://host.docker.internal:8002")

    last_error = "realtime unreachable"
    for candidate in candidates:
        url = candidate.rstrip("/") + "/api/setup/health"
        try:
            async with httpx.AsyncClient(timeout=3.0, trust_env=False) as c:
                r = await c.get(url)
                if r.status_code == 200:
                    return {"ok": True, "data": r.json(), "error": None, "url": candidate}
                last_error = f"{url} HTTP {r.status_code}"
        except Exception as exc:
            last_error = str(exc) or last_error
    return {"ok": False, "data": None, "error": last_error}


async def _probe_robots() -> Dict[str, Any]:
    base = settings.REALTIME_SERVICE_URL.rstrip("/")
    candidates = [base]
    if base != "http://127.0.0.1:8002":
        candidates.append("http://127.0.0.1:8002")
    if "realtime:8002" in base:
        candidates.append("http://host.docker.internal:8002")

    last_error = "robots api unreachable"
    for candidate in candidates:
        url = candidate.rstrip("/") + "/api/robots"
        try:
            async with httpx.AsyncClient(timeout=3.0, trust_env=False) as c:
                r = await c.get(url)
                if r.status_code == 200:
                    body = r.json()
                    return {
                        "ok": True,
                        "count": len(body.get("robots", [])),
                        "error": None,
                    }
                last_error = f"{url} HTTP {r.status_code}"
        except Exception as exc:
            last_error = str(exc) or last_error
    return {"ok": False, "count": 0, "error": last_error}


def _probe_db(db: Session) -> Dict[str, Any]:
    try:
        db.execute(text("SELECT 1"))
        return {"ok": True, "error": None}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


async def _run_server_diagnostics(db: Session) -> Dict[str, Any]:
    cloud, realtime, robots = await asyncio.gather(
        _probe_cloud_api(),
        _probe_realtime(),
        _probe_robots(),
    )
    db_result = _probe_db(db)
    rt_data = realtime.get("data") or {}

    issues: List[Dict[str, str]] = []

    if not realtime["ok"]:
        issues.append({
            "severity": "error",
            "code": "realtime_unreachable",
            "title": "Local Agent / Realtime service not reachable",
            "message": (
                f"Cannot reach {settings.REALTIME_SERVICE_URL}. "
                "If you are a user, start the Local Agent: "
                "cd botversex-local-agent && source .venv/bin/activate && python run_api.py"
            ),
        })
    if not db_result["ok"]:
        issues.append({
            "severity": "error",
            "code": "database_error",
            "title": "Database error",
            "message": f"Database probe failed: {db_result.get('error')}",
        })
    if not robots["ok"] and realtime["ok"]:
        issues.append({
            "severity": "warning",
            "code": "robots_api_error",
            "title": "Robot manifests unavailable",
            "message": f"/api/robots failed: {robots.get('error')}",
        })

    if rt_data:
        if rt_data.get("dialout_member") is False:
            issues.append({
                "severity": "warning",
                "code": "dialout_missing",
                "title": "User not in dialout group",
                "message": "Run: sudo usermod -aG dialout $USER && newgrp dialout",
            })
        if rt_data.get("video_device_count", 0) == 0:
            issues.append({
                "severity": "warning",
                "code": "no_cameras",
                "title": "No camera detected",
                "message": "Plug in a USB camera before starting the setup wizard.",
            })
        elif rt_data.get("camera_usable_count", 0) == 0:
            issues.append({
                "severity": "warning",
                "code": "camera_busy",
                "title": "Camera(s) busy or unreadable",
                "message": "Close other apps using the camera, or POST /api/camera/stop_streams.",
            })
        if rt_data.get("serial_device_count", 0) == 0:
            issues.append({
                "severity": "warning",
                "code": "no_serial",
                "title": "No serial devices",
                "message": "Plug in and power on the robot arm.",
            })
        if not rt_data.get("lerobot_available"):
            issues.append({
                "severity": "info",
                "code": "lerobot_missing",
                "title": "lerobot SDK not installed",
                "message": "Some features (Wiggle, advanced teleop) require lerobot in the venv.",
            })

    has_error = any(i["severity"] == "error" for i in issues)
    has_warning = any(i["severity"] == "warning" for i in issues)
    overall = "error" if has_error else ("warning" if has_warning else "ok")

    return {
        "overall": overall,
        "cloud_api": cloud,
        "database": db_result,
        "realtime": {
            "ok": realtime["ok"],
            "url": settings.REALTIME_SERVICE_URL,
            "error": realtime.get("error"),
        },
        "runtime": rt_data or None,
        "robots": robots,
        "issues": issues,
        "llm_enabled": _llm_enabled(),
        "timestamp": time.time(),
    }

# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class DiagnoseRequest(BaseModel):
    page: str = Field("", description="Current page pathname, e.g. /setup")
    client_diagnostics: Optional[Dict[str, Any]] = Field(
        None, description="Browser-side checks passed by the widget"
    )


class ChatRequest(BaseModel):
    message: str = Field(..., description="User question")
    page: str = Field("", description="Current page pathname")
    client_diagnostics: Optional[Dict[str, Any]] = None
    history: List[Dict[str, str]] = Field(
        default_factory=list,
        description="Previous messages [{role, content}, ...]",
    )

# ---------------------------------------------------------------------------
# POST /diagnose
# ---------------------------------------------------------------------------

@router.post("/diagnose")
@limiter.limit("30/minute")
async def diagnose(request: Request, req: DiagnoseRequest, db: Session = Depends(get_db)):
    server_diag = await _run_server_diagnostics(db)
    matches = match_playbooks(
        db,
        server_diag=server_diag,
        client_diag=req.client_diagnostics,
        page=req.page,
    )
    actions = plan_client_actions("", req.page, server_diag, req.client_diagnostics)
    return {
        "server": server_diag,
        "client": req.client_diagnostics,
        "page": req.page,
        "matches": matches,
        "actions": actions,
        "safe_summary": safe_diagnostic_summary(
            server_diag, req.client_diagnostics, req.page
        ),
    }

# ---------------------------------------------------------------------------
# POST /chat
# ---------------------------------------------------------------------------

@router.post("/chat")
@limiter.limit("20/minute")
async def chat(request: Request, req: ChatRequest, db: Session = Depends(get_db)):
    user = _user_from_bearer(request.headers.get("authorization"), db)
    if _llm_enabled() and user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="AI 问答需要登录。诊断页仍可使用 Playbook 规则诊断。",
        )
    server_diag = await _run_server_diagnostics(db)
    matches = match_playbooks(
        db,
        server_diag=server_diag,
        client_diag=req.client_diagnostics,
        page=req.page,
        user_message=req.message,
    )

    if not _llm_enabled():
        return _fallback_response(
            server_diag, req.page, matches, req.client_diagnostics, req.message
        )

    system_prompt = _build_system_prompt(
        server_diag, req.client_diagnostics, req.page, matches
    )

    messages = [{"role": "system", "content": system_prompt}]
    for msg in req.history[-10:]:
        messages.append({"role": msg.get("role", "user"), "content": msg.get("content", "")})
    messages.append({"role": "user", "content": req.message})

    try:
        answer = await _call_llm(messages)
        actions = plan_client_actions(
            req.message, req.page, server_diag, req.client_diagnostics
        )
        return {
            "answer": answer,
            "diagnostics": server_diag,
            "matches": matches,
            "actions": actions,
            "safe_summary": safe_diagnostic_summary(
                server_diag, req.client_diagnostics, req.page
            ),
        }
    except Exception as exc:
        logger.warning("Copilot LLM call failed: %s", exc)
        resp = _fallback_response(
            server_diag, req.page, matches, req.client_diagnostics, req.message
        )
        resp["llm_error"] = str(exc)
        return resp

# ---------------------------------------------------------------------------
# LLM adapter
# ---------------------------------------------------------------------------

async def _call_llm(messages: List[Dict[str, str]]) -> str:
    """Call LLM via OpenAI-compatible or Anthropic-compatible API."""
    if _copilot_provider() in ("anthropic",):
        return await _call_anthropic(messages)
    return await _call_openai_compatible(messages)


async def _call_openai_compatible(messages: List[Dict[str, str]]) -> str:
    base_url = _copilot_base_url()
    base = base_url.rstrip("/") if base_url else "https://api.openai.com/v1"
    url = f"{base}/chat/completions"
    headers = {
        "Authorization": f"Bearer {_copilot_api_key()}",
        "Content-Type": "application/json",
    }
    body = {
        "model": _copilot_model() or "gpt-4o-mini",
        "messages": messages,
        "max_tokens": 1024,
        "temperature": 0.3,
    }
    async with httpx.AsyncClient(timeout=30.0) as c:
        r = await c.post(url, json=body, headers=headers)
        r.raise_for_status()
        data = r.json()
        return data["choices"][0]["message"]["content"]


async def _call_anthropic(messages: List[Dict[str, str]]) -> str:
    base_url = _copilot_base_url()
    base = base_url.rstrip("/") if base_url else "https://api.anthropic.com"
    url = f"{base}/v1/messages"
    system_msg = ""
    chat_msgs = []
    for m in messages:
        if m["role"] == "system":
            system_msg += m["content"] + "\n"
        else:
            chat_msgs.append({"role": m["role"], "content": m["content"]})

    headers = {
        "x-api-key": _copilot_api_key(),
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    body = {
        "model": _copilot_model() or "claude-sonnet-4-20250514",
        "max_tokens": 1024,
        "system": system_msg.strip(),
        "messages": chat_msgs,
    }
    async with httpx.AsyncClient(timeout=30.0) as c:
        r = await c.post(url, json=body, headers=headers)
        r.raise_for_status()
        data = r.json()
        return data["content"][0]["text"]

# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def _build_system_prompt(
    server_diag: Dict[str, Any],
    client_diag: Optional[Dict[str, Any]],
    page: str,
    matches: Optional[List[Dict[str, Any]]] = None,
) -> str:
    parts = [
        "You are BotverseX Copilot — an **agent**, not a plain chatbot.",
        "You can trigger client actions on the user's behalf: navigate pages, start setup guides, run diagnostics,",
        "launch Reachy's virtual mode, and play preset Reachy emotions / dances / demos. When the user asks for",
        "something actionable, briefly tell them what you're doing in plain language — the system automatically",
        "shows the matching action button; you do NOT need to (and MUST NOT) mention internal tool names.",
        "",
        "Voice: speak to the user in natural Chinese (unless they write in English). Be concise and actionable.",
        "Explain WHAT will happen and WHY, then let the action button do the rest. Give terminal commands only",
        "when the user explicitly needs to run one (e.g. install a missing dependency).",
        "",
        "ABSOLUTE RULES about wording:",
        "  • NEVER mention internal action identifiers like `reachy_play_demo`, `reachy_play_emotion`,",
        "    `reachy_play_dance`, `reachy_virtual_start`, `reachy_goto`, etc. in replies to the user.",
        "  • Instead describe actions in user language: '播放一个 hello 演示动作', '让 Reachy 表演一个开心表情',",
        "    '跳一段舞蹈', '进入虚拟模式（不需要连接硬件）', '把头转向左边'.",
        "  • Do not teach the user internal command names — they will click buttons, not type commands.",
        "",
        "Capabilities (internal — do not echo these names to the user):",
        "  - navigate to a page / start a setup guide / start the product tour / run diagnostics",
        "  - start Reachy virtual mode (for users without hardware)",
        "  - play preset demo / emotion / dance moves on a connected Reachy Mini",
        "  - send a goto pose command to a connected Reachy Mini",
        "  - start the head tracker so Reachy follows the user's face",
        "  - start a chat with the robot (the chat panel itself)",
        "",
        "Your job: explain what to do next, troubleshoot setup, and clarify Setup vs 进入向导.",
        "Base troubleshooting on MATCHED PLAYBOOKS and diagnostics below.",
        "For product/how-to questions, use SITE KNOWLEDGE below.",
        "NEVER reveal: server IPs, JWT secrets, encryption keys, .env contents, internal infra paths, or other users' data.",
        "The platform: cloud website + Local Agent (localhost:8002) on user's PC + USB robot arms + cameras.",
        "",
        "=== SITE KNOWLEDGE (public product docs) ===",
        load_site_knowledge() or "(not loaded)",
        "",
        "=== SERVER DIAGNOSTICS ===",
    ]

    issues = server_diag.get("issues", [])
    if issues:
        for iss in issues:
            parts.append(f"[{iss['severity'].upper()}] {iss['code']}: {iss['message']}")
    else:
        parts.append("All server checks passed (cloud API, database, realtime, robots).")

    rt = server_diag.get("runtime") or {}
    if rt:
        parts.append(f"\nRuntime: lerobot={rt.get('lerobot_available')}, "
                      f"pytorch={rt.get('pytorch_available')}, "
                      f"cameras={rt.get('camera_usable_count', '?')}/{rt.get('video_device_count', '?')}, "
                      f"serial={rt.get('serial_device_count', 0)}, "
                      f"dialout={rt.get('dialout_member')}")

    if client_diag:
        parts.append("\n=== CLIENT DIAGNOSTICS ===")
        la = client_diag.get("localAgent")
        if la:
            parts.append(f"Local Agent probe: ok={la.get('ok')}, error={la.get('error')}")
        errs = client_diag.get("recentErrors")
        if errs:
            parts.append(f"Recent frontend errors ({len(errs)}):")
            for e in errs[:5]:
                parts.append(f"  - {e}")

    if page:
        parts.append(f"\n=== PAGE CONTEXT ===")
        parts.append(f"User is on: {page}")
        hints = _page_hints(page)
        if hints:
            parts.append(hints)

    if matches:
        parts.append("\n=== MATCHED PLAYBOOKS (use these as primary source) ===")
        for m in matches[:5]:
            parts.append(f"\n[{m['severity'].upper()}] {m['code']}: {m['title']}")
            parts.append(f"Root cause: {m['root_cause']}")
            parts.append("Fix steps:")
            for i, step in enumerate(m.get("fix_steps") or [], 1):
                parts.append(f"  {i}. {step}")
            if m.get("verify_steps"):
                parts.append("Verify:")
                for step in m["verify_steps"]:
                    parts.append(f"  - {step}")

    return "\n".join(parts)


def _fallback_response(
    server_diag: Dict[str, Any],
    page: str,
    matches: Optional[List[Dict[str, Any]]] = None,
    client_diag: Optional[Dict[str, Any]] = None,
    user_message: str = "",
) -> Dict[str, Any]:
    """When LLM is disabled or failed, return Playbook-grounded answer."""
    playbook_text = format_playbook_answer(matches or [])
    if playbook_text:
        summary = playbook_text
    else:
        snippet = page_knowledge_snippet(page)
        issues = server_diag.get("issues", [])
        if not issues:
            summary = snippet or "系统检查通过。如果仍有问题，请描述你看到的错误信息。"
        else:
            lines = []
            for iss in issues:
                icon = {"error": "X", "warning": "!", "info": "i"}.get(iss["severity"], "?")
                lines.append(f"[{icon}] {iss['title']}: {iss['message']}")
            summary = (snippet + "\n\n" if snippet else "") + "发现以下问题：\n\n" + "\n".join(lines)

    return {
        "answer": summary,
        "diagnostics": server_diag,
        "matches": matches or [],
        "actions": plan_client_actions(user_message, page, server_diag, client_diag),
        "safe_summary": safe_diagnostic_summary(server_diag, client_diag, page),
    }


def _page_hints(page: str) -> str:
    snippet = page_knowledge_snippet(page)
    if snippet:
        return snippet
    if "/setup" in page:
        return (
            "This page checks Local Agent connectivity. Common issues:\n"
            "- Local Agent not started (python run_api.py)\n"
            "- python3-venv or python3-dev not installed\n"
            "- pip install failed (needs proxy for GitHub/PyPI in China)\n"
            "- Port 8002 already in use"
        )
    if "/robots" in page:
        return (
            "This page lists robot hardware via /api/robots (cloud→realtime).\n"
            "If blank: check realtime container or Local Agent.\n"
            "If HTTPS fails: SSL cert may not cover botversex.feispace.me."
        )
    if "/training" in page:
        return (
            "Training page needs auth (JWT). Common issues:\n"
            "- Not logged in → redirect to /login\n"
            "- Training API unreachable → check cloud API health\n"
            "- Job stuck → check Qualia service or training logs"
        )
    if "/teleop" in page:
        return (
            "Teleop requires Local Agent + serial ports + camera.\n"
            "Check: python run_api.py running, arms plugged in and powered,\n"
            "user in dialout group, camera not held by another app."
        )
    return ""
