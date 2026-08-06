from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA = "ProofLaunchProductionRequestTraceV1"
STATUS_SCHEMA = "ProofLaunchProductionTraceStatusV1"
POLICY_VERSION = "prooflaunch-production-trace-retention-2026-08-02.v1"
_GENESIS_HASH = "0" * 64
_METHODS = frozenset({"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"})
_METHOD_PATTERN = re.compile(r"^[A-Z]{3,16}$")


def _canonical(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


class ProductionTraceLedger:
    """Content-free, restart-verifiable request traces with a 30–90 day contract."""

    def __init__(self, root: Path, *, retention_days: int = 90) -> None:
        if not isinstance(root, Path) or not root.is_absolute():
            raise ValueError("production trace root must be an absolute pathlib.Path")
        if type(retention_days) is not int or not 30 <= retention_days <= 90:
            raise ValueError("production trace retention_days must be in [30, 90]")
        if root.is_symlink() or (root.exists() and not root.is_dir()):
            raise ValueError("production trace root must be a real directory")
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        root.chmod(0o700)
        self.root = root.resolve(strict=True)
        self.path = self.root / "request-traces.jsonl"
        if self.path.is_symlink() or (self.path.exists() and not self.path.is_file()):
            raise ValueError("production trace path must be a regular file")
        if not self.path.exists():
            descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(descriptor)
        self.path.chmod(0o600)
        self.retention_days = retention_days
        self._lock = threading.Lock()
        self._events = self._load_verified()

    def _load_verified(self) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        previous = _GENESIS_HASH
        for line_number, line in enumerate(
            self.path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            try:
                event = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(
                    f"production trace line {line_number} is invalid JSON"
                ) from error
            if not isinstance(event, dict) or event.get("schema") != SCHEMA:
                raise ValueError("production trace schema is invalid")
            supplied = event.get("event_hash")
            unsigned = dict(event)
            unsigned.pop("event_hash", None)
            if event.get("sequence") != line_number:
                raise ValueError("production trace sequence drifted")
            if event.get("previous_hash") != previous or supplied != _digest(unsigned):
                raise ValueError("production trace hash chain is invalid")
            if event.get("raw_content_retained") is not False:
                raise ValueError("production trace retained raw content")
            if event.get("retention_days") != self.retention_days:
                raise ValueError("production trace retention contract drifted")
            previous = str(supplied)
            events.append(event)
        return events

    def append(
        self,
        *,
        method: str,
        route: str,
        status_code: int,
        duration_ms: float,
        request_bytes: int,
        response_bytes: int,
        tenant_id: str | None,
        trace_id: str,
        exception_observed: bool,
    ) -> dict[str, Any]:
        if not isinstance(method, str) or not _METHOD_PATTERN.fullmatch(method):
            raise ValueError("production trace method is invalid")
        if not isinstance(route, str) or not route.startswith("/") or len(route) > 512:
            raise ValueError("production trace route is invalid")
        if type(status_code) is not int or not 0 <= status_code <= 599:
            raise ValueError("production trace status code is invalid")
        if not isinstance(duration_ms, (int, float)) or duration_ms < 0:
            raise ValueError("production trace duration is invalid")
        for value, label in (
            (request_bytes, "request_bytes"),
            (response_bytes, "response_bytes"),
        ):
            if type(value) is not int or value < 0:
                raise ValueError(f"production trace {label} is invalid")
        if not isinstance(trace_id, str) or not 16 <= len(trace_id) <= 128:
            raise ValueError("production trace identity is invalid")
        if type(exception_observed) is not bool:
            raise ValueError("production trace exception flag is invalid")

        with self._lock:
            previous = self._events[-1]["event_hash"] if self._events else _GENESIS_HASH
            event: dict[str, Any] = {
                "schema": SCHEMA,
                "policy_version": POLICY_VERSION,
                "sequence": len(self._events) + 1,
                "occurred_at": _utc_now(),
                "retention_days": self.retention_days,
                "trace_id_sha256": _hash_text(trace_id),
                "tenant_principal_sha256": (
                    _hash_text(tenant_id) if tenant_id is not None else None
                ),
                "method": method,
                "route": route,
                "status_code": status_code,
                "duration_ms": round(float(duration_ms), 3),
                "request_bytes": request_bytes,
                "response_bytes": response_bytes,
                "exception_observed": exception_observed,
                "raw_content_retained": False,
                "previous_hash": previous,
            }
            event["event_hash"] = _digest(event)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(_canonical(event) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            self._events.append(event)
            return dict(event)

    def status(self, *, tenant_id: str | None = None) -> dict[str, Any]:
        with self._lock:
            tenant_digest = _hash_text(tenant_id) if tenant_id is not None else None
            selected = [
                event
                for event in self._events
                if tenant_digest is None
                or event.get("tenant_principal_sha256") == tenant_digest
            ]
            return {
                "schema": STATUS_SCHEMA,
                "policy_version": POLICY_VERSION,
                "retention_days": self.retention_days,
                "request_trace_count": len(selected),
                "exception_trace_count": sum(
                    bool(event["exception_observed"]) for event in selected
                ),
                "method_counts": {
                    method: sum(event["method"] == method for event in selected)
                    for method in sorted(_METHODS)
                }
                | {
                    "OTHER": sum(event["method"] not in _METHODS for event in selected)
                },
                "status_class_counts": {
                    f"{hundreds}xx": sum(
                        int(event["status_code"]) // 100 == hundreds
                        for event in selected
                    )
                    for hundreds in range(0, 6)
                },
                "hash_chain_valid": True,
                "latest_event_hash": (
                    selected[-1]["event_hash"] if selected else _GENESIS_HASH
                ),
                "raw_content_retained": False,
                "valid_request_boundary_instrumented": True,
                "production_deployment_observed": False,
            }


__all__ = [
    "POLICY_VERSION",
    "ProductionTraceLedger",
    "SCHEMA",
    "STATUS_SCHEMA",
]
