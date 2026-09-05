from __future__ import annotations

import queue
import threading
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import sessionmaker
from sqlmodel import select

from ..config import AppPaths
from .knowledge_content_store import CanonicalBundleIdentity, KnowledgeContentStore
from .knowledge_service import (
    KnowledgeUnitInput,
    bound_knowledge_units,
    prepare_knowledge_search_text,
)
from .knowledge_projection import (
    RETRIEVAL_PROJECTION_VERSION,
    knowledge_unit_id,
    retrieval_content_fingerprint,
)
from .storage.models import (
    KnowledgeCanonicalGenerationRow,
    KnowledgeDerivationRow,
    KnowledgeDocumentRow,
    KnowledgeUnitRow,
    utc_now,
)
from .storage.repositories.knowledge import KnowledgeRepository

_STOP = object()
LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class DerivationResult:
    job_id: str
    document_id: str
    canonical_generation_id: str
    retrieval_ready: bool
    unit_count: int


@dataclass(frozen=True)
class KnowledgeDerivationView:
    job_id: str
    status: str
    phase: str
    error_code: str | None
    retryable: bool


class KnowledgeDerivationService:
    """Publish retrievable Units/FTS independently from canonical import."""

    def __init__(
        self,
        *,
        paths: AppPaths,
        session_factory: sessionmaker,
        retrieval_ready_notifier: Callable[[str], object] | None = None,
        start_worker: bool = True,
    ) -> None:
        self._session_factory = session_factory
        self._store = KnowledgeContentStore(paths)
        self._repository = KnowledgeRepository()
        self._retrieval_ready_notifier = retrieval_ready_notifier
        self._queue: queue.Queue[str | object] = queue.Queue()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        pending = self._recover_jobs()
        if start_worker:
            self._thread = threading.Thread(
                target=self._worker_main,
                name="xenix-knowledge-derivation",
                daemon=True,
            )
            self._thread.start()
            for job_id in pending:
                self.notify(job_id)

    def notify(self, job_id: str) -> None:
        if not self._stop.is_set():
            self._queue.put(job_id)

    def enqueue_generation(
        self,
        document_id: str,
        canonical_generation_id: str,
        import_id: str | None,
    ) -> str:
        """Idempotently materialize the canonical-ready event as a derivation job."""

        with self._session_factory() as session:
            existing = session.exec(
                select(KnowledgeDerivationRow)
                .where(
                    KnowledgeDerivationRow.document_id == document_id,
                    KnowledgeDerivationRow.canonical_generation_id
                    == canonical_generation_id,
                )
                .order_by(KnowledgeDerivationRow.attempt_number.desc())
            ).first()
            if existing is not None:
                job_id = existing.id
                should_notify = existing.status in {"queued", "running"}
            else:
                document = session.get(KnowledgeDocumentRow, document_id)
                generation = session.get(
                    KnowledgeCanonicalGenerationRow,
                    canonical_generation_id,
                )
                if (
                    document is None
                    or generation is None
                    or document.canonical_generation_id != canonical_generation_id
                    or generation.document_id != document_id
                ):
                    raise ValueError("Canonical Knowledge generation is not current.")
                job = KnowledgeDerivationRow(
                    document_id=document_id,
                    canonical_generation_id=canonical_generation_id,
                    import_id=import_id,
                    status="queued",
                    phase="queued",
                    attempt_number=1,
                    retryable=False,
                )
                session.add(job)
                session.commit()
                session.refresh(job)
                job_id = job.id
                should_notify = True
        if should_notify:
            self.notify(job_id)
        return job_id

    def status_for_import(self, import_id: str) -> KnowledgeDerivationView | None:
        with self._session_factory() as session:
            row = session.exec(
                select(KnowledgeDerivationRow)
                .where(KnowledgeDerivationRow.import_id == import_id)
                .order_by(KnowledgeDerivationRow.attempt_number.desc())
            ).first()
            if row is None:
                return None
            return KnowledgeDerivationView(
                job_id=row.id,
                status=row.status,
                phase=row.phase,
                error_code=row.error_code,
                retryable=row.retryable,
            )

    def retry_for_import(self, import_id: str) -> str:
        """Create a new retrieval attempt without reparsing canonical content."""

        with self._session_factory() as session:
            previous = session.exec(
                select(KnowledgeDerivationRow)
                .where(
                    KnowledgeDerivationRow.import_id == import_id,
                )
                .order_by(KnowledgeDerivationRow.attempt_number.desc())
            ).first()
            if previous is None or previous.status != "failed" or not previous.retryable:
                raise ValueError("Knowledge derivation retry is not available.")

            job = KnowledgeDerivationRow(
                document_id=previous.document_id,
                canonical_generation_id=previous.canonical_generation_id,
                import_id=import_id,
                status="queued",
                phase="queued",
                attempt_number=previous.attempt_number + 1,
                retry_of=previous.id,
                retryable=False,
            )
            document = session.get(KnowledgeDocumentRow, previous.document_id)
            if document is not None and document.retrieval_generation_id is None:
                document.retrieval_status = "pending"
                document.updated_at = utc_now()
                session.add(document)
            session.add(job)
            session.commit()
            session.refresh(job)
        self.notify(job.id)
        return job.id

    def derive_now(self, job_id: str) -> DerivationResult:
        with self._session_factory() as session:
            job = session.get(KnowledgeDerivationRow, job_id)
            if job is None:
                raise ValueError("Knowledge derivation job does not exist.")
            if job.status == "succeeded":
                document = session.get(KnowledgeDocumentRow, job.document_id)
                ready = bool(
                    document is not None
                    and document.retrieval_status == "ready"
                    and document.retrieval_generation_id == job.canonical_generation_id
                    and document.retrieval_projection_version
                    == RETRIEVAL_PROJECTION_VERSION
                )
                count = document.retrieval_unit_count if ready and document is not None else 0
                return DerivationResult(job.id, job.document_id, job.canonical_generation_id, ready, count)
            if job.status not in {"queued", "running"}:
                raise ValueError("Knowledge derivation job is not runnable.")
            job.status = "running"
            job.phase = "reading_canonical"
            job.updated_at = utc_now()
            session.add(job)
            session.commit()
            generation_id = job.canonical_generation_id

        with self._session_factory() as session:
            generation = session.get(KnowledgeCanonicalGenerationRow, generation_id)
            if generation is None:
                return self._record_failure(job_id, "knowledge_canonical_generation_missing")
            relative_path = generation.relative_path
            envelope_sha256 = generation.envelope_sha256
            content_ir_sha256 = generation.content_ir_sha256
        try:
            bundle = self._store.read_canonical_bundle(
                relative_path,
                expected_envelope_sha256=envelope_sha256,
                expected_content_ir_sha256=content_ir_sha256,
                expected_identity=CanonicalBundleIdentity(
                    document_id=generation.document_id,
                    import_id=generation.import_id,
                    canonical_generation_id=generation.id,
                    source_artifact_id=generation.source_artifact_id,
                    library_id=generation.library_id,
                    source_sha256=generation.source_sha256,
                    source_format=generation.source_format,
                ),
            )
            from docling_core.types.doc import DoclingDocument

            document_ir = DoclingDocument.model_validate(bundle.docling_document)
            inputs = _knowledge_units(document_ir)
        except Exception:
            return self._record_failure(job_id, "knowledge_derivation_failed")

        with self._session_factory() as session:
            job = session.get(KnowledgeDerivationRow, job_id)
            generation = session.get(KnowledgeCanonicalGenerationRow, generation_id)
            if job is None or generation is None:
                raise ValueError("Knowledge derivation state disappeared.")
            document = session.get(KnowledgeDocumentRow, job.document_id)
            if document is None:
                return self._record_failure(job_id, "knowledge_document_missing")
            if document.canonical_generation_id != generation.id:
                job.status = "succeeded"
                job.phase = "superseded"
                job.updated_at = utc_now()
                session.add(job)
                session.commit()
                return DerivationResult(job.id, document.id, generation.id, False, 0)

            rows = [
                KnowledgeUnitRow(
                    id=knowledge_unit_id(
                        document_id=document.id,
                        canonical_generation_id=generation.id,
                        ordinal=ordinal,
                    ),
                    document_id=document.id,
                    canonical_generation_id=generation.id,
                    ordinal=ordinal,
                    text=item.text.strip(),
                    search_text=prepare_knowledge_search_text(item.text),
                    locator_payload=dict(item.locator),
                )
                for ordinal, item in enumerate(inputs)
                if item.text.strip()
            ]
            self._repository.replace_units(session, document=document, units=rows)
            now = utc_now()
            if rows:
                document.retrieval_generation_id = generation.id
                document.retrieval_status = "ready"
                document.retrieval_projection_version = RETRIEVAL_PROJECTION_VERSION
                document.retrieval_content_fingerprint = retrieval_content_fingerprint(
                    (row.ordinal, row.text, row.locator_payload) for row in rows
                )
                document.retrieval_unit_count = len(rows)
            else:
                document.retrieval_generation_id = None
                document.retrieval_status = "unavailable"
                document.retrieval_projection_version = RETRIEVAL_PROJECTION_VERSION
                document.retrieval_content_fingerprint = None
                document.retrieval_unit_count = 0
            document.updated_at = now
            session.add(document)
            job.status = "succeeded"
            job.phase = "completed" if rows else "no_text_projection"
            job.error_code = None
            job.error_summary = None
            job.retryable = False
            job.updated_at = now
            session.add(job)
            session.commit()
            result = DerivationResult(
                job.id,
                document.id,
                generation.id,
                bool(rows),
                len(rows),
            )
            library_id = document.library_id
        if self._retrieval_ready_notifier is not None:
            try:
                self._retrieval_ready_notifier(library_id)
            except Exception:
                LOGGER.warning(
                    "Knowledge vector rebuild notification was deferred",
                    extra={"event_name": "knowledge.index.notification_deferred"},
                )
        return result

    def shutdown(self, *, timeout: float = 10.0) -> None:
        if self._stop.is_set():
            return
        self._stop.set()
        self._queue.put(_STOP)
        if self._thread is not None:
            self._thread.join(timeout=max(0.0, timeout))

    def _worker_main(self) -> None:
        while not self._stop.is_set():
            item = self._queue.get()
            try:
                if item is _STOP:
                    return
                assert isinstance(item, str)
                try:
                    self.derive_now(item)
                except Exception:
                    self._record_failure(item, "knowledge_derivation_failed")
            finally:
                self._queue.task_done()

    def _recover_jobs(self) -> list[str]:
        pending: list[str] = []
        with self._session_factory() as session:
            rows = list(
                session.exec(
                    select(KnowledgeDerivationRow)
                    .where(KnowledgeDerivationRow.status.in_(["queued", "running"]))
                    .order_by(KnowledgeDerivationRow.created_at)
                )
            )
            for row in rows:
                row.status = "queued"
                row.phase = "queued"
                row.updated_at = utc_now()
                session.add(row)
                pending.append(row.id)
            existing_attempts: dict[str, list[KnowledgeDerivationRow]] = {}
            for row in session.exec(select(KnowledgeDerivationRow)):
                existing_attempts.setdefault(row.canonical_generation_id, []).append(row)
            documents = list(
                session.exec(
                    select(KnowledgeDocumentRow).where(
                        KnowledgeDocumentRow.active.is_(True)
                    )
                )
            )
            for document in documents:
                if (
                    document.retrieval_generation_id == document.canonical_generation_id
                    and document.retrieval_status == "ready"
                    and document.retrieval_projection_version
                    == RETRIEVAL_PROJECTION_VERSION
                ):
                    continue
                attempts = existing_attempts.get(document.canonical_generation_id, [])
                if any(row.status in {"queued", "running"} for row in attempts):
                    continue
                generation = session.get(
                    KnowledgeCanonicalGenerationRow,
                    document.canonical_generation_id,
                )
                if generation is None or generation.document_id != document.id:
                    continue
                job = KnowledgeDerivationRow(
                    document_id=document.id,
                    canonical_generation_id=generation.id,
                    import_id=generation.import_id,
                    status="queued",
                    phase="queued",
                    attempt_number=max(
                        (row.attempt_number for row in attempts),
                        default=0,
                    )
                    + 1,
                    retry_of=max(
                        attempts,
                        key=lambda row: row.attempt_number,
                        default=None,
                    ).id
                    if attempts
                    else None,
                    retryable=False,
                )
                session.add(job)
                pending.append(job.id)
            session.commit()
        return pending

    def _record_failure(self, job_id: str, error_code: str) -> DerivationResult:
        with self._session_factory() as session:
            job = session.get(KnowledgeDerivationRow, job_id)
            if job is None:
                raise ValueError("Knowledge derivation job does not exist.")
            document = session.get(KnowledgeDocumentRow, job.document_id)
            now = utc_now()
            job.status = "failed"
            job.phase = "failed"
            job.error_code = error_code
            job.error_summary = "Knowledge text derivation could not be completed."
            job.retryable = True
            job.updated_at = now
            session.add(job)
            if document is not None and document.retrieval_generation_id is None:
                document.retrieval_status = "failed"
                document.updated_at = now
                session.add(document)
            session.commit()
            return DerivationResult(job.id, job.document_id, job.canonical_generation_id, False, 0)


def _knowledge_units(document: Any) -> list[KnowledgeUnitInput]:
    units: list[KnowledgeUnitInput] = []
    for item, level in document.iterate_items():
        text = str(getattr(item, "text", "") or "").strip()
        label = str(getattr(getattr(item, "label", None), "value", getattr(item, "label", ""))).casefold()
        if not text and label != "picture" and hasattr(item, "export_to_markdown"):
            try:
                text = str(item.export_to_markdown(doc=document)).strip()
            except Exception:
                text = ""
        if not text:
            continue
        locator: dict[str, Any] = {"level": int(level)}
        provenance = list(getattr(item, "prov", ()) or ())
        if provenance:
            page_no = getattr(provenance[0], "page_no", None)
            if page_no is not None:
                locator["page"] = int(page_no)
        if "page" not in locator:
            locator["passage"] = len(units) + 1
        units.append(KnowledgeUnitInput(text=text, locator=locator))
    if not units:
        fallback = str(document.export_to_text()).strip()
        if fallback:
            units.append(KnowledgeUnitInput(text=fallback, locator={"document": True}))
    return bound_knowledge_units(units)
