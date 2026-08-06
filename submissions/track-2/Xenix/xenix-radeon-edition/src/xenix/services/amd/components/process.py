"""Fenced POSIX process supervision for one AMD target component.

Only a process launched through this module can be reaped.  Signalling happens
only after the current Linux ``/proc`` observation still matches the recorded
owner, boot/start identity, dedicated session/process group, and argv
fingerprint.  A mismatch is a refusal, never a PID-only fallback.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
import signal
import subprocess
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Final

from .auth import read_bearer_token_handoff
from .errors import (
    ManagedProcessError,
    ManagedProcessFenceError,
    ManagedProcessLaunchError,
    ManagedProcessPlatformError,
    ManagedProcessReapError,
    ManagedProcessSpecError,
)


_COMMAND_FINGERPRINT_PATTERN: Final = re.compile(r"[0-9a-f]{64}\Z")
_ENVIRONMENT_NAME_PATTERN: Final = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,127}\Z")
_SENSITIVE_ENVIRONMENT_NAME: Final = re.compile(
    r"(?:api[-_]?key|authorization|bearer|credential|password|private[-_]?key|secret|token)",
    re.IGNORECASE,
)
_BOOT_ID_PATTERN: Final = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z")
_POLL_INTERVAL_SECONDS: Final = 0.05
_NON_LIVE_PROC_STATES: Final = {b"Z", b"X"}


class ManagedProcessState(StrEnum):
    """A deliberately redacted state projection for a managed process."""

    RUNNING = "running"
    EXITED = "exited"
    FENCE_REJECTED = "fence_rejected"


@dataclass(frozen=True, slots=True)
class ProcessStartIdentity:
    """Linux boot and start-time identity that prevents PID-reuse confusion."""

    boot_id: str = field(repr=False)
    start_ticks: int = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.boot_id, str) or not _BOOT_ID_PATTERN.fullmatch(self.boot_id):
            raise ManagedProcessFenceError()
        if not isinstance(self.start_ticks, int) or isinstance(self.start_ticks, bool) or self.start_ticks < 0:
            raise ManagedProcessFenceError()

    def __repr__(self) -> str:
        return "ProcessStartIdentity(<redacted>)"


@dataclass(frozen=True, slots=True)
class ManagedProcessIdentity:
    """The exact observation required before signalling a managed process group."""

    pid: int = field(repr=False)
    start_identity: ProcessStartIdentity = field(repr=False)
    process_group_id: int = field(repr=False)
    session_id: int = field(repr=False)
    owner_uid: int = field(repr=False)
    command_fingerprint: str = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.start_identity, ProcessStartIdentity):
            raise ManagedProcessFenceError()
        for value in (self.pid, self.process_group_id, self.session_id, self.owner_uid):
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ManagedProcessFenceError()
        if self.pid <= 0 or self.process_group_id != self.pid or self.session_id != self.pid:
            raise ManagedProcessFenceError()
        if not isinstance(self.command_fingerprint, str) or not _COMMAND_FINGERPRINT_PATTERN.fullmatch(
            self.command_fingerprint
        ):
            raise ManagedProcessFenceError()

    def __repr__(self) -> str:
        return "ManagedProcessIdentity(<redacted>)"


@dataclass(frozen=True, slots=True)
class RedactedProcessStatus:
    """Status suitable for callers that must not receive live target details."""

    state: ManagedProcessState
    return_code: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.state, ManagedProcessState):
            raise ManagedProcessReapError()
        if self.return_code is not None and (
            not isinstance(self.return_code, int) or isinstance(self.return_code, bool)
        ):
            raise ManagedProcessReapError()


@dataclass(frozen=True, slots=True)
class ManagedProcessSpec:
    """An immutable launch contract that delivers the token only by file path.

    ``environment`` is a snapshot of public variables only.  The launcher does
    not inherit the controller environment, and it adds just the token-file path
    under ``token_file_environment_variable``.  Token text is rejected if it is
    found in argv or in a public environment value at launch time.
    """

    command: tuple[str, ...] = field(repr=False)
    cwd: Path = field(repr=False)
    token_file: Path = field(repr=False)
    environment: Mapping[str, str] = field(default_factory=dict, repr=False)
    token_file_environment_variable: str = "XENIX_RUNTIME_BEARER_TOKEN_FILE"

    def __post_init__(self) -> None:
        object.__setattr__(self, "command", _normalise_command(self.command))
        object.__setattr__(self, "cwd", _normalise_absolute_path(self.cwd))
        object.__setattr__(self, "token_file", _normalise_absolute_path(self.token_file))
        environment = _normalise_public_environment(self.environment)
        _validate_token_file_environment_variable(self.token_file_environment_variable, environment)
        object.__setattr__(self, "environment", MappingProxyType(environment))

    @property
    def command_fingerprint(self) -> str:
        return command_fingerprint(self.command)

    def launch(self) -> ManagedProcess:
        """Start this spec through the exact same fenced launch path as the function API."""

        return launch_managed_process(self)

    def __repr__(self) -> str:
        return "ManagedProcessSpec(<redacted>)"

    def __str__(self) -> str:
        return "<redacted managed process spec>"


@dataclass(frozen=True, slots=True)
class _ProcStat:
    state: bytes
    process_group_id: int
    session_id: int
    start_ticks: int


class _ProcMissingError(Exception):
    """A proc entry vanished between observations."""


class _ProcObservationError(Exception):
    """A proc entry exists but cannot be trusted for a fence."""


class ManagedProcess:
    """One local child plus its non-persistent exact identity record."""

    __slots__ = ("_process", "identity")

    def __init__(self, process: subprocess.Popen[bytes], identity: ManagedProcessIdentity) -> None:
        if process.pid != identity.pid:
            raise ManagedProcessFenceError()
        self._process = process
        self.identity = identity

    def status(self) -> RedactedProcessStatus:
        """Project current state without exposing a PID, command, path, or secret."""

        if self._process.returncode is not None:
            return RedactedProcessStatus(ManagedProcessState.EXITED, self._process.returncode)
        try:
            if _child_has_exited_without_reaping(self._process):
                return RedactedProcessStatus(ManagedProcessState.EXITED)
            verify_managed_process_fence(self.identity)
        except ManagedProcessError:
            return RedactedProcessStatus(ManagedProcessState.FENCE_REJECTED)
        return RedactedProcessStatus(ManagedProcessState.RUNNING)

    def reap(self, *, timeout_seconds: float | None = 0.0) -> RedactedProcessStatus:
        """Reap only after the direct child and its dedicated group are proven drained."""

        deadline = _deadline(timeout_seconds)
        if self._process.returncode is not None:
            return RedactedProcessStatus(ManagedProcessState.EXITED, self._process.returncode)

        while True:
            if _child_has_exited_without_reaping(self._process):
                if not _process_group_has_live_members(self.identity.process_group_id):
                    try:
                        return_code = self._process.wait(timeout=0)
                    except (OSError, subprocess.SubprocessError):
                        raise ManagedProcessReapError() from None
                    return RedactedProcessStatus(ManagedProcessState.EXITED, return_code)
            else:
                verify_managed_process_fence(self.identity)

            if _deadline_expired(deadline):
                raise ManagedProcessReapError()
            _sleep_until_next_observation(deadline)

    def terminate(
        self,
        *,
        timeout_seconds: float | None = 10.0,
        kill_after_timeout: bool = True,
    ) -> RedactedProcessStatus:
        """Terminate the isolated group only while its leader still passes its fence.

        If the leader has already exited while group members remain, this method
        refuses to send another signal: a bare historical group ID is not a safe
        authority to kill.
        """

        _deadline(timeout_seconds)
        if not isinstance(kill_after_timeout, bool):
            raise ManagedProcessSpecError()
        if self._process.returncode is not None or _child_has_exited_without_reaping(self._process):
            return self.reap(timeout_seconds=timeout_seconds)

        verify_managed_process_fence(self.identity)
        _signal_fenced_process_group(self.identity, signal.SIGTERM)
        try:
            return self.reap(timeout_seconds=timeout_seconds)
        except ManagedProcessReapError:
            if not kill_after_timeout or _child_has_exited_without_reaping(self._process):
                raise
            verify_managed_process_fence(self.identity)
            _signal_fenced_process_group(self.identity, signal.SIGKILL)
            return self.reap(timeout_seconds=timeout_seconds)

    def __repr__(self) -> str:
        return "ManagedProcess(<redacted>)"


def launch_managed_process(spec: ManagedProcessSpec) -> ManagedProcess:
    """Launch one session-leading POSIX child after protected-handoff validation."""

    if not isinstance(spec, ManagedProcessSpec):
        raise ManagedProcessSpecError()
    _require_posix_fencing()
    if not spec.cwd.is_dir():
        raise ManagedProcessSpecError()

    token = read_bearer_token_handoff(spec.token_file)
    _reject_token_material_in_public_launch_fields(spec, token.value)
    environment = dict(spec.environment)
    environment[spec.token_file_environment_variable] = os.fspath(spec.token_file)
    try:
        process = subprocess.Popen(
            spec.command,
            cwd=os.fspath(spec.cwd),
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            start_new_session=True,
        )
    except (OSError, TypeError, ValueError, subprocess.SubprocessError):
        raise ManagedProcessLaunchError() from None

    identity: ManagedProcessIdentity | None = None
    try:
        identity = _observe_managed_process_identity(process.pid)
        if identity.command_fingerprint != spec.command_fingerprint:
            raise ManagedProcessFenceError()
        return ManagedProcess(process, identity)
    except ManagedProcessError:
        if identity is not None and identity.command_fingerprint == spec.command_fingerprint:
            _best_effort_reap_verified_startup_child(process, identity)
        raise ManagedProcessLaunchError() from None


def verify_managed_process_fence(identity: ManagedProcessIdentity) -> None:
    """Require a live process to still be precisely the recorded managed child."""

    if not isinstance(identity, ManagedProcessIdentity):
        raise ManagedProcessFenceError()
    observed = _observe_managed_process_identity(identity.pid)
    if observed != identity:
        raise ManagedProcessFenceError()


def command_fingerprint(command: Sequence[str]) -> str:
    """Return a collision-resistant fingerprint of a literal argv sequence."""

    arguments = _normalise_command(command)
    encoded_arguments: list[bytes] = []
    try:
        encoded_arguments = [os.fsencode(argument) for argument in arguments]
    except (TypeError, UnicodeError):
        raise ManagedProcessSpecError() from None
    return _fingerprint_bytes(encoded_arguments)


def _normalise_command(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        raise ManagedProcessSpecError()
    try:
        command = tuple(value)  # type: ignore[arg-type]
    except TypeError:
        raise ManagedProcessSpecError() from None
    if not command:
        raise ManagedProcessSpecError()
    for argument in command:
        if (
            not isinstance(argument, str)
            or not argument
            or "\x00" in argument
            or len(argument) > 32_768
        ):
            raise ManagedProcessSpecError()
    return command


def _normalise_absolute_path(value: object) -> Path:
    try:
        path = Path(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise ManagedProcessSpecError() from None
    if not path.is_absolute():
        raise ManagedProcessSpecError()
    return path


def _normalise_public_environment(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise ManagedProcessSpecError()
    environment = dict(value)
    for name, item in environment.items():
        if (
            not isinstance(name, str)
            or not _ENVIRONMENT_NAME_PATTERN.fullmatch(name)
            or _SENSITIVE_ENVIRONMENT_NAME.search(name)
            or not isinstance(item, str)
            or "\x00" in item
        ):
            raise ManagedProcessSpecError()
    return dict(sorted(environment.items()))


def _validate_token_file_environment_variable(value: object, environment: Mapping[str, str]) -> None:
    if (
        not isinstance(value, str)
        or not _ENVIRONMENT_NAME_PATTERN.fullmatch(value)
        or value in environment
    ):
        raise ManagedProcessSpecError()


def _reject_token_material_in_public_launch_fields(spec: ManagedProcessSpec, token_value: str) -> None:
    if any(token_value in argument for argument in spec.command) or any(
        token_value in value for value in spec.environment.values()
    ):
        raise ManagedProcessSpecError()


def _require_posix_fencing() -> None:
    required_os_attributes = ("P_PID", "WEXITED", "WNOHANG", "WNOWAIT", "waitid", "geteuid")
    if os.name != "posix" or not all(hasattr(os, attribute) for attribute in required_os_attributes):
        raise ManagedProcessPlatformError()
    if not Path("/proc").is_dir():
        raise ManagedProcessPlatformError()


def _observe_managed_process_identity(pid: int) -> ManagedProcessIdentity:
    _require_posix_fencing()
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        raise ManagedProcessFenceError()
    try:
        first = _read_proc_stat(pid)
        if first.state in _NON_LIVE_PROC_STATES:
            raise ManagedProcessFenceError()
        owner_uid = os.stat(f"/proc/{pid}").st_uid
        command_value = _read_proc_command_fingerprint(pid)
        boot_id = _read_boot_id()
        second = _read_proc_stat(pid)
    except _ProcMissingError:
        raise ManagedProcessFenceError() from None
    except _ProcObservationError:
        raise ManagedProcessFenceError() from None
    except OSError:
        raise ManagedProcessFenceError() from None

    if (
        second.state in _NON_LIVE_PROC_STATES
        or first.start_ticks != second.start_ticks
        or first.process_group_id != second.process_group_id
        or first.session_id != second.session_id
        or owner_uid != os.geteuid()
    ):
        raise ManagedProcessFenceError()
    return ManagedProcessIdentity(
        pid=pid,
        start_identity=ProcessStartIdentity(boot_id=boot_id, start_ticks=second.start_ticks),
        process_group_id=second.process_group_id,
        session_id=second.session_id,
        owner_uid=owner_uid,
        command_fingerprint=command_value,
    )


def _read_proc_stat(pid: int) -> _ProcStat:
    payload = _read_proc_bytes(pid, "stat")
    closing = payload.rfind(b") ")
    if closing < 0:
        raise _ProcObservationError()
    fields = payload[closing + 2 :].split()
    if len(fields) <= 19:
        raise _ProcObservationError()
    try:
        state = fields[0]
        process_group_id = int(fields[2])
        session_id = int(fields[3])
        start_ticks = int(fields[19])
    except ValueError:
        raise _ProcObservationError() from None
    if not state or process_group_id <= 0 or session_id <= 0 or start_ticks < 0:
        raise _ProcObservationError()
    return _ProcStat(
        state=state,
        process_group_id=process_group_id,
        session_id=session_id,
        start_ticks=start_ticks,
    )


def _read_proc_command_fingerprint(pid: int) -> str:
    payload = _read_proc_bytes(pid, "cmdline")
    if not payload.endswith(b"\x00"):
        raise _ProcObservationError()
    arguments = payload[:-1].split(b"\x00")
    if not arguments or not arguments[0]:
        raise _ProcObservationError()
    return _fingerprint_bytes(arguments)


def _read_boot_id() -> str:
    try:
        payload = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip().lower()
    except (OSError, UnicodeError):
        raise _ProcObservationError() from None
    if not _BOOT_ID_PATTERN.fullmatch(payload):
        raise _ProcObservationError()
    return payload


def _read_proc_bytes(pid: int, entry: str) -> bytes:
    try:
        return Path(f"/proc/{pid}/{entry}").read_bytes()
    except (FileNotFoundError, ProcessLookupError):
        raise _ProcMissingError() from None
    except OSError:
        raise _ProcObservationError() from None


def _fingerprint_bytes(arguments: Sequence[bytes]) -> str:
    digest = hashlib.sha256()
    for argument in arguments:
        digest.update(len(argument).to_bytes(8, byteorder="big", signed=False))
        digest.update(argument)
    return digest.hexdigest()


def _child_has_exited_without_reaping(process: subprocess.Popen[bytes]) -> bool:
    _require_posix_fencing()
    if process.returncode is not None:
        return True
    try:
        result = os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
    except ChildProcessError:
        raise ManagedProcessReapError() from None
    except OSError:
        raise ManagedProcessReapError() from None
    return result is not None


def _process_group_has_live_members(process_group_id: int) -> bool:
    _require_posix_fencing()
    try:
        entries = os.scandir("/proc")
    except OSError:
        raise ManagedProcessReapError() from None
    try:
        for entry in entries:
            if not entry.name.isdecimal():
                continue
            try:
                observed = _read_proc_stat(int(entry.name))
            except _ProcMissingError:
                continue
            except _ProcObservationError:
                raise ManagedProcessReapError() from None
            if observed.process_group_id == process_group_id and observed.state not in _NON_LIVE_PROC_STATES:
                return True
    finally:
        entries.close()
    return False


def _signal_fenced_process_group(identity: ManagedProcessIdentity, sig: signal.Signals) -> None:
    verify_managed_process_fence(identity)
    try:
        os.killpg(identity.process_group_id, sig)
    except OSError:
        raise ManagedProcessFenceError() from None


def _best_effort_reap_verified_startup_child(
    process: subprocess.Popen[bytes],
    identity: ManagedProcessIdentity,
) -> None:
    try:
        ManagedProcess(process, identity).terminate(timeout_seconds=1.0)
    except ManagedProcessError:
        pass


def _deadline(timeout_seconds: float | None) -> float | None:
    if timeout_seconds is None:
        return None
    if (
        not isinstance(timeout_seconds, (int, float))
        or isinstance(timeout_seconds, bool)
        or not math.isfinite(timeout_seconds)
        or timeout_seconds < 0
    ):
        raise ManagedProcessSpecError()
    return time.monotonic() + float(timeout_seconds)


def _deadline_expired(deadline: float | None) -> bool:
    return deadline is not None and time.monotonic() >= deadline


def _sleep_until_next_observation(deadline: float | None) -> None:
    if deadline is None:
        time.sleep(_POLL_INTERVAL_SECONDS)
        return
    remaining = deadline - time.monotonic()
    if remaining > 0:
        time.sleep(min(_POLL_INTERVAL_SECONDS, remaining))


__all__ = [
    "ManagedProcess",
    "ManagedProcessIdentity",
    "ManagedProcessState",
    "ManagedProcessSpec",
    "ProcessStartIdentity",
    "RedactedProcessStatus",
    "command_fingerprint",
    "launch_managed_process",
    "verify_managed_process_fence",
]
