"""Real desktop recording and replay for AutoFlow.

This module deliberately keeps the first useful product small: capture global
mouse and keyboard events, persist them locally, and replay them later.  It has
no network dependency and exposes two emergency stops during replay:

* press Ctrl+Shift+F12
* move the pointer to the top-left corner (PyAutoGUI fail-safe)
"""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from autoflow.config import get_settings

STOP_MODIFIERS = {"ctrl", "shift"}
MODIFIER_NAMES = {
    "ctrl",
    "ctrl_l",
    "ctrl_r",
    "shift",
    "shift_l",
    "shift_r",
}
TASK_ID_PATTERN = re.compile(r"^desktop_[a-f0-9]{10}$")


class DesktopTaskStore:
    """JSON-backed local store for recorded desktop tasks."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or (get_settings().data_dir / "desktop_tasks")
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, recording: dict[str, Any], name: str) -> dict[str, Any]:
        task_id = f"desktop_{uuid.uuid4().hex[:10]}"
        now = datetime.now(timezone.utc).isoformat()
        payload = {
            "id": task_id,
            "name": name.strip() or "未命名自动化",
            "created_at": now,
            "updated_at": now,
            "last_run_at": None,
            "run_count": 0,
            "duration": round(float(recording.get("duration", 0.0)), 3),
            "screen": recording.get("screen", {}),
            "events": recording.get("events", []),
        }
        self._write(payload)
        return payload

    def list(self) -> list[dict[str, Any]]:
        tasks: list[dict[str, Any]] = []
        for path in self.root.glob("desktop_*.json"):
            try:
                task = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            tasks.append(self.summary(task))
        tasks.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
        return tasks

    def get(self, task_id: str) -> dict[str, Any]:
        path = self._path(task_id)
        if not path.exists():
            raise ValueError("没有找到这项自动化。")
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError("自动化文件已损坏。") from exc

    def delete(self, task_id: str) -> None:
        path = self._path(task_id)
        if not path.exists():
            raise ValueError("没有找到这项自动化。")
        path.unlink()

    def rename(self, task_id: str, name: str) -> dict[str, Any]:
        name = name.strip()
        if not name:
            raise ValueError("名称不能为空。")
        task = self.get(task_id)
        task["name"] = name
        task["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._write(task)
        return self.summary(task)

    def mark_run(self, task_id: str) -> None:
        task = self.get(task_id)
        task["run_count"] = int(task.get("run_count", 0)) + 1
        task["last_run_at"] = datetime.now(timezone.utc).isoformat()
        task["updated_at"] = task["last_run_at"]
        self._write(task)

    @staticmethod
    def summary(task: dict[str, Any]) -> dict[str, Any]:
        return {
            key: task.get(key)
            for key in (
                "id",
                "name",
                "created_at",
                "updated_at",
                "last_run_at",
                "run_count",
                "duration",
                "screen",
            )
        } | {"event_count": len(task.get("events", []))}

    def _write(self, payload: dict[str, Any]) -> None:
        path = self._path(str(payload["id"]))
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _path(self, task_id: str) -> Path:
        if not TASK_ID_PATTERN.fullmatch(task_id):
            raise ValueError("无效的自动化编号。")
        return self.root / f"{task_id}.json"


class DesktopRecorder:
    """Capture global mouse and keyboard events until the stop hotkey is used."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._events: list[dict[str, Any]] = []
        self._started_at = 0.0
        self._stopped_at = 0.0
        self._mouse_listener: Any = None
        self._keyboard_listener: Any = None
        self._pressed_buttons: set[str] = set()
        self._modifiers: set[str] = set()
        self._last_move_at = 0.0
        self._screen = {"width": 0, "height": 0}
        self._stopped = threading.Event()
        self._active = False

    @property
    def active(self) -> bool:
        with self._lock:
            return self._active

    def start(self) -> None:
        from pynput import keyboard, mouse
        import pyautogui

        with self._lock:
            if self._active:
                raise RuntimeError("已经在录制中。")
            width, height = pyautogui.size()
            self._screen = {"width": int(width), "height": int(height)}
            self._events = []
            self._pressed_buttons = set()
            self._modifiers = set()
            self._started_at = time.monotonic()
            self._stopped_at = 0.0
            self._last_move_at = 0.0
            self._stopped.clear()
            self._active = True

        self._mouse_listener = mouse.Listener(
            on_move=self._on_move,
            on_click=self._on_click,
            on_scroll=self._on_scroll,
        )
        self._keyboard_listener = keyboard.Listener(
            on_press=self._on_key_press,
            on_release=self._on_key_release,
        )
        self._mouse_listener.start()
        self._keyboard_listener.start()

    def stop(self) -> dict[str, Any]:
        with self._lock:
            if not self._active:
                return self.snapshot()
            self._active = False
            self._stopped_at = time.monotonic()
            self._trim_stop_hotkey()
        if self._mouse_listener is not None:
            self._mouse_listener.stop()
        if self._keyboard_listener is not None:
            self._keyboard_listener.stop()
        self._stopped.set()
        return self.snapshot()

    def wait_stopped(self, timeout: float | None = None) -> bool:
        return self._stopped.wait(timeout)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            end = self._stopped_at or time.monotonic()
            duration = max(0.0, end - self._started_at) if self._started_at else 0.0
            return {
                "duration": duration,
                "screen": dict(self._screen),
                "events": [dict(event) for event in self._events],
            }

    def _timestamp(self) -> float:
        return round(max(0.0, time.monotonic() - self._started_at), 4)

    def _append(self, event: dict[str, Any]) -> None:
        with self._lock:
            # Ignore the browser click that initiated recording.
            if self._active and time.monotonic() - self._started_at >= 0.75:
                self._events.append({"t": self._timestamp(), **event})

    def _on_move(self, x: int, y: int) -> None:
        with self._lock:
            if not self._pressed_buttons:
                return
            now = time.monotonic()
            if now - self._last_move_at < 0.04:
                return
            self._last_move_at = now
        self._append({"type": "mouse_move", "x": int(x), "y": int(y)})

    def _on_click(self, x: int, y: int, button: Any, pressed: bool) -> None:
        name = getattr(button, "name", str(button).split(".")[-1])
        with self._lock:
            if pressed:
                self._pressed_buttons.add(name)
            else:
                self._pressed_buttons.discard(name)
        self._append(
            {
                "type": "mouse_down" if pressed else "mouse_up",
                "x": int(x),
                "y": int(y),
                "button": name,
            }
        )

    def _on_scroll(self, x: int, y: int, dx: int, dy: int) -> None:
        self._append(
            {
                "type": "scroll",
                "x": int(x),
                "y": int(y),
                "dx": int(dx),
                "dy": int(dy),
            }
        )

    def _on_key_press(self, key: Any) -> bool | None:
        spec = serialize_key(key)
        name = str(spec.get("value", ""))
        modifier = normalize_modifier(name)
        if modifier:
            with self._lock:
                self._modifiers.add(modifier)
        if name == "f12" and STOP_MODIFIERS.issubset(self._modifiers):
            threading.Thread(target=self.stop, daemon=True).start()
            return False
        self._append({"type": "key_down", "key": spec})
        return None

    def _on_key_release(self, key: Any) -> None:
        spec = serialize_key(key)
        name = str(spec.get("value", ""))
        self._append({"type": "key_up", "key": spec})
        modifier = normalize_modifier(name)
        if modifier:
            with self._lock:
                self._modifiers.discard(modifier)

    def _trim_stop_hotkey(self) -> None:
        if not self._events:
            return
        cutoff = max(0.0, self._timestamp() - 2.0)
        stop_keys = MODIFIER_NAMES | {"f12"}
        self._events = [
            event
            for event in self._events
            if not (
                event.get("t", 0.0) >= cutoff
                and event.get("type") in {"key_down", "key_up"}
                and event.get("key", {}).get("value") in stop_keys
            )
        ]


class ReplayStopped(RuntimeError):
    """Raised when the user activates an emergency replay stop."""


class DesktopReplayer:
    """Replay locally recorded events with emergency-stop protection."""

    def __init__(self) -> None:
        self.stop_event = threading.Event()
        self.running = False
        self._listener: Any = None
        self._modifiers: set[str] = set()

    def stop(self) -> None:
        self.stop_event.set()

    def run(
        self,
        task: dict[str, Any],
        *,
        speed: float = 1.0,
        progress: Callable[[str], None] | None = None,
    ) -> None:
        import pyautogui
        from pynput import keyboard

        if self.running:
            raise RuntimeError("已有自动化正在运行。")
        events = task.get("events", [])
        if not events:
            raise ValueError("这项自动化没有可执行的操作。")
        if speed <= 0:
            raise ValueError("运行速度必须大于 0。")

        self.running = True
        self.stop_event.clear()
        self._modifiers = set()
        notify = progress or (lambda _message: None)
        pyautogui.FAILSAFE = True
        pyautogui.PAUSE = 0.02
        current_width, current_height = pyautogui.size()
        recorded = task.get("screen", {})
        source_width = max(1, int(recorded.get("width") or current_width))
        source_height = max(1, int(recorded.get("height") or current_height))
        scale_x = current_width / source_width
        scale_y = current_height / source_height

        self._listener = keyboard.Listener(on_press=self._on_stop_key_press, on_release=self._on_stop_key_release)
        self._listener.start()
        notify("自动化开始运行。把鼠标移到左上角可立即停止。")
        previous = 0.0
        try:
            for index, event in enumerate(events):
                if self.stop_event.is_set():
                    raise ReplayStopped("已紧急停止。")
                timestamp = float(event.get("t", previous))
                self._sleep(max(0.0, timestamp - previous) / speed)
                previous = timestamp
                self._apply_event(event, scale_x, scale_y, pyautogui)
                if index and index % 25 == 0:
                    notify(f"正在执行… {index}/{len(events)}")
        except pyautogui.FailSafeException as exc:
            raise ReplayStopped("鼠标已移到左上角，自动化停止。") from exc
        finally:
            self.running = False
            self.stop_event.set()
            if self._listener is not None:
                self._listener.stop()
            self._release_controls(pyautogui)
        notify("自动化执行完成。")

    def _sleep(self, seconds: float) -> None:
        deadline = time.monotonic() + seconds
        while True:
            if self.stop_event.is_set():
                raise ReplayStopped("已紧急停止。")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            time.sleep(min(remaining, 0.05))

    def _apply_event(self, event: dict[str, Any], sx: float, sy: float, gui: Any) -> None:
        event_type = event.get("type")
        if event_type.startswith("mouse_") or event_type == "scroll":
            x = round(float(event.get("x", 0)) * sx)
            y = round(float(event.get("y", 0)) * sy)
        if event_type == "mouse_move":
            gui.moveTo(x, y, duration=0)
        elif event_type == "mouse_down":
            gui.moveTo(x, y, duration=0)
            gui.mouseDown(button=event.get("button", "left"))
        elif event_type == "mouse_up":
            gui.moveTo(x, y, duration=0)
            gui.mouseUp(button=event.get("button", "left"))
        elif event_type == "scroll":
            gui.moveTo(x, y, duration=0)
            gui.hscroll(int(event.get("dx", 0))) if event.get("dx") else None
            gui.scroll(int(event.get("dy", 0))) if event.get("dy") else None
        elif event_type in {"key_down", "key_up"}:
            key = pyautogui_key(event.get("key", {}))
            if not key:
                return
            if event_type == "key_down":
                gui.keyDown(key)
            else:
                gui.keyUp(key)

    def _on_stop_key_press(self, key: Any) -> bool | None:
        spec = serialize_key(key)
        name = str(spec.get("value", ""))
        modifier = normalize_modifier(name)
        if modifier:
            self._modifiers.add(modifier)
        if name == "f12" and STOP_MODIFIERS.issubset(self._modifiers):
            self.stop()
            return False
        return None

    def _on_stop_key_release(self, key: Any) -> None:
        spec = serialize_key(key)
        modifier = normalize_modifier(str(spec.get("value", "")))
        if modifier:
            self._modifiers.discard(modifier)

    @staticmethod
    def _release_controls(gui: Any) -> None:
        for key in ("ctrl", "shift", "alt", "win"):
            try:
                gui.keyUp(key)
            except Exception:
                pass
        for button in ("left", "right", "middle"):
            try:
                gui.mouseUp(button=button)
            except Exception:
                pass


def serialize_key(key: Any) -> dict[str, str]:
    """Convert a pynput key into a stable JSON representation."""
    char = getattr(key, "char", None)
    if char is not None:
        return {"kind": "char", "value": char}
    name = getattr(key, "name", None)
    if name:
        return {"kind": "special", "value": str(name)}
    text = str(key)
    if text.startswith("Key."):
        text = text[4:]
    return {"kind": "special", "value": text.strip("'")}


def normalize_modifier(name: str) -> str | None:
    if name.startswith("ctrl"):
        return "ctrl"
    if name.startswith("shift"):
        return "shift"
    return None


def pyautogui_key(spec: dict[str, Any]) -> str:
    value = str(spec.get("value", ""))
    if spec.get("kind") == "char":
        return value
    aliases = {
        "ctrl_l": "ctrl",
        "ctrl_r": "ctrl",
        "shift_l": "shift",
        "shift_r": "shift",
        "alt_l": "alt",
        "alt_r": "alt",
        "alt_gr": "altright",
        "cmd": "win",
        "cmd_l": "winleft",
        "cmd_r": "winright",
        "page_up": "pgup",
        "page_down": "pgdn",
        "caps_lock": "capslock",
        "num_lock": "numlock",
        "print_screen": "printscreen",
    }
    return aliases.get(value, value)
