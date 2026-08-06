from __future__ import annotations

import logging
import os

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QLayout, QWidget

LOGGER = logging.getLogger("xenix.ui.layout_debug")


def dump_layout_if_enabled(root: QObject, *, reason: str, settle_ticks: int = 3) -> None:
    if os.environ.get("XENIX_LAYOUT_DEBUG", "").lower() not in {"1", "true", "yes"}:
        return

    _schedule_dump(root, reason=reason, remaining_ticks=max(0, settle_ticks))


def _schedule_dump(root: QObject, *, reason: str, remaining_ticks: int) -> None:
    if remaining_ticks == 0:
        dump_layout_tree(root, reason=reason)
        return
    QTimer.singleShot(0, lambda: _schedule_dump(root, reason=reason, remaining_ticks=remaining_ticks - 1))


def dump_layout_tree(root: QObject, *, reason: str) -> None:
    lines = [f"Qt layout dump: {reason}"]
    _append_object(lines, root, depth=0)
    LOGGER.info("\n%s", "\n".join(lines))


def _append_object(lines: list[str], obj: QObject, *, depth: int) -> None:
    indent = "  " * depth
    name = obj.objectName() or "-"
    lines.append(f"{indent}{obj.__class__.__name__} name={name} {_object_details(obj)}".rstrip())
    for child in obj.children():
        if isinstance(child, (QWidget, QLayout)):
            _append_object(lines, child, depth=depth + 1)


def _object_details(obj: QObject) -> str:
    if isinstance(obj, QWidget):
        policy = obj.sizePolicy()
        return (
            f"geom={_rect(obj.geometry())} "
            f"size={_size(obj.size())} "
            f"hint={_size(obj.sizeHint())} "
            f"minHint={_size(obj.minimumSizeHint())} "
            f"min={_size(obj.minimumSize())} "
            f"max={_size(obj.maximumSize())} "
            f"policy={_enum_name(policy.horizontalPolicy())}/{_enum_name(policy.verticalPolicy())} "
            f"visible={obj.isVisible()} hidden={obj.isHidden()}"
        )
    if isinstance(obj, QLayout):
        margins = obj.contentsMargins()
        return (
            f"geom={_rect(obj.geometry())} "
            f"margins=({margins.left()},{margins.top()},{margins.right()},{margins.bottom()}) "
            f"spacing={obj.spacing()}"
        )
    return ""


def _rect(rect) -> str:
    return f"({rect.x()},{rect.y()},{rect.width()},{rect.height()})"


def _size(size) -> str:
    return f"({size.width()},{size.height()})"


def _enum_name(value) -> str:
    return getattr(value, "name", str(value))
