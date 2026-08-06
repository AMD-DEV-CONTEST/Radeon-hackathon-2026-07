from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QMessageBox,
    QVBoxLayout,
)

from ..services.knowledge_index_service import (
    KnowledgeIndexKind,
    KnowledgeIndexService,
)


class KnowledgeIndexRebuildDialog(QDialog):
    submitted = Signal(str)

    def __init__(
        self,
        index_service: KnowledgeIndexService,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowModality(Qt.WindowModal)
        self._service = index_service
        self._summary = QLabel(self)
        self._summary.setWordWrap(True)
        self._keyword_checkbox = QCheckBox(self)
        self._text_vector_checkbox = QCheckBox(self)
        self._buttons = QDialogButtonBox(parent=self)
        self._rebuild_button = self._buttons.addButton(
            "",
            QDialogButtonBox.AcceptRole,
        )
        self._cancel_button = self._buttons.addButton(
            "",
            QDialogButtonBox.RejectRole,
        )
        self._buttons.accepted.connect(self._submit)
        self._buttons.rejected.connect(self.reject)
        self._keyword_checkbox.toggled.connect(self._sync_submit_state)
        self._text_vector_checkbox.toggled.connect(self._sync_submit_state)
        layout = QVBoxLayout(self)
        layout.addWidget(self._summary)
        layout.addWidget(self._keyword_checkbox)
        layout.addWidget(self._text_vector_checkbox)
        layout.addWidget(self._buttons)
        self.resize(520, 240)
        self.retranslate_ui()

    def refresh(self) -> None:
        try:
            status = self._service.status()
        except Exception:
            self._summary.setText(self.tr("Knowledge index status is unavailable."))
            self._keyword_checkbox.setEnabled(False)
            self._text_vector_checkbox.setEnabled(False)
            self._sync_submit_state()
            return
        self._summary.setText(
            self.tr(
                "%1 searchable unit(s). A text vector rebuild is estimated to use "
                "%2 provider request(s)."
            )
            .replace("%1", str(status.unit_count))
            .replace("%2", str(status.estimated_vector_requests))
        )
        self._keyword_checkbox.setEnabled(status.unit_count > 0)
        self._text_vector_checkbox.setEnabled(
            status.vector_configured and status.unit_count > 0
        )
        self._keyword_checkbox.setChecked(status.unit_count > 0)
        self._text_vector_checkbox.setChecked(
            status.vector_configured and status.unit_count > 0
        )
        self._sync_submit_state()

    def _submit(self) -> None:
        selected: list[KnowledgeIndexKind] = []
        if self._keyword_checkbox.isChecked():
            selected.append(KnowledgeIndexKind.KEYWORD)
        if self._text_vector_checkbox.isChecked():
            selected.append(KnowledgeIndexKind.TEXT_VECTOR)
        if not selected:
            return
        try:
            task_id = self._service.enqueue_rebuild(selected, trigger="manual")
        except Exception:
            QMessageBox.warning(
                self,
                self.tr("Knowledge Indexes"),
                self.tr("The selected index rebuild could not be queued."),
            )
            return
        self.submitted.emit(task_id)
        self.accept()

    def _sync_submit_state(self) -> None:
        self._rebuild_button.setEnabled(
            self._keyword_checkbox.isChecked()
            or self._text_vector_checkbox.isChecked()
        )

    def retranslate_ui(self) -> None:
        self.setWindowTitle(self.tr("Rebuild Knowledge Indexes"))
        self._keyword_checkbox.setText(self.tr("Keyword index"))
        self._text_vector_checkbox.setText(self.tr("Text semantic vector index"))
        self._rebuild_button.setText(self.tr("Rebuild"))
        self._cancel_button.setText(self.tr("Cancel"))

    def showEvent(self, event) -> None:
        self.refresh()
        super().showEvent(event)

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.LanguageChange:
            self.retranslate_ui()
            self.refresh()


__all__ = ["KnowledgeIndexRebuildDialog"]
