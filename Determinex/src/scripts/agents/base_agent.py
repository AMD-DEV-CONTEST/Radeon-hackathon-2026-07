"""
Root contract for all Determinex visual/browser/desktop/mobile agents.
Every controller, adapter, and test must import types from here only.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

SCHEMA_VERSION = "determinex-agent-trace-v1"


# ---------------------------------------------------------------------------
# Environment types
# ---------------------------------------------------------------------------


class EnvType(str, Enum):
    CODE = "code"
    TERMINAL = "terminal"
    VISION = "vision"
    BROWSER = "browser"
    DESKTOP = "desktop"
    MOBILE = "mobile"
    DOCUMENT = "document"
    SQL = "sql"
    SECURITY = "security"


# ---------------------------------------------------------------------------
# Action types
# ---------------------------------------------------------------------------


class ActionType(str, Enum):
    # Observation (read-only)
    READ_SCREEN = "READ_SCREEN"
    READ_DOM = "READ_DOM"
    READ_ACCESSIBILITY_TREE = "READ_ACCESSIBILITY_TREE"

    # Pointer / keyboard
    CLICK = "CLICK"
    TYPE = "TYPE"
    PRESS_KEY = "PRESS_KEY"
    SCROLL = "SCROLL"
    DRAG = "DRAG"

    # Touch (mobile)
    TAP = "TAP"
    SWIPE = "SWIPE"

    # System / window
    OPEN_APP = "OPEN_APP"
    SWITCH_WINDOW = "SWITCH_WINDOW"

    # Shell / code
    RUN_COMMAND = "RUN_COMMAND"
    EDIT_FILE = "EDIT_FILE"
    APPLY_PATCH = "APPLY_PATCH"

    # Data transfer (confirmation-required)
    UPLOAD_FILE = "UPLOAD_FILE"
    DOWNLOAD_FILE = "DOWNLOAD_FILE"

    # High-consequence (confirmation-required)
    SUBMIT_FORM = "SUBMIT_FORM"
    SEND_MESSAGE = "SEND_MESSAGE"
    INSTALL_SOFTWARE = "INSTALL_SOFTWARE"
    GRANT_PERMISSION = "GRANT_PERMISSION"
    ENTER_CREDENTIAL = "ENTER_CREDENTIAL"
    MAKE_PURCHASE = "MAKE_PURCHASE"
    DELETE_DATA = "DELETE_DATA"
    DEPLOY_OR_PUBLISH = "DEPLOY_OR_PUBLISH"


# ---------------------------------------------------------------------------
# Oracle types
# ---------------------------------------------------------------------------


class OracleType(str, Enum):
    COMPILER = "compiler"
    TEST = "test"
    TERMINAL = "terminal"
    BROWSER = "browser"
    VISUAL = "visual"
    DOM = "dom"
    ACCESSIBILITY = "accessibility"
    DESKTOP = "desktop"
    MOBILE = "mobile"
    SQL = "sql"
    SECURITY = "security"
    POLICY = "policy"
    HUMAN_CONFIRMATION = "human_confirmation"


# ---------------------------------------------------------------------------
# Corpus types
# ---------------------------------------------------------------------------


class CorpusType(str, Enum):
    CODE_VERDICT = "code_verdict"
    TERMINAL_TRACE = "terminal_trace"
    BROWSER_TRACE = "browser_trace"
    DESKTOP_TRACE = "desktop_trace"
    MOBILE_TRACE = "mobile_trace"
    VISUAL_REPAIR = "visual_repair"
    SAFETY_REFUSAL = "safety_refusal"


# ---------------------------------------------------------------------------
# Core data types
# ---------------------------------------------------------------------------


@dataclass
class VisualTaskSpec:
    task_id: str
    env_type: EnvType
    goal: str
    constraints: list[str] = field(default_factory=list)
    source_benchmark: str = "manual"
    max_steps: int = 30
    timeout_seconds: int = 300
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "env_type": self.env_type.value,
            "goal": self.goal,
            "constraints": self.constraints,
            "source_benchmark": self.source_benchmark,
            "max_steps": self.max_steps,
            "timeout_seconds": self.timeout_seconds,
            "metadata": self.metadata,
        }

    def input_hash(self) -> str:
        payload = json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=True)
        return hashlib.sha256(payload.encode()).hexdigest()


@dataclass
class AgentObservation:
    env_type: EnvType
    step: int
    screenshot_path: str | None = None
    screenshot_hash: str | None = None
    dom_snapshot: str | None = None
    dom_hash: str | None = None
    accessibility_tree: str | None = None
    accessibility_hash: str | None = None
    ocr_text: str | None = None
    url: str | None = None
    window_title: str | None = None
    activity: str | None = None
    stdout: str | None = None
    stderr: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v is not None}


@dataclass
class AgentAction:
    action_type: ActionType
    step: int
    target: str | None = None  # CSS selector, file path, app name, etc.
    payload: str | None = None  # text to type, command to run, patch content, etc.
    x: int | None = None  # screen coordinates
    y: int | None = None
    rationale: str = ""
    safety_decision: str = ""  # filled by safety_governor before execution
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict:
        d = {k: v for k, v in self.__dict__.items() if v is not None and v != ""}
        d["action_type"] = self.action_type.value
        return d


@dataclass
class ActionResult:
    action: AgentAction
    success: bool
    observation_after: AgentObservation | None = None
    error: str | None = None
    duration_ms: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "action": self.action.to_dict(),
            "success": self.success,
            "observation_after": self.observation_after.to_dict()
            if self.observation_after
            else None,
            "error": self.error,
            "duration_ms": self.duration_ms,
            "metadata": self.metadata,
        }


@dataclass
class OracleVerdict:
    oracle_type: OracleType
    passed: bool
    score: float = 0.0  # 0.0–1.0
    evidence: str = ""
    raw_output: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "oracle_type": self.oracle_type.value,
            "passed": self.passed,
            "score": self.score,
            "evidence": self.evidence,
            "raw_output": self.raw_output,
            "metadata": self.metadata,
        }


@dataclass
class AgentTrace:
    schema_version: str = SCHEMA_VERSION
    task_spec: VisualTaskSpec | None = None
    observations: list[AgentObservation] = field(default_factory=list)
    actions: list[AgentAction] = field(default_factory=list)
    results: list[ActionResult] = field(default_factory=list)
    verdicts: list[OracleVerdict] = field(default_factory=list)
    final_score: float = 0.0
    success: bool = False
    aborted: bool = False
    abort_reason: str = ""
    start_time: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    end_time: str = ""
    total_steps: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "task_spec": self.task_spec.to_dict() if self.task_spec else None,
            "observations": [o.to_dict() for o in self.observations],
            "actions": [a.to_dict() for a in self.actions],
            "results": [r.to_dict() for r in self.results],
            "verdicts": [v.to_dict() for v in self.verdicts],
            "final_score": self.final_score,
            "success": self.success,
            "aborted": self.aborted,
            "abort_reason": self.abort_reason,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "total_steps": self.total_steps,
            "metadata": self.metadata,
        }

    def output_hash(self) -> str:
        d = {
            "actions": [a.to_dict() for a in self.actions],
            "results": [r.to_dict() for r in self.results],
            "verdicts": [v.to_dict() for v in self.verdicts],
            "final_score": self.final_score,
            "success": self.success,
        }
        payload = json.dumps(d, sort_keys=True, ensure_ascii=True)
        return hashlib.sha256(payload.encode()).hexdigest()


@dataclass
class CorpusRecord:
    """Fully normalized, HMAC-ready training record. Created only by CorpusManager."""

    schema_version: str
    corpus_type: CorpusType
    timestamp: str
    source_benchmark: str
    task_id: str
    input_hash: str
    output_hash: str
    payload: dict[str, Any]  # corpus-type-specific fields
    _sig: str = ""  # BLAKE2b-256 HMAC, filled by CorpusManager.sign()

    def to_dict(self) -> dict:
        d = {
            "schema_version": self.schema_version,
            "corpus_type": self.corpus_type.value,
            "timestamp": self.timestamp,
            "source_benchmark": self.source_benchmark,
            "task_id": self.task_id,
            "input_hash": self.input_hash,
            "output_hash": self.output_hash,
            **self.payload,
        }
        if self._sig:
            d["_sig"] = self._sig
        return d
