"""
Unified corpus writer for all seven Determinex corpus types.
ONLY this module may append to corpus JSONL files on T:.
All writes are HMAC-signed, schema-versioned, and fsync'd.
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import json
import logging
import os
import tempfile
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agents.base_agent import (
    SCHEMA_VERSION,
    AgentTrace,
    CorpusType,
    OracleVerdict,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Immutability guard
# ---------------------------------------------------------------------------


class CorpusWriteBlockedError(RuntimeError):
    """Raised when a corpus write is attempted under DETERMINEX_NO_CORPUS_WRITE=1.

    Set this env var (or use :func:`read_only_context`) in any inspection,
    status, or doctor code path to guarantee those paths never mutate corpus.
    """


@contextlib.contextmanager
def read_only_context():
    """Context manager that blocks all corpus writes for the duration.

    Use this in any code path that should be read-only (doctor, status, validate).
    Any call to a write method inside this context raises CorpusWriteBlockedError.

    Example::

        with read_only_context():
            manager = CorpusManager()
            rows = manager.read_rows(...)  # OK
            manager.write_trace(...)       # raises CorpusWriteBlockedError
    """
    prev = os.environ.get("DETERMINEX_NO_CORPUS_WRITE", "")
    os.environ["DETERMINEX_NO_CORPUS_WRITE"] = "1"
    try:
        yield
    finally:
        if prev:
            os.environ["DETERMINEX_NO_CORPUS_WRITE"] = prev
        else:
            os.environ.pop("DETERMINEX_NO_CORPUS_WRITE", None)


def _assert_writes_allowed() -> None:
    """Raise CorpusWriteBlockedError if DETERMINEX_NO_CORPUS_WRITE is active."""
    if os.environ.get("DETERMINEX_NO_CORPUS_WRITE", "").strip().lower() in ("1", "true", "yes"):
        raise CorpusWriteBlockedError(
            "Corpus write blocked: DETERMINEX_NO_CORPUS_WRITE is set. "
            "Do not write corpus rows from read-only code paths (doctor, status, validate)."
        )


# ---------------------------------------------------------------------------
# T: drive root layout
# ---------------------------------------------------------------------------

_DEFAULT_ROOT = Path(os.environ.get("DETERMINEX_CORPUS_ROOT", "T:/determinex_corpus"))

_CORPUS_SUBDIRS = {
    CorpusType.CODE_VERDICT: "code_verdict",
    CorpusType.TERMINAL_TRACE: "terminal_trace",
    CorpusType.BROWSER_TRACE: "browser_trace",
    CorpusType.DESKTOP_TRACE: "desktop_trace",
    CorpusType.MOBILE_TRACE: "mobile_trace",
    CorpusType.VISUAL_REPAIR: "visual_repair",
    CorpusType.SAFETY_REFUSAL: "safety_refusal",
}

_AUDIT_SUBDIR = "audit"
_REJECTED_SUBDIR = "rejected"


# ---------------------------------------------------------------------------
# HMAC key management (mirrors determinex_safety.py approach)
# ---------------------------------------------------------------------------


def _read_dotenv_key() -> str:
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.is_file():
        return ""
    try:
        for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.startswith("DETERMINEX_CORPUS_HMAC_KEY="):
                return stripped.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        return ""
    return ""


def _configured_hmac_key() -> str:
    return os.environ.get("DETERMINEX_CORPUS_HMAC_KEY", "").strip() or _read_dotenv_key()


def hmac_key_scope() -> str:
    """Return durable if a valid configured key exists, else ephemeral."""
    raw = _configured_hmac_key()
    if not raw:
        return "ephemeral"
    try:
        key = bytes.fromhex(raw.strip())
    except ValueError:
        return "ephemeral"
    return "durable" if len(key) >= 32 else "ephemeral"


def _load_hmac_key() -> bytes:
    raw = _configured_hmac_key()
    if raw:
        try:
            key = bytes.fromhex(raw.strip())
            if len(key) >= 32:
                return key
            log.warning(
                "[corpus_manager] DETERMINEX_CORPUS_HMAC_KEY too short (%d bytes) — using ephemeral",
                len(key),
            )
        except ValueError:
            log.warning(
                "[corpus_manager] DETERMINEX_CORPUS_HMAC_KEY is not valid hex — using ephemeral"
            )
    # Ephemeral: in-process only, changes on restart
    if not hasattr(_load_hmac_key, "_ephemeral"):
        _load_hmac_key._ephemeral = os.urandom(32)  # type: ignore[attr-defined]
        log.warning(
            "[corpus_manager] No DETERMINEX_CORPUS_HMAC_KEY set — using ephemeral key. "
            "Set this in .env before running any training pipeline."
        )
    return _load_hmac_key._ephemeral  # type: ignore[attr-defined]


def _canonical_json(record: dict) -> bytes:
    """Sorted-key, ASCII-safe, NFC-normalized JSON for HMAC."""
    raw = json.dumps(record, sort_keys=True, ensure_ascii=True)
    return unicodedata.normalize("NFC", raw).encode()


def _sign_record(record: dict) -> str:
    """Compute BLAKE2b-256 HMAC over record without _sig field."""
    payload = {k: v for k, v in record.items() if k != "_sig"}
    return hmac.new(_load_hmac_key(), _canonical_json(payload), hashlib.blake2b).hexdigest()


def _verify_signature(record: dict) -> bool:
    sig = record.get("_sig", "")
    if not sig:
        return False
    expected = _sign_record(record)
    return hmac.compare_digest(expected, sig)


def verify_signature(record: dict) -> bool:
    """Non-mutating signature check for reports and audits."""
    return _verify_signature(record)


def resign_record(record: dict) -> dict:
    """Return a copy of record signed with the currently configured key."""
    updated = dict(record)
    updated["signature_key_scope"] = hmac_key_scope()
    updated["_sig"] = _sign_record(updated)
    return updated


# ---------------------------------------------------------------------------
# CorpusManager
# ---------------------------------------------------------------------------


class CorpusManager:
    """
    Single entry point for all corpus writes.

    Usage:
        cm = CorpusManager()
        cm.write_trace(trace, corpus_type=CorpusType.BROWSER_TRACE, benchmark="webarena")
        cm.write_refusal(task, action_dict, decision, layer="L5", category="covert_surveillance")
    """

    def __init__(self, root: Path | str | None = None) -> None:
        self.root = Path(root) if root else _DEFAULT_ROOT
        self._ensure_dirs()

    # ------------------------------------------------------------------
    # Directory setup
    # ------------------------------------------------------------------

    def _ensure_dirs(self) -> None:
        for subdir in _CORPUS_SUBDIRS.values():
            (self.root / subdir).mkdir(parents=True, exist_ok=True)
        (self.root / _AUDIT_SUBDIR).mkdir(parents=True, exist_ok=True)
        (self.root / _REJECTED_SUBDIR).mkdir(parents=True, exist_ok=True)

    def _corpus_path(self, corpus_type: CorpusType) -> Path:
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        return self.root / _CORPUS_SUBDIRS[corpus_type] / f"{today}.jsonl"

    def _audit_path(self) -> Path:
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        return self.root / _AUDIT_SUBDIR / f"{today}_audit.log"

    def _rejected_path(self) -> Path:
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        return self.root / _REJECTED_SUBDIR / f"{today}_rejected.jsonl"

    # ------------------------------------------------------------------
    # Core write primitive
    # ------------------------------------------------------------------

    def _normalize_record(
        self,
        corpus_type: CorpusType,
        task_id: str,
        input_hash: str,
        output_hash: str,
        source_benchmark: str,
        payload: dict[str, Any],
    ) -> dict:
        record: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "corpus_type": corpus_type.value,
            "timestamp": datetime.now(UTC).isoformat(),
            "source_benchmark": source_benchmark,
            "task_id": task_id,
            "input_hash": input_hash,
            "output_hash": output_hash,
            "signature_key_scope": hmac_key_scope(),
            **payload,
        }
        record["_sig"] = _sign_record(record)
        return record

    def _atomic_append(self, path: Path, record: dict) -> None:
        """Append a signed JSON line atomically with fsync."""
        line = json.dumps(record, ensure_ascii=True) + "\n"
        self._atomic_append_lines(path, [line])

    def _atomic_append_lines(self, path: Path, lines: list[str]) -> None:
        """Append signed JSON lines atomically with one read/fsync/replace cycle."""
        if not lines:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write to a temp file in the same directory then rename (atomic on POSIX)
        # On Windows, os.replace is atomic only within the same volume.
        fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            # Read existing content first
            existing = b""
            if path.exists():
                with open(path, "rb") as f:
                    existing = f.read()
            with os.fdopen(fd, "wb") as f:
                f.write(existing)
                for line in lines:
                    f.write(line.encode())
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def _write_record(self, corpus_type: CorpusType, record: dict) -> None:
        _assert_writes_allowed()
        path = self._corpus_path(corpus_type)
        try:
            self._atomic_append(path, record)
            log.debug(
                "[corpus] wrote %s record task_id=%s", corpus_type.value, record.get("task_id")
            )
        except Exception as exc:
            log.error("[corpus] WRITE FAILED for %s: %s", corpus_type.value, exc)
            self._write_audit(f"WRITE_FAILED corpus_type={corpus_type.value} error={exc}")
            raise

    def _write_records(self, corpus_type: CorpusType, records: list[dict]) -> None:
        """Batch append signed records. Used by high-volume benchmark ingests."""
        _assert_writes_allowed()
        if not records:
            return
        path = self._corpus_path(corpus_type)
        try:
            lines = [json.dumps(record, ensure_ascii=True) + "\n" for record in records]
            self._atomic_append_lines(path, lines)
            log.debug("[corpus] wrote %d %s records", len(records), corpus_type.value)
        except Exception as exc:
            log.error("[corpus] BATCH WRITE FAILED for %s: %s", corpus_type.value, exc)
            self._write_audit(
                f"BATCH_WRITE_FAILED corpus_type={corpus_type.value} count={len(records)} error={exc}"
            )
            raise

    def _write_audit(self, message: str) -> None:
        try:
            path = self._audit_path()
            ts = datetime.now(UTC).isoformat()
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(f"{ts} {message}\n")
        except Exception as exc:
            log.error("[corpus] audit write failed: %s", exc)

    def _write_rejected(self, record: dict, reason: str) -> None:
        try:
            path = self._rejected_path()
            rejected = {**record, "_rejection_reason": reason}
            self._atomic_append(path, rejected)
        except Exception as exc:
            log.error("[corpus] rejected-write failed: %s", exc)

    # ------------------------------------------------------------------
    # Verification
    # ------------------------------------------------------------------

    def verify(self, record: dict) -> bool:
        """Return True if HMAC signature is valid."""
        ok = _verify_signature(record)
        if not ok:
            self._write_rejected(record, "invalid_hmac_signature")
            self._write_audit(
                f"TAMPER_DETECTED task_id={record.get('task_id')} corpus_type={record.get('corpus_type')}"
            )
            log.error(
                "[corpus] TAMPER DETECTED — rejecting record task_id=%s", record.get("task_id")
            )
        return ok

    # ------------------------------------------------------------------
    # Public write methods
    # ------------------------------------------------------------------

    def write_trace(
        self,
        trace: AgentTrace,
        corpus_type: CorpusType,
        benchmark: str = "manual",
    ) -> None:
        """Write a completed agent trace to the appropriate corpus."""
        if trace.task_spec is None:
            raise ValueError("AgentTrace.task_spec must be set before writing to corpus")
        record = self._normalize_record(
            corpus_type=corpus_type,
            task_id=trace.task_spec.task_id,
            input_hash=trace.task_spec.input_hash(),
            output_hash=trace.output_hash(),
            source_benchmark=benchmark,
            payload=trace.to_dict(),
        )
        self._write_record(corpus_type, record)

    def write_code_verdict(
        self,
        task_id: str,
        lang: str,
        spec_text: str,
        patch: str,
        compile_result: str,
        compile_errors: list[str],
        test_result: str,
        test_errors: list[str],
        attempt: int,
        model_builder: str,
        benchmark: str = "programbench",
    ) -> None:
        """Compatibility entry for hive/pb_verdict_corpus pipeline."""
        input_hash = hashlib.sha256((spec_text + lang).encode()).hexdigest()
        output_hash = hashlib.sha256(patch.encode()).hexdigest()
        record = self._normalize_record(
            corpus_type=CorpusType.CODE_VERDICT,
            task_id=task_id,
            input_hash=input_hash,
            output_hash=output_hash,
            source_benchmark=benchmark,
            payload={
                "language": lang,
                "lang": lang,
                "spec_text": spec_text[:4096],
                "patch": patch,
                "compile_result": compile_result,
                "compile_errors": compile_errors,
                "test_result": test_result,
                "test_errors": test_errors,
                "failure_type": "none"
                if test_result == "pass" and compile_result == "pass"
                else "validator_failure",
                "validator": "programbench eval",
                "source_kind": "benchmark_verdict",
                "license_gate": "unknown",
                "safety_gate": "unknown",
                "supply_chain_gate": "unknown",
                "repair_outcome": test_result,
                "model_router": model_builder,
                "attempt": attempt,
                "model_builder": model_builder,
            },
        )
        self._write_record(CorpusType.CODE_VERDICT, record)

    def write_refusal(
        self,
        task_id: str,
        trigger: str,
        layer: str,
        category: str,
        violating_excerpt: str,
        safety_mode: str = "strict",
        action_type: str = "",
        benchmark: str = "manual",
    ) -> None:
        """Write a safety refusal to the safety_refusal corpus."""
        input_hash = hashlib.sha256(violating_excerpt.encode()).hexdigest()
        output_hash = hashlib.sha256(b"BLOCKED").hexdigest()
        record = self._normalize_record(
            corpus_type=CorpusType.SAFETY_REFUSAL,
            task_id=task_id,
            input_hash=input_hash,
            output_hash=output_hash,
            source_benchmark=benchmark,
            payload={
                "trigger": trigger,
                "layer": layer,
                "category": category,
                "violating_text_excerpt": violating_excerpt[:200],
                "safety_mode": safety_mode,
                "action_type": action_type,
                "blocked": True,
            },
        )
        self._write_record(CorpusType.SAFETY_REFUSAL, record)

    def write_visual_repair(
        self,
        task_id: str,
        before_hash: str,
        after_hash: str,
        diff_regions: list[dict],
        repair_patch: str,
        verdict: OracleVerdict,
        benchmark: str = "manual",
    ) -> None:
        input_hash = before_hash
        output_hash = after_hash
        record = self._normalize_record(
            corpus_type=CorpusType.VISUAL_REPAIR,
            task_id=task_id,
            input_hash=input_hash,
            output_hash=output_hash,
            source_benchmark=benchmark,
            payload={
                "before_screenshot_hash": before_hash,
                "after_screenshot_hash": after_hash,
                "diff_regions": diff_regions,
                "repair_patch": repair_patch,
                "oracle_verdict": verdict.to_dict(),
            },
        )
        self._write_record(CorpusType.VISUAL_REPAIR, record)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_manager: CorpusManager | None = None


def get_manager(root: Path | str | None = None) -> CorpusManager:
    global _manager
    if _manager is None:
        _manager = CorpusManager(root)
    return _manager
