from __future__ import annotations

import logging
import os
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlmodel import select

from ..config import AppPaths
from ..exceptions import ValidationError
from .artifact_service import ArtifactService, RegisterArtifactInput
from .knowledge_canonical import CanonicalIdentity
from .knowledge_content_store import (
    CANONICAL_SCHEMA_VERSION,
    CanonicalBundleIdentity,
    KnowledgeContentStore,
)
from .knowledge_import_worker import (
    KnowledgeImportWorkerCancelled,
    KnowledgeImportWorkerCrashed,
    KnowledgeImportWorkerEvent,
    KnowledgeImportWorkerLaunchFailed,
    KnowledgeImportWorkerRequest,
    KnowledgeImportWorkerRunner,
    KnowledgeImportWorkerTimedOut,
    LocalKnowledgeImportWorkerRunner,
)
from .ocr.composition import LocalPaddleOcrAttemptFactory
from .ocr.contracts import OcrAttemptFactory
from .knowledge_import_storage_maintenance import (
    KnowledgeImportStorageMaintenance,
    KnowledgeImportStorageMaintenanceError,
)
from .knowledge_formats import SUPPORTED_KNOWLEDGE_SUFFIXES
from .knowledge_pipeline import (
    MAX_SOURCE_BYTES,
    FileProbe,
    FileProbeResult,
    FormatNormalizer,
    ParserRouter,
    _find_libreoffice,
)
from .knowledge_task_logs import KnowledgeTaskLogEntry, KnowledgeTaskLogStore
from .storage.models import (
    ArtifactKind,
    ArtifactRow,
    KnowledgeCanonicalGenerationRow,
    KnowledgeDocumentRow,
    KnowledgeImportRow,
    generate_id,
    utc_now,
)
from .storage.layout import knowledge_root

_STOP = object()
LOGGER = logging.getLogger(__name__)
_TERMINAL_IMPORT_STATUSES = frozenset(
    {"retrieval_ready", "canonical_ready", "needs_attention", "failed", "cancelled", "reused"}
)
_SAFE_IMPORT_ERRORS = {
    "knowledge_password_required": "A password is required to continue this import.",
    "knowledge_password_invalid": "The document password was not accepted.",
    "knowledge_doc_converter_unavailable": "LibreOffice is required to import this DOC file.",
    "knowledge_doc_conversion_failed": "The DOC file could not be converted.",
    "knowledge_ppt_converter_unavailable": "LibreOffice is required to import this PPT file.",
    "knowledge_ppt_conversion_failed": "The PPT file could not be converted.",
    "knowledge_format_unsupported": "This file type is not supported by the Knowledge Library.",
    "knowledge_format_mismatch": "The file signature does not match its extension.",
    "knowledge_pdf_invalid": "The PDF is structurally invalid.",
    "knowledge_source_size_unsupported": "The file size is outside the supported range.",
    "knowledge_text_encoding_unknown": "The TXT encoding could not be identified safely.",
    "knowledge_text_encoding_invalid": "The TXT content is invalid for its encoding.",
    "knowledge_text_controls_invalid": "The TXT file contains unsupported control characters.",
    "knowledge_text_line_too_long": "The TXT file contains a line that is too long.",
    "knowledge_docx_package_invalid": "The DOCX file is not a valid Office document.",
    "knowledge_docx_entry_limit": "The DOCX package contains too many entries.",
    "knowledge_docx_entries_ambiguous": "The DOCX package contains ambiguous entries.",
    "knowledge_docx_entry_encrypted": "The DOCX package contains an unsupported encrypted entry.",
    "knowledge_docx_entry_unsafe": "The DOCX package contains an unsafe entry.",
    "knowledge_docx_path_unsafe": "The DOCX package contains an unsafe path.",
    "knowledge_docx_size_invalid": "The DOCX package contains invalid size metadata.",
    "knowledge_docx_entry_too_large": "The DOCX package contains an entry that is too large.",
    "knowledge_docx_expansion_limit": "The expanded DOCX package is too large.",
    "knowledge_docx_compression_ratio": "The DOCX package compression ratio is unsafe.",
    "knowledge_pptx_package_invalid": "The PPTX file is not a valid Office document.",
    "knowledge_pptx_entry_limit": "The PPTX package contains too many entries.",
    "knowledge_pptx_entries_ambiguous": "The PPTX package contains ambiguous entries.",
    "knowledge_pptx_entry_encrypted": "The PPTX package contains an unsupported encrypted entry.",
    "knowledge_pptx_entry_unsafe": "The PPTX package contains an unsafe entry.",
    "knowledge_pptx_path_unsafe": "The PPTX package contains an unsafe path.",
    "knowledge_pptx_size_invalid": "The PPTX package contains invalid size metadata.",
    "knowledge_pptx_entry_too_large": "The PPTX package contains an entry that is too large.",
    "knowledge_pptx_expansion_limit": "The expanded PPTX package is too large.",
    "knowledge_pptx_compression_ratio": "The PPTX package compression ratio is unsafe.",
    "knowledge_docling_conversion_failed": "The document could not be parsed into canonical content.",
    "knowledge_canonical_integrity_failed": "Canonical content failed integrity validation.",
    "knowledge_source_integrity_failed": "The app-owned source snapshot failed integrity validation.",
    "knowledge_source_reselection_required": "Select the source file again to retry this import.",
    "knowledge_import_not_retryable": "This import attempt cannot be retried.",
    "knowledge_import_cancelled": "The import was cancelled.",
    "knowledge_import_worker_crashed": "The import worker stopped unexpectedly.",
    "knowledge_import_worker_launch_failed": "The import worker could not be started.",
    "knowledge_import_worker_timed_out": "The import worker exceeded the allowed execution time.",
    "knowledge_import_failed": "The file could not be imported.",
}


@dataclass(frozen=True)
class KnowledgeImportReceipt:
    import_id: str
    status: str
    reused_existing: bool


@dataclass(frozen=True)
class KnowledgeImportResult:
    import_id: str
    document_id: str
    source_artifact_id: str | None
    source_sha256: str
    canonical_path: str | None
    canonical_generation_id: str | None
    canonical_ready: bool
    reused_existing: bool


@dataclass(frozen=True)
class KnowledgeImportView:
    import_id: str
    file_name: str
    source_format: str
    status: str
    phase: str
    attempt_number: int
    document_id: str | None
    canonical_generation_id: str | None
    reused_existing: bool
    error_code: str | None
    error_summary: str | None
    retryable: bool
    cancel_requested: bool


class KnowledgeImportService:
    """Own durable import admission, serialized execution, recovery, and shutdown."""

    def __init__(
        self,
        *,
        paths: AppPaths,
        session_factory: sessionmaker,
        artifact_service: ArtifactService,
        worker_runner: KnowledgeImportWorkerRunner | None = None,
        ocr_attempt_factory: OcrAttemptFactory | None = None,
        canonical_ready_notifier: Callable[[str, str, str | None], object] | None = None,
        corpus_changed_notifier: Callable[[str], object] | None = None,
        start_worker: bool = True,
    ) -> None:
        self._paths = paths
        self._session_factory = session_factory
        self._artifacts = artifact_service
        self._store = KnowledgeContentStore(paths)
        self._task_logs = KnowledgeTaskLogStore(paths)
        self._probe = FileProbe()
        self._worker_runner = worker_runner or LocalKnowledgeImportWorkerRunner()
        self._ocr_attempt_factory = ocr_attempt_factory or LocalPaddleOcrAttemptFactory()
        self._canonical_ready_notifier = canonical_ready_notifier
        self._corpus_changed_notifier = corpus_changed_notifier
        self._queue: queue.Queue[str | object] = queue.Queue()
        self._passwords: dict[str, str] = {}
        self._password_lock = threading.Lock()
        self._source_paths: dict[str, Path] = {}
        self._source_path_lock = threading.Lock()
        self._mutation_lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.cleanup_storage_orphans()
        pending = self._recover_imports()
        if start_worker:
            self._thread = threading.Thread(
                target=self._worker_main,
                name="xenix-knowledge-import",
                daemon=True,
            )
            self._thread.start()
            for import_id in pending:
                self._queue.put(import_id)

    def preflight_import(self, source_path: Path) -> FileProbeResult:
        return self._probe.probe(source_path)

    def enqueue_file(self, source_path: Path, *, password: str | None = None) -> KnowledgeImportReceipt:
        source = source_path.expanduser().resolve()
        if not source.is_file():
            raise ValidationError("Knowledge source must be an existing local file.")
        suffix = source.suffix.casefold()
        if suffix not in SUPPORTED_KNOWLEDGE_SUFFIXES:
            raise ValidationError(
                self._probe.supported_formats_message,
                error_code="knowledge_format_unsupported",
            )
        size = source.stat().st_size
        if size <= 0 or size > MAX_SOURCE_BYTES:
            raise ValidationError(
                "Knowledge source size is outside the supported range.",
                error_code="knowledge_source_size_unsupported",
            )
        import_id = generate_id()
        planned_document_id = generate_id()
        with self._session_factory() as session:
            row = KnowledgeImportRow(
                id=import_id,
                library_id="global",
                original_file_name=source.name,
                source_format="jpeg" if suffix in {".jpg", ".jpeg"} else suffix.lstrip("."),
                source_sha256=None,
                status="queued",
                phase="snapshot",
                attempt_number=1,
                planned_document_id=planned_document_id,
                source_artifact_id=None,
                retryable=False,
            )
            session.add(row)
            session.commit()
        self._remember_source_path(import_id, source)
        self._remember_password(import_id, password)
        self._log_event(import_id, phase="queued", event_code="import_queued")
        self._queue.put(import_id)
        return KnowledgeImportReceipt(import_id, "queued", False)

    def import_file(
        self,
        source_path: Path,
        *,
        password: str | None = None,
        timeout: float = 900.0,
    ) -> KnowledgeImportResult:
        receipt = self.enqueue_file(source_path, password=password)
        return self.wait_for_import(receipt.import_id, timeout=timeout)

    def wait_for_import(
        self,
        import_id: str,
        *,
        timeout: float = 900.0,
    ) -> KnowledgeImportResult:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            result = self._completed_result(import_id)
            if result is not None:
                return result
            time.sleep(0.02)
        raise TimeoutError("Knowledge import did not finish within the local timeout.")

    def retry_import(
        self,
        import_id: str,
        *,
        password: str | None = None,
        source_path: Path | None = None,
    ) -> KnowledgeImportReceipt:
        with self._mutation_lock, self._session_factory() as session:
            previous = session.get(KnowledgeImportRow, import_id)
            if previous is None:
                raise ValidationError("Knowledge import attempt was not found.")
            if previous.status not in {"failed", "needs_attention", "cancelled"} or not previous.retryable:
                raise ValidationError(
                    "Knowledge import attempt is not retryable.",
                    error_code="knowledge_import_not_retryable",
                )
            existing_retry = session.exec(
                select(KnowledgeImportRow)
                .where(KnowledgeImportRow.retry_of == previous.id)
                .order_by(KnowledgeImportRow.created_at.desc())
            ).first()
            if existing_retry is not None:
                return KnowledgeImportReceipt(
                    existing_retry.id,
                    existing_retry.status,
                    existing_retry.reused_existing,
                )

            artifact = (
                session.get(ArtifactRow, previous.source_artifact_id)
                if previous.source_artifact_id
                else None
            )
            reuse_snapshot = False
            if artifact is not None and previous.source_sha256:
                try:
                    self._store.verify_source_snapshot(
                        Path(artifact.absolute_path),
                        expected_sha256=previous.source_sha256,
                    )
                except ValidationError:
                    artifact = None
                else:
                    reuse_snapshot = True
            source_reference: Path | None = None
            if not reuse_snapshot:
                if source_path is None:
                    raise ValidationError(
                        "Select the source file again to retry this import.",
                        error_code="knowledge_source_reselection_required",
                        retryable=True,
                    )
                source_reference = source_path.expanduser().resolve()
                if (
                    not source_reference.is_file()
                    or source_reference.suffix.casefold()
                    not in SUPPORTED_KNOWLEDGE_SUFFIXES
                ):
                    raise ValidationError(
                        "The selected Knowledge source cannot be used for retry.",
                        error_code="knowledge_source_reselection_required",
                        retryable=True,
                    )
            latest_attempt = session.exec(
                select(KnowledgeImportRow.attempt_number)
                .where(KnowledgeImportRow.planned_document_id == previous.planned_document_id)
                .order_by(KnowledgeImportRow.attempt_number.desc())
            ).first()
            row = KnowledgeImportRow(
                library_id=previous.library_id,
                original_file_name=(
                    source_reference.name
                    if source_reference is not None
                    else previous.original_file_name
                ),
                source_format=(
                    (
                        "jpeg"
                        if source_reference is not None
                        and source_reference.suffix.casefold() in {".jpg", ".jpeg"}
                        else source_reference.suffix.casefold().lstrip(".")
                    )
                    if source_reference is not None
                    else previous.source_format
                ),
                source_sha256=previous.source_sha256 if reuse_snapshot else None,
                status="queued",
                phase="snapshot",
                attempt_number=int(latest_attempt or previous.attempt_number) + 1,
                retry_of=previous.id,
                planned_document_id=previous.planned_document_id,
                source_artifact_id=previous.source_artifact_id if reuse_snapshot else None,
                retryable=False,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
        if source_reference is not None:
            self._remember_source_path(row.id, source_reference)
        self._remember_password(row.id, password)
        self._log_event(row.id, phase="queued", event_code="import_retry_queued")
        self._queue.put(row.id)
        return KnowledgeImportReceipt(row.id, row.status, False)

    def cancel_import(self, import_id: str) -> bool:
        with self._session_factory() as session:
            row = session.get(KnowledgeImportRow, import_id)
            if row is None or row.status in _TERMINAL_IMPORT_STATUSES:
                return False
            row.cancel_requested = True
            if row.status == "queued":
                row.status = "cancelled"
                row.phase = "cancelled"
                row.error_code = "knowledge_import_cancelled"
                row.error_summary = _SAFE_IMPORT_ERRORS["knowledge_import_cancelled"]
                row.retryable = True
            row.updated_at = utc_now()
            session.add(row)
            session.commit()
            self._log_event(
                import_id,
                phase="cancelled" if row.status == "cancelled" else row.phase,
                event_code="cancellation_requested",
                level="warning",
            )
            return True

    def list_imports(self) -> list[KnowledgeImportView]:
        with self._session_factory() as session:
            rows = list(
                session.exec(
                    select(KnowledgeImportRow).order_by(KnowledgeImportRow.created_at.desc())
                )
            )
        return [
            KnowledgeImportView(
                import_id=row.id,
                file_name=row.original_file_name,
                source_format=row.source_format,
                status=row.status,
                phase=row.phase,
                attempt_number=row.attempt_number,
                document_id=row.document_id,
                canonical_generation_id=row.canonical_generation_id,
                reused_existing=row.reused_existing,
                error_code=row.error_code,
                error_summary=row.error_summary,
                retryable=row.retryable,
                cancel_requested=row.cancel_requested,
            )
            for row in rows
        ]

    def read_import_logs(self, import_id: str) -> tuple[KnowledgeTaskLogEntry, ...]:
        return self._task_logs.read(import_id)

    def shutdown(self, *, timeout: float = 15.0) -> None:
        if self._stop.is_set():
            return
        self._stop.set()
        self._queue.put(_STOP)
        if self._thread is not None:
            self._thread.join(timeout=max(0.0, timeout))
        with self._password_lock:
            self._passwords.clear()
        with self._source_path_lock:
            self._source_paths.clear()

    def _worker_main(self) -> None:
        while not self._stop.is_set():
            item = self._queue.get()
            try:
                if item is _STOP:
                    return
                assert isinstance(item, str)
                try:
                    self._process_import(item)
                except Exception as exc:
                    LOGGER.exception(
                        "Knowledge import attempt failed",
                        extra={"event_name": "knowledge.import.failed", "import_id": item},
                    )
                    self._record_failure(item, exc)
            finally:
                if isinstance(item, str):
                    self._store.discard_staged_canonical_bundle(item)
                self._queue.task_done()

    def _process_import(self, import_id: str) -> None:
        password = self._take_password(import_id)
        prepared = self._prepare_source_snapshot(import_id)
        if prepared is None:
            return
        source_path, probe, identity_values = prepared
        self._raise_if_cancelled(import_id)
        generation_id = generate_id()
        identity = CanonicalIdentity(
            **identity_values,
            canonical_generation_id=generation_id,
            media_type=probe.media_type,
            title=Path(str(identity_values["display_name"])).stem,
        )
        try:
            attempt = self._ocr_attempt_factory.prepare()
            try:
                request = KnowledgeImportWorkerRequest(
                    paths=self._paths,
                    import_id=import_id,
                    source_path=str(source_path),
                    expected_source_sha256=str(identity_values["source_sha256"]),
                    expected_source_format=str(identity_values["source_format"]),
                    expected_media_type=probe.media_type,
                    identity=identity,
                    ocr_spawn_spec=attempt.spawn_spec,
                    password=password,
                )
                result = self._worker_runner.run(
                    request,
                    is_cancelled=lambda: self._stop.is_set()
                    or self._cancel_requested(import_id),
                    on_event=lambda event: self._handle_worker_event(import_id, event),
                )
            finally:
                attempt.close()
        except KnowledgeImportWorkerCancelled:
            if self._stop.is_set() and not self._cancel_requested(import_id):
                self._advance(import_id, status="queued", phase="queued")
                self._log_event(
                    import_id,
                    phase="queued",
                    event_code="worker_interrupted_for_shutdown",
                    level="warning",
                )
                return
            self._mark_import_cancelled(import_id)
            raise _ImportCancelled from None
        except KnowledgeImportWorkerCrashed as exc:
            raise ValidationError(
                _SAFE_IMPORT_ERRORS["knowledge_import_worker_crashed"],
                error_code="knowledge_import_worker_crashed",
                retryable=True,
            ) from exc
        except KnowledgeImportWorkerLaunchFailed as exc:
            raise ValidationError(
                _SAFE_IMPORT_ERRORS["knowledge_import_worker_launch_failed"],
                error_code="knowledge_import_worker_launch_failed",
                retryable=True,
            ) from exc
        except KnowledgeImportWorkerTimedOut as exc:
            raise ValidationError(
                _SAFE_IMPORT_ERRORS["knowledge_import_worker_timed_out"],
                error_code="knowledge_import_worker_timed_out",
                retryable=True,
            ) from exc
        if result.status != "succeeded":
            error_code = result.error_code or "knowledge_import_failed"
            raise ValidationError(
                _SAFE_IMPORT_ERRORS.get(
                    error_code,
                    _SAFE_IMPORT_ERRORS["knowledge_import_failed"],
                ),
                error_code=error_code,
                retryable=result.retryable,
            )
        if (
            result.canonical_generation_id != generation_id
            or result.media_type != probe.media_type
            or result.envelope_sha256 is None
            or result.content_ir_sha256 is None
            or result.staged_relative_path is None
        ):
            raise ValidationError(
                _SAFE_IMPORT_ERRORS["knowledge_canonical_integrity_failed"],
                error_code="knowledge_canonical_integrity_failed",
            )
        self._raise_if_cancelled(import_id)
        self._advance(import_id, status="running", phase="publishing_canonical")
        self._log_event(
            import_id,
            phase="publishing_canonical",
            event_code="canonical_publish_started",
        )
        bundle = self._store.publish_staged_canonical_bundle(
            result.staged_relative_path,
            import_id=import_id,
            expected_envelope_sha256=result.envelope_sha256,
            expected_content_ir_sha256=result.content_ir_sha256,
            expected_identity=CanonicalBundleIdentity(
                document_id=identity.document_id,
                import_id=identity.import_id,
                canonical_generation_id=identity.canonical_generation_id,
                source_artifact_id=identity.source_artifact_id,
                library_id=identity.library_id,
                source_sha256=identity.source_sha256,
                source_format=identity.source_format,
            ),
        )
        stored = bundle.stored

        self._raise_if_cancelled(import_id)
        now = utc_now()
        try:
            with self._session_factory() as session:
                row = session.get(KnowledgeImportRow, import_id)
                if row is None:
                    return
                if row.cancel_requested:
                    self._mark_cancelled(row, session)
                    return
                existing = session.exec(
                    select(KnowledgeDocumentRow).where(
                        KnowledgeDocumentRow.library_id == row.library_id,
                        KnowledgeDocumentRow.source_sha256 == row.source_sha256,
                        KnowledgeDocumentRow.active.is_(True),
                    )
                ).first()
                if existing is not None:
                    row.planned_document_id = existing.id
                    row.attempt_number = self._next_attempt_number(
                        session,
                        planned_document_id=existing.id,
                        excluding_import_id=row.id,
                    )
                    row.status = "reused"
                    row.phase = "completed"
                    row.document_id = existing.id
                    row.canonical_generation_id = existing.canonical_generation_id
                    row.source_artifact_id = existing.source_artifact_id
                    row.reused_existing = True
                    row.updated_at = now
                    session.add(row)
                    session.commit()
                    self._log_event(
                        import_id,
                        phase="completed",
                        event_code="document_reused",
                    )
                    return
                document = KnowledgeDocumentRow(
                    id=str(identity_values["document_id"]),
                    library_id=str(identity_values["library_id"]),
                    title=Path(str(identity_values["display_name"])).stem,
                    source_artifact_id=str(identity_values["source_artifact_id"]),
                    source_sha256=str(identity_values["source_sha256"]),
                    source_format=str(identity_values["source_format"]),
                    canonical_path=None,
                    canonical_generation_id=generation_id,
                    retrieval_generation_id=None,
                    retrieval_status="pending",
                )
                session.add(document)
                # These rows intentionally have no ORM relationships.  Flush each
                # authority before inserting the row whose fixed FK names it.
                session.flush()
                generation = KnowledgeCanonicalGenerationRow(
                    id=generation_id,
                    document_id=document.id,
                    import_id=row.id,
                    source_artifact_id=document.source_artifact_id,
                    library_id=document.library_id,
                    source_sha256=str(identity_values["source_sha256"]),
                    source_format=str(identity_values["source_format"]),
                    media_type=probe.media_type,
                    display_name=str(identity_values["display_name"]),
                    envelope_sha256=stored.envelope_sha256,
                    content_ir_sha256=stored.content_ir_sha256,
                    relative_path=stored.relative_path,
                    schema_version=CANONICAL_SCHEMA_VERSION,
                    pipeline_payload=dict(result.pipeline),
                    warnings_payload=list(result.warnings),
                    compatibility_state="verified",
                )
                session.add(generation)
                session.flush()
                row.status = "canonical_ready"
                row.phase = "completed"
                row.document_id = document.id
                row.canonical_generation_id = generation.id
                row.envelope_sha256 = stored.envelope_sha256
                row.content_ir_sha256 = stored.content_ir_sha256
                row.error_code = None
                row.error_summary = None
                row.retryable = False
                row.updated_at = now
                session.add(row)
                session.commit()
        except IntegrityError:
            self._converge_duplicate(import_id)
            return
        self._log_event(import_id, phase="completed", event_code="import_completed")
        if self._canonical_ready_notifier is not None:
            try:
                self._canonical_ready_notifier(document.id, generation.id, import_id)
            except Exception:
                # Canonical publication is already authoritative.  The independent
                # derivation service recovers a missing event from current generations.
                LOGGER.warning(
                    "Knowledge derivation notification deferred to startup recovery",
                    extra={"event_name": "knowledge.derivation.notification_deferred"},
                )

    def _prepare_source_snapshot(
        self,
        import_id: str,
    ) -> tuple[Path, FileProbeResult, dict[str, Any]] | None:
        self._advance(import_id, status="running", phase="snapshot")
        self._log_event(
            import_id,
            phase="snapshot",
            event_code="source_snapshot_started",
        )
        with self._session_factory() as session:
            row = session.get(KnowledgeImportRow, import_id)
            if row is None or row.status == "cancelled":
                return None
            artifact = session.get(ArtifactRow, row.source_artifact_id) if row.source_artifact_id else None
            existing_artifact_path = Path(artifact.absolute_path) if artifact is not None else None
            expected_sha256 = row.source_sha256

        if artifact is None:
            source_reference = self._take_source_path(import_id)
            if source_reference is None:
                raise ValidationError(
                    "Select the source file again to retry this import.",
                    error_code="knowledge_source_reselection_required",
                    retryable=True,
                )
            self._raise_if_cancelled(import_id)
            snapshot = self._store.snapshot_source(
                source_reference,
                maximum_bytes=MAX_SOURCE_BYTES,
            )
            authoritative = self._probe.probe(snapshot.path)
            self._raise_if_cancelled(import_id)
            with self._session_factory() as session:
                row = session.get(KnowledgeImportRow, import_id)
                if row is None or row.status == "cancelled":
                    return None
                existing = session.exec(
                    select(KnowledgeDocumentRow).where(
                        KnowledgeDocumentRow.library_id == row.library_id,
                        KnowledgeDocumentRow.source_sha256 == snapshot.sha256,
                    )
                ).first()
                if existing is not None:
                    was_inactive = not existing.active
                    if was_inactive:
                        existing.active = True
                        existing.updated_at = utc_now()
                        session.add(existing)
                    row.attempt_number = self._next_attempt_number(
                        session,
                        planned_document_id=existing.id,
                        excluding_import_id=row.id,
                    )
                    row.status = "reused"
                    row.phase = "completed"
                    row.source_sha256 = snapshot.sha256
                    row.source_format = authoritative.source_format
                    row.planned_document_id = existing.id
                    row.document_id = existing.id
                    row.source_artifact_id = existing.source_artifact_id
                    row.canonical_generation_id = existing.canonical_generation_id
                    row.reused_existing = True
                    row.retryable = False
                    row.updated_at = utc_now()
                    session.add(row)
                    session.commit()
                    self._log_event(
                        import_id,
                        phase="completed",
                        event_code=(
                            "document_reactivated"
                            if was_inactive
                            else "document_reused"
                        ),
                    )
                    if was_inactive and self._corpus_changed_notifier is not None:
                        try:
                            self._corpus_changed_notifier(row.library_id)
                        except Exception:
                            LOGGER.warning(
                                "Knowledge index notification deferred to startup recovery",
                                extra={
                                    "event_name": (
                                        "knowledge.index.notification_deferred"
                                    )
                                },
                            )
                    return None
                artifact = self._artifacts.register_artifact_in_session(
                    session,
                    RegisterArtifactInput(
                        title=row.original_file_name,
                        absolute_path=str(snapshot.path),
                        kind=ArtifactKind.FILE,
                        mime_type=authoritative.media_type,
                        metadata_payload={
                            "knowledge_source_sha256": snapshot.sha256,
                            "original_file_name": row.original_file_name,
                            "source_format": authoritative.source_format,
                        },
                    ),
                )
                row.source_sha256 = snapshot.sha256
                row.source_format = authoritative.source_format
                row.source_artifact_id = artifact.id
                row.phase = "probing"
                row.updated_at = utc_now()
                session.add(row)
                session.commit()
            self._log_event(
                import_id,
                phase="snapshot",
                event_code="source_snapshot_published",
            )
            source_path = snapshot.path
            probe = authoritative
        else:
            if expected_sha256 is None or existing_artifact_path is None:
                raise ValidationError("Knowledge import identity is incomplete.")
            source = self._store.verify_source_snapshot(
                existing_artifact_path,
                expected_sha256=expected_sha256,
            )
            source_path = source.path
            probe = self._probe.probe(source_path)
            self._log_event(
                import_id,
                phase="snapshot",
                event_code="source_snapshot_verified",
            )

        self._advance(import_id, status="running", phase="probing")
        self._log_event(import_id, phase="probing", event_code="source_probed")
        with self._session_factory() as session:
            row = session.get(KnowledgeImportRow, import_id)
            if row is None or row.status == "cancelled" or not row.source_artifact_id:
                return None
            identity_values = {
                "library_id": row.library_id,
                "document_id": row.planned_document_id,
                "import_id": row.id,
                "source_artifact_id": row.source_artifact_id,
                "source_sha256": row.source_sha256,
                "source_format": row.source_format,
                "display_name": row.original_file_name,
                "attempt_number": row.attempt_number,
            }
        if not identity_values["document_id"] or not identity_values["source_sha256"]:
            raise ValidationError("Knowledge import identity is incomplete.")
        return source_path, probe, identity_values

    def _completed_result(self, import_id: str) -> KnowledgeImportResult | None:
        with self._session_factory() as session:
            row = session.get(KnowledgeImportRow, import_id)
            if row is None:
                raise ValidationError("Knowledge import attempt was not found.")
            if row.status in {"queued", "running"}:
                return None
            if row.status in {"failed", "needs_attention", "cancelled"}:
                raise ValidationError(
                    row.error_summary or "Knowledge import could not be completed.",
                    error_code=row.error_code or "knowledge_import_failed",
                    retryable=row.retryable,
                )
            canonical_path: str | None = None
            if row.canonical_generation_id:
                generation = session.get(KnowledgeCanonicalGenerationRow, row.canonical_generation_id)
                if generation is not None:
                    canonical_path = str(self._store.resolve_relative_path(generation.relative_path))
            if canonical_path is None and row.canonical_path:
                try:
                    canonical_path = str(
                        self._store.resolve_legacy_canonical_path(row.canonical_path)
                    )
                except ValidationError:
                    canonical_path = None
            return KnowledgeImportResult(
                import_id=row.id,
                document_id=row.document_id or row.planned_document_id or "",
                source_artifact_id=row.source_artifact_id,
                source_sha256=row.source_sha256 or "",
                canonical_path=canonical_path,
                canonical_generation_id=row.canonical_generation_id,
                canonical_ready=row.status in {"canonical_ready", "reused", "retrieval_ready"},
                reused_existing=row.reused_existing,
            )

    def _recover_imports(self) -> list[str]:
        pending: list[str] = []
        with self._session_factory() as session:
            rows = list(
                session.exec(
                    select(KnowledgeImportRow)
                    .where(KnowledgeImportRow.status.in_(["queued", "running"]))
                    .order_by(KnowledgeImportRow.created_at)
                )
            )
            for row in rows:
                artifact = session.get(ArtifactRow, row.source_artifact_id) if row.source_artifact_id else None
                try:
                    if artifact is None or not row.source_sha256:
                        raise ValidationError("Knowledge source snapshot is unavailable.")
                    self._store.verify_source_snapshot(
                        Path(artifact.absolute_path),
                        expected_sha256=row.source_sha256,
                    )
                except ValidationError:
                    row.status = "needs_attention"
                    row.phase = "source_reselection_required"
                    row.error_code = "knowledge_source_reselection_required"
                    row.error_summary = _SAFE_IMPORT_ERRORS[
                        "knowledge_source_reselection_required"
                    ]
                    row.retryable = True
                else:
                    row.status = "queued"
                    row.phase = "queued"
                    row.error_code = None
                    row.error_summary = None
                    pending.append(row.id)
                row.updated_at = utc_now()
                session.add(row)
            session.commit()
        return pending

    def cleanup_storage_orphans(self) -> None:
        """Reclaim only source/canonical objects with no live SQLite authority."""

        root = knowledge_root(self._paths)
        canonical_paths: list[str] = []
        source_paths: list[str] = []
        with self._session_factory() as session:
            imports = list(session.exec(select(KnowledgeImportRow)))
            documents = list(session.exec(select(KnowledgeDocumentRow)))
            generations = list(session.exec(select(KnowledgeCanonicalGenerationRow)))
            registered_artifacts = list(session.exec(select(ArtifactRow)))
            source_artifact_ids = {
                artifact_id
                for artifact_id in (
                    *(row.source_artifact_id for row in imports),
                    *(row.source_artifact_id for row in documents),
                    *(row.source_artifact_id for row in generations),
                )
                if artifact_id
            }
            for artifact_id in source_artifact_ids:
                artifact = session.get(ArtifactRow, artifact_id)
                if artifact is not None and _is_current_source_cas_reference(
                    Path(artifact.absolute_path), root
                ):
                    source_paths.append(artifact.absolute_path)
            for artifact in registered_artifacts:
                if _is_current_source_cas_reference(
                    Path(artifact.absolute_path), root
                ):
                    source_paths.append(artifact.absolute_path)
            canonical_paths.extend(row.relative_path for row in generations)
        try:
            result = KnowledgeImportStorageMaintenance(root).cleanup(
                referenced_source_paths=source_paths,
                referenced_canonical_paths=canonical_paths,
            )
        except KnowledgeImportStorageMaintenanceError:
            LOGGER.warning(
                "Knowledge Import storage maintenance skipped an unsafe topology",
                extra={"event_name": "knowledge.import.storage_maintenance_skipped"},
            )
            return
        reclaimed = (
            result.source_cas_quarantined
            + result.canonical_bundles_quarantined
            + result.source_staging_quarantined
            + result.canonical_staging_quarantined
        )
        if reclaimed or result.trash_remaining:
            LOGGER.info(
                "Knowledge Import storage maintenance completed",
                extra={
                    "event_name": "knowledge.import.storage_maintenance_completed",
                    "reclaimed_count": reclaimed,
                    "trash_remaining": result.trash_remaining,
                },
            )

    def _advance(self, import_id: str, *, status: str, phase: str) -> None:
        with self._session_factory() as session:
            row = session.get(KnowledgeImportRow, import_id)
            if row is None or row.status == "cancelled":
                return
            row.status = status
            row.phase = phase
            row.updated_at = utc_now()
            session.add(row)
            session.commit()

    def _handle_worker_event(
        self,
        import_id: str,
        event: KnowledgeImportWorkerEvent,
    ) -> None:
        if event.phase in {
            "normalizing",
            "routing",
            "parsing",
            "canonicalizing",
            "staging_canonical",
        }:
            self._advance(import_id, status="running", phase=event.phase)
        self._log_event(
            import_id,
            phase=event.phase,
            event_code=event.event_code,
            level=event.level,
        )

    def _log_event(
        self,
        import_id: str,
        *,
        phase: str,
        event_code: str,
        level: str = "info",
    ) -> None:
        try:
            self._task_logs.append(
                import_id,
                phase=phase,
                event_code=event_code,
                level=level,
            )
        except Exception:
            LOGGER.warning(
                "Knowledge import task event could not be persisted",
                extra={"event_name": "knowledge.import.task_log_failed"},
            )

    def _cancel_requested(self, import_id: str) -> bool:
        with self._session_factory() as session:
            row = session.get(KnowledgeImportRow, import_id)
            return bool(
                row is None
                or row.cancel_requested
                or row.status == "cancelled"
            )

    def _mark_import_cancelled(self, import_id: str) -> None:
        with self._session_factory() as session:
            row = session.get(KnowledgeImportRow, import_id)
            if row is None or row.status in {
                "canonical_ready",
                "retrieval_ready",
                "reused",
            }:
                return
            self._mark_cancelled(row, session)
        self._log_event(
            import_id,
            phase="cancelled",
            event_code="import_cancelled",
            level="warning",
        )

    def _raise_if_cancelled(self, import_id: str) -> None:
        with self._session_factory() as session:
            row = session.get(KnowledgeImportRow, import_id)
            if row is not None and row.cancel_requested:
                self._mark_cancelled(row, session)
                raise _ImportCancelled

    @staticmethod
    def _mark_cancelled(row: KnowledgeImportRow, session) -> None:
        row.status = "cancelled"
        row.phase = "cancelled"
        row.error_code = "knowledge_import_cancelled"
        row.error_summary = _SAFE_IMPORT_ERRORS["knowledge_import_cancelled"]
        row.retryable = True
        row.updated_at = utc_now()
        session.add(row)
        session.commit()

    def _record_failure(self, import_id: str, exc: Exception) -> None:
        if isinstance(exc, _ImportCancelled):
            return
        code = getattr(exc, "error_code", None)
        if not isinstance(code, str) or not code:
            code = "knowledge_import_failed"
        needs_attention = code in {
            "knowledge_password_required",
            "knowledge_password_invalid",
            "knowledge_doc_converter_unavailable",
            "knowledge_doc_conversion_failed",
            "knowledge_ppt_converter_unavailable",
            "knowledge_ppt_conversion_failed",
            "knowledge_source_reselection_required",
        }
        with self._session_factory() as session:
            row = session.get(KnowledgeImportRow, import_id)
            if row is None or row.status in {
                "cancelled",
                "canonical_ready",
                "retrieval_ready",
                "reused",
            }:
                return
            row.status = "needs_attention" if needs_attention else "failed"
            row.phase = "needs_attention" if needs_attention else "failed"
            row.error_code = code
            row.error_summary = _SAFE_IMPORT_ERRORS.get(code, _SAFE_IMPORT_ERRORS["knowledge_import_failed"])
            row.retryable = bool(getattr(exc, "retryable", False) or needs_attention)
            row.updated_at = utc_now()
            session.add(row)
            session.commit()
        self._log_event(
            import_id,
            phase="needs_attention" if needs_attention else "failed",
            event_code=code,
            level="warning" if needs_attention else "error",
        )

    def _converge_duplicate(self, import_id: str) -> None:
        with self._session_factory() as session:
            row = session.get(KnowledgeImportRow, import_id)
            if row is None or not row.source_sha256:
                return
            existing = session.exec(
                select(KnowledgeDocumentRow).where(
                    KnowledgeDocumentRow.library_id == row.library_id,
                    KnowledgeDocumentRow.source_sha256 == row.source_sha256,
                    KnowledgeDocumentRow.active.is_(True),
                )
            ).first()
            if existing is None:
                raise ValidationError("Concurrent Knowledge publication did not converge.")
            row.planned_document_id = existing.id
            row.attempt_number = self._next_attempt_number(
                session,
                planned_document_id=existing.id,
                excluding_import_id=row.id,
            )
            row.status = "reused"
            row.phase = "completed"
            row.document_id = existing.id
            row.canonical_generation_id = existing.canonical_generation_id
            row.source_artifact_id = existing.source_artifact_id
            row.reused_existing = True
            row.updated_at = utc_now()
            session.add(row)
            session.commit()
        self._log_event(
            import_id,
            phase="completed",
            event_code="document_reused",
        )

    @staticmethod
    def _next_attempt_number(
        session,
        *,
        planned_document_id: str,
        excluding_import_id: str | None = None,
    ) -> int:
        statement = select(KnowledgeImportRow.attempt_number).where(
            KnowledgeImportRow.planned_document_id == planned_document_id
        )
        if excluding_import_id is not None:
            statement = statement.where(KnowledgeImportRow.id != excluding_import_id)
        latest = session.exec(
            statement.order_by(KnowledgeImportRow.attempt_number.desc())
        ).first()
        return int(latest or 0) + 1

    def _remember_password(self, import_id: str, password: str | None) -> None:
        if password:
            with self._password_lock:
                self._passwords[import_id] = password

    def _take_password(self, import_id: str) -> str | None:
        with self._password_lock:
            return self._passwords.pop(import_id, None)

    def _remember_source_path(self, import_id: str, source_path: Path) -> None:
        with self._source_path_lock:
            self._source_paths[import_id] = source_path

    def _take_source_path(self, import_id: str) -> Path | None:
        with self._source_path_lock:
            return self._source_paths.pop(import_id, None)


class _ImportCancelled(Exception):
    pass


def _path_is_lexically_within(candidate: Path, root: Path) -> bool:
    try:
        absolute_candidate = Path(os.path.abspath(candidate.expanduser()))
        absolute_root = Path(os.path.abspath(root.expanduser()))
        absolute_candidate.relative_to(absolute_root)
    except (OSError, ValueError):
        return False
    return True


def _is_current_source_cas_reference(candidate: Path, root: Path) -> bool:
    if not _path_is_lexically_within(candidate, root):
        return False
    absolute_candidate = Path(os.path.abspath(candidate.expanduser()))
    absolute_root = Path(os.path.abspath(root.expanduser()))
    relative = absolute_candidate.relative_to(absolute_root)
    parts = relative.parts
    if len(parts) != 6 or parts[:2] != ("objects", "source"):
        return False
    digest = parts[4]
    return bool(
        len(digest) == 64
        and all(character in "0123456789abcdef" for character in digest)
        and parts[2] == digest[:2]
        and parts[3] == digest[2:4]
        and (parts[5] == "source" or parts[5].startswith("source."))
    )


__all__ = [
    "FileProbe",
    "FileProbeResult",
    "FormatNormalizer",
    "KnowledgeImportReceipt",
    "KnowledgeImportResult",
    "KnowledgeImportService",
    "KnowledgeImportView",
    "ParserRouter",
    "SUPPORTED_KNOWLEDGE_SUFFIXES",
    "_find_libreoffice",
]
