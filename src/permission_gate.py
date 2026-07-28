"""
Permission Gate: propose-only safety control and action audit log.

Enforces the core design principle: the agent NEVER writes to the user's
environment, driver, or repo without an explicit approval step.
"""

import json
import os
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Optional


class ActionType(str, Enum):
    READ_FILE = "read_file"
    READ_PROFILER = "read_profiler"
    READ_SMI = "read_rocm_smi"
    RUN_BENCHMARK = "run_benchmark"
    PROPOSE_DIFF = "propose_diff"
    SAVE_DIFF = "save_diff"


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    AUTO_ALLOWED = "auto_allowed"


@dataclass
class AuditEntry:
    timestamp: float
    action_type: str
    target: str
    status: str
    details: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class PermissionConfig:
    """Defines what the agent is allowed to do without explicit user approval."""

    # Paths the agent may read freely (supports glob-style prefix matching)
    auto_read_paths: list[str] = field(default_factory=lambda: [
        "corpus/",
        "cases/",
        "tests/",
    ])

    # Action types that are always permitted without asking
    auto_allowed_actions: list[str] = field(default_factory=lambda: [
        ActionType.READ_FILE,
        ActionType.READ_PROFILER,
        ActionType.READ_SMI,
        ActionType.RUN_BENCHMARK,
    ])

    # Action types that ALWAYS require explicit user confirmation
    require_confirmation_actions: list[str] = field(default_factory=lambda: [
        ActionType.SAVE_DIFF,
    ])

    # The agent may NEVER do any of these
    forbidden_actions: list[str] = field(default_factory=list)


class PermissionGate:
    """
    Enforces propose-only safety controls.

    The agent may read, profile, and benchmark freely.
    It may PROPOSE diffs freely (as text output).
    It may only SAVE diffs to disk after explicit user approval.
    It may NEVER mutate driver config, env vars, or user's source files directly.
    """

    def __init__(
        self,
        config: Optional[PermissionConfig] = None,
        audit_log_path: Optional[str] = None,
    ):
        self.config = config or PermissionConfig()
        self.audit_log_path = audit_log_path or "omnikernel_audit.jsonl"
        self._audit_log: list[AuditEntry] = []

    # ------------------------------------------------------------------
    # Permission checks
    # ------------------------------------------------------------------

    def can_read(self, path: str) -> bool:
        """Returns True if the agent is allowed to read the given path."""
        for allowed_prefix in self.config.auto_read_paths:
            if path.startswith(allowed_prefix) or Path(path).is_relative_to(Path(allowed_prefix)):
                return True
        # Default: allow reads (the agent is a diagnostics tool)
        return ActionType.READ_FILE in self.config.auto_allowed_actions

    def can_propose_diff(self) -> bool:
        """Proposing a diff (as text output) is always allowed."""
        return True

    def can_save_diff(self) -> bool:
        """
        Saving a diff to disk requires explicit approval.
        This method always returns False — the orchestrator must ask the user first,
        then call approve_action() before saving.
        """
        return False

    def requires_confirmation(self, action_type: ActionType) -> bool:
        return action_type in self.config.require_confirmation_actions

    def is_forbidden(self, action_type: ActionType) -> bool:
        return action_type in self.config.forbidden_actions

    # ------------------------------------------------------------------
    # Audit logging
    # ------------------------------------------------------------------

    def log_action(
        self,
        action_type: ActionType,
        target: str,
        status: ApprovalStatus,
        details: Optional[str] = None,
    ) -> AuditEntry:
        """Record every proposed action and its approval status."""
        entry = AuditEntry(
            timestamp=time.time(),
            action_type=action_type.value,
            target=target,
            status=status.value,
            details=details,
        )
        self._audit_log.append(entry)
        self._persist_entry(entry)
        return entry

    def get_audit_log(self) -> list[dict]:
        """Return full audit log as list of dicts."""
        return [e.to_dict() for e in self._audit_log]

    def get_pending_approvals(self) -> list[dict]:
        """Return all actions still awaiting approval."""
        return [
            e.to_dict()
            for e in self._audit_log
            if e.status == ApprovalStatus.PENDING.value
        ]

    # ------------------------------------------------------------------
    # Approval flow
    # ------------------------------------------------------------------

    def request_approval(self, action_type: ActionType, target: str, details: str) -> AuditEntry:
        """
        Log an action as PENDING approval.
        The orchestrator should surface this to the user and wait for confirmation.
        """
        entry = self.log_action(action_type, target, ApprovalStatus.PENDING, details)
        return entry

    def approve_action(self, entry: AuditEntry) -> None:
        """Mark a pending action as APPROVED."""
        entry.status = ApprovalStatus.APPROVED.value
        self._persist_entry(entry)

    def reject_action(self, entry: AuditEntry) -> None:
        """Mark a pending action as REJECTED."""
        entry.status = ApprovalStatus.REJECTED.value
        self._persist_entry(entry)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _persist_entry(self, entry: AuditEntry) -> None:
        """Append audit entry to the JSONL log file."""
        try:
            with open(self.audit_log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry.to_dict()) + "\n")
        except OSError:
            pass  # Non-fatal: audit log write failure shouldn't crash the agent

    def load_audit_log_from_disk(self) -> list[dict]:
        """Load and return all entries from the persisted audit log."""
        if not os.path.exists(self.audit_log_path):
            return []
        entries = []
        with open(self.audit_log_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))
        return entries
