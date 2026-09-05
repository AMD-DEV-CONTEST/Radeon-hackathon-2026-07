from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QApplication, QMessageBox, QProgressDialog, QWidget
from shiboken6 import isValid

from ..services.update_service import UpdateService, UpdateState, UpdateStatus


class _SoftwareUpdateOperation(StrEnum):
    CHECK = "check"
    DOWNLOAD = "download"
    APPLY = "apply"


@dataclass(frozen=True)
class _SoftwareUpdateOperationCompleted:
    operation: _SoftwareUpdateOperation
    status: UpdateStatus


class SoftwareUpdateController(QObject):
    operation_active_changed = Signal(bool)

    _operation_completed = Signal(object)
    _progress_changed = Signal(int)
    _quit_for_update = Signal()

    def __init__(
        self,
        parent_window: QWidget,
        update_service: UpdateService,
    ) -> None:
        super().__init__(parent_window)
        self._parent_window = parent_window
        self._update_service = update_service
        self._progress_dialog: QProgressDialog | None = None
        self._target_version: str | None = None
        self._active_operation: _SoftwareUpdateOperation | None = None
        self._operation_interactive = False
        self._closing = False

        self._operation_completed.connect(self._finish_operation)
        self._progress_changed.connect(self._set_progress)
        self._quit_for_update.connect(self._quit_after_update_handoff)

    @property
    def can_auto_check(self) -> bool:
        return self._update_service.status.state is not UpdateState.UNAVAILABLE

    @property
    def active(self) -> bool:
        return self._active_operation is not None

    @property
    def progress_dialog(self) -> QProgressDialog | None:
        return self._progress_dialog

    def start_background_check(self) -> None:
        self._start_check(interactive=False)

    def request_update(self) -> None:
        if self._closing:
            return
        if self._active_operation is not None:
            if self._active_operation is _SoftwareUpdateOperation.CHECK:
                self._operation_interactive = True
            if self._progress_dialog is not None:
                self._progress_dialog.show()
                self._progress_dialog.raise_()
                self._progress_dialog.activateWindow()
            return

        status = self._update_service.status
        if status.state in (
            UpdateState.UPDATE_AVAILABLE,
            UpdateState.READY,
        ):
            self._handle_status(status, interactive=True)
            return
        self._start_check(interactive=True)

    def retranslate_ui(self) -> None:
        if self._progress_dialog is None:
            return
        self._progress_dialog.setWindowTitle(self.tr("Software Update"))
        self._progress_dialog.setLabelText(
            self.tr("Downloading Xenix {version}...").format(
                version=self._target_version or ""
            )
        )

    def shutdown(self) -> None:
        self._closing = True
        self._close_progress()

    def _start_check(self, *, interactive: bool) -> None:
        self._run_operation(
            _SoftwareUpdateOperation.CHECK,
            self._update_service.check,
            interactive=interactive,
        )

    def _run_operation(
        self,
        operation: _SoftwareUpdateOperation,
        worker: Callable[[], UpdateStatus],
        *,
        interactive: bool,
    ) -> bool:
        if self._closing or self._active_operation is not None:
            return False
        service = self._update_service
        self._active_operation = operation
        self._operation_interactive = interactive
        self.operation_active_changed.emit(True)

        def run() -> None:
            try:
                status = worker()
            except Exception as exc:
                current = service.status
                status = UpdateStatus(
                    UpdateState.FAILED,
                    current.installed_version,
                    current.target_version,
                    message=str(exc),
                )
            if isValid(self):
                self._operation_completed.emit(
                    _SoftwareUpdateOperationCompleted(operation, status)
                )

        threading.Thread(
            target=run,
            name=f"xenix-update-{operation.value}",
            daemon=True,
        ).start()
        return True

    def _finish_operation(
        self,
        result: _SoftwareUpdateOperationCompleted,
    ) -> None:
        if self._closing or result.operation is not self._active_operation:
            return
        interactive = self._operation_interactive
        self._active_operation = None
        self._operation_interactive = False
        self.operation_active_changed.emit(False)
        if result.operation is _SoftwareUpdateOperation.DOWNLOAD:
            if self._progress_dialog is not None:
                self._progress_dialog.setValue(100)
            self._close_progress()
        self._handle_status(result.status, interactive=interactive)

    def _handle_status(
        self,
        status: UpdateStatus,
        *,
        interactive: bool,
    ) -> None:
        if self._closing:
            return
        if status.state is UpdateState.UNAVAILABLE:
            if interactive:
                QMessageBox.information(
                    self._parent_window,
                    self.tr("Updates"),
                    self.tr("Updates are unavailable in this build."),
                )
        elif status.state is UpdateState.IDLE:
            if interactive:
                QMessageBox.information(
                    self._parent_window,
                    self.tr("Updates"),
                    self.tr("Xenix is up to date."),
                )
        elif status.state is UpdateState.FAILED:
            if interactive:
                QMessageBox.warning(
                    self._parent_window,
                    self.tr("Updates"),
                    status.message,
                )
        elif status.state is UpdateState.UPDATE_AVAILABLE and interactive:
            answer = QMessageBox.question(
                self._parent_window,
                self.tr("Update available"),
                self.tr(
                    "Xenix {version} is available. Download it now?"
                ).format(version=status.target_version),
            )
            if answer == QMessageBox.Yes:
                self._show_progress(status.target_version or "")
                self._run_operation(
                    _SoftwareUpdateOperation.DOWNLOAD,
                    lambda: self._update_service.download(
                        self._progress_changed.emit
                    ),
                    interactive=True,
                )
        elif status.state is UpdateState.READY and interactive:
            answer = QMessageBox.question(
                self._parent_window,
                self.tr("Update ready"),
                self.tr(
                    "Restart Xenix now to apply version {version}?"
                ).format(version=status.target_version),
            )
            if answer == QMessageBox.Yes:
                self._run_operation(
                    _SoftwareUpdateOperation.APPLY,
                    self._apply_update,
                    interactive=True,
                )

    def _apply_update(self) -> UpdateStatus:
        self._update_service.apply(self._quit_for_update.emit)
        return self._update_service.status

    def _show_progress(self, target_version: str) -> None:
        self._close_progress()
        self._target_version = target_version
        dialog = QProgressDialog("", "", 0, 100, self._parent_window)
        dialog.setObjectName("softwareUpdateProgressDialog")
        dialog.setWindowModality(Qt.NonModal)
        dialog.setMinimumDuration(0)
        dialog.setCancelButton(None)
        dialog.setAutoClose(False)
        dialog.setAutoReset(False)
        dialog.setValue(0)
        self._progress_dialog = dialog
        self.retranslate_ui()
        dialog.show()

    def _set_progress(self, value: int) -> None:
        if self._progress_dialog is not None:
            self._progress_dialog.setValue(max(0, min(100, value)))

    def _close_progress(self) -> None:
        if self._progress_dialog is None:
            return
        dialog = self._progress_dialog
        self._progress_dialog = None
        self._target_version = None
        dialog.close()
        dialog.deleteLater()

    def _quit_after_update_handoff(self) -> None:
        self.shutdown()
        app = QApplication.instance()
        if app is not None:
            app.quit()
