from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

from agent_factory.trace_system.schema import (
    TraceFactQuery,
    TraceFactRecord,
    TraceManifest,
    TraceReferenceIndexItem,
    TraceReferenceRecord,
    TraceRunFilter,
)


class TraceReadError(ValueError):
    pass


class TraceReader:
    """Read-only access to JSONL trace facts.

    Reader does not classify or project records. It is intentionally a thin
    fact-access layer used by WebUI projections and repair diagnostics.
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def list_runs(self, filters: TraceRunFilter | dict[str, Any] | None = None) -> list[TraceManifest]:
        query = filters if isinstance(filters, TraceRunFilter) else TraceRunFilter.model_validate(filters or {})
        manifests = sorted(
            self._iter_manifests(),
            key=lambda item: item.updated_at,
            reverse=True,
        )
        result: list[TraceManifest] = []
        for manifest in manifests:
            if query.status and manifest.status not in set(query.status):
                continue
            if query.agent_id and manifest.agent_id != query.agent_id:
                continue
            if query.session_id and manifest.session_id != query.session_id:
                continue
            if query.package_id and manifest.package_id != query.package_id:
                continue
            if query.producer_type and manifest.producer_type != query.producer_type:
                continue
            result.append(manifest)
            if len(result) >= query.limit:
                break
        return result

    def get_manifest(self, trace_id: str) -> TraceManifest:
        path = self._manifest_path(_safe_trace_id(trace_id))
        if not path.is_file():
            raise TraceReadError(f"trace manifest not found: {trace_id}")
        return TraceManifest.model_validate_json(path.read_text(encoding="utf-8"))

    def iter_facts(
        self,
        trace_id: str,
        query: TraceFactQuery | dict[str, Any] | None = None,
    ) -> Iterator[TraceFactRecord]:
        safe_trace_id = _safe_trace_id(trace_id)
        fact_query = query if isinstance(query, TraceFactQuery) else TraceFactQuery.model_validate(query or {})
        count = 0
        for record in self._iter_jsonl(self._trace_path(safe_trace_id, "trace.jsonl"), TraceFactRecord):
            if not _matches_fact_query(record, fact_query):
                continue
            yield record
            count += 1
            if fact_query.limit is not None and count >= fact_query.limit:
                break

    def read_facts(
        self,
        trace_id: str,
        query: TraceFactQuery | dict[str, Any] | None = None,
    ) -> list[TraceFactRecord]:
        return list(self.iter_facts(trace_id, query))

    def read_refs(self, trace_id: str) -> list[TraceReferenceIndexItem]:
        safe_trace_id = _safe_trace_id(trace_id)
        return [
            TraceReferenceIndexItem(
                reference_id=record.reference_id,
                trace_id=record.trace_id,
                run_id=record.run_id,
                span_id=record.span_id,
                reference_type=record.reference_type,
                uri=record.uri,
                metadata=record.metadata,
                created_at=record.created_at,
            )
            for record in self._iter_jsonl(self._trace_path(safe_trace_id, "refs.jsonl"), TraceReferenceRecord)
        ]

    def _iter_manifests(self) -> Iterable[TraceManifest]:
        runs_root = self.root / "runs"
        if not runs_root.is_dir():
            return []
        manifests: list[TraceManifest] = []
        for path in runs_root.glob("*/manifest.json"):
            try:
                manifests.append(TraceManifest.model_validate_json(path.read_text(encoding="utf-8")))
            except Exception as exc:
                raise TraceReadError(f"invalid trace manifest: {path}: {type(exc).__name__}: {exc}") from exc
        return manifests

    def _manifest_path(self, trace_id: str) -> Path:
        return self.root / "runs" / trace_id / "manifest.json"

    def _trace_path(self, trace_id: str, filename: str) -> Path:
        return self.root / "runs" / trace_id / filename

    def _iter_jsonl(self, path: Path, model) -> Iterator[Any]:
        if not path.is_file():
            return
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                text = line.strip()
                if not text:
                    continue
                try:
                    payload = json.loads(text)
                    yield model.model_validate(payload)
                except Exception as exc:
                    raise TraceReadError(
                        f"invalid trace jsonl record: {path}:{line_number}: {type(exc).__name__}: {exc}"
                    ) from exc


def _matches_fact_query(record: TraceFactRecord, query: TraceFactQuery) -> bool:
    if query.record_types and record.record_type not in set(query.record_types):
        return False
    if query.event_types and record.event_type not in set(query.event_types):
        return False
    if query.node_id and record.node_id != query.node_id:
        return False
    if query.span_id and record.span_id != query.span_id:
        return False
    if query.status and record.status != query.status:
        return False
    return True


def _safe_trace_id(trace_id: str) -> str:
    value = str(trace_id).strip()
    if not value:
        raise TraceReadError("trace_id must not be empty")
    if value in {".", ".."} or "/" in value or "\\" in value:
        raise TraceReadError(f"invalid trace_id: {trace_id}")
    return value
