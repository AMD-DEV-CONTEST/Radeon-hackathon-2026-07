"""Playwright 实现的 Web 录制/执行后端。

负责：
- 启动浏览器并打开目标 URL
- 按语义提示定位元素 (text / placeholder / role / 坐标)
- 执行点击、输入、按键、等待等动作
- 采集屏幕截图 / 页面状态用于录制
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from autoflow.capture.base import CaptureBackend
from autoflow.config import get_settings
from autoflow.models import Recording


class WebBackend(CaptureBackend):
    """基于 Playwright 的 Web 后端。

    注意: 需要安装 playwright 并执行 `playwright install chromium`。
    未安装时提供清晰的错误提示，避免静默失败。
    """

    def __init__(self, url: str = "", headless: bool = False) -> None:
        self.url = url
        self.headless = headless
        self._page = None
        self._browser = None
        self._context = None
        self.settings = get_settings()
        self._shot_index = 0

    def start(self, recording: Recording) -> None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError(
                "未安装 playwright。请执行: pip install 'autoflow[replay]' && "
                "python -m playwright install chromium"
            ) from exc

        pw = sync_playwright().start()
        self._browser = pw.chromium.launch(headless=self.headless)
        self._context = self._browser.new_context(viewport={"width": 1440, "height": 900})
        self._page = self._context.new_page()
        if self.url:
            self._page.goto(self.url, wait_until="domcontentloaded")
        recording.metadata.setdefault("url", self.url)
        recording.metadata.setdefault("viewport", "1440x900")

    def locate(self, hint: dict[str, Any]) -> Any:
        """按提示定位元素。

        优先级: text -> placeholder -> role/label -> CSS selector。
        """
        if self._page is None:
            return None

        page = self._page
        text = hint.get("expected_text")
        semantic = hint.get("semantic_hint", "")
        selector = hint.get("selector")

        # 1. 显式 selector
        if selector:
            loc = page.locator(selector).first
            if loc.count() > 0:
                return loc

        # 2. 期望文字 (按钮/链接)
        if text:
            for loc in [
                page.get_by_role("button", name=text).first,
                page.get_by_role("link", name=text).first,
                page.get_by_text(text, exact=True).first,
            ]:
                try:
                    if loc.count() > 0:
                        return loc
                except Exception:
                    continue

        # 3. 语义提示尝试常见控件
        hint_lower = semantic.lower()
        if any(k in hint_lower for k in ("输入", "框", "input", "文本框")):
            loc = page.locator("input, textarea").first
            if loc.count() > 0:
                return loc
        if "按钮" in hint_lower or "button" in hint_lower or "提交" in hint_lower:
            loc = page.get_by_role("button").first
            if loc.count() > 0:
                return loc
        if "链接" in hint_lower or "link" in hint_lower:
            loc = page.get_by_role("link").first
            if loc.count() > 0:
                return loc

        return None

    def do(self, action: str, element: Any = None, **kwargs: Any) -> Any:
        if self._page is None:
            raise RuntimeError("Web 后端未启动，请先调用 start()")

        if action == "click":
            if element is not None:
                element.click()
            else:
                self._page.mouse.click(**kwargs)
            return None

        if action == "type":
            text = kwargs.get("text", "")
            if element is not None:
                element.click()
                element.fill(text)
            else:
                self._page.keyboard.type(text)
            return None

        if action == "press":
            self._page.keyboard.press(kwargs.get("key", "Enter"))
            return None

        if action == "hotkey":
            self._page.keyboard.press(kwargs.get("combination", ""))
            return None

        if action == "wait":
            self._page.wait_for_timeout(kwargs.get("ms", 1000))
            return None

        raise ValueError(f"不支持的 action: {action}")

    def snapshot(self) -> dict[str, Any]:
        """采集当前截图和页面标题。"""
        if self._page is None:
            return {"screen": None, "title": ""}

        shot_dir = self.settings.recordings_dir / "screenshots"
        shot_dir.mkdir(parents=True, exist_ok=True)
        self._shot_index += 1
        shot_path = shot_dir / f"shot_{self._shot_index:04d}.png"
        try:
            self._page.screenshot(path=str(shot_path))
        except Exception:
            shot_path = None

        return {
            "screen": str(shot_path) if shot_path else None,
            "title": self._page.title(),
            "url": self._page.url,
        }

    def stop(self) -> None:
        if self._browser:
            try:
                self._browser.close()
            except Exception:
                pass
        self._browser = None
        self._context = None
        self._page = None
