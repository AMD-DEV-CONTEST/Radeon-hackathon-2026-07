"""Structured route-decision record produced by ``ModelRouter.route()``.

The record is the *only* output of a route call. It is reproducible from
config (same inputs → same record), JSON-serializable, and carries
exactly the authorization booleans a downstream caller is allowed to
consult:

  * ``execution_authorized``      — may the caller actually invoke the model?
  * ``corpus_write_authorized``   — may anything written downstream be
                                    admitted to the training corpus?
  * ``training_eligible``         — may a row derived from this route be
                                    flagged training-eligible?

All three default to ``False`` and are flipped to ``True`` only by an
explicit live-mode route through a verified, available model id. Dry-run
and any blocked decision keep them all ``False``.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class RouteRecord:
    """Immutable, JSON-serializable route decision."""

    task_class: str
    requested_mode: str  # "dry_run" | "live"
    selected_route: str  # ModelRole value (or "NO_MODEL")
    selected_model_id: str  # may be "" when blocked or no model
    fallback_chain: tuple[str, ...]  # ordered ModelRole values
    availability_checked: bool
    stale_model_id_detected: bool
    decision: str  # RouteDecision value
    execution_authorized: bool = False
    corpus_write_authorized: bool = False
    training_eligible: bool = False
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["fallback_chain"] = list(self.fallback_chain)
        d["notes"] = list(self.notes)
        return d

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    # ------------------------------------------------------------------
    # Convenience predicates
    # ------------------------------------------------------------------

    @property
    def is_blocked(self) -> bool:
        return self.decision.startswith("ROUTE_BLOCKED_")

    @property
    def is_dry_run(self) -> bool:
        return self.decision == "ROUTE_DRY_RUN_SELECTED"

    @property
    def is_no_model(self) -> bool:
        return self.decision == "ROUTE_NO_MODEL_REQUIRED" or self.selected_route == "NO_MODEL"
