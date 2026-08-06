from __future__ import annotations

from contextlib import AbstractContextManager
from pathlib import Path
import json
import sqlite3
from typing import Any

from agent_factory.knowledge_system.schema import (
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeIngestionJob,
    KnowledgeResult,
    KnowledgeSourceManifest,
    now_iso,
)
from agent_factory.sqlite_runtime import initialize_sqlite_store, sqlite_session


SQLITE_BUSY_TIMEOUT_MS = 10000


class KnowledgeCatalog:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        initialize_sqlite_store(
            self.path,
            self._init_schema,
            timeout_ms=SQLITE_BUSY_TIMEOUT_MS,
            wal=True,
        )

    def upsert_source(self, manifest: KnowledgeSourceManifest) -> None:
        manifest = manifest.model_copy(update={"updated_at": now_iso()})
        with self._connect() as conn:
            conn.execute(
                """
                insert into knowledge_sources(source_id, manifest_json, status, updated_at)
                values(?, ?, ?, ?)
                on conflict(source_id) do update set
                    manifest_json = excluded.manifest_json,
                    status = excluded.status,
                    updated_at = excluded.updated_at
                """,
                (
                    manifest.source_id,
                    manifest.model_dump_json(),
                    manifest.status,
                    manifest.updated_at,
                ),
            )
            conn.commit()

    def get_source(self, source_id: str) -> KnowledgeSourceManifest | None:
        with self._connect() as conn:
            row = conn.execute(
                "select manifest_json from knowledge_sources where source_id = ?",
                (source_id,),
            ).fetchone()
        if row is None:
            return None
        return KnowledgeSourceManifest.model_validate_json(row["manifest_json"])

    def list_sources(self) -> list[KnowledgeSourceManifest]:
        with self._connect() as conn:
            rows = conn.execute(
                "select manifest_json from knowledge_sources where status != 'removed' order by updated_at desc"
            ).fetchall()
        return [KnowledgeSourceManifest.model_validate_json(row["manifest_json"]) for row in rows]

    def set_source_status(self, source_id: str, status: str) -> None:
        manifest = self.get_source(source_id)
        if manifest is None:
            return
        self.upsert_source(manifest.model_copy(update={"status": status}))

    def replace_source_documents(
        self,
        *,
        source_id: str,
        documents: list[KnowledgeDocument],
        chunks: list[KnowledgeChunk],
    ) -> None:
        with self._connect() as conn:
            conn.execute("delete from knowledge_fts where source_id = ?", (source_id,))
            conn.execute("delete from knowledge_chunks where source_id = ?", (source_id,))
            conn.execute("delete from knowledge_documents where source_id = ?", (source_id,))
            for document in documents:
                conn.execute(
                    """
                    insert into knowledge_documents(document_id, source_id, title, uri, document_type, content_hash, metadata_json, created_at, updated_at)
                    values(?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        document.document_id,
                        document.source_id,
                        document.title,
                        document.uri,
                        document.document_type,
                        document.content_hash,
                        json.dumps(document.metadata, ensure_ascii=False, sort_keys=True),
                        document.created_at,
                        document.updated_at,
                    ),
                )
            for chunk in chunks:
                conn.execute(
                    """
                    insert into knowledge_chunks(chunk_id, source_id, document_id, title, content, content_hash, chunk_index, position_json, summary, metadata_json, created_at, updated_at)
                    values(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        chunk.chunk_id,
                        chunk.source_id,
                        chunk.document_id,
                        chunk.title,
                        chunk.content,
                        chunk.content_hash,
                        chunk.chunk_index,
                        json.dumps(chunk.position, ensure_ascii=False, sort_keys=True),
                        chunk.summary,
                        json.dumps(chunk.metadata, ensure_ascii=False, sort_keys=True),
                        chunk.created_at,
                        chunk.updated_at,
                    ),
                )
                conn.execute(
                    "insert into knowledge_fts(chunk_id, source_id, document_id, title, content) values(?, ?, ?, ?, ?)",
                    (chunk.chunk_id, chunk.source_id, chunk.document_id, chunk.title, chunk.content),
                )
            conn.commit()

    def list_documents(self, source_id: str | None = None) -> list[KnowledgeDocument]:
        sql = "select * from knowledge_documents"
        params: tuple[Any, ...] = ()
        if source_id:
            sql += " where source_id = ?"
            params = (source_id,)
        sql += " order by title"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_document_from_row(row) for row in rows]

    def get_document(self, document_id: str) -> KnowledgeDocument | None:
        with self._connect() as conn:
            row = conn.execute(
                "select * from knowledge_documents where document_id = ?",
                (document_id,),
            ).fetchone()
        return _document_from_row(row) if row is not None else None

    def get_chunk(self, chunk_id: str) -> KnowledgeChunk | None:
        with self._connect() as conn:
            row = conn.execute("select * from knowledge_chunks where chunk_id = ?", (chunk_id,)).fetchone()
        return _chunk_from_row(row) if row is not None else None

    def chunks_for_document(self, document_id: str) -> list[KnowledgeChunk]:
        with self._connect() as conn:
            rows = conn.execute(
                "select * from knowledge_chunks where document_id = ? order by chunk_index",
                (document_id,),
            ).fetchall()
        return [_chunk_from_row(row) for row in rows]

    def keyword_search(
        self,
        *,
        query: str,
        source_id: str | None = None,
        limit: int = 8,
    ) -> list[KnowledgeResult]:
        query = query.strip()
        if not query:
            return []
        params: list[Any] = [query]
        where_source = ""
        if source_id:
            where_source = " and source_id = ?"
            params.append(source_id)
        params.append(limit)
        results: list[KnowledgeResult] = []
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    f"""
                    select chunk_id, source_id, document_id, title, content, rank
                    from knowledge_fts
                    where knowledge_fts match ? {where_source}
                    order by rank
                    limit ?
                    """,
                    tuple(params),
                ).fetchall()
            results.extend(_result_from_fts_row(row) for row in rows)
        except sqlite3.OperationalError:
            results = []
        if len(results) < limit:
            results.extend(self._like_search(query=query, source_id=source_id, limit=limit))
        return _dedupe_results(results)[:limit]

    def upsert_job(self, job: KnowledgeIngestionJob) -> None:
        job = job.model_copy(update={"updated_at": now_iso()})
        with self._connect() as conn:
            conn.execute(
                """
                insert into knowledge_ingestion_jobs(job_id, source_id, job_json, status, updated_at)
                values(?, ?, ?, ?, ?)
                on conflict(job_id) do update set
                    job_json = excluded.job_json,
                    status = excluded.status,
                    updated_at = excluded.updated_at
                """,
                (job.job_id, job.source_id, job.model_dump_json(), job.status, job.updated_at),
            )
            conn.commit()

    def get_job(self, job_id: str) -> KnowledgeIngestionJob | None:
        with self._connect() as conn:
            row = conn.execute(
                "select job_json from knowledge_ingestion_jobs where job_id = ?",
                (job_id,),
            ).fetchone()
        if row is None:
            return None
        return KnowledgeIngestionJob.model_validate_json(row["job_json"])

    def delete_source(self, source_id: str) -> None:
        with self._connect() as conn:
            conn.execute("delete from knowledge_fts where source_id = ?", (source_id,))
            conn.execute("delete from knowledge_chunks where source_id = ?", (source_id,))
            conn.execute("delete from knowledge_documents where source_id = ?", (source_id,))
            conn.execute("delete from knowledge_sources where source_id = ?", (source_id,))
            conn.commit()

    def _like_search(self, *, query: str, source_id: str | None, limit: int) -> list[KnowledgeResult]:
        pattern = f"%{query}%"
        params: list[Any] = [pattern]
        where_source = ""
        if source_id:
            where_source = " and source_id = ?"
            params.append(source_id)
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                select chunk_id, source_id, document_id, title, content
                from knowledge_chunks
                where content like ? {where_source}
                order by updated_at desc
                limit ?
                """,
                tuple(params),
            ).fetchall()
        return [_result_from_chunk_row(row, score=0.5) for row in rows]

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                create table if not exists knowledge_sources(
                    source_id text primary key,
                    manifest_json text not null,
                    status text not null,
                    updated_at text not null
                )
                """
            )
            conn.execute(
                """
                create table if not exists knowledge_documents(
                    document_id text primary key,
                    source_id text not null,
                    title text not null,
                    uri text not null,
                    document_type text not null,
                    content_hash text not null,
                    metadata_json text not null,
                    created_at text not null,
                    updated_at text not null
                )
                """
            )
            conn.execute(
                """
                create table if not exists knowledge_chunks(
                    chunk_id text primary key,
                    source_id text not null,
                    document_id text not null,
                    title text not null,
                    content text not null,
                    content_hash text not null,
                    chunk_index integer not null,
                    position_json text not null,
                    summary text,
                    metadata_json text not null,
                    created_at text not null,
                    updated_at text not null
                )
                """
            )
            conn.execute(
                """
                create table if not exists knowledge_ingestion_jobs(
                    job_id text primary key,
                    source_id text not null,
                    job_json text not null,
                    status text not null,
                    updated_at text not null
                )
                """
            )
            conn.execute(
                """
                create virtual table if not exists knowledge_fts
                using fts5(chunk_id unindexed, source_id unindexed, document_id unindexed, title, content)
                """
            )
            conn.commit()

    def _connect(self) -> AbstractContextManager[sqlite3.Connection]:
        return sqlite_session(self.path, timeout_ms=SQLITE_BUSY_TIMEOUT_MS)


def _document_from_row(row: sqlite3.Row) -> KnowledgeDocument:
    return KnowledgeDocument(
        document_id=row["document_id"],
        source_id=row["source_id"],
        title=row["title"],
        uri=row["uri"],
        document_type=row["document_type"],
        content_hash=row["content_hash"],
        metadata=json.loads(row["metadata_json"] or "{}"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _chunk_from_row(row: sqlite3.Row) -> KnowledgeChunk:
    return KnowledgeChunk(
        chunk_id=row["chunk_id"],
        source_id=row["source_id"],
        document_id=row["document_id"],
        title=row["title"],
        content=row["content"],
        content_hash=row["content_hash"],
        chunk_index=int(row["chunk_index"]),
        position=json.loads(row["position_json"] or "{}"),
        summary=row["summary"],
        metadata=json.loads(row["metadata_json"] or "{}"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _result_from_fts_row(row: sqlite3.Row) -> KnowledgeResult:
    score = None
    try:
        score = max(0.0, 1.0 / (1.0 + abs(float(row["rank"]))))
    except Exception:
        pass
    return KnowledgeResult(
        result_id=row["chunk_id"],
        source_id=row["source_id"],
        document_id=row["document_id"],
        chunk_id=row["chunk_id"],
        title=row["title"],
        content=row["content"],
        score=score,
        metadata={"retrieval": "keyword"},
    )


def _result_from_chunk_row(row: sqlite3.Row, *, score: float | None) -> KnowledgeResult:
    return KnowledgeResult(
        result_id=row["chunk_id"],
        source_id=row["source_id"],
        document_id=row["document_id"],
        chunk_id=row["chunk_id"],
        title=row["title"],
        content=row["content"],
        score=score,
        metadata={"retrieval": "keyword_like"},
    )


def _dedupe_results(results: list[KnowledgeResult]) -> list[KnowledgeResult]:
    seen: set[str] = set()
    output: list[KnowledgeResult] = []
    for item in results:
        key = item.chunk_id or item.document_id or item.result_id
        if key in seen:
            continue
        seen.add(key)
        output.append(item)
    return output
