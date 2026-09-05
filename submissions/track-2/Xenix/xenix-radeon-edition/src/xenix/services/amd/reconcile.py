"""Placement-neutral reconciliation ports for the AMD control plane.

The deployment facade owns durable lifecycle transitions.  A placement driver
owns observation, target acquisition, process realization, live bindings, and
exact cleanup.  This small contract keeps those concerns independent without a
generic inference gateway or a mutable endpoint registry.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Protocol

from .compatibility import TargetCompatibilityFacts
from .manifests import ComponentManifest, ExecutionProfileManifest, ManifestCapability
from .placement import AmdExecutionSession
from .progress import AmdProgressSink


_LOCATION_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+-]{0,159}$")
_WSL_DISTRIBUTION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._()@+-]{0,79}$")


@dataclass(frozen=True, slots=True)
class AmdExecutionLocation:
    """One explicit Linux execution location for a deployment operation.

    This is deliberately not a generic ``target_id``.  The shape makes the
    trust and transport distinction durable at the controller boundary: SSH
    receives an enrolled opaque target identifier, while Local WSL receives
    the user's explicitly selected distribution reference.  A historical
    Local Linux row has neither reference and is accepted only by its legacy
    cleanup controller.
    """

    placement_kind: str
    private_target_id: str | None = field(default=None, repr=False)
    local_wsl_distribution: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.placement_kind not in {"local_linux", "local_wsl", "private_ssh"}:
            raise ValueError("AMD execution location placement is unsupported.")
        if self.placement_kind == "private_ssh":
            if (
                not isinstance(self.private_target_id, str)
                or not _LOCATION_IDENTIFIER.fullmatch(self.private_target_id)
                or self.local_wsl_distribution is not None
            ):
                raise ValueError("Private SSH execution location is invalid.")
            return
        if self.placement_kind == "local_wsl":
            if (
                self.private_target_id is not None
                or not isinstance(self.local_wsl_distribution, str)
                or not _WSL_DISTRIBUTION.fullmatch(self.local_wsl_distribution)
                or self.local_wsl_distribution != self.local_wsl_distribution.strip()
                or self.local_wsl_distribution.startswith("-")
            ):
                raise ValueError("Local WSL execution location is invalid.")
            return
        if self.private_target_id is not None or self.local_wsl_distribution is not None:
            raise ValueError("Historical Local Linux execution location is invalid.")

    @property
    def operation_key(self) -> tuple[str, str]:
        """Return the in-process serialization key without live endpoint data."""

        if self.placement_kind == "private_ssh":
            assert self.private_target_id is not None
            return (self.placement_kind, self.private_target_id)
        if self.placement_kind == "local_wsl":
            assert self.local_wsl_distribution is not None
            return (self.placement_kind, self.local_wsl_distribution)
        return (self.placement_kind, "historical-local-linux")


@dataclass(frozen=True, slots=True)
class AmdGenerationMaterialization:
    """Exact durable generation/recipe pair given to one placement realization."""

    capability: ManifestCapability
    generation_id: str
    manifest: ComponentManifest


class AmdCancellationSignal(Protocol):
    """Volatile signal used only to stop a committed retirement race."""

    def is_set(self) -> bool: ...


class AmdPlacementController(Protocol):
    """A Local or Private placement implementation owned by the AMD slice."""

    @property
    def placement_kind(self) -> str: ...

    def observe(
        self,
        *,
        profile: ExecutionProfileManifest,
        location: AmdExecutionLocation,
    ) -> TargetCompatibilityFacts: ...

    def materialize(
        self,
        *,
        installation_id: str,
        location: AmdExecutionLocation,
        profile: ExecutionProfileManifest,
        generations: tuple[AmdGenerationMaterialization, ...],
        cancellation: AmdCancellationSignal | None = None,
        progress: AmdProgressSink | None = None,
    ) -> AmdExecutionSession: ...

    def open_retirement_session(
        self,
        *,
        installation_id: str,
        location: AmdExecutionLocation,
        profile: ExecutionProfileManifest,
        generations: tuple[AmdGenerationMaterialization, ...],
    ) -> AmdExecutionSession: ...

    def self_test(
        self,
        *,
        session: AmdExecutionSession,
        generation: AmdGenerationMaterialization,
    ) -> str: ...

    def cancel_generation_provisioning(
        self,
        *,
        session: AmdExecutionSession,
        installation_id: str,
        profile: ExecutionProfileManifest,
        generation: AmdGenerationMaterialization,
    ) -> None: ...

    def retire_generation(
        self,
        *,
        session: AmdExecutionSession,
        installation_id: str,
        profile: ExecutionProfileManifest,
        generation: AmdGenerationMaterialization,
    ) -> None: ...


__all__ = [
    "AmdExecutionLocation",
    "AmdGenerationMaterialization",
    "AmdCancellationSignal",
    "AmdPlacementController",
]
