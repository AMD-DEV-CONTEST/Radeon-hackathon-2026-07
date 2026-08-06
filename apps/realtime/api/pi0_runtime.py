"""LeRobot HF runtime adapter — HTTP client to the Plan B sidecar (ACT / Pi0).

The real policies (``ACTPolicy``, ``PI0Policy``, …) live in a separate Python 3.12 venv
(``apps/pi0_sidecar``) because LeRobot's ``[pi]`` extra is incompatible with
the realtime service's Python 3.11 + ROCm stack. This module is a thin
client that talks to that sidecar over ``http://127.0.0.1:8010``, so the
rest of ``vision_inference.py`` can stay unchanged.

Import-wise this file MUST NOT depend on torch / lerobot / transformers —
those live behind the sidecar process.
"""
from __future__ import annotations

import base64
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import cv2
import numpy as np
import requests

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

PI0_SIDECAR_URL = os.environ.get("BOTVERSEX_PI0_SIDECAR_URL", "http://127.0.0.1:8010")
PI0_LOAD_TIMEOUT_S = float(os.environ.get("BOTVERSEX_PI0_LOAD_TIMEOUT", "600"))
PI0_PREDICT_TIMEOUT_S = float(os.environ.get("BOTVERSEX_PI0_PREDICT_TIMEOUT", "30"))
PI0_PREDICT_RETRIES = int(os.environ.get("BOTVERSEX_PI0_PREDICT_RETRIES", "1"))
PI0_BREAKER_FAILS = int(os.environ.get("BOTVERSEX_PI0_BREAKER_FAILS", "3"))
PI0_BREAKER_COOLDOWN_S = float(os.environ.get("BOTVERSEX_PI0_BREAKER_COOLDOWN", "5"))

_consecutive_predict_failures = 0
_breaker_open_until = 0.0


def get_predict_health() -> dict[str, Any]:
    now = time.time()
    return {
        "consecutive_failures": _consecutive_predict_failures,
        "breaker_open": now < _breaker_open_until,
        "breaker_open_until": _breaker_open_until if _breaker_open_until > 0 else None,
        "breaker_remaining_s": max(0.0, _breaker_open_until - now),
    }


class Pi0SidecarError(RuntimeError):
    """Raised when the sidecar is unreachable or returns an error."""


def looks_like_hf_repo(model_key: str) -> bool:
    """Return True when ``model_key`` looks like an HF repo id (``owner/name``).

    Local model_keys produced by the training worker are always a single
    segment (``vision_stub_demo``, ``mlp_baseline_2026...``), so the presence
    of a ``/`` is a reliable router signal.
    """
    if not model_key:
        return False
    return "/" in model_key


# --------------------------------------------------------------------------- #
# Session (client-side handle, mirrors sidecar state)
# --------------------------------------------------------------------------- #


@dataclass
class Pi0Session:
    """Client-side handle for a LeRobot HF policy (ACT / Pi0 / …) in the sidecar."""

    repo_id: str
    device: str
    image_keys: list[str]
    policy_family: str = "pi0"  # from sidecar /load: "act" | "pi0" | ...
    state_key: str = "observation.state"
    action_key: str = "action"
    task_prompt: str = "perform the task"
    sidecar_url: str = PI0_SIDECAR_URL
    loaded_at: float = field(default_factory=time.time)

    # Kept for API-compat with the previous in-process Pi0Session; unused.
    policy: Any = None
    preprocessor: Any = None
    postprocessor: Any = None


# --------------------------------------------------------------------------- #
# Loader (delegates to sidecar /load)
# --------------------------------------------------------------------------- #


def _sidecar_healthy(base_url: str) -> bool:
    try:
        r = requests.get(f"{base_url}/healthz", timeout=2.0)
        return r.ok
    except requests.RequestException:
        return False


def load_pi0(repo_id: str, device: str, task_prompt: str = "perform the task") -> Pi0Session:
    """Ask the sidecar to load a LeRobot HF checkpoint (ACT or Pi0) and return a client handle.

    ``device`` is forwarded as ``prefer_device`` to the sidecar. Note the
    sidecar runs CPU-first by default because ROCm wheels aren't wired into
    its 3.12 venv yet — that's intentional and does not affect the realtime
    teleop/record stack.
    """
    base_url = PI0_SIDECAR_URL

    if not _sidecar_healthy(base_url):
        raise Pi0SidecarError(
            f"LeRobot HF sidecar unreachable at {base_url}. "
            "Start it with: bash apps/pi0_sidecar/run.sh "
            "(first time: bash apps/pi0_sidecar/setup_env.sh)."
        )

    logger.info(
        "[pi0_runtime] requesting sidecar load repo=%s device=%s url=%s",
        repo_id, device, base_url,
    )

    try:
        resp = requests.post(
            f"{base_url}/load",
            json={
                "model_key": repo_id,
                "prefer_device": device,
                "task_prompt": task_prompt,
            },
            timeout=PI0_LOAD_TIMEOUT_S,
        )
    except requests.RequestException as exc:
        raise Pi0SidecarError(f"sidecar /load network error: {exc}") from exc

    if not resp.ok:
        detail = _extract_detail(resp)
        raise Pi0SidecarError(f"sidecar /load failed ({resp.status_code}): {detail}")

    payload = resp.json()
    fam = str(payload.get("policy_family") or "pi0").lower()
    return Pi0Session(
        repo_id=payload.get("model_key", repo_id),
        device=str(payload.get("device", device)),
        image_keys=list(payload.get("image_keys") or ["observation.images.top"]),
        policy_family=fam,
        task_prompt=str(payload.get("task_prompt") or task_prompt),
        sidecar_url=base_url,
    )


# --------------------------------------------------------------------------- #
# Per-frame inference (delegates to sidecar /predict)
# --------------------------------------------------------------------------- #


def _bgr_to_jpeg_b64(bgr: np.ndarray, quality: int = 85) -> str:
    """Encode a BGR frame as a base64 JPEG string for the sidecar wire format."""
    ok, buf = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
    if not ok:
        raise Pi0SidecarError("cv2.imencode JPEG failed")
    return base64.b64encode(buf.tobytes()).decode("ascii")


def predict_action(
    session: Pi0Session,
    bgr_frame: np.ndarray,
    joint_state: list[float],
    task_prompt: Optional[str] = None,
) -> list[float]:
    """Run one Pi0 inference step via the sidecar.

    Returns a length-6 absolute joint target (post-processor already
    un-normalized). Errors from the sidecar surface as ``Pi0SidecarError``
    so the caller in ``vision_inference.py`` can attach an HTTP status.
    """
    img_b64 = _bgr_to_jpeg_b64(bgr_frame)

    payload = {
        "joint_state": [float(x) for x in (joint_state or [])],
        "image_b64": img_b64,
        "task_prompt": task_prompt or session.task_prompt,
    }

    global _consecutive_predict_failures, _breaker_open_until
    now = time.time()
    if now < _breaker_open_until:
        remaining = round(_breaker_open_until - now, 2)
        raise Pi0SidecarError(
            f"sidecar predict circuit breaker open for {remaining}s "
            f"(recent failures={_consecutive_predict_failures})"
        )

    last_err: Exception | None = None
    tries = max(1, PI0_PREDICT_RETRIES)
    resp: requests.Response | None = None
    for attempt in range(1, tries + 1):
        try:
            resp = requests.post(
                f"{session.sidecar_url}/predict",
                json=payload,
                timeout=PI0_PREDICT_TIMEOUT_S,
            )
            if not resp.ok:
                detail = _extract_detail(resp)
                raise Pi0SidecarError(
                    f"sidecar /predict failed ({resp.status_code}): {detail}"
                )
            break
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            if attempt < tries:
                logger.warning(
                    "[pi0_runtime] /predict retry %d/%d after error: %s",
                    attempt, tries, exc
                )
                continue
    if resp is None or not resp.ok:
        _consecutive_predict_failures += 1
        if _consecutive_predict_failures >= max(1, PI0_BREAKER_FAILS):
            _breaker_open_until = time.time() + max(0.5, PI0_BREAKER_COOLDOWN_S)
            logger.error(
                "[pi0_runtime] opening predict breaker for %.1fs after %d consecutive failures",
                PI0_BREAKER_COOLDOWN_S,
                _consecutive_predict_failures,
            )
        if isinstance(last_err, Pi0SidecarError):
            raise last_err
        raise Pi0SidecarError(f"sidecar /predict network error: {last_err}") from last_err

    _consecutive_predict_failures = 0
    _breaker_open_until = 0.0

    data = resp.json()
    action = list(data.get("action") or [])
    # Preserve full DoF (B601=7). Only pad to 6 for legacy SO-101 callers;
    # never truncate a longer vector.
    if len(action) < 6:
        action = action + [0.0] * (6 - len(action))
    return [float(x) for x in action]


# --------------------------------------------------------------------------- #
# internal
# --------------------------------------------------------------------------- #


def _extract_detail(resp: "requests.Response") -> str:
    try:
        j = resp.json()
        if isinstance(j, dict) and "detail" in j:
            return str(j["detail"])
        return str(j)
    except ValueError:
        return resp.text[:500]
