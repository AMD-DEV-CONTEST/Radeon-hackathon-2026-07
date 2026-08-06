from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from typing import Mapping, Sequence

from .v10_contracts import (
    AgencyRole,
    AgencyRoleKind,
    AgencyTopology,
    V10ContractError,
)


class ExecutionStrategy(str, Enum):
    DIRECT = "direct"
    RETRIEVE = "retrieve"
    SEARCH = "search"
    SIMULATE = "simulate"
    TEAM = "team"
    HUMAN = "human"


@dataclass(frozen=True)
class RoleTemplate:
    role_id: str
    capabilities: frozenset[str]
    permissions: frozenset[str]
    action_budget: int


DEFAULT_ROLE_CATALOG = (
    RoleTemplate(
        "evidence",
        frozenset({"research", "claims", "rights"}),
        frozenset({"read_sources", "propose_claims"}),
        3,
    ),
    RoleTemplate(
        "strategist",
        frozenset({"strategy", "twin", "experiment"}),
        frozenset({"read_state", "propose_plan"}),
        3,
    ),
    RoleTemplate(
        "creative",
        frozenset({"copy", "image", "video", "audio"}),
        frozenset({"read_state", "write_draft"}),
        4,
    ),
    RoleTemplate(
        "critic",
        frozenset({"taste", "brand", "quality", "safety"}),
        frozenset({"read_state", "write_findings"}),
        3,
    ),
)


class DynamicAgencyDesigner:
    """Builds a bounded L2 topology; it never creates a free-form swarm."""

    def __init__(self, catalog: Sequence[RoleTemplate] = DEFAULT_ROLE_CATALOG):
        self.catalog = tuple(catalog)

    def build(
        self,
        required_capabilities: Sequence[str],
        *,
        max_parallel_specialists: int = 3,
        action_budget: int = 16,
    ) -> AgencyTopology:
        required = set(required_capabilities)
        if not required:
            raise V10ContractError("agency design requires capabilities")
        remaining = set(required)
        selected: list[RoleTemplate] = []
        available = list(self.catalog)
        while remaining and available:
            ranked = sorted(
                available,
                key=lambda role: (
                    -len(role.capabilities & remaining),
                    role.action_budget,
                    role.role_id,
                ),
            )
            best = ranked[0]
            coverage = best.capabilities & remaining
            if not coverage:
                break
            selected.append(best)
            remaining -= coverage
            available.remove(best)
        if remaining:
            raise V10ContractError(
                f"no bounded specialist covers capabilities: {sorted(remaining)}"
            )
        supervisor_budget = max(3, len(selected) + 1)
        roles = [
            AgencyRole(
                "supervisor",
                AgencyRoleKind.SUPERVISOR,
                frozenset(
                    {
                        "route",
                        "checkpoint",
                        "approve_internal",
                        "request_human",
                    }
                ),
                owns_state=True,
                max_actions=supervisor_budget,
            )
        ]
        roles.extend(
            AgencyRole(
                template.role_id,
                AgencyRoleKind.SPECIALIST,
                template.permissions,
                max_actions=template.action_budget,
            )
            for template in selected
        )
        roles.append(
            AgencyRole(
                "human_release",
                AgencyRoleKind.HUMAN,
                frozenset({"approve_release", "reject_release"}),
                max_actions=1,
            )
        )
        declared_actions = sum(role.max_actions for role in roles)
        if declared_actions > action_budget:
            raise V10ContractError(
                f"selected topology needs {declared_actions} actions, "
                f"budget is {action_budget}"
            )
        return AgencyTopology(
            roles=tuple(roles),
            max_parallel_specialists=min(
                max_parallel_specialists,
                max(1, len(selected)),
            ),
            max_total_actions=action_budget,
            stop_conditions=(
                "action budget exhausted",
                "two repair rounds exhausted",
                "unsupported critical claim",
                "human release boundary",
            ),
        )


@dataclass(frozen=True)
class AdapterExpert:
    expert_id: str
    capabilities: frozenset[str]
    latency_cost: float
    memory_cost_gb: float
    is_generalist: bool = False


@dataclass(frozen=True)
class AdapterRoute:
    selected_experts: tuple[str, ...]
    weights: tuple[float, ...]
    confidence_margin: float
    fallback_used: bool
    reason: str
    schema: str = "ProofLaunchSparseAdapterRouteV10"


class SparseAdapterRouter:
    """Deterministic top-2 pseudo-MoE router with confidence fallback."""

    def __init__(
        self,
        experts: Sequence[AdapterExpert],
        *,
        confidence_floor: float = 0.12,
        max_active: int = 2,
    ) -> None:
        if not experts:
            raise V10ContractError("adapter router needs experts")
        if len({item.expert_id for item in experts}) != len(experts):
            raise V10ContractError("adapter expert ids must be unique")
        if max_active not in {1, 2}:
            raise V10ContractError("single-card router allows one or two active experts")
        generalists = [item for item in experts if item.is_generalist]
        if len(generalists) != 1:
            raise V10ContractError("exactly one fallback generalist is required")
        self.experts = tuple(experts)
        self.generalist = generalists[0]
        self.confidence_floor = confidence_floor
        self.max_active = max_active

    def route(
        self,
        required_capabilities: Sequence[str],
        learned_scores: Mapping[str, float],
    ) -> AdapterRoute:
        required = set(required_capabilities)
        scored: list[tuple[float, AdapterExpert]] = []
        for expert in self.experts:
            coverage = (
                len(expert.capabilities & required) / max(1, len(required))
            )
            learned = learned_scores.get(expert.expert_id, 0.0)
            if not math.isfinite(learned):
                raise V10ContractError("adapter route scores must be finite")
            cost_penalty = 0.01 * expert.latency_cost + 0.005 * expert.memory_cost_gb
            scored.append((coverage + learned - cost_penalty, expert))
        scored.sort(key=lambda item: (-item[0], item[1].expert_id))
        top = scored[0]
        second_score = scored[1][0] if len(scored) > 1 else float("-inf")
        margin = top[0] - second_score
        fallback = margin < self.confidence_floor or not (
            top[1].capabilities & required
        )
        selected = (
            [self.generalist]
            if fallback
            else [item[1] for item in scored[: self.max_active]]
        )
        raw = [
            max(
                1e-9,
                next(score for score, expert in scored if expert == selected_item),
            )
            for selected_item in selected
        ]
        denominator = sum(raw)
        return AdapterRoute(
            selected_experts=tuple(item.expert_id for item in selected),
            weights=tuple(value / denominator for value in raw),
            confidence_margin=margin,
            fallback_used=fallback,
            reason=(
                "confidence below floor; deterministic generalist fallback"
                if fallback
                else "top sparse experts cover requested capabilities"
            ),
        )


@dataclass(frozen=True)
class MemoryFact:
    fact_id: str
    key: str
    value: str
    source_locator: str
    observed_at: str
    valid_until: str
    approved: bool
    confidence: float
    superseded_by: str | None = None

    def __post_init__(self) -> None:
        if not self.fact_id.strip() or not self.key.strip():
            raise V10ContractError("memory fact id and key are required")
        if not self.source_locator.strip():
            raise V10ContractError("memory fact source locator is required")
        if not 0 <= self.confidence <= 1:
            raise V10ContractError("memory confidence must be in [0, 1]")
        observed = datetime.fromisoformat(self.observed_at.replace("Z", "+00:00"))
        expires = datetime.fromisoformat(self.valid_until.replace("Z", "+00:00"))
        if expires <= observed:
            raise V10ContractError("memory valid_until must follow observed_at")


@dataclass(frozen=True)
class MemoryConflict:
    key: str
    existing_fact_id: str
    incoming_fact_id: str
    requires_human: bool = True


class TaskFocusedMemory:
    def __init__(self) -> None:
        self._facts: dict[str, MemoryFact] = {}
        self._active_by_key: dict[str, str] = {}
        self._conflicts: list[MemoryConflict] = []
        self._quarantined_keys: set[str] = set()

    @property
    def conflicts(self) -> tuple[MemoryConflict, ...]:
        return tuple(self._conflicts)

    def add(self, fact: MemoryFact) -> MemoryConflict | None:
        if fact.fact_id in self._facts:
            raise V10ContractError("memory fact id already exists")
        current_id = self._active_by_key.get(fact.key)
        conflict: MemoryConflict | None = None
        if current_id:
            current = self._facts[current_id]
            if current.value != fact.value:
                conflict = MemoryConflict(fact.key, current.fact_id, fact.fact_id)
                self._conflicts.append(conflict)
                if not fact.approved:
                    self._facts[fact.fact_id] = fact
                    self._quarantined_keys.add(fact.key)
                    return conflict
            self._facts[current_id] = replace(
                current,
                superseded_by=fact.fact_id,
            )
        self._facts[fact.fact_id] = fact
        self._active_by_key[fact.key] = fact.fact_id
        self._quarantined_keys.discard(fact.key)
        return conflict

    def retrieve(
        self,
        keys: Sequence[str],
        *,
        now: str | None = None,
        minimum_confidence: float = 0.0,
    ) -> tuple[MemoryFact, ...]:
        moment = datetime.fromisoformat(
            (now or datetime.now(timezone.utc).isoformat()).replace("Z", "+00:00")
        )
        found: list[MemoryFact] = []
        for key in keys:
            if key in self._quarantined_keys:
                continue
            fact_id = self._active_by_key.get(key)
            if not fact_id:
                continue
            fact = self._facts[fact_id]
            expires = datetime.fromisoformat(
                fact.valid_until.replace("Z", "+00:00")
            )
            if (
                fact.approved
                and fact.superseded_by is None
                and fact.confidence >= minimum_confidence
                and moment <= expires
            ):
                found.append(fact)
        return tuple(found)


@dataclass(frozen=True)
class TestTimeDecision:
    strategy: ExecutionStrategy
    max_steps: int
    max_tool_calls: int
    requires_human: bool
    reason: str
    schema: str = "ProofLaunchTestTimeDecisionV10"


class OutcomeAwareTestTimeController:
    """Allocates bounded compute from task difficulty, risk, and evidence gaps."""

    def decide(
        self,
        *,
        difficulty: float,
        action_risk: float,
        evidence_freshness: float,
        model_disagreement: float,
        expected_value: float,
        tool_budget: int,
    ) -> TestTimeDecision:
        for name, value in (
            ("difficulty", difficulty),
            ("action_risk", action_risk),
            ("evidence_freshness", evidence_freshness),
            ("model_disagreement", model_disagreement),
        ):
            if not 0 <= value <= 1:
                raise V10ContractError(f"{name} must be in [0, 1]")
        if tool_budget < 0:
            raise V10ContractError("tool budget cannot be negative")
        if action_risk >= 0.8:
            return TestTimeDecision(
                ExecutionStrategy.HUMAN,
                1,
                0,
                True,
                "high-impact action requires human approval",
            )
        if evidence_freshness < 0.5 and tool_budget:
            return TestTimeDecision(
                ExecutionStrategy.SEARCH,
                3,
                min(tool_budget, 3),
                False,
                "evidence is stale; refresh before planning",
            )
        if model_disagreement >= 0.4 and tool_budget >= 2:
            return TestTimeDecision(
                ExecutionStrategy.SIMULATE,
                4,
                min(tool_budget, 4),
                False,
                "model disagreement warrants bounded counterfactual simulation",
            )
        if difficulty >= 0.7 and expected_value > 0 and tool_budget >= 2:
            return TestTimeDecision(
                ExecutionStrategy.TEAM,
                5,
                min(tool_budget, 4),
                False,
                "high-value hard task merits bounded specialist topology",
            )
        if difficulty >= 0.35:
            return TestTimeDecision(
                ExecutionStrategy.RETRIEVE,
                2,
                min(tool_budget, 1),
                False,
                "moderate task can reuse fresh approved memory",
            )
        return TestTimeDecision(
            ExecutionStrategy.DIRECT,
            1,
            0,
            False,
            "low-risk easy task uses deterministic direct path",
        )
