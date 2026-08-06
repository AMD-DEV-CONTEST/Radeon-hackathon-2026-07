from __future__ import annotations

import hmac
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from threading import RLock
from types import MappingProxyType
from typing import Any, TypeAlias

from pydantic import JsonValue

from shared_contracts import SchemaRevision, canonical_json, stable_json_sha256


Upcaster: TypeAlias = Callable[[dict[str, JsonValue]], Mapping[str, JsonValue]]


class FrozenList(tuple[Any, ...]):
    """Tuple-backed JSON array that compares by sequence value."""

    def __eq__(self, other: object) -> bool:
        if isinstance(other, (list, tuple)):
            return tuple.__eq__(self, tuple(other))
        return False

    __hash__ = None


FrozenJson: TypeAlias = (
    None | bool | int | float | str | FrozenList | Mapping[str, Any]
)


class UpcastError(ValueError):
    """Base class for deterministic historical payload conversion failures."""


class DuplicateUpcasterError(UpcastError):
    pass


class InvalidUpcasterStepError(UpcastError):
    pass


class MissingUpcasterError(UpcastError):
    pass


class UpcasterOutputError(UpcastError):
    pass


class UpcasterRegistryFrozenError(UpcastError):
    pass


class UpcasterSnapshotNotFoundError(UpcastError, LookupError):
    pass


def _revision_key(revision: SchemaRevision) -> tuple[int, int]:
    return revision.major, revision.minor


def _is_next_revision(
    source: SchemaRevision,
    target: SchemaRevision,
) -> bool:
    if target.major == source.major:
        return target.minor == source.minor + 1
    return target.major == source.major + 1 and target.minor == 0


def _freeze(value: Any) -> FrozenJson:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return FrozenList(_freeze(item) for item in value)
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    raise TypeError(f"value is not JSON-compatible: {type(value).__name__}")


def _snapshot(payload: Mapping[str, JsonValue]) -> str:
    try:
        return canonical_json(dict(payload))
    except (TypeError, ValueError) as exc:
        raise UpcasterOutputError("payload must be canonical JSON-compatible") from exc


def _load_frozen(payload_json: str) -> Mapping[str, FrozenJson]:
    loaded = json.loads(payload_json)
    if not isinstance(loaded, dict):
        raise AssertionError("registry payload snapshot must be a JSON object")
    frozen = _freeze(loaded)
    if not isinstance(frozen, Mapping):
        raise AssertionError("registry payload snapshot must remain a mapping")
    return frozen


@dataclass(frozen=True, slots=True)
class AppliedUpcaster:
    contract_name: str
    source_revision: SchemaRevision
    target_revision: SchemaRevision
    implementation_digest: str


@dataclass(frozen=True, slots=True)
class UpcastResult:
    contract_name: str
    source_revision: SchemaRevision
    target_revision: SchemaRevision
    raw_payload_json: str
    payload_json: str
    applied_steps: tuple[AppliedUpcaster, ...]

    @property
    def raw_payload(self) -> Mapping[str, FrozenJson]:
        """A fresh, recursively read-only view of the untouched historical data."""

        return _load_frozen(self.raw_payload_json)

    @property
    def payload(self) -> Mapping[str, FrozenJson]:
        return _load_frozen(self.payload_json)


@dataclass(frozen=True, slots=True)
class _Registration:
    target_revision: SchemaRevision
    implementation_digest: str
    upcaster: Upcaster


RegistrationMap: TypeAlias = Mapping[tuple[str, int, int], _Registration]


def _registry_digest(registrations: RegistrationMap) -> str:
    identity = [
        {
            "contract_name": contract_name,
            "source_revision": {"major": major, "minor": minor},
            "target_revision": registration.target_revision.model_dump(mode="json"),
            "implementation_digest": registration.implementation_digest,
        }
        for (
            contract_name,
            major,
            minor,
        ), registration in registrations.items()
    ]
    identity.sort(
        key=lambda item: (
            item["contract_name"],
            item["source_revision"]["major"],
            item["source_revision"]["minor"],
        )
    )
    return stable_json_sha256(identity)


def _resolve_steps(
    registrations: RegistrationMap,
    contract_name: str,
    source_revision: SchemaRevision,
    target_revision: SchemaRevision,
) -> tuple[_Registration, ...]:
    if _revision_key(source_revision) > _revision_key(target_revision):
        raise MissingUpcasterError("downcasting is not supported")
    if source_revision == target_revision:
        return ()
    current = source_revision
    steps: list[_Registration] = []
    visited: set[tuple[int, int]] = set()
    while current != target_revision:
        current_key = _revision_key(current)
        if current_key in visited:
            raise MissingUpcasterError("upcaster chain contains a cycle")
        visited.add(current_key)
        registration = registrations.get(
            (contract_name, current.major, current.minor)
        )
        if registration is None:
            raise MissingUpcasterError(
                f"missing upcaster for {contract_name} "
                f"{current.major}.{current.minor}"
            )
        if _revision_key(registration.target_revision) > _revision_key(
            target_revision
        ):
            raise MissingUpcasterError(
                f"upcaster chain skips target "
                f"{target_revision.major}.{target_revision.minor}"
            )
        steps.append(registration)
        current = registration.target_revision
    return tuple(steps)


def _upcast(
    registrations: RegistrationMap,
    contract_name: str,
    raw_payload: Mapping[str, JsonValue],
    source_revision: SchemaRevision,
    target_revision: SchemaRevision,
) -> UpcastResult:
    raw_payload_json = _snapshot(raw_payload)
    steps = _resolve_steps(
        registrations,
        contract_name,
        source_revision,
        target_revision,
    )
    current_payload = json.loads(raw_payload_json)
    if not isinstance(current_payload, dict):
        raise UpcasterOutputError("historical payload must be a JSON object")
    applied: list[AppliedUpcaster] = []
    current_revision = source_revision
    for registration in steps:
        step_input = json.loads(canonical_json(current_payload))
        try:
            candidate = registration.upcaster(step_input)
        except Exception as exc:
            raise UpcasterOutputError(
                f"upcaster failed for {contract_name} "
                f"{current_revision.major}.{current_revision.minor}"
            ) from exc
        candidate_json = _snapshot(candidate)
        current_payload = json.loads(candidate_json)
        applied.append(
            AppliedUpcaster(
                contract_name=contract_name,
                source_revision=current_revision,
                target_revision=registration.target_revision,
                implementation_digest=registration.implementation_digest,
            )
        )
        current_revision = registration.target_revision
    return UpcastResult(
        contract_name=contract_name,
        source_revision=source_revision,
        target_revision=target_revision,
        raw_payload_json=raw_payload_json,
        payload_json=canonical_json(current_payload),
        applied_steps=tuple(applied),
    )


@dataclass(frozen=True, slots=True)
class UpcasterSnapshot:
    """Immutable, digest-addressed set of executable upcast steps."""

    digest: str
    _registrations: RegistrationMap

    def __post_init__(self) -> None:
        copied = MappingProxyType(dict(self._registrations))
        actual = _registry_digest(copied)
        if not hmac.compare_digest(actual, self.digest):
            raise ValueError("upcaster snapshot digest mismatch")
        object.__setattr__(self, "_registrations", copied)

    @classmethod
    def from_registrations(
        cls,
        registrations: RegistrationMap,
    ) -> UpcasterSnapshot:
        copied = dict(registrations)
        return cls(digest=_registry_digest(copied), _registrations=copied)

    def registry_digest(self) -> str:
        return self.digest

    def can_upcast(
        self,
        contract_name: str,
        source_revision: SchemaRevision,
        target_revision: SchemaRevision,
    ) -> bool:
        try:
            _resolve_steps(
                self._registrations,
                contract_name,
                source_revision,
                target_revision,
            )
        except MissingUpcasterError:
            return False
        return True

    def upcast(
        self,
        contract_name: str,
        raw_payload: Mapping[str, JsonValue],
        source_revision: SchemaRevision,
        target_revision: SchemaRevision,
    ) -> UpcastResult:
        return _upcast(
            self._registrations,
            contract_name,
            raw_payload,
            source_revision,
            target_revision,
        )


class UpcasterRegistry:
    """Central registry of explicit, adjacent and deterministic upcast steps.

    Registration is intentionally independent of plugin discovery. Runtime
    bootstrap code owns which registrations are installed.
    """

    def __init__(self) -> None:
        self._registrations: dict[
            tuple[str, int, int],
            _Registration,
        ] = {}
        self._frozen = False
        self._snapshots: dict[str, UpcasterSnapshot] = {}
        self._lock = RLock()

    @property
    def is_frozen(self) -> bool:
        with self._lock:
            return self._frozen

    def register(
        self,
        contract_name: str,
        source_revision: SchemaRevision,
        target_revision: SchemaRevision,
        upcaster: Upcaster,
        *,
        implementation_digest: str,
    ) -> None:
        if not contract_name:
            raise ValueError("contract name cannot be empty")
        if not _is_next_revision(source_revision, target_revision):
            raise InvalidUpcasterStepError(
                "upcasters must advance one minor revision or to the next major .0"
            )
        if (
            len(implementation_digest) != 64
            or any(character not in "0123456789abcdef" for character in implementation_digest)
        ):
            raise ValueError("upcaster implementation digest must be lowercase SHA-256")
        key = (contract_name, source_revision.major, source_revision.minor)
        with self._lock:
            if self._frozen:
                raise UpcasterRegistryFrozenError("upcaster registry is frozen")
            if key in self._registrations:
                raise DuplicateUpcasterError(
                    f"upcaster already registered for {contract_name} "
                    f"{source_revision.major}.{source_revision.minor}"
                )
            self._registrations[key] = _Registration(
                target_revision=target_revision,
                implementation_digest=implementation_digest,
                upcaster=upcaster,
            )

    def snapshot(self) -> UpcasterSnapshot:
        """Retain and return an immutable point-in-time registry snapshot."""

        with self._lock:
            snapshot = UpcasterSnapshot.from_registrations(self._registrations)
            self._snapshots.setdefault(snapshot.digest, snapshot)
            return self._snapshots[snapshot.digest]

    def freeze(self) -> UpcasterSnapshot:
        with self._lock:
            snapshot = self.snapshot()
            self._frozen = True
            return snapshot

    def resolve_snapshot(self, digest: str) -> UpcasterSnapshot:
        with self._lock:
            try:
                return self._snapshots[digest]
            except KeyError as exc:
                raise UpcasterSnapshotNotFoundError(
                    f"upcaster snapshot is unavailable: {digest}"
                ) from exc

    @property
    def snapshots(self) -> Mapping[str, UpcasterSnapshot]:
        with self._lock:
            return MappingProxyType(dict(self._snapshots))

    def can_upcast(
        self,
        contract_name: str,
        source_revision: SchemaRevision,
        target_revision: SchemaRevision,
    ) -> bool:
        with self._lock:
            registrations = MappingProxyType(dict(self._registrations))
        try:
            _resolve_steps(
                registrations,
                contract_name,
                source_revision,
                target_revision,
            )
        except MissingUpcasterError:
            return False
        return True

    def upcast(
        self,
        contract_name: str,
        raw_payload: Mapping[str, JsonValue],
        source_revision: SchemaRevision,
        target_revision: SchemaRevision,
    ) -> UpcastResult:
        with self._lock:
            registrations = MappingProxyType(dict(self._registrations))
        return _upcast(
            registrations,
            contract_name,
            raw_payload,
            source_revision,
            target_revision,
        )

    def registry_digest(self) -> str:
        with self._lock:
            return _registry_digest(self._registrations)
