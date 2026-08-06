from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from queue import Full, Queue
from threading import Event, Thread
from time import perf_counter
from typing import Callable

from langgraph.store.base import BaseStore

from agent_factory.memory_system.config import MemorySystemConfig
from agent_factory.memory_system.extraction import extract_memory_actions
from agent_factory.memory_system.retrieval import retrieve_scoped_memory_context
from agent_factory.memory_system.segment import segment_query_text
from agent_factory.memory_system.schema import (
    MemoryConversationMessage,
    MemoryRetrievalSource,
    MemoryWriteJob,
    MemoryWriteReport,
)
from agent_factory.memory_system.writer import MemoryStoreWriter


MemoryEventSink = Callable[[str, dict], None]
MemoryMessageLoader = Callable[[dict], list[dict]]


class MemoryJobJournal:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def mark_pending(self, job: MemoryWriteJob) -> None:
        self._write(job.job_id, {"status": "pending", "job": job.journal_payload(), "updated_at": _now()})

    def mark_completed(self, report: MemoryWriteReport) -> None:
        record = self._read(report.job_id)
        self._write(report.job_id, {**record, "status": report.status, "report": report.model_dump(mode="json"), "updated_at": _now()})

    def mark_failed(self, job_id: str, error: str) -> None:
        record = self._read(job_id)
        self._write(job_id, {**record, "status": "failed", "error": error, "updated_at": _now()})

    def pending_records(self) -> list[dict]:
        records: list[dict] = []
        for path in sorted(self.root.glob("*.json")):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if record.get("status") == "pending":
                records.append(record)
        return records

    def _read(self, job_id: str) -> dict:
        path = self.root / f"{job_id}.json"
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _write(self, job_id: str, record: dict) -> None:
        path = self.root / f"{job_id}.json"
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")


class MemoryBackgroundWorker:
    def __init__(
        self,
        *,
        store: BaseStore,
        config: MemorySystemConfig,
        event_sink: MemoryEventSink | None = None,
        extraction_model: object | None = None,
    ) -> None:
        self.store = store
        self.config = config
        self.event_sink = event_sink or (lambda _event_type, _payload: None)
        self.extraction_model = extraction_model
        self.journal = MemoryJobJournal(config.background.journal_root)
        self.queue: Queue[MemoryWriteJob] = Queue(maxsize=config.background.max_pending_jobs)
        self._stop = Event()
        self._thread: Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = Thread(target=self._run_loop, name="memory-background-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def enqueue(self, job: MemoryWriteJob) -> MemoryWriteReport:
        if not self.config.enabled or not self.config.write_enabled:
            return MemoryWriteReport(
                job_id=job.job_id,
                status="queued_failed",
                namespace=job.namespace,
                error="memory writes disabled",
            )
        self.journal.mark_pending(job)
        try:
            self.queue.put_nowait(job)
        except Full:
            report = MemoryWriteReport(
                job_id=job.job_id,
                status="queued_failed",
                namespace=job.namespace,
                error="memory write queue is full",
            )
            self.journal.mark_completed(report)
            self.event_sink("memory_write_queued_failed", _safe_report(report))
            return report
        report = MemoryWriteReport(job_id=job.job_id, status="queued", namespace=job.namespace)
        self.event_sink("memory_write_queued", _safe_report(report))
        return report

    def recover_pending(self, message_loader: MemoryMessageLoader) -> list[MemoryWriteReport]:
        reports: list[MemoryWriteReport] = []
        for record in self.journal.pending_records():
            try:
                job = MemoryWriteJob.model_validate(record.get("job") or {})
                job.segment.messages = [
                    MemoryConversationMessage.model_validate(message) for message in message_loader(record)
                ]
                reports.append(self.enqueue(job))
            except Exception as exc:
                job_id = str((record.get("job") or {}).get("job_id") or "unknown")
                self.journal.mark_failed(job_id, f"{type(exc).__name__}: {exc}")
        return reports

    def _run_loop(self) -> None:
        while not self._stop.is_set():
            try:
                job = self.queue.get(timeout=0.1)
            except Exception:
                continue
            try:
                report = self._process(job)
                self.journal.mark_completed(report)
                event_type = "memory_write_completed" if report.status in {"completed", "noop"} else "memory_write_failed"
                self.event_sink(event_type, _safe_report(report))
            finally:
                self.queue.task_done()

    def _process(self, job: MemoryWriteJob) -> MemoryWriteReport:
        started = perf_counter()
        try:
            segment = job.segment
            if not segment.messages:
                return MemoryWriteReport(
                    job_id=job.job_id,
                    status="noop",
                    namespace=job.namespace,
                    action_counts={"noop": 1},
                    duration_ms=int((perf_counter() - started) * 1000),
                )
            self.event_sink(
                "memory_segment_prepared",
                {
                    "job_id": job.job_id,
                    "namespace": list(job.namespace),
                    "namespaces": [list(namespace) for namespace in job.available_namespaces.values()],
                    "segment_id": segment.segment_id,
                    "start_turn": segment.start_turn,
                    "end_turn": segment.end_turn,
                    "message_count": len(segment.messages),
                },
            )
            query = segment_query_text(segment)
            related = retrieve_scoped_memory_context(
                store=self.store,
                sources=_job_retrieval_sources(job),
                query=query,
                config=self.config,
            )
            extraction = extract_memory_actions(
                segment=segment,
                related_memories=related,
                model=self.extraction_model,
            )
            self.event_sink(
                "memory_extraction_completed",
                {
                    "job_id": job.job_id,
                    "namespace": list(job.namespace),
                    "namespaces": [list(namespace) for namespace in job.available_namespaces.values()],
                    "status": extraction.status,
                    "action_count": len(extraction.actions),
                    "target_scopes": [action.target_scope for action in extraction.actions],
                    "segment_id": segment.segment_id,
                },
            )
            if extraction.status != "complete":
                return MemoryWriteReport(
                    job_id=job.job_id,
                    status="noop" if extraction.status == "noop" else "failed",
                    namespace=job.namespace,
                    error="memory extraction failed" if extraction.status == "failed" else None,
                    duration_ms=int((perf_counter() - started) * 1000),
                )
            return MemoryStoreWriter(self.store).apply(
                job=job,
                decision=extraction,
                related_memories=related,
            )
        except Exception as exc:
            return MemoryWriteReport(
                job_id=job.job_id,
                status="failed",
                namespace=job.namespace,
                error=f"{type(exc).__name__}: {exc}",
                duration_ms=int((perf_counter() - started) * 1000),
            )


def _safe_report(report: MemoryWriteReport) -> dict:
    return report.model_dump(mode="json")
def _now() -> str:
    return datetime.now(UTC).isoformat()


def _job_retrieval_sources(job: MemoryWriteJob) -> list[MemoryRetrievalSource]:
    ordered_scopes = ("factory", "workspace", "agent", "user")
    selected = [scope for scope in ordered_scopes if scope in job.available_namespaces]
    return [
        MemoryRetrievalSource(
            scope=scope,
            namespace=job.available_namespaces[scope],
            priority=len(selected) - index,
        )
        for index, scope in enumerate(selected)
    ]
