from __future__ import annotations

import json
import shutil
from pathlib import Path
from threading import RLock
from typing import Any

from agent_factory.trace_system.schema import (
    DEFAULT_TRACE_MANIFEST_FLUSH_RECORD_INTERVAL,
    TraceFactRecord,
    TraceManifest,
    TraceReferenceRecord,
    utc_now,
)


class JSONLTraceStore:
    """Filesystem-backed trace fact store.

    One trace owns one directory. The append-only JSONL files are the durable
    fact source; manifest.json is only a compact index for listing and UI entry.
    """

    def __init__(
        self,
        root: str | Path,
        *,
        manifest_flush_record_interval: int = DEFAULT_TRACE_MANIFEST_FLUSH_RECORD_INTERVAL,
    ) -> None:
        if manifest_flush_record_interval < 1:
            raise ValueError("manifest_flush_record_interval must be at least 1")
        self.root = Path(root)
        self.manifest_flush_record_interval = manifest_flush_record_interval
        self._lock = RLock()
        self._manifest_cache: dict[str, TraceManifest] = {}
        self._pending_manifest_records: dict[str, int] = {}
        self._reconciled_trace_ids: set[str] = set()

    def ensure_trace(
        self,
        *,
        trace_id: str,
        run_id: str | None = None,
        agent_id: str | None = None,
        session_id: str | None = None,
        package_id: str | None = None,
        producer_type: str | None = None,
    ) -> TraceManifest:
        with self._lock:
            manifest = self._current_manifest(trace_id)
            if manifest is None:
                manifest = TraceManifest(
                    trace_id=trace_id,
                    run_id=run_id,
                    agent_id=agent_id,
                    session_id=session_id,
                    package_id=package_id,
                    producer_type=producer_type,
                )
                self._cache_and_write_manifest(manifest)
                self._reconciled_trace_ids.add(trace_id)
                return manifest
            if trace_id not in self._reconciled_trace_ids:
                reconciled = self._reconcile_manifest_counters(manifest)
                counters_changed = reconciled.counters != manifest.counters
                manifest = reconciled
                self._manifest_cache[trace_id] = manifest
                self._reconciled_trace_ids.add(trace_id)
                if counters_changed:
                    self._cache_and_write_manifest(manifest)
            updates = {
                "run_id": run_id or manifest.run_id,
                "agent_id": agent_id or manifest.agent_id,
                "session_id": session_id or manifest.session_id,
                "package_id": package_id or manifest.package_id,
                "producer_type": producer_type or manifest.producer_type,
            }
            if manifest.status == "started":
                updates["status"] = "running"
            changed = any(getattr(manifest, key) != value for key, value in updates.items())
            if changed:
                manifest = manifest.model_copy(update={**updates, "updated_at": utc_now()})
                self._cache_and_write_manifest(manifest)
            else:
                self._manifest_cache[trace_id] = manifest
            return manifest

    def append_fact(self, record: TraceFactRecord) -> None:
        with self._lock:
            self._append_jsonl(record.trace_id, "trace.jsonl", record.model_dump(mode="json"))
            self._increment(record.trace_id, record.record_type)

    def append_reference(self, record: TraceReferenceRecord) -> None:
        with self._lock:
            self._append_jsonl(record.trace_id, "refs.jsonl", record.model_dump(mode="json"))
            self._increment(record.trace_id, "reference")

    def finish_trace(self, *, trace_id: str, status: str) -> None:
        with self._lock:
            manifest = self._current_manifest(trace_id)
            if manifest is None:
                return
            final_status = "failed" if status == "failed" else "completed"
            finished_at = utc_now()
            self._cache_and_write_manifest(
                manifest.model_copy(
                    update={"status": final_status, "finished_at": finished_at, "updated_at": finished_at}
                )
            )
            self._manifest_cache.pop(trace_id, None)
            self._pending_manifest_records.pop(trace_id, None)
            self._reconciled_trace_ids.discard(trace_id)

    def delete_trace(self, trace_id: str) -> None:
        with self._lock:
            trace_dir = self._trace_dir(trace_id)
            if trace_dir.exists():
                shutil.rmtree(trace_dir)
            self._manifest_cache.pop(trace_id, None)
            self._pending_manifest_records.pop(trace_id, None)
            self._reconciled_trace_ids.discard(trace_id)

    def manifest_for(self, trace_id: str) -> TraceManifest | None:
        with self._lock:
            return self._current_manifest(trace_id)

    def _increment(self, trace_id: str, key: str) -> None:
        manifest = self._current_manifest(trace_id)
        if manifest is None:
            return
        counters = dict(manifest.counters)
        counters[key] = int(counters.get(key, 0)) + 1
        updated = manifest.model_copy(
            update={
                "status": "running" if manifest.status == "started" else manifest.status,
                "updated_at": utc_now(),
                "counters": counters,
            }
        )
        self._manifest_cache[trace_id] = updated
        pending = self._pending_manifest_records.get(trace_id, 0) + 1
        self._pending_manifest_records[trace_id] = pending
        if pending >= self.manifest_flush_record_interval:
            self._cache_and_write_manifest(updated)

    def _current_manifest(self, trace_id: str) -> TraceManifest | None:
        cached = self._manifest_cache.get(trace_id)
        if cached is not None:
            return cached
        manifest = self._read_manifest(trace_id)
        if manifest is not None:
            self._manifest_cache[trace_id] = manifest
        return manifest

    def _cache_and_write_manifest(self, manifest: TraceManifest) -> None:
        self._manifest_cache[manifest.trace_id] = manifest
        self._write_manifest(manifest)
        self._pending_manifest_records[manifest.trace_id] = 0

    def _reconcile_manifest_counters(self, manifest: TraceManifest) -> TraceManifest:
        counters: dict[str, int] = {}
        trace_path = self._trace_dir(manifest.trace_id) / "trace.jsonl"
        if trace_path.is_file():
            with trace_path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    try:
                        payload = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    record_type = str(payload.get("record_type") or "").strip()
                    if record_type:
                        counters[record_type] = counters.get(record_type, 0) + 1
        refs_path = self._trace_dir(manifest.trace_id) / "refs.jsonl"
        if refs_path.is_file():
            with refs_path.open("r", encoding="utf-8") as handle:
                counters["reference"] = sum(1 for line in handle if line.strip())
        if counters == manifest.counters:
            return manifest
        return manifest.model_copy(update={"counters": counters, "updated_at": utc_now()})

    def _trace_dir(self, trace_id: str) -> Path:
        return self.root / "runs" / trace_id

    def _manifest_path(self, trace_id: str) -> Path:
        return self._trace_dir(trace_id) / "manifest.json"

    def _read_manifest(self, trace_id: str) -> TraceManifest | None:
        path = self._manifest_path(trace_id)
        if not path.is_file():
            return None
        return TraceManifest.model_validate_json(path.read_text(encoding="utf-8"))

    def _write_manifest(self, manifest: TraceManifest) -> None:
        path = self._manifest_path(manifest.trace_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(manifest.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )
        tmp.replace(path)

    def _append_jsonl(self, trace_id: str, filename: str, payload: dict[str, Any]) -> None:
        trace_dir = self._trace_dir(trace_id)
        trace_dir.mkdir(parents=True, exist_ok=True)
        with (trace_dir / filename).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str))
            handle.write("\n")
