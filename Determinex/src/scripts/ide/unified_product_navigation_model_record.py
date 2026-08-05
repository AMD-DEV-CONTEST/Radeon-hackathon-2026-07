"""Records for DETERMINEX_UNIFIED_PRODUCT_NAVIGATION_MODEL_LOCK_001.

Defines the top-level Determinex product shell. Five surfaces, one
shared authority vocabulary, one shared proof/evidence spine.

Each surface declares its target users, beginner/professional
views, status states, blocked states, and the proof and
mutation boundaries that bound it. None of this writes anything;
this is a backend-side view-model that the frontend will render.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

UNIFIED_PRODUCT_NAVIGATION_MODEL_STATUS_TOKENS = (
    "UNIFIED_PRODUCT_NAVIGATION_MODEL_WRITTEN",
    "UNIFIED_PRODUCT_NAVIGATION_MODEL_VALIDATED",
    "UNIFIED_PRODUCT_NAVIGATION_MODEL_BLOCKED_AUTHORITY_CONFUSION",
    "UNIFIED_PRODUCT_NAVIGATION_MODEL_BLOCKED_MISSING_SURFACE",
)


# The five required top-level surfaces.
UNIFIED_PRODUCT_SURFACES = (
    "idea_lab",
    "repo_clinic",
    "maintenance_bay",
    "learning_studio",
    "proof_operator_center",
)


# Shared authority vocabulary — the eight classes a status token may
# fall into. Imported here as the source-of-truth so other surfaces
# can reference one constant.
SHARED_AUTHORITY_VOCABULARY = (
    "capability_available",
    "evidence_present",
    "request_pending",
    "admission_present",
    "approval_present",
    "execution_authorized",
    "source_mutation_authorized",
    "training_eligible",
)


@dataclass(frozen=True)
class ProductSurface:
    key: str
    title: str
    purpose: str
    target_users: tuple[str, ...]
    beginner_view: str
    professional_view: str
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    status_states: tuple[str, ...]
    blocked_states: tuple[str, ...]
    proof_evidence_requirements: tuple[str, ...]
    source_mutation_boundary: str
    training_eligibility_boundary: str
    claim_caveats: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        for f in (
            "target_users",
            "inputs",
            "outputs",
            "status_states",
            "blocked_states",
            "proof_evidence_requirements",
            "claim_caveats",
        ):
            d[f] = list(d[f])
        return d


@dataclass(frozen=True)
class UnifiedProductNavigationModelRecord:
    decision: str
    surfaces: tuple[ProductSurface, ...]
    shared_authority_vocabulary: tuple[str, ...]
    unsupported_state_visible_per_surface: dict
    source_mutation_authorized: bool = False
    training_eligible: bool = False
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["surfaces"] = [s.to_dict() for s in self.surfaces]
        d["shared_authority_vocabulary"] = list(self.shared_authority_vocabulary)
        d["notes"] = list(self.notes)
        return d

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    @property
    def is_written(self) -> bool:
        return self.decision in (
            "UNIFIED_PRODUCT_NAVIGATION_MODEL_WRITTEN",
            "UNIFIED_PRODUCT_NAVIGATION_MODEL_VALIDATED",
        )

    @property
    def is_blocked(self) -> bool:
        return self.decision.startswith("UNIFIED_PRODUCT_NAVIGATION_MODEL_BLOCKED_")


__all__ = [
    "UNIFIED_PRODUCT_NAVIGATION_MODEL_STATUS_TOKENS",
    "UNIFIED_PRODUCT_SURFACES",
    "SHARED_AUTHORITY_VOCABULARY",
    "ProductSurface",
    "UnifiedProductNavigationModelRecord",
]
