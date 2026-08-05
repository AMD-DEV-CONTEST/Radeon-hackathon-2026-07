"""
ADB controller — the ONLY module that calls adb.
All mobile actions go through safety_governor first.
"""

from __future__ import annotations

import logging
import subprocess
import time
from pathlib import Path
from typing import Any

from agents.base_agent import (
    ActionResult,
    ActionType,
    AgentAction,
    AgentObservation,
    EnvType,
)
from agents.safety_governor import get_governor
from corpus.corpus_manager import get_manager

log = logging.getLogger(__name__)


def _adb(serial: str, *args: str, timeout: int = 30) -> subprocess.CompletedProcess:
    cmd = ["adb", "-s", serial] + list(args)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


class AdbController:
    """
    Controls an Android device (emulator only by default) via adb.
    Every action goes through safety_governor first.
    """

    def __init__(
        self,
        task: Any,
        serial: str,
        screenshot_dir: str | Path = ".",
    ) -> None:
        self.task = task
        self.serial = serial
        self.screenshot_dir = Path(screenshot_dir)
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        self._governor = get_governor()
        self._corpus = get_manager()
        self._step = 0

    # ------------------------------------------------------------------
    # Screenshot
    # ------------------------------------------------------------------

    def take_screenshot(self, label: str = "screen") -> Path:
        path = self.screenshot_dir / f"{label}_{self._step}.png"
        remote = "/sdcard/determinex_screenshot.png"
        _adb(self.serial, "shell", "screencap", "-p", remote)
        _adb(self.serial, "pull", remote, str(path))
        return path

    def capture_observation(self) -> AgentObservation:
        from vision.screenshot_loader import screenshot_hash

        from mobile.uiautomator_reader import dump_ui_xml

        path = self.take_screenshot(f"obs_{self.task.task_id}")
        ui_xml = dump_ui_xml(self.serial)
        import hashlib

        xml_hash = hashlib.sha256(ui_xml.encode()).hexdigest() if ui_xml else ""
        return AgentObservation(
            env_type=EnvType.MOBILE,
            step=self._step,
            screenshot_path=str(path),
            screenshot_hash=screenshot_hash(path),
            accessibility_tree=ui_xml[:8192] if ui_xml else None,
            accessibility_hash=xml_hash,
            activity=self.current_activity(),
        )

    # ------------------------------------------------------------------
    # Device queries
    # ------------------------------------------------------------------

    def current_activity(self) -> str:
        try:
            r = _adb(
                self.serial,
                "shell",
                "dumpsys",
                "activity",
                "activities",
                "|",
                "grep",
                "mResumedActivity",
            )
            return r.stdout.strip().split()[-1] if r.stdout.strip() else ""
        except Exception:
            return ""

    def get_installed_packages(self) -> list[str]:
        r = _adb(self.serial, "shell", "pm", "list", "packages")
        return [
            line.replace("package:", "").strip() for line in r.stdout.splitlines() if line.strip()
        ]

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def execute(self, action: AgentAction) -> ActionResult:
        obs = self.capture_observation()
        t0 = time.monotonic()

        decision = self._governor.evaluate_action(self.task, obs, action)
        action.safety_decision = decision.value.value

        if decision.is_blocked:
            self._corpus.write_refusal(
                task_id=self.task.task_id,
                trigger="action",
                layer="L5",
                category=decision.reason,
                violating_excerpt=f"{action.action_type.value}: {action.target or ''} {action.payload or ''}",
                benchmark=self.task.source_benchmark,
            )
            return ActionResult(
                action=action,
                success=False,
                error=f"BLOCKED: {decision.reason}",
                duration_ms=int((time.monotonic() - t0) * 1000),
            )

        if decision.needs_confirmation:
            return ActionResult(
                action=action,
                success=False,
                error=f"Action {action.action_type.value} requires confirmation",
                duration_ms=int((time.monotonic() - t0) * 1000),
            )

        try:
            result = self._dispatch(action)
            result.duration_ms = int((time.monotonic() - t0) * 1000)
            result.observation_after = self.capture_observation()
            self._step += 1
            return result
        except Exception as exc:
            return ActionResult(
                action=action,
                success=False,
                error=str(exc),
                duration_ms=int((time.monotonic() - t0) * 1000),
            )

    def _dispatch(self, action: AgentAction) -> ActionResult:
        at = action.action_type

        if at == ActionType.READ_SCREEN:
            path = self.take_screenshot("read_screen")
            return ActionResult(action=action, success=True, metadata={"screenshot": str(path)})

        if at == ActionType.TAP:
            x, y = action.x or 0, action.y or 0
            _adb(self.serial, "shell", "input", "tap", str(x), str(y))
            return ActionResult(action=action, success=True)

        if at == ActionType.SWIPE:
            meta = action.metadata
            x1, y1 = action.x or 0, action.y or 0
            x2, y2 = meta.get("x2", x1), meta.get("y2", y1 + 300)
            duration = meta.get("duration_ms", 300)
            _adb(
                self.serial,
                "shell",
                "input",
                "swipe",
                str(x1),
                str(y1),
                str(x2),
                str(y2),
                str(duration),
            )
            return ActionResult(action=action, success=True)

        if at == ActionType.TYPE:
            text = (action.payload or "").replace(" ", "%s")
            _adb(self.serial, "shell", "input", "text", text)
            return ActionResult(action=action, success=True)

        if at == ActionType.PRESS_KEY:
            # Map common key names to ADB key events
            key_map = {
                "BACK": "4",
                "HOME": "3",
                "ENTER": "66",
                "DELETE": "67",
                "VOLUME_UP": "24",
                "VOLUME_DOWN": "25",
            }
            keycode = key_map.get(action.payload or "", action.payload or "66")
            _adb(self.serial, "shell", "input", "keyevent", keycode)
            return ActionResult(action=action, success=True)

        if at == ActionType.OPEN_APP:
            _adb(
                self.serial,
                "shell",
                "monkey",
                "-p",
                action.target or "",
                "-c",
                "android.intent.category.LAUNCHER",
                "1",
            )
            return ActionResult(action=action, success=True)

        if at == ActionType.RUN_COMMAND:
            r = _adb(self.serial, "shell", action.payload or "echo ok")
            return ActionResult(
                action=action,
                success=r.returncode == 0,
                metadata={"stdout": r.stdout[:500], "rc": r.returncode},
            )

        raise ValueError(f"Unhandled action type in adb_controller: {at}")
