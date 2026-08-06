from __future__ import annotations

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QLabel


def emphasize_label(label: QLabel, *, point_delta: int = 0) -> None:
    font = QFont(label.font())
    font.setBold(True)
    if point_delta:
        point_size = font.pointSize()
        if point_size > 0:
            font.setPointSize(max(1, point_size + point_delta))
    label.setFont(font)


def mark_status_label(label: QLabel, *, is_error: bool) -> None:
    role = "error" if is_error else "status"
    label.setProperty("xenixStatusRole", role)
    label.setAccessibleDescription(role)
