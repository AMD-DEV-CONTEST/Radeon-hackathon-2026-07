from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol


ResourcePool = Literal[
    "cpu",
    "local_gpu",
    "cloud_image",
    "cloud_video",
    "llm",
]
BudgetScope = Literal["global", "project", "workflow"]
BudgetVerdict = Literal["allow", "warn", "block"]

_RESOURCE_POOLS = frozenset(
    {"cpu", "local_gpu", "cloud_image", "cloud_video", "llm"}
)
_SCOPES = frozenset({"global", "project", "workflow"})
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_ROOT_KEYS = frozenset({"budgets"})
_BUDGET_KEYS = frozenset(
    {
        "budget_id",
        "scope",
        "scope_id",
        "resource_pool",
        "hard_limit_micros",
        "warning_bps",
        "max_attempt_micros",
        "require_known_estimate",
    }
)


class BudgetConfigurationError(ValueError):
    """Raised when a cost policy is unsafe or ambiguous."""


def _integer(value: object, *, name: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise BudgetConfigurationError(f"{name} must be an integer")
    if value < minimum:
        raise BudgetConfigurationError(f"{name} is below its minimum")
    return value


def _identifier(value: object, *, name: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise BudgetConfigurationError(f"{name} is invalid")
    return value


@dataclass(frozen=True, slots=True)
class BudgetUsage:
    """A point-in-time projection derived from the durable attempt ledger."""

    spent_micros: int = 0
    reserved_micros: int = 0

    def __post_init__(self) -> None:
        _integer(self.spent_micros, name="spent_micros")
        _integer(self.reserved_micros, name="reserved_micros")

    @property
    def committed_and_reserved_micros(self) -> int:
        return self.spent_micros + self.reserved_micros


@dataclass(frozen=True, slots=True)
class CostProposal:
    resource_pool: ResourcePool
    estimated_micros: int | None
    project_id: str | None = None
    workflow_id: str | None = None

    def __post_init__(self) -> None:
        if self.resource_pool not in _RESOURCE_POOLS:
            raise BudgetConfigurationError("resource_pool is invalid")
        if self.estimated_micros is not None:
            _integer(self.estimated_micros, name="estimated_micros")
        if self.project_id is not None:
            _identifier(self.project_id, name="project_id")
        if self.workflow_id is not None:
            _identifier(self.workflow_id, name="workflow_id")


@dataclass(frozen=True, slots=True)
class CostBudget:
    budget_id: str
    scope: BudgetScope
    scope_id: str | None
    resource_pool: ResourcePool
    hard_limit_micros: int
    warning_bps: int = 8_000
    max_attempt_micros: int | None = None
    require_known_estimate: bool = True

    def __post_init__(self) -> None:
        _identifier(self.budget_id, name="budget_id")
        if self.scope not in _SCOPES:
            raise BudgetConfigurationError("scope is invalid")
        if self.resource_pool not in _RESOURCE_POOLS:
            raise BudgetConfigurationError("resource_pool is invalid")
        if self.scope == "global":
            if self.scope_id is not None:
                raise BudgetConfigurationError(
                    "global budgets cannot declare scope_id"
                )
        elif self.scope_id is None:
            raise BudgetConfigurationError(
                f"{self.scope} budgets require scope_id"
            )
        else:
            _identifier(self.scope_id, name="scope_id")
        _integer(
            self.hard_limit_micros,
            name="hard_limit_micros",
            minimum=1,
        )
        warning_bps = _integer(
            self.warning_bps,
            name="warning_bps",
            minimum=1,
        )
        if warning_bps > 10_000:
            raise BudgetConfigurationError("warning_bps exceeds 10000")
        if self.max_attempt_micros is not None:
            _integer(
                self.max_attempt_micros,
                name="max_attempt_micros",
                minimum=1,
            )
        if not isinstance(self.require_known_estimate, bool):
            raise BudgetConfigurationError(
                "require_known_estimate must be boolean"
            )

    @property
    def warning_threshold_micros(self) -> int:
        return (
            self.hard_limit_micros * self.warning_bps + 9_999
        ) // 10_000

    def applies_to(self, proposal: CostProposal) -> bool:
        if self.resource_pool != proposal.resource_pool:
            return False
        if self.scope == "global":
            return True
        if self.scope == "project":
            return self.scope_id == proposal.project_id
        return self.scope_id == proposal.workflow_id


@dataclass(frozen=True, slots=True)
class BudgetDecision:
    verdict: BudgetVerdict
    reason_code: str
    scope: str
    limiting_budget_id: str | None
    projected_micros: int | None
    hard_limit_micros: int | None

    @property
    def allowed(self) -> bool:
        return self.verdict != "block"


class CostBudgetPolicy:
    """Pure admission policy over durable, caller-supplied cost projections.

    Money is represented only as integer micro-units. The policy does not keep
    an in-memory balance: callers must read and reserve against their durable
    OperationAttempt ledger in the same transaction as admission.
    """

    def __init__(self, budgets: tuple[CostBudget, ...]) -> None:
        identifiers = [item.budget_id for item in budgets]
        if len(identifiers) != len(set(identifiers)):
            raise BudgetConfigurationError("budget_id values must be unique")
        dimensions = [
            (item.scope, item.scope_id, item.resource_pool)
            for item in budgets
        ]
        if len(dimensions) != len(set(dimensions)):
            raise BudgetConfigurationError(
                "budget scope and resource_pool values must be unique"
            )
        self._budgets = budgets

    @property
    def budgets(self) -> tuple[CostBudget, ...]:
        return self._budgets

    @classmethod
    def from_json_file(cls, path: str | Path) -> "CostBudgetPolicy":
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise BudgetConfigurationError(
                "cost budget policy cannot be loaded"
            ) from exc
        return cls.from_dict(payload)

    @classmethod
    def from_dict(cls, payload: object) -> "CostBudgetPolicy":
        if not isinstance(payload, dict):
            raise BudgetConfigurationError("policy root must be an object")
        if set(payload) - _ROOT_KEYS:
            raise BudgetConfigurationError("policy contains unknown keys")
        raw_budgets = payload.get("budgets")
        if not isinstance(raw_budgets, list):
            raise BudgetConfigurationError("budgets must be a list")
        budgets: list[CostBudget] = []
        for raw in raw_budgets:
            if not isinstance(raw, dict):
                raise BudgetConfigurationError(
                    "each budget must be an object"
                )
            if set(raw) - _BUDGET_KEYS:
                raise BudgetConfigurationError(
                    "budget contains unknown keys"
                )
            try:
                budget = CostBudget(
                    budget_id=_identifier(
                        raw["budget_id"],
                        name="budget_id",
                    ),
                    scope=raw["scope"],
                    scope_id=raw.get("scope_id"),
                    resource_pool=raw["resource_pool"],
                    hard_limit_micros=_integer(
                        raw["hard_limit_micros"],
                        name="hard_limit_micros",
                        minimum=1,
                    ),
                    warning_bps=_integer(
                        raw.get("warning_bps", 8_000),
                        name="warning_bps",
                        minimum=1,
                    ),
                    max_attempt_micros=(
                        None
                        if raw.get("max_attempt_micros") is None
                        else _integer(
                            raw["max_attempt_micros"],
                            name="max_attempt_micros",
                            minimum=1,
                        )
                    ),
                    require_known_estimate=raw.get(
                        "require_known_estimate",
                        True,
                    ),
                )
            except KeyError as exc:
                raise BudgetConfigurationError(
                    "budget is missing a required field"
                ) from exc
            budgets.append(budget)
        return cls(tuple(budgets))

    def assess(
        self,
        proposal: CostProposal,
        *,
        usage_by_budget: dict[str, BudgetUsage],
    ) -> BudgetDecision:
        applicable = tuple(
            item for item in self._budgets if item.applies_to(proposal)
        )
        if not applicable:
            return BudgetDecision(
                verdict="allow",
                reason_code="no_budget_configured",
                scope="unconfigured",
                limiting_budget_id=None,
                projected_micros=proposal.estimated_micros,
                hard_limit_micros=None,
            )

        if proposal.estimated_micros is None:
            required = next(
                (
                    item
                    for item in applicable
                    if item.require_known_estimate
                ),
                None,
            )
            if required is not None:
                return BudgetDecision(
                    verdict="block",
                    reason_code="cost_estimate_required",
                    scope=required.scope,
                    limiting_budget_id=required.budget_id,
                    projected_micros=None,
                    hard_limit_micros=required.hard_limit_micros,
                )
            estimate = 0
        else:
            estimate = proposal.estimated_micros

        warnings: list[tuple[CostBudget, int]] = []
        for budget in applicable:
            if budget.budget_id not in usage_by_budget:
                return BudgetDecision(
                    verdict="block",
                    reason_code="cost_usage_snapshot_required",
                    scope=budget.scope,
                    limiting_budget_id=budget.budget_id,
                    projected_micros=None,
                    hard_limit_micros=budget.hard_limit_micros,
                )
            if (
                budget.max_attempt_micros is not None
                and estimate > budget.max_attempt_micros
            ):
                return BudgetDecision(
                    verdict="block",
                    reason_code="attempt_cost_limit_exceeded",
                    scope=budget.scope,
                    limiting_budget_id=budget.budget_id,
                    projected_micros=estimate,
                    hard_limit_micros=budget.max_attempt_micros,
                )
            usage = usage_by_budget[budget.budget_id]
            projected = usage.committed_and_reserved_micros + estimate
            if projected > budget.hard_limit_micros:
                return BudgetDecision(
                    verdict="block",
                    reason_code="cost_budget_exceeded",
                    scope=budget.scope,
                    limiting_budget_id=budget.budget_id,
                    projected_micros=projected,
                    hard_limit_micros=budget.hard_limit_micros,
                )
            if projected >= budget.warning_threshold_micros:
                warnings.append((budget, projected))

        if warnings:
            limiting, projected = max(
                warnings,
                key=lambda item: (
                    item[1] * 10_000 // item[0].hard_limit_micros,
                    item[0].budget_id,
                ),
            )
            return BudgetDecision(
                verdict="warn",
                reason_code="cost_budget_warning",
                scope=limiting.scope,
                limiting_budget_id=limiting.budget_id,
                projected_micros=projected,
                hard_limit_micros=limiting.hard_limit_micros,
            )

        return BudgetDecision(
            verdict="allow",
            reason_code="within_cost_budget",
            scope=max(
                (item.scope for item in applicable),
                key={"global": 0, "project": 1, "workflow": 2}.get,
            ),
            limiting_budget_id=None,
            projected_micros=estimate,
            hard_limit_micros=None,
        )


class CostBudgetObserver(Protocol):
    def record_cost_budget_check(
        self,
        *,
        scope: str,
        resource_pool: str,
        verdict: str,
    ) -> None: ...


class CostBudgetGuard:
    """Admission facade that publishes only bounded budget dimensions."""

    def __init__(
        self,
        policy: CostBudgetPolicy,
        *,
        observer: CostBudgetObserver | None = None,
    ) -> None:
        self.policy = policy
        self.observer = observer

    def assess(
        self,
        proposal: CostProposal,
        *,
        usage_by_budget: dict[str, BudgetUsage],
    ) -> BudgetDecision:
        decision = self.policy.assess(
            proposal,
            usage_by_budget=usage_by_budget,
        )
        if self.observer is not None:
            try:
                self.observer.record_cost_budget_check(
                    scope=decision.scope,
                    resource_pool=proposal.resource_pool,
                    verdict=decision.verdict,
                )
            except Exception:
                # Admission semantics cannot depend on telemetry availability.
                pass
        return decision
