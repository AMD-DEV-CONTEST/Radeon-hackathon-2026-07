"""Auditable episodic strategy memory for bounded mobile-task retries."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class RetryStrategy:
    name: str
    policy_mode: str
    force_memory: bool
    learned_arm_authority: bool
    cooperative_safe: bool
    depth_sidecar: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RecoveryRecipe:
    """Small, bounded physical adjustment applied between whole-task attempts."""

    name: str
    approach_speed_scale: float = 1.0
    contact_offset_m: tuple[float, float] = (0.0, 0.0)
    contact_penetration_delta_m: float = 0.0
    vertical_speed_scale: float = 1.0
    lift_height_delta_m: float = 0.0
    placement_clearance_m: float = 0.015

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("recovery recipe name must be non-empty")
        values = (
            self.approach_speed_scale,
            *self.contact_offset_m,
            self.contact_penetration_delta_m,
            self.vertical_speed_scale,
            self.lift_height_delta_m,
            self.placement_clearance_m,
        )
        if any(not math.isfinite(value) for value in values):
            raise ValueError("recovery recipe values must be finite")
        if not 0.40 <= self.approach_speed_scale <= 1.0:
            raise ValueError("approach_speed_scale must be in [0.40, 1.0]")
        if any(abs(value) > 0.008 for value in self.contact_offset_m):
            raise ValueError("contact offsets must remain within 8 mm")
        if not -0.0015 <= self.contact_penetration_delta_m <= 0.0015:
            raise ValueError("contact penetration adjustment must remain within 1.5 mm")
        if not 0.60 <= self.vertical_speed_scale <= 1.0:
            raise ValueError("vertical_speed_scale must be in [0.60, 1.0]")
        if not 0.0 <= self.lift_height_delta_m <= 0.020:
            raise ValueError("lift height adjustment must be in [0, 20] mm")
        if not 0.008 <= self.placement_clearance_m <= 0.020:
            raise ValueError("placement clearance must be in [8, 20] mm")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RecoveryPlan:
    """Harness decision containing both policy authority and physical recovery."""

    strategy: RetryStrategy
    recipe: RecoveryRecipe

    @property
    def key(self) -> str:
        return f"{self.strategy.name}@{self.recipe.name}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "strategy": self.strategy.to_dict(),
            "recipe": self.recipe.to_dict(),
        }


PASH_DUAL_ARM = RetryStrategy(
    "pash_dual_arm", "base_dual_arm_residual", True, True, True, True
)
PASH_ARM = RetryStrategy("pash_arm", "base_arm_residual", True, True, False, True)
PASH_BASE = RetryStrategy("pash_base", "base_residual", True, False, True, True)
EXPERT_RECOVERY = RetryStrategy("expert_recovery", "shadow", False, False, True, False)
DEFAULT_STRATEGIES = (PASH_DUAL_ARM, PASH_ARM, PASH_BASE, EXPERT_RECOVERY)

NOMINAL_RECOVERY = RecoveryRecipe("nominal")
SEAL_SEARCH_PLUS_Y = RecoveryRecipe(
    "seal_search_plus_y",
    approach_speed_scale=0.75,
    contact_offset_m=(0.0, 0.006),
    contact_penetration_delta_m=0.001,
)
SEAL_SEARCH_MINUS_Y = RecoveryRecipe(
    "seal_search_minus_y",
    approach_speed_scale=0.60,
    contact_offset_m=(0.0, -0.006),
    contact_penetration_delta_m=0.001,
)
GENTLE_LIFT = RecoveryRecipe(
    "gentle_lift",
    approach_speed_scale=0.75,
    contact_penetration_delta_m=0.0005,
    vertical_speed_scale=0.75,
    lift_height_delta_m=0.015,
)
PRECISION_PLACE = RecoveryRecipe(
    "precision_place",
    vertical_speed_scale=0.75,
    placement_clearance_m=0.010,
)
FORCE_RETREAT = RecoveryRecipe(
    "force_retreat",
    approach_speed_scale=0.50,
    contact_penetration_delta_m=-0.001,
    vertical_speed_scale=0.70,
)
TRANSPORT_STABILIZE = RecoveryRecipe(
    "transport_stabilize",
    approach_speed_scale=0.75,
    vertical_speed_scale=0.70,
    lift_height_delta_m=0.010,
)


def classify_mobile_failure(summary: dict[str, Any]) -> str | None:
    """Return the first failed closed-loop gate, or None for a valid success."""

    if bool(summary.get("success")):
        return None
    suction = summary.get("suction") or {}
    cradle = (summary.get("cradle") or {}).get("physical") or {}
    peak_force = max(
        float(suction.get("max_contact_force_n") or 0.0),
        float(suction.get("max_suction_force_n") or 0.0),
        float(cradle.get("max_contact_force_n") or 0.0),
    )
    if peak_force >= 35.0:
        return "force_safety_abort"
    if not bool(summary.get("scene_stable")):
        return "scene_stability_failure"
    if not bool(summary.get("latched")):
        return (
            "contact_failure"
            if float(suction.get("max_contact_force_n") or 0.0) <= 0.0
            else "suction_latch_failure"
        )
    ordered_gates = (
        ("lift_success", "lift_support_failure"),
        ("transport_success", "transport_failure"),
        ("placed_before_release", "placement_failure"),
        ("released", "release_failure"),
    )
    for field, stage in ordered_gates:
        if not bool(summary.get(field)):
            return stage
    return "unclassified"


def strategy_context(
    *, profile: str, mass_kg: float, previous_failure: str | None
) -> str:
    if not profile.strip():
        raise ValueError("profile must be non-empty")
    if not math.isfinite(mass_kg) or mass_kg <= 0.0:
        raise ValueError("mass_kg must be finite and positive")
    mass_band = "light" if mass_kg < 0.40 else "medium" if mass_kg < 0.65 else "heavy"
    return f"{profile}:{mass_band}:{previous_failure or 'initial'}"


class EpisodicStrategyMemory:
    """Small persisted bandit memory; it selects strategies, not robot actions."""

    def __init__(self, payload: dict[str, Any] | None = None) -> None:
        payload = payload or {}
        if payload and payload.get("protocol") != "pash-episodic-strategy-memory-v1":
            raise ValueError("unsupported episodic strategy-memory protocol")
        contexts = payload.get("contexts") or {}
        if not isinstance(contexts, dict):
            raise ValueError("strategy-memory contexts must be an object")
        self.contexts: dict[str, dict[str, dict[str, int]]] = contexts

    @classmethod
    def load(cls, path: Path) -> "EpisodicStrategyMemory":
        if not path.exists():
            return cls()
        return cls(json.loads(path.read_text(encoding="utf-8")))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "protocol": "pash-episodic-strategy-memory-v1",
            "contexts": self.contexts,
            "claim_boundary": (
                "episode-level strategy selection only; model weights never change during "
                "an active rollout and retry success is reported separately from first-attempt success"
            ),
        }

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.parent / f".{path.name}.tmp"
        temporary.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        temporary.replace(path)

    def record(
        self,
        *,
        context: str,
        strategy: RetryStrategy,
        success: bool,
        force_abort: bool,
    ) -> None:
        self.record_key(
            context=context,
            arm_name=strategy.name,
            success=success,
            force_abort=force_abort,
        )

    def record_plan(
        self,
        *,
        context: str,
        plan: RecoveryPlan,
        success: bool,
        force_abort: bool,
    ) -> None:
        self.record_key(
            context=context,
            arm_name=plan.key,
            success=success,
            force_abort=force_abort,
        )

    def record_key(
        self,
        *,
        context: str,
        arm_name: str,
        success: bool,
        force_abort: bool,
    ) -> None:
        if not context:
            raise ValueError("context must be non-empty")
        if not arm_name:
            raise ValueError("strategy-memory arm name must be non-empty")
        for key in (context, _global_context(context)):
            stats = self.contexts.setdefault(key, {}).setdefault(
                arm_name,
                {"attempts": 0, "successes": 0, "force_aborts": 0},
            )
            stats["attempts"] = int(stats.get("attempts") or 0) + 1
            stats["successes"] = int(stats.get("successes") or 0) + int(success)
            stats["force_aborts"] = int(stats.get("force_aborts") or 0) + int(force_abort)

    def score(self, *, context: str, strategy: RetryStrategy) -> float:
        return self.score_key(context=context, arm_name=strategy.name)

    def score_plan(self, *, context: str, plan: RecoveryPlan) -> float:
        return self.score_key(context=context, arm_name=plan.key)

    def score_key(self, *, context: str, arm_name: str) -> float:
        task_score = self._score_one(context=context, arm_name=arm_name)
        global_key = _global_context(context)
        global_stats = self.contexts.get(global_key, {}).get(arm_name, {})
        if int(global_stats.get("attempts") or 0) == 0:
            return task_score
        return 0.75 * task_score + 0.25 * self._score_one(
            context=global_key, arm_name=arm_name
        )

    def _score_one(self, *, context: str, arm_name: str) -> float:
        context_stats = self.contexts.get(context, {})
        stats = context_stats.get(arm_name, {})
        attempts = int(stats.get("attempts") or 0)
        successes = int(stats.get("successes") or 0)
        force_aborts = int(stats.get("force_aborts") or 0)
        total_attempts = sum(
            int(item.get("attempts") or 0) for item in context_stats.values()
        )
        posterior_mean = (successes + 1.0) / (attempts + 2.0)
        exploration = math.sqrt(2.0 * math.log(total_attempts + 2.0) / (attempts + 1.0))
        force_penalty = 2.0 * force_aborts / (attempts + 1.0)
        return posterior_mean + 0.15 * exploration - force_penalty


def choose_retry_strategy(
    *,
    memory: EpisodicStrategyMemory,
    context: str,
    previous_failure: str | None,
    attempted_strategy_names: Iterable[str] = (),
    cooperative_cradle: bool = False,
    strategies: Iterable[RetryStrategy] = DEFAULT_STRATEGIES,
) -> RetryStrategy:
    """Choose the highest-scoring strategy allowed by failure-specific safety rules."""

    attempted = set(attempted_strategy_names)
    candidates = list(
        _allowed_strategies(
            previous_failure=previous_failure,
            cooperative_cradle=cooperative_cradle,
            strategies=strategies,
        )
    )
    untried = [item for item in candidates if item.name not in attempted]
    if untried:
        candidates = untried
    preference = {
        PASH_DUAL_ARM.name: 3,
        PASH_ARM.name: 2,
        PASH_BASE.name: 1,
        EXPERT_RECOVERY.name: 0,
    }
    return max(
        candidates,
        key=lambda item: (memory.score(context=context, strategy=item), preference[item.name]),
    )


def recovery_recipes(previous_failure: str | None) -> tuple[RecoveryRecipe, ...]:
    """Return only pre-registered, safety-bounded recipes for a failure class."""

    if previous_failure is None:
        return (NOMINAL_RECOVERY,)
    if previous_failure in {"contact_failure", "suction_latch_failure", "suction_latch"}:
        return (SEAL_SEARCH_PLUS_Y, SEAL_SEARCH_MINUS_Y)
    if previous_failure in {"lift_support_failure", "lift_success"}:
        return (GENTLE_LIFT, TRANSPORT_STABILIZE)
    if previous_failure in {"transport_failure", "transport_success"}:
        return (TRANSPORT_STABILIZE, GENTLE_LIFT)
    if previous_failure in {
        "placement_failure",
        "release_failure",
        "placement_success",
        "release_success",
    }:
        return (PRECISION_PLACE,)
    if previous_failure == "force_safety_abort":
        return (FORCE_RETREAT,)
    return (NOMINAL_RECOVERY,)


def choose_recovery_plan(
    *,
    memory: EpisodicStrategyMemory,
    context: str,
    previous_failure: str | None,
    attempted_plan_keys: Iterable[str] = (),
    cooperative_cradle: bool = False,
    strategies: Iterable[RetryStrategy] = DEFAULT_STRATEGIES,
) -> RecoveryPlan:
    """Select a memory-scored Harness plan without changing model weights online."""

    allowed = _allowed_strategies(
        previous_failure=previous_failure,
        cooperative_cradle=cooperative_cradle,
        strategies=strategies,
    )
    plans = tuple(
        RecoveryPlan(strategy, recipe)
        for strategy in allowed
        for recipe in recovery_recipes(previous_failure)
    )
    attempted = set(attempted_plan_keys)
    untried = tuple(plan for plan in plans if plan.key not in attempted)
    candidates = untried or plans
    strategy_preference = {
        PASH_DUAL_ARM.name: 3,
        PASH_ARM.name: 2,
        PASH_BASE.name: 1,
        EXPERT_RECOVERY.name: 0,
    }
    recipe_preference = {
        recipe.name: -index
        for index, recipe in enumerate(recovery_recipes(previous_failure))
    }
    return max(
        candidates,
        key=lambda plan: (
            memory.score_plan(context=context, plan=plan),
            strategy_preference[plan.strategy.name],
            recipe_preference[plan.recipe.name],
        ),
    )


def summarize_adaptive_attempts(attempts: list[dict[str, Any]]) -> dict[str, Any]:
    if not attempts:
        raise ValueError("adaptive retry summary requires at least one attempt")
    valid = [item for item in attempts if item.get("summary_available")]
    successes = [item for item in valid if item.get("success")]
    force_aborts = sum(item.get("failure_stage") == "force_safety_abort" for item in valid)
    first_success_index = next(
        (int(item["attempt_index"]) for item in valid if item.get("success")), None
    )
    return {
        "schema_version": 1,
        "protocol": "pash-adaptive-retry-v1",
        "attempts_requested": len(attempts),
        "attempts_with_summary": len(valid),
        "first_attempt_success": bool(valid and valid[0].get("success")),
        "eventual_success": bool(successes),
        "attempts_to_success": first_success_index + 1 if first_success_index is not None else None,
        "force_abort_count": force_aborts,
        "primitive_gaps": [
            str(item["failure_stage"])
            for item in valid
            if item.get("failure_stage") is not None
        ],
        "strategies_attempted": [str(item["strategy"]["name"]) for item in attempts],
        "recovery_plans_attempted": [
            str((item.get("recovery_plan") or {}).get("key") or "legacy")
            for item in attempts
        ],
        "attempts": attempts,
        "claim_boundary": (
            "eventual success includes bounded retries and must not be reported as first-attempt "
            "success; this loop adapts strategy authority while weight updates remain near-line"
        ),
    }


def build_primitive_acquisition_manifest(
    attempts: list[dict[str, Any]],
) -> dict[str, Any]:
    """Convert retry outcomes into an InSight-style primitive-gap writeback manifest."""

    if not attempts:
        raise ValueError("primitive acquisition requires at least one attempt")
    gaps = []
    acquisitions = []
    pending_gap: dict[str, Any] | None = None
    for attempt in attempts:
        if not attempt.get("summary_available"):
            continue
        failure_stage = attempt.get("failure_stage")
        if failure_stage:
            pending_gap = {
                "source_attempt_index": int(attempt["attempt_index"]),
                "primitive": str(failure_stage),
                "source_strategy": str(attempt["strategy"]["name"]),
                "source_summary": attempt.get("summary"),
            }
            gaps.append(dict(pending_gap))
            continue
        if attempt.get("success") and pending_gap is not None:
            dataset = attempt.get("dataset") or {}
            dataset_saved = bool(dataset.get("saved"))
            acquisitions.append(
                {
                    **pending_gap,
                    "recovery_attempt_index": int(attempt["attempt_index"]),
                    "recovery_strategy": str(attempt["strategy"]["name"]),
                    "successful_summary": attempt.get("summary"),
                    "successful_dataset_root": dataset.get("root"),
                    "successful_dataset_frames": int(dataset.get("frames") or 0),
                    "writeback_status": (
                        "eligible_after_dataset_audit"
                        if dataset_saved
                        else "blocked_missing_trajectory"
                    ),
                    "primitive_task_text": (
                        f"Recover the {pending_gap['primitive']} primitive while preserving "
                        "the 35 N force limit and complete the parcel task."
                    ),
                }
            )
            pending_gap = None
    return {
        "schema_version": 1,
        "protocol": "pash-primitive-acquisition-v1",
        "primitive_gaps": gaps,
        "successful_acquisitions": acquisitions,
        "retraining_candidate_count": sum(
            item["writeback_status"] == "eligible_after_dataset_audit"
            for item in acquisitions
        ),
        "claim_boundary": (
            "successful recovery summaries are candidates for audited primitive-level data "
            "extraction; they are not training data until sensor/action frames pass dataset audit"
        ),
    }


def _allowed_strategies(
    *,
    previous_failure: str | None,
    cooperative_cradle: bool,
    strategies: Iterable[RetryStrategy],
) -> tuple[RetryStrategy, ...]:
    candidates = list(strategies)
    if cooperative_cradle:
        candidates = [item for item in candidates if item.cooperative_safe]
    else:
        candidates = [item for item in candidates if item.name != PASH_DUAL_ARM.name]
    if previous_failure == "force_safety_abort":
        candidates = [item for item in candidates if item.name == EXPERT_RECOVERY.name]
    elif previous_failure in {
        "contact_failure",
        "suction_latch_failure",
        "lift_support_failure",
        "placement_failure",
        "release_failure",
        "suction_latch",
        "lift_success",
        "placement_success",
        "release_success",
    }:
        candidates = [item for item in candidates if not item.learned_arm_authority]
    if not candidates:
        raise ValueError("no retry strategy satisfies the safety constraints")
    return tuple(candidates)


def _global_context(context: str) -> str:
    parts = context.split(":", 2)
    if len(parts) != 3 or any(not part for part in parts):
        raise ValueError("strategy context must be profile:mass_band:primitive")
    return f"*:{parts[1]}:{parts[2]}"
