from __future__ import annotations

from PySide6.QtGui import QColor, QIcon

import qtawesome as qta

DEFAULT_ICON_COLOR = "#4b5563"
DEFAULT_CHEVRON_COLOR = "#374151"

_TOOL_ICON_NAMES: dict[str, str] = {
    "table": "ph.table",
    "text": "ph.text-aa",
    "merge": "ph.git-merge",
    "analysis": "ph.chart-bar",
    "sparkles": "ph.sparkle",
    "table-search": "ph.magnifying-glass",
    "table-transform": "ph.magic-wand",
    "columns": "ph.columns",
    "list-tree": "ph.tree-structure",
    "model": "ph.brain",
    "sliders": "ph.sliders-horizontal",
    "prediction": "ph.trend-up",
    "connection": "ph.link",
    "tool": "ph.wrench",
}


def icon(name: str, *, color: QColor | str = DEFAULT_ICON_COLOR) -> QIcon:
    return qta.icon(name, color=_color_value(color))


def tool_icon(icon_key: str | None, *, color: QColor | str = DEFAULT_ICON_COLOR) -> QIcon:
    return icon(_TOOL_ICON_NAMES.get(icon_key or "tool", _TOOL_ICON_NAMES["tool"]), color=color)


def chevron_icon(*, expanded: bool, color: QColor | str = DEFAULT_CHEVRON_COLOR) -> QIcon:
    name = "ph.caret-down" if expanded else "ph.caret-right"
    return icon(name, color=color)


def attach_file_icon(*, color: QColor | str = DEFAULT_ICON_COLOR) -> QIcon:
    return icon("ph.paperclip", color=color)


def plus_icon(*, color: QColor | str = DEFAULT_ICON_COLOR) -> QIcon:
    return icon("ph.plus", color=color)


def spinner_icon(*, color: QColor | str = DEFAULT_ICON_COLOR) -> QIcon:
    return icon("ph.spinner", color=color)


def status_error_icon(*, color: QColor | str = "#b91c1c") -> QIcon:
    return icon("ph.warning-circle", color=color)


def scroll_to_bottom_icon(*, color: QColor | str = DEFAULT_ICON_COLOR) -> QIcon:
    return icon("ph.arrow-down", color=color)


def remove_icon(*, color: QColor | str = DEFAULT_ICON_COLOR) -> QIcon:
    return icon("ph.x", color=color)


def _color_value(color: QColor | str) -> str:
    if isinstance(color, QColor):
        return color.name()
    return color
