"""Private OpenSSH placement for long-lived, authenticated AMD runtimes."""

from __future__ import annotations

import hashlib
import ipaddress
import os
import re
import secrets
import shlex
import socket
import subprocess
import tempfile
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from pathlib import PurePosixPath
from typing import Protocol

from ..placement import (
    AmdPlacementError,
    AmdRuntimeKey,
    LoopbackHttpBinding,
    RuntimeIncarnation,
)
from ..compatibility import TargetCompatibilityFacts
from ..remote_supervisor import (
    ProtectedRuntimeSecret,
    RemoteGenerationIdentity,
    RemoteLaunchSpec,
    RemoteProcessObservation,
    RemoteScriptResult,
    RemoteSupervisor,
)

_SSH_ALIAS = "xenix-managed-target"
_TARGET_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+-]{0,159}$")
_SSH_USER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_DNS_LABEL = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")
_HOST_KEY_TYPE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9@._+-]{0,127}$")
_HOST_KEY_DATA = re.compile(r"^[A-Za-z0-9+/]+={0,3}$")
_MAX_SSH_OUTPUT = 64 * 1_024


class SshPlacementError(AmdPlacementError):
    """OpenSSH placement failed without exposing target or credential material."""

    error_code = "amd_ssh_operation_failed"


class SshTargetResolutionError(SshPlacementError):
    """An immutable target or one of its local security handles was unavailable."""

    error_code = "amd_ssh_target_unavailable"


class SshClientUnavailableError(SshPlacementError):
    """The supported OpenSSH client is absent or cannot be started."""

    error_code = "amd_ssh_client_unavailable"


class SshHostTrustError(SshPlacementError):
    """Pinned host trust did not match exactly."""

    error_code = "amd_ssh_host_trust_failed"


class SshAuthenticationError(SshPlacementError):
    """Public-key authentication failed without an allowed fallback."""

    error_code = "amd_ssh_authentication_failed"


class SshConnectionError(SshPlacementError):
    """The enrolled target could not sustain an SSH connection."""

    error_code = "amd_ssh_connection_failed"


class SshCommandTimeoutError(SshConnectionError):
    """A bounded SSH operation exceeded its deadline."""

    error_code = "amd_ssh_connection_timeout"


class SshForwardError(SshConnectionError):
    """A loopback forward could not be established or was lost."""

    error_code = "amd_ssh_forward_failed"


@dataclass(frozen=True, slots=True)
class SshTargetEnrollment:
    """Immutable AMD-private target snapshot resolved from its durable ID."""

    target_id: str
    host: str = field(repr=False)
    user: str = field(repr=False)
    port: int = field(repr=False)
    pinned_host_key_reference: str = field(repr=False)
    identity_file_reference: str = field(repr=False)

    def __post_init__(self) -> None:
        _require_target_id(self.target_id)
        _require_host(self.host)
        if not isinstance(self.user, str) or not _SSH_USER.fullmatch(self.user):
            raise SshTargetResolutionError(
                "SSH target user is invalid.",
                error_code="amd_ssh_user_invalid",
            )
        if (
            not isinstance(self.port, int)
            or isinstance(self.port, bool)
            or not 1 <= self.port <= 65_535
        ):
            raise SshTargetResolutionError(
                "SSH target port is invalid.",
                error_code="amd_ssh_port_invalid",
            )
        _require_opaque_reference(self.pinned_host_key_reference, "Pinned host-key reference")
        _require_opaque_reference(self.identity_file_reference, "Identity-file reference")


@dataclass(frozen=True, slots=True)
class ResolvedSshIdentity:
    """Ephemeral local identity handle; private-key bytes never enter this API."""

    identity_file: Path = field(repr=False)

    def __post_init__(self) -> None:
        path = Path(self.identity_file)
        if not path.is_absolute():
            raise SshTargetResolutionError(
                "Resolved SSH identity is invalid.",
                error_code="amd_ssh_identity_invalid",
            )
        object.__setattr__(self, "identity_file", path)


@dataclass(frozen=True, slots=True)
class PinnedHostKey:
    """Exact OpenSSH public host key without a mutable hostname prefix."""

    key_type: str = field(repr=False)
    key_data: str = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.key_type, str) or not _HOST_KEY_TYPE.fullmatch(self.key_type):
            raise SshTargetResolutionError("Pinned SSH host-key type is invalid.")
        if (
            not isinstance(self.key_data, str)
            or len(self.key_data) > 16_384
            or not _HOST_KEY_DATA.fullmatch(self.key_data)
        ):
            raise SshTargetResolutionError("Pinned SSH host-key data is invalid.")


class SshTargetResolver(Protocol):
    """Resolve only the immutable target named by an installation."""

    def resolve_target(self, target_id: str) -> SshTargetEnrollment: ...


class SshCredentialResolver(Protocol):
    """Resolve an opaque credential reference to a short-lived local handle."""

    def resolve_identity(self, identity_file_reference: str) -> ResolvedSshIdentity: ...


class SshTrustResolver(Protocol):
    """Resolve an enrolled trust reference without TOFU or network discovery."""

    def resolve_host_key(self, pinned_host_key_reference: str) -> PinnedHostKey: ...


@dataclass(frozen=True, slots=True)
class OpenSshCommandResult:
    return_code: int
    stdout: bytes = field(repr=False, default=b"")
    stderr: bytes = field(repr=False, default=b"")


class LocalSshProcess(Protocol):
    @property
    def pid(self) -> int: ...

    def poll(self) -> int | None: ...

    def terminate(self) -> None: ...

    def kill(self) -> None: ...

    def wait(self, timeout: float | None = None) -> int: ...


class OpenSshProcessRunner(Protocol):
    """Injectable local process boundary for deterministic placement tests."""

    def run(
        self,
        arguments: Sequence[str],
        *,
        stdin: bytes | None,
        timeout_seconds: float,
        environment: Mapping[str, str],
    ) -> OpenSshCommandResult: ...

    def start(
        self,
        arguments: Sequence[str],
        *,
        environment: Mapping[str, str],
    ) -> LocalSshProcess: ...


class SubprocessOpenSshRunner:
    """Production runner.  Raw process output remains inside the placement."""

    def run(
        self,
        arguments: Sequence[str],
        *,
        stdin: bytes | None,
        timeout_seconds: float,
        environment: Mapping[str, str],
    ) -> OpenSshCommandResult:
        try:
            completed = subprocess.run(
                tuple(arguments),
                input=stdin,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=timeout_seconds,
                env=dict(environment),
                creationflags=_no_window_creation_flags(),
            )
        except subprocess.TimeoutExpired:
            raise SshCommandTimeoutError("SSH operation exceeded its deadline.") from None
        except OSError:
            raise SshClientUnavailableError("OpenSSH client could not be started.") from None
        return OpenSshCommandResult(
            return_code=completed.returncode,
            stdout=completed.stdout[: _MAX_SSH_OUTPUT + 1],
            stderr=completed.stderr[: _MAX_SSH_OUTPUT + 1],
        )

    def start(
        self,
        arguments: Sequence[str],
        *,
        environment: Mapping[str, str],
    ) -> LocalSshProcess:
        try:
            return subprocess.Popen(
                tuple(arguments),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=dict(environment),
                creationflags=_no_window_creation_flags(),
            )
        except OSError:
            raise SshClientUnavailableError("OpenSSH client could not be started.") from None


class _IsolatedOpenSshMaterial:
    """Ephemeral config keeps sensitive paths out of the OpenSSH command line."""

    def __init__(
        self,
        enrollment: SshTargetEnrollment,
        identity: ResolvedSshIdentity,
        host_key: PinnedHostKey,
        *,
        temporary_parent: Path | None,
        connect_timeout_seconds: int,
        keepalive_interval_seconds: int,
        keepalive_failures: int,
    ) -> None:
        if not identity.identity_file.is_file():
            raise SshTargetResolutionError(
                "Resolved SSH identity is unavailable.",
                error_code="amd_ssh_identity_unavailable",
            )
        try:
            self._temporary = tempfile.TemporaryDirectory(
                prefix="xenix-amd-ssh-",
                dir=None if temporary_parent is None else os.fspath(temporary_parent),
            )
        except OSError:
            raise SshTargetResolutionError("Isolated SSH security material could not be created.") from None
        directory = Path(self._temporary.name)
        self.config_path = directory / "ssh_config"
        known_hosts_path = directory / "known_hosts"
        global_known_hosts_path = directory / "global_known_hosts"
        host_pattern = _known_host_pattern(enrollment.host, enrollment.port)
        _write_private_text(
            known_hosts_path,
            f"{host_pattern} {host_key.key_type} {host_key.key_data}\n",
        )
        _write_private_text(global_known_hosts_path, "")
        identity_path = _quote_ssh_config_value(os.fspath(identity.identity_file).replace("\\", "/"))
        lines = (
            f"Host {_SSH_ALIAS}",
            f"    HostName {_quote_ssh_config_value(enrollment.host)}",
            f"    User {_quote_ssh_config_value(enrollment.user)}",
            f"    Port {enrollment.port}",
            f"    IdentityFile {identity_path}",
            "    IdentitiesOnly yes",
            "    IdentityAgent none",
            "    AddKeysToAgent no",
            "    BatchMode yes",
            "    PasswordAuthentication no",
            "    KbdInteractiveAuthentication no",
            "    PubkeyAuthentication yes",
            "    PreferredAuthentications publickey",
            "    StrictHostKeyChecking yes",
            "    CheckHostIP no",
            f"    UserKnownHostsFile {_quote_ssh_config_value(known_hosts_path.as_posix())}",
            f"    GlobalKnownHostsFile {_quote_ssh_config_value(global_known_hosts_path.as_posix())}",
            "    UpdateHostKeys no",
            "    VerifyHostKeyDNS no",
            "    HashKnownHosts no",
            "    ForwardAgent no",
            "    ForwardX11 no",
            "    PermitLocalCommand no",
            "    ProxyCommand none",
            "    ProxyJump none",
            "    CanonicalizeHostname no",
            "    RequestTTY no",
            "    LogLevel ERROR",
            "    ConnectionAttempts 3",
            f"    ConnectTimeout {connect_timeout_seconds}",
            f"    ServerAliveInterval {keepalive_interval_seconds}",
            f"    ServerAliveCountMax {keepalive_failures}",
            "    ExitOnForwardFailure yes",
            "",
        )
        _write_private_text(self.config_path, "\n".join(lines))

    def close(self) -> None:
        self._temporary.cleanup()


class OpenSshTransport:
    """Isolated OpenSSH command/forward implementation for one enrollment."""

    def __init__(
        self,
        material: _IsolatedOpenSshMaterial,
        *,
        executable: str,
        process_runner: OpenSshProcessRunner,
        forward_attempts: int,
        forward_start_grace_seconds: float,
        forward_stop_grace_seconds: float,
    ) -> None:
        if not executable or "\x00" in executable or "\r" in executable or "\n" in executable:
            raise SshClientUnavailableError("OpenSSH executable is invalid.")
        if not 1 <= forward_attempts <= 20:
            raise SshPlacementError("SSH forward retry policy is invalid.")
        _require_short_deadline(forward_start_grace_seconds, maximum=5.0)
        _require_short_deadline(forward_stop_grace_seconds, maximum=10.0)
        self._material = material
        self._executable = executable
        self._runner = process_runner
        self._forward_attempts = forward_attempts
        self._forward_start_grace_seconds = forward_start_grace_seconds
        self._forward_stop_grace_seconds = forward_stop_grace_seconds
        self._environment = _isolated_ssh_environment()

    def probe(self, *, timeout_seconds: float = 15.0) -> None:
        result = self.run_script(
            "set -eu\nprintf 'xenix-ssh-v1\\n'",
            timeout_seconds=timeout_seconds,
        )
        if result.stdout != b"xenix-ssh-v1\n":
            raise SshConnectionError("SSH target returned an invalid transport probe.")

    def run_script(
        self,
        script: str,
        arguments: tuple[str, ...] = (),
        *,
        stdin: bytes | None = None,
        timeout_seconds: float,
    ) -> RemoteScriptResult:
        _require_remote_script(script)
        _require_process_deadline(timeout_seconds)
        remote_command = shlex.join(("sh", "-c", script, "--", *arguments))
        result = self._runner.run(
            (*self._base_arguments(), _SSH_ALIAS, remote_command),
            stdin=stdin,
            timeout_seconds=timeout_seconds,
            environment=self._environment,
        )
        if len(result.stdout) > _MAX_SSH_OUTPUT or len(result.stderr) > _MAX_SSH_OUTPUT:
            raise SshConnectionError("SSH target output exceeded its safety bound.")
        if result.return_code == 255 or result.return_code < 0:
            raise _classified_ssh_error(result.stderr)
        return RemoteScriptResult(return_code=result.return_code, stdout=result.stdout)

    def open_loopback_forward(self, remote_port: int) -> LocalLoopbackForward:
        if (
            not isinstance(remote_port, int)
            or isinstance(remote_port, bool)
            or not 1_024 <= remote_port <= 65_535
        ):
            raise SshForwardError("Remote loopback port is invalid.")
        for _attempt in range(self._forward_attempts):
            local_port = _allocate_loopback_port()
            arguments = (
                *self._base_arguments(),
                "-N",
                "-T",
                "-L",
                f"127.0.0.1:{local_port}:127.0.0.1:{remote_port}",
                _SSH_ALIAS,
            )
            process = self._runner.start(arguments, environment=self._environment)
            forward = LocalLoopbackForward(
                process,
                arguments=arguments,
                local_port=local_port,
                remote_port=remote_port,
                stop_grace_seconds=self._forward_stop_grace_seconds,
            )
            if self._forward_start_grace_seconds:
                threading.Event().wait(self._forward_start_grace_seconds)
            if forward.is_alive:
                return forward
            forward.close()
        raise SshForwardError("No local loopback port could establish the SSH forward.")

    def _base_arguments(self) -> tuple[str, ...]:
        return (
            self._executable,
            "-F",
            os.fspath(self._material.config_path),
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            "IdentitiesOnly=yes",
            "-o",
            "IdentityAgent=none",
            "-o",
            "PasswordAuthentication=no",
            "-o",
            "KbdInteractiveAuthentication=no",
            "-o",
            "PreferredAuthentications=publickey",
            "-o",
            "ForwardAgent=no",
        )


class LocalLoopbackForward:
    """Exact local process handle for one forward; its PID is not authority."""

    def __init__(
        self,
        process: LocalSshProcess,
        *,
        arguments: Sequence[str],
        local_port: int,
        remote_port: int,
        stop_grace_seconds: float,
    ) -> None:
        if process.pid <= 0:
            raise SshForwardError("SSH forward process identity is invalid.")
        self._process = process
        self._process_id = process.pid
        self._arguments = tuple(arguments)
        self._command_fingerprint = _local_command_fingerprint(self._arguments)
        self._stop_grace_seconds = stop_grace_seconds
        self.local_port = local_port
        self.remote_port = remote_port

    @property
    def is_alive(self) -> bool:
        return (
            self._process.pid == self._process_id
            and self._command_fingerprint == _local_command_fingerprint(self._arguments)
            and self._process.poll() is None
        )

    def close(self) -> None:
        if not self.is_alive:
            return
        self._process.terminate()
        try:
            self._process.wait(timeout=self._stop_grace_seconds)
        except subprocess.TimeoutExpired:
            if not self.is_alive:
                return
            self._process.kill()
            try:
                self._process.wait(timeout=self._stop_grace_seconds)
            except subprocess.TimeoutExpired:
                raise SshForwardError("SSH forward did not stop within its bounded reap policy.") from None


@dataclass(slots=True)
class _LiveRealization:
    observation: RemoteProcessObservation = field(repr=False)
    forward: LocalLoopbackForward = field(repr=False)
    binding: LoopbackHttpBinding = field(repr=False)


class SshAmdExecutionSession:
    """One controller incarnation over one immutable enrolled SSH target."""

    def __init__(
        self,
        *,
        incarnation: RuntimeIncarnation,
        transport: OpenSshTransport,
        supervisor: RemoteSupervisor,
        material: _IsolatedOpenSshMaterial,
        token_factory: Callable[[], str],
        target_root: str,
    ) -> None:
        self._incarnation = incarnation
        self._transport = transport
        self._supervisor = supervisor
        self._material = material
        self._token_factory = token_factory
        self._target_root = target_root
        self._realizations: dict[AmdRuntimeKey, _LiveRealization] = {}
        self._stopped: dict[AmdRuntimeKey, RemoteProcessObservation] = {}
        self._closed = False

    @property
    def incarnation(self) -> RuntimeIncarnation:
        return self._incarnation

    @property
    def target_root(self) -> str:
        """Ephemeral, derived target root; never persist this observation."""

        return self._target_root

    def realize(self, spec: RemoteLaunchSpec) -> LoopbackHttpBinding:
        """Start and forward one exact generation using a fresh in-memory secret."""

        self._require_open()
        if spec.generation.incarnation != self._incarnation:
            raise SshPlacementError("Remote launch incarnation does not belong to this session.")
        key = spec.generation.runtime_key
        existing = self._realizations.get(key)
        if existing is not None:
            if existing.observation.matches(spec) and existing.forward.is_alive:
                return existing.binding
            raise SshPlacementError("A different live realization already owns this runtime key.")

        token = self._token_factory()
        secret = ProtectedRuntimeSecret(token)
        observation = self._supervisor.start(spec, secret)
        try:
            forward = self._transport.open_loopback_forward(spec.remote_loopback_port)
        except Exception:
            try:
                self._supervisor.stop(observation)
            except AmdPlacementError:
                pass
            raise
        binding = LoopbackHttpBinding(
            base_url=f"http://127.0.0.1:{forward.local_port}",
            bearer_token=token,
        )
        self._realizations[key] = _LiveRealization(
            observation=observation,
            forward=forward,
            binding=binding,
        )
        return binding

    def prepare_recipe_root(self, generation: RemoteGenerationIdentity) -> str:
        """Prepare an owned generation root before its non-secret recipe runs."""

        self._require_open()
        if generation.incarnation != self._incarnation:
            raise SshPlacementError("Remote recipe incarnation does not belong to this session.")
        return self._supervisor.prepare_recipe_root(generation)

    def run_generation_recipe(
        self,
        generation: RemoteGenerationIdentity,
        script: str,
        arguments: tuple[str, ...] = (),
        *,
        stdin: bytes | None = None,
        timeout_seconds: float,
    ) -> RemoteScriptResult:
        """Run only a bundled non-secret recipe for this exact incarnation."""

        self._require_open()
        if generation.incarnation != self._incarnation:
            raise SshPlacementError("Remote recipe incarnation does not belong to this session.")
        return self._supervisor.run_generation_recipe(
            generation,
            script,
            arguments,
            stdin=stdin,
            timeout_seconds=timeout_seconds,
        )

    def resolve_process_executable(self, command_executable: str) -> str:
        """Resolve the target's ``/proc`` executable spelling without persisting it."""

        self._require_open()
        if not isinstance(command_executable, str) or not command_executable.startswith("/"):
            raise SshPlacementError("Remote command executable is invalid.")
        result = self._transport.run_script(
            "set -eu\nreadlink -f -- \"$1\"",
            (command_executable,),
            timeout_seconds=15.0,
        )
        if result.return_code != 0 or len(result.stdout) > 4_096:
            raise SshPlacementError("Remote command executable could not be resolved.")
        try:
            value = result.stdout.decode("utf-8", errors="strict").removesuffix("\n")
        except UnicodeDecodeError:
            raise SshPlacementError("Remote command executable could not be resolved.") from None
        if not value.startswith("/") or "\n" in value or "\r" in value or "\x00" in value:
            raise SshPlacementError("Remote command executable could not be resolved.")
        return value

    def allocate_remote_loopback_port(self) -> int:
        """Reserve no state; return a freshly probed remote loopback port candidate."""

        self._require_open()
        result = self._transport.run_script(
            "set -eu\npython3 -c 'import socket; s=socket.socket(); s.bind((\"127.0.0.1\", 0)); print(s.getsockname()[1]); s.close()'",
            timeout_seconds=15.0,
        )
        if result.return_code != 0 or len(result.stdout) > 16:
            raise SshPlacementError("Remote loopback port could not be allocated.")
        try:
            value = int(result.stdout.decode("ascii", errors="strict").strip())
        except (UnicodeDecodeError, ValueError):
            raise SshPlacementError("Remote loopback port could not be allocated.") from None
        if not 1_024 <= value <= 65_535:
            raise SshPlacementError("Remote loopback port could not be allocated.")
        return value

    def observe_target_facts(self) -> TargetCompatibilityFacts:
        """Collect only redacted compatibility facts for this already trusted target."""

        self._require_open()
        result = self._transport.run_script(
            _TARGET_FACTS_SCRIPT,
            (self._target_root,),
            timeout_seconds=30.0,
        )
        if result.return_code != 0 or len(result.stdout) > 8_192:
            raise SshPlacementError("Remote target compatibility facts could not be observed.")
        return _parse_target_facts(result.stdout)

    def resolve_binding(self, key: AmdRuntimeKey) -> LoopbackHttpBinding:
        """Resolve only while both the SSH forward and exact remote identity live."""

        self._require_open()
        realization = self._realizations.get(key)
        if realization is None:
            raise SshForwardError("Managed SSH runtime binding is unavailable.")
        if not realization.forward.is_alive:
            self._realizations.pop(key, None)
            raise SshForwardError("Managed SSH runtime binding was disconnected.")
        try:
            observed = self._supervisor.observe(realization.observation.generation)
        except SshConnectionError:
            # A failed read-only identity probe says nothing about the remote
            # process identity.  Do not authorize this request, but retain the
            # still-live forward so a later probe can re-establish certainty.
            # Destroying it here would turn one transient SSH front-door drop
            # into an unrecoverable live remote realization.
            if not realization.forward.is_alive:
                self._realizations.pop(key, None)
            raise SshForwardError("Managed SSH runtime identity could not be revalidated.") from None
        except AmdPlacementError:
            realization.forward.close()
            self._realizations.pop(key, None)
            raise SshForwardError("Managed SSH runtime identity could not be revalidated.") from None
        if observed != realization.observation:
            realization.forward.close()
            self._realizations.pop(key, None)
            raise SshForwardError("Managed SSH runtime identity changed.")
        return realization.binding

    def stop(self, key: AmdRuntimeKey) -> None:
        """Stop one realization only through its captured exact identity."""

        self._require_open()
        realization = self._realizations.get(key)
        if realization is None:
            return
        realization.forward.close()
        self._supervisor.stop(realization.observation)
        self._realizations.pop(key, None)
        self._stopped[key] = realization.observation

    def cleanup_generation(
        self,
        generation: RemoteGenerationIdentity,
        owned_relative_paths: tuple[str, ...],
    ) -> None:
        self._require_open()
        if generation.incarnation != self._incarnation:
            raise SshPlacementError("Remote cleanup incarnation does not belong to this session.")
        if generation.runtime_key in self._realizations:
            raise SshPlacementError("A live runtime cannot be cleaned.")
        observation = self._stopped.get(generation.runtime_key)
        if observation is None or observation.generation != generation:
            raise SshPlacementError("Remote cleanup lacks an exact stopped-process fence.")
        self._supervisor.cleanup_generation(observation, owned_relative_paths)
        self._stopped.pop(generation.runtime_key, None)

    def cancel_generation_provisioning(
        self,
        *,
        key: AmdRuntimeKey,
        manifest_digest: str,
    ) -> None:
        """Use only committed retirement authority to stop an unfinished recipe."""

        self._require_open()
        self._supervisor.cancel_provisioning_for_retirement(
            runtime_key=key,
            manifest_digest=manifest_digest,
        )

    def retire_and_cleanup_generation(
        self,
        *,
        key: AmdRuntimeKey,
        manifest_digest: str,
        owned_relative_paths: tuple[str, ...],
    ) -> None:
        """Stop and remove one generation with an exact current or recovered fence.

        An application restart intentionally loses the prior session and its
        bearer token.  That absence is not deletion authority: the remote
        supervisor must recover the old receipt, prove the process (if live),
        stop it, and then use its own stopped receipt for cleanup.
        """

        self._require_open()
        self._supervisor.cancel_provisioning_for_retirement(
            runtime_key=key,
            manifest_digest=manifest_digest,
        )
        if self._supervisor.cleanup_provisioned_generation(
            runtime_key=key,
            manifest_digest=manifest_digest,
            owned_relative_paths=owned_relative_paths,
        ):
            return
        if self._supervisor.cleanup_empty_generation(
            runtime_key=key,
            manifest_digest=manifest_digest,
        ):
            return
        if key in self._realizations:
            self.stop(key)
        observation = self._stopped.get(key)
        if observation is None:
            observation = self._supervisor.recover_stopped_observation(
                runtime_key=key,
                manifest_digest=manifest_digest,
            )
        if (
            observation.generation.runtime_key != key
            or observation.generation.manifest_digest != manifest_digest
        ):
            raise SshPlacementError("Recovered remote generation identity changed.")
        self._supervisor.cleanup_generation(observation, owned_relative_paths)
        self._stopped.pop(key, None)

    def close(self) -> None:
        if self._closed:
            return
        failures = False
        for key in tuple(self._realizations):
            realization = self._realizations[key]
            try:
                realization.forward.close()
                self._supervisor.stop(realization.observation)
                self._realizations.pop(key, None)
                self._stopped[key] = realization.observation
            except AmdPlacementError:
                # A remote child can already be a zombie when its SSH parent
                # reaps slowly.  It has no runnable process identity, so the
                # supervisor may safely fence its existing receipt into the
                # stopped form; do not leave the close path falsely blocked.
                try:
                    self._supervisor.reap_stale_receipt(realization.observation.generation)
                except AmdPlacementError:
                    failures = True
                    continue
                self._realizations.pop(key, None)
                self._stopped[key] = realization.observation
        self._closed = True
        self._material.close()
        if failures:
            raise SshPlacementError("One or more exact SSH realizations could not be stopped safely.")

    def _require_open(self) -> None:
        if self._closed:
            raise SshPlacementError("SSH execution session is closed.")


class PrivateSshAmdPlacement:
    """Resolve an immutable enrollment into a private execution session."""

    def __init__(
        self,
        *,
        target_resolver: SshTargetResolver,
        credential_resolver: SshCredentialResolver,
        trust_resolver: SshTrustResolver,
        remote_root_suffix: str = ".local/share/Xenix/amd-runtime",
        ssh_executable: str = "ssh",
        process_runner: OpenSshProcessRunner | None = None,
        temporary_parent: Path | None = None,
        token_factory: Callable[[], str] | None = None,
        connect_timeout_seconds: int = 10,
        keepalive_interval_seconds: int = 5,
        keepalive_failures: int = 3,
        forward_attempts: int = 5,
        forward_start_grace_seconds: float = 0.15,
        forward_stop_grace_seconds: float = 2.0,
    ) -> None:
        if not 1 <= connect_timeout_seconds <= 60:
            raise SshPlacementError("SSH connect timeout is invalid.")
        if not 1 <= keepalive_interval_seconds <= 60 or not 1 <= keepalive_failures <= 10:
            raise SshPlacementError("SSH keepalive policy is invalid.")
        self._target_resolver = target_resolver
        self._credential_resolver = credential_resolver
        self._trust_resolver = trust_resolver
        self._remote_root_suffix = _require_remote_root_suffix(remote_root_suffix)
        self._ssh_executable = ssh_executable
        self._process_runner = process_runner or SubprocessOpenSshRunner()
        self._temporary_parent = temporary_parent
        self._token_factory = token_factory or (lambda: secrets.token_urlsafe(32))
        self._connect_timeout_seconds = connect_timeout_seconds
        self._keepalive_interval_seconds = keepalive_interval_seconds
        self._keepalive_failures = keepalive_failures
        self._forward_attempts = forward_attempts
        self._forward_start_grace_seconds = forward_start_grace_seconds
        self._forward_stop_grace_seconds = forward_stop_grace_seconds

    def open_session(
        self,
        target_id: str,
        incarnation: RuntimeIncarnation,
    ) -> SshAmdExecutionSession:
        """Resolve security handles, then perform only read-only preflight probes."""

        _require_target_id(target_id)
        try:
            enrollment = self._target_resolver.resolve_target(target_id)
            if enrollment.target_id != target_id:
                raise SshTargetResolutionError("Resolved SSH target identity changed.")
            identity = self._credential_resolver.resolve_identity(enrollment.identity_file_reference)
            host_key = self._trust_resolver.resolve_host_key(enrollment.pinned_host_key_reference)
        except SshPlacementError:
            raise
        except Exception:
            raise SshTargetResolutionError("SSH target security material could not be resolved.") from None

        material = _IsolatedOpenSshMaterial(
            enrollment,
            identity,
            host_key,
            temporary_parent=self._temporary_parent,
            connect_timeout_seconds=self._connect_timeout_seconds,
            keepalive_interval_seconds=self._keepalive_interval_seconds,
            keepalive_failures=self._keepalive_failures,
        )
        transport = OpenSshTransport(
            material,
            executable=self._ssh_executable,
            process_runner=self._process_runner,
            forward_attempts=self._forward_attempts,
            forward_start_grace_seconds=self._forward_start_grace_seconds,
            forward_stop_grace_seconds=self._forward_stop_grace_seconds,
        )
        try:
            transport.probe()
            target_root = _resolve_target_root(transport, self._remote_root_suffix)
            supervisor = RemoteSupervisor(
                transport,
                target_id=target_id,
                product_root=target_root,
            )
            supervisor.probe_prerequisites()
        except Exception:
            material.close()
            raise
        return SshAmdExecutionSession(
            incarnation=incarnation,
            transport=transport,
            supervisor=supervisor,
            material=material,
            token_factory=self._token_factory,
            target_root=target_root,
        )


def _require_target_id(value: str) -> None:
    if not isinstance(value, str) or not _TARGET_ID.fullmatch(value):
        raise SshTargetResolutionError(
            "SSH target ID is invalid.",
            error_code="amd_ssh_target_id_invalid",
        )


def _require_host(value: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 253
        or value != value.strip()
        or value.startswith("-")
        or any(character.isspace() or ord(character) < 0x21 or ord(character) == 0x7F for character in value)
    ):
        raise SshTargetResolutionError(
            "SSH target host is invalid.",
            error_code="amd_ssh_host_invalid",
        )
    try:
        ipaddress.ip_address(value)
    except ValueError:
        dns_name = value[:-1] if value.endswith(".") else value
        if not dns_name or any(not _DNS_LABEL.fullmatch(label) for label in dns_name.split(".")):
            raise SshTargetResolutionError(
                "SSH target host is invalid.",
                error_code="amd_ssh_host_invalid",
            ) from None


def _require_opaque_reference(value: str, label: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 1_024
        or value != value.strip()
        or "\x00" in value
        or "\r" in value
        or "\n" in value
    ):
        raise SshTargetResolutionError(f"{label} is invalid.")


def _require_remote_root_suffix(value: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 256 or "\x00" in value:
        raise SshTargetResolutionError("Managed target root suffix is invalid.")
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or ".." in path.parts or any(part in {"", "."} for part in path.parts):
        raise SshTargetResolutionError("Managed target root suffix is invalid.")
    return str(path)


def _resolve_target_root(transport: OpenSshTransport, suffix: str) -> str:
    result = transport.run_script(
        "set -eu\nprintf '%s\\n' \"$HOME\"",
        timeout_seconds=15.0,
    )
    if result.return_code != 0 or len(result.stdout) > 1_024:
        raise SshTargetResolutionError("Managed target home directory could not be resolved.")
    try:
        text = result.stdout.decode("utf-8", errors="strict")
        home = text.removesuffix("\n")
    except UnicodeDecodeError:
        raise SshTargetResolutionError("Managed target home directory could not be resolved.") from None
    if not home or "\n" in home or "\r" in home:
        raise SshTargetResolutionError("Managed target home directory could not be resolved.")
    home_path = PurePosixPath(home)
    if not home_path.is_absolute() or ".." in home_path.parts or str(home_path) in {"/", "/home"}:
        raise SshTargetResolutionError("Managed target home directory is unsafe.")
    return str(home_path / suffix)


def _parse_target_facts(payload: bytes) -> TargetCompatibilityFacts:
    try:
        text = payload.decode("utf-8", errors="strict")
        values: dict[str, str] = {}
        for line in text.splitlines():
            key, value = line.split("\t", 1)
            if key in values or not value or "\t" in value:
                raise ValueError
            values[key] = value
        expected = {
            "architecture",
            "driver_version",
            "free_persistent_bytes",
            "free_system_memory_bytes",
            "free_vram_bytes",
            "gpu_architectures",
            "gpu_count",
            "hip_version",
            "kernel_version",
            "os_name",
            "os_version",
            "python_version",
            "rocm_version",
        }
        if set(values) != expected:
            raise ValueError
        architectures = tuple(item for item in values["gpu_architectures"].split(",") if item)
        return TargetCompatibilityFacts(
            os_name=values["os_name"],
            os_version=values["os_version"],
            kernel_version=values["kernel_version"],
            architecture=values["architecture"],
            gpu_architectures=architectures,
            driver_version=values["driver_version"],
            rocm_version=values["rocm_version"],
            hip_version=values["hip_version"],
            python_version=values["python_version"],
            gpu_count=int(values["gpu_count"]),
            free_vram_bytes=int(values["free_vram_bytes"]),
            free_system_memory_bytes=int(values["free_system_memory_bytes"]),
            free_persistent_bytes=int(values["free_persistent_bytes"]),
        )
    except (UnicodeDecodeError, ValueError) as exc:
        raise SshPlacementError("Remote target compatibility facts were malformed.") from exc


_TARGET_FACTS_SCRIPT = r"""
set -eu
target_root=$1
for tool in uname awk python3 rocm_agent_enumerator hipcc rocm-smi df; do
    command -v "$tool" >/dev/null 2>&1 || exit 31
done
[ -r /etc/os-release ] && [ -r /sys/module/amdgpu/version ] && [ -r /opt/rocm/.info/version ] || exit 32
. /etc/os-release
parent=${target_root%/*}
while [ ! -d "$parent" ]; do
    next=${parent%/*}
    [ "$next" != "$parent" ] || exit 33
    parent=$next
done
gpu_agents=$(rocm_agent_enumerator | awk '/^gfx[0-9a-z]+$/ { print }')
gpu_architectures=$(printf '%s\n' "$gpu_agents" | sort -u | paste -sd, -)
[ -n "$gpu_architectures" ] || exit 34
gpu_count=$(printf '%s\n' "$gpu_agents" | awk 'END { print NR }')
free_vram=$(python3 -c 'import json, subprocess; data=json.loads(subprocess.check_output(("rocm-smi", "--showmeminfo", "vram", "--json"), text=True)); print(sum(int(card["VRAM Total Memory (B)"]) - int(card["VRAM Total Used Memory (B)"]) for card in data.values()))')
free_memory=$(awk '/^MemAvailable:/ { print $2 * 1024; found=1 } END { exit found ? 0 : 1 }' /proc/meminfo)
free_persistent=$(df -B1 --output=avail "$parent" | awk 'NR == 2 { print $1 }')
hip_version=$(hipcc --version | awk '/^HIP version:/ { print $3; found=1 } END { exit found ? 0 : 1 }')
python_version=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')
printf 'os_name\t%s\n' "$NAME"
printf 'os_version\t%s\n' "$VERSION_ID"
printf 'kernel_version\t%s\n' "$(uname -r)"
printf 'architecture\t%s\n' "$(uname -m)"
printf 'gpu_architectures\t%s\n' "$gpu_architectures"
printf 'driver_version\t%s\n' "$(cat /sys/module/amdgpu/version)"
printf 'rocm_version\t%s\n' "$(cat /opt/rocm/.info/version)"
printf 'hip_version\t%s\n' "$hip_version"
printf 'python_version\t%s\n' "$python_version"
printf 'gpu_count\t%s\n' "$gpu_count"
printf 'free_vram_bytes\t%s\n' "$free_vram"
printf 'free_system_memory_bytes\t%s\n' "$free_memory"
printf 'free_persistent_bytes\t%s\n' "$free_persistent"
""".strip()


def _known_host_pattern(host: str, port: int) -> str:
    if port != 22 or ":" in host:
        return f"[{host}]:{port}"
    return host


def _quote_ssh_config_value(value: str) -> str:
    if not value or "\x00" in value or "\r" in value or "\n" in value or "$" in value:
        raise SshTargetResolutionError("SSH configuration value is invalid.")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%") + '"'


def _write_private_text(path: Path, value: str) -> None:
    try:
        path.write_text(value, encoding="utf-8", newline="\n")
        path.chmod(0o600)
    except OSError:
        raise SshTargetResolutionError("Isolated SSH security material could not be created.") from None


def _isolated_ssh_environment() -> dict[str, str]:
    environment = dict(os.environ)
    environment.pop("SSH_AUTH_SOCK", None)
    environment.pop("SSH_AGENT_PID", None)
    return environment


def _require_remote_script(script: str) -> None:
    if (
        not isinstance(script, str)
        or not script
        or len(script) > 64 * 1_024
        or "\x00" in script
    ):
        raise SshPlacementError("Remote supervision program is invalid.")


def _require_process_deadline(value: float) -> None:
    if (
        not isinstance(value, int | float)
        or isinstance(value, bool)
        or not 0 < float(value) <= 7_200
    ):
        raise SshPlacementError("SSH operation deadline is invalid.")


def _require_short_deadline(value: float, *, maximum: float) -> None:
    if (
        not isinstance(value, int | float)
        or isinstance(value, bool)
        or not 0 <= float(value) <= maximum
    ):
        raise SshPlacementError("SSH process grace period is invalid.")


def _allocate_loopback_port() -> int:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
    except OSError:
        raise SshForwardError("A local loopback port could not be reserved.") from None
    if not isinstance(port, int) or not 1 <= port <= 65_535:
        raise SshForwardError("A local loopback port could not be reserved.")
    return port


def _classified_ssh_error(stderr: bytes) -> SshPlacementError:
    lowered = stderr[:_MAX_SSH_OUTPUT].decode("utf-8", errors="ignore").casefold()
    if (
        "host key verification failed" in lowered
        or "remote host identification has changed" in lowered
        or "no matching host key" in lowered
    ):
        return SshHostTrustError("Pinned SSH host trust verification failed.")
    if (
        "permission denied" in lowered
        or "no more authentication methods" in lowered
        or "sign_and_send_pubkey" in lowered
    ):
        return SshAuthenticationError("SSH public-key authentication failed.")
    return SshConnectionError("SSH connection or remote command failed.")


def _local_command_fingerprint(arguments: Sequence[str]) -> str:
    digest = hashlib.sha256()
    for argument in arguments:
        digest.update(argument.encode("utf-8"))
        digest.update(b"\x00")
    return digest.hexdigest()


def _no_window_creation_flags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


__all__ = [
    "LocalLoopbackForward",
    "OpenSshCommandResult",
    "OpenSshProcessRunner",
    "PinnedHostKey",
    "PrivateSshAmdPlacement",
    "ResolvedSshIdentity",
    "SshAmdExecutionSession",
    "SshAuthenticationError",
    "SshClientUnavailableError",
    "SshCommandTimeoutError",
    "SshConnectionError",
    "SshCredentialResolver",
    "SshForwardError",
    "SshHostTrustError",
    "SshPlacementError",
    "SshTargetEnrollment",
    "SshTargetResolutionError",
    "SshTargetResolver",
    "SshTrustResolver",
    "SubprocessOpenSshRunner",
]
