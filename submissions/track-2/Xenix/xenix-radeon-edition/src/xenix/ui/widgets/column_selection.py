from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ...services.dataset_inspection import DatasetColumnMetadata
from ..native_widgets import emphasize_label


class ColumnSelectionWidget(QFrame):
    selection_changed = Signal()

    def __init__(
        self,
        *,
        single_target_selection: bool = False,
        required_target_count: int = 1,
        parent: QFrame | None = None,
    ) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        self._single_target_selection = single_target_selection
        self._required_target_count = required_target_count
        self._columns: list[DatasetColumnMetadata] = []
        self._feature_checkboxes: dict[str, QCheckBox] = {}
        self._target_checkboxes: dict[str, QCheckBox] = {}
        self._syncing_selection = False

        self._hint_label = QLabel()
        self._feature_title_label = QLabel()
        self._target_title_label = QLabel()
        self._feature_panel = QWidget()
        self._feature_layout = QVBoxLayout(self._feature_panel)
        self._feature_group = QWidget()
        self._target_panel = QWidget()
        self._target_layout = QVBoxLayout(self._target_panel)
        self._target_group = QWidget()

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(12, 12, 12, 12)
        root_layout.setSpacing(10)

        self._hint_label.setWordWrap(True)
        root_layout.addWidget(self._hint_label)

        columns_layout = QHBoxLayout()
        columns_layout.setSpacing(12)
        self._build_checkbox_group(self._feature_group, self._feature_title_label, self._feature_panel)
        self._build_checkbox_group(self._target_group, self._target_title_label, self._target_panel)
        columns_layout.addWidget(self._feature_group, 1)
        columns_layout.addWidget(self._target_group, 1)
        root_layout.addLayout(columns_layout)

        self._feature_layout.setContentsMargins(0, 0, 0, 0)
        self._feature_layout.setSpacing(6)
        self._target_layout.setContentsMargins(0, 0, 0, 0)
        self._target_layout.setSpacing(6)

        self.retranslate_ui()

    def _build_checkbox_group(self, container: QWidget, title_label: QLabel, panel: QWidget) -> None:
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        title_label.setAlignment(Qt.AlignLeft)
        emphasize_label(title_label)
        layout.addWidget(title_label)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(panel)
        layout.addWidget(scroll, 1)

    def retranslate_ui(self) -> None:
        if self._required_target_count == 0:
            self._hint_label.setText(self.tr("Select one or more input columns. No prediction target is required."))
            self._target_title_label.setText(self.tr("Prediction Target"))
            self._target_group.hide()
        elif self._single_target_selection:
            self._hint_label.setText(
                self.tr("Choose one prediction target, then select one or more input columns.")
            )
            self._target_title_label.setText(self.tr("Prediction Target"))
            self._target_group.show()
        else:
            self._hint_label.setText(self.tr("Select target columns and one or more input columns."))
            self._target_title_label.setText(self.tr("Target Columns"))
            self._target_group.show()
        self._feature_title_label.setText(self.tr("Input Columns"))

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.LanguageChange:
            self.retranslate_ui()
        super().changeEvent(event)

    def clear(self) -> None:
        self._columns = []
        self._feature_checkboxes = {}
        self._target_checkboxes = {}
        self._clear_checkbox_layout(self._feature_layout)
        self._clear_checkbox_layout(self._target_layout)
        self.selection_changed.emit()

    def set_columns(
        self,
        columns: list[DatasetColumnMetadata],
        feature_columns: list[str] | None = None,
        target_columns: list[str] | None = None,
    ) -> None:
        self.clear()
        self._columns = list(columns)
        available_names = {column.name for column in self._columns}

        target_names = [name for name in (target_columns or []) if name in available_names]
        if self._single_target_selection and len(target_names) > 1:
            target_names = target_names[:1]
        target_name_set = set(target_names)
        feature_name_set = {
            name
            for name in (feature_columns or [])
            if name in available_names and name not in target_name_set
        }

        for column in self._columns:
            feature_checkbox = QCheckBox(self._column_label(column))
            feature_checkbox.setChecked(column.name in feature_name_set)
            feature_checkbox.toggled.connect(
                lambda checked, column_name=column.name: self._on_feature_toggled(column_name, checked)
            )
            self._feature_layout.addWidget(feature_checkbox)
            self._feature_checkboxes[column.name] = feature_checkbox

            target_checkbox = QCheckBox(self._column_label(column))
            target_checkbox.setChecked(column.name in target_name_set)
            target_checkbox.toggled.connect(
                lambda checked, column_name=column.name: self._on_target_toggled(column_name, checked)
            )
            self._target_layout.addWidget(target_checkbox)
            self._target_checkboxes[column.name] = target_checkbox

        self._feature_layout.addStretch(1)
        self._target_layout.addStretch(1)
        self.selection_changed.emit()

    def selected_feature_columns(self) -> list[str]:
        return [
            column.name
            for column in self._columns
            if self._feature_checkboxes.get(column.name) is not None
            and self._feature_checkboxes[column.name].isChecked()
        ]

    def selected_target_columns(self) -> list[str]:
        if self._required_target_count == 0:
            return []
        return [
            column.name
            for column in self._columns
            if self._target_checkboxes.get(column.name) is not None
            and self._target_checkboxes[column.name].isChecked()
        ]

    def _on_feature_toggled(self, column_name: str, checked: bool) -> None:
        if self._syncing_selection or not checked:
            self.selection_changed.emit()
            return
        target_checkbox = self._target_checkboxes.get(column_name)
        if target_checkbox is None or not target_checkbox.isChecked():
            self.selection_changed.emit()
            return
        self._syncing_selection = True
        target_checkbox.setChecked(False)
        self._syncing_selection = False
        self.selection_changed.emit()

    def _on_target_toggled(self, column_name: str, checked: bool) -> None:
        if self._required_target_count == 0:
            self.selection_changed.emit()
            return
        if self._syncing_selection or not checked:
            self.selection_changed.emit()
            return

        self._syncing_selection = True
        try:
            if self._single_target_selection:
                for other_name, checkbox in self._target_checkboxes.items():
                    if other_name != column_name and checkbox.isChecked():
                        checkbox.setChecked(False)

            feature_checkbox = self._feature_checkboxes.get(column_name)
            if feature_checkbox is not None and feature_checkbox.isChecked():
                feature_checkbox.setChecked(False)
        finally:
            self._syncing_selection = False
        self.selection_changed.emit()

    def _clear_checkbox_layout(self, layout: QVBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _column_label(self, column: DatasetColumnMetadata) -> str:
        return f"{column.name} ({column.kind.value})"
