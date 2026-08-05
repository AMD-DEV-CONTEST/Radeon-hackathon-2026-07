"""
scripts/observability/event_schema.py — Canonical event type definitions.

Every pipeline step emits a structured JSON event. This module defines:
  - EventType enum — all event names, grouped by subsystem
  - DeterminexEvent dataclass — wire format for each event
  - to_json() — deterministic JSON serialization for log files

Why structured events? The compiler oracle is the ground truth for code quality.
Structured events make the factory transparent: a user (or downstream tooling)
can tail the event log and see exactly what the factory is doing at each stage —
no "black box" inference required.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class EventType(str, Enum):
    # Task lifecycle
    TASK_ACCEPTED = "task.accepted"
    TASK_DENIED = "task.denied"

    # Baseline verification
    BASELINE_STARTED = "baseline.started"
    BASELINE_COMPLETED = "baseline.completed"
    BASELINE_FAILED = "baseline.failed"

    # Mutation
    MUTATION_CREATED = "mutation.created"
    MUTATION_SKIPPED = "mutation.skipped"

    # Repair
    REPAIR_STARTED = "repair.started"
    REPAIR_COMPLETED = "repair.completed"
    REPAIR_FAILED = "repair.failed"

    # Verifier / oracle
    VERIFIER_STARTED = "verifier.started"
    VERIFIER_COMPLETED = "verifier.completed"
    VERIFIER_TIMEOUT = "verifier.timeout"

    # Corpus
    CORPUS_ROW_WRITTEN = "corpus.row_written"
    CORPUS_ROW_REJECTED = "corpus.row_rejected"
    CORPUS_SIGNED = "corpus.signed"
    CORPUS_SIGNATURE_FAILED = "corpus.signature_failed"

    # Cloak
    CLOAK_APPLIED = "cloak.applied"
    CLOAK_FAILED = "cloak.failed"
    CLOAK_AUDIT_LOGGED = "cloak.audit_logged"

    # Gates
    LICENSE_REJECTED = "gate.license_rejected"
    LICENSE_ACCEPTED = "gate.license_accepted"
    SUPPLY_CHAIN_REJECTED = "gate.supply_chain_rejected"
    SECRET_REJECTED = "gate.secret_rejected"

    # Action safety
    ACTION_ALLOWED = "action.allowed"
    ACTION_CONFIRMATION_REQUIRED = "action.confirmation_required"
    ACTION_BLOCKED = "action.blocked"

    # Hive / pipeline
    SESSION_STARTED = "session.started"
    SESSION_COMPLETED = "session.completed"
    DAG_GENERATED = "dag.generated"
    STEP_STARTED = "step.started"
    STEP_COMPLETED = "step.completed"
    STEP_FAILED = "step.failed"
    COMPILE_ERROR = "compile.error"
    COMPILE_PASS = "compile.pass"

    # Schema
    SCHEMA_VALIDATION_FAILED = "schema.validation_failed"
    SCHEMA_MIGRATION_APPLIED = "schema.migration_applied"


@dataclass
class DeterminexEvent:
    event_type: EventType
    trace_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    task_id: str = ""
    session_id: str = ""
    language: str = ""
    verifier: str = ""
    result: str = ""  # "pass" | "fail" | "timeout" | "skip"
    reason: str = ""
    duration_ms: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["event_type"] = self.event_type.value
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=True)
