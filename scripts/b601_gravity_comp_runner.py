#!/usr/bin/env python3
"""B601 gravity compensation runner — basic or end-effector lock mode."""
from __future__ import annotations

import argparse
import json
import signal
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np

_running = True


def _handle_sig(signum, frame) -> None:  # noqa: ANN001
    global _running
    _running = False


def _sdk_paths() -> None:
    vendor = Path(__file__).resolve().parents[1] / "vendor" / "reBotArm_control_py"
    if vendor.is_dir():
        sys.path.insert(0, str(vendor))
    home = Path.home() / "reBotArm_control_py"
    if home.is_dir():
        sys.path.insert(0, str(home))


def _import_sdk():
    _sdk_paths()
    from reBotArm_control_py.actuator import RebotArm
    from reBotArm_control_py.dynamics import compute_generalized_gravity

    return RebotArm, compute_generalized_gravity


def _send_state(payload: Dict[str, Any], state_file: Optional[Path] = None) -> None:
    if state_file:
        try:
            state_file.write_text(json.dumps(payload), encoding="utf-8")
        except Exception:
            pass


def run(mode: str, gains: Dict[int, float], can: str, state_port: int) -> int:
    global _running
    signal.signal(signal.SIGINT, _handle_sig)
    signal.signal(signal.SIGTERM, _handle_sig)

    RebotArm, compute_generalized_gravity = _import_sdk()
    arm = RebotArm()
    if can and can != "can0":
        arm._cfg["channel"] = can  # noqa: SLF001 — runner override

    state_file = Path("/tmp/b601_gravity_comp_state.json")
    q_target: Optional[np.ndarray] = None
    lock_vel_thresh = 0.04
    lock_ang_thresh = 0.08
    locked = False
    counter = 0
    # Which motors answer on CAN. A dead joint (e.g. a dropped gripper) is
    # skipped: broadcast enable/disable ACK-times-out on a dead motor and would
    # otherwise leave the whole arm un-enabled (no torque).
    gripper_state = {"online": False}
    online_motors: list = []
    # Safety heartbeat: re-assert enable on the live motors periodically. The
    # 500 Hz MIT stream is normally enough to keep RobStride energized, but this
    # is belt-and-suspenders so a single missed/faulted enable can never leave
    # the arm silently de-energized mid-float (→ sudden drop). enable() is a
    # control command; it does NOT write any motor register/parameter.
    reenable = {"last": 0.0, "period_s": 0.5}

    def control_loop(r: Any, dt: float) -> None:
        nonlocal q_target, locked, counter
        lin_v = 0.0
        ang_v = 0.0
        # RobStride auto-replies its state after every MIT command, so we read
        # the cached position without an extra request frame — this matches the
        # official example (9_gravity_compensation.py) and, crucially, keeps the
        # bus quiet so the MIT command stream stays gap-free (extra request
        # frames caused command gaps → the motor dropped torque + jerked).
        q = r.arm.get_positions(request_feedback=False)
        tau_g = compute_generalized_gravity(q=q)
        for jid, gain in gains.items():
            idx = int(jid) - 1
            if 0 <= idx < len(tau_g):
                tau_g[idx] *= float(gain)

        if mode == "lock":
            if control_loop._prev_q is not None and dt > 0:
                dq = q - control_loop._prev_q
                lin_v = float(np.linalg.norm(dq[:3]) / dt)
                ang_v = float(np.linalg.norm(dq[3:6]) / dt)
            control_loop._prev_q = q.copy()
            if lin_v < lock_vel_thresh and ang_v < lock_ang_thresh:
                if q_target is None:
                    q_target = q.copy()
                locked = True
            else:
                q_target = q.copy()
                locked = False
            # Official lock gains (10_gravity_compensation_lock.py).
            kp, kd = 8.0, 1.0
            pos_cmd = q_target if q_target is not None else q
        else:
            locked = False
            # Official basic gains (9_gravity_compensation.py): position
            # closed-loop + gravity feedforward → hand-push floats at pose.
            kp, kd = 2.0, 1.0
            pos_cmd = q

        r.arm.send_mit(
            pos=pos_cmd,
            vel=np.zeros(r.arm.num_joints),
            kp=np.full(r.arm.num_joints, kp),
            kd=np.full(r.arm.num_joints, kd),
            tau=tau_g,
        )
        if r.has_gripper and gripper_state["online"]:
            try:
                r.gripper.send_mit(r.gripper.get_positions(request_feedback=False))
            except Exception:
                pass

        now = time.monotonic()
        if now - reenable["last"] >= reenable["period_s"]:
            reenable["last"] = now
            for _m in online_motors:
                try:
                    _m.enable()
                except Exception:
                    pass

        counter += 1
        if counter % 4 == 0:
            _send_state(
                {
                    "joints": {f"joint{i + 1}": float(q[i]) for i in range(min(6, len(q)))},
                    "joint7": float(q[6]) if len(q) > 6 else 0.0,
                    "tau_g": [float(t) for t in tau_g[:6]],
                    "ee_velocity": lin_v if mode == "lock" else 0.0,
                    "ee_angular_velocity": ang_v if mode == "lock" else 0.0,
                    "locked": locked,
                    "timestamp": time.time(),
                },
                state_file,
            )

    control_loop._prev_q = None  # type: ignore[attr-defined]

    def _probe_online(motor: Any, timeout_ms: int = 400) -> bool:
        try:
            motor.robstride_get_param_i8(0x7005, timeout_ms)
            return True
        except Exception:
            pass
        try:
            return motor.get_state() is not None
        except Exception:
            return False

    try:
        arm.connect()

        # Detect which motors actually answer on CAN; skip the rest.
        online = {name: _probe_online(m) for name, m in arm._motor_map.items()}  # noqa: SLF001
        gripper_state["online"] = bool(online.get("gripper", False))
        online_motors[:] = [m for name, m in arm._motor_map.items() if online.get(name)]  # noqa: SLF001
        offline = [n for n, ok in online.items() if not ok]
        if offline:
            print(
                json.dumps({"ok": True, "info": "skipping offline motors", "offline": offline}),
                flush=True,
            )

        # mode_mit on the arm group is already per-joint (only a dead joint errors).
        arm.arm.mode_mit()
        if gripper_state["online"]:
            arm.gripper.mode_mit()

        # Per-motor disable/enable ONLY the online motors. Broadcast enable_all()
        # waits for an ACK from every motor on the bus, so one dead motor makes it
        # time out and the live joints never get enabled → zero torque.
        for name, m in arm._motor_map.items():  # noqa: SLF001
            if online.get(name):
                try:
                    m.disable()
                except Exception:
                    pass
        time.sleep(0.15)
        for name, m in arm._motor_map.items():  # noqa: SLF001
            if online.get(name):
                try:
                    m.enable()
                except Exception:
                    pass

        # Warm up feedback so first MIT command uses actual joint angles (no jump).
        for _ in range(5):
            arm.arm.get_positions(request_feedback=True)
            time.sleep(0.02)
        arm.start_control_loop(control_loop, rate=arm.rate)
        while _running:
            time.sleep(0.05)
    except Exception as exc:
        print(json.dumps({"ok": False, "message": str(exc)}), flush=True)
        return 1
    finally:
        try:
            arm.stop_control_loop()
        except Exception:
            pass
        # Smooth stop (community "MIT ramp-out"): keep the gravity feedforward so
        # the arm doesn't drop, but ramp the position stiffness (kp/kd) down to
        # zero over a few frames so releasing the hold is gentle instead of a
        # snap/clack, then de-energize.
        try:
            n = arm.arm.num_joints
            q_last = arm.arm.get_positions(request_feedback=False)
            tau_last = compute_generalized_gravity(q=q_last)
            for jid, gain in gains.items():
                idx = int(jid) - 1
                if 0 <= idx < len(tau_last):
                    tau_last[idx] *= float(gain)
            base_kp, base_kd = (8.0, 1.0) if mode == "lock" else (2.0, 1.0)
            for scale in (0.66, 0.33, 0.0):
                arm.arm.send_mit(
                    pos=q_last,
                    vel=np.zeros(n),
                    kp=np.full(n, base_kp * scale),
                    kd=np.full(n, base_kd * scale),
                    tau=tau_last,
                )
                time.sleep(0.04)
        except Exception:
            pass
        # Per-motor disable (safe de-energize) before tearing down the bus.
        try:
            for _name, _m in list(getattr(arm, "_motor_map", {}).items()):  # noqa: SLF001
                try:
                    _m.disable()
                except Exception:
                    pass
        except Exception:
            pass
        try:
            arm.disconnect()
        except Exception:
            pass
        try:
            state_file.unlink(missing_ok=True)
        except Exception:
            pass

    print(json.dumps({"ok": True, "stopped": True}), flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("basic", "lock"), default="basic")
    parser.add_argument("--gains-json", default="{}")
    parser.add_argument("--can", default="can0")
    parser.add_argument("--state-port", type=int, default=18765)
    args = parser.parse_args()
    try:
        raw_gains = json.loads(args.gains_json)
        gains = {int(k): float(v) for k, v in raw_gains.items()}
    except (json.JSONDecodeError, TypeError, ValueError):
        gains = {}
    return run(args.mode, gains, args.can, args.state_port)


if __name__ == "__main__":
    raise SystemExit(main())
