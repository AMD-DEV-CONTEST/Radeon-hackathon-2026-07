from __future__ import annotations

from PySide6.QtCore import QEvent, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


class ApplyRowEditorWidget(QFrame):
    rows_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        self._columns: list[str] = []
        self._add_button = QPushButton()
        self._remove_button = QPushButton()
        self._table = QTableWidget(0, 0, self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        controls = QHBoxLayout()
        self._add_button.clicked.connect(self._add_row)
        self._remove_button.clicked.connect(self._remove_selected_rows)
        controls.addWidget(self._add_button)
        controls.addWidget(self._remove_button)
        controls.addStretch(1)

        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.itemChanged.connect(lambda _item: self.rows_changed.emit())

        layout.addLayout(controls)
        layout.addWidget(self._table)

        self.retranslate_ui()

    def retranslate_ui(self) -> None:
        self._add_button.setText(self.tr("Add Row"))
        self._remove_button.setText(self.tr("Remove Row"))

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.LanguageChange:
            self.retranslate_ui()
        super().changeEvent(event)

    def set_columns(self, columns: list[str]) -> None:
        if list(columns) == self._columns:
            return
        self._columns = list(columns)
        self._table.setColumnCount(len(self._columns))
        self._table.setHorizontalHeaderLabels(self._columns)
        self._table.setRowCount(0)
        if self._columns:
            self._add_row()

    def rows(self) -> list[dict[str, str | None]]:
        rows: list[dict[str, str | None]] = []
        for row_index in range(self._table.rowCount()):
            payload: dict[str, str | None] = {}
            has_value = False
            for column_index, column_name in enumerate(self._columns):
                item = self._table.item(row_index, column_index)
                value = item.text().strip() if item is not None else ""
                if value:
                    has_value = True
                payload[column_name] = value or None
            if has_value:
                rows.append(payload)
        return rows

    def clear(self) -> None:
        self._columns = []
        self._table.setColumnCount(0)
        self._table.setRowCount(0)
        self.rows_changed.emit()

    def complete_rows(self) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        for row_index in range(self._table.rowCount()):
            values = self._row_values(row_index)
            if not any(values.values()):
                continue
            if not all(values.values()):
                continue
            rows.append(values)
        return rows

    def has_complete_rows(self) -> bool:
        return bool(self.complete_rows())

    def has_partial_rows(self) -> bool:
        for row_index in range(self._table.rowCount()):
            values = self._row_values(row_index)
            populated = [value for value in values.values() if value]
            if populated and len(populated) < len(self._columns):
                return True
        return False

    def _add_row(self) -> None:
        if not self._columns:
            return
        row_index = self._table.rowCount()
        self._table.insertRow(row_index)
        for column_index in range(len(self._columns)):
            self._table.setItem(row_index, column_index, QTableWidgetItem(""))
        self.rows_changed.emit()

    def _remove_selected_rows(self) -> None:
        selected_rows = sorted({index.row() for index in self._table.selectedIndexes()}, reverse=True)
        for row_index in selected_rows:
            self._table.removeRow(row_index)
        if self._columns and self._table.rowCount() == 0:
            self._add_row()
            return
        self.rows_changed.emit()

    def _row_values(self, row_index: int) -> dict[str, str]:
        values: dict[str, str] = {}
        for column_index, column_name in enumerate(self._columns):
            item = self._table.item(row_index, column_index)
            values[column_name] = item.text().strip() if item is not None else ""
        return values
