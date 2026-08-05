"""Records for DETERMINEX_UNIFIED_PRODUCT_SPLASH_DEMO_SPEC_LOCK_001."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

UNIFIED_PRODUCT_SPLASH_DEMO_SPEC_STATUS_TOKENS = (
    "UNIFIED_PRODUCT_SPLASH_DEMO_SPEC_WRITTEN",
    "UNIFIED_PRODUCT_SPLASH_DEMO_BLOCKED_FALSE_UNIVERSALITY",
    "UNIFIED_PRODUCT_SPLASH_DEMO_BLOCKED_AUTHORITY_CONFUSION",
    "UNIFIED_PRODUCT_SPLASH_DEMO_BLOCKED_MISSING_PROOF_VIEW",
)


# Required tagline and required negative caveat phrases.
REQUIRED_TAGLINE = "Proof Before Mutation"
REQUIRED_PHRASES = (
    "Generated is not verified.",
    "Working means build/test/smoke passed.",
)
REQUIRED_NEGATIVE_CAVEATS = (
    "not all apps",
    "not all languages",
    "not production-ready arbitrary apps",
    "not training enabled",
)


@dataclass(frozen=True)
class DemoSequenceStep:
    n: int  # 1..5
    surface: str  # one of the five product surfaces
    title: str
    description: str
    is_blocked_step: bool = False
    is_teaching_step: bool = False
    is_proof_view: bool = False


@dataclass(frozen=True)
class UnifiedProductSplashDemoSpecRecord:
    decision: str
    sequence: tuple[DemoSequenceStep, ...]
    tagline: str
    required_phrases_present: bool
    required_caveats_present: bool
    happy_path_step_present: bool
    blocked_path_step_present: bool
    teaching_step_present: bool
    proof_view_step_present: bool
    network_required: bool
    docker_required: bool
    programbench_required: bool
    real_external_mutation: bool
    source_mutation_authorized: bool = False
    training_eligible: bool = False
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["sequence"] = [asdict(s) for s in self.sequence]
        d["notes"] = list(self.notes)
        return d

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    @property
    def is_written(self) -> bool:
        return self.decision == "UNIFIED_PRODUCT_SPLASH_DEMO_SPEC_WRITTEN"

    @property
    def is_blocked(self) -> bool:
        return self.decision.startswith("UNIFIED_PRODUCT_SPLASH_DEMO_BLOCKED_")


__all__ = [
    "UNIFIED_PRODUCT_SPLASH_DEMO_SPEC_STATUS_TOKENS",
    "REQUIRED_TAGLINE",
    "REQUIRED_PHRASES",
    "REQUIRED_NEGATIVE_CAVEATS",
    "DemoSequenceStep",
    "UnifiedProductSplashDemoSpecRecord",
]
