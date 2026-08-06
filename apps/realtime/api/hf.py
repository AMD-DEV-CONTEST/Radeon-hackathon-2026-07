"""Lightweight HF helpers for the wizard (realtime side).

The wizard frontend talks to ``realtime:8002`` via the Vite dev proxy without
authentication. We expose a single whoami endpoint here so Step 4 can compute
the correct dataset owner (``<hf_username>/so101-...``) instead of a hardcoded
placeholder like ``botversex/...`` that the user likely does not own.

Source of the token, in order:
  1. ``HF_TOKEN`` env var (our preferred convention in apps/api/.env)
  2. ``HUGGING_FACE_HUB_TOKEN`` env var (huggingface_hub's own name)
  3. ``~/.cache/huggingface/token`` (written by ``huggingface-cli login``)
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/hf", tags=["hf"])


def _read_token() -> Optional[str]:
    for k in ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN", "HUGGINGFACE_TOKEN"):
        v = os.environ.get(k)
        if v:
            return v.strip()
    # Fall back to the canonical on-disk location used by huggingface-cli.
    token_path = Path.home() / ".cache" / "huggingface" / "token"
    if token_path.is_file():
        try:
            t = token_path.read_text(encoding="utf-8").strip()
            if t:
                return t
        except Exception:
            pass
    return None


def _whoami(token: str) -> Optional[dict[str, Any]]:
    """Call HF ``/api/whoami-v2``. Prefers the SDK, falls back to raw HTTP."""
    try:
        from huggingface_hub import HfApi  # type: ignore

        info = HfApi(token=token).whoami()
        if isinstance(info, dict):
            return info
        # Older SDKs returned an object.
        return {"name": getattr(info, "name", "")}
    except Exception as e:
        logger.debug("HF SDK whoami failed, trying raw HTTP: %s", e)

    try:
        import httpx  # type: ignore

        with httpx.Client(timeout=8.0, follow_redirects=True) as c:
            r = c.get(
                "https://huggingface.co/api/whoami-v2",
                headers={"Authorization": f"Bearer {token}"},
            )
        if r.status_code != 200:
            logger.warning("HF whoami HTTP %s: %s", r.status_code, r.text[:200])
            return None
        return r.json()
    except Exception as e:
        logger.warning("HF whoami request failed: %s", e)
        return None


@router.get("/whoami")
async def hf_whoami() -> dict[str, Any]:
    """Return ``{ok, username, source}`` for the configured HF token.

    Never raises — returns ``ok=False`` with a message the UI can show
    to the user so they know to configure ``HF_TOKEN``.
    """
    token = _read_token()
    if not token:
        return {
            "ok": False,
            "message": (
                "HF token 未配置。请在 apps/api/.env 里设置 HF_TOKEN，"
                "或运行 `huggingface-cli login`。"
            ),
            "username": "",
        }

    info = _whoami(token)
    if info is None:
        return {
            "ok": False,
            "message": "HF whoami 失败：token 可能已失效或网络不可达。",
            "username": "",
        }

    username = info.get("name") or ""
    if not username:
        return {"ok": False, "message": "HF whoami 返回空 username。", "username": ""}

    return {
        "ok": True,
        "username": username,
        "orgs": [o.get("name") for o in (info.get("orgs") or []) if o.get("name")],
    }
