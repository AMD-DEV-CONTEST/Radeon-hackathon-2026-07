from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, QTimer, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..services.storage.models import MLTaskStatus
from .widgets.task_log_view import TaskLogView

if TYPE_CHECKING:
    from ..services.ml_service import MLService


class ToolCallDetailView(QDialog):
    def __init__(
        self,
        *,
        ml_service: MLService,
        task_ids: list[str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._ml_service = ml_service
        self._task_ids = list(dict.fromkeys(task_ids))
        self._selected_task_id: str | None = None
        self._selected_artifact_path: str | None = None

        self._title_label = QLabel(self)
        self._status_label = QLabel(self)
        self._task_tree = QTreeWidget(self)
        self._refresh_button = QPushButton(self)
        self._open_button = QPushButton(self)
        self._log_view = TaskLogView(self)
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(1000)
        self._refresh_timer.timeout.connect(self.refresh)

        self.resize(860, 560)
        self._setup_ui()
        self.retranslate_ui()
        self.refresh()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        self._title_label.setObjectName("toolCallDetailTitle")
        self._status_label.setObjectName("toolCallDetailStatus")
        layout.addWidget(self._title_label)
        layout.addWidget(self._status_label)

        self._task_tree.setObjectName("toolCallDetailTaskTree")
        self._task_tree.setColumnCount(5)
        self._task_tree.itemSelectionChanged.connect(self._sync_selection)
        self._task_tree.itemDoubleClicked.connect(self._open_selected_artifact)

        splitter = QSplitter(Qt.Vertical, self)
        splitter.addWidget(self._task_tree)
        splitter.addWidget(self._log_view)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter, 1)

        actions_layout = QHBoxLayout()
        actions_layout.addStretch(1)
        actions_layout.addWidget(self._refresh_button)
        actions_layout.addWidget(self._open_button)
        layout.addLayout(actions_layout)

        self._refresh_button.clicked.connect(self.refresh)
        self._open_button.clicked.connect(self._open_selected_artifact)

    def retranslate_ui(self) -> None:
        self.setWindowTitle(self.tr("Tool Call Details"))
        self._title_label.setText(self.tr("Tool Call Details"))
        self._task_tree.setHeaderLabels(
            [
                self.tr("Item"),
                self.tr("Status"),
                self.tr("Model"),
                self.tr("Started"),
                self.tr("Finished"),
            ]
        )
        self._refresh_button.setText(self.tr("Refresh"))
        self._open_button.setText(self.tr("Open"))
        self._log_view.retranslate_ui()
        self._sync_selection()

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.LanguageChange:
            self.retranslate_ui()
        super().changeEvent(event)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self._refresh_timer.stop()
        super().closeEvent(event)

    def refresh(self) -> None:
        current_task_id = self._selected_task_id
        self._task_tree.clear()
        running_task_ids: list[str] = []
        first_task_item: QTreeWidgetItem | None = None
        selected_item: QTreeWidgetItem | None = None

        for task_id in self._task_ids:
            try:
                details = self._ml_service.get_task_details(task_id)
            except Exception as exc:
                item = QTreeWidgetItem([task_id, self.tr("Error"), "", "", ""])
                item.setData(0, Qt.UserRole, {"task_id": task_id})
                self._task_tree.addTopLevelItem(item)
                self._status_label.setText(str(exc))
                continue

            task = details.task
            if task.status in {MLTaskStatus.PENDING, MLTaskStatus.RUNNING}:
                running_task_ids.append(task.id)
            model_key = self._model_key_from_payload(task.request_payload)
            item = QTreeWidgetItem(
                [
                    f"{task.task_type.value}: {task.id}",
                    task.status.value,
                    model_key or "",
                    task.started_at.isoformat() if task.started_at else "",
                    task.finished_at.isoformat() if task.finished_at else "",
                ]
            )
            item.setData(0, Qt.UserRole, {"task_id": task.id})
            self._task_tree.addTopLevelItem(item)
            if first_task_item is None:
                first_task_item = item
            if task.id == current_task_id:
                selected_item = item
            for artifact in details.artifacts:
                artifact_item = QTreeWidgetItem(
                    [
                        f"{artifact.artifact_kind.value}: {Path(artifact.absolute_path).name}",
                        self.tr("Ready") if artifact.ready_to_open else self.tr("Not ready"),
                        "",
                        "",
                        artifact.created_at.isoformat() if artifact.created_at else "",
                    ]
                )
                artifact_item.setData(
                    0,
                    Qt.UserRole,
                    {"task_id": task.id, "artifact_path": artifact.absolute_path},
                )
                item.addChild(artifact_item)
            item.setExpanded(True)

        if selected_item is None:
            selected_item = first_task_item
        if selected_item is not None:
            self._task_tree.setCurrentItem(selected_item)
        if running_task_ids:
            if not self._refresh_timer.isActive():
                self._refresh_timer.start()
            self._status_label.setText(
                self.tr("{count} task(s) still running.").format(count=str(len(running_task_ids)))
            )
        else:
            self._refresh_timer.stop()
            self._status_label.setText(self.tr("All tracked tasks are terminal."))
        self._sync_selection()

    def _sync_selection(self) -> None:
        item = self._task_tree.currentItem()
        payload = item.data(0, Qt.UserRole) if item is not None else None
        if not isinstance(payload, dict):
            self._selected_task_id = None
            self._selected_artifact_path = None
            self._open_button.setEnabled(False)
            self._log_view.clear()
            return
        self._selected_task_id = str(payload.get("task_id") or "") or None
        self._selected_artifact_path = str(payload.get("artifact_path") or "") or None
        self._open_button.setEnabled(bool(self._selected_artifact_path))
        if self._selected_task_id is None:
            self._log_view.clear()
            return
        try:
            self._log_view.set_logs(self._ml_service.get_task_details(self._selected_task_id).logs)
        except Exception:
            self._log_view.clear()

    def _open_selected_artifact(self, *_args) -> None:
        if not self._selected_artifact_path:
            return
        opened = QDesktopServices.openUrl(QUrl.fromLocalFile(self._selected_artifact_path))
        if not opened:
            QMessageBox.warning(
                self,
                self.tr("Open Failed"),
                self.tr("Could not open artifact: {path}").format(path=self._selected_artifact_path),
            )

    def _model_key_from_payload(self, payload: dict) -> str | None:
        for key in ("manual_training", "hyperparameter_tuning", "evaluate_model", "apply_model"):
            value = payload.get(key)
            if isinstance(value, dict) and isinstance(value.get("model_key"), str):
                return value["model_key"]
        return None
