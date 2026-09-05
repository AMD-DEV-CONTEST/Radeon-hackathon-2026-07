"""Read-only AMD deployment status projections.

Status is derived from durable lifecycle rows, capability projection status, and
the current in-memory realization.  In particular, there is no persisted
aggregate ``READY`` state that could outlive a process, tunnel, or binding.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .manifests import ManifestCapability


class AmdInstallationCondition(StrEnum):
    NOT_MATERIALIZED = "not_materialized"
    INSTALLING = "installing"
    DEGRADED = "degraded"
    OPERATIONAL = "operational"
    RETIRING = "retiring"
    REMOVAL_BLOCKED = "removal_blocked"
    REMOVED = "removed"
    INCOMPATIBLE = "incompatible"


@dataclass(frozen=True, slots=True)
class AmdComponentStatus:
    capability: ManifestCapability
    generation_id: str | None
    manifest_digest: str
    lifecycle_state: str
    phase: str
    error_code: str | None
    projected: bool
    projection_retiring: bool
    selected: bool
    live: bool

    @property
    def operational(self) -> bool:
        return self.lifecycle_state == "registered" and self.projected and not self.projection_retiring and self.live


@dataclass(frozen=True, slots=True)
class AmdInstallationStatus:
    installation_id: str
    placement: str
    profile_id: str
    profile_digest: str
    desired_presence: bool
    lifecycle_state: str
    condition: AmdInstallationCondition
    target_observation_error_code: str | None
    compatibility_issues: tuple[str, ...]
    components: tuple[AmdComponentStatus, ...]

    @property
    def profile_usable(self) -> bool:
        return bool(self.components) and all(component.operational for component in self.components)

    @property
    def selected_capabilities(self) -> tuple[ManifestCapability, ...]:
        return tuple(component.capability for component in self.components if component.selected)


__all__ = [
    "AmdComponentStatus",
    "AmdInstallationCondition",
    "AmdInstallationStatus",
]
