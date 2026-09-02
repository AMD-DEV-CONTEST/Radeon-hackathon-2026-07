"""Records for DETERMINEX_LIVE_REACT_PRODUCT_SHELL_DEMO_READINESS_FINAL_STATE_LOCK_001."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

LIVE_REACT_PRODUCT_SHELL_DEMO_READINESS_FINAL_STATE_STATUS_TOKENS = (
    "LIVE_REACT_PRODUCT_SHELL_DEMO_READINESS_FINAL_STATE_PASSED",
    "LIVE_REACT_PRODUCT_SHELL_DEMO_READINESS_FINAL_STATE_BLOCKED_MISSING_RUNG",
    "LIVE_REACT_PRODUCT_SHELL_DEMO_READINESS_FINAL_STATE_BLOCKED_DIMENSION_NOT_CLOSED",
)


@dataclass(frozen=True)
class LiveReactProductShellDemoReadinessFinalStateRecord:
    # verified_demo_binding_closed and release_blocker_panel_closed were
    # dropped 2026-07-20: their panels+locks+tests were deliberately
    # archived (commit 30b3ff570) as a Claude<->Codex tandem-pipeline
    # trail, not real features. Was four dimensions, now two.
    decision: str
    browser_snapshot_closed: bool
    happy_blocked_path_closed: bool
    source_mutation_authorized: bool
    training_eligible: bool
    release_ready: bool
    unsupported_claims_blocked: bool
    rungs_inspected: tuple[str, ...] = field(default_factory=tuple)
    next_recommended_rung: str = ""
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["rungs_inspected"] = list(self.rungs_inspected)
        d["notes"] = list(self.notes)
        return d

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    @property
    def is_passed(self) -> bool:
        return self.decision == ("LIVE_REACT_PRODUCT_SHELL_DEMO_READINESS_FINAL_STATE_PASSED")

    @property
    def is_blocked(self) -> bool:
        return self.decision.startswith(
            "LIVE_REACT_PRODUCT_SHELL_DEMO_READINESS_FINAL_STATE_BLOCKED_"
        )


__all__ = [
    "LIVE_REACT_PRODUCT_SHELL_DEMO_READINESS_FINAL_STATE_STATUS_TOKENS",
    "LiveReactProductShellDemoReadinessFinalStateRecord",
]
