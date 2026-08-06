"""Setup / onboarding preflight aggregator (M9.1).

The ``/api/v1/setup/status`` endpoint is what the Dashboard status card and
the ``/robots/so101`` wizard poll to know whether the user is ready to go.

It collapses four independent checks into one response:

  * API service itself    — always True when this handler runs.
  * Database              — trivial ``SELECT 1``.
  * Realtime service      — GET http://<realtime>/api/setup/health.
  * Runtime health        — forwards realtime's lerobot / torch / opencv /
                            video / serial / ROCm probes.

It intentionally does NOT require authentication. Rationale: this is the
very first thing the frontend loads after login, and returning 401 would
break the wizard for first-time users who just registered. Sensitive info
(tokens, paths) is not included in the response.

Ports & cameras are NOT aggregated here — the wizard calls the realtime
endpoints directly through the existing Vite proxy to avoid double-hops.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter()


async def _probe_realtime_health(timeout_s: float = 2.0) -> Dict[str, Any]:
    url = settings.REALTIME_SERVICE_URL.rstrip("/") + "/api/setup/health"
    try:
        # trust_env=False: ignore HTTP_PROXY/SOCKS_PROXY env vars. The API<->Realtime
        # hop is always loopback, so honouring the user's outbound proxy would
        # just break it (and requires httpx[socks] which we don't bundle).
        async with httpx.AsyncClient(timeout=timeout_s, trust_env=False) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                return {"reachable": True, "data": resp.json(), "error": None}
            return {
                "reachable": False,
                "data": None,
                "error": f"HTTP {resp.status_code}",
            }
    except Exception as exc:
        return {"reachable": False, "data": None, "error": str(exc)}


def _probe_db(db: Session) -> Dict[str, Any]:
    try:
        db.execute(text("SELECT 1"))
        return {"ok": True, "error": None}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@router.get("/status")
async def get_setup_status(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Aggregate preflight snapshot for the onboarding wizard."""
    db_probe = _probe_db(db)
    rt_probe = await _probe_realtime_health()

    rt_data: Dict[str, Any] = rt_probe.get("data") or {}

    # Build a shortlist of human-readable issues the UI can render as yellow
    # warning boxes. Order matters: most blocking issue first.
    issues: list[Dict[str, str]] = []
    if not rt_probe.get("reachable"):
        issues.append(
            {
                # Realtime can be managed separately in dev (or briefly restarting),
                # so keep this visible but non-blocking for onboarding navigation.
                "severity": "warning",
                "code": "realtime_unreachable",
                "message": (
                    f"Realtime service not reachable at {settings.REALTIME_SERVICE_URL}. "
                    "Make sure `apps/realtime` is running on port 8002."
                ),
            }
        )
    if not db_probe.get("ok"):
        issues.append(
            {
                "severity": "error",
                "code": "database_error",
                "message": f"Database probe failed: {db_probe.get('error')}",
            }
        )
    if rt_data:
        if rt_data.get("dialout_member") is False:
            issues.append(
                {
                    "severity": "warning",
                    "code": "dialout_missing",
                    "message": (
                        "Current user is not in the `dialout` group. "
                        "Without it you may not be able to open /dev/ttyACM*. "
                        "Fix: `sudo usermod -aG dialout $USER && newgrp dialout`"
                    ),
                }
            )
        # M12: split "no /dev/video" vs "/dev/video exists but can't be opened".
        video_count = rt_data.get("video_device_count", 0)
        usable = rt_data.get("camera_usable_count", None)
        busy = rt_data.get("camera_busy_count", None)
        if video_count == 0:
            issues.append(
                {
                    "severity": "warning",
                    "code": "no_cameras",
                    "message": (
                        "No /dev/video* device detected. Plug in a USB camera "
                        "before the 'Camera check' step."
                    ),
                }
            )
        elif usable == 0 and busy and busy > 0:
            # Device file exists but OpenCV refused to open it — most common
            # root cause for Step 4 'Camera index out of range' failures.
            issues.append(
                {
                    "severity": "warning",
                    "code": "camera_busy",
                    "message": (
                        f"Found {video_count} /dev/video* node(s) but OpenCV could "
                        "not open any of them. Another app (browser preview, Zoom, "
                        "OBS, a leftover recording) is probably holding them. "
                        "Close it, or POST /api/camera/stop_streams to release "
                        "our own preview, then rescan."
                    ),
                }
            )
        elif usable == 0 and video_count > 0:
            issues.append(
                {
                    "severity": "warning",
                    "code": "camera_unreadable",
                    "message": (
                        f"{video_count} /dev/video* node(s) present but none "
                        "delivered a frame. The device might be a metadata-only "
                        "V4L node (e.g. Intel RealSense depth), or the connected "
                        "camera has a driver issue."
                    ),
                }
            )
        if rt_data.get("serial_device_count", 0) == 0:
            issues.append(
                {
                    "severity": "warning",
                    "code": "no_serial",
                    "message": (
                        "No serial device (/dev/ttyACM* or /dev/ttyUSB*) detected. "
                        "Plug in and power on the SO-101 follower before the "
                        "'Arm connection' step."
                    ),
                }
            )
        if rt_data.get("pytorch_available") and rt_data.get("rocm_probe_ok") is False:
            issues.append(
                {
                    "severity": "info",
                    "code": "rocm_cpu_fallback",
                    "message": (
                        "ROCm GPU not usable for PyTorch kernels — inference "
                        "and training will run on CPU. This is expected on "
                        "gfx1151 (Ryzen AI Max 395) today."
                    ),
                }
            )
        if not rt_data.get("lerobot_available"):
            issues.append(
                {
                    "severity": "info",
                    "code": "lerobot_missing",
                    "message": (
                        "lerobot motor SDK not installed in realtime venv. "
                        "Teleop/Record still work via the built-in fallbacks; "
                        "Wiggle during setup will be disabled."
                    ),
                }
            )

    # Highest severity wins for the "all green" banner.
    has_error = any(i["severity"] == "error" for i in issues)
    has_warning = any(i["severity"] == "warning" for i in issues)
    overall = "error" if has_error else ("warning" if has_warning else "ok")

    return {
        "overall": overall,
        "checks": {
            "api": {"ok": True},
            "database": db_probe,
            "realtime": {
                "reachable": rt_probe.get("reachable"),
                "url": settings.REALTIME_SERVICE_URL,
                "error": rt_probe.get("error"),
            },
            "runtime": rt_data or None,
        },
        "issues": issues,
        "next_action": _suggest_next_action(rt_data, has_error),
    }


def _suggest_next_action(rt_data: Optional[Dict[str, Any]], has_error: bool) -> Dict[str, str]:
    """Return {label, path} the wizard can show as the main CTA."""
    if has_error:
        return {"label": "Fix blocking issues", "path": "/robots/so101"}
    if not rt_data:
        return {"label": "Start SO-101 Setup", "path": "/robots/so101"}
    if rt_data.get("serial_device_count", 0) == 0:
        return {"label": "Plug in your SO-101, then start setup", "path": "/robots/so101"}
    if rt_data.get("video_device_count", 0) == 0:
        return {"label": "Plug in a USB camera, then start setup", "path": "/robots/so101"}
    return {"label": "Start SO-101 Setup", "path": "/robots/so101"}
