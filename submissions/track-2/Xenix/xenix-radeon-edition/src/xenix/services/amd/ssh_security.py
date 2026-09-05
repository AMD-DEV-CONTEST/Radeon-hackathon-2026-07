"""AMD-owned enrollment handles for Private SSH placements.

SQLite owns the durable target identity and only stores opaque references to
local security material.  This module owns the small settings document behind
those references: an absolute identity-file *path* and a pinned public host
key.  It never reads private-key bytes, never performs SSH discovery, and never
persists a password, token, or endpoint binding.
"""

from __future__ import annotations

import base64
import binascii
import threading
from collections.abc import Callable, Mapping
from pathlib import Path

from sqlmodel import Session

from ..settings_store import SettingsConflictError, SettingsSnapshot, SettingsStore, SettingsStoreError
from ..storage.models import AmdTargetEnrollmentRow
from ..storage.repositories.amd_installations import AmdInstallationRepository
from .placements.ssh import (
    PinnedHostKey,
    ResolvedSshIdentity,
    SshCredentialResolver,
    SshTargetEnrollment,
    SshTargetResolutionError,
    SshTargetResolver,
    SshTrustResolver,
)


_DOCUMENT_ID = "amd_ssh_security.json"
_SCHEMA_VERSION = 1
_REFERENCE_PREFIX = "amd-private-target:"
_MAX_TARGETS = 128


class AmdSshSecurityError(RuntimeError):
    """A local Private SSH enrollment handle could not be used safely."""

    def __init__(
        self,
        message: str,
        *,
        error_code: str = "amd_ssh_security_invalid",
    ) -> None:
        super().__init__(message)
        self.error_code = error_code


class AmdSshSecurityStore:
    """One app-scoped store for opaque Private SSH enrollment material."""

    def __init__(self, store: SettingsStore) -> None:
        if not isinstance(store, SettingsStore):
            raise TypeError("AMD SSH security requires the app settings store.")
        self._store = store
        self._lock = threading.RLock()
        self._closed = False

    def close(self) -> None:
        """Fence later settings access before the app closes its store."""

        with self._lock:
            self._closed = True

    def references_for_target(self, target_id: str) -> tuple[str, str]:
        """Return deterministic opaque references without reading or writing a key."""

        normalized_target_id = _require_target_id(target_id)
        with self._lock:
            self._require_open()
        reference = _reference_for_target(normalized_target_id)
        return reference, reference

    def contains_target(self, target_id: str) -> bool:
        """Return whether the exact local security checkpoint exists."""

        normalized_target_id = _require_target_id(target_id)
        with self._lock:
            self._require_open()
            payload = _payload_from_snapshot(self._load())
        return normalized_target_id in payload["targets"]

    def record(
        self,
        *,
        target_id: str,
        identity_file: Path,
        host_key: PinnedHostKey,
    ) -> tuple[str, str]:
        """Persist non-secret local handles and return stable opaque refs."""

        normalized_target_id = _require_target_id(target_id)
        path = _require_identity_path(identity_file)
        if not isinstance(host_key, PinnedHostKey):
            raise AmdSshSecurityError(
                "Pinned SSH host key is invalid.",
                error_code="amd_ssh_host_key_invalid",
            )
        reference = _reference_for_target(normalized_target_id)
        record = {
            "identity_file": str(path),
            "host_key_type": host_key.key_type,
            "host_key_data": host_key.key_data,
        }
        with self._lock:
            self._require_open()
            for _attempt in range(8):
                snapshot = self._load()
                current = _payload_from_snapshot(snapshot)
                targets = dict(current["targets"])
                existing = targets.get(normalized_target_id)
                if existing is not None and existing != record:
                    raise AmdSshSecurityError(
                        "Private SSH target security material is already enrolled.",
                        error_code="amd_ssh_security_conflict",
                    )
                if existing == record:
                    return reference, reference
                if len(targets) >= _MAX_TARGETS:
                    raise AmdSshSecurityError(
                        "Too many Private SSH targets are enrolled.",
                        error_code="amd_ssh_security_capacity_reached",
                    )
                targets[normalized_target_id] = record
                next_payload = {"schema_version": _SCHEMA_VERSION, "targets": targets}
                try:
                    self._store.compare_and_swap(
                        _DOCUMENT_ID,
                        snapshot.revision,
                        lambda _payload, payload=next_payload: payload,
                    )
                    return reference, reference
                except SettingsConflictError:
                    continue
                except SettingsStoreError as exc:
                    raise AmdSshSecurityError(
                        "Private SSH security material could not be saved.",
                        error_code="amd_ssh_security_unavailable",
                    ) from exc
        raise AmdSshSecurityError(
            "Private SSH security material changed repeatedly; retry enrollment.",
            error_code="amd_ssh_security_conflict",
        )

    def resolve_identity(self, reference: str) -> ResolvedSshIdentity:
        record = self._record(reference)
        try:
            return ResolvedSshIdentity(identity_file=Path(record["identity_file"]))
        except (KeyError, TypeError, ValueError, SshTargetResolutionError) as exc:
            raise AmdSshSecurityError(
                "Private SSH identity handle is invalid.",
                error_code="amd_ssh_identity_invalid",
            ) from exc

    def resolve_host_key(self, reference: str) -> PinnedHostKey:
        record = self._record(reference)
        try:
            return PinnedHostKey(
                key_type=record["host_key_type"],
                key_data=record["host_key_data"],
            )
        except (KeyError, TypeError, ValueError, SshTargetResolutionError) as exc:
            raise AmdSshSecurityError(
                "Pinned SSH host key is invalid.",
                error_code="amd_ssh_host_key_invalid",
            ) from exc

    def _record(self, reference: str) -> Mapping[str, str]:
        target_id = _target_id_from_reference(reference)
        with self._lock:
            self._require_open()
            payload = _payload_from_snapshot(self._load())
        record = payload["targets"].get(target_id)
        if record is None:
            raise AmdSshSecurityError(
                "Private SSH target security material is unavailable.",
                error_code="amd_ssh_security_unavailable",
            )
        return record

    def _load(self) -> SettingsSnapshot:
        try:
            return self._store.load(_DOCUMENT_ID)
        except SettingsStoreError as exc:
            raise AmdSshSecurityError(
                "Private SSH security material could not be read.",
                error_code="amd_ssh_security_unavailable",
            ) from exc

    def _require_open(self) -> None:
        if self._closed:
            raise AmdSshSecurityError(
                "Private SSH security store is closed.",
                error_code="amd_ssh_security_unavailable",
            )


class AmdSqliteSshTargetResolver(SshTargetResolver):
    """Resolve a persisted enrollment row into the narrow SSH target port."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        repository: AmdInstallationRepository | None = None,
    ) -> None:
        if not callable(session_factory):
            raise TypeError("AMD SSH target resolver requires a session factory.")
        self._session_factory = session_factory
        self._repository = repository or AmdInstallationRepository()
        self._lock = threading.RLock()
        self._closed = False

    def close(self) -> None:
        """Fence later SQLite access before the app disposes its engine."""

        with self._lock:
            self._closed = True

    def resolve_target(self, target_id: str) -> SshTargetEnrollment:
        _require_target_id(target_id)
        try:
            with self._lock:
                if self._closed:
                    raise SshTargetResolutionError("Private SSH target resolver is closed.")
                with self._session_factory() as session:
                    row = self._repository.get_target(session, target_id)
        except Exception as exc:
            raise SshTargetResolutionError("Private SSH target could not be resolved.") from exc
        if not isinstance(row, AmdTargetEnrollmentRow):
            raise SshTargetResolutionError("Private SSH target is unavailable.")
        try:
            return SshTargetEnrollment(
                target_id=row.id,
                host=row.host,
                user=row.user,
                port=row.port,
                pinned_host_key_reference=row.pinned_host_key,
                identity_file_reference=row.identity_file_reference,
            )
        except (TypeError, ValueError, SshTargetResolutionError) as exc:
            raise SshTargetResolutionError("Private SSH target is invalid.") from exc


class AmdSettingsSshCredentialResolver(SshCredentialResolver):
    """Resolve only a local key-file path; private-key content stays in OpenSSH."""

    def __init__(self, security_store: AmdSshSecurityStore) -> None:
        self._security_store = security_store

    def resolve_identity(self, identity_file_reference: str) -> ResolvedSshIdentity:
        try:
            return self._security_store.resolve_identity(identity_file_reference)
        except AmdSshSecurityError as exc:
            raise SshTargetResolutionError("Private SSH identity is unavailable.") from exc


class AmdSettingsSshTrustResolver(SshTrustResolver):
    """Resolve an enrolled host key without TOFU, DNS, or known-hosts reuse."""

    def __init__(self, security_store: AmdSshSecurityStore) -> None:
        self._security_store = security_store

    def resolve_host_key(self, pinned_host_key_reference: str) -> PinnedHostKey:
        try:
            return self._security_store.resolve_host_key(pinned_host_key_reference)
        except AmdSshSecurityError as exc:
            raise SshTargetResolutionError("Pinned SSH host key is unavailable.") from exc


def parse_pinned_host_key(
    value: str,
    *,
    expected_host: str | None = None,
    expected_port: int | None = None,
) -> PinnedHostKey:
    """Parse one verified OpenSSH server host key.

    The accepted forms are ``key-type base64 [comment...]`` and, when the
    expected endpoint is supplied, the exact un-hashed ``known_hosts`` form
    ``host-pattern key-type base64 [comment...]``.  Fingerprints, multi-line
    scans, wildcard/hashed host patterns, and mismatched endpoint prefixes are
    rejected.  The binary key blob must name the same algorithm as the text
    prefix.
    """

    if not isinstance(value, str) or "\x00" in value or "\r" in value or "\n" in value:
        raise _invalid_host_key()
    fields = value.strip().split()
    candidates: list[tuple[str, str]] = []
    if len(fields) >= 2:
        candidates.append((fields[0], fields[1]))
    if expected_host is not None and expected_port is not None and len(fields) >= 3:
        expected_pattern = (
            f"[{expected_host}]:{expected_port}"
            if expected_port != 22 or ":" in expected_host
            else expected_host
        )
        if fields[0] == expected_pattern:
            candidates.insert(0, (fields[1], fields[2]))

    for key_type, key_data in candidates:
        try:
            host_key = PinnedHostKey(key_type=key_type, key_data=key_data)
            if _embedded_key_type(key_data) != key_type:
                continue
            return host_key
        except (ValueError, SshTargetResolutionError):
            continue
    raise _invalid_host_key()


def _payload_from_snapshot(snapshot: SettingsSnapshot) -> dict[str, object]:
    payload = snapshot.payload
    if payload == {}:
        return {"schema_version": _SCHEMA_VERSION, "targets": {}}
    if not isinstance(payload, Mapping) or set(payload) != {"schema_version", "targets"}:
        raise AmdSshSecurityError("Private SSH security document is invalid.")
    if payload.get("schema_version") != _SCHEMA_VERSION or not isinstance(payload.get("targets"), Mapping):
        raise AmdSshSecurityError("Private SSH security document is invalid.")
    targets = payload["targets"]
    if len(targets) > _MAX_TARGETS or not all(isinstance(key, str) for key in targets):
        raise AmdSshSecurityError("Private SSH security document is invalid.")
    return {
        "schema_version": _SCHEMA_VERSION,
        "targets": {
            target_id: _security_record(record)
            for target_id, record in targets.items()
        },
    }


def _security_record(value: object) -> dict[str, str]:
    """Validate and detach one immutable SettingsStore record for publication."""

    expected_fields = ("identity_file", "host_key_type", "host_key_data")
    if (
        not isinstance(value, Mapping)
        or set(value) != set(expected_fields)
        or not all(isinstance(value[field], str) for field in expected_fields)
    ):
        raise AmdSshSecurityError("Private SSH target security material is invalid.")
    return {field: value[field] for field in expected_fields}


def _require_target_id(value: str) -> str:
    try:
        # SshTargetEnrollment centralizes the target-id grammar while this
        # store intentionally remains independent from endpoint details.
        return SshTargetEnrollment(
            target_id=value,
            host="127.0.0.1",
            user="xenix",
            port=22,
            pinned_host_key_reference="validation",
            identity_file_reference="validation",
        ).target_id
    except SshTargetResolutionError as exc:
        raise AmdSshSecurityError(
            "Private SSH target ID is invalid.",
            error_code="amd_ssh_target_id_invalid",
        ) from exc


def _require_identity_path(value: Path) -> Path:
    try:
        path = Path(value)
    except (OSError, TypeError, ValueError):
        raise AmdSshSecurityError(
            "Private SSH identity path is invalid.",
            error_code="amd_ssh_identity_invalid",
        ) from None
    rendered = str(path)
    if (
        not path.is_absolute()
        or "\x00" in rendered
        or "\r" in rendered
        or "\n" in rendered
        or len(rendered) > 2_048
    ):
        raise AmdSshSecurityError(
            "Private SSH identity path is invalid.",
            error_code="amd_ssh_identity_invalid",
        )
    return path


def _embedded_key_type(key_data: str) -> str:
    try:
        padding = "=" * ((4 - len(key_data) % 4) % 4)
        payload = base64.b64decode(key_data + padding, validate=True)
        if len(payload) < 5:
            raise ValueError
        name_length = int.from_bytes(payload[:4], byteorder="big", signed=False)
        name_end = 4 + name_length
        if not 1 <= name_length <= 256 or name_end >= len(payload):
            raise ValueError
        return payload[4:name_end].decode("ascii", errors="strict")
    except (UnicodeDecodeError, ValueError, binascii.Error):
        raise ValueError("Invalid OpenSSH public key blob.") from None


def _invalid_host_key() -> AmdSshSecurityError:
    return AmdSshSecurityError(
        "Pinned SSH host key is invalid.",
        error_code="amd_ssh_host_key_invalid",
    )


def _reference_for_target(target_id: str) -> str:
    return _REFERENCE_PREFIX + target_id


def _target_id_from_reference(reference: str) -> str:
    if not isinstance(reference, str) or not reference.startswith(_REFERENCE_PREFIX):
        raise AmdSshSecurityError("Private SSH security reference is invalid.")
    return _require_target_id(reference.removeprefix(_REFERENCE_PREFIX))


__all__ = [
    "AmdSettingsSshCredentialResolver",
    "AmdSettingsSshTrustResolver",
    "AmdSqliteSshTargetResolver",
    "AmdSshSecurityError",
    "AmdSshSecurityStore",
    "parse_pinned_host_key",
]
