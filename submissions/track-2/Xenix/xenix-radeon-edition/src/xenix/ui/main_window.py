from __future__ import annotations

import logging
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from PySide6.QtCore import QEvent, QPoint, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid

from ..config import AppPaths
from ..i18n import TranslationManager
from ..services.agent import (
    AgentHarnessService,
    AgentHarnessStreamEvent,
    AttachmentImportStatus,
    SourceAttachmentInput,
    SubmitUserTurnInput,
)
from ..services.artifact_service import ArtifactService
from ..services.dataset_service import DatasetService
from ..services.embedding_service import EmbeddingSettingsService
from ..services.link_router import LinkRouter
from ..services.llm import ConversationSnapshot, LLMService, LLMSettingsService
from ..services.ml.worker_settings import MLWorkerSettingsService
from .chatbot import ComposerAttachmentStatus, ThreadDetailView
from .icons import plus_icon
from .layout_debug import dump_layout_if_enabled
from .native_widgets import emphasize_label
from .settings_dialog import SettingsDialog, SettingsDialogContribution, SettingsTab
from .software_update import SoftwareUpdateController
from .tool_call_detail_view import ToolCallDetailView

LOGGER = logging.getLogger(__name__)

if TYPE_CHECKING:
    from ..services.knowledge_derivation_service import KnowledgeDerivationService
    from ..services.knowledge_document_lifecycle_service import (
        KnowledgeDocumentLifecycleService,
    )
    from ..services.knowledge_import_service import KnowledgeImportService
    from ..services.knowledge_index_service import KnowledgeIndexService
    from ..services.knowledge_service import KnowledgeService
    from ..services.knowledge_task_query import KnowledgeTaskQueryService
    from ..services.knowledge_workspace_service import KnowledgeWorkspaceService
    from ..services.ml_service import MLService
    from ..services.paddle_ocr_service import PaddleOcrDeploymentService
    from ..services.ocr.settings import OcrSettingsService
    from ..services.update_service import UpdateService


@dataclass(frozen=True)
class _ServiceLinkActivationSucceeded:
    activation_id: str
    uri: str


@dataclass(frozen=True)
class _ServiceLinkActivationFailed:
    activation_id: str
    uri: str
    message: str


@dataclass
class _ComposerAttachmentRecord:
    path: str
    attachment: SourceAttachmentInput


@dataclass
class _PendingComposerSubmission:
    client_submission_id: str
    text: str
    file_paths: list[str]
    append_acknowledged: bool = False


class MainWindow(QMainWindow):
    closing = Signal()
    _harness_failed = Signal(object)
    _harness_stream_event = Signal(object)
    _thread_title_generated = Signal(str, str)
    _thread_title_generation_failed = Signal(str, str)
    _service_link_activation_succeeded = Signal(object)
    _service_link_activation_failed = Signal(object)

    def __init__(
        self,
        paths: AppPaths,
        log_path: Path,
        db_path: Path,
        translation_manager: TranslationManager,
        agent_harness_service: AgentHarnessService,
        llm_service: LLMService,
        llm_settings_service: LLMSettingsService,
        embedding_settings_service: EmbeddingSettingsService,
        ocr_settings_service: OcrSettingsService,
        ml_worker_settings_service: MLWorkerSettingsService,
        artifact_service: ArtifactService,
        link_router: LinkRouter,
        dataset_service: DatasetService,
        ml_service: MLService,
        update_service: UpdateService | None = None,
        knowledge_import_service: KnowledgeImportService | None = None,
        knowledge_derivation_service: KnowledgeDerivationService | None = None,
        knowledge_service: KnowledgeService | None = None,
        knowledge_index_service: KnowledgeIndexService | None = None,
        paddle_ocr_deployment: PaddleOcrDeploymentService | None = None,
        knowledge_task_query_service: KnowledgeTaskQueryService | None = None,
        knowledge_workspace_service: KnowledgeWorkspaceService | None = None,
        knowledge_document_lifecycle_service: KnowledgeDocumentLifecycleService
        | None = None,
        settings_contributions: Sequence[SettingsDialogContribution] = (),
    ) -> None:
        super().__init__()
        self._paths = paths
        self._log_path = log_path
        self._db_path = db_path
        self._translation_manager = translation_manager
        self._agent_harness_service = agent_harness_service
        self._llm_service = llm_service
        self._llm_settings_service = llm_settings_service
        self._embedding_settings_service = embedding_settings_service
        self._ocr_settings_service = ocr_settings_service
        self._ml_worker_settings_service = ml_worker_settings_service
        self._artifact_service = artifact_service
        self._link_router = link_router
        self._dataset_service = dataset_service
        self._ml_service = ml_service
        self._update_service = update_service
        self._software_update_controller = (
            SoftwareUpdateController(self, update_service)
            if update_service is not None
            else None
        )
        self._knowledge_import_service = knowledge_import_service
        self._knowledge_derivation_service = knowledge_derivation_service
        self._knowledge_service = knowledge_service
        self._knowledge_index_service = knowledge_index_service
        self._paddle_ocr_deployment = paddle_ocr_deployment
        self._knowledge_task_query_service = knowledge_task_query_service
        self._knowledge_workspace_service = knowledge_workspace_service
        self._knowledge_document_lifecycle_service = (
            knowledge_document_lifecycle_service
        )
        self._settings_contributions = tuple(settings_contributions)
        self._agent_thread_id: str | None = None
        self._active_pending_message_id: str | None = None
        self._active_submission_id: str | None = None
        self._composer_attachments: dict[str, _ComposerAttachmentRecord] = {}
        self._pending_composer_submission: _PendingComposerSubmission | None = None
        self._cancelled_pending_message_ids: set[str] = set()
        self._paused_thread_ids: set[str] = set()
        self._settings_dialog: SettingsDialog | None = None
        self._knowledge_workspace = None
        self._tool_call_detail_views: list[ToolCallDetailView] = []
        self._thread_title_progress_dialog: QProgressDialog | None = None
        self._service_link_progress_dialog: QProgressDialog | None = None
        self._active_service_link_activation_ids: set[str] = set()

        self._title_label = QLabel(parent=self)
        self._settings_button = QPushButton(parent=self)
        self._settings_button.clicked.connect(self._open_settings)
        self._knowledge_button = QPushButton(parent=self)
        self._knowledge_button.clicked.connect(self._open_knowledge_workspace)

        self._history_sidebar = QFrame(parent=self)
        self._history_sidebar.setObjectName("historySidebar")
        self._history_sidebar.setFrameShape(QFrame.StyledPanel)
        self._history_label = QLabel(parent=self._history_sidebar)
        self._new_thread_button = QPushButton(parent=self._history_sidebar)
        self._new_thread_button.setObjectName("newThreadButton")
        self._new_thread_button.setFixedSize(28, 28)
        self._new_thread_button.setIcon(plus_icon())
        self._new_thread_button.setIconSize(QSize(14, 14))
        self._new_thread_button.clicked.connect(self._create_agent_thread)
        self._history_list = QListWidget(parent=self._history_sidebar)
        self._history_list.itemClicked.connect(self._open_history_thread)
        self._history_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self._history_list.customContextMenuRequested.connect(self._open_history_item_menu)
        self._refreshing_history = False

        self._thread_detail_view = ThreadDetailView(parent=self)
        self._thread_detail_view.set_artifact_resolver(self._artifact_service.resolve_uri)
        self._thread_detail_view.message_submitted.connect(self._submit_chat_message)
        self._thread_detail_view.files_attached.connect(self._register_source_attachments)
        self._thread_detail_view.attachment_removed.connect(self._discard_composer_attachment)
        self._thread_detail_view.model_selected.connect(self._update_thread_model)
        self._thread_detail_view.service_link_activated.connect(self._open_service_link)
        self._thread_detail_view.source_file_activated.connect(self._open_source_file)
        self._thread_detail_view.tool_action_requested.connect(self._handle_tool_action)
        self._thread_detail_view.stop_requested.connect(self._request_harness_stop)
        self._harness_failed.connect(self._render_harness_error)
        self._harness_stream_event.connect(self._render_harness_stream_event)
        self._thread_title_generated.connect(self._finish_generated_thread_title)
        self._thread_title_generation_failed.connect(self._fail_generated_thread_title)
        self._service_link_activation_succeeded.connect(self._finish_service_link_activation)
        self._service_link_activation_failed.connect(self._fail_service_link_activation)

        self.resize(1080, 760)
        self._setup_ui()
        self.retranslate_ui()
        self._sync_model_picker_options()
        if (
            self._software_update_controller is not None
            and self._software_update_controller.can_auto_check
        ):
            QTimer.singleShot(
                1000,
                self._software_update_controller.start_background_check,
            )

    def _setup_ui(self) -> None:
        root = QWidget(self)
        root.setObjectName("mainWindowRoot")
        layout = QVBoxLayout(root)
        layout.setObjectName("mainWindowRootLayout")
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        header_layout = QHBoxLayout()
        header_layout.setObjectName("mainHeaderLayout")
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(12)
        emphasize_label(self._title_label, point_delta=2)
        self._settings_button.setMinimumWidth(96)
        self._knowledge_button.setMinimumWidth(112)
        header_layout.addWidget(self._title_label)
        header_layout.addStretch(1)
        header_layout.addWidget(self._knowledge_button)
        header_layout.addWidget(self._settings_button)
        layout.addLayout(header_layout)

        sidebar_layout = QVBoxLayout(self._history_sidebar)
        sidebar_layout.setObjectName("historySidebarLayout")
        sidebar_layout.setContentsMargins(10, 10, 10, 10)
        sidebar_layout.setSpacing(8)
        self._history_sidebar.setFixedWidth(248)
        self._history_label.setObjectName("historySidebarTitle")
        self._history_list.setObjectName("historyList")
        history_header_layout = QHBoxLayout()
        history_header_layout.setObjectName("historyHeaderLayout")
        history_header_layout.setContentsMargins(0, 0, 0, 0)
        history_header_layout.setSpacing(8)
        history_header_layout.addWidget(self._history_label)
        history_header_layout.addStretch(1)
        history_header_layout.addWidget(self._new_thread_button)
        sidebar_layout.addLayout(history_header_layout)
        sidebar_layout.addWidget(self._history_list, 1)

        content_layout = QHBoxLayout()
        content_layout.setObjectName("mainContentLayout")
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(14)
        content_layout.addWidget(self._history_sidebar)
        content_layout.addWidget(self._thread_detail_view, 1)
        layout.addLayout(content_layout, 1)

        self.setCentralWidget(root)
        self._refresh_history_sidebar()
        current_item = self._history_list.currentItem()
        if current_item is not None:
            self._open_history_thread(current_item)
        dump_layout_if_enabled(root, reason="main-window-setup")

    def closeEvent(self, event) -> None:  # type: ignore[override]
        super().closeEvent(event)
        if event.isAccepted():
            if self._software_update_controller is not None:
                self._software_update_controller.shutdown()
            if self._knowledge_workspace is not None:
                self._knowledge_workspace.shutdown()
            if self._settings_dialog is not None:
                self._settings_dialog.shutdown()
            self.closing.emit()

    def retranslate_ui(self) -> None:
        self.setWindowTitle(self.tr("Xenix Native"))
        self._title_label.setText(self.tr("Xenix"))
        self._settings_button.setText(self.tr("Settings"))
        self._knowledge_button.setText(self.tr("Knowledge"))
        self._history_label.setText(self.tr("History"))
        self._new_thread_button.setText("")
        self._new_thread_button.setToolTip(self.tr("New thread"))
        self._thread_detail_view.retranslate_ui()
        if self._settings_dialog is not None:
            self._settings_dialog.retranslate_ui()
        if self._knowledge_workspace is not None:
            self._knowledge_workspace.retranslate_ui()
        self._retranslate_service_link_progress()
        if self._software_update_controller is not None:
            self._software_update_controller.retranslate_ui()
        self._sync_model_picker_options()

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.LanguageChange:
            self.retranslate_ui()
        super().changeEvent(event)

    def _sync_model_picker_options(self) -> None:
        options = [
            (option.fq_model_key, option.label)
            for option in self._llm_service.model_options()
        ]
        selected = None
        if self._agent_thread_id is not None:
            try:
                selected = self._agent_harness_service.get_thread_snapshot(
                    self._agent_thread_id
                ).thread.selected_fq_model_key
            except Exception:
                selected = None
        self._thread_detail_view.set_model_options(
            options,
            selected_fq_model_key=selected or self._llm_service.default_fq_model_key(),
        )

    def _sync_thread_model_picker(self, snapshot: ConversationSnapshot) -> None:
        selected = snapshot.thread.selected_fq_model_key or self._llm_service.default_fq_model_key()
        self._thread_detail_view.set_selected_fq_model_key(selected)

    def _update_thread_model(self, fq_model_key: str) -> None:
        if self._agent_thread_id is None:
            return
        try:
            snapshot = self._agent_harness_service.set_thread_model(self._agent_thread_id, fq_model_key)
        except Exception as exc:
            self._thread_detail_view.show_error(str(exc))
            return
        self._sync_thread_model_picker(snapshot)

    def _open_settings(
        self,
        _checked: bool = False,
        *,
        tab: SettingsTab = SettingsTab.AI,
    ) -> None:
        if self._settings_dialog is None:
            self._settings_dialog = SettingsDialog(
                paths=self._paths,
                log_path=self._log_path,
                db_path=self._db_path,
                translation_manager=self._translation_manager,
                llm_service=self._llm_service,
                llm_settings_service=self._llm_settings_service,
                embedding_settings_service=self._embedding_settings_service,
                ocr_settings_service=self._ocr_settings_service,
                ml_worker_settings_service=self._ml_worker_settings_service,
                update_service=self._update_service,
                paddle_ocr_deployment=self._paddle_ocr_deployment,
                knowledge_index_service=self._knowledge_index_service,
                settings_contributions=self._settings_contributions,
                parent=self,
            )
            self._settings_dialog.agent_settings_saved.connect(self._reload_agent_provider)
            if self._software_update_controller is not None:
                self._settings_dialog.software_update_requested.connect(
                    self._software_update_controller.request_update
                )
                self._software_update_controller.operation_active_changed.connect(
                    self._settings_dialog.set_update_operation_active
                )
                self._settings_dialog.set_update_operation_active(
                    self._software_update_controller.active
                )
        self._settings_dialog.show_tab(tab)
        self._settings_dialog.show()
        self._settings_dialog.raise_()
        self._settings_dialog.activateWindow()

    def _open_knowledge_workspace(self) -> None:
        if self._knowledge_import_service is None:
            QMessageBox.warning(
                self,
                self.tr("Knowledge Workspace"),
                self.tr("Knowledge services are not available."),
            )
            return
        if self._knowledge_workspace is None:
            from .knowledge_workspace import KnowledgeWorkspaceDialog

            self._knowledge_workspace = KnowledgeWorkspaceDialog(
                import_service=self._knowledge_import_service,
                derivation_service=self._knowledge_derivation_service,
                knowledge_service=self._knowledge_service,
                knowledge_index_service=self._knowledge_index_service,
                ocr_deployment=self._paddle_ocr_deployment,
                task_query_service=self._knowledge_task_query_service,
                workspace_service=self._knowledge_workspace_service,
                document_lifecycle_service=(
                    self._knowledge_document_lifecycle_service
                ),
                open_knowledge_settings=lambda: self._open_settings(
                    tab=SettingsTab.KNOWLEDGE_BASE
                ),
                parent=self,
            )
        self._knowledge_workspace.show()
        self._knowledge_workspace.raise_()
        self._knowledge_workspace.activateWindow()

    def _submit_chat_message(self, text: str, file_paths: list[str], fq_model_key: str) -> None:
        if self._pending_composer_submission is not None or self._active_pending_message_id is not None:
            return
        source_attachments = self._ready_source_attachments(file_paths)
        if source_attachments is None:
            return

        self._start_harness_submission(
            text=text,
            source_attachments=source_attachments,
            file_paths=file_paths,
            fq_model_key=fq_model_key,
            interface_locale=self._translation_manager.current_locale(),
            client_submission_id=uuid4().hex,
        )

    def _register_source_attachments(self, file_paths: list[str]) -> None:
        for file_path in file_paths:
            self._register_source_attachment(file_path)

    def _register_source_attachment(self, file_path: str) -> None:
        source_path = Path(file_path).expanduser().resolve()
        normalized_path = str(source_path)
        if normalized_path in self._composer_attachments:
            return
        self._thread_detail_view.set_attachment_status(
            normalized_path,
            ComposerAttachmentStatus.PENDING,
        )
        try:
            attachment = self._source_attachment_input(normalized_path)
        except Exception as exc:
            self._thread_detail_view.set_attachment_status(
                normalized_path,
                ComposerAttachmentStatus.FAILED,
                error=str(exc),
            )
            self._thread_detail_view.show_error(str(exc))
            return
        self._composer_attachments[normalized_path] = _ComposerAttachmentRecord(
            path=normalized_path,
            attachment=attachment,
        )
        self._thread_detail_view.set_attachment_status(
            normalized_path,
            ComposerAttachmentStatus.READY,
        )

    def _start_harness_submission(
        self,
        *,
        text: str,
        source_attachments: list[SourceAttachmentInput],
        file_paths: list[str],
        fq_model_key: str,
        interface_locale: str,
        client_submission_id: str,
    ) -> None:
        try:
            submit_input = SubmitUserTurnInput(
                thread_id=self._agent_thread_id,
                text=text,
                source_attachments=source_attachments,
                fq_model_key=fq_model_key or None,
                interface_locale=interface_locale,
                client_submission_id=client_submission_id,
            )
        except Exception as exc:
            self._thread_detail_view.show_error(str(exc))
            return

        self._pending_composer_submission = _PendingComposerSubmission(
            client_submission_id=client_submission_id,
            text=text,
            file_paths=[str(Path(file_path).resolve()) for file_path in file_paths],
        )
        # The client submission id is a live stream generation.  It lets the
        # GUI discard late events from an older submission on the same Thread
        # after a pause/re-entry race without persisting a Run identity.
        self._active_submission_id = client_submission_id
        # A new explicit User Message is the UI's re-entry command.  The
        # Conversation service clears its runtime pause when that append
        # commits; clear the local event gate at the same boundary so the new
        # stream can render its acknowledgement/thinking events immediately.
        if self._agent_thread_id is not None:
            self._paused_thread_ids.discard(self._agent_thread_id)
        self._thread_detail_view.begin_composer_submission(file_paths)

        def run_harness() -> None:
            try:
                for event in self._agent_harness_service.submit_user_turn_stream(submit_input):
                    if not isValid(self):
                        return
                    self._harness_stream_event.emit(event)
            except Exception as exc:
                if isValid(self):
                    self._harness_failed.emit(exc)

        threading.Thread(target=run_harness, name="xenix-agent-harness", daemon=True).start()

    def _source_attachment_input(self, file_path: str) -> SourceAttachmentInput:
        source_path = Path(file_path).expanduser().resolve(strict=True)
        if not source_path.is_file():
            raise ValueError(self.tr("The selected source path is not a file."))
        return SourceAttachmentInput(file_path=str(source_path))

    def _ready_source_attachments(self, file_paths: list[str]) -> list[SourceAttachmentInput] | None:
        attachments: list[SourceAttachmentInput] = []
        for file_path in file_paths:
            record = self._composer_attachments.get(str(Path(file_path).resolve()))
            if record is None:
                return None
            attachments.append(record.attachment)
        return attachments

    def _discard_composer_attachment(self, file_path: str) -> None:
        self._composer_attachments.pop(str(Path(file_path).resolve()), None)

    @staticmethod
    def _open_source_file(file_path: str) -> None:
        """Open an ephemeral Chatbot source target without treating it as an Artifact."""

        try:
            source_path = Path(file_path).expanduser().resolve(strict=True)
        except (OSError, RuntimeError):
            return
        if source_path.is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(source_path)))

    def _render_harness_snapshot(self, snapshot: ConversationSnapshot) -> None:
        self._pending_composer_submission = None
        self._agent_thread_id = snapshot.thread.id
        self._active_pending_message_id = None
        self._active_submission_id = None
        self._paused_thread_ids.discard(snapshot.thread.id)
        self._sync_thread_model_picker(snapshot)
        self._thread_detail_view.hide_thinking_indicator()
        self._thread_detail_view.render_events(self._agent_harness_service.project_chatbot_events(snapshot))
        self._thread_detail_view.set_running(False)
        self._refresh_history_sidebar(selected_thread_id=snapshot.thread.id)

    def _render_harness_stream_event(self, event) -> None:
        if not self._event_belongs_to_current_stream(event):
            return
        if (
            event.thread_id in self._paused_thread_ids
            and not (event.kind == "snapshot" and event.is_final)
        ):
            # A paused Thread may still deliver one stable terminal snapshot,
            # but no stale Thinking/activity/connection event may reactivate
            # the Composer after Stop.
            return
        if event.kind == "attachment_import" and event.attachment_import is not None:
            self._render_attachment_import_progress(event)
            return
        if event.kind == "title" and event.snapshot is not None:
            # A late title update is metadata-only.  It must not replace the
            # live event projection or alter the current sampling state.
            self._refresh_history_sidebar(selected_thread_id=self._agent_thread_id)
            return
        if event.pending_message_id in self._cancelled_pending_message_ids and event.kind != "snapshot":
            return
        if event.kind == "snapshot" and event.snapshot is not None:
            if event.is_final:
                if event.pending_message_id is not None:
                    self._cancelled_pending_message_ids.discard(event.pending_message_id)
                self._render_harness_snapshot(event.snapshot)
                return
            self._acknowledge_composer_submission(event.client_submission_id)
            self._agent_thread_id = event.snapshot.thread.id
            self._paused_thread_ids.discard(event.snapshot.thread.id)
            self._active_pending_message_id = event.pending_message_id
            self._sync_thread_model_picker(event.snapshot)
            self._thread_detail_view.render_events(
                event.chatbot_events
                if event.chatbot_events is not None
                else self._agent_harness_service.project_chatbot_events(event.snapshot)
            )
            self._refresh_history_sidebar(selected_thread_id=event.snapshot.thread.id)
            return
        if event.kind in {"chatbot_event", "thinking", "activity", "connection"} and event.chatbot_event is not None:
            if event.pending_message_id is not None:
                self._active_pending_message_id = event.pending_message_id
                self._pending_composer_submission = None
                self._thread_detail_view.set_running(True)
            self._thread_detail_view.apply_chatbot_event(event.chatbot_event)
            return

    def _render_harness_error(self, failure: object) -> None:
        message = str(failure)
        self._thread_detail_view.hide_thinking_indicator()
        pending = self._pending_composer_submission
        self._pending_composer_submission = None
        if pending is not None and not pending.append_acknowledged:
            # No canonical UserMessage exists yet.  The Composer still owns
            # the captured input, including any per-tag FAILED state.
            self._thread_detail_view.abort_composer_submission()
        else:
            # An append acknowledgement is irreversible from the UI's point
            # of view.  Re-project canonical state; never offer a resend.
            self._restore_stable_message_view()
            self._thread_detail_view.abort_composer_submission()
        self._active_pending_message_id = None
        self._active_submission_id = None
        self._thread_detail_view.show_error(message)
        self._thread_detail_view.set_running(False)

    def _event_belongs_to_current_stream(self, event: AgentHarnessStreamEvent) -> bool:
        """Reject late events from an inactive Thread or old submission.

        Sampling events carry the client submission id as a live-only stream
        generation.  Metadata events (for example automatic title refreshes)
        intentionally have no submission id and are accepted only for the
        currently selected Thread.
        """

        submission_id = getattr(event, "client_submission_id", None)
        if submission_id is not None:
            return self._active_submission_id == submission_id
        event_thread_id = getattr(event, "thread_id", None)
        return event_thread_id is None or event_thread_id == self._agent_thread_id

    def _acknowledge_composer_submission(self, client_submission_id: str | None) -> None:
        pending = self._pending_composer_submission
        if pending is None or client_submission_id != pending.client_submission_id:
            return
        pending.append_acknowledged = True
        for file_path in pending.file_paths:
            self._composer_attachments.pop(file_path, None)
        self._thread_detail_view.acknowledge_composer_submission()

    def _render_attachment_import_progress(self, event: AgentHarnessStreamEvent) -> None:
        progress = event.attachment_import
        if progress is None:
            return
        pending = self._pending_composer_submission
        if pending is None or event.client_submission_id != pending.client_submission_id:
            return
        if progress.source_index < 0 or progress.source_index >= len(pending.file_paths):
            return
        path = pending.file_paths[progress.source_index]
        if progress.status is AttachmentImportStatus.PENDING:
            self._thread_detail_view.set_attachment_status(path, ComposerAttachmentStatus.PENDING)
        elif progress.status is AttachmentImportStatus.FAILED:
            self._thread_detail_view.set_attachment_status(path, ComposerAttachmentStatus.FAILED)

    def _restore_stable_message_view(self) -> None:
        if self._agent_thread_id is None:
            self._thread_detail_view.clear_messages()
            return
        try:
            snapshot = self._agent_harness_service.get_thread_snapshot(self._agent_thread_id)
        except Exception:
            self._thread_detail_view.clear_messages()
            return
        self._thread_detail_view.render_events(self._agent_harness_service.project_chatbot_events(snapshot))

    def _open_service_link(self, uri: str) -> None:
        activation_id = uuid4().hex
        self._active_service_link_activation_ids.add(activation_id)
        self._show_service_link_progress()

        def run_activation() -> None:
            try:
                self._link_router.activate(uri, thread_id=self._agent_thread_id)
            except Exception as exc:
                self._service_link_activation_failed.emit(
                    _ServiceLinkActivationFailed(
                        activation_id=activation_id,
                        uri=uri,
                        message=str(exc),
                    )
                )
                return
            self._service_link_activation_succeeded.emit(
                _ServiceLinkActivationSucceeded(
                    activation_id=activation_id,
                    uri=uri,
                )
            )

        threading.Thread(target=run_activation, name="xenix-service-link-activation", daemon=True).start()

    def _show_service_link_progress(self) -> None:
        if self._service_link_progress_dialog is not None:
            return
        dialog = QProgressDialog(
            self.tr("Opening link..."),
            "",
            0,
            0,
            self,
        )
        dialog.setObjectName("serviceLinkProgressDialog")
        dialog.setWindowModality(Qt.NonModal)
        dialog.setMinimumDuration(0)
        dialog.setCancelButton(None)
        self._service_link_progress_dialog = dialog
        self._retranslate_service_link_progress()
        dialog.show()

    def _retranslate_service_link_progress(self) -> None:
        if self._service_link_progress_dialog is None:
            return
        self._service_link_progress_dialog.setLabelText(self.tr("Opening link..."))
        self._service_link_progress_dialog.setWindowTitle(self.tr("Open Link"))

    def _close_service_link_progress_if_idle(self) -> None:
        if self._active_service_link_activation_ids or self._service_link_progress_dialog is None:
            return
        dialog = self._service_link_progress_dialog
        self._service_link_progress_dialog = None
        dialog.close()
        dialog.deleteLater()

    def _finish_service_link_activation(self, result: object) -> None:
        if not isinstance(result, _ServiceLinkActivationSucceeded):
            return
        self._active_service_link_activation_ids.discard(result.activation_id)
        self._close_service_link_progress_if_idle()

    def _fail_service_link_activation(self, result: object) -> None:
        if not isinstance(result, _ServiceLinkActivationFailed):
            return
        self._active_service_link_activation_ids.discard(result.activation_id)
        self._close_service_link_progress_if_idle()
        self._thread_detail_view.show_error(result.message)

    def _handle_tool_action(self, action: object) -> None:
        if not isinstance(action, dict):
            return
        action_type = str(action.get("type") or "")
        raw_task_ids = action.get("task_ids")
        if not isinstance(raw_task_ids, list):
            return
        task_ids = [str(task_id) for task_id in raw_task_ids if str(task_id).strip()]
        if not task_ids:
            return
        if action_type == "open_tool_call_detail":
            self._open_tool_call_detail(task_ids)

    def _open_tool_call_detail(self, task_ids: list[str]) -> None:
        view = ToolCallDetailView(
            ml_service=self._ml_service,
            task_ids=task_ids,
            parent=self,
        )
        view.destroyed.connect(lambda _obj=None, view=view: self._forget_tool_call_detail_view(view))
        self._tool_call_detail_views.append(view)
        view.show()
        view.raise_()
        view.activateWindow()

    def _forget_tool_call_detail_view(self, view: ToolCallDetailView) -> None:
        if view in self._tool_call_detail_views:
            self._tool_call_detail_views.remove(view)

    def _request_harness_stop(self) -> None:
        if self._pending_composer_submission is not None and self._active_pending_message_id is None:
            self._thread_detail_view.show_error(self.tr("The submitted message is being prepared and cannot be stopped."))
            return
        thread_id = self._agent_thread_id
        if thread_id is None:
            return
        try:
            self._agent_harness_service.pause_thread(thread_id)
        except Exception as exc:
            self._thread_detail_view.show_error(str(exc))
            return
        self._paused_thread_ids.add(thread_id)
        self._thread_detail_view.hide_thinking_indicator()
        self._thread_detail_view.set_running(False)
        self._thread_detail_view.show_error(self.tr("Stopped."))

    def _reload_agent_provider(self) -> None:
        self._sync_model_picker_options()

    def _create_agent_thread(self) -> None:
        self._active_pending_message_id = None
        self._active_submission_id = None
        snapshot = self._agent_harness_service.create_thread(
            interface_locale=self._translation_manager.current_locale(),
        )
        self._agent_thread_id = snapshot.thread.id
        self._sync_thread_model_picker(snapshot)
        self._thread_detail_view.render_events(self._agent_harness_service.project_chatbot_events(snapshot))
        self._refresh_history_sidebar(selected_thread_id=snapshot.thread.id)

    def _refresh_history_sidebar(self, *, selected_thread_id: str | None = None) -> None:
        self._history_list.clear()
        self._refreshing_history = True
        try:
            selected_row = -1
            for index, thread in enumerate(self._agent_harness_service.list_threads()):
                title = thread.title or "Untitled conversation"
                item = QListWidgetItem(title)
                item.setData(Qt.UserRole, thread.id)
                self._history_list.addItem(item)
                if thread.id == selected_thread_id:
                    selected_row = index
            if selected_row >= 0:
                self._history_list.setCurrentRow(selected_row)
            elif selected_thread_id is None and self._agent_thread_id is None and self._history_list.count() > 0:
                self._history_list.setCurrentRow(0)
        finally:
            self._refreshing_history = False

    def _open_history_thread(self, item: QListWidgetItem) -> None:
        if self._refreshing_history:
            return
        thread_id = self._thread_id_from_history_item(item)
        if thread_id is None:
            return
        snapshot = self._agent_harness_service.get_thread_snapshot(thread_id)
        self._agent_thread_id = thread_id
        self._active_submission_id = None
        self._sync_thread_model_picker(snapshot)
        if self._active_pending_message_id is not None:
            self._active_pending_message_id = None
        self._thread_detail_view.set_running(False)
        self._thread_detail_view.render_events(self._agent_harness_service.project_chatbot_events(snapshot))

    def _open_history_item_menu(self, position: QPoint) -> None:
        item = self._history_list.itemAt(position)
        if item is None:
            return

        menu = QMenu(self)
        rename_action = menu.addAction(self.tr("Rename"))
        generate_title_action = menu.addAction(self.tr("Generate title..."))
        copy_thread_id_action = menu.addAction(self.tr("Copy thread ID"))
        delete_action = menu.addAction(self.tr("Delete"))
        selected_action = menu.exec(self._history_list.viewport().mapToGlobal(position))

        if selected_action is rename_action:
            self._rename_history_thread(item)
        elif selected_action is generate_title_action:
            self._generate_history_thread_title(item)
        elif selected_action is copy_thread_id_action:
            self._copy_history_thread_id(item)
        elif selected_action is delete_action:
            self._delete_history_thread(item)

    def _copy_history_thread_id(self, item: QListWidgetItem) -> None:
        thread_id = self._thread_id_from_history_item(item)
        if thread_id is None:
            return
        QApplication.clipboard().setText(thread_id)

    def _rename_history_thread(self, item: QListWidgetItem) -> None:
        thread_id = self._thread_id_from_history_item(item)
        if thread_id is None:
            return

        title, accepted = QInputDialog.getText(
            self,
            self.tr("Rename Thread"),
            self.tr("Thread name"),
            text=item.text(),
        )
        if not accepted:
            return

        snapshot = self._agent_harness_service.rename_thread(thread_id, title.strip() or None)
        self._refresh_history_sidebar(selected_thread_id=snapshot.thread.id)

    def _generate_history_thread_title(self, item: QListWidgetItem) -> None:
        thread_id = self._thread_id_from_history_item(item)
        if thread_id is None:
            return
        if not self._agent_harness_service.has_thread_title_provider():
            QMessageBox.information(
                self,
                self.tr("Generate Thread Title"),
                self.tr("Thread title model is not configured."),
            )
            return

        self._show_thread_title_progress()

        def run_title_generation() -> None:
            try:
                title = self._agent_harness_service.generate_thread_title(thread_id)
            except Exception as exc:
                self._thread_title_generation_failed.emit(thread_id, str(exc))
                return
            self._thread_title_generated.emit(thread_id, title)

        threading.Thread(
            target=run_title_generation,
            name="xenix-thread-title-generation",
            daemon=True,
        ).start()

    def _show_thread_title_progress(self) -> None:
        self._close_thread_title_progress()
        dialog = QProgressDialog(
            self.tr("Generating thread title..."),
            "",
            0,
            0,
            self,
        )
        dialog.setObjectName("threadTitleProgressDialog")
        dialog.setWindowTitle(self.tr("Generate Thread Title"))
        dialog.setWindowModality(Qt.WindowModal)
        dialog.setMinimumDuration(0)
        dialog.setCancelButton(None)
        self._thread_title_progress_dialog = dialog
        dialog.show()

    def _close_thread_title_progress(self) -> None:
        if self._thread_title_progress_dialog is None:
            return
        dialog = self._thread_title_progress_dialog
        self._thread_title_progress_dialog = None
        dialog.close()
        dialog.deleteLater()

    def _finish_generated_thread_title(self, thread_id: str, proposal: str) -> None:
        self._close_thread_title_progress()
        title, accepted = QInputDialog.getText(
            self,
            self.tr("Apply Generated Title"),
            self.tr("Thread name"),
            text=proposal,
        )
        if not accepted:
            return
        try:
            snapshot = self._agent_harness_service.rename_thread(thread_id, title.strip() or None)
        except Exception as exc:
            QMessageBox.warning(
                self,
                self.tr("Generate Thread Title"),
                str(exc),
            )
            return
        self._refresh_history_sidebar(selected_thread_id=snapshot.thread.id)

    def _fail_generated_thread_title(self, _thread_id: str, message: str) -> None:
        self._close_thread_title_progress()
        QMessageBox.warning(
            self,
            self.tr("Generate Thread Title"),
            message,
        )

    def _delete_history_thread(self, item: QListWidgetItem) -> None:
        thread_id = self._thread_id_from_history_item(item)
        if thread_id is None:
            return

        if (
            self._agent_thread_id == thread_id
            and (self._thread_detail_view._running or self._active_pending_message_id is not None)
        ):
            QMessageBox.information(
                self,
                self.tr("Delete Thread"),
                self.tr("Stop the current run before deleting this thread."),
            )
            return

        title = item.text()
        response = QMessageBox.question(
            self,
            self.tr("Delete Thread"),
            self.tr('Delete "{title}"? This action cannot be undone.').format(title=title),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if response != QMessageBox.Yes:
            return

        deleting_current = self._agent_thread_id == thread_id
        self._agent_harness_service.delete_thread(thread_id)
        if deleting_current:
            self._agent_thread_id = None
            self._active_pending_message_id = None
            self._thread_detail_view.clear_messages()

        self._refresh_history_sidebar(selected_thread_id=None if deleting_current else self._agent_thread_id)
        if deleting_current:
            current_item = self._history_list.currentItem()
            if current_item is not None:
                self._open_history_thread(current_item)

    def _thread_id_from_history_item(self, item: QListWidgetItem) -> str | None:
        thread_id = item.data(Qt.UserRole)
        return thread_id if isinstance(thread_id, str) else None
