from __future__ import annotations

import threading

from PySide6.QtCore import QEvent, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWizard,
    QWizardPage,
    QWidget,
)

from ..services.ml.ssh_worker_setup import SshWorkerSetupInput, SshWorkerSetupResult, SshWorkerSetupService
from ..services.ml.worker_settings import MLWorkerSettingsService


class SshWorkerSetupWizard(QWizard):
    worker_saved = Signal()
    _setup_succeeded = Signal(object)
    _setup_failed = Signal(str)

    def __init__(
        self,
        settings_service: MLWorkerSettingsService,
        *,
        setup_service: SshWorkerSetupService | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings_service = settings_service
        self._setup_service = setup_service or SshWorkerSetupService()
        self._completed = False
        self._running = False

        self._connection_page = QWizardPage()
        self._setup_page = _CompletablePage(lambda: self._completed)

        self._name_label = QLabel()
        self._alias_label = QLabel()
        self._host_label = QLabel()
        self._user_label = QLabel()
        self._port_label = QLabel()
        self._identity_label = QLabel()
        self._remote_root_label = QLabel()
        self._python_label = QLabel()
        self._write_config_label = QLabel()
        self._install_deps_label = QLabel()
        self._setup_summary_label = QLabel()

        self._name_input = QLineEdit()
        self._alias_input = QLineEdit()
        self._host_input = QLineEdit()
        self._user_input = QLineEdit()
        self._port_input = QSpinBox()
        self._port_input.setRange(1, 65535)
        self._port_input.setValue(22)
        self._identity_input = QLineEdit()
        self._remote_root_input = QLineEdit("~/.xenix/workers/default")
        self._python_input = QLineEdit("python3")
        self._write_config_checkbox = QCheckBox()
        self._write_config_checkbox.setChecked(True)
        self._install_deps_checkbox = QCheckBox()
        self._install_deps_checkbox.setChecked(True)
        self._run_setup_button = QPushButton()
        self._status_output = QPlainTextEdit()
        self._status_output.setReadOnly(True)
        self._status_output.setMinimumHeight(220)

        self._build_ui()
        self._wire_events()
        self.retranslate_ui()

    def _build_ui(self) -> None:
        self.setWizardStyle(QWizard.ModernStyle)
        self.setOption(QWizard.NoBackButtonOnStartPage, False)
        self.setOption(QWizard.NoBackButtonOnLastPage, False)

        form = QFormLayout(self._connection_page)
        form.setContentsMargins(12, 12, 12, 12)
        form.setSpacing(10)
        form.addRow(self._name_label, self._name_input)
        form.addRow(self._alias_label, self._alias_input)
        form.addRow(self._host_label, self._host_input)
        form.addRow(self._user_label, self._user_input)
        form.addRow(self._port_label, self._port_input)
        form.addRow(self._identity_label, self._identity_input)
        form.addRow(self._remote_root_label, self._remote_root_input)
        form.addRow(self._python_label, self._python_input)
        form.addRow(self._write_config_label, self._write_config_checkbox)
        form.addRow(self._install_deps_label, self._install_deps_checkbox)

        setup_layout = QVBoxLayout(self._setup_page)
        setup_layout.setContentsMargins(12, 12, 12, 12)
        setup_layout.setSpacing(10)
        setup_layout.addWidget(self._setup_summary_label)
        setup_layout.addWidget(self._status_output, 1)
        button_row = QHBoxLayout()
        button_row.addStretch(1)
        button_row.addWidget(self._run_setup_button)
        setup_layout.addLayout(button_row)

        self.addPage(self._connection_page)
        self.addPage(self._setup_page)
        self.resize(680, 560)

    def _wire_events(self) -> None:
        self._run_setup_button.clicked.connect(self._run_setup)
        self._setup_succeeded.connect(self._handle_setup_succeeded)
        self._setup_failed.connect(self._handle_setup_failed)

    def retranslate_ui(self) -> None:
        self.setWindowTitle(self.tr("Set Up SSH Worker"))
        self._connection_page.setTitle(self.tr("SSH worker"))
        self._connection_page.setSubTitle(self.tr("Configure a key-based SSH worker for ML workloads."))
        self._setup_page.setTitle(self.tr("Setup and validation"))
        self._setup_page.setSubTitle(self.tr("Create the remote environment and validate execution prerequisites."))
        self._name_label.setText(self.tr("Worker name"))
        self._alias_label.setText(self.tr("SSH alias"))
        self._host_label.setText(self.tr("Host"))
        self._user_label.setText(self.tr("User"))
        self._port_label.setText(self.tr("Port"))
        self._identity_label.setText(self.tr("Identity file"))
        self._remote_root_label.setText(self.tr("Remote root"))
        self._python_label.setText(self.tr("Python command"))
        self._write_config_label.setText(self.tr("Write SSH config"))
        self._install_deps_label.setText(self.tr("Set up remote environment"))
        self._setup_summary_label.setText(
            self.tr("Xenix will use key or agent-based SSH. Password and passphrase storage is not supported.")
        )
        self._run_setup_button.setText(self.tr("Run setup"))
        if not self._status_output.toPlainText().strip():
            self._status_output.setPlainText(self.tr("Setup has not run yet."))

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.LanguageChange:
            self.retranslate_ui()
        super().changeEvent(event)

    def _run_setup(self) -> None:
        if self._running:
            return
        self._completed = False
        self._setup_page.completeChanged.emit()
        self._running = True
        self._run_setup_button.setEnabled(False)
        self._status_output.setPlainText(self.tr("Running setup..."))
        input_data = SshWorkerSetupInput(
            display_name=self._name_input.text().strip(),
            host=self._host_input.text().strip(),
            user=self._user_input.text().strip(),
            port=self._port_input.value(),
            identity_file_path=self._identity_input.text().strip(),
            ssh_alias=self._alias_input.text().strip(),
            remote_root=self._remote_root_input.text().strip(),
            python_command=self._python_input.text().strip(),
            write_ssh_config=self._write_config_checkbox.isChecked(),
            install_dependencies=self._install_deps_checkbox.isChecked(),
        )

        def worker() -> None:
            try:
                result = self._setup_service.setup(input_data)
            except Exception as exc:
                self._setup_failed.emit(str(exc))
                return
            self._setup_succeeded.emit(result)

        threading.Thread(target=worker, name="xenix-ssh-worker-setup", daemon=True).start()

    def _handle_setup_succeeded(self, result_obj: object) -> None:
        result = result_obj
        if not isinstance(result, SshWorkerSetupResult):
            self._handle_setup_failed(self.tr("Setup returned an invalid result."))
            return
        self._settings_service.add_or_update_worker(result.worker)
        self._completed = True
        self._running = False
        self._run_setup_button.setEnabled(True)
        self._status_output.setPlainText("\n".join(result.details))
        self._setup_page.completeChanged.emit()
        self.worker_saved.emit()

    def _handle_setup_failed(self, message: str) -> None:
        self._completed = False
        self._running = False
        self._run_setup_button.setEnabled(True)
        self._status_output.setPlainText(message)
        self._setup_page.completeChanged.emit()


class _CompletablePage(QWizardPage):
    def __init__(self, is_complete_callback) -> None:
        super().__init__()
        self._is_complete_callback = is_complete_callback

    def isComplete(self) -> bool:
        return bool(self._is_complete_callback())
