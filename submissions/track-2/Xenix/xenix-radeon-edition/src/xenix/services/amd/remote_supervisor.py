"""Exact, application-owned supervision for one managed Linux target.

This module deliberately knows nothing about SSH, component recipes, provider
settings, or capability protocols.  Its transport accepts fixed POSIX shell
programs plus separately quoted arguments.  Process receipts are observations:
every signal and deletion is fenced again against live ``/proc`` identity.
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Protocol

from .placement import AmdPlacementError, AmdRuntimeKey, RuntimeIncarnation

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+-]{0,159}$")
_ENVIRONMENT_NAME = re.compile(r"^[A-Z_][A-Z0-9_]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_RECEIPT_VERSION = "xenix-runtime-v1"
_PROVISIONING_RECEIPT_VERSION = "xenix-provisioning-v1"
_AUTH_ENVIRONMENT_NAME = "XENIX_RUNTIME_BEARER_TOKEN_FILE"


class RemoteSupervisorError(AmdPlacementError):
    """A remote realization could not be supervised without weakening a fence."""


class UnsupportedRemoteTargetError(RemoteSupervisorError):
    """The target lacks a declared supervision prerequisite."""


class RemoteProcessConflictError(RemoteSupervisorError):
    """A different live owner or process already occupies the generation."""


class RemoteProcessIdentityError(RemoteSupervisorError):
    """A process receipt no longer proves the exact live process identity."""


class RemoteCleanupRefusedError(RemoteSupervisorError):
    """A target path could not be proven safe for the requested cleanup."""


@dataclass(frozen=True, slots=True)
class RemoteScriptResult:
    """Bounded internal result; callers must never surface raw target output."""

    return_code: int
    stdout: bytes = field(repr=False, default=b"")


class RemoteScriptRunner(Protocol):
    """Transport seam that keeps shell quoting outside the supervisor."""

    def run_script(
        self,
        script: str,
        arguments: tuple[str, ...] = (),
        *,
        stdin: bytes | None = None,
        timeout_seconds: float,
    ) -> RemoteScriptResult: ...


@dataclass(frozen=True, slots=True)
class RemoteGenerationIdentity:
    """Durable generation facts plus the volatile controller fence."""

    runtime_key: AmdRuntimeKey
    manifest_digest: str
    incarnation: RuntimeIncarnation

    def __post_init__(self) -> None:
        _require_identifier(self.runtime_key.installation_id, "Installation ID")
        _require_identifier(self.runtime_key.component_generation_id, "Component generation ID")
        _require_identifier(self.manifest_digest, "Manifest digest")
        _require_identifier(self.incarnation.controller_owner_id, "Controller owner ID")
        _require_identifier(self.incarnation.incarnation_id, "Runtime incarnation ID")


@dataclass(frozen=True, slots=True)
class RemoteEnvironmentSetting:
    """One non-secret launch setting from an admitted component recipe."""

    name: str
    value: str = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not _ENVIRONMENT_NAME.fullmatch(self.name):
            raise RemoteSupervisorError("Remote environment setting name is invalid.")
        _require_safe_argument(self.value, "Remote environment setting value", allow_empty=True)
        if self.name == _AUTH_ENVIRONMENT_NAME:
            raise RemoteSupervisorError("Runtime authentication is supplied only by protected handoff.")


@dataclass(frozen=True, slots=True)
class ProtectedRuntimeSecret:
    """One incarnation-only secret.  It is sent on stdin and never in argv."""

    value: str = field(repr=False)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.value, str)
            or not 24 <= len(self.value) <= 4_096
            or "\x00" in self.value
            or "\r" in self.value
            or "\n" in self.value
        ):
            raise RemoteSupervisorError("Runtime authentication handoff is invalid.")


@dataclass(frozen=True, slots=True)
class RemoteLaunchSpec:
    """Exact non-secret command for one loopback-only runtime incarnation."""

    generation: RemoteGenerationIdentity
    command: tuple[str, ...] = field(repr=False)
    process_executable: str | None = field(default=None, repr=False)
    environment: tuple[RemoteEnvironmentSetting, ...] = field(default=(), repr=False)
    remote_loopback_port: int = field(default=0, repr=False)
    startup_deadline_seconds: float = field(default=30.0, repr=False)

    def __post_init__(self) -> None:
        command = tuple(self.command)
        if not command:
            raise RemoteSupervisorError("Remote launch command is empty.")
        for argument in command:
            _require_safe_argument(argument, "Remote launch argument", allow_empty=True)
        executable = PurePosixPath(command[0])
        if not executable.is_absolute() or ".." in executable.parts:
            raise RemoteSupervisorError("Remote launch executable must be an absolute managed path.")
        process_executable = command[0] if self.process_executable is None else self.process_executable
        _require_safe_argument(process_executable, "Remote process executable")
        process_path = PurePosixPath(process_executable)
        if not process_path.is_absolute() or ".." in process_path.parts:
            raise RemoteSupervisorError("Remote process executable must be absolute.")
        if not any(argument in {"127.0.0.1", "::1"} for argument in command):
            raise RemoteSupervisorError("Remote launch must explicitly declare a loopback listener.")
        if any(argument in {"0.0.0.0", "::", "*"} for argument in command):
            raise RemoteSupervisorError("Remote launch cannot declare a public listener.")
        environment = tuple(self.environment)
        if len({setting.name for setting in environment}) != len(environment):
            raise RemoteSupervisorError("Remote launch environment names must be unique.")
        if (
            not isinstance(self.remote_loopback_port, int)
            or isinstance(self.remote_loopback_port, bool)
            or not 1_024 <= self.remote_loopback_port <= 65_535
        ):
            raise RemoteSupervisorError("Remote loopback port is invalid.")
        if str(self.remote_loopback_port) not in command and not any(
            setting.value == str(self.remote_loopback_port) for setting in environment
        ):
            raise RemoteSupervisorError("Remote launch must explicitly declare its loopback port.")
        _require_deadline(self.startup_deadline_seconds)
        object.__setattr__(self, "command", command)
        object.__setattr__(self, "process_executable", str(process_path))
        object.__setattr__(self, "environment", tuple(sorted(environment, key=lambda setting: setting.name)))

    @property
    def command_fingerprint(self) -> str:
        return _command_fingerprint(self.command)

    @property
    def executable(self) -> str:
        """Expected ``/proc/<pid>/exe`` value, not necessarily argv[0]."""

        assert self.process_executable is not None
        return self.process_executable

    @property
    def command_executable(self) -> str:
        """Literal first argv element whose fingerprint is process authority."""

        return self.command[0]


@dataclass(frozen=True, slots=True)
class RemoteProcessObservation:
    """Verified live facts.  The receipt alone never constructs this value."""

    generation: RemoteGenerationIdentity
    pid: int = field(repr=False)
    process_group_id: int = field(repr=False)
    start_identity: str = field(repr=False)
    executable: str = field(repr=False)
    command_fingerprint: str = field(repr=False)
    remote_loopback_port: int = field(repr=False)

    def __post_init__(self) -> None:
        for value in (self.pid, self.process_group_id):
            if not isinstance(value, int) or isinstance(value, bool) or value <= 1:
                raise RemoteProcessIdentityError("Remote process observation is invalid.")
        if not isinstance(self.start_identity, str) or not self.start_identity.isdecimal():
            raise RemoteProcessIdentityError("Remote process start identity is invalid.")
        _require_safe_argument(self.executable, "Remote process executable")
        if not _SHA256.fullmatch(self.command_fingerprint):
            raise RemoteProcessIdentityError("Remote command fingerprint is invalid.")
        if not 1_024 <= self.remote_loopback_port <= 65_535:
            raise RemoteProcessIdentityError("Remote loopback port observation is invalid.")

    def matches(self, spec: RemoteLaunchSpec) -> bool:
        return (
            self.generation == spec.generation
            and self.executable == spec.executable
            and self.command_fingerprint == spec.command_fingerprint
            and self.remote_loopback_port == spec.remote_loopback_port
        )


class RemoteSupervisor:
    """Deep process/root owner behind a placement-specific execution session."""

    def __init__(
        self,
        runner: RemoteScriptRunner,
        *,
        target_id: str,
        product_root: str,
        command_deadline_seconds: float = 20.0,
        stop_grace_seconds: int = 10,
    ) -> None:
        _require_identifier(target_id, "Target ID")
        self._runner = runner
        self._target_id = target_id
        self._product_root = _require_product_root(product_root)
        _require_deadline(command_deadline_seconds)
        if (
            not isinstance(stop_grace_seconds, int)
            or isinstance(stop_grace_seconds, bool)
            or not 1 <= stop_grace_seconds <= 30
        ):
            raise RemoteSupervisorError("Remote stop grace period is invalid.")
        self._command_deadline_seconds = float(command_deadline_seconds)
        self._stop_grace_seconds = stop_grace_seconds

    def probe_prerequisites(self) -> None:
        """Read-only proof for the fixed supervision primitives."""

        result = self._runner.run_script(
            _PROBE_SCRIPT,
            timeout_seconds=self._command_deadline_seconds,
        )
        if result.return_code != 0 or result.stdout != b"xenix-supervisor-v1\n":
            raise UnsupportedRemoteTargetError("Remote target lacks managed supervision prerequisites.")

    def observe(self, generation: RemoteGenerationIdentity) -> RemoteProcessObservation | None:
        """Return only a receipt whose complete live process identity still matches."""

        result = self._runner.run_script(
            _OBSERVE_SCRIPT,
            self._generation_arguments(generation),
            timeout_seconds=self._command_deadline_seconds,
        )
        if result.return_code == 3:
            return None
        if result.return_code != 0:
            raise RemoteProcessIdentityError("Remote process identity could not be verified.")
        return _parse_observation(result.stdout)

    def recover_stopped_observation(
        self,
        *,
        runtime_key: AmdRuntimeKey,
        manifest_digest: str,
    ) -> RemoteProcessObservation:
        """Fence a prior incarnation into a stopped receipt for cleanup.

        This is deliberately a recovery operation rather than a normal
        realization path.  It is used only after durable retirement has closed
        capability admission.  A live receipt is re-observed and stopped using
        its own recorded identity; a dead receipt may be reaped without ever
        signalling its historical PID.  No current endpoint, token, or port is
        trusted or returned to callers.
        """

        _require_identifier(runtime_key.installation_id, "Installation ID")
        _require_identifier(runtime_key.component_generation_id, "Component generation ID")
        _require_identifier(manifest_digest, "Manifest digest")
        try:
            live = self._observe_any_live(runtime_key=runtime_key, manifest_digest=manifest_digest)
        except RemoteProcessIdentityError:
            self._reap_any_stale_receipt(runtime_key=runtime_key, manifest_digest=manifest_digest)
        else:
            if live is not None:
                self.stop(live)

        result = self._runner.run_script(
            _OBSERVE_STOPPED_SCRIPT,
            self._unfenced_generation_arguments(runtime_key, manifest_digest),
            timeout_seconds=self._command_deadline_seconds,
        )
        if result.return_code != 0:
            raise RemoteProcessIdentityError("Remote stopped-process fence could not be recovered.")
        observation = _parse_observation(result.stdout)
        if (
            observation.generation.runtime_key != runtime_key
            or observation.generation.manifest_digest != manifest_digest
        ):
            raise RemoteProcessIdentityError("Remote stopped-process fence changed.")
        return observation

    def start(
        self,
        spec: RemoteLaunchSpec,
        secret: ProtectedRuntimeSecret,
    ) -> RemoteProcessObservation:
        """Start idempotently, never replacing a different verified realization."""

        self._claim_product_root()
        self._prepare_generation(spec.generation)
        try:
            existing = self.observe(spec.generation)
        except RemoteProcessIdentityError:
            self.reap_stale_receipt(spec.generation)
            existing = None
        if existing is not None:
            if existing.matches(spec):
                return existing
            raise RemoteProcessConflictError("A different managed process already owns this generation.")

        arguments = [
            *self._generation_arguments(spec.generation),
            spec.command_executable,
            spec.executable,
            spec.command_fingerprint,
            str(spec.remote_loopback_port),
            _AUTH_ENVIRONMENT_NAME,
            str(len(spec.environment)),
        ]
        for setting in spec.environment:
            arguments.extend((setting.name, setting.value))
        arguments.extend((str(len(spec.command)), *spec.command))
        result = self._runner.run_script(
            _START_SCRIPT,
            tuple(arguments),
            stdin=(secret.value + "\n").encode("utf-8"),
            timeout_seconds=spec.startup_deadline_seconds,
        )
        if result.return_code == 23:
            raise RemoteProcessConflictError("A different managed process already owns this generation.")
        if result.return_code != 0:
            raise RemoteSupervisorError("Remote runtime could not be started.")
        observation = _parse_observation(result.stdout)
        if not observation.matches(spec):
            raise RemoteProcessIdentityError("Started process did not match its exact launch identity.")
        return observation

    def prepare_recipe_root(self, generation: RemoteGenerationIdentity) -> str:
        """Claim and prepare one exact generation before trusted provisioning.

        The returned path is an ephemeral controller value.  It is never a
        durable setting and can only be derived from the same target/install/
        generation markers verified by the supervisor.
        """

        self._claim_product_root()
        self._prepare_generation(generation)
        return self._generation_root(generation.runtime_key)

    def run_generation_recipe(
        self,
        generation: RemoteGenerationIdentity,
        script: str,
        arguments: tuple[str, ...] = (),
        *,
        stdin: bytes | None = None,
        timeout_seconds: float,
    ) -> RemoteScriptResult:
        """Run a bounded product recipe inside an exact prepared generation.

        Recipe source is bundled application code, not user input.  It receives
        the generation root only through separately quoted positional
        arguments, so controller-owned artifact paths cannot be interpolated
        into a shell program.
        """

        _require_recipe_deadline(timeout_seconds)
        _require_recipe_script(script)
        self._claim_product_root()
        self._prepare_generation(generation)
        self._recover_interrupted_recipe(generation)
        result = self._runner.run_script(
            _RECIPE_WRAPPER_SCRIPT,
            (
                _RECIPE_EXECUTION_SCRIPT,
                *self._generation_arguments(generation),
                str(math.ceil(timeout_seconds)),
                script,
                *arguments,
            ),
            stdin=stdin,
            timeout_seconds=float(timeout_seconds),
        )
        if result.return_code == 23:
            raise RemoteProcessConflictError("A bounded generation recipe is already active.")
        if len(result.stdout) > 64 * 1_024:
            raise RemoteSupervisorError("Remote generation recipe output exceeded its safety bound.")
        return result

    def cancel_provisioning_for_retirement(
        self,
        *,
        runtime_key: AmdRuntimeKey,
        manifest_digest: str,
    ) -> None:
        """Explicitly cancel only the exact unfinished recipe being retired.

        This is deliberately not part of forward reconciliation.  A requested
        removal revokes the durable generation intent, so it may stop the
        target-side provisioning process only after its receipt proves the
        same installation, generation, manifest, PID, process group, start
        identity, executable, and command fingerprint.
        """

        _require_identifier(runtime_key.installation_id, "Installation ID")
        _require_identifier(runtime_key.component_generation_id, "Component generation ID")
        _require_identifier(manifest_digest, "Manifest digest")
        result = self._runner.run_script(
            _CANCEL_PROVISIONING_SCRIPT,
            (*self._unfenced_generation_arguments(runtime_key, manifest_digest), str(self._stop_grace_seconds)),
            timeout_seconds=self._command_deadline_seconds + self._stop_grace_seconds,
        )
        if result.return_code != 0:
            raise RemoteProcessIdentityError("Unfinished remote provisioning could not be cancelled safely.")

    def stop(self, observation: RemoteProcessObservation) -> None:
        """Signal only the same live process group represented by ``observation``."""

        arguments = (
            *self._generation_arguments(observation.generation),
            str(observation.pid),
            str(observation.process_group_id),
            observation.start_identity,
            observation.executable,
            observation.command_fingerprint,
            str(observation.remote_loopback_port),
            str(self._stop_grace_seconds),
        )
        result = self._runner.run_script(
            _STOP_SCRIPT,
            arguments,
            timeout_seconds=self._command_deadline_seconds + self._stop_grace_seconds,
        )
        if result.return_code == 3:
            return
        if result.return_code != 0:
            raise RemoteProcessIdentityError("Remote process changed before it could be stopped.")

    def reap_stale_receipt(self, generation: RemoteGenerationIdentity) -> None:
        """Forget a dead receipt without ever signalling its observed PID."""

        result = self._runner.run_script(
            _REAP_SCRIPT,
            self._generation_arguments(generation),
            timeout_seconds=self._command_deadline_seconds,
        )
        if result.return_code == 23:
            raise RemoteProcessConflictError("A verified orphan still owns this generation.")
        if result.return_code != 0:
            raise RemoteProcessIdentityError("Stale remote process receipt could not be fenced.")

    def cleanup_generation(
        self,
        observation: RemoteProcessObservation,
        owned_relative_paths: tuple[str, ...],
    ) -> None:
        """Delete only an explicit allow-list below an exactly marked generation."""

        paths = tuple(_require_owned_relative_path(path) for path in owned_relative_paths)
        if len(set(paths)) != len(paths):
            raise RemoteCleanupRefusedError("Managed cleanup paths must be unique.")
        arguments = (
            *self._generation_arguments(observation.generation),
            str(observation.pid),
            str(observation.process_group_id),
            observation.start_identity,
            observation.executable,
            observation.command_fingerprint,
            str(observation.remote_loopback_port),
            str(len(paths)),
            *paths,
        )
        result = self._runner.run_script(
            _CLEANUP_SCRIPT,
            arguments,
            timeout_seconds=self._command_deadline_seconds,
        )
        if result.return_code != 0:
            raise RemoteCleanupRefusedError("Remote generation cleanup was refused by its ownership fence.")

    def cleanup_provisioned_generation(
        self,
        *,
        runtime_key: AmdRuntimeKey,
        manifest_digest: str,
        owned_relative_paths: tuple[str, ...],
    ) -> bool:
        """Clean a retired generation that never produced a runtime receipt.

        The target-side stopped provisioning receipt must prove the completed
        or cancelled recipe and an empty process group.  ``False`` means a
        runtime receipt or no provisioning fence exists, so callers must use
        a stronger recovery path (or leave removal blocked).
        """

        paths = tuple(_require_owned_relative_path(path) for path in owned_relative_paths)
        if len(set(paths)) != len(paths):
            raise RemoteCleanupRefusedError("Managed cleanup paths must be unique.")
        result = self._runner.run_script(
            _CLEANUP_PROVISIONED_SCRIPT,
            (*self._unfenced_generation_arguments(runtime_key, manifest_digest), str(len(paths)), *paths),
            timeout_seconds=self._command_deadline_seconds,
        )
        if result.return_code == 3:
            return False
        if result.return_code != 0:
            raise RemoteCleanupRefusedError("Provisioned remote generation cleanup was refused by its ownership fence.")
        return True

    def cleanup_empty_generation(
        self,
        *,
        runtime_key: AmdRuntimeKey,
        manifest_digest: str,
    ) -> bool:
        """Remove only a marked generation root that has never held payload."""

        result = self._runner.run_script(
            _CLEANUP_EMPTY_GENERATION_SCRIPT,
            self._unfenced_generation_arguments(runtime_key, manifest_digest),
            timeout_seconds=self._command_deadline_seconds,
        )
        if result.return_code == 3:
            return False
        if result.return_code != 0:
            raise RemoteCleanupRefusedError("Empty remote generation cleanup was refused by its ownership fence.")
        return True

    def _claim_product_root(self) -> None:
        result = self._runner.run_script(
            _CLAIM_ROOT_SCRIPT,
            (self._product_root, self._target_id),
            timeout_seconds=self._command_deadline_seconds,
        )
        if result.return_code != 0:
            raise RemoteCleanupRefusedError("Remote product root is not exclusively owned by this target.")

    def _prepare_generation(self, generation: RemoteGenerationIdentity) -> None:
        result = self._runner.run_script(
            _PREPARE_GENERATION_SCRIPT,
            self._generation_arguments(generation),
            timeout_seconds=self._command_deadline_seconds,
        )
        if result.return_code != 0:
            raise RemoteCleanupRefusedError("Remote generation root ownership could not be established.")

    def _recover_interrupted_recipe(self, generation: RemoteGenerationIdentity) -> None:
        """Fence only an expired, target-receipted provisioning process group.

        A dropped SSH client must never make a later reconcile mistake an
        arbitrary downloader for a completed recipe.  The target therefore owns
        a short-lived provisioning receipt.  It remains deliberately separate
        from the runtime receipt: it cannot produce a binding or enter desktop
        persistence, but it lets the next forward reconcile either wait for the
        declared bounded operation or terminate that exact expired process group.
        """

        result = self._runner.run_script(
            _RECOVER_PROVISIONING_SCRIPT,
            (*self._generation_arguments(generation), str(self._stop_grace_seconds)),
            timeout_seconds=self._command_deadline_seconds + self._stop_grace_seconds,
        )
        if result.return_code == 23:
            raise RemoteProcessConflictError("A bounded generation recipe is already active.")
        if result.return_code != 0:
            raise RemoteProcessIdentityError("Interrupted generation provisioning could not be fenced.")

    def _generation_arguments(self, generation: RemoteGenerationIdentity) -> tuple[str, ...]:
        return (
            self._product_root,
            self._target_id,
            generation.runtime_key.installation_id,
            generation.runtime_key.component_generation_id,
            generation.manifest_digest,
            generation.incarnation.controller_owner_id,
            generation.incarnation.incarnation_id,
        )

    def _unfenced_generation_arguments(
        self,
        runtime_key: AmdRuntimeKey,
        manifest_digest: str,
    ) -> tuple[str, ...]:
        return (
            self._product_root,
            self._target_id,
            runtime_key.installation_id,
            runtime_key.component_generation_id,
            manifest_digest,
        )

    def _generation_root(self, runtime_key: AmdRuntimeKey) -> str:
        return str(
            PurePosixPath(self._product_root)
            / "installations"
            / runtime_key.installation_id
            / "generations"
            / runtime_key.component_generation_id
        )

    def _observe_any_live(
        self,
        *,
        runtime_key: AmdRuntimeKey,
        manifest_digest: str,
    ) -> RemoteProcessObservation | None:
        result = self._runner.run_script(
            _OBSERVE_ANY_SCRIPT,
            self._unfenced_generation_arguments(runtime_key, manifest_digest),
            timeout_seconds=self._command_deadline_seconds,
        )
        if result.return_code == 3:
            return None
        if result.return_code != 0:
            raise RemoteProcessIdentityError("Remote process identity could not be recovered.")
        observation = _parse_observation(result.stdout)
        if (
            observation.generation.runtime_key != runtime_key
            or observation.generation.manifest_digest != manifest_digest
        ):
            raise RemoteProcessIdentityError("Remote process identity changed.")
        return observation

    def _reap_any_stale_receipt(
        self,
        *,
        runtime_key: AmdRuntimeKey,
        manifest_digest: str,
    ) -> None:
        result = self._runner.run_script(
            _REAP_ANY_SCRIPT,
            self._unfenced_generation_arguments(runtime_key, manifest_digest),
            timeout_seconds=self._command_deadline_seconds,
        )
        if result.return_code == 23:
            raise RemoteProcessConflictError("A verified prior process still owns this generation.")
        if result.return_code != 0:
            raise RemoteProcessIdentityError("Stale remote process receipt could not be recovered.")


def _parse_observation(payload: bytes) -> RemoteProcessObservation:
    if len(payload) > 8_192:
        raise RemoteProcessIdentityError("Remote process observation exceeded its bound.")
    try:
        text = payload.decode("utf-8", errors="strict")
        lines = text.splitlines()
        if len(lines) != 12:
            raise ValueError
        values: dict[str, str] = {}
        for line in lines:
            name, value = line.split("\t", 1)
            if name in values or not value:
                raise ValueError
            values[name] = value
    except (UnicodeDecodeError, ValueError, KeyError) as exc:
        raise RemoteProcessIdentityError("Remote process observation was malformed.") from exc

    try:
        version = _take(values, "version")
        if version != _RECEIPT_VERSION:
            raise ValueError
        generation = RemoteGenerationIdentity(
            runtime_key=AmdRuntimeKey(
                installation_id=_take(values, "installation"),
                component_generation_id=_take(values, "generation"),
            ),
            manifest_digest=_take(values, "manifest"),
            incarnation=RuntimeIncarnation(
                controller_owner_id=_take(values, "owner"),
                incarnation_id=_take(values, "incarnation"),
            ),
        )
        observation = RemoteProcessObservation(
            generation=generation,
            pid=int(_take(values, "pid")),
            process_group_id=int(_take(values, "pgid")),
            start_identity=_take(values, "start"),
            executable=_take(values, "executable"),
            command_fingerprint=_take(values, "command"),
            remote_loopback_port=int(_take(values, "port")),
        )
        if values:
            raise ValueError
        return observation
    except (KeyError, ValueError) as exc:
        raise RemoteProcessIdentityError("Remote process observation was malformed.") from exc


def _take(values: dict[str, str], name: str) -> str:
    return values.pop(name)


def _command_fingerprint(command: tuple[str, ...]) -> str:
    digest = hashlib.sha256()
    for argument in command:
        digest.update(argument.encode("utf-8"))
        digest.update(b"\x00")
    return digest.hexdigest()


def _require_identifier(value: str, label: str) -> None:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise RemoteSupervisorError(f"{label} is invalid.")


def _require_safe_argument(value: str, label: str, *, allow_empty: bool = False) -> None:
    if (
        not isinstance(value, str)
        or (not allow_empty and not value)
        or len(value) > 8_192
        or "\x00" in value
        or "\r" in value
        or "\n" in value
        or any(ord(character) == 0x7F for character in value)
    ):
        raise RemoteSupervisorError(f"{label} is invalid.")


def _require_recipe_script(value: str) -> None:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > 128 * 1_024
        or "\x00" in value
        or any(ord(character) == 0x7F for character in value)
    ):
        raise RemoteSupervisorError("Remote generation recipe is invalid.")


def _require_deadline(value: float) -> None:
    if (
        not isinstance(value, int | float)
        or isinstance(value, bool)
        or not 0 < float(value) <= 300
    ):
        raise RemoteSupervisorError("Remote command deadline is invalid.")


def _require_recipe_deadline(value: float) -> None:
    if (
        not isinstance(value, int | float)
        or isinstance(value, bool)
        or not 0 < float(value) <= 7_200
    ):
        raise RemoteSupervisorError("Remote recipe deadline is invalid.")


def _require_product_root(value: str) -> str:
    _require_safe_argument(value, "Remote product root")
    path = PurePosixPath(value)
    if not path.is_absolute() or ".." in path.parts or len(path.parts) < 3:
        raise RemoteCleanupRefusedError("Remote product root is unsafe.")
    if str(path) in {"/", "/home", "/opt", "/tmp", "/var", "/workspace"}:
        raise RemoteCleanupRefusedError("Remote product root is too broad.")
    if len(path.parts) > 1 and path.parts[1] == "workspace":
        raise RemoteCleanupRefusedError("Remote product root is not on the admitted persistent filesystem.")
    if any(part.casefold() in {"xenix-rocm-lab", ".xenix-rocm-lab"} for part in path.parts):
        raise RemoteCleanupRefusedError("Remote product root cannot reuse an evidence-only lab.")
    return str(path)


def _require_owned_relative_path(value: str) -> str:
    _require_safe_argument(value, "Managed cleanup path")
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or ".." in path.parts or str(path) in {".", ""}:
        raise RemoteCleanupRefusedError("Managed cleanup path is unsafe.")
    if path.parts[0].startswith(".xenix-"):
        raise RemoteCleanupRefusedError("Managed ownership markers are not cleanup payloads.")
    return str(path)


_PROBE_SCRIPT = r"""
set -eu
[ -r /proc/self/stat ] || exit 31
for tool in flock setsid readlink sha256sum sed; do
    command -v "$tool" >/dev/null 2>&1 || exit 32
done
setsid --wait sh -c ':' >/dev/null 2>&1 || exit 33
date +%s >/dev/null 2>&1 || exit 34
printf 'xenix-supervisor-v1\n'
""".strip()

_CLAIM_ROOT_SCRIPT = r"""
set -eu
root=$1
target=$2
marker="$root/.xenix-target"
if [ -e "$root" ]; then
    [ -d "$root" ] && [ ! -L "$root" ] || exit 41
    [ -f "$marker" ] && [ ! -L "$marker" ] || exit 42
    [ "$(cat "$marker")" = "$target" ] || exit 43
    exit 0
fi
parent=${root%/*}
base=${root##*/}
[ -n "$parent" ] && [ -n "$base" ] || exit 44
mkdir -p -- "$parent"
tmp="$parent/.${base}.claim.$$"
umask 077
mkdir -- "$tmp"
printf '%s\n' "$target" > "$tmp/.xenix-target"
if mv -- "$tmp" "$root" 2>/dev/null; then
    exit 0
fi
rm -- "$tmp/.xenix-target"
rmdir -- "$tmp"
[ -d "$root" ] && [ ! -L "$root" ] || exit 45
[ -f "$marker" ] && [ ! -L "$marker" ] || exit 46
[ "$(cat "$marker")" = "$target" ] || exit 47
""".strip()

_PREPARE_GENERATION_SCRIPT = r"""
set -eu
root=$1
target=$2
installation=$3
generation=$4
manifest=$5
owner=$6
incarnation=$7
[ -f "$root/.xenix-target" ] && [ "$(cat "$root/.xenix-target")" = "$target" ] || exit 41
install_root="$root/installations/$installation"
generation_root="$install_root/generations/$generation"
install_marker="$install_root/.xenix-installation"
generation_marker="$generation_root/.xenix-generation"
control_lock="$generation_root/.xenix-control.lock"
mkdir -p -- "$install_root/generations"
if [ -e "$install_marker" ]; then
    [ -f "$install_marker" ] && [ ! -L "$install_marker" ] || exit 42
    [ "$(cat "$install_marker")" = "$target	$installation" ] || exit 43
else
    umask 077
    printf '%s\t%s\n' "$target" "$installation" > "$install_marker"
fi
if [ -e "$generation_root" ]; then
    [ -d "$generation_root" ] && [ ! -L "$generation_root" ] || exit 44
    [ -f "$generation_marker" ] && [ ! -L "$generation_marker" ] || exit 45
    [ "$(cat "$generation_marker")" = "$target	$installation	$generation	$manifest" ] || exit 46
else
    umask 077
    mkdir -- "$generation_root"
    printf '%s\t%s\t%s\t%s\n' "$target" "$installation" "$generation" "$manifest" > "$generation_marker"
fi
if [ ! -e "$control_lock" ]; then
    (umask 077; set -C; : > "$control_lock") 2>/dev/null || true
fi
[ -f "$control_lock" ] && [ ! -L "$control_lock" ] || exit 47
""".strip()

_RECIPE_WRAPPER_SCRIPT = r"""
set -eu
[ "$#" -ge 1 ] || exit 43
execution_script=$1
shift
exec setsid --wait sh -c "$execution_script" -- "$@"
""".strip()

_RECIPE_EXECUTION_SCRIPT = r"""
set -eu
[ "$#" -ge 9 ] || exit 43
root=$1
target=$2
installation=$3
generation=$4
manifest=$5
owner=$6
incarnation=$7
deadline_seconds=$8
recipe=$9
shift 9
case "$deadline_seconds" in
    ""|*[!0-9]*) exit 44 ;;
esac
generation_root="$root/installations/$installation/generations/$generation"
marker="$generation_root/.xenix-generation"
provisioning="$generation_root/.xenix-provisioning"
provisioning_receipt="$provisioning/receipt"
provisioning_receipt_tmp="$provisioning/.receipt.$$"
stopped_provisioning_receipt="$generation_root/.xenix-provisioning-stopped"
retiring="$generation_root/.xenix-retiring"
[ -f "$root/.xenix-target" ] && [ "$(cat "$root/.xenix-target")" = "$target" ] || exit 45
[ -f "$marker" ] && [ "$(cat "$marker")" = "$target	$installation	$generation	$manifest" ] || exit 46
[ ! -e "$retiring" ] || exit 58
[ ! -e "$stopped_provisioning_receipt" ] || exit 47
umask 077
mkdir -- "$provisioning" 2>/dev/null || exit 23
[ -d "$provisioning" ] && [ ! -L "$provisioning" ] || exit 47
abort_before_receipt() {
    trap - EXIT HUP INT TERM
    rm -f -- "$provisioning_receipt_tmp"
    rmdir -- "$provisioning" 2>/dev/null || true
}
trap abort_before_receipt EXIT HUP INT TERM
r_pid=$$
[ -r "/proc/$r_pid/stat" ] && [ -r "/proc/$r_pid/cmdline" ] || exit 48
proc_fields=$(sed 's/^.*) //' "/proc/$r_pid/stat") || exit 49
r_pgid=$(set -- $proc_fields; printf '%s\n' "$3")
r_start=$(set -- $proc_fields; shift 19; printf '%s\n' "$1")
r_executable=$(readlink "/proc/$r_pid/exe") || exit 50
r_command=$(sha256sum "/proc/$r_pid/cmdline") || exit 51
r_command=${r_command%% *}
[ "$r_pgid" = "$r_pid" ] || exit 52
now=$(date +%s) || exit 53
case "$now" in
    ""|*[!0-9]*) exit 53 ;;
esac
r_deadline=$((now + deadline_seconds))
{
    printf 'version\txenix-provisioning-v1\n'
    printf 'installation\t%s\n' "$installation"
    printf 'generation\t%s\n' "$generation"
    printf 'manifest\t%s\n' "$manifest"
    printf 'owner\t%s\n' "$owner"
    printf 'incarnation\t%s\n' "$incarnation"
    printf 'pid\t%s\n' "$r_pid"
    printf 'pgid\t%s\n' "$r_pgid"
    printf 'start\t%s\n' "$r_start"
    printf 'executable\t%s\n' "$r_executable"
    printf 'command\t%s\n' "$r_command"
    printf 'deadline\t%s\n' "$r_deadline"
} > "$provisioning_receipt_tmp"
mv -- "$provisioning_receipt_tmp" "$provisioning_receipt"
[ ! -e "$retiring" ] || exit 58
finish_recipe() {
    status=$?
    trap - EXIT HUP INT TERM
    [ ! -e "$stopped_provisioning_receipt" ] || exit 54
    mv -- "$provisioning_receipt" "$stopped_provisioning_receipt" || exit 54
    rmdir -- "$provisioning" || exit 55
    exit "$status"
}
retain_recipe_receipt() {
    status=$1
    trap - EXIT HUP INT TERM
    exit "$status"
}
trap finish_recipe EXIT
trap 'retain_recipe_receipt 129' HUP
trap 'retain_recipe_receipt 130' INT
trap 'retain_recipe_receipt 143' TERM
set +e
sh -c "$recipe" -- "$root" "$target" "$installation" "$generation" "$manifest" "$owner" "$incarnation" "$@"
status=$?
set -e
exit "$status"
""".strip()

_RECOVER_PROVISIONING_SCRIPT_TEMPLATE = (
    r"""
set -eu
root=$1
target=$2
installation=$3
generation=$4
manifest=$5
owner=$6
incarnation=$7
grace=$8
generation_root="$root/installations/$installation/generations/$generation"
marker="$generation_root/.xenix-generation"
provisioning="$generation_root/.xenix-provisioning"
provisioning_receipt="$provisioning/receipt"
stopped_provisioning_receipt="$generation_root/.xenix-provisioning-stopped"
retiring="$generation_root/.xenix-retiring"
[ -f "$root/.xenix-target" ] && [ "$(cat "$root/.xenix-target")" = "$target" ] || exit 4
[ -f "$marker" ] && [ "$(cat "$marker")" = "$target	$installation	$generation	$manifest" ] || exit 4
[ ! -e "$retiring" ] || exit 58
"""
    + "\n"
    + "{provisioning_reader}"
    + "\n"
    + r"""
if [ -e "$stopped_provisioning_receipt" ]; then
    [ -f "$stopped_provisioning_receipt" ] && [ ! -L "$stopped_provisioning_receipt" ] || exit 4
    provisioning_receipt=$stopped_provisioning_receipt
    read_provisioning_receipt || exit 4
    [ "$r_installation" = "$installation" ] &&
    [ "$r_generation" = "$generation" ] &&
    [ "$r_manifest" = "$manifest" ] || exit 4
    provisioning_process_group_is_empty || exit 4
    rm -- "$stopped_provisioning_receipt"
    provisioning_receipt="$provisioning/receipt"
fi
[ ! -e "$provisioning" ] && exit 0
[ -d "$provisioning" ] && [ ! -L "$provisioning" ] || exit 4
if [ ! -e "$provisioning_receipt" ]; then
    rmdir -- "$provisioning" && exit 0
    exit 4
fi
[ -f "$provisioning_receipt" ] && [ ! -L "$provisioning_receipt" ] || exit 4
read_provisioning_receipt || exit 4
[ "$r_installation" = "$installation" ] &&
[ "$r_generation" = "$generation" ] &&
[ "$r_manifest" = "$manifest" ] || exit 4
case "$r_deadline" in
    ""|*[!0-9]*) exit 4 ;;
esac
clear_provisioning() {
    rm -- "$provisioning_receipt"
    rmdir -- "$provisioning"
}
if ! provisioning_receipt_matches_process; then
    if ! provisioning_process_group_is_empty; then
        exit 4
    fi
    clear_provisioning
    exit 0
fi
now=$(date +%s) || exit 4
case "$now" in
    ""|*[!0-9]*) exit 4 ;;
esac
[ "$now" -ge "$r_deadline" ] || exit 23
kill -TERM "-$r_pgid" 2>/dev/null || exit 4
i=0
limit=$((grace * 10))
while [ "$i" -lt "$limit" ]; do
    if provisioning_process_group_is_empty; then
        clear_provisioning
        exit 0
    fi
    sleep 0.1
    i=$((i + 1))
done
if ! provisioning_receipt_matches_process; then
    if ! provisioning_process_group_is_empty; then
        exit 4
    fi
    clear_provisioning
    exit 0
fi
kill -KILL "-$r_pgid" 2>/dev/null || exit 4
i=0
while [ "$i" -lt 50 ]; do
    if provisioning_process_group_is_empty; then
        clear_provisioning
        exit 0
    fi
    sleep 0.1
    i=$((i + 1))
done
exit 4
"""
)

_READ_RECEIPT = r"""
read_receipt() {
    {
        IFS="$(printf '\t')" read -r k_version r_version
        IFS="$(printf '\t')" read -r k_installation r_installation
        IFS="$(printf '\t')" read -r k_generation r_generation
        IFS="$(printf '\t')" read -r k_manifest r_manifest
        IFS="$(printf '\t')" read -r k_owner r_owner
        IFS="$(printf '\t')" read -r k_incarnation r_incarnation
        IFS="$(printf '\t')" read -r k_pid r_pid
        IFS="$(printf '\t')" read -r k_pgid r_pgid
        IFS="$(printf '\t')" read -r k_start r_start
        IFS="$(printf '\t')" read -r k_executable r_executable
        IFS="$(printf '\t')" read -r k_command r_command
        IFS="$(printf '\t')" read -r k_port r_port
        if IFS= read -r extra; then
            return 1
        fi
        true
    } < "$receipt" || return 1
    [ "$k_version" = version ] && [ "$r_version" = xenix-runtime-v1 ] &&
    [ "$k_installation" = installation ] && [ "$k_generation" = generation ] &&
    [ "$k_manifest" = manifest ] && [ "$k_owner" = owner ] &&
    [ "$k_incarnation" = incarnation ] && [ "$k_pid" = pid ] &&
    [ "$k_pgid" = pgid ] && [ "$k_start" = start ] &&
    [ "$k_executable" = executable ] && [ "$k_command" = command ] &&
    [ "$k_port" = port ] || return 1
    case "$r_pid" in
        ""|0|1|*[!0-9]*) return 1 ;;
    esac
    [ "$r_pgid" = "$r_pid" ] || return 1
    case "$r_start" in
        ""|*[!0-9]*) return 1 ;;
    esac
}
load_process() {
    [ -r "/proc/$r_pid/stat" ] && [ -r "/proc/$r_pid/cmdline" ] || return 1
    proc_fields=$(sed 's/^.*) //' "/proc/$r_pid/stat") || return 1
    set -- $proc_fields
    live_pgid=$3
    shift 19
    live_start=$1
    live_executable=$(readlink "/proc/$r_pid/exe") || return 1
    live_command=$(sha256sum "/proc/$r_pid/cmdline") || return 1
    live_command=${live_command%% *}
}
receipt_matches_process() {
    load_process || return 1
    [ "$live_pgid" = "$r_pgid" ] &&
    [ "$live_start" = "$r_start" ] &&
    [ "$live_executable" = "$r_executable" ] &&
    [ "$live_command" = "$r_command" ]
}
process_is_live() {
    [ -r "/proc/$r_pid/stat" ] || return 1
    proc_fields=$(sed 's/^.*) //' "/proc/$r_pid/stat") || return 1
    set -- $proc_fields
    case "$1" in
        Z|X) return 1 ;;
    esac
    kill -0 "$r_pid" 2>/dev/null
}
process_group_is_live() {
    for stat_file in /proc/[0-9]*/stat; do
        [ -e "$stat_file" ] || continue
        [ -r "$stat_file" ] || return 2
        proc_fields=$(sed 's/^.*) //' "$stat_file") || {
            [ ! -e "$stat_file" ] && continue
            return 2
        }
        set -- $proc_fields
        [ "$#" -ge 3 ] || return 2
        case "$1" in
            Z|X) continue ;;
        esac
        [ "$3" = "$r_pgid" ] && return 0
    done
    return 1
}
process_group_is_empty() {
    if process_group_is_live; then
        return 1
    else
        status=$?
    fi
    [ "$status" -eq 1 ]
}
""".strip()

_READ_PROVISIONING_RECEIPT = r"""
read_provisioning_receipt() {
    {
        IFS="$(printf '\t')" read -r k_version r_version
        IFS="$(printf '\t')" read -r k_installation r_installation
        IFS="$(printf '\t')" read -r k_generation r_generation
        IFS="$(printf '\t')" read -r k_manifest r_manifest
        IFS="$(printf '\t')" read -r k_owner r_owner
        IFS="$(printf '\t')" read -r k_incarnation r_incarnation
        IFS="$(printf '\t')" read -r k_pid r_pid
        IFS="$(printf '\t')" read -r k_pgid r_pgid
        IFS="$(printf '\t')" read -r k_start r_start
        IFS="$(printf '\t')" read -r k_executable r_executable
        IFS="$(printf '\t')" read -r k_command r_command
        IFS="$(printf '\t')" read -r k_deadline r_deadline
        if IFS= read -r extra; then
            return 1
        fi
        true
    } < "$provisioning_receipt" || return 1
    [ "$k_version" = version ] && [ "$r_version" = xenix-provisioning-v1 ] &&
    [ "$k_installation" = installation ] && [ "$k_generation" = generation ] &&
    [ "$k_manifest" = manifest ] && [ "$k_owner" = owner ] &&
    [ "$k_incarnation" = incarnation ] && [ "$k_pid" = pid ] &&
    [ "$k_pgid" = pgid ] && [ "$k_start" = start ] &&
    [ "$k_executable" = executable ] && [ "$k_command" = command ] &&
    [ "$k_deadline" = deadline ] || return 1
    case "$r_pid" in
        ""|0|1|*[!0-9]*) return 1 ;;
    esac
    [ "$r_pgid" = "$r_pid" ] || return 1
    case "$r_start" in
        ""|*[!0-9]*) return 1 ;;
    esac
}
load_provisioning_process() {
    [ -r "/proc/$r_pid/stat" ] && [ -r "/proc/$r_pid/cmdline" ] || return 1
    proc_fields=$(sed 's/^.*) //' "/proc/$r_pid/stat") || return 1
    set -- $proc_fields
    live_pgid=$3
    shift 19
    live_start=$1
    live_executable=$(readlink "/proc/$r_pid/exe") || return 1
    live_command=$(sha256sum "/proc/$r_pid/cmdline") || return 1
    live_command=${live_command%% *}
}
provisioning_receipt_matches_process() {
    load_provisioning_process || return 1
    [ "$live_pgid" = "$r_pgid" ] &&
    [ "$live_start" = "$r_start" ] &&
    [ "$live_executable" = "$r_executable" ] &&
    [ "$live_command" = "$r_command" ]
}
provisioning_process_is_live() {
    [ -r "/proc/$r_pid/stat" ] || return 1
    proc_fields=$(sed 's/^.*) //' "/proc/$r_pid/stat") || return 1
    set -- $proc_fields
    case "$1" in
        Z|X) return 1 ;;
    esac
    kill -0 "$r_pid" 2>/dev/null
}
provisioning_process_group_is_live() {
    for stat_file in /proc/[0-9]*/stat; do
        [ -e "$stat_file" ] || continue
        [ -r "$stat_file" ] || return 2
        proc_fields=$(sed 's/^.*) //' "$stat_file") || {
            [ ! -e "$stat_file" ] && continue
            return 2
        }
        set -- $proc_fields
        [ "$#" -ge 3 ] || return 2
        case "$1" in
            Z|X) continue ;;
        esac
        [ "$3" = "$r_pgid" ] && return 0
    done
    return 1
}
provisioning_process_group_is_empty() {
    if provisioning_process_group_is_live; then
        return 1
    else
        status=$?
    fi
    [ "$status" -eq 1 ]
}
""".strip()

_RECOVER_PROVISIONING_SCRIPT = _RECOVER_PROVISIONING_SCRIPT_TEMPLATE.replace(
    "{provisioning_reader}",
    _READ_PROVISIONING_RECEIPT,
)

_CANCEL_PROVISIONING_SCRIPT_TEMPLATE = (
    r"""
set -eu
root=$1
target=$2
installation=$3
generation=$4
manifest=$5
grace=$6
generation_root="$root/installations/$installation/generations/$generation"
marker="$generation_root/.xenix-generation"
provisioning="$generation_root/.xenix-provisioning"
provisioning_receipt="$provisioning/receipt"
stopped_provisioning_receipt="$generation_root/.xenix-provisioning-stopped"
retiring="$generation_root/.xenix-retiring"
retirement_intent="$retiring/intent"
[ -f "$root/.xenix-target" ] && [ "$(cat "$root/.xenix-target")" = "$target" ] || exit 4
expected_marker=$(printf '%s\t%s\t%s\t%s' "$target" "$installation" "$generation" "$manifest")
[ -f "$marker" ] && [ "$(cat "$marker")" = "$expected_marker" ] || exit 4
case "$grace" in
    ""|*[!0-9]*) exit 4 ;;
esac
claim_retirement() {
    if [ -e "$retiring" ]; then
        [ -d "$retiring" ] && [ ! -L "$retiring" ] || exit 4
    else
        umask 077
        mkdir -- "$retiring" 2>/dev/null || {
            [ -d "$retiring" ] && [ ! -L "$retiring" ] || exit 4
        }
    fi
    if [ ! -e "$retirement_intent" ]; then
        intent_tmp="$retiring/.intent.$$"
        printf '%s\t%s\t%s\t%s\n' "$target" "$installation" "$generation" "$manifest" > "$intent_tmp" || exit 4
        mv -- "$intent_tmp" "$retirement_intent" || exit 4
    fi
    [ -f "$retirement_intent" ] && [ ! -L "$retirement_intent" ] || exit 4
    [ "$(cat "$retirement_intent")" = "$expected_marker" ] || exit 4
}
claim_retirement
[ ! -e "$provisioning" ] && exit 0
[ -d "$provisioning" ] && [ ! -L "$provisioning" ] || exit 4
[ -f "$provisioning_receipt" ] && [ ! -L "$provisioning_receipt" ] || exit 4
"""
    + "\n"
    + "{provisioning_reader}"
    + "\n"
    + r"""
read_provisioning_receipt || exit 4
[ "$r_installation" = "$installation" ] &&
[ "$r_generation" = "$generation" ] &&
[ "$r_manifest" = "$manifest" ] || exit 4
clear_provisioning() {
    [ ! -e "$stopped_provisioning_receipt" ] || exit 4
    mv -- "$provisioning_receipt" "$stopped_provisioning_receipt"
    rmdir -- "$provisioning"
}
if ! provisioning_receipt_matches_process; then
    if ! provisioning_process_group_is_empty; then
        exit 4
    fi
    clear_provisioning
    exit 0
fi
kill -TERM "-$r_pgid" 2>/dev/null || exit 4
i=0
limit=$((grace * 10))
while [ "$i" -lt "$limit" ]; do
    if provisioning_process_group_is_empty; then
        clear_provisioning
        exit 0
    fi
    sleep 0.1
    i=$((i + 1))
done
if ! provisioning_receipt_matches_process; then
    if ! provisioning_process_group_is_empty; then
        exit 4
    fi
    clear_provisioning
    exit 0
fi
kill -KILL "-$r_pgid" 2>/dev/null || exit 4
i=0
while [ "$i" -lt 50 ]; do
    if provisioning_process_group_is_empty; then
        clear_provisioning
        exit 0
    fi
    sleep 0.1
    i=$((i + 1))
done
exit 4
"""
)

_CANCEL_PROVISIONING_SCRIPT = _CANCEL_PROVISIONING_SCRIPT_TEMPLATE.replace(
    "{provisioning_reader}",
    _READ_PROVISIONING_RECEIPT,
)

_OBSERVE_SCRIPT = (
    r"""
set -eu
root=$1
target=$2
installation=$3
generation=$4
manifest=$5
expected_owner=$6
expected_incarnation=$7
generation_root="$root/installations/$installation/generations/$generation"
marker="$generation_root/.xenix-generation"
receipt="$generation_root/.xenix-runtime"
[ -f "$root/.xenix-target" ] && [ "$(cat "$root/.xenix-target")" = "$target" ] || exit 4
[ -f "$marker" ] && [ "$(cat "$marker")" = "$target	$installation	$generation	$manifest" ] || exit 4
[ -e "$receipt" ] || exit 3
[ -f "$receipt" ] && [ ! -L "$receipt" ] || exit 4
"""
    + "\n"
    + _READ_RECEIPT
    + r"""
read_receipt || exit 4
[ "$r_installation" = "$installation" ] &&
[ "$r_generation" = "$generation" ] &&
[ "$r_manifest" = "$manifest" ] &&
[ "$r_owner" = "$expected_owner" ] &&
[ "$r_incarnation" = "$expected_incarnation" ] || exit 4
receipt_matches_process || exit 4
cat -- "$receipt"
"""
)

_OBSERVE_ANY_SCRIPT = (
    r"""
set -eu
root=$1
target=$2
installation=$3
generation=$4
manifest=$5
generation_root="$root/installations/$installation/generations/$generation"
marker="$generation_root/.xenix-generation"
receipt="$generation_root/.xenix-runtime"
[ -f "$root/.xenix-target" ] && [ "$(cat "$root/.xenix-target")" = "$target" ] || exit 4
[ -f "$marker" ] && [ "$(cat "$marker")" = "$target	$installation	$generation	$manifest" ] || exit 4
[ -e "$receipt" ] || exit 3
[ -f "$receipt" ] && [ ! -L "$receipt" ] || exit 4
"""
    + "\n"
    + _READ_RECEIPT
    + r"""
read_receipt || exit 4
[ "$r_installation" = "$installation" ] &&
[ "$r_generation" = "$generation" ] &&
[ "$r_manifest" = "$manifest" ] || exit 4
receipt_matches_process || exit 4
cat -- "$receipt"
"""
)

_OBSERVE_STOPPED_SCRIPT = (
    r"""
set -eu
root=$1
target=$2
installation=$3
generation=$4
manifest=$5
generation_root="$root/installations/$installation/generations/$generation"
marker="$generation_root/.xenix-generation"
receipt="$generation_root/.xenix-runtime"
stopped_receipt="$generation_root/.xenix-stopped"
[ -f "$root/.xenix-target" ] && [ "$(cat "$root/.xenix-target")" = "$target" ] || exit 4
[ -f "$marker" ] && [ "$(cat "$marker")" = "$target	$installation	$generation	$manifest" ] || exit 4
[ ! -e "$receipt" ] || exit 4
[ -f "$stopped_receipt" ] && [ ! -L "$stopped_receipt" ] || exit 4
receipt=$stopped_receipt
"""
    + "\n"
    + _READ_RECEIPT
    + r"""
read_receipt || exit 4
[ "$r_installation" = "$installation" ] &&
[ "$r_generation" = "$generation" ] &&
[ "$r_manifest" = "$manifest" ] || exit 4
cat -- "$receipt"
"""
)

_START_SCRIPT = (
    r"""
set -eu
root=$1
target=$2
installation=$3
generation=$4
manifest=$5
owner=$6
incarnation=$7
expected_command_executable=$8
expected_process_executable=$9
expected_command=${10}
shift 10
port=$1
secret_name=$2
environment_count=$3
shift 3
generation_root="$root/installations/$installation/generations/$generation"
marker="$generation_root/.xenix-generation"
receipt="$generation_root/.xenix-runtime"
stopped_receipt="$generation_root/.xenix-stopped"
provisioning="$generation_root/.xenix-provisioning"
retiring="$generation_root/.xenix-retiring"
control_lock="$generation_root/.xenix-control.lock"
token_file="$generation_root/.xenix-runtime-token"
log="$generation_root/runtime.log"
[ -f "$root/.xenix-target" ] && [ "$(cat "$root/.xenix-target")" = "$target" ] || exit 41
[ -f "$marker" ] && [ "$(cat "$marker")" = "$(printf '%s\t%s\t%s\t%s' "$target" "$installation" "$generation" "$manifest")" ] || exit 42
[ -f "$control_lock" ] && [ ! -L "$control_lock" ] || exit 24
exec 9>"$control_lock"
flock 9
[ ! -e "$retiring" ] || exit 58
"""
    + "\n"
    + _READ_RECEIPT
    + r"""
if [ -e "$receipt" ]; then
    [ -f "$receipt" ] && [ ! -L "$receipt" ] || exit 24
    read_receipt || exit 23
    [ "$r_installation" = "$installation" ] &&
    [ "$r_generation" = "$generation" ] &&
    [ "$r_manifest" = "$manifest" ] || exit 24
    if receipt_matches_process; then
        exit 23
    fi
    process_group_is_empty || exit 24
    rm -- "$receipt"
fi
if [ -e "$stopped_receipt" ]; then
    [ -f "$stopped_receipt" ] && [ ! -L "$stopped_receipt" ] || exit 24
    receipt=$stopped_receipt
    read_receipt || exit 24
    [ "$r_installation" = "$installation" ] &&
    [ "$r_generation" = "$generation" ] &&
    [ "$r_manifest" = "$manifest" ] || exit 24
    process_group_is_empty || exit 24
    rm -- "$stopped_receipt"
    receipt="$generation_root/.xenix-runtime"
fi
[ ! -e "$provisioning" ] || exit 23
i=0
while [ "$i" -lt "$environment_count" ]; do
    [ "$#" -ge 2 ] || exit 43
    export "$1=$2"
    shift 2
    i=$((i + 1))
done
[ "$#" -ge 2 ] || exit 44
command_count=$1
shift
[ "$#" -eq "$command_count" ] && [ "$command_count" -gt 0 ] || exit 45
[ "$1" = "$expected_command_executable" ] || exit 46
IFS= read -r runtime_secret || exit 47
[ -n "$runtime_secret" ] || exit 48
umask 077
printf '%s\n' "$runtime_secret" > "$token_file" || exit 56
chmod 600 -- "$token_file" || exit 56
export "$secret_name=$token_file"
unset runtime_secret
launch_script='
set -eu
root=$1
target=$2
installation=$3
generation=$4
manifest=$5
owner=$6
incarnation=$7
expected_process_executable=$8
expected_command=$9
port=${10}
shift 10
generation_root="$root/installations/$installation/generations/$generation"
marker="$generation_root/.xenix-generation"
receipt="$generation_root/.xenix-runtime"
retiring="$generation_root/.xenix-retiring"
[ -f "$root/.xenix-target" ] && [ "$(cat "$root/.xenix-target")" = "$target" ] || exit 41
[ -f "$marker" ] && [ "$(cat "$marker")" = "$(printf "%s\\t%s\\t%s\\t%s" "$target" "$installation" "$generation" "$manifest")" ] || exit 42
[ ! -e "$retiring" ] || exit 58
r_pid=$$
[ -r "/proc/$r_pid/stat" ] && [ -r "/proc/$r_pid/cmdline" ] || exit 50
proc_fields=$(sed "s/^.*) //" "/proc/$r_pid/stat") || exit 50
r_pgid=$(set -- $proc_fields; printf "%s\\n" "$3") || exit 50
r_start=$(set -- $proc_fields; shift 19; printf "%s\\n" "$1") || exit 50
[ "$r_pgid" = "$r_pid" ] || exit 53
receipt_tmp="$generation_root/.xenix-runtime.$$.tmp"
trap "rm -f -- \"$receipt_tmp\"" EXIT HUP INT TERM
{
    printf "version\\txenix-runtime-v1\\n"
    printf "installation\\t%s\\n" "$installation"
    printf "generation\\t%s\\n" "$generation"
    printf "manifest\\t%s\\n" "$manifest"
    printf "owner\\t%s\\n" "$owner"
    printf "incarnation\\t%s\\n" "$incarnation"
    printf "pid\\t%s\\n" "$r_pid"
    printf "pgid\\t%s\\n" "$r_pgid"
    printf "start\\t%s\\n" "$r_start"
    printf "executable\\t%s\\n" "$expected_process_executable"
    printf "command\\t%s\\n" "$expected_command"
    printf "port\\t%s\\n" "$port"
} > "$receipt_tmp"
mv -- "$receipt_tmp" "$receipt"
trap - EXIT HUP INT TERM
# The parent start script holds this inherited generation lock until it has
# re-observed the receipt.  Closing it only after the receipt is durable keeps
# a crashed parent from exposing a no-receipt window to cleanup.
exec 9>&-
[ ! -e "$retiring" ] || exit 58
exec "$@"
'
setsid sh -c "$launch_script" x \
    "$root" "$target" "$installation" "$generation" "$manifest" \
    "$owner" "$incarnation" "$expected_process_executable" "$expected_command" "$port" \
    "$@" </dev/null >>"$log" 2>&1 &
i=0
while [ "$i" -lt 100 ]; do
    if [ -e "$receipt" ]; then
        [ -f "$receipt" ] && [ ! -L "$receipt" ] || exit 50
        read_receipt || exit 50
        [ "$r_installation" = "$installation" ] &&
        [ "$r_generation" = "$generation" ] &&
        [ "$r_manifest" = "$manifest" ] &&
        [ "$r_owner" = "$owner" ] &&
        [ "$r_incarnation" = "$incarnation" ] &&
        [ "$r_port" = "$port" ] || exit 50
        if receipt_matches_process; then
            cat -- "$receipt"
            exit 0
        fi
        if process_group_is_empty; then
            exit 49
        fi
    fi
    sleep 0.05
    i=$((i + 1))
done
exit 50
"""
)

_STOP_SCRIPT = (
    r"""
set -eu
root=$1
target=$2
installation=$3
generation=$4
manifest=$5
expected_owner=$6
expected_incarnation=$7
expected_pid=$8
expected_pgid=$9
shift 9
expected_start=$1
expected_executable=$2
expected_command=$3
expected_port=$4
grace=$5
generation_root="$root/installations/$installation/generations/$generation"
marker="$generation_root/.xenix-generation"
receipt="$generation_root/.xenix-runtime"
stopped_receipt="$generation_root/.xenix-stopped"
token_file="$generation_root/.xenix-runtime-token"
control_lock="$generation_root/.xenix-control.lock"
[ -f "$root/.xenix-target" ] && [ "$(cat "$root/.xenix-target")" = "$target" ] || exit 4
[ -f "$marker" ] && [ "$(cat "$marker")" = "$target	$installation	$generation	$manifest" ] || exit 4
[ -f "$control_lock" ] && [ ! -L "$control_lock" ] || exit 4
exec 9>"$control_lock"
flock 9
[ -e "$receipt" ] || exit 3
[ ! -e "$stopped_receipt" ] || exit 4
[ -f "$receipt" ] && [ ! -L "$receipt" ] || exit 4
"""
    + "\n"
    + _READ_RECEIPT
    + r"""
read_receipt || exit 4
[ "$r_installation" = "$installation" ] &&
[ "$r_generation" = "$generation" ] &&
[ "$r_manifest" = "$manifest" ] &&
[ "$r_owner" = "$expected_owner" ] &&
[ "$r_incarnation" = "$expected_incarnation" ] &&
[ "$r_pid" = "$expected_pid" ] &&
[ "$r_pgid" = "$expected_pgid" ] &&
[ "$r_start" = "$expected_start" ] &&
[ "$r_executable" = "$expected_executable" ] &&
[ "$r_command" = "$expected_command" ] &&
[ "$r_port" = "$expected_port" ] || exit 4
move_to_stopped() {
    mv -- "$receipt" "$generation_root/.xenix-stopped"
    if [ -e "$token_file" ]; then
        [ -f "$token_file" ] && [ ! -L "$token_file" ] || exit 4
        rm -- "$token_file"
    fi
}
if ! receipt_matches_process; then
    if ! process_group_is_empty; then
        exit 4
    fi
    move_to_stopped
    exit 0
fi
kill -TERM "-$r_pgid" 2>/dev/null || exit 4
i=0
limit=$((grace * 10))
while [ "$i" -lt "$limit" ]; do
    if process_group_is_empty; then
        move_to_stopped
        exit 0
    fi
    sleep 0.1
    i=$((i + 1))
done
if ! receipt_matches_process; then
    if ! process_group_is_empty; then
        exit 4
    fi
    move_to_stopped
    exit 0
fi
kill -KILL "-$r_pgid" 2>/dev/null || exit 4
i=0
while [ "$i" -lt 50 ]; do
    if process_group_is_empty; then
        move_to_stopped
        exit 0
    fi
    sleep 0.1
    i=$((i + 1))
done
exit 4
"""
)

_REAP_SCRIPT = (
    r"""
set -eu
root=$1
target=$2
installation=$3
generation=$4
manifest=$5
expected_owner=$6
expected_incarnation=$7
generation_root="$root/installations/$installation/generations/$generation"
marker="$generation_root/.xenix-generation"
receipt="$generation_root/.xenix-runtime"
stopped_receipt="$generation_root/.xenix-stopped"
token_file="$generation_root/.xenix-runtime-token"
control_lock="$generation_root/.xenix-control.lock"
[ -f "$root/.xenix-target" ] && [ "$(cat "$root/.xenix-target")" = "$target" ] || exit 4
[ -f "$marker" ] && [ "$(cat "$marker")" = "$target	$installation	$generation	$manifest" ] || exit 4
[ -f "$control_lock" ] && [ ! -L "$control_lock" ] || exit 4
exec 9>"$control_lock"
flock 9
[ -e "$receipt" ] || exit 0
[ ! -e "$stopped_receipt" ] || exit 4
[ -f "$receipt" ] && [ ! -L "$receipt" ] || exit 4
"""
    + "\n"
    + _READ_RECEIPT
    + r"""
read_receipt || exit 4
[ "$r_installation" = "$installation" ] &&
[ "$r_generation" = "$generation" ] &&
[ "$r_manifest" = "$manifest" ] &&
[ "$r_owner" = "$expected_owner" ] &&
[ "$r_incarnation" = "$expected_incarnation" ] || exit 4
if receipt_matches_process; then
    exit 23
fi
if ! process_group_is_empty; then
    exit 4
fi
mv -- "$receipt" "$stopped_receipt"
if [ -e "$token_file" ]; then
    [ -f "$token_file" ] && [ ! -L "$token_file" ] || exit 4
    rm -- "$token_file"
fi
"""
)

_REAP_ANY_SCRIPT = (
    r"""
set -eu
root=$1
target=$2
installation=$3
generation=$4
manifest=$5
generation_root="$root/installations/$installation/generations/$generation"
marker="$generation_root/.xenix-generation"
receipt="$generation_root/.xenix-runtime"
stopped_receipt="$generation_root/.xenix-stopped"
token_file="$generation_root/.xenix-runtime-token"
control_lock="$generation_root/.xenix-control.lock"
[ -f "$root/.xenix-target" ] && [ "$(cat "$root/.xenix-target")" = "$target" ] || exit 4
[ -f "$marker" ] && [ "$(cat "$marker")" = "$target	$installation	$generation	$manifest" ] || exit 4
[ -f "$control_lock" ] && [ ! -L "$control_lock" ] || exit 4
exec 9>"$control_lock"
flock 9
[ -e "$receipt" ] || exit 0
[ ! -e "$stopped_receipt" ] || exit 4
[ -f "$receipt" ] && [ ! -L "$receipt" ] || exit 4
"""
    + "\n"
    + _READ_RECEIPT
    + r"""
read_receipt || exit 4
[ "$r_installation" = "$installation" ] &&
[ "$r_generation" = "$generation" ] &&
[ "$r_manifest" = "$manifest" ] || exit 4
if receipt_matches_process; then
    exit 23
fi
if ! process_group_is_empty; then
    exit 4
fi
mv -- "$receipt" "$stopped_receipt"
if [ -e "$token_file" ]; then
    [ -f "$token_file" ] && [ ! -L "$token_file" ] || exit 4
    rm -- "$token_file"
fi
"""
)

_CLEANUP_SCRIPT = r"""
set -eu
root=$1
target=$2
installation=$3
generation=$4
manifest=$5
expected_owner=$6
expected_incarnation=$7
expected_pid=$8
expected_pgid=$9
shift 9
expected_start=$1
expected_executable=$2
expected_command=$3
expected_port=$4
path_count=$5
shift 5
[ "$#" -eq "$path_count" ] || exit 61
generation_root="$root/installations/$installation/generations/$generation"
marker="$generation_root/.xenix-generation"
receipt="$generation_root/.xenix-runtime"
stopped_receipt="$generation_root/.xenix-stopped"
token_file="$generation_root/.xenix-runtime-token"
provisioning="$generation_root/.xenix-provisioning"
stopped_provisioning_receipt="$generation_root/.xenix-provisioning-stopped"
retiring="$generation_root/.xenix-retiring"
retirement_intent="$retiring/intent"
control_lock="$generation_root/.xenix-control.lock"
[ -f "$root/.xenix-target" ] && [ "$(cat "$root/.xenix-target")" = "$target" ] || exit 4
[ -f "$marker" ] && [ "$(cat "$marker")" = "$(printf '%s\t%s\t%s\t%s' "$target" "$installation" "$generation" "$manifest")" ] || exit 4
[ -d "$retiring" ] && [ ! -L "$retiring" ] || exit 4
[ -f "$retirement_intent" ] && [ ! -L "$retirement_intent" ] || exit 4
[ "$(cat "$retirement_intent")" = "$(printf '%s\t%s\t%s\t%s' "$target" "$installation" "$generation" "$manifest")" ] || exit 4
if [ -e "$control_lock" ]; then
    [ -f "$control_lock" ] && [ ! -L "$control_lock" ] || exit 4
else
    # Only an exact, already-retiring legacy generation may lack the control
    # lock introduced after its receipt protocol.  Recreate it before taking
    # the same lock and rechecking the tombstone below.
    umask 077
    (set -C; : > "$control_lock") 2>/dev/null || true
    [ -f "$control_lock" ] && [ ! -L "$control_lock" ] || exit 4
fi
exec 9>"$control_lock"
flock 9
[ -d "$retiring" ] && [ ! -L "$retiring" ] || exit 4
[ -f "$retirement_intent" ] && [ ! -L "$retirement_intent" ] || exit 4
[ "$(cat "$retirement_intent")" = "$(printf '%s\t%s\t%s\t%s' "$target" "$installation" "$generation" "$manifest")" ] || exit 4
[ ! -e "$receipt" ] || exit 23
[ -f "$stopped_receipt" ] && [ ! -L "$stopped_receipt" ] || exit 4
receipt=$stopped_receipt
""" + "\n" + _READ_RECEIPT + "\n" + _READ_PROVISIONING_RECEIPT + "\n" + r"""
read_receipt || exit 4
[ "$r_installation" = "$installation" ] &&
[ "$r_generation" = "$generation" ] &&
[ "$r_manifest" = "$manifest" ] &&
[ "$r_owner" = "$expected_owner" ] &&
[ "$r_incarnation" = "$expected_incarnation" ] &&
[ "$r_pid" = "$expected_pid" ] &&
[ "$r_pgid" = "$expected_pgid" ] &&
[ "$r_start" = "$expected_start" ] &&
[ "$r_executable" = "$expected_executable" ] &&
[ "$r_command" = "$expected_command" ] &&
[ "$r_port" = "$expected_port" ] || exit 4
process_group_is_empty || exit 4
if [ -e "$provisioning" ]; then
    exit 4
fi
if [ -e "$stopped_provisioning_receipt" ]; then
    [ -f "$stopped_provisioning_receipt" ] && [ ! -L "$stopped_provisioning_receipt" ] || exit 4
    provisioning_receipt=$stopped_provisioning_receipt
    read_provisioning_receipt || exit 4
    [ "$r_installation" = "$installation" ] &&
    [ "$r_generation" = "$generation" ] &&
    [ "$r_manifest" = "$manifest" ] || exit 4
    provisioning_process_group_is_empty || exit 4
fi
if [ -e "$token_file" ]; then
    [ -f "$token_file" ] && [ ! -L "$token_file" ] || exit 4
    rm -- "$token_file"
fi
canonical_root=$(readlink -f -- "$generation_root") || exit 62
for relative in "$@"; do
    candidate="$generation_root/$relative"
    if [ -e "$candidate" ] || [ -L "$candidate" ]; then
        canonical_parent=$(readlink -f -- "${candidate%/*}") || exit 63
        case "$canonical_parent/" in
            "$canonical_root/"*) ;;
            *) exit 64 ;;
        esac
        rm -rf -- "$candidate"
    fi
done
for remaining in "$generation_root"/* "$generation_root"/.[!.]* "$generation_root"/..?*; do
    [ -e "$remaining" ] || [ -L "$remaining" ] || continue
    [ "$remaining" = "$marker" ] || [ "$remaining" = "$stopped_receipt" ] || [ "$remaining" = "$stopped_provisioning_receipt" ] || [ "$remaining" = "$retiring" ] || [ "$remaining" = "$control_lock" ] || exit 65
done
rm -- "$stopped_receipt"
if [ -e "$stopped_provisioning_receipt" ]; then
    rm -- "$stopped_provisioning_receipt"
fi
rm -- "$retirement_intent"
rmdir -- "$retiring"
rm -- "$control_lock"
rm -- "$marker"
rmdir -- "$generation_root"
""".strip()

_CLEANUP_PROVISIONED_SCRIPT = (
    r"""
set -eu
root=$1
target=$2
installation=$3
generation=$4
manifest=$5
path_count=$6
shift 6
[ "$#" -eq "$path_count" ] || exit 61
generation_root="$root/installations/$installation/generations/$generation"
marker="$generation_root/.xenix-generation"
receipt="$generation_root/.xenix-runtime"
stopped_receipt="$generation_root/.xenix-stopped"
provisioning="$generation_root/.xenix-provisioning"
stopped_provisioning_receipt="$generation_root/.xenix-provisioning-stopped"
retiring="$generation_root/.xenix-retiring"
retirement_intent="$retiring/intent"
control_lock="$generation_root/.xenix-control.lock"
[ -f "$root/.xenix-target" ] && [ "$(cat "$root/.xenix-target")" = "$target" ] || exit 4
[ -f "$marker" ] && [ "$(cat "$marker")" = "$(printf '%s\t%s\t%s\t%s' "$target" "$installation" "$generation" "$manifest")" ] || exit 4
[ -d "$retiring" ] && [ ! -L "$retiring" ] || exit 4
[ -f "$retirement_intent" ] && [ ! -L "$retirement_intent" ] || exit 4
[ "$(cat "$retirement_intent")" = "$(printf '%s\t%s\t%s\t%s' "$target" "$installation" "$generation" "$manifest")" ] || exit 4
if [ -e "$control_lock" ]; then
    [ -f "$control_lock" ] && [ ! -L "$control_lock" ] || exit 4
else
    umask 077
    (set -C; : > "$control_lock") 2>/dev/null || true
    [ -f "$control_lock" ] && [ ! -L "$control_lock" ] || exit 4
fi
exec 9>"$control_lock"
flock 9
[ -d "$retiring" ] && [ ! -L "$retiring" ] || exit 4
[ -f "$retirement_intent" ] && [ ! -L "$retirement_intent" ] || exit 4
[ "$(cat "$retirement_intent")" = "$(printf '%s\t%s\t%s\t%s' "$target" "$installation" "$generation" "$manifest")" ] || exit 4
[ ! -e "$receipt" ] || exit 3
[ ! -e "$stopped_receipt" ] || exit 3
[ ! -e "$provisioning" ] || exit 4
[ -e "$stopped_provisioning_receipt" ] || exit 3
[ -f "$stopped_provisioning_receipt" ] && [ ! -L "$stopped_provisioning_receipt" ] || exit 4
provisioning_receipt=$stopped_provisioning_receipt
"""
    + "\n"
    + _READ_PROVISIONING_RECEIPT
    + r"""
read_provisioning_receipt || exit 4
[ "$r_installation" = "$installation" ] &&
[ "$r_generation" = "$generation" ] &&
[ "$r_manifest" = "$manifest" ] || exit 4
provisioning_process_group_is_empty || exit 4
canonical_root=$(readlink -f -- "$generation_root") || exit 62
for relative in "$@"; do
    candidate="$generation_root/$relative"
    if [ -e "$candidate" ] || [ -L "$candidate" ]; then
        canonical_parent=$(readlink -f -- "${candidate%/*}") || exit 63
        case "$canonical_parent/" in
            "$canonical_root/"*) ;;
            *) exit 64 ;;
        esac
        rm -rf -- "$candidate"
    fi
done
for remaining in "$generation_root"/* "$generation_root"/.[!.]* "$generation_root"/..?*; do
    [ -e "$remaining" ] || [ -L "$remaining" ] || continue
    [ "$remaining" = "$marker" ] || [ "$remaining" = "$stopped_provisioning_receipt" ] || [ "$remaining" = "$retiring" ] || [ "$remaining" = "$control_lock" ] || exit 65
done
rm -- "$stopped_provisioning_receipt"
rm -- "$retirement_intent"
rmdir -- "$retiring"
rm -- "$control_lock"
rm -- "$marker"
rmdir -- "$generation_root"
"""
).strip()

_CLEANUP_EMPTY_GENERATION_SCRIPT = r"""
set -eu
root=$1
target=$2
installation=$3
generation=$4
manifest=$5
generation_root="$root/installations/$installation/generations/$generation"
marker="$generation_root/.xenix-generation"
receipt="$generation_root/.xenix-runtime"
stopped_receipt="$generation_root/.xenix-stopped"
provisioning="$generation_root/.xenix-provisioning"
stopped_provisioning_receipt="$generation_root/.xenix-provisioning-stopped"
retiring="$generation_root/.xenix-retiring"
retirement_intent="$retiring/intent"
control_lock="$generation_root/.xenix-control.lock"
[ -f "$root/.xenix-target" ] && [ "$(cat "$root/.xenix-target")" = "$target" ] || exit 4
[ -f "$marker" ] && [ "$(cat "$marker")" = "$(printf '%s\t%s\t%s\t%s' "$target" "$installation" "$generation" "$manifest")" ] || exit 4
[ -d "$retiring" ] && [ ! -L "$retiring" ] || exit 4
[ -f "$retirement_intent" ] && [ ! -L "$retirement_intent" ] || exit 4
[ "$(cat "$retirement_intent")" = "$(printf '%s\t%s\t%s\t%s' "$target" "$installation" "$generation" "$manifest")" ] || exit 4
if [ -e "$control_lock" ]; then
    [ -f "$control_lock" ] && [ ! -L "$control_lock" ] || exit 4
else
    umask 077
    (set -C; : > "$control_lock") 2>/dev/null || true
    [ -f "$control_lock" ] && [ ! -L "$control_lock" ] || exit 4
fi
exec 9>"$control_lock"
flock 9
[ -d "$retiring" ] && [ ! -L "$retiring" ] || exit 4
[ -f "$retirement_intent" ] && [ ! -L "$retirement_intent" ] || exit 4
[ "$(cat "$retirement_intent")" = "$(printf '%s\t%s\t%s\t%s' "$target" "$installation" "$generation" "$manifest")" ] || exit 4
[ ! -e "$receipt" ] || exit 3
[ ! -e "$stopped_receipt" ] || exit 3
[ ! -e "$provisioning" ] || exit 3
[ ! -e "$stopped_provisioning_receipt" ] || exit 3
for remaining in "$generation_root"/* "$generation_root"/.[!.]* "$generation_root"/..?*; do
    [ -e "$remaining" ] || [ -L "$remaining" ] || continue
    [ "$remaining" = "$marker" ] || [ "$remaining" = "$retiring" ] || [ "$remaining" = "$control_lock" ] || exit 65
done
rm -- "$retirement_intent"
rmdir -- "$retiring"
rm -- "$control_lock"
rm -- "$marker"
rmdir -- "$generation_root"
""".strip()


__all__ = [
    "ProtectedRuntimeSecret",
    "RemoteCleanupRefusedError",
    "RemoteEnvironmentSetting",
    "RemoteGenerationIdentity",
    "RemoteLaunchSpec",
    "RemoteProcessConflictError",
    "RemoteProcessIdentityError",
    "RemoteProcessObservation",
    "RemoteScriptResult",
    "RemoteScriptRunner",
    "RemoteSupervisor",
    "RemoteSupervisorError",
    "UnsupportedRemoteTargetError",
]
