"""Typed runtime model router.

Promotes the prose-only ``scripts/model_advisor.py`` into a structured
routing surface. The router itself **never invokes a model, network, or
subprocess**. It produces a ``RouteRecord`` whose ``execution_authorized``
boolean is the *only* thing a caller may consult before making an actual
inference call.

Invariants (locked by tests; do not weaken):

  1. Routing is a pure function of ``(task_class, mode, config, inventory)``.
  2. The router mutates no source, no corpus, and no evidence files.
  3. Unsupported task classes fail closed with a blocked record.
  4. Stale model ids fail closed with ``ROUTE_BLOCKED_STALE_MODEL_ID``.
  5. Missing local model availability falls back along the chain until
     either an available role is found or the chain ends in ``NO_MODEL``.
  6. Dry-run mode never sets ``execution_authorized=True``.
  7. ``training_eligible`` is **never** flipped to ``True`` by routing
     alone — corpus eligibility is a separate gate (a later rung).
  8. ``corpus_write_authorized`` likewise stays ``False`` here.
  9. The router takes no fast-drive dependency and reads no network resource.
 10. ``RouterMode.LIVE`` does not by itself imply network access — it
     only changes the decision token from DRY_RUN to SELECTED. Whether
     a configured role *requires* network must be enforced by the caller
     based on ``allow_network_models``.
"""

from __future__ import annotations

import enum
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from .model_inventory import LocalModelInventory
from .model_router_record import RouteRecord

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class TaskClass(str, enum.Enum):
    REPO_TRIAGE = "REPO_TRIAGE"
    BUILD_DIAGNOSIS = "BUILD_DIAGNOSIS"
    TEST_FAILURE_LOCALIZATION = "TEST_FAILURE_LOCALIZATION"
    PATCH_PLANNING = "PATCH_PLANNING"
    PATCH_GENERATION = "PATCH_GENERATION"
    PATCH_REVIEW = "PATCH_REVIEW"
    VERIFIER_SUMMARY = "VERIFIER_SUMMARY"
    CORPUS_ELIGIBILITY_REVIEW = "CORPUS_ELIGIBILITY_REVIEW"
    GENERAL_EXPLANATION = "GENERAL_EXPLANATION"
    UNKNOWN = "UNKNOWN"


class ModelRole(str, enum.Enum):
    FAST_LOCAL = "FAST_LOCAL"
    STRONG_LOCAL = "STRONG_LOCAL"
    CODE_SPECIALIST = "CODE_SPECIALIST"
    REASONING_SPECIALIST = "REASONING_SPECIALIST"
    NO_MODEL = "NO_MODEL"


class RouteDecision(str, enum.Enum):
    ROUTE_SELECTED = "ROUTE_SELECTED"
    ROUTE_DRY_RUN_SELECTED = "ROUTE_DRY_RUN_SELECTED"
    ROUTE_BLOCKED_NO_AVAILABLE_MODEL = "ROUTE_BLOCKED_NO_AVAILABLE_MODEL"
    ROUTE_BLOCKED_STALE_MODEL_ID = "ROUTE_BLOCKED_STALE_MODEL_ID"
    ROUTE_BLOCKED_UNSUPPORTED_TASK_CLASS = "ROUTE_BLOCKED_UNSUPPORTED_TASK_CLASS"
    ROUTE_FALLBACK_SELECTED = "ROUTE_FALLBACK_SELECTED"
    ROUTE_NO_MODEL_REQUIRED = "ROUTE_NO_MODEL_REQUIRED"


class RouterMode(str, enum.Enum):
    DRY_RUN = "dry_run"
    LIVE = "live"


# ---------------------------------------------------------------------------
# Default routes
# ---------------------------------------------------------------------------


#: Preferred role plus deterministic fallback chain per task class. Unknown
#: is intentionally absent (fail closed).
DEFAULT_ROUTES: Mapping[TaskClass, tuple[ModelRole, tuple[ModelRole, ...]]] = {
    TaskClass.REPO_TRIAGE: (
        ModelRole.FAST_LOCAL,
        (ModelRole.STRONG_LOCAL, ModelRole.NO_MODEL),
    ),
    TaskClass.BUILD_DIAGNOSIS: (
        ModelRole.CODE_SPECIALIST,
        (ModelRole.STRONG_LOCAL, ModelRole.FAST_LOCAL, ModelRole.NO_MODEL),
    ),
    TaskClass.TEST_FAILURE_LOCALIZATION: (
        ModelRole.CODE_SPECIALIST,
        (ModelRole.STRONG_LOCAL, ModelRole.NO_MODEL),
    ),
    TaskClass.PATCH_PLANNING: (
        ModelRole.REASONING_SPECIALIST,
        (ModelRole.CODE_SPECIALIST, ModelRole.NO_MODEL),
    ),
    TaskClass.PATCH_GENERATION: (
        ModelRole.CODE_SPECIALIST,
        (ModelRole.NO_MODEL,),
    ),
    TaskClass.PATCH_REVIEW: (
        ModelRole.REASONING_SPECIALIST,
        (ModelRole.CODE_SPECIALIST, ModelRole.NO_MODEL),
    ),
    TaskClass.VERIFIER_SUMMARY: (
        ModelRole.FAST_LOCAL,
        (ModelRole.NO_MODEL,),
    ),
    TaskClass.CORPUS_ELIGIBILITY_REVIEW: (
        ModelRole.REASONING_SPECIALIST,
        (ModelRole.CODE_SPECIALIST, ModelRole.NO_MODEL),
    ),
    TaskClass.GENERAL_EXPLANATION: (
        ModelRole.FAST_LOCAL,
        (ModelRole.NO_MODEL,),
    ),
}


# ---------------------------------------------------------------------------
# Role → model-id mapping (defaults)
# ---------------------------------------------------------------------------

#: Default role-to-model mapping. These ids match the v11/v6/v5 generation
#: documented in CLAUDE.md ("Role Assignments"). The mapping can be
#: overridden per-router via ``role_to_model_id`` argument.
DEFAULT_ROLE_TO_MODEL_ID: Mapping[ModelRole, str] = {
    ModelRole.FAST_LOCAL: "determinex-observer-v6-dsl",
    ModelRole.STRONG_LOCAL: "determinex-sentinel-v5-dsl",
    ModelRole.CODE_SPECIALIST: "determinex-engineer-v11-dsl",
    ModelRole.REASONING_SPECIALIST: "determinex-sentinel-v5-dsl",
    ModelRole.NO_MODEL: "",  # sentinel: no id needed
}


# ---------------------------------------------------------------------------
# Stale / current model ids
# ---------------------------------------------------------------------------

#: Currently-supported model ids per CLAUDE.md role assignments.
CURRENT_MODEL_IDS: frozenset[str] = frozenset(
    {
        "determinex-engineer-v11-dsl",
        "determinex-observer-v6-dsl",
        "determinex-sentinel-v5-dsl",
    }
)

#: Explicitly superseded ids. The router flags these as stale even if
#: someone configures them via env var. (Discovered at audit time:
#: scripts/codebase_explorer.py lines 58-59 referenced v10/v5 defaults.)
STALE_MODEL_IDS: frozenset[str] = frozenset(
    {
        "determinex-engineer-v10-dsl",
        "determinex-engineer-v9-dsl",
        "determinex-engineer-v8",
        "determinex-observer-v5-dsl",
        "determinex-observer-v5",
        "determinex-observer-v4",
        "determinex-observer-v3",
        "determinex-sentinel-v4",
        "determinex-sentinel-v3",
        "determinex-sentinel-v2",
    }
)


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RouterConfig:
    """Router-level config knobs.

    All booleans default to the safety-conservative value. Mode default is
    DRY_RUN. Tests and callers may override per-call as needed.
    """

    default_mode: RouterMode = RouterMode.DRY_RUN
    allow_network_models: bool = False
    allow_unverified_model_ids: bool = False
    role_to_model_id: Mapping[ModelRole, str] = field(
        default_factory=lambda: dict(DEFAULT_ROLE_TO_MODEL_ID)
    )
    routes: Mapping[TaskClass, tuple[ModelRole, tuple[ModelRole, ...]]] = field(
        default_factory=lambda: dict(DEFAULT_ROUTES)
    )


class ModelRouter:
    """Pure-function routing surface.

    Construct once per process (or per test). Call ``route(...)`` to obtain
    a ``RouteRecord``. The router holds no mutable state.
    """

    __slots__ = ("_config", "_inventory")

    def __init__(
        self,
        config: RouterConfig | None = None,
        inventory: LocalModelInventory | None = None,
    ) -> None:
        self._config = config or RouterConfig()
        self._inventory = inventory or LocalModelInventory.empty()

    # ------------------------------------------------------------------
    # Accessors (useful for tests and the CLI)
    # ------------------------------------------------------------------

    @property
    def config(self) -> RouterConfig:
        return self._config

    @property
    def inventory(self) -> LocalModelInventory:
        return self._inventory

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------

    def route(
        self,
        task_class: TaskClass | str,
        mode: RouterMode | str | None = None,
    ) -> RouteRecord:
        """Produce a structured route decision."""
        tc = self._normalize_task_class(task_class)
        rm = self._normalize_mode(mode)

        # Unsupported task class (including UNKNOWN) → fail closed.
        if tc not in self._config.routes:
            return self._blocked_record(
                task_class=tc,
                requested_mode=rm,
                decision=RouteDecision.ROUTE_BLOCKED_UNSUPPORTED_TASK_CLASS,
                note=(
                    "Task class is not registered in router config. "
                    "Unsupported task classes fail closed; no model is selected."
                ),
            )

        preferred, fallback = self._config.routes[tc]
        chain: tuple[ModelRole, ...] = (preferred,) + tuple(fallback)
        notes: list[str] = []

        # Walk the chain; pick the first role whose model id is available
        # (or NO_MODEL, which is always trivially available).
        chosen_role: ModelRole | None = None
        chosen_model_id: str = ""
        used_fallback = False
        for idx, role in enumerate(chain):
            if role is ModelRole.NO_MODEL:
                chosen_role = role
                chosen_model_id = ""
                if idx > 0:
                    used_fallback = True
                    notes.append(
                        f"Reached NO_MODEL after exhausting roles {[r.value for r in chain[:idx]]}."
                    )
                break

            model_id = self._config.role_to_model_id.get(role, "") or ""

            # Stale-id guard — short-circuit *before* availability check.
            if model_id in STALE_MODEL_IDS:
                # Blocked decision is final regardless of mode.
                notes.append(
                    f"Role {role.value} maps to stale id {model_id!r} (see STALE_MODEL_IDS)."
                )
                return self._blocked_record(
                    task_class=tc,
                    requested_mode=rm,
                    decision=RouteDecision.ROUTE_BLOCKED_STALE_MODEL_ID,
                    selected_route=role,
                    selected_model_id=model_id,
                    fallback_chain=chain,
                    stale_detected=True,
                    note=notes[-1],
                )

            # Unverified id guard — block unless explicitly allowed.
            if (
                model_id
                and model_id not in CURRENT_MODEL_IDS
                and not self._config.allow_unverified_model_ids
            ):
                notes.append(
                    f"Role {role.value} maps to unverified id {model_id!r} "
                    f"(not in CURRENT_MODEL_IDS); allow_unverified_model_ids=False."
                )
                # Fall through to next role rather than hard-block; the
                # caller can flip allow_unverified_model_ids to opt in.
                used_fallback = True
                continue

            if self._inventory.is_available(model_id):
                chosen_role = role
                chosen_model_id = model_id
                if idx > 0:
                    used_fallback = True
                    notes.append(
                        f"Selected fallback role {role.value!r} after "
                        f"preferred {chain[0].value!r} unavailable."
                    )
                break
            notes.append(f"Role {role.value} (model {model_id!r}) not present in inventory.")

        # Nothing in the chain matched (no NO_MODEL terminus).
        if chosen_role is None:
            return self._blocked_record(
                task_class=tc,
                requested_mode=rm,
                decision=RouteDecision.ROUTE_BLOCKED_NO_AVAILABLE_MODEL,
                fallback_chain=chain,
                note="Fallback chain exhausted without a registered NO_MODEL terminus.",
            )

        # NO_MODEL chosen → explicit "no-model required" record.
        if chosen_role is ModelRole.NO_MODEL:
            return RouteRecord(
                task_class=tc.value,
                requested_mode=rm.value,
                selected_route=ModelRole.NO_MODEL.value,
                selected_model_id="",
                fallback_chain=tuple(r.value for r in chain),
                availability_checked=True,
                stale_model_id_detected=False,
                decision=RouteDecision.ROUTE_NO_MODEL_REQUIRED.value,
                execution_authorized=False,
                corpus_write_authorized=False,
                training_eligible=False,
                notes=tuple(notes),
            )

        # Live or dry-run with a chosen, available, non-stale, verified id.
        if rm is RouterMode.DRY_RUN:
            return RouteRecord(
                task_class=tc.value,
                requested_mode=rm.value,
                selected_route=chosen_role.value,
                selected_model_id=chosen_model_id,
                fallback_chain=tuple(r.value for r in chain),
                availability_checked=True,
                stale_model_id_detected=False,
                decision=RouteDecision.ROUTE_DRY_RUN_SELECTED.value,
                execution_authorized=False,
                corpus_write_authorized=False,
                training_eligible=False,
                notes=tuple(notes),
            )

        # rm is LIVE
        decision = (
            RouteDecision.ROUTE_FALLBACK_SELECTED if used_fallback else RouteDecision.ROUTE_SELECTED
        )
        return RouteRecord(
            task_class=tc.value,
            requested_mode=rm.value,
            selected_route=chosen_role.value,
            selected_model_id=chosen_model_id,
            fallback_chain=tuple(r.value for r in chain),
            availability_checked=True,
            stale_model_id_detected=False,
            decision=decision.value,
            execution_authorized=True,
            # Corpus + training eligibility require a separate gate; routing
            # does not by itself open them.
            corpus_write_authorized=False,
            training_eligible=False,
            notes=tuple(notes),
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_task_class(tc: TaskClass | str) -> TaskClass:
        if isinstance(tc, TaskClass):
            return tc
        try:
            return TaskClass(tc)
        except ValueError:
            return TaskClass.UNKNOWN

    def _normalize_mode(self, mode: RouterMode | str | None) -> RouterMode:
        if mode is None:
            return self._config.default_mode
        if isinstance(mode, RouterMode):
            return mode
        try:
            return RouterMode(mode)
        except ValueError:
            return self._config.default_mode

    @staticmethod
    def _blocked_record(
        *,
        task_class: TaskClass,
        requested_mode: RouterMode,
        decision: RouteDecision,
        selected_route: ModelRole | None = None,
        selected_model_id: str = "",
        fallback_chain: Iterable[ModelRole] = (),
        stale_detected: bool = False,
        note: str | None = None,
    ) -> RouteRecord:
        return RouteRecord(
            task_class=task_class.value,
            requested_mode=requested_mode.value,
            selected_route=(selected_route.value if selected_route else ModelRole.NO_MODEL.value),
            selected_model_id=selected_model_id,
            fallback_chain=tuple(r.value for r in fallback_chain),
            availability_checked=False,
            stale_model_id_detected=stale_detected,
            decision=decision.value,
            execution_authorized=False,
            corpus_write_authorized=False,
            training_eligible=False,
            notes=((note,) if note else ()),
        )


__all__ = [
    "TaskClass",
    "ModelRole",
    "RouteDecision",
    "RouterMode",
    "RouterConfig",
    "ModelRouter",
    "DEFAULT_ROUTES",
    "DEFAULT_ROLE_TO_MODEL_ID",
    "CURRENT_MODEL_IDS",
    "STALE_MODEL_IDS",
]
