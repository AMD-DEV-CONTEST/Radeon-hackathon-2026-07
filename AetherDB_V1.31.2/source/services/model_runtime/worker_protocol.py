"""Canonical JSONL IPC contract for isolated native model workers."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


PROTOCOL_VERSION = "1.0"
MAX_MESSAGE_BYTES = 16 * 1024 * 1024


class WorkerState(str, Enum):
    STOPPED = "STOPPED"
    COLD = "COLD"
    STARTING = "STARTING"
    READY = "READY"
    BUSY = "BUSY"
    DRAINING = "DRAINING"
    FAILED = "FAILED"


class WorkerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    protocol_version: Literal["1.0"]
    request_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    command: Literal[
        "health",
        "capabilities",
        "load",
        "unload",
        "probe",
        "infer",
        "cancel",
        "metrics",
        "shutdown",
    ]
    payload: dict[str, Any] = Field(default_factory=dict)


class WorkerError(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str = Field(min_length=1, max_length=96)
    message: str = Field(min_length=1, max_length=512)


class WorkerResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    protocol_version: Literal["1.0"] = PROTOCOL_VERSION
    request_id: str | None = None
    event: Literal["result", "error", "heartbeat"]
    ok: bool
    worker_id: str
    state: WorkerState
    data: dict[str, Any] = Field(default_factory=dict)
    error: WorkerError | None = None
