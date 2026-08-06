from __future__ import annotations

import logging
import math
import queue
import threading
import time
from collections.abc import Iterable
from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy.orm import sessionmaker

from .embedding_service import (
    EmbeddingService,
    EmbeddingSettings,
    EmbeddingSettingsSource,
    EmbeddingValidationError,
    embedding_profile_from_settings,
)
from .knowledge_semantic_service import KnowledgeSemanticService
from .storage.models import KnowledgeIndexTaskRow, utc_now
from .storage.repositories.knowledge import KnowledgeRepository

_STOP = object()
LOGGER = logging.getLogger(__name__)
_INDEX_ORDER = ("keyword", "text_vector")
_TRIGGERS = frozenset({"manual", "corpus_change", "settings_change"})


class KnowledgeIndexKind(StrEnum):
    KEYWORD = "keyword"
    TEXT_VECTOR = "text_vector"


@dataclass(frozen=True)
class KnowledgeIndexOverview:
    keyword_state: str
    text_vector_state: str
    vector_configured: bool
    unit_count: int
    estimated_vector_requests: int
    active_task_id: str | None
    active_task_status: str | None
    error_code: str | None


@dataclass(frozen=True)
class KnowledgeIndexTaskView:
    task_id: str
    index_kinds: tuple[str, ...]
    trigger: str
    status: str
    phase: str
    error_code: str | None
    error_summary: str | None


class KnowledgeIndexService:
    """Own serialized, observable rebuilds of derived Knowledge indexes."""

    def __init__(
        self,
        *,
        session_factory: sessionmaker,
        semantic_service: KnowledgeSemanticService,
        embedding_service: EmbeddingService,
        embedding_settings_source: EmbeddingSettingsSource,
        start_worker: bool = True,
    ) -> None:
        self._session_factory = session_factory
        self._semantic = semantic_service
        self._embedding = embedding_service
        self._embedding_settings = embedding_settings_source
        self._repository = KnowledgeRepository()
        self._queue: queue.Queue[str | object] = queue.Queue()
        self._status_executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="xenix-knowledge-status",
        )
        self._enqueue_lock = threading.Lock()
        self._status_requests_lock = threading.Lock()
        self._status_requests: set[Future[KnowledgeIndexOverview]] = set()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        pending = self._recover_tasks()
        if start_worker:
            self._thread = threading.Thread(
                target=self._worker_main,
                name="xenix-knowledge-index",
                daemon=True,
            )
            self._thread.start()
            for task_id in pending:
                self._queue.put(task_id)

    def enqueue_rebuild(
        self,
        index_kinds: Iterable[KnowledgeIndexKind | str],
        *,
        trigger: str,
        library_id: str = "global",
    ) -> str:
        kinds = _normalize_index_kinds(index_kinds)
        if trigger not in _TRIGGERS:
            raise ValueError("Knowledge index task trigger is invalid.")
        created = False
        with self._enqueue_lock:
            with self._session_factory() as session:
                queued = self._repository.list_index_tasks(
                    session,
                    library_id=library_id,
                    statuses=("queued",),
                )
                if queued:
                    row = queued[0]
                    row.index_kinds_payload = list(
                        _normalize_index_kinds((*row.index_kinds_payload, *kinds))
                    )
                    if trigger == "manual" or row.trigger == "corpus_change":
                        row.trigger = trigger
                    row.updated_at = utc_now()
                    self._repository.save_index_task(session, row)
                else:
                    row = KnowledgeIndexTaskRow(
                        library_id=library_id,
                        index_kinds_payload=list(kinds),
                        trigger=trigger,
                        status="queued",
                        phase="queued",
                    )
                    self._repository.create_index_task(session, row)
                    created = True
                session.commit()
                task_id = row.id
        if created and not self._stop.is_set():
            self._queue.put(task_id)
        return task_id

    def notify_corpus_changed(self, library_id: str = "global") -> str | None:
        try:
            configured = self._embedding.freeze() is not None
        except EmbeddingValidationError:
            configured = False
        if not configured or not self.has_searchable_content(library_id=library_id):
            return None
        return self.enqueue_rebuild(
            (KnowledgeIndexKind.TEXT_VECTOR,),
            trigger="corpus_change",
            library_id=library_id,
        )

    def embedding_change_requires_confirmation(
        self,
        previous: EmbeddingSettings,
        proposed: EmbeddingSettings,
        *,
        library_id: str = "global",
    ) -> bool:
        if not proposed.enabled or not self.has_searchable_content(library_id=library_id):
            return False
        return (
            embedding_profile_from_settings(previous).profile_fingerprint
            != embedding_profile_from_settings(proposed).profile_fingerprint
        )

    def has_searchable_content(self, *, library_id: str = "global") -> bool:
        with self._session_factory() as session:
            current, _indexed = self._repository.keyword_index_counts(
                session,
                library_id=library_id,
            )
        return current > 0

    def status(self, *, library_id: str = "global") -> KnowledgeIndexOverview:
        with self._session_factory() as session:
            unit_count, indexed_count = self._repository.keyword_index_counts(
                session,
                library_id=library_id,
            )
            tasks = self._repository.list_index_tasks(
                session,
                library_id=library_id,
            )
        active = next(
            (task for task in tasks if task.status in {"queued", "running"}),
            None,
        )
        latest_keyword_task = next(
            (
                task
                for task in tasks
                if KnowledgeIndexKind.KEYWORD.value in task.index_kinds_payload
                and task.status in {"succeeded", "failed"}
            ),
            None,
        )
        latest_vector_task = next(
            (
                task
                for task in tasks
                if KnowledgeIndexKind.TEXT_VECTOR.value in task.index_kinds_payload
                and task.status in {"succeeded", "failed"}
            ),
            None,
        )
        active_kinds = set(active.index_kinds_payload) if active is not None else set()
        if KnowledgeIndexKind.KEYWORD.value in active_kinds:
            keyword_state = "building"
        elif unit_count == 0:
            keyword_state = "unavailable"
        elif indexed_count == unit_count:
            keyword_state = "ready"
        elif latest_keyword_task is not None and latest_keyword_task.status == "failed":
            keyword_state = "needs_attention"
        else:
            keyword_state = "needs_rebuild"

        if KnowledgeIndexKind.TEXT_VECTOR.value in active_kinds:
            try:
                vector_configured = self._semantic.is_configured()
            except Exception:
                vector_configured = False
            vector_state = "building"
        else:
            try:
                semantic = self._semantic.inspect_index(library_id=library_id)
            except Exception:
                semantic = None
            vector_configured = bool(semantic is not None and semantic.configured)
            if semantic is None:
                vector_state = "needs_attention"
            elif not semantic.configured or semantic.unit_count == 0:
                vector_state = "unavailable"
            elif semantic.ready:
                vector_state = "ready"
            elif (
                latest_vector_task is not None
                and latest_vector_task.status == "failed"
            ):
                vector_state = "needs_attention"
            else:
                vector_state = "needs_rebuild"

        relevant_failure = next(
            (
                task
                for task, state in (
                    (latest_keyword_task, keyword_state),
                    (latest_vector_task, vector_state),
                )
                if task is not None
                and task.status == "failed"
                and state == "needs_attention"
            ),
            None,
        )

        batch_size = 1
        try:
            batch_size = max(1, self._embedding_settings.load().batch_size)
        except Exception:
            pass
        return KnowledgeIndexOverview(
            keyword_state=keyword_state,
            text_vector_state=vector_state,
            vector_configured=vector_configured,
            unit_count=unit_count,
            estimated_vector_requests=(
                math.ceil(unit_count / batch_size)
                if vector_configured and unit_count
                else 0
            ),
            active_task_id=active.id if active is not None else None,
            active_task_status=active.status if active is not None else None,
            error_code=(
                relevant_failure.error_code if relevant_failure is not None else None
            ),
        )

    def request_status(
        self,
        *,
        library_id: str = "global",
    ) -> Future[KnowledgeIndexOverview]:
        """Run a status read on the service-owned single-query lane."""
        with self._status_requests_lock:
            if self._stop.is_set():
                future: Future[KnowledgeIndexOverview] = Future()
                future.cancel()
                return future
            future = self._status_executor.submit(
                self.status,
                library_id=library_id,
            )
            self._status_requests.add(future)
        future.add_done_callback(self._forget_status_request)
        return future

    def list_tasks(
        self,
        *,
        library_id: str = "global",
    ) -> list[KnowledgeIndexTaskView]:
        with self._session_factory() as session:
            rows = self._repository.list_index_tasks(
                session,
                library_id=library_id,
            )
        return [
            KnowledgeIndexTaskView(
                task_id=row.id,
                index_kinds=tuple(row.index_kinds_payload),
                trigger=row.trigger,
                status=row.status,
                phase=row.phase,
                error_code=row.error_code,
                error_summary=row.error_summary,
            )
            for row in rows
        ]

    def rebuild_now(self, task_id: str) -> KnowledgeIndexTaskView:
        # Claim the task under the same short lock used by enqueue/coalescing.
        # Otherwise a producer can merge a new kind into a still-queued row after
        # this worker has read its old payload, making metadata claim work that the
        # worker never performed.
        with self._enqueue_lock:
            with self._session_factory() as session:
                row = self._repository.get_index_task(session, task_id)
                if row is None:
                    raise ValueError("Knowledge index task does not exist.")
                if row.status == "succeeded":
                    return _task_view(row)
                if row.status not in {"queued", "running"}:
                    raise ValueError("Knowledge index task is not runnable.")
                row.status = "running"
                row.phase = "starting"
                row.updated_at = utc_now()
                self._repository.save_index_task(session, row)
                session.commit()
                kinds = tuple(row.index_kinds_payload)
                library_id = row.library_id
                trigger = row.trigger
        try:
            if KnowledgeIndexKind.KEYWORD.value in kinds:
                self._set_phase(task_id, "rebuilding_keyword")
                with self._session_factory() as session:
                    self._repository.rebuild_keyword_index(
                        session,
                        library_id=library_id,
                    )
                    session.commit()
            generation_id: str | None = None
            profile_fingerprint: str | None = None
            corpus_fingerprint: str | None = None
            if KnowledgeIndexKind.TEXT_VECTOR.value in kinds:
                self._set_phase(task_id, "rebuilding_text_vector")
                generation = self._semantic.rebuild_generation(
                    library_id=library_id,
                    force=trigger == "manual",
                )
                generation_id = generation.id
                profile_fingerprint = generation.profile_fingerprint
                corpus_fingerprint = generation.corpus_fingerprint
                current = self._semantic.inspect_index(library_id=library_id)
                if current.generation_id != generation.id:
                    raise RuntimeError(
                        "Knowledge corpus changed before the vector task completed."
                    )
            with self._session_factory() as session:
                row = self._repository.get_index_task(session, task_id)
                if row is None:
                    raise ValueError("Knowledge index task disappeared.")
                row.status = "succeeded"
                row.phase = "completed"
                row.profile_fingerprint = profile_fingerprint
                row.corpus_fingerprint = corpus_fingerprint
                row.vector_generation_id = generation_id
                row.error_code = None
                row.error_summary = None
                row.updated_at = utc_now()
                self._repository.save_index_task(session, row)
                session.commit()
                return _task_view(row)
        except Exception as exc:
            code, summary = _safe_task_failure(exc)
            with self._session_factory() as session:
                row = self._repository.get_index_task(session, task_id)
                if row is None:
                    raise
                row.status = "failed"
                row.phase = "failed"
                row.error_code = code
                row.error_summary = summary
                row.updated_at = utc_now()
                self._repository.save_index_task(session, row)
                session.commit()
                return _task_view(row)

    def shutdown(self, *, timeout: float = 15.0) -> None:
        deadline = time.monotonic() + max(0.0, timeout)
        with self._status_requests_lock:
            if self._stop.is_set():
                return
            self._stop.set()
            pending_status = tuple(self._status_requests)
        self._status_executor.shutdown(wait=False, cancel_futures=True)
        self._queue.put(_STOP)
        if self._thread is not None:
            self._thread.join(timeout=max(0.0, deadline - time.monotonic()))
        if pending_status:
            _done, not_done = wait(
                pending_status,
                timeout=max(0.0, deadline - time.monotonic()),
            )
            if not_done:
                LOGGER.warning(
                    "Knowledge index status shutdown exceeded %.1f seconds; "
                    "waiting for safe quiescence.",
                    max(0.0, timeout),
                )
        self._status_executor.shutdown(wait=True, cancel_futures=True)

    def _set_phase(self, task_id: str, phase: str) -> None:
        with self._session_factory() as session:
            row = self._repository.get_index_task(session, task_id)
            if row is None:
                raise ValueError("Knowledge index task does not exist.")
            row.phase = phase
            row.updated_at = utc_now()
            self._repository.save_index_task(session, row)
            session.commit()

    def _worker_main(self) -> None:
        while not self._stop.is_set():
            item = self._queue.get()
            try:
                if item is _STOP:
                    return
                assert isinstance(item, str)
                self.rebuild_now(item)
            finally:
                self._queue.task_done()

    def _forget_status_request(
        self,
        future: Future[KnowledgeIndexOverview],
    ) -> None:
        with self._status_requests_lock:
            self._status_requests.discard(future)

    def _recover_tasks(self) -> list[str]:
        pending: list[str] = []
        with self._session_factory() as session:
            rows = self._repository.list_index_tasks(
                session,
                library_id=None,
                statuses=("queued", "running"),
            )
            for row in reversed(rows):
                row.status = "queued"
                row.phase = "queued"
                row.updated_at = utc_now()
                self._repository.save_index_task(session, row)
                pending.append(row.id)
            session.commit()
        return pending


def _normalize_index_kinds(
    values: Iterable[KnowledgeIndexKind | str],
) -> tuple[str, ...]:
    normalized = {str(value) for value in values}
    invalid = normalized - set(_INDEX_ORDER)
    if invalid or not normalized:
        raise ValueError("Knowledge index task must select a supported index.")
    return tuple(value for value in _INDEX_ORDER if value in normalized)


def _task_view(row: KnowledgeIndexTaskRow) -> KnowledgeIndexTaskView:
    return KnowledgeIndexTaskView(
        task_id=row.id,
        index_kinds=tuple(row.index_kinds_payload),
        trigger=row.trigger,
        status=row.status,
        phase=row.phase,
        error_code=row.error_code,
        error_summary=row.error_summary,
    )


def _safe_task_failure(exc: Exception) -> tuple[str, str]:
    code = getattr(exc, "error_code", None)
    if not isinstance(code, str) or not code.startswith(("knowledge_", "embedding_")):
        return (
            "knowledge_index_rebuild_failed",
            "Knowledge index rebuild could not be completed.",
        )
    if code == "embedding_provider_http_error":
        details = getattr(exc, "error_details", {})
        status_code = details.get("status_code") if isinstance(details, dict) else None
        status = (
            f" (HTTP {status_code})"
            if isinstance(status_code, int) and not isinstance(status_code, bool)
            else ""
        )
        return (
            code,
            "Embedding provider rejected the request"
            f"{status}. Check the model and Batch size setting.",
        )
    if code == "embedding_provider_unavailable":
        return (
            code,
            "Embedding provider is unavailable. Check the endpoint and network connection.",
        )
    if code.startswith("embedding_"):
        return (
            code,
            "Embedding could not be completed. Check the Knowledge Base embedding settings.",
        )
    return code, "Knowledge index rebuild could not be completed."


__all__ = [
    "KnowledgeIndexKind",
    "KnowledgeIndexOverview",
    "KnowledgeIndexService",
    "KnowledgeIndexTaskView",
]
