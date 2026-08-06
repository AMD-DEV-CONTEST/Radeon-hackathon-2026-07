#!/usr/bin/env python3
"""lerobot-teleoperate with B601 configure() tolerant of disable_all broadcast timeout.

Also patches SeeedB601FollowerBase.get_observation to dump live joint positions
to /tmp/b601_joints_live.json for the web UI.

Demo-safe: any offline joint is skipped so teleop still starts (e.g. gripper ID7
dropped off CAN). Skipped motors are not commanded in send_action.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

LIVE_JOINTS_FILE = Path(os.environ.get("B601_LIVE_JOINTS_FILE", "/tmp/b601_joints_live.json"))
LIVE_JOINTS_TTL_S = 5.0


def _apply_configure_patch() -> None:
    from lerobot_robot_seeed_b601.seeed_b601_follower import (
        FOLLOWER_GRIPPER_MOTOR,
        MEDIUM_TIMEOUT_SEC,
        MotorBridgeMode,
        SeeedB601FollowerBase,
        logger,
    )

    if getattr(SeeedB601FollowerBase.configure, "_botversex_patched", False):
        return

    def _motor_online(motor, *, timeout_ms: int = 250) -> bool:
        try:
            motor.robstride_get_param_i8(0x7005, timeout_ms)
            return True
        except Exception:
            pass
        try:
            return motor.get_state() is not None
        except Exception:
            return False

    def configure(self: SeeedB601FollowerBase) -> None:
        self._botversex_skip_motors = set()  # type: ignore[attr-defined]

        try:
            self.bus.disable_all()
        except Exception as exc:
            logger.warning(
                "disable_all broadcast failed (%s) — per-motor disable fallback (BotverseX)",
                exc,
            )
            for motor_name, motor in self.motors.items():
                if motor_name in self._botversex_skip_motors:
                    continue
                try:
                    motor.disable()
                except Exception:
                    pass

        num_retry = 9
        total = len(self.motors)
        for idx, (motor_name, motor) in enumerate(self.motors.items(), start=1):
            if not _motor_online(motor, timeout_ms=350):
                self._botversex_skip_motors.add(motor_name)  # type: ignore[attr-defined]
                logger.warning(
                    "[%d/%d] %s offline on CAN — skipping (teleop continues without this joint)",
                    idx,
                    total,
                    motor_name,
                )
                continue

            target_mode = (
                MotorBridgeMode.MIT
                if self.motor_type == "rs"
                else (
                    MotorBridgeMode.FORCE_POS
                    if motor_name == FOLLOWER_GRIPPER_MOTOR
                    else MotorBridgeMode.POS_VEL
                )
            )
            logger.info("[%d/%d] %s ensure_mode %s (BotverseX)", idx, total, motor_name, target_mode)
            is_gripper = motor_name == FOLLOWER_GRIPPER_MOTOR
            max_attempts = (3 if is_gripper else num_retry) + 1
            mode_timeout_ms = 2000 if is_gripper else 2500
            last_exc: Exception | None = None
            ok = False
            for attempt in range(max_attempts):
                try:
                    if attempt > 0:
                        try:
                            motor.disable()
                        except Exception:
                            pass
                        time.sleep(0.15 + attempt * 0.1)
                    motor.ensure_mode(target_mode, timeout_ms=mode_timeout_ms)
                    ok = True
                    break
                except Exception as exc:
                    last_exc = exc
                    if attempt == max_attempts - 1:
                        break
                    time.sleep(0.15 if is_gripper else MEDIUM_TIMEOUT_SEC)
            if ok:
                logger.info("[%d/%d] %s ensure mode %s OK", idx, total, motor_name, target_mode)
            else:
                self._botversex_skip_motors.add(motor_name)  # type: ignore[attr-defined]
                logger.warning(
                    "[%d/%d] %s ensure_mode failed (%s) — skipping joint",
                    idx,
                    total,
                    motor_name,
                    last_exc,
                )

        skipped = getattr(self, "_botversex_skip_motors", set())
        active = total - len(skipped)
        if active < 1:
            raise RuntimeError(
                "没有可用电机 — 请检查 48V、PCAN 与 CAN 线后重试。"
            )

        try:
            self.bus.enable_all()
        except Exception as exc:
            logger.warning("enable_all failed (%s) — per-motor enable (BotverseX)", exc)
            for motor_name, motor in self.motors.items():
                if motor_name in skipped:
                    continue
                try:
                    motor.enable()
                except Exception:
                    pass

        if skipped:
            logger.warning(
                "configure done — teleop with %d/%d joints (skipped: %s)",
                active,
                total,
                sorted(skipped),
            )
        else:
            logger.info("configure done — entering teleop loop (BotverseX)")

    configure._botversex_patched = True  # type: ignore[attr-defined]
    SeeedB601FollowerBase.configure = configure  # type: ignore[method-assign]


def _apply_send_action_skip_patch() -> None:
    from lerobot_robot_seeed_b601.seeed_b601_follower import SeeedB601FollowerBase

    if getattr(SeeedB601FollowerBase.send_action, "_botversex_skip_patched", False):
        return

    original = SeeedB601FollowerBase.send_action

    def send_action(self: SeeedB601FollowerBase, action, *args, **kwargs):
        skip = getattr(self, "_botversex_skip_motors", None)
        if skip and isinstance(action, dict):
            action = {
                k: v for k, v in action.items() if not any(name in k for name in skip)
            }
        return original(self, action, *args, **kwargs)

    send_action._botversex_skip_patched = True  # type: ignore[attr-defined]
    SeeedB601FollowerBase.send_action = send_action  # type: ignore[method-assign]


def _apply_observation_patch() -> None:
    from lerobot_robot_seeed_b601.seeed_b601_follower import SeeedB601FollowerBase, logger

    if getattr(SeeedB601FollowerBase.get_observation, "_botversex_live_patched", False):
        return

    original = SeeedB601FollowerBase.get_observation
    last_write = [0.0]
    name_to_joint = {
        "shoulder_pan": 1,
        "shoulder_lift": 2,
        "elbow_flex": 3,
        "wrist_flex": 4,
        "wrist_yaw": 5,
        "wrist_roll": 6,
        "gripper": 7,
    }

    def get_observation(self: SeeedB601FollowerBase):
        obs = original(self)
        try:
            now = time.monotonic()
            if now - last_write[0] < 0.016:
                return obs
            last_write[0] = now
            joints: dict[str, float] = {}
            for motor_name, motor in self.motors.items():
                try:
                    state = motor.get_state()
                    if state is not None:
                        idx = name_to_joint.get(motor_name)
                        if idx is not None:
                            joints[f"joint{idx}"] = float(state.pos)
                except Exception:
                    pass
            payload = {
                "ok": True,
                "teleop_running": True,
                "ts": time.time(),
                "joints": joints,
                "units": "rad",
            }
            tmp = LIVE_JOINTS_FILE.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(payload))
            tmp.replace(LIVE_JOINTS_FILE)
        except Exception as exc:
            logger.debug("live joints dump failed: %s", exc)
        return obs

    get_observation._botversex_live_patched = True  # type: ignore[attr-defined]
    SeeedB601FollowerBase.get_observation = get_observation  # type: ignore[method-assign]


def main() -> None:
    _apply_configure_patch()
    _apply_send_action_skip_patch()
    _apply_observation_patch()
    from lerobot.scripts.lerobot_teleoperate import main as lerobot_main

    lerobot_main()


if __name__ == "__main__":
    main()
