"""Persistent cross-platform ONLINE/INDEXING/TRAINING state machine."""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from enum import StrEnum
from importlib import import_module
from pathlib import Path
from typing import Literal

import orjson
from pydantic import Field

from buildguard.config import RuntimeModeConfig
from buildguard.logging_system.jsonl_writer import atomic_write_json
from buildguard.schemas.common import StrictSchema
from buildguard.utils.time import utc_now


class RuntimeMode(StrEnum):
    ONLINE = "online"
    INDEXING = "indexing"
    TRAINING = "training"


class RuntimeModeState(StrictSchema):
    mode: RuntimeMode = RuntimeMode.ONLINE
    entered_at: str
    changed_by_pid: int = Field(ge=1)
    generation: int = Field(default=0, ge=0)
    recovered: bool = False
    task_priority: int = Field(ge=1)


class RuntimeModeConflict(RuntimeError):
    """A mutually exclusive mode is already active."""


@contextmanager
def _file_lock(path: Path, timeout: float) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = path.open("a+b")
    try:
        if path.stat().st_size == 0:
            stream.write(b"\0")
            stream.flush()
        started = time.monotonic()
        while True:
            try:
                if os.name == "nt":
                    import msvcrt

                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    fcntl = import_module("fcntl")
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() - started >= timeout:
                    raise TimeoutError(f"Runtime mode lock timed out: {path}")
                time.sleep(0.05)
        yield
    finally:
        try:
            if os.name == "nt":
                import msvcrt

                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl = import_module("fcntl")
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        finally:
            stream.close()


class RuntimeModeManager:
    def __init__(self, config: RuntimeModeConfig, workspace: Path) -> None:
        root = workspace.resolve()
        self.config = config
        self.state_path = self._inside(config.state_path, root)
        self.lock_path = self._inside(config.lock_path, root)
        self.audit_path = self._inside(config.audit_path, root)

    @staticmethod
    def _inside(path: Path, workspace: Path) -> Path:
        if path.is_absolute():
            candidate = path.resolve()
        elif path.parts and path.parts[0] in {"workspace", workspace.name}:
            candidate = workspace.joinpath(*path.parts[1:]).resolve()
        else:
            candidate = (workspace / path).resolve()
        try:
            candidate.relative_to(workspace)
        except ValueError as exc:
            raise ValueError(f"Runtime mode path must remain in workspace: {path}") from exc
        return candidate

    def _default(self, *, recovered: bool = False, generation: int = 0) -> RuntimeModeState:
        return RuntimeModeState(
            mode=RuntimeMode.ONLINE,
            entered_at=utc_now().isoformat(),
            changed_by_pid=os.getpid(),
            generation=generation,
            recovered=recovered,
            task_priority=self.config.task_priorities["online"],
        )

    def _read(self) -> RuntimeModeState:
        if not self.state_path.is_file():
            state = self._default()
            atomic_write_json(self.state_path, state.model_dump(mode="json"))
            return state
        try:
            return RuntimeModeState.model_validate(
                orjson.loads(self.state_path.read_bytes())
            )
        except (OSError, orjson.JSONDecodeError, ValueError):
            corrupt = self.state_path.with_name(
                f"{self.state_path.name}.corrupt-{time.time_ns()}"
            )
            self.state_path.replace(corrupt)
            state = self._default(recovered=True)
            atomic_write_json(self.state_path, state.model_dump(mode="json"))
            self._audit("recover", None, state)
            return state

    def _audit(
        self,
        action: Literal["enter", "leave", "recover"],
        previous: RuntimeModeState | None,
        current: RuntimeModeState,
    ) -> None:
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "timestamp": utc_now().isoformat(),
            "action": action,
            "pid": os.getpid(),
            "previous_mode": previous.mode.value if previous else None,
            "current_mode": current.mode.value,
            "generation": current.generation,
            "recovered": current.recovered,
        }
        with self.audit_path.open("ab") as stream:
            stream.write(orjson.dumps(record) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())

    def status(self) -> RuntimeModeState:
        with _file_lock(self.lock_path, self.config.lock_timeout_seconds):
            return self._read()

    def enter(self, mode: RuntimeMode) -> RuntimeModeState:
        with _file_lock(self.lock_path, self.config.lock_timeout_seconds):
            previous = self._read()
            if previous.mode == mode:
                return previous
            if previous.mode != RuntimeMode.ONLINE:
                raise RuntimeModeConflict(
                    f"Cannot enter {mode.value}; {previous.mode.value} is active. "
                    "Run runtime-mode leave first."
                )
            current = RuntimeModeState(
                mode=mode,
                entered_at=utc_now().isoformat(),
                changed_by_pid=os.getpid(),
                generation=previous.generation + 1,
                task_priority=self.config.task_priorities[mode.value],
            )
            atomic_write_json(self.state_path, current.model_dump(mode="json"))
            self._audit("enter", previous, current)
            return current

    def leave(self) -> RuntimeModeState:
        with _file_lock(self.lock_path, self.config.lock_timeout_seconds):
            previous = self._read()
            if previous.mode == RuntimeMode.ONLINE:
                return previous
            current = self._default(generation=previous.generation + 1)
            atomic_write_json(self.state_path, current.model_dump(mode="json"))
            self._audit("leave", previous, current)
            return current
