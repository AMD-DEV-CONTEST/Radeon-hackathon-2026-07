from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QSpinBox,
    QWidget,
)


@dataclass
class _FieldBinding:
    name: str
    label: str
    widget: QWidget
    field_type: str
    nullable: bool = False
    array_item_type: str | None = None


class JsonSchemaFormWidget(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        self._layout = QFormLayout(self)
        self._layout.setContentsMargins(12, 12, 12, 12)
        self._layout.setSpacing(10)
        self._bindings: dict[str, _FieldBinding] = {}
        self._schema: dict[str, Any] = {}
        self._empty_label: QLabel | None = None
        self._show_empty_label()

    def set_schema(self, schema: dict[str, Any], initial_values: dict[str, Any] | None = None) -> None:
        self.clear()
        self._schema = schema
        properties = schema.get("properties", {})
        if not properties:
            self._show_empty_label()
            return

        if self._layout.rowCount():
            self._layout.removeRow(0)
        self._empty_label = None
        for name, property_schema in properties.items():
            binding = self._create_binding(name, property_schema)
            self._bindings[name] = binding
            label = QLabel(binding.label)
            if description := property_schema.get("description"):
                label.setToolTip(str(description))
                binding.widget.setToolTip(str(description))
            self._layout.addRow(label, binding.widget)

        values = initial_values or {}
        for name, value in values.items():
            if name in self._bindings:
                self._set_widget_value(self._bindings[name], value)

    def clear(self) -> None:
        while self._layout.rowCount():
            self._layout.removeRow(0)
        self._bindings.clear()
        self._empty_label = None
        self._show_empty_label()

    def values(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        for name, binding in self._bindings.items():
            payload[name] = self._get_widget_value(binding)
        return payload

    def _create_binding(self, name: str, schema: dict[str, Any]) -> _FieldBinding:
        field_schema, nullable = self._unwrap_nullable(schema)
        label = str(field_schema.get("title") or name.replace("_", " ").title())
        if "enum" in field_schema:
            widget = QComboBox()
            for option in field_schema["enum"]:
                widget.addItem(str(option), option)
            default = field_schema.get("default")
            if default is not None:
                index = widget.findData(default)
                if index >= 0:
                    widget.setCurrentIndex(index)
            return _FieldBinding(name=name, label=label, widget=widget, field_type="enum", nullable=nullable)

        field_type = field_schema.get("type")
        if field_type == "boolean":
            widget = QCheckBox()
            widget.setChecked(bool(field_schema.get("default", False)))
            return _FieldBinding(name=name, label=label, widget=widget, field_type="boolean", nullable=nullable)
        if field_type == "integer" and not nullable:
            widget = QSpinBox()
            widget.setRange(int(field_schema.get("minimum", -1_000_000)), int(field_schema.get("maximum", 1_000_000)))
            widget.setValue(int(field_schema.get("default", 0)))
            return _FieldBinding(name=name, label=label, widget=widget, field_type="integer", nullable=False)
        if field_type == "number" and not nullable:
            widget = QDoubleSpinBox()
            widget.setDecimals(6)
            widget.setRange(float(field_schema.get("minimum", -1_000_000.0)), float(field_schema.get("maximum", 1_000_000.0)))
            widget.setValue(float(field_schema.get("default", 0.0)))
            return _FieldBinding(name=name, label=label, widget=widget, field_type="number", nullable=False)
        if field_type == "array":
            widget = QPlainTextEdit()
            widget.setFixedHeight(92)
            default = field_schema.get("default", [])
            if isinstance(default, list):
                widget.setPlainText("\n".join(str(item) for item in default))
            widget.setPlaceholderText(self.tr("One value per line"))
            item_schema, _ = self._unwrap_nullable(field_schema.get("items", {}))
            return _FieldBinding(
                name=name,
                label=label,
                widget=widget,
                field_type="array",
                array_item_type=item_schema.get("type", "string"),
            )

        widget = QLineEdit()
        default = field_schema.get("default")
        if default is not None:
            widget.setText(str(default))
        return _FieldBinding(name=name, label=label, widget=widget, field_type=field_type or "string", nullable=nullable)

    def _get_widget_value(self, binding: _FieldBinding) -> Any:
        widget = binding.widget
        if binding.field_type == "boolean":
            return widget.isChecked()  # type: ignore[union-attr]
        if binding.field_type == "integer" and not binding.nullable:
            return int(widget.value())  # type: ignore[union-attr]
        if binding.field_type == "number" and not binding.nullable:
            return float(widget.value())  # type: ignore[union-attr]
        if binding.field_type == "enum":
            return widget.currentData()  # type: ignore[union-attr]
        if binding.field_type == "array":
            raw = widget.toPlainText().strip()  # type: ignore[union-attr]
            if not raw:
                return []
            normalized_items = [
                part.strip()
                for line in raw.splitlines()
                for part in line.split(",")
                if part.strip()
            ]
            return [
                self._parse_scalar(binding.array_item_type or "string", item)
                for item in normalized_items
            ]

        raw = widget.text().strip()  # type: ignore[union-attr]
        if binding.nullable and raw == "":
            return None
        return self._parse_scalar(binding.field_type, raw)

    def _set_widget_value(self, binding: _FieldBinding, value: Any) -> None:
        widget = binding.widget
        if binding.field_type == "boolean":
            widget.setChecked(bool(value))  # type: ignore[union-attr]
            return
        if binding.field_type == "integer" and not binding.nullable:
            widget.setValue(int(value))  # type: ignore[union-attr]
            return
        if binding.field_type == "number" and not binding.nullable:
            widget.setValue(float(value))  # type: ignore[union-attr]
            return
        if binding.field_type == "enum":
            index = widget.findData(value)  # type: ignore[union-attr]
            if index >= 0:
                widget.setCurrentIndex(index)  # type: ignore[union-attr]
            return
        if binding.field_type == "array":
            widget.setPlainText("\n".join(str(item) for item in value))  # type: ignore[union-attr]
            return
        widget.setText("" if value is None else str(value))  # type: ignore[union-attr]

    def _unwrap_nullable(self, schema: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        any_of = schema.get("anyOf")
        if not isinstance(any_of, list):
            return schema, False
        non_null = [entry for entry in any_of if entry.get("type") != "null"]
        if len(non_null) == 1:
            merged = dict(non_null[0])
            if "default" in schema:
                merged.setdefault("default", schema["default"])
            if "title" in schema:
                merged.setdefault("title", schema["title"])
            if "description" in schema:
                merged.setdefault("description", schema["description"])
            return merged, True
        return schema, False

    def _parse_scalar(self, field_type: str, raw: str) -> Any:
        if field_type == "integer":
            return int(raw)
        if field_type == "number":
            return float(raw)
        if field_type == "boolean":
            return raw.lower() in {"1", "true", "yes", "on"}
        return raw

    def _show_empty_label(self) -> None:
        if self._empty_label is None:
            self._empty_label = QLabel(self.tr("No parameters to configure."))
            self._empty_label.setAlignment(Qt.AlignCenter)
        self._layout.addRow(self._empty_label)

    def retranslate_ui(self) -> None:
        if self._empty_label is not None:
            self._empty_label.setText(self.tr("No parameters to configure."))
        for binding in self._bindings.values():
            if binding.field_type == "array":
                binding.widget.setPlaceholderText(self.tr("One value per line"))  # type: ignore[union-attr]

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.LanguageChange:
            self.retranslate_ui()
        super().changeEvent(event)
