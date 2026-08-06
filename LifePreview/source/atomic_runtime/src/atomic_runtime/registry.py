from __future__ import annotations

from threading import RLock
from types import MappingProxyType
from typing import Iterable, Mapping

from shared_contracts import OperationRequest, OperationResult, SchemaRevision

from .capabilities import (
    CapabilityKey,
    CapabilityPlugin,
    CapabilityRegistration,
    InvalidCapabilityError,
)
from .errors import ErrorContext
from .upcasting import UpcasterRegistry, UpcasterSnapshot


class CapabilityRegistryError(RuntimeError):
    pass


class CapabilityCollisionError(CapabilityRegistryError):
    pass


class CapabilityNotFoundError(CapabilityRegistryError, LookupError):
    def __init__(
        self,
        requested: CapabilityKey,
        available: tuple[CapabilityKey, ...],
    ) -> None:
        self.requested = requested
        self.available = available
        super().__init__(
            "no exactly pinned capability is registered; "
            f"requested={requested!r}; available={available!r}"
        )


class RegistryFrozenError(CapabilityRegistryError):
    pass


class RegistryNotFrozenError(CapabilityRegistryError):
    pass


class UpcasterDigestMismatchError(CapabilityRegistryError):
    pass


class UpcasterSnapshotCollisionError(CapabilityRegistryError):
    pass


class CapabilityRegistry:
    """Transactional mutable builder that can be irreversibly frozen."""

    __slots__ = (
        "_frozen",
        "_lock",
        "_registrations",
        "_upcaster_snapshots",
    )

    def __init__(self) -> None:
        self._registrations: dict[CapabilityKey, CapabilityRegistration] = {}
        self._upcaster_snapshots: dict[str, UpcasterSnapshot] = {}
        self._frozen = False
        self._lock = RLock()

    @property
    def is_frozen(self) -> bool:
        with self._lock:
            return self._frozen

    @property
    def registrations(self) -> Mapping[CapabilityKey, CapabilityRegistration]:
        with self._lock:
            return MappingProxyType(dict(self._registrations))

    @property
    def upcaster_snapshots(self) -> Mapping[str, UpcasterSnapshot]:
        with self._lock:
            return MappingProxyType(dict(self._upcaster_snapshots))

    def retain_upcaster_snapshot(self, snapshot: UpcasterSnapshot) -> None:
        if not isinstance(snapshot, UpcasterSnapshot):
            raise TypeError("snapshot must be UpcasterSnapshot")
        with self._lock:
            if self._frozen:
                raise RegistryFrozenError("capability registry is frozen")
            self._merge_upcaster_snapshot(self._upcaster_snapshots, snapshot)

    @staticmethod
    def _merge_upcaster_snapshot(
        target: dict[str, UpcasterSnapshot],
        snapshot: UpcasterSnapshot,
    ) -> None:
        existing = target.get(snapshot.digest)
        if existing is not None and existing != snapshot:
            raise UpcasterSnapshotCollisionError(
                "different upcaster snapshots claim the same digest"
            )
        target.setdefault(snapshot.digest, snapshot)

    def _prepare(
        self,
        registrations: Iterable[CapabilityRegistration],
    ) -> tuple[CapabilityRegistration, ...]:
        prepared = tuple(registrations)
        if not all(
            isinstance(registration, CapabilityRegistration)
            for registration in prepared
        ):
            raise InvalidCapabilityError(
                "registry accepts only CapabilityRegistration objects"
            )
        keys = tuple(registration.key for registration in prepared)
        if len(keys) != len(set(keys)):
            raise CapabilityCollisionError(
                "capability collision inside registration transaction"
            )
        return prepared

    def register(self, registration: CapabilityRegistration) -> None:
        self.register_all((registration,))

    def register_plugin(self, plugin: CapabilityPlugin) -> None:
        if not isinstance(plugin, CapabilityPlugin):
            raise InvalidCapabilityError("registry accepts only CapabilityPlugin objects")
        self.register_all(plugin.registrations)

    def register_plugins(self, plugins: Iterable[CapabilityPlugin]) -> None:
        plugin_snapshot = tuple(plugins)
        if not all(isinstance(plugin, CapabilityPlugin) for plugin in plugin_snapshot):
            raise InvalidCapabilityError(
                "registry accepts only CapabilityPlugin objects"
            )
        self.register_all(
            registration
            for plugin in plugin_snapshot
            for registration in plugin.registrations
        )

    @staticmethod
    def _snapshot_candidates(
        upcasters: (
            UpcasterRegistry
            | UpcasterSnapshot
            | Iterable[UpcasterSnapshot]
            | None
        ),
    ) -> tuple[UpcasterSnapshot, ...]:
        if upcasters is None:
            return ()
        if isinstance(upcasters, UpcasterRegistry):
            current = upcasters.freeze()
            return tuple(upcasters.snapshots.values()) or (current,)
        if isinstance(upcasters, UpcasterSnapshot):
            return (upcasters,)
        snapshots = tuple(upcasters)
        if not all(isinstance(snapshot, UpcasterSnapshot) for snapshot in snapshots):
            raise TypeError("upcasters must contain only UpcasterSnapshot objects")
        return snapshots

    @staticmethod
    def _require_bound_upcasters(
        registrations: Iterable[CapabilityRegistration],
        snapshots: Mapping[str, UpcasterSnapshot],
    ) -> None:
        missing = sorted(
            {
                registration.implementation_manifest.upcaster_digest
                for registration in registrations
                if registration.implementation_manifest.upcaster_digest
                not in snapshots
            }
        )
        if missing:
            raise UpcasterDigestMismatchError(
                "implementation manifests reference unavailable upcaster snapshots: "
                + ", ".join(missing)
            )

    def register_all(
        self,
        registrations: Iterable[CapabilityRegistration],
    ) -> None:
        # Validate the complete transaction before acquiring the commit lock.
        prepared = self._prepare(registrations)
        with self._lock:
            if self._frozen:
                raise RegistryFrozenError("capability registry is frozen")
            collisions = [
                registration.key
                for registration in prepared
                if registration.key in self._registrations
            ]
            if collisions:
                raise CapabilityCollisionError(
                    "capability key is already registered: "
                    + ", ".join(
                        (
                            f"{key.op_type}@{key.op_version.major}."
                            f"{key.op_version.minor}/{key.spec_digest}/"
                            f"{key.implementation_digest}"
                        )
                        for key in collisions
                    )
                )
            # No operation above mutates registry state: commit is all-or-nothing.
            self._registrations.update(
                (registration.key, registration) for registration in prepared
            )

    def freeze(
        self,
        upcasters: (
            UpcasterRegistry
            | UpcasterSnapshot
            | Iterable[UpcasterSnapshot]
            | None
        ) = None,
    ) -> CapabilityRegistry:
        candidates = self._snapshot_candidates(upcasters)
        with self._lock:
            if self._frozen:
                if candidates:
                    raise RegistryFrozenError("capability registry is frozen")
                return self
            snapshots = dict(self._upcaster_snapshots)
            for snapshot in candidates:
                self._merge_upcaster_snapshot(snapshots, snapshot)
            if not snapshots:
                empty = UpcasterRegistry().freeze()
                snapshots[empty.digest] = empty
            self._require_bound_upcasters(
                self._registrations.values(),
                snapshots,
            )
            self._registrations = {
                key: registration._bind(
                    snapshots[
                        registration.implementation_manifest.upcaster_digest
                    ]
                )
                for key, registration in self._registrations.items()
            }
            self._upcaster_snapshots = snapshots
            self._frozen = True
        return self

    def register_plugins_and_freeze(
        self,
        plugins: Iterable[CapabilityPlugin],
        *,
        upcasters: (
            UpcasterRegistry
            | UpcasterSnapshot
            | Iterable[UpcasterSnapshot]
            | None
        ) = None,
    ) -> None:
        plugin_snapshot = tuple(plugins)
        if not all(isinstance(plugin, CapabilityPlugin) for plugin in plugin_snapshot):
            raise InvalidCapabilityError(
                "registry accepts only CapabilityPlugin objects"
            )
        prepared = self._prepare(
            registration
            for plugin in plugin_snapshot
            for registration in plugin.registrations
        )
        candidates = self._snapshot_candidates(upcasters)
        with self._lock:
            if self._frozen:
                raise RegistryFrozenError("capability registry is frozen")
            combined = dict(self._registrations)
            collisions = [
                registration.key
                for registration in prepared
                if registration.key in combined
            ]
            if collisions:
                raise CapabilityCollisionError(
                    "capability key is already registered"
                )
            combined.update(
                (registration.key, registration) for registration in prepared
            )
            snapshots = dict(self._upcaster_snapshots)
            for snapshot in candidates:
                self._merge_upcaster_snapshot(snapshots, snapshot)
            if not snapshots:
                empty = UpcasterRegistry().freeze()
                snapshots[empty.digest] = empty
            self._require_bound_upcasters(combined.values(), snapshots)
            combined = {
                key: registration._bind(
                    snapshots[
                        registration.implementation_manifest.upcaster_digest
                    ]
                )
                for key, registration in combined.items()
            }
            # Registration, snapshot publication and freeze are one commit.
            self._registrations = combined
            self._upcaster_snapshots = snapshots
            self._frozen = True

    def resolve_upcaster_snapshot(self, digest: str) -> UpcasterSnapshot:
        with self._lock:
            if not self._frozen:
                raise RegistryNotFrozenError(
                    "capability registry must be frozen before snapshot resolution"
                )
            try:
                return self._upcaster_snapshots[digest]
            except KeyError as exc:
                raise UpcasterDigestMismatchError(
                    f"upcaster snapshot is unavailable: {digest}"
                ) from exc

    def resolve(
        self,
        key: CapabilityKey | None = None,
        *,
        op_type: str | None = None,
        op_version: SchemaRevision | None = None,
        spec_digest: str | None = None,
        implementation_digest: str | None = None,
    ) -> CapabilityRegistration:
        if key is None:
            if (
                op_type is None
                or op_version is None
                or spec_digest is None
                or implementation_digest is None
            ):
                raise TypeError(
                    "resolve requires an exact CapabilityKey or all four identity fields"
                )
            key = CapabilityKey(
                op_type=op_type,
                op_version=op_version,
                spec_digest=spec_digest,
                implementation_digest=implementation_digest,
            )
        elif any(
            value is not None
            for value in (op_type, op_version, spec_digest, implementation_digest)
        ):
            raise TypeError("resolve accepts either key or identity fields, not both")
        with self._lock:
            if not self._frozen:
                raise RegistryNotFrozenError(
                    "capability registry must be frozen before resolution"
                )
            try:
                return self._registrations[key]
            except KeyError as exc:
                raise CapabilityNotFoundError(
                    key,
                    tuple(
                        sorted(
                            self._registrations,
                            key=lambda item: (
                                item.op_type,
                                item.op_version.major,
                                item.op_version.minor,
                                item.spec_digest,
                                item.implementation_digest,
                            ),
                        )
                    ),
                ) from exc

    def resolve_request(self, request: OperationRequest) -> CapabilityRegistration:
        return self.resolve(
            op_type=request.op_type,
            op_version=request.op_version,
            spec_digest=request.operation_spec_digest,
            implementation_digest=request.implementation_digest,
        )

    def invoke(
        self,
        request: OperationRequest,
        context: object,
        /,
        *,
        error_context: ErrorContext | None = None,
    ) -> OperationResult:
        return self.resolve_request(request).invoke(
            request,
            context,
            error_context=error_context,
        )
