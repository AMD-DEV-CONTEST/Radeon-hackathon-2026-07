"""Universal, observable computer tools used by the AutoFlow agent."""

from __future__ import annotations

import os
import re
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from autoflow.assistant import AppResolver


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    risk: str
    parameters: dict[str, str]


def _vk_code_table() -> dict[str, int]:
    """Build a name → virtual-key-code map usable for PostMessage."""
    vk: dict[str, int] = {
        "ctrl": 0x11,
        "ctrl_l": 0xA2,
        "ctrl_r": 0xA3,
        "shift": 0x10,
        "shift_l": 0xA0,
        "shift_r": 0xA1,
        "alt": 0x12,
        "alt_l": 0xA4,
        "alt_r": 0xA5,
        "win": 0x5B,
        "win_l": 0x5B,
        "win_r": 0x5C,
        "enter": 0x0D,
        "return": 0x0D,
        "tab": 0x09,
        "escape": 0x1B,
        "esc": 0x1B,
        "space": 0x20,
        "backspace": 0x08,
        "delete": 0x2E,
        "del": 0x2E,
        "insert": 0x2D,
        "ins": 0x2D,
        "home": 0x24,
        "end": 0x23,
        "page_up": 0x21,
        "page_down": 0x22,
        "pgup": 0x21,
        "pgdn": 0x22,
        "left": 0x25,
        "right": 0x27,
        "up": 0x26,
        "down": 0x28,
        "print_screen": 0x2C,
        "prtsc": 0x2C,
        "caps_lock": 0x14,
        "num_lock": 0x90,
        "scroll_lock": 0x91,
        "pause": 0x13,
        "apps": 0x5D,
        "menu": 0x5D,
        "volume_mute": 0xAD,
        "volume_down": 0xAE,
        "volume_up": 0xAF,
        "media_next": 0xB0,
        "media_prev": 0xB1,
        "media_stop": 0xB2,
        "media_play_pause": 0xB3,
    }
    for i in range(1, 13):
        vk[f"f{i}"] = 0x6F + i
    for i in range(ord("a"), ord("z") + 1):
        vk[chr(i)] = i - 32
    for i in range(10):
        vk[str(i)] = ord("0") + i
    return vk


VK_CODES = _vk_code_table()

_EXTENDED_VK = {
    0x5C,
    0x5D,
    0xA2,
    0xA3,
    0xA4,
    0xA5,
    0x25,
    0x27,
    0x26,
    0x28,
    0x21,
    0x22,
    0x23,
    0x24,
    0x2D,
    0x2E,
}


def _post_key_message(hwnd: int, vk: int, down: bool, user32: Any = None) -> bool:
    """Post WM_KEYDOWN / WM_KEYUP to a window with correct scan-code lparam.

    Returns True if PostMessageW succeeded, False otherwise.
    """
    if user32 is None:
        import ctypes as _ct

        user32 = _ct.windll.user32
    if not user32.IsWindow(hwnd):
        return False
    scan = user32.MapVirtualKeyW(vk, 0)
    ext = 1 if vk in _EXTENDED_VK else 0
    lparam = (scan << 16) | (ext << 24)
    if not down:
        lparam |= (1 << 30) | (1 << 31)
    msg = 0x0100 if down else 0x0101  # WM_KEYDOWN=0x0100, WM_KEYUP=0x0101
    return bool(user32.PostMessageW(hwnd, msg, vk, lparam))


class WindowsObserver:
    """Read windows and UI Automation controls without relying on coordinates."""

    def __init__(self, desktop_factory: Callable[..., Any] | None = None) -> None:
        self.desktop_factory = desktop_factory
        self._elements: dict[str, Any] = {}

    def observe(self, *, window_title: str = "", max_windows: int = 20, max_elements: int = 100) -> dict[str, Any]:
        try:
            desktop = self._desktop()
            windows = []
            visible_wrappers = []
            for wrapper in desktop.windows()[:max_windows]:
                try:
                    title = wrapper.window_text().strip()
                    if title and wrapper.is_visible():
                        visible_wrappers.append(wrapper)
                        windows.append({"title": title, "type": wrapper.element_info.control_type, "enabled": bool(wrapper.is_enabled())})
                except Exception:
                    continue

            foreground = desktop.window(active_only=True)
            foreground_title = foreground.window_text().strip()
            observed = foreground
            if window_title.strip():
                needle = window_title.strip().casefold()
                match = next((wrapper for wrapper in visible_wrappers if needle in wrapper.window_text().strip().casefold()), None)
                if match is None:
                    raise ValueError(f"找不到后台任务窗口：{window_title}")
                observed = match
            observed_title = observed.window_text().strip()
            elements = []
            cache: dict[str, Any] = {}
            for index, wrapper in enumerate(observed.descendants()[:max_elements], start=1):
                try:
                    info = wrapper.element_info
                    name = (wrapper.window_text() or info.name or "").strip()
                    control_type = info.control_type or "Unknown"
                    if not name and control_type not in {"Edit", "Button", "ComboBox", "ListItem", "TabItem"}:
                        continue
                    rect = wrapper.rectangle()
                    element_id = f"e{index:03d}"
                    cache[element_id] = wrapper
                    elements.append({
                        "id": element_id,
                        "name": name[:160],
                        "type": control_type,
                        "enabled": bool(wrapper.is_enabled()),
                        "bounds": [int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)],
                    })
                except Exception:
                    continue
            self._elements = cache
            return {
                "ok": True,
                "active_window": observed_title,
                "foreground_window": foreground_title,
                "background_observation": observed_title != foreground_title,
                "windows": windows,
                "elements": elements,
            }
        except Exception as exc:
            self._elements = {}
            return {"ok": False, "error": f"无法读取 Windows UI：{exc}", "windows": [], "elements": []}

    def element(self, element_id: str) -> Any:
        wrapper = self._elements.get(element_id)
        if wrapper is None:
            raise ValueError(f"控件 {element_id} 已失效，请重新观察界面。")
        return wrapper

    def find_window_handle(self, title: str) -> int | None:
        """Find a visible window handle by title substring using UIA backend."""
        desktop = self._desktop()
        for wrapper in desktop.windows():
            try:
                if title.casefold() in wrapper.window_text().casefold() and wrapper.is_visible():
                    return wrapper.element_info.handle
            except Exception:
                continue
        return None

    def _desktop(self) -> Any:
        if self.desktop_factory is not None:
            return self.desktop_factory(backend="uia")
        from pywinauto import Desktop

        return Desktop(backend="uia")


class ComputerToolbox:
    """Small universal action vocabulary; the model composes these at runtime."""

    SPECS = (
        ToolSpec("observe", "读取当前或指定后台窗口的 UI 控件", "low", {"title": "可选：要在后台观察的窗口标题"}),
        ToolSpec("focus_window", "按标题切换到一个窗口", "low", {"title": "窗口标题中的文字"}),
        ToolSpec("open", "打开应用、文件、文件夹或网址", "low", {"target": "名称、路径或网址"}),
        ToolSpec("click_element", "点击本次观察结果中的 UI 控件", "low", {"element_id": "例如 e012"}),
        ToolSpec("type_text", "优先直接向指定输入控件写入文字；未提供控件时才使用前台键盘", "medium", {"text": "要输入的文字", "replace": "是否替换原内容", "element_id": "可选：输入控件编号，后台模式应优先提供"}),
        ToolSpec("press_keys", "发送快捷键或按键", "medium", {"keys": "例如 ctrl+l、enter、alt+f4"}),
        ToolSpec("click_at", "没有可访问控件时按屏幕坐标点击", "medium", {"x": "横坐标", "y": "纵坐标"}),
        ToolSpec("list_files", "查看文件夹内容，可按通配符筛选", "low", {"path": "文件夹路径", "pattern": "例如 *.pdf"}),
        ToolSpec("read_text", "读取本地文本文件的一部分", "low", {"path": "文件路径"}),
        ToolSpec("run_powershell", "运行 PowerShell 完成尚无专用工具的本地任务", "high", {"command": "完整命令"}),
        ToolSpec("wait", "等待应用加载", "low", {"seconds": "1 到 10 秒"}),
        ToolSpec("finish", "确认全部目标已有证据后结束", "low", {"message": "给用户的完整结果答复，包含实际成果、位置或状态，不能只写完成"}),
        ToolSpec("ask_user", "缺少必要信息或权限时向用户提问", "low", {"message": "需要用户回答的问题"}),
    )
    DANGEROUS_WORDS = re.compile(
        r"删除|清空|覆盖|发送|提交|付款|支付|购买|卸载|格式化|"
        r"delete|remove(?:-item)?|\brm\b|\bdel\b|rmdir|clear-content|"
        r"send|submit|pay|purchase|uninstall|"
        r"format-volume|diskpart|shutdown|stop-computer|restart-computer|"
        r"reg\s+delete|reg\s+add|invoke-webrequest|\bcurl\b|upload|"
        r"cmdkey|get-storedcredential|"
        r"-enc(?:odedcommand)?\b|invoke-expression\b|\biex\b|"
        r"start-process.*-windowstyle\s+hidden|add-type|"
        r"system\.net\.|system\.management\.|system\.diagnostics\.process",
        re.I,
    )
    POWERSHELL_ALWAYS_BLOCKED = re.compile(
        r"-enc(?:odedcommand)?\b|invoke-expression\b|\biex\b|add-type|"
        r"start-process.*-windowstyle\s+hidden|cmdkey|get-storedcredential|"
        r"system\.net\.|system\.management\.|system\.diagnostics\.process|"
        r"\bpowershell(?:\.exe)?\b|\bcmd(?:\.exe)?\b|\bpython(?:\.exe)?\b",
        re.I,
    )
    WINDOWS_PATH = re.compile(r"(?:[A-Za-z]:\\|\\\\)[^\r\n\"']+")

    def __init__(self, observer: WindowsObserver | None = None, resolver: AppResolver | None = None) -> None:
        self.observer = observer or WindowsObserver()
        self.resolver = resolver or AppResolver()

    @classmethod
    def schema(cls) -> list[dict[str, Any]]:
        return [asdict(spec) for spec in cls.SPECS]

    def risk_for(self, action: str, arguments: dict[str, Any], observation: dict[str, Any] | None = None) -> str:
        spec = next((item for item in self.SPECS if item.name == action), None)
        if spec is None:
            return "blocked"
        text = " ".join(str(value) for value in arguments.values())
        if self.DANGEROUS_WORDS.search(text):
            return "high"
        if action == "press_keys" and str(arguments.get("keys", "")).strip().casefold() in {"alt+f4", "ctrl+w", "ctrl+shift+w", "shift+delete"}:
            return "high"
        if action == "click_element" and observation:
            element_id = str(arguments.get("element_id", ""))
            match = next((item for item in observation.get("elements", []) if item.get("id") == element_id), None)
            if match and self.DANGEROUS_WORDS.search(str(match.get("name", ""))):
                return "high"
        return spec.risk

    def goal_authorizes(self, goal: str, action: str, arguments: dict[str, Any], observation: dict[str, Any] | None = None) -> bool:
        """Treat the original goal as authorization only for matching sensitive effects."""
        action_text = " ".join(str(value) for value in arguments.values())
        if action == "run_powershell" and not self._powershell_scope_is_explicit(goal, str(arguments.get("command", ""))):
            return False
        if action == "click_element" and observation:
            element_id = str(arguments.get("element_id", ""))
            match = next((item for item in observation.get("elements", []) if item.get("id") == element_id), None)
            if match:
                action_text += " " + str(match.get("name", ""))
        categories = (
            (r"删除|清空|移除|delete|remove", r"删除|清空|移除|delete|remove"),
            (r"覆盖|替换|overwrite|replace", r"覆盖|替换|overwrite|replace"),
            (r"发送|提交|send|submit", r"发送|提交|send|submit"),
            (r"付款|支付|购买|充值|pay|purchase|buy", r"付款|支付|购买|充值|买|pay|purchase|buy"),
            (r"卸载|格式化|uninstall|format", r"卸载|格式化|uninstall|format"),
            (r"invoke-webrequest|\bcurl\b|upload", r"下载|上传|请求|访问|download|upload|fetch"),
            (r"alt\+f4|ctrl\+(?:shift\+)?w", r"关闭|退出|close|quit|exit"),
        )
        return any(re.search(effect, action_text, re.I) and re.search(intent, goal, re.I) for effect, intent in categories)

    @classmethod
    def _powershell_scope_is_explicit(cls, goal: str, command: str) -> bool:
        """Reject compound or opaque scripts and require every absolute target path in the goal."""
        if not command.strip() or cls.POWERSHELL_ALWAYS_BLOCKED.search(command):
            return False
        if re.search(r"[;|&\r\n`]", command):
            return False
        if re.search(r"\$(?:env:|home\b|profile\b|pwd\b)|\$\(|@\(", command, re.I):
            return False
        paths = [match.group(0).rstrip(" ,)") for match in cls.WINDOWS_PATH.finditer(command)]
        goal_folded = goal.casefold()
        return bool(paths) and all(path.casefold() in goal_folded for path in paths)

    def execute(self, action: str, arguments: dict[str, Any]) -> dict[str, Any]:
        handler = getattr(self, f"_tool_{action}", None)
        if handler is None:
            raise ValueError(f"不允许执行工具：{action}")
        return handler(arguments)

    def _tool_observe(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self.observer.observe(window_title=str(arguments.get("title", "")))

    def _tool_focus_window(self, arguments: dict[str, Any]) -> dict[str, Any]:
        title = self._required(arguments, "title")
        desktop = self.observer._desktop()
        matches = [window for window in desktop.windows() if title.casefold() in window.window_text().casefold()]
        if not matches:
            raise ValueError(f"找不到包含“{title}”的窗口。")
        matches[0].set_focus()
        return {"ok": True, "message": f"已切换到窗口：{matches[0].window_text()}"}

    def _tool_open(self, arguments: dict[str, Any]) -> dict[str, Any]:
        target = self._required(arguments, "target")
        resolved = self.resolver.resolve(target)
        if resolved is None:
            raise ValueError(f"找不到要打开的目标：{target}")
        if resolved["kind"] == "url":
            import webbrowser

            webbrowser.open(resolved["path"])
        elif os.name == "nt":
            os.startfile(resolved["path"])  # type: ignore[attr-defined]
        else:
            raise RuntimeError("当前系统不支持打开本地目标。")
        return {"ok": True, "message": f"已打开：{resolved['name']}"}

    def _tool_click_element(self, arguments: dict[str, Any]) -> dict[str, Any]:
        element_id = self._required(arguments, "element_id")
        wrapper = self.observer.element(element_id)
        try:
            wrapper.invoke()
            return {"ok": True, "message": f"已在后台点击控件 {element_id}", "background": True}
        except Exception:
            for method_name in ("select", "toggle"):
                try:
                    getattr(wrapper, method_name)()
                    return {"ok": True, "message": f"已在后台操作控件 {element_id}", "background": True}
                except Exception:
                    continue
        if bool(arguments.get("_background_only", False)):
            raise RuntimeError(f"控件 {element_id} 不支持静默点击，需要前台坐标操作。")
        wrapper.click_input()
        return {"ok": True, "message": f"已点击控件 {element_id}", "background": False}

    def _tool_type_text(self, arguments: dict[str, Any]) -> dict[str, Any]:
        text = str(arguments.get("text", ""))
        element_id = str(arguments.get("element_id", "")).strip()
        if element_id:
            wrapper = self.observer.element(element_id)
            try:
                wrapper.set_edit_text(text)
                return {"ok": True, "message": f"已在后台向控件 {element_id} 写入 {len(text)} 个字符", "background": True}
            except Exception:
                try:
                    wrapper.iface_value.SetValue(text)
                    return {"ok": True, "message": f"已在后台向控件 {element_id} 写入 {len(text)} 个字符", "background": True}
                except Exception as exc:
                    if bool(arguments.get("_background_only", False)):
                        raise RuntimeError(f"控件 {element_id} 不支持静默写入，需要短暂使用前台键盘。") from exc
                    wrapper.set_focus()
        import pyautogui
        import pyperclip

        if bool(arguments.get("replace", False)):
            pyautogui.hotkey("ctrl", "a")
        pyperclip.copy(text)
        pyautogui.hotkey("ctrl", "v")
        return {"ok": True, "message": f"已输入 {len(text)} 个字符"}

    def _tool_press_keys(self, arguments: dict[str, Any]) -> dict[str, Any]:
        keys = [item.strip().lower() for item in self._required(arguments, "keys").split("+") if item.strip()]
        if not keys or len(keys) > 4:
            raise ValueError("快捷键格式不正确。")
        window_title = str(arguments.get("window_title", "")).strip()
        if bool(arguments.get("_background_only", False)) and window_title:
            return self._send_keys_background(keys, window_title)
        import pyautogui

        pyautogui.hotkey(*keys) if len(keys) > 1 else pyautogui.press(keys[0])
        return {"ok": True, "message": f"已发送按键：{'+'.join(keys)}"}

    def _send_keys_background(self, keys: list[str], window_title: str) -> dict[str, Any]:
        """Send a key combo to a background window via Win32 PostMessage."""
        import ctypes
        import time as _time

        user32 = ctypes.windll.user32
        hwnd = self.observer.find_window_handle(window_title)
        if hwnd is None:
            raise RuntimeError(f'找不到后台窗口"{window_title}"，无法发送后台快捷键。请先确保任务窗口可见。')
        if not user32.IsWindow(hwnd):
            raise RuntimeError(f'后台窗口"{window_title}"已失效，请重新观察后重试。')
        modifiers = {"ctrl", "ctrl_l", "ctrl_r", "shift", "shift_l", "shift_r", "alt", "alt_l", "alt_r", "win", "win_l", "win_r"}
        mod_keys = [k for k in keys if k in modifiers]
        main_keys = [k for k in keys if k not in modifiers]
        if not main_keys:
            raise ValueError("快捷键缺少主要按键。")
        invalid = [k for k in mod_keys + main_keys if k not in VK_CODES]
        if invalid:
            raise ValueError(f"不支持的按键：{', '.join(invalid)}")
        failed: list[str] = []
        for mod in mod_keys:
            if not _post_key_message(hwnd, VK_CODES[mod], True, user32):
                failed.append(f"{mod}↓")
        for key in main_keys:
            if not _post_key_message(hwnd, VK_CODES[key], True, user32):
                failed.append(f"{key}↓")
            _time.sleep(0.02)
            if not _post_key_message(hwnd, VK_CODES[key], False, user32):
                failed.append(f"{key}↑")
        for mod in reversed(mod_keys):
            if not _post_key_message(hwnd, VK_CODES[mod], False, user32):
                failed.append(f"{mod}↑")
        if failed:
            dropped = ", ".join(failed)
            raise RuntimeError(f"后台按键 {dropped} 发送失败（窗口可能拒绝了 PostMessage 或权限不足）。请降级使用前台快捷键。")
        return {"ok": True, "message": f"已在后台向窗口发送按键：{'+'.join(keys)}", "background": True}

    def _tool_click_at(self, arguments: dict[str, Any]) -> dict[str, Any]:
        import pyautogui

        x, y = int(arguments.get("x", -1)), int(arguments.get("y", -1))
        width, height = pyautogui.size()
        if not (0 <= x < width and 0 <= y < height):
            raise ValueError("点击坐标超出屏幕范围。")
        pyautogui.click(x, y)
        return {"ok": True, "message": f"已点击坐标 ({x}, {y})"}

    def _tool_list_files(self, arguments: dict[str, Any]) -> dict[str, Any]:
        path = Path(self._required(arguments, "path")).expanduser()
        if not path.is_dir():
            raise ValueError(f"找不到文件夹：{path}")
        pattern = str(arguments.get("pattern") or "*")
        files = []
        for item in sorted(path.glob(pattern), key=lambda value: value.name.casefold())[:200]:
            files.append({"name": item.name, "path": str(item.resolve()), "type": "folder" if item.is_dir() else "file", "size": item.stat().st_size if item.is_file() else None})
        return {"ok": True, "path": str(path.resolve()), "items": files, "truncated": len(files) == 200}

    def _tool_read_text(self, arguments: dict[str, Any]) -> dict[str, Any]:
        path = Path(self._required(arguments, "path")).expanduser()
        if not path.is_file() or path.stat().st_size > 2_000_000:
            raise ValueError("文件不存在或过大，无法直接读取。")
        return {"ok": True, "path": str(path.resolve()), "content": path.read_text(encoding="utf-8", errors="replace")[:30000]}

    def _tool_run_powershell(self, arguments: dict[str, Any]) -> dict[str, Any]:
        command = self._required(arguments, "command")
        completed = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", command], capture_output=True, text=True, timeout=45, cwd=str(Path.home()))
        return {"ok": completed.returncode == 0, "returncode": completed.returncode, "stdout": completed.stdout[-20000:], "stderr": completed.stderr[-10000:]}

    def _tool_wait(self, arguments: dict[str, Any]) -> dict[str, Any]:
        seconds = max(0.2, min(float(arguments.get("seconds", 1)), 10.0))
        time.sleep(seconds)
        return {"ok": True, "message": f"已等待 {seconds:g} 秒"}

    def _tool_finish(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "message": str(arguments.get("message", "任务完成。"))}

    def _tool_ask_user(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "message": self._required(arguments, "message")}

    @staticmethod
    def _required(arguments: dict[str, Any], name: str) -> str:
        value = str(arguments.get(name, "")).strip()
        if not value:
            raise ValueError(f"缺少参数：{name}")
        return value
