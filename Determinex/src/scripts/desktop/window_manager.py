"""Window management utilities for desktop agents (via AT-SPI or accessibility APIs over VNC)."""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


def get_window_list(screen_controller: Any) -> list[dict]:
    """
    Returns list of visible windows as [{title, x, y, w, h}].
    Implementation depends on VM OS; uses screenshot + OCR heuristic by default.
    """
    # This is a heuristic stub — real implementation requires
    # AT-SPI (Linux) or Windows Accessibility API via RDP/Pywinauto inside the VM.
    log.debug("[window_manager] get_window_list — returning empty list (stub)")
    return []


def find_window_by_title(screen_controller: Any, title: str) -> dict | None:
    windows = get_window_list(screen_controller)
    title_lower = title.lower()
    for win in windows:
        if title_lower in win.get("title", "").lower():
            return win
    return None


def bring_to_front(screen_controller: Any, window: dict) -> None:
    """Click the window's title bar region to bring it to front."""
    x = window.get("x", 0) + window.get("w", 100) // 2
    y = window.get("y", 0) + 10
    screen_controller.click(x, y)


def close_window(screen_controller: Any, window: dict) -> None:
    """Click the close button (top-right for most OS)."""
    x = window.get("x", 0) + window.get("w", 100) - 15
    y = window.get("y", 0) + 10
    screen_controller.click(x, y)
