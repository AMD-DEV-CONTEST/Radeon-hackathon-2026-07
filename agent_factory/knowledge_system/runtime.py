from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
import json
import shutil
import threading
from typing import Any

from langgraph.store.base import BaseStore

from agent_factory.context_system.token_estimation import estimate_text_tokens
from agent_factory.knowledge_system.catalog import KnowledgeCatalog
from agent_factory.knowledge_system.chunking import chunk_document
from agent_factory.knowledge_system.events import KnowledgeEventSink, emit_knowledge_event, knowledge_event_payload
from agent_factory.knowledge_system.identifiers import stable_source_id
from agent_factory.knowledge_system.loaders import discover_source, json_hash, sha256_text
from agent_factory.knowledge_system.planner import plan_knowledge_ingestion
from agent_factory.knowledge_system.schema import (
    KnowledgeRuntimeConfig,
    KnowledgeDocument,
    KnowledgeIngestionPlan,
    KnowledgeIngestionJob,
    KnowledgeResult,
    KnowledgeSourceManifest,
    KnowledgeSourcePreview,
    MountMode,
    SourceType,
    now_iso,
)


@dataclass(slots=True)
class KnowledgeRuntime:
    config: KnowledgeRuntimeConfig
    owner_type: str
    owner_id: str
    catalog: KnowledgeCatalog
    store: BaseStore | None = None
    semantic_index_enabled: bool = False
    event_sink: KnowledgeEventSink | None = None
    pending_jobs: deque[str] = field(default_factory=deque)
    _queue_condition: threading.Condition = field(default_factory=threading.Condition)

    @property
    def root(self) -> Path:
        return Path(self.config.root)

    def prepare_source(self, source: dict[str, Any]) -> KnowledgeSourcePreview:
        source_type, mount_mode, uri, source_id, display_name, metadata = self._normalize_source_spec(source)
        self._emit(
            "knowledge_source_prepare_started",
            source_id=source_id,
            mode=mount_mode,
            status="running",
            message="Preparing knowledge source preview.",
        )
        discovery = discover_source(
            source_type=source_type,
            uri=uri,
            metadata=metadata,
            limits=self.config.limits,
        )
        ingestion_plan = plan_knowledge_ingestion(
            source_type=source_type,
            mount_mode=mount_mode,
            discovery=discovery,
            limits=self.config.limits,
            metadata=metadata,
        )
        preview = KnowledgeSourcePreview(
            source_id=source_id,
            source_type=source_type,
            display_name=display_name,
            mount_mode=mount_mode,
            uri=uri,
            owner_type=self.owner_type,
            owner_id=self.owner_id,
            capabilities=_capabilities_for(source_type=source_type, mount_mode=mount_mode),
            estimated_documents=len(discovery.documents),
            file_type_counts=discovery.file_type_counts,
            requires_embedding=mount_mode == "rag",
            planned_phases=_planned_phases(mount_mode),
            warnings=discovery.warnings,
            metadata={
                "content_hash": _source_hash(uri=uri, metadata=metadata),
                "sample_titles": [item.title for item in discovery.documents[:8]],
                "ingestion_plan": ingestion_plan.model_dump(mode="json"),
            },
        )
        self._emit(
            "knowledge_source_preview_available",
            source_id=source_id,
            mode=mount_mode,
            status="completed",
            message="Knowledge source preview is ready.",
            payload={"preview": preview.model_dump(mode="json")},
        )
        return preview

    def confirm_source(self, source: dict[str, Any]) -> KnowledgeIngestionJob:
        source_type, mount_mode, uri, source_id, display_name, metadata = self._normalize_source_spec(source)
        self._require_semantic_index(mount_mode)
        ingestion_plan = _ingestion_plan_from_source(source, metadata)
        if ingestion_plan is None:
            discovery = discover_source(
                source_type=source_type,
                uri=uri,
                metadata=metadata,
                limits=self.config.limits,
            )
            ingestion_plan = plan_knowledge_ingestion(
                source_type=source_type,
                mount_mode=mount_mode,
                discovery=discovery,
                limits=self.config.limits,
                metadata=metadata,
            )
        metadata = {**metadata, "ingestion_plan": ingestion_plan.model_dump(mode="json")}
        manifest = KnowledgeSourceManifest(
            source_id=source_id,
            source_type=source_type,
            display_name=display_name,
            mount_mode=mount_mode,
            uri=uri,
            original_uri=str(metadata.get("original_uri") or uri),
            capabilities=_capabilities_for(source_type=source_type, mount_mode=mount_mode),
            content_hash=_source_hash(uri=uri, metadata=metadata),
            metadata=metadata,
            status="registered",
        )
        self.catalog.upsert_source(manifest)
        job = KnowledgeIngestionJob(source_id=source_id, mode=mount_mode)
        self.catalog.upsert_job(job)
        self.enqueue_job(job.job_id)
        self._emit(
            "knowledge_source_registered",
            source_id=source_id,
            job_id=job.job_id,
            mode=mount_mode,
            status="registered",
            message="Knowledge source registered.",
            payload={"source": manifest.model_dump(mode="json")},
        )
        self._emit(
            "knowledge_ingestion_queued",
            source_id=source_id,
            job_id=job.job_id,
            mode=mount_mode,
            status="queued",
            message="Knowledge ingestion job queued.",
        )
        return job

    def enqueue_job(self, job_id: str) -> None:
        with self._queue_condition:
            if job_id not in self.pending_jobs:
                self.pending_jobs.append(job_id)
            self._queue_condition.notify_all()

    def next_job(self, timeout: float = 0.5) -> str | None:
        with self._queue_condition:
            if not self.pending_jobs:
                self._queue_condition.wait(timeout=timeout)
            if not self.pending_jobs:
                return None
            return self.pending_jobs.popleft()

    def run_job(self, job_id: str) -> KnowledgeIngestionJob:
        job = self.catalog.get_job(job_id)
        if job is None:
            raise ValueError(f"knowledge ingestion job not found: {job_id}")
        manifest = self.catalog.get_source(job.source_id)
        if manifest is None:
            raise ValueError(f"knowledge source not found: {job.source_id}")
        ingestion_plan = _ingestion_plan_from_manifest(manifest)
        job = job.model_copy(update={"status": "running", "phase": "discover", "updated_at": now_iso()})
        self.catalog.upsert_job(job)
        self.catalog.set_source_status(job.source_id, "indexing")
        self._emit_job("knowledge_ingestion_started", job, message="Knowledge ingestion started.")
        try:
            self._require_semantic_index(manifest.mount_mode)
            discovery = discover_source(
                source_type=manifest.source_type,
                uri=manifest.uri,
                metadata=manifest.metadata,
                limits=self.config.limits,
            )
            self._emit_job(
                "knowledge_ingestion_progress",
                job.model_copy(update={"phase": "load"}),
                counts={"documents_discovered": len(discovery.documents)},
                progress={"current": 1, "total": 6, "percent": 16},
                message="Knowledge documents discovered.",
            )
            documents: list[KnowledgeDocument] = []
            chunks = []
            for index, loaded in enumerate(discovery.documents):
                document_id = f"{manifest.source_id}:{sha256_text(loaded.uri)[:16]}"
                document = KnowledgeDocument(
                    document_id=document_id,
                    source_id=manifest.source_id,
                    title=loaded.title,
                    uri=loaded.uri,
                    document_type=loaded.document_type,
                    content_hash=loaded.content_hash,
                    metadata=loaded.metadata,
                )
                documents.append(document)
                chunks.extend(
                    chunk_document(
                        source_id=manifest.source_id,
                        document=document,
                        content=loaded.content,
                        limits=self.config.limits,
                        ingestion_plan=ingestion_plan,
                    )
                )
                if index and index % 20 == 0:
                    self._emit_job(
                        "knowledge_ingestion_progress",
                        job.model_copy(update={"phase": "chunk"}),
                        counts={"documents_loaded": index, "chunks_created": len(chunks)},
                        progress={"current": min(index, len(discovery.documents)), "total": max(1, len(discovery.documents))},
                        message="Knowledge documents are being chunked.",
                    )
            self._emit_job(
                "knowledge_ingestion_progress",
                job.model_copy(update={"phase": "index"}),
                counts={"documents_loaded": len(documents), "chunks_created": len(chunks)},
                progress={"current": 4, "total": 6, "percent": 66},
                message="Writing knowledge catalog and keyword index.",
            )
            self.catalog.replace_source_documents(source_id=manifest.source_id, documents=documents, chunks=chunks)
            chunks_embedded = 0
            if manifest.mount_mode == "rag":
                self._emit_job(
                    "knowledge_ingestion_progress",
                    job.model_copy(update={"phase": "embed"}),
                    counts={"chunks_created": len(chunks)},
                    progress={"current": 5, "total": 6, "percent": 83},
                    message="Writing semantic index through LangGraph BaseStore.",
                )
                chunks_embedded = self._write_semantic_index(manifest=manifest, chunks=chunks)
            report_path = self._write_report(job=job, manifest=manifest, documents=documents, chunks=chunks, warnings=discovery.warnings)
            completed = job.model_copy(
                update={
                    "status": "completed",
                    "phase": "finalize",
                    "report_path": str(report_path),
                    "counts": {
                        "documents_discovered": len(discovery.documents),
                        "documents_loaded": len(documents),
                        "chunks_created": len(chunks),
                        "chunks_embedded": chunks_embedded,
                        "documents_skipped": max(0, len(discovery.documents) - len(documents)),
                        "errors": 0,
                    },
                    "updated_at": now_iso(),
                }
            )
            self.catalog.upsert_job(completed)
            self.catalog.upsert_source(
                manifest.model_copy(update={"status": "ready", "updated_at": now_iso()})
            )
            self._emit_job("knowledge_ingestion_completed", completed, message="Knowledge source indexing completed.")
            self._emit(
                "knowledge_source_ready",
                source_id=manifest.source_id,
                job_id=completed.job_id,
                mode=manifest.mount_mode,
                status="ready",
                report_path=str(report_path),
                counts=completed.counts,
                message="Knowledge source is ready.",
            )
            return completed
        except Exception as exc:
            failed = job.model_copy(
                update={
                    "status": "failed",
                    "error": f"{type(exc).__name__}: {exc}",
                    "updated_at": now_iso(),
                }
            )
            self.catalog.upsert_job(failed)
            self.catalog.upsert_source(manifest.model_copy(update={"status": "failed", "updated_at": now_iso()}))
            self._emit_job(
                "knowledge_ingestion_failed",
                failed,
                error={"where": "knowledge.ingestion", "why": "ingestion_failed", "message": failed.error},
                message="Knowledge ingestion failed.",
            )
            return failed

    def list_sources(self) -> list[KnowledgeSourceManifest]:
        return self.catalog.list_sources()

    def describe_source(self, source_id: str) -> dict[str, Any]:
        source = self._require_source(source_id)
        documents = self.catalog.list_documents(source_id)
        return {
            "source": source.model_dump(mode="json"),
            "document_count": len(documents),
            "documents": [document.model_dump(mode="json") for document in documents[:50]],
        }

    def list_documents(self, source_id: str | None = None) -> list[KnowledgeDocument]:
        return self.catalog.list_documents(source_id)

    def search(
        self,
        *,
        query: str,
        source_id: str | None = None,
        mode: str = "auto",
        top_k: int = 8,
    ) -> list[KnowledgeResult]:
        query = query.strip()
        if not query:
            return []
        limit = min(top_k, self.config.limits.max_search_results)
        results: list[KnowledgeResult] = []
        if mode in {"semantic", "hybrid"}:
            self._require_semantic_index("rag")
        if mode in {"auto", "keyword", "hybrid", "readable"}:
            results.extend(self.catalog.keyword_search(query=query, source_id=source_id, limit=limit))
        if mode in {"auto", "semantic", "hybrid"} and self.semantic_index_enabled:
            results.extend(self._semantic_search(query=query, source_id=source_id, limit=limit))
        return _dedupe_results(results)[:limit]

    def open(self, *, source_id: str | None = None, document_id: str | None = None, chunk_id: str | None = None) -> dict[str, Any]:
        if chunk_id:
            chunk = self.catalog.get_chunk(chunk_id)
            if chunk is None:
                raise ValueError(f"knowledge chunk not found: {chunk_id}")
            return {"chunk": chunk.model_dump(mode="json")}
        if document_id:
            document = self.catalog.get_document(document_id)
            if document is None:
                raise ValueError(f"knowledge document not found: {document_id}")
            chunks = self.catalog.chunks_for_document(document_id)
            return {
                "document": document.model_dump(mode="json"),
                "chunks": [chunk.model_dump(mode="json", exclude={"content"}) for chunk in chunks[:50]],
            }
        if source_id:
            return self.describe_source(source_id)
        raise ValueError("open requires source_id, document_id, or chunk_id")

    def read(self, *, document_id: str | None = None, chunk_id: str | None = None, max_chars: int | None = None) -> dict[str, Any]:
        limit = max_chars or self.config.limits.max_read_chars
        if chunk_id:
            chunk = self.catalog.get_chunk(chunk_id)
            if chunk is None:
                raise ValueError(f"knowledge chunk not found: {chunk_id}")
            return {
                "content": chunk.content[:limit],
                "content_length": len(chunk.content),
                "truncated": len(chunk.content) > limit,
                "chunk": chunk.model_dump(mode="json", exclude={"content"}),
            }
        if not document_id:
            raise ValueError("read requires document_id or chunk_id")
        chunks = self.catalog.chunks_for_document(document_id)
        content = "\n\n".join(chunk.content for chunk in chunks)
        return {
            "content": content[:limit],
            "content_length": len(content),
            "truncated": len(content) > limit,
            "document_id": document_id,
            "chunk_count": len(chunks),
        }

    def reindex_source(self, source_id: str) -> KnowledgeIngestionJob:
        manifest = self._require_source(source_id)
        job = KnowledgeIngestionJob(source_id=manifest.source_id, mode=manifest.mount_mode)
        self.catalog.upsert_job(job)
        self.enqueue_job(job.job_id)
        self._emit(
            "knowledge_source_reindex_requested",
            source_id=source_id,
            job_id=job.job_id,
            mode=manifest.mount_mode,
            status="queued",
            message="Knowledge source reindex requested.",
        )
        return job

    def remove_source(self, source_id: str) -> bool:
        manifest = self._require_source(source_id)
        if self.store is not None:
            for item in self.store.search(self._namespace(manifest.source_id), limit=100000):
                self.store.delete(tuple(item.namespace), item.key)
        self.catalog.delete_source(source_id)
        self._delete_managed_source_files(manifest)
        self._emit(
            "knowledge_source_removed",
            source_id=source_id,
            mode=manifest.mount_mode,
            status="removed",
            message="Knowledge source removed.",
        )
        return True

    def _semantic_search(self, *, query: str, source_id: str | None, limit: int) -> list[KnowledgeResult]:
        namespace = self._namespace(source_id) if source_id else tuple([*self.config.rag_store.namespace_prefix, self.owner_type, self.owner_id])
        results = []
        for item in self.store.search(namespace, query=query, limit=limit):  # type: ignore[union-attr]
            value = item.value if isinstance(item.value, dict) else {}
            results.append(
                KnowledgeResult(
                    result_id=str(value.get("chunk_id") or item.key),
                    source_id=str(value.get("source_id") or ""),
                    document_id=value.get("document_id"),
                    chunk_id=value.get("chunk_id"),
                    title=str(value.get("title") or item.key),
                    content=str(value.get("content") or ""),
                    score=item.score,
                    uri=value.get("uri"),
                    metadata={"retrieval": "semantic", **dict(value.get("metadata") or {})},
                )
            )
        return results

    def _write_semantic_index(self, *, manifest: KnowledgeSourceManifest, chunks: list[Any]) -> int:
        self._require_semantic_index("rag")
        assert self.store is not None
        namespace = self._namespace(manifest.source_id)
        self._clear_semantic_namespace(namespace)
        embedded_count = 0
        try:
            for chunk in chunks:
                self.store.put(
                    namespace,
                    chunk.chunk_id,
                    {
                        "chunk_id": chunk.chunk_id,
                        "source_id": chunk.source_id,
                        "document_id": chunk.document_id,
                        "title": chunk.title,
                        "summary": chunk.summary or "",
                        "content": chunk.content,
                        "uri": chunk.metadata.get("relative_path") or chunk.metadata.get("file_name"),
                        "metadata": chunk.metadata,
                    },
                )
                self._raise_for_semantic_write_failure(chunk.chunk_id)
                embedded_count += 1
        except Exception:
            self._clear_semantic_namespace(namespace)
            raise
        return embedded_count

    def _require_semantic_index(self, mount_mode: MountMode) -> None:
        if mount_mode != "rag":
            return
        if self.store is None or not self.semantic_index_enabled:
            raise RuntimeError("RAG knowledge source requires an available embedding model and semantic vector store")

    def _clear_semantic_namespace(self, namespace: tuple[str, ...]) -> None:
        assert self.store is not None
        for item in self.store.search(namespace, limit=100000):
            self.store.delete(tuple(item.namespace), item.key)

    def _raise_for_semantic_write_failure(self, chunk_id: str) -> None:
        assert self.store is not None
        report_fn = getattr(self.store, "semantic_index_report", None)
        if not callable(report_fn):
            return
        diagnostics = list(report_fn().get("diagnostics") or [])
        diagnostic = next(
            (item for item in reversed(diagnostics) if str(item.get("key") or "") == chunk_id),
            None,
        )
        if diagnostic is None:
            raise RuntimeError(f"embedding result was not reported for chunk {chunk_id}")
        if diagnostic.get("status") == "ok":
            return
        reason = str(diagnostic.get("reason") or "embedding_failed")
        message = str(diagnostic.get("message") or reason)
        raise RuntimeError(f"embedding failed for chunk {chunk_id}: {message}")

    def _write_report(
        self,
        *,
        job: KnowledgeIngestionJob,
        manifest: KnowledgeSourceManifest,
        documents: list[KnowledgeDocument],
        chunks: list[Any],
        warnings: list[str],
    ) -> Path:
        report_root = self.root / "ingestion_jobs"
        report_root.mkdir(parents=True, exist_ok=True)
        report_path = report_root / f"{job.job_id}.json"
        report = {
            "version": "knowledge_ingestion_report.v0",
            "job_id": job.job_id,
            "source_id": manifest.source_id,
            "source_type": manifest.source_type,
            "mode": manifest.mount_mode,
            "status": "completed",
            "document_count": len(documents),
            "chunk_count": len(chunks),
            "warnings": warnings,
            "ingestion_plan": manifest.metadata.get("ingestion_plan"),
            "created_at": now_iso(),
        }
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return report_path

    def _delete_managed_source_files(self, manifest: KnowledgeSourceManifest) -> None:
        uri = Path(manifest.uri)
        try:
            uri.resolve().relative_to((self.root / "sources").resolve())
        except Exception:
            return
        if uri.is_dir():
            shutil.rmtree(uri)
        elif uri.is_file():
            uri.unlink()

    def _namespace(self, source_id: str) -> tuple[str, ...]:
        return tuple([*self.config.rag_store.namespace_prefix, self.owner_type, self.owner_id, source_id])

    def _require_source(self, source_id: str) -> KnowledgeSourceManifest:
        source = self.catalog.get_source(source_id)
        if source is None:
            raise ValueError(f"knowledge source not found: {source_id}")
        return source

    def _normalize_source_spec(
        self,
        source: dict[str, Any],
    ) -> tuple[SourceType, MountMode, str, str, str, dict[str, Any]]:
        source_type = str(source.get("source_type") or "filesystem")
        mount_mode = str(source.get("mount_mode") or source.get("mode") or self.config.default_mount_mode)
        uri = str(source.get("uri") or source.get("path") or source.get("url") or "").strip()
        metadata = dict(source.get("metadata") or {})
        if not uri and source_type == "manual_note":
            uri = str(metadata.get("content") or source.get("content") or "")
            metadata.setdefault("content", uri)
        if not uri:
            raise ValueError("knowledge source requires uri/path/url")
        source_id = str(source.get("source_id") or stable_source_id(uri)).strip()
        display_name = str(source.get("display_name") or metadata.get("display_name") or source_id).strip()
        if source_type not in _SOURCE_TYPES:
            raise ValueError(f"unsupported knowledge source_type: {source_type}")
        if mount_mode not in {"index_only", "rag"}:
            raise ValueError(f"unsupported knowledge mount_mode: {mount_mode}")
        return source_type, mount_mode, uri, source_id, display_name, metadata  # type: ignore[return-value]

    def _emit(
        self,
        event_type: str,
        *,
        source_id: str | None = None,
        job_id: str | None = None,
        mode: str | None = None,
        phase: str | None = None,
        status: str | None = None,
        progress: dict[str, Any] | None = None,
        counts: dict[str, Any] | None = None,
        message: str | None = None,
        error: dict[str, Any] | None = None,
        report_path: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        emit_knowledge_event(
            event_sink=self.event_sink,
            **knowledge_event_payload(
                event_type=event_type,
                owner_type=self.owner_type,
                owner_id=self.owner_id,
                source_id=source_id,
                job_id=job_id,
                mode=mode,
                phase=phase,
                status=status,
                progress=progress,
                counts=counts,
                message=message,
                error=error,
                report_path=report_path,
                payload=payload,
            ),
        )

    def _emit_job(
        self,
        event_type: str,
        job: KnowledgeIngestionJob,
        *,
        progress: dict[str, Any] | None = None,
        counts: dict[str, Any] | None = None,
        message: str | None = None,
        error: dict[str, Any] | None = None,
    ) -> None:
        self._emit(
            event_type,
            source_id=job.source_id,
            job_id=job.job_id,
            mode=job.mode,
            phase=job.phase,
            status=job.status,
            progress=progress,
            counts=counts or job.counts,
            message=message,
            error=error,
            report_path=job.report_path,
        )


class KnowledgeIngestionWorker:
    def __init__(self, runtime: KnowledgeRuntime) -> None:
        self.runtime = runtime
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name=f"knowledge-ingestion-{self.runtime.owner_id}", daemon=True)
        self._thread.start()

    def shutdown(self) -> None:
        self._stop.set()
        with self.runtime._queue_condition:
            self.runtime._queue_condition.notify_all()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def _run(self) -> None:
        while not self._stop.is_set():
            job_id = self.runtime.next_job(timeout=0.5)
            if not job_id:
                continue
            self.runtime.run_job(job_id)


def _planned_phases(mode: MountMode) -> list[str]:
    phases = ["discover", "load", "normalize", "chunk", "index", "finalize"]
    if mode == "rag":
        phases.insert(4, "embed")
    return phases


def _capabilities_for(*, source_type: SourceType, mount_mode: MountMode) -> list[str]:
    capabilities = ["list_documents", "read_document", "keyword_search"]
    if mount_mode == "rag":
        capabilities.extend(["semantic_search", "hybrid_search"])
    if source_type in {"mcp", "database"}:
        capabilities.append("managed_retriever")
    return capabilities


def _source_hash(*, uri: str, metadata: dict[str, Any]) -> str:
    return json_hash({"uri": uri, "metadata": metadata})


def _dedupe_results(results: list[KnowledgeResult]) -> list[KnowledgeResult]:
    seen: set[str] = set()
    output: list[KnowledgeResult] = []
    for item in sorted(results, key=lambda result: result.score or 0.0, reverse=True):
        key = item.chunk_id or item.document_id or item.result_id
        if key in seen:
            continue
        seen.add(key)
        output.append(item)
    return output


def _ingestion_plan_from_source(source: dict[str, Any], metadata: dict[str, Any]) -> KnowledgeIngestionPlan | None:
    raw = source.get("ingestion_plan") or metadata.get("ingestion_plan")
    if raw is None:
        return None
    if isinstance(raw, KnowledgeIngestionPlan):
        return raw
    return KnowledgeIngestionPlan.model_validate(raw)


def _ingestion_plan_from_manifest(manifest: KnowledgeSourceManifest) -> KnowledgeIngestionPlan | None:
    raw = manifest.metadata.get("ingestion_plan")
    if raw is None:
        return None
    return KnowledgeIngestionPlan.model_validate(raw)


_SOURCE_TYPES = {
    "filesystem",
    "codebase",
    "web_snapshot",
    "database",
    "mcp",
    "skill",
    "artifact_report",
    "manual_note",
}
