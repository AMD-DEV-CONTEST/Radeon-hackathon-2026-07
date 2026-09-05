from __future__ import annotations

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFormLayout,
    QFrame,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
)

from ...services.dataset_inspection import DatasetInspection


class DatasetSummaryWidget(QFrame):
    def __init__(self, parent: QFrame | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        self._layout = QFormLayout(self)

        self._file_label = QLabel()
        self._path_label = QLabel()
        self._format_label = QLabel()
        self._rows_label = QLabel()
        self._columns_label = QLabel()
        self._preview_label = QLabel()

        self._file_name = QLabel("-")
        self._file_path = QLabel("-")
        self._source_format = QLabel("-")
        self._row_count = QLabel("-")
        self._column_count = QLabel("-")
        self._preview_table = QTableWidget(0, 0)

        self._file_path.setWordWrap(True)
        self._preview_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._preview_table.setSelectionMode(QAbstractItemView.NoSelection)
        self._preview_table.setFocusPolicy(Qt.NoFocus)
        self._preview_table.setAlternatingRowColors(True)
        self._preview_table.verticalHeader().setVisible(False)
        self._preview_table.setMinimumHeight(150)

        self._layout.addRow(self._file_label, self._file_name)
        self._layout.addRow(self._path_label, self._file_path)
        self._layout.addRow(self._format_label, self._source_format)
        self._layout.addRow(self._rows_label, self._row_count)
        self._layout.addRow(self._columns_label, self._column_count)
        self._layout.addRow(self._preview_label, self._preview_table)

        self.retranslate_ui()

    def retranslate_ui(self) -> None:
        self._file_label.setText(self.tr("File"))
        self._path_label.setText(self.tr("Path"))
        self._format_label.setText(self.tr("Format"))
        self._rows_label.setText(self.tr("Rows"))
        self._columns_label.setText(self.tr("Columns"))
        self._preview_label.setText(self.tr("Preview"))

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.LanguageChange:
            self.retranslate_ui()
        super().changeEvent(event)

    def clear(self) -> None:
        self._file_name.setText("-")
        self._file_path.setText("-")
        self._source_format.setText("-")
        self._row_count.setText("-")
        self._column_count.setText("-")
        self._preview_table.clear()
        self._preview_table.setRowCount(0)
        self._preview_table.setColumnCount(0)

    def set_inspection(self, inspection: DatasetInspection) -> None:
        self._file_name.setText(inspection.file_name)
        self._file_path.setText(inspection.source_path)
        self._source_format.setText(inspection.source_format.value)
        self._row_count.setText(str(inspection.row_count))
        self._column_count.setText(str(inspection.column_count))
        self._preview_table.clear()
        self._preview_table.setColumnCount(len(inspection.preview_columns))
        self._preview_table.setHorizontalHeaderLabels(inspection.preview_columns)
        self._preview_table.setRowCount(len(inspection.preview_rows))
        for row_index, row in enumerate(inspection.preview_rows):
            for column_index, value in enumerate(row):
                self._preview_table.setItem(row_index, column_index, QTableWidgetItem(value))
        self._preview_table.resizeColumnsToContents()
