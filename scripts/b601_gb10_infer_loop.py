#!/usr/bin/env python3
"""B601 laptop loop: cams+joints → GB10 Pi0.5 sidecar → send_action to follower.

Env:
  BOTVERSEX_PI0_SIDECAR_URL  default http://192.168.100.106:8010
  B601_CAN                   default can0
  B601_ROBOT_ID              default b601_rs
  B601_CAMERA_FRONT          default 4
  B601_CAMERA_SIDE           default 6
  B601_TASK                  ice-hockey task string
  B601_INFER_HZ              default 5
  B601_PI05_MODEL            model path on GB10
"""
from __future__ import annotations

import base64
import json
import logging
import os
import signal
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("b601_gb10_infer")

SIDECAR = os.environ.get("BOTVERSEX_PI0_SIDECAR_URL", "http://192.168.100.106:8010").rstrip("/")
# RS uses SocketCAN (can0); DM uses USB serial (/dev/ttyACM0)
ARM_VARIANT = os.environ.get("B601_ARM_VARIANT", "auto").strip().lower()
FOLLOWER_PORT = os.environ.get("B601_FOLLOWER_PORT") or os.environ.get("B601_CAN", "can0")
ROBOT_ID = os.environ.get("B601_ROBOT_ID", "follower1")
# Ice-hockey pair as user-recorded: front=icspring, side=SN0002 (often 4+6).
# /dev/videoN can renumber after reboot/replug — UI passes explicit indices.
CAM_FRONT = int(os.environ.get("B601_CAMERA_FRONT", "4"))
CAM_SIDE = int(os.environ.get("B601_CAMERA_SIDE", "6"))
TASK = os.environ.get(
    "B601_TASK",
    "冰球游戏，将对方击过来的红色圆盘击回去",
)
HZ = float(os.environ.get("B601_INFER_HZ", "5"))
MODEL = os.environ.get("B601_PI05_MODEL", "/home/zhouzhigang/outputs/pi05_smoke_patched")
STATUS_FILE = Path(os.environ.get("B601_REMOTE_INFER_STATUS", "/tmp/b601_gb10_infer_status.json"))
# Two-phase rate limit:
# 1) Lift: while |shoulder_lift| motor < LIFT_DONE_DEG, clamp slowly so big arm
#    rises smoothly (teleop-like). Dataset hit swings often exceed 12°/step —
#    those need phase 2.
# 2) Hit: after big arm is up, uncapped (HIT_MAX_DELTA<=0) so strike is snappy.
LIFT_DONE_DEG = float(os.environ.get("B601_LIFT_DONE_DEG", "55.0"))
LIFT_MAX_DELTA_DEG = float(os.environ.get("B601_LIFT_MAX_DELTA_DEG", "8.0"))
HIT_MAX_DELTA_DEG = float(os.environ.get("B601_HIT_MAX_DELTA_DEG", "0"))
# Brief hold so step-1 absolute targets don't yank from near-zero pose.
WARMUP_STEPS = int(os.environ.get("B601_WARMUP_STEPS", "5"))
# Legacy single-limit env still honored if set (overrides two-phase).
_LEGACY_MAX = os.environ.get("B601_MAX_DELTA_DEG")
MAX_DELTA_DEG = float(_LEGACY_MAX) if _LEGACY_MAX not in (None, "") else None

ACTION_NAMES = [
    "shoulder_pan",
    "shoulder_lift",
    "elbow_flex",
    "wrist_flex",
    "wrist_yaw",
    "wrist_roll",
    "gripper",
]

_stop = False


def _handle_sig(*_a) -> None:
    global _stop
    _stop = True


def _jpeg_b64(bgr: np.ndarray, quality: int = 80) -> str:
    ok, buf = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        raise RuntimeError("jpeg encode failed")
    return base64.b64encode(buf.tobytes()).decode("ascii")


def _write_status(**kwargs) -> None:
    payload = {"ts": time.time(), **kwargs}
    try:
        STATUS_FILE.write_text(json.dumps(payload, ensure_ascii=False))
    except Exception:
        pass


def _open_cam(index: int) -> cv2.VideoCapture:
    cap = cv2.VideoCapture(index)
    if not cap.isOpened():
        cap = cv2.VideoCapture(f"/dev/video{index}")
    if not cap.isOpened():
        raise RuntimeError(f"cannot open camera index={index}")
    return cap


def _grab(cap: cv2.VideoCapture) -> np.ndarray:
    ok, frame = cap.read()
    if not ok or frame is None:
        raise RuntimeError("camera read failed")
    return frame


def _ensure_sidecar_loaded() -> None:
    r = requests.get(f"{SIDECAR}/healthz", timeout=5)
    r.raise_for_status()
    health = r.json()
    if health.get("loaded"):
        logger.info("sidecar already loaded model=%s", health.get("model_key"))
        return
    logger.info("loading model on sidecar %s", MODEL)
    resp = requests.post(
        f"{SIDECAR}/load",
        json={"model_key": MODEL, "prefer_device": "cuda", "task_prompt": TASK},
        timeout=600,
    )
    if not resp.ok:
        raise RuntimeError(f"/load failed: {resp.status_code} {resp.text[:400]}")
    logger.info("load ok: %s", resp.json())


def _obs_state_from_robot(robot) -> list[float]:
    obs = robot.get_observation()
    vals: list[float] = []
    for name in ACTION_NAMES:
        key = f"{name}.pos"
        if key in obs:
            vals.append(float(obs[key]))
        elif name in obs:
            vals.append(float(obs[name]))
        else:
            vals.append(0.0)
    return vals


def _action_dict(action: list[float]) -> dict:
    return {
        f"{name}.pos": float(action[i])
        for i, name in enumerate(ACTION_NAMES)
        if i < len(action)
    }


def _clamp_action(
    action: list[float],
    state: list[float],
    max_delta: float,
    directions: dict[str, float] | None = None,
) -> list[float]:
    """Rate-limit motion in *motor* degrees, then convert back to send_action goals.

    Seeed ``send_action`` multiplies goals by ``joint_directions`` (e.g. DM
    shoulder_lift=-1). Clamping in goal/obs space without that sign creates a
    fixed point near 0 — big arm looks frozen while the model asks for ~90°.
    """
    dirs = directions or {}
    out: list[float] = []
    for i, name in enumerate(ACTION_NAMES):
        cur_motor = float(state[i]) if i < len(state) else 0.0
        tgt_goal = float(action[i]) if i < len(action) else cur_motor
        d = float(dirs.get(name, 1.0) or 1.0)
        tgt_motor = tgt_goal * d
        delta = max(-max_delta, min(max_delta, tgt_motor - cur_motor))
        next_motor = cur_motor + delta
        out.append(next_motor / d)
    return out


def main() -> int:
    signal.signal(signal.SIGINT, _handle_sig)
    signal.signal(signal.SIGTERM, _handle_sig)

    variant = ARM_VARIANT
    port = FOLLOWER_PORT
    if variant in ("", "auto"):
        variant = "dm" if port.startswith("/dev/") or "tty" in port else "rs"
    logger.info(
        "sidecar=%s variant=%s port=%s cams=%s,%s hz=%.1f",
        SIDECAR, variant, port, CAM_FRONT, CAM_SIDE, HZ,
    )
    _write_status(running=True, phase="connect_sidecar", sidecar=SIDECAR, variant=variant)

    try:
        _ensure_sidecar_loaded()
    except Exception as exc:
        logger.error("sidecar load failed: %s", exc)
        _write_status(running=False, phase="error", error=str(exc))
        return 2

    if variant == "dm":
        from lerobot_robot_seeed_b601.config_seeed_b601_dm_follower import SeeedB601DMFollowerConfig
        from lerobot_robot_seeed_b601.seeed_b601_dm_follower import SeeedB601DMFollower

        baud = int(os.environ.get("B601_DM_BAUD", "921600"))
        cfg = SeeedB601DMFollowerConfig(
            port=port,
            id=ROBOT_ID,
            cameras={},
            can_adapter="damiao",
            dm_serial_baud=baud,
        )
        robot = SeeedB601DMFollower(cfg)
    else:
        from lerobot_robot_seeed_b601.config_seeed_b601_rs_follower import SeeedB601RSFollowerConfig
        from lerobot_robot_seeed_b601.seeed_b601_rs_follower import SeeedB601RSFollower

        cfg = SeeedB601RSFollowerConfig(
            port=port,
            id=ROBOT_ID,
            cameras={},
            can_adapter="socketcan",
        )
        robot = SeeedB601RSFollower(cfg)

    logger.info("connecting follower…")
    robot.connect(calibrate=False)
    joint_dirs = dict(getattr(robot.config, "joint_directions", {}) or {})
    logger.info(
        "joint_directions=%s warmup=%d lift_done=%.0f° lift_delta=%.1f hit_delta=%s legacy_max=%s",
        joint_dirs,
        WARMUP_STEPS,
        LIFT_DONE_DEG,
        LIFT_MAX_DELTA_DEG,
        HIT_MAX_DELTA_DEG if HIT_MAX_DELTA_DEG > 0 else "off",
        MAX_DELTA_DEG,
    )
    _write_status(running=True, phase="connected")

    cap_f = None
    cap_s = None
    try:
        cap_f = _open_cam(CAM_FRONT)
        cap_s = _open_cam(CAM_SIDE)
    except Exception as exc:
        logger.error("camera open failed: %s", exc)
        _write_status(
            running=False,
            phase="error",
            error=f"camera open failed (front={CAM_FRONT}, side={CAM_SIDE}): {exc}",
        )
        try:
            robot.disconnect()
        except Exception:
            pass
        if cap_f is not None:
            try:
                cap_f.release()
            except Exception:
                pass
        return 1

    period = 1.0 / max(0.5, HZ)
    n = 0
    reset = True

    try:
        while not _stop:
            t0 = time.time()
            try:
                front = _grab(cap_f)
                side = _grab(cap_s)
                state = _obs_state_from_robot(robot)
                payload = {
                    "joint_state": state,
                    "images_b64": {
                        "front": _jpeg_b64(front),
                        "side": _jpeg_b64(side),
                    },
                    "task_prompt": TASK,
                    "reset": reset,
                }
                reset = False
                resp = requests.post(f"{SIDECAR}/predict", json=payload, timeout=30)
                if not resp.ok:
                    raise RuntimeError(f"predict {resp.status_code}: {resp.text[:300]}")
                data = resp.json()
                action = list(data.get("action") or [])
                if len(action) < 7:
                    action = action + [0.0] * (7 - len(action))
                raw = action[:7]
                shoulder_abs = abs(float(state[1]) if len(state) > 1 else 0.0)
                if n < WARMUP_STEPS:
                    # Hold: send goals that map back to current motor pose.
                    cmd = []
                    for i, name in enumerate(ACTION_NAMES):
                        cur = float(state[i]) if i < len(state) else 0.0
                        d = float(joint_dirs.get(name, 1.0) or 1.0)
                        cmd.append(cur / d)
                    rate_phase = "warmup"
                elif MAX_DELTA_DEG is not None:
                    # Explicit legacy override (e.g. B601_MAX_DELTA_DEG=12).
                    if MAX_DELTA_DEG > 0:
                        cmd = _clamp_action(raw, state, MAX_DELTA_DEG, joint_dirs)
                        rate_phase = f"legacy_{MAX_DELTA_DEG:g}"
                    else:
                        cmd = raw
                        rate_phase = "legacy_off"
                elif shoulder_abs < LIFT_DONE_DEG:
                    # Big arm still rising — slow clamp so forearm can keep up.
                    cmd = _clamp_action(raw, state, LIFT_MAX_DELTA_DEG, joint_dirs)
                    rate_phase = "lift"
                elif HIT_MAX_DELTA_DEG > 0:
                    cmd = _clamp_action(raw, state, HIT_MAX_DELTA_DEG, joint_dirs)
                    rate_phase = "hit_limited"
                else:
                    # Raised: uncapped for ice-hockey strike.
                    cmd = raw
                    rate_phase = "hit"
                robot.send_action(_action_dict(cmd))
                n += 1
                _write_status(
                    running=True,
                    phase="running",
                    n=n,
                    rate_phase=rate_phase,
                    shoulder_abs=round(shoulder_abs, 1),
                    latency_ms=data.get("latency_ms"),
                    action7=raw,
                    cmd7=cmd,
                    state7=state,
                )
                if n % 10 == 1:
                    logger.info(
                        "step=%d phase=%s sh=%.0f° latency=%.0fms raw=%s cmd=%s state=%s",
                        n,
                        rate_phase,
                        shoulder_abs,
                        float(data.get("latency_ms") or 0),
                        [round(x, 2) for x in raw],
                        [round(x, 2) for x in cmd],
                        [round(x, 2) for x in state[:7]],
                    )
            except Exception as exc:
                logger.warning("step failed: %s", exc)
                _write_status(running=True, phase="step_error", error=str(exc), n=n)
                time.sleep(0.5)
            dt = time.time() - t0
            if dt < period:
                time.sleep(period - dt)
    finally:
        cap_f.release()
        cap_s.release()
        try:
            robot.disconnect()
        except Exception:
            pass
        _write_status(running=False, phase="stopped", n=n)
        logger.info("stopped after %d steps", n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
