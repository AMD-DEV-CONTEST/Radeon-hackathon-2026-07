"""Read-only first-use host-key discovery for guided Private SSH enrollment."""

from __future__ import annotations

import base64
import binascii
import hashlib
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .placements.ssh import (
    OpenSshProcessRunner,
    PinnedHostKey,
    SshPlacementError,
    SshTargetEnrollment,
    SubprocessOpenSshRunner,
)
from .ssh_security import AmdSshSecurityError, parse_pinned_host_key


_MAX_DISCOVERY_OUTPUT = 64 * 1_024
_SUPPORTED_KEY_TYPES = (
    "ssh-ed25519",
    "ecdsa-sha2-nistp256",
    "ssh-rsa",
)


class AmdSshHostTrustDiscoveryError(RuntimeError):
    """Host identity could not be discovered without exposing raw output."""

    def __init__(self, error_code: str) -> None:
        super().__init__(error_code)
        self.error_code = error_code


@dataclass(frozen=True, slots=True)
class AmdSshHostTrustChallenge:
    """Exact ephemeral key bound to the fingerprint shown for one endpoint."""

    host: str = field(repr=False)
    port: int = field(repr=False)
    host_key: PinnedHostKey = field(repr=False)

    def __post_init__(self) -> None:
        try:
            SshTargetEnrollment(
                target_id="guided-host-trust",
                host=self.host,
                user="xenix",
                port=self.port,
                pinned_host_key_reference="guided-host-trust",
                identity_file_reference="guided-host-trust",
            )
        except SshPlacementError:
            raise AmdSshHostTrustDiscoveryError(
                "amd_ssh_host_key_discovery_invalid"
            ) from None
        if (
            not isinstance(self.host_key, PinnedHostKey)
            or self.host_key.key_type not in _SUPPORTED_KEY_TYPES
        ):
            raise AmdSshHostTrustDiscoveryError(
                "amd_ssh_host_key_discovery_invalid"
            )

    @property
    def algorithm(self) -> str:
        return self.host_key.key_type

    @property
    def fingerprint(self) -> str:
        try:
            padding = "=" * ((4 - len(self.host_key.key_data) % 4) % 4)
            payload = base64.b64decode(
                self.host_key.key_data + padding,
                validate=True,
            )
        except (ValueError, TypeError, binascii.Error):
            raise AmdSshHostTrustDiscoveryError(
                "amd_ssh_host_key_discovery_invalid"
            ) from None
        digest = base64.b64encode(hashlib.sha256(payload).digest()).decode("ascii")
        return f"SHA256:{digest.rstrip('=')}"


class OpenSshHostTrustProbe:
    """Discover a presented key without authenticating or changing user trust.

    ``ssh-keyscan`` is the preferred probe because it does not complete an SSH
    transport handshake.  Some managed-cloud SSH front doors intentionally do
    not answer scanner clients while accepting normal OpenSSH clients.  For
    that narrow case, a fresh temporary known-hosts file and an explicitly
    unauthenticated OpenSSH connection can collect the same public host key.
    The fallback never uses a user config, agent, credential, global known-host
    file, or target command; its temporary key remains only the candidate shown
    for the ordinary explicit trust confirmation.
    """

    def __init__(
        self,
        *,
        temporary_parent: Path | None,
        executable: str = "ssh-keyscan",
        ssh_executable: str = "ssh",
        process_runner: OpenSshProcessRunner | None = None,
        timeout_seconds: int = 10,
    ) -> None:
        if not _is_safe_executable(executable) or not _is_safe_executable(ssh_executable):
            raise AmdSshHostTrustDiscoveryError(
                "amd_ssh_client_unavailable"
            )
        if not isinstance(timeout_seconds, int) or not 1 <= timeout_seconds <= 60:
            raise AmdSshHostTrustDiscoveryError(
                "amd_ssh_host_key_discovery_invalid"
            )
        self._temporary_parent = temporary_parent
        self._executable = executable
        self._ssh_executable = ssh_executable
        self._runner = process_runner or SubprocessOpenSshRunner()
        self._timeout_seconds = timeout_seconds

    def discover(self, *, host: str, port: int) -> AmdSshHostTrustChallenge:
        """Return one deterministic supported key; never authenticate or write."""

        try:
            SshTargetEnrollment(
                target_id="guided-host-trust",
                host=host,
                user="xenix",
                port=port,
                pinned_host_key_reference="guided-host-trust",
                identity_file_reference="guided-host-trust",
            )
        except SshPlacementError as exc:
            raise AmdSshHostTrustDiscoveryError(exc.error_code) from None

        try:
            temporary = tempfile.TemporaryDirectory(
                prefix="xenix-amd-host-trust-",
                dir=(
                    None
                    if self._temporary_parent is None
                    else os.fspath(self._temporary_parent)
                ),
            )
        except OSError:
            raise AmdSshHostTrustDiscoveryError(
                "amd_ssh_host_key_discovery_failed"
            ) from None
        with temporary:
            host_file = Path(temporary.name) / "hosts"
            try:
                host_file.write_text(f"{host}\n", encoding="utf-8", newline="\n")
                host_file.chmod(0o600)
            except OSError:
                raise AmdSshHostTrustDiscoveryError(
                    "amd_ssh_host_key_discovery_failed"
                ) from None
            try:
                result = self._runner.run(
                    (
                        self._executable,
                        "-T",
                        str(self._timeout_seconds),
                        "-p",
                        str(port),
                        "-t",
                        "ed25519,ecdsa,rsa",
                        "-f",
                        os.fspath(host_file),
                    ),
                    stdin=None,
                    timeout_seconds=float(self._timeout_seconds + 2),
                    environment=_isolated_environment(),
                )
            except SshPlacementError as exc:
                raise AmdSshHostTrustDiscoveryError(exc.error_code) from None
            if (
                len(result.stdout) > _MAX_DISCOVERY_OUTPUT
                or len(result.stderr) > _MAX_DISCOVERY_OUTPUT
            ):
                raise AmdSshHostTrustDiscoveryError(
                    "amd_ssh_host_key_discovery_invalid"
                )
            candidates = _parse_candidates(
                result.stdout,
                expected_host=host,
                expected_port=port,
            )
            if candidates:
                return _challenge_for_candidates(
                    candidates,
                    host=host,
                    port=port,
                )
            return self._discover_with_unauthenticated_ssh(
                host=host,
                port=port,
                temporary_directory=Path(temporary.name),
            )

    def _discover_with_unauthenticated_ssh(
        self,
        *,
        host: str,
        port: int,
        temporary_directory: Path,
    ) -> AmdSshHostTrustChallenge:
        """Read a candidate into an ephemeral known-hosts file, never authenticate."""

        known_hosts = temporary_directory / "known_hosts"
        try:
            result = self._runner.run(
                (
                    self._ssh_executable,
                    "-F",
                    os.devnull,
                    "-p",
                    str(port),
                    "-o",
                    "BatchMode=yes",
                    "-o",
                    "PreferredAuthentications=none",
                    "-o",
                    "PubkeyAuthentication=no",
                    "-o",
                    "GSSAPIAuthentication=no",
                    "-o",
                    "HostbasedAuthentication=no",
                    "-o",
                    "IdentityAgent=none",
                    "-o",
                    "IdentitiesOnly=yes",
                    "-o",
                    "PasswordAuthentication=no",
                    "-o",
                    "KbdInteractiveAuthentication=no",
                    "-o",
                    "NumberOfPasswordPrompts=0",
                    "-o",
                    "GlobalKnownHostsFile=none",
                    "-o",
                    "HashKnownHosts=no",
                    "-o",
                    "UpdateHostKeys=no",
                    "-o",
                    "StrictHostKeyChecking=accept-new",
                    "-o",
                    f"UserKnownHostsFile={known_hosts.as_posix()}",
                    "-o",
                    f"ConnectTimeout={self._timeout_seconds}",
                    f"xenix-host-probe@{host}",
                    "exit",
                ),
                stdin=None,
                timeout_seconds=float(self._timeout_seconds + 2),
                environment=_isolated_environment(),
            )
        except SshPlacementError as exc:
            raise AmdSshHostTrustDiscoveryError(exc.error_code) from None
        if (
            len(result.stdout) > _MAX_DISCOVERY_OUTPUT
            or len(result.stderr) > _MAX_DISCOVERY_OUTPUT
        ):
            raise AmdSshHostTrustDiscoveryError(
                "amd_ssh_host_key_discovery_invalid"
            )
        try:
            payload = known_hosts.read_bytes()
        except OSError:
            raise AmdSshHostTrustDiscoveryError(
                "amd_ssh_host_key_discovery_failed"
            ) from None
        candidates = _parse_candidates(
            payload,
            expected_host=host,
            expected_port=port,
        )
        if not candidates:
            raise AmdSshHostTrustDiscoveryError(
                "amd_ssh_host_key_discovery_failed"
            )
        return _challenge_for_candidates(candidates, host=host, port=port)


def _parse_candidates(
    payload: bytes,
    *,
    expected_host: str,
    expected_port: int,
) -> tuple[PinnedHostKey, ...]:
    try:
        text = payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        raise AmdSshHostTrustDiscoveryError(
            "amd_ssh_host_key_discovery_invalid"
        ) from None
    candidates: list[PinnedHostKey] = []
    for line in text.splitlines():
        rendered = line.strip()
        if not rendered or rendered.startswith("#"):
            continue
        try:
            candidate = parse_pinned_host_key(
                rendered,
                expected_host=expected_host,
                expected_port=expected_port,
            )
        except AmdSshSecurityError:
            raise AmdSshHostTrustDiscoveryError(
                "amd_ssh_host_key_discovery_invalid"
            ) from None
        if candidate.key_type in _SUPPORTED_KEY_TYPES:
            candidates.append(candidate)
    return tuple(candidates)


def _select_candidate(candidates: tuple[PinnedHostKey, ...]) -> PinnedHostKey:
    for key_type in _SUPPORTED_KEY_TYPES:
        matching = tuple(
            candidate for candidate in candidates if candidate.key_type == key_type
        )
        if not matching:
            continue
        unique = {(candidate.key_type, candidate.key_data) for candidate in matching}
        if len(unique) != 1:
            raise AmdSshHostTrustDiscoveryError(
                "amd_ssh_host_key_discovery_conflict"
            )
        return matching[0]
    raise AmdSshHostTrustDiscoveryError("amd_ssh_host_key_discovery_failed")


def _challenge_for_candidates(
    candidates: tuple[PinnedHostKey, ...],
    *,
    host: str,
    port: int,
) -> AmdSshHostTrustChallenge:
    return AmdSshHostTrustChallenge(
        host=host,
        port=port,
        host_key=_select_candidate(candidates),
    )


def _is_safe_executable(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and "\x00" not in value
        and "\r" not in value
        and "\n" not in value
    )


def _isolated_environment() -> dict[str, str]:
    environment = dict(os.environ)
    environment.pop("SSH_AUTH_SOCK", None)
    environment.pop("SSH_AGENT_PID", None)
    return environment


__all__ = [
    "AmdSshHostTrustChallenge",
    "AmdSshHostTrustDiscoveryError",
    "OpenSshHostTrustProbe",
]
