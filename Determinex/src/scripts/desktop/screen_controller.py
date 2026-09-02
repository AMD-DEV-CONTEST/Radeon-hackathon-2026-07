"""
Screen controller for desktop agent — captures screenshots and executes pointer/keyboard
actions inside a VM via VNC or RDP. NO host pyautogui calls are permitted.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from agents.base_agent import ActionResult, ActionType, AgentAction, AgentObservation, EnvType

log = logging.getLogger(__name__)

try:
    import vncdotool.api as _vnc_api

    _VNC_AVAILABLE = True
except ImportError:
    _VNC_AVAILABLE = False
    log.warning("[screen_controller] vncdotool not installed — VNC actions unavailable")


class ScreenController:
    """
    Controls a VM display via VNC.
    Hard rule: this module ONLY connects to VMs (by IP:port), never to localhost.
    """

    def __init__(self, vm_ip: str, vnc_port: int = 5900, screenshot_dir: str | Path = ".") -> None:
        if vm_ip.lower() in ("localhost", "127.0.0.1", "::1"):
            raise ValueError(
                "ScreenController refuses to connect to localhost. "
                "Desktop agents must run inside a VM. Use vm_manager to start one."
            )
        self.vm_ip = vm_ip
        self.vnc_port = vnc_port
        self.screenshot_dir = Path(screenshot_dir)
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        self._client = None
        self._step = 0

    def connect(self) -> None:
        if not _VNC_AVAILABLE:
            raise RuntimeError("vncdotool required for ScreenController. pip install vncdotool")
        self._client = _vnc_api.connect(self.vm_ip, port=self.vnc_port)
        log.info("[screen_controller] connected to %s:%d", self.vm_ip, self.vnc_port)

    def disconnect(self) -> None:
        if self._client:
            try:
                self._client.disconnect()
            except Exception:
                pass
            self._client = None

    def __enter__(self) -> ScreenController:
        self.connect()
        return self

    def __exit__(self, *args: Any) -> None:
        self.disconnect()

    # ------------------------------------------------------------------
    # Screenshot
    # ------------------------------------------------------------------

    def take_screenshot(self, label: str = "screen") -> Path:
        path = self.screenshot_dir / f"{label}_{self._step}.png"
        if self._client:
            self._client.captureScreen(str(path))
        return path

    def capture_observation(self, task_id: str) -> AgentObservation:
        from vision.screenshot_loader import screenshot_hash

        path = self.take_screenshot(f"obs_{task_id}")
        return AgentObservation(
            env_type=EnvType.DESKTOP,
            step=self._step,
            screenshot_path=str(path),
            screenshot_hash=screenshot_hash(path),
        )

    # ------------------------------------------------------------------
    # Actions (all via VM-bound VNC connection)
    # ------------------------------------------------------------------

    def click(self, x: int, y: int, button: str = "left") -> None:
        if self._client:
            self._client.mouseMove(x, y)
            self._client.mousePress(1 if button == "left" else 3)

    def double_click(self, x: int, y: int) -> None:
        if self._client:
            self._client.mouseMove(x, y)
            self._client.mousePress(1)
            time.sleep(0.05)
            self._client.mousePress(1)

    def type_text(self, text: str) -> None:
        if self._client:
            self._client.type(text)

    def press_key(self, key: str) -> None:
        if self._client:
            self._client.keyPress(key)

    def scroll(self, x: int, y: int, direction: str = "down", clicks: int = 3) -> None:
        if self._client:
            self._client.mouseMove(x, y)
            button = 5 if direction == "down" else 4
            for _ in range(clicks):
                self._client.mousePress(button)

    def drag(self, x1: int, y1: int, x2: int, y2: int) -> None:
        if self._client:
            self._client.mouseMove(x1, y1)
            self._client.mouseDown(1)
            time.sleep(0.1)
            self._client.mouseMove(x2, y2)
            time.sleep(0.1)
            self._client.mouseUp(1)

    def execute_action(self, action: AgentAction) -> ActionResult:
        """Dispatch an AgentAction to the VM screen."""
        t0 = time.monotonic()
        try:
            at = action.action_type
            if at == ActionType.READ_SCREEN:
                path = self.take_screenshot("read_screen")
                return ActionResult(action=action, success=True, metadata={"screenshot": str(path)})
            if at == ActionType.CLICK:
                self.click(action.x or 0, action.y or 0)
                return ActionResult(action=action, success=True)
            if at == ActionType.TYPE:
                self.type_text(action.payload or "")
                return ActionResult(action=action, success=True)
            if at == ActionType.PRESS_KEY:
                self.press_key(action.payload or "Return")
                return ActionResult(action=action, success=True)
            if at == ActionType.SCROLL:
                self.scroll(action.x or 400, action.y or 400)
                return ActionResult(action=action, success=True)
            if at == ActionType.DRAG:
                meta = action.metadata
                self.drag(action.x or 0, action.y or 0, meta.get("x2", 0), meta.get("y2", 0))
                return ActionResult(action=action, success=True)
            return ActionResult(action=action, success=False, error=f"Unhandled action type: {at}")
        except Exception as exc:
            return ActionResult(
                action=action,
                success=False,
                error=str(exc),
                duration_ms=int((time.monotonic() - t0) * 1000),
            )
        finally:
            self._step += 1
