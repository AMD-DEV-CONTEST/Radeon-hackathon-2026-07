from __future__ import annotations

import math
from dataclasses import asdict, dataclass, replace
from enum import Enum
from typing import Mapping, Sequence

from .v10_contracts import EvidenceClass, V10ContractError
from .v10_supply_chain import stable_sha256


_HEX = frozenset("0123456789abcdef")


def _require_sha256(value: str, field_name: str) -> None:
    if len(value) != 64 or any(character not in _HEX for character in value):
        raise V10ContractError(f"{field_name} must be a lowercase SHA-256")


def _require_unit(value: float, field_name: str) -> None:
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise V10ContractError(f"{field_name} must be finite and in [0, 1]")


class Capability(str, Enum):
    EVIDENCE = "evidence"
    AUDIENCE = "audience"
    COMPETITION = "competition"
    STRATEGY = "strategy"
    CREATIVE = "creative"
    COPY = "copy"
    ART = "art"
    CHANNEL = "channel"
    PRODUCTION = "production"
    COMPLIANCE = "compliance"
    EXPERIMENT = "experiment"
    CRITIC = "critic"


@dataclass(frozen=True)
class CapabilityContract:
    capability: Capability
    input_fields: tuple[str, ...]
    output_fields: tuple[str, ...]
    permitted_tools: tuple[str, ...]
    permissions: tuple[str, ...]
    maximum_actions: int

    def __post_init__(self) -> None:
        if not self.input_fields or not self.output_fields or self.maximum_actions < 1:
            raise V10ContractError("capability contract needs typed IO and action budget")
        if any(permission in {"publish", "send", "approve_release"} for permission in self.permissions):
            raise V10ContractError("capability workers cannot publish send or approve release")


def default_capability_contracts() -> tuple[CapabilityContract, ...]:
    details = {
        Capability.EVIDENCE: (("claims", "sources"), ("claim_evidence", "gaps"), ("search", "retrieve")),
        Capability.AUDIENCE: (("consented_data", "objective"), ("segments", "exclusions"), ("analyze",)),
        Capability.COMPETITION: (("market_sources",), ("competitor_map", "white_space"), ("search", "analyze")),
        Capability.STRATEGY: (("evidence", "audience", "market"), ("smp", "plan"), ("simulate",)),
        Capability.CREATIVE: (("smp", "brand_rules"), ("big_idea", "concepts"), ("draft",)),
        Capability.COPY: (("concept", "claims"), ("copy_variants", "claim_links"), ("draft",)),
        Capability.ART: (("concept", "brand_rules"), ("art_direction", "asset_spec"), ("render",)),
        Capability.CHANNEL: (("assets", "channel_constraints"), ("channel_plan", "adaptations"), ("analyze",)),
        Capability.PRODUCTION: (("asset_spec", "approved_inputs"), ("artifacts", "provenance"), ("render", "encode")),
        Capability.COMPLIANCE: (("claims", "assets", "policy"), ("findings", "blocks"), ("audit",)),
        Capability.EXPERIMENT: (("hypothesis", "population"), ("assignment", "analysis_plan"), ("analyze",)),
        Capability.CRITIC: (("candidate", "rubric"), ("findings", "repair_priority"), ("audit",)),
    }
    return tuple(
        CapabilityContract(
            capability,
            values[0],
            values[1],
            values[2],
            ("read_scoped_state", "write_typed_output"),
            3,
        )
        for capability, values in details.items()
    )


class SearchMode(str, Enum):
    WIDTH = "width_search"
    DEPTH = "depth_search"
    FEEDBACK = "feedback_search"


class WorkPhase(str, Enum):
    RESEARCH = "research"
    PRODUCTION = "production"
    REPAIR = "repair"


def search_mode_for_phase(phase: WorkPhase) -> SearchMode:
    return {
        WorkPhase.RESEARCH: SearchMode.WIDTH,
        WorkPhase.PRODUCTION: SearchMode.DEPTH,
        WorkPhase.REPAIR: SearchMode.FEEDBACK,
    }[phase]


@dataclass(frozen=True)
class TopologyRequest:
    task_id: str
    required_capabilities: tuple[Capability, ...]
    phase: WorkPhase
    task_entropy: float
    action_risk: float
    conflict_count: int
    expected_worker_value: Mapping[Capability, float]
    confidence: float
    maximum_parallel: int = 3
    maximum_rounds: int = 8
    maximum_tokens: int = 16_000
    maximum_tool_calls: int = 20

    def __post_init__(self) -> None:
        if not self.task_id.strip() or not self.required_capabilities:
            raise V10ContractError("topology request needs task and capabilities")
        if len(set(self.required_capabilities)) != len(self.required_capabilities):
            raise V10ContractError("required capabilities cannot be duplicated")
        for field_name in ("task_entropy", "action_risk", "confidence"):
            _require_unit(getattr(self, field_name), field_name)
        if self.conflict_count < 0:
            raise V10ContractError("conflict count cannot be negative")
        if not 1 <= self.maximum_parallel <= 3:
            raise V10ContractError("dynamic topology permits at most three parallel workers")
        if not 1 <= self.maximum_rounds <= 8:
            raise V10ContractError("dynamic topology permits at most eight interaction rounds")
        if not 1 <= self.maximum_tokens <= 16_000 or not 0 <= self.maximum_tool_calls <= 20:
            raise V10ContractError("topology token or tool-call budget is invalid")
        for value in self.expected_worker_value.values():
            _require_unit(value, "expected worker value")


@dataclass(frozen=True)
class TopologyNode:
    node_id: str
    capability: Capability | None
    permissions: tuple[str, ...]
    context_fields: tuple[str, ...]
    maximum_actions: int
    owns_state: bool = False
    arbiter: bool = False
    human: bool = False


@dataclass(frozen=True)
class DynamicTopologyV1:
    topology_id: str
    revision: int
    nodes: tuple[TopologyNode, ...]
    dependency_edges: tuple[tuple[str, str], ...]
    conflict_edges: tuple[tuple[str, str], ...]
    failure_edges: tuple[tuple[str, str], ...]
    search_mode: SearchMode
    maximum_parallel: int
    maximum_rounds: int
    maximum_tokens: int
    maximum_tool_calls: int
    escalation_required: bool

    def __post_init__(self) -> None:
        if not self.topology_id.strip() or self.revision < 1:
            raise V10ContractError("topology identity and revision are required")
        ids = {node.node_id for node in self.nodes}
        if len(ids) != len(self.nodes):
            raise V10ContractError("topology node ids must be unique")
        supervisors = [node for node in self.nodes if node.owns_state]
        if len(supervisors) != 1 or supervisors[0].node_id != "supervisor":
            raise V10ContractError("exactly one supervisor must own state")
        if any(node.node_id.startswith("persona-") for node in self.nodes):
            raise V10ContractError("fixed persona chat nodes are prohibited")
        if not 1 <= self.maximum_parallel <= 3 or not 1 <= self.maximum_rounds <= 8:
            raise V10ContractError("topology parallelism or round limit is invalid")
        if not 1 <= self.maximum_tokens <= 16_000 or not 0 <= self.maximum_tool_calls <= 20:
            raise V10ContractError("topology token or tool limit is invalid")
        for edges in (self.dependency_edges, self.conflict_edges, self.failure_edges):
            if any(left not in ids or right not in ids or left == right for left, right in edges):
                raise V10ContractError("topology graph edge references invalid nodes")
        self._assert_dependency_dag()

    def _assert_dependency_dag(self) -> None:
        outgoing: dict[str, list[str]] = {node.node_id: [] for node in self.nodes}
        indegree = {node.node_id: 0 for node in self.nodes}
        for source, target in self.dependency_edges:
            outgoing[source].append(target)
            indegree[target] += 1
        queue = sorted(node for node, degree in indegree.items() if degree == 0)
        visited = 0
        while queue:
            node = queue.pop(0)
            visited += 1
            for target in outgoing[node]:
                indegree[target] -= 1
                if indegree[target] == 0:
                    queue.append(target)
                    queue.sort()
        if visited != len(self.nodes):
            raise V10ContractError("topology dependency graph must be acyclic")

    @property
    def digest(self) -> str:
        return stable_sha256(asdict(self))


class SupervisorMetaPolicy:
    def __init__(self, contracts: Sequence[CapabilityContract] | None = None) -> None:
        rows = tuple(contracts or default_capability_contracts())
        if {row.capability for row in rows} != set(Capability):
            raise V10ContractError("supervisor requires all capability contracts")
        self.contracts = {row.capability: row for row in rows}

    def build(self, request: TopologyRequest) -> DynamicTopologyV1:
        active = set(request.required_capabilities)
        if request.task_entropy >= 0.60:
            active.update({Capability.AUDIENCE, Capability.COMPETITION})
        if request.action_risk >= 0.50:
            active.update({Capability.COMPLIANCE, Capability.CRITIC})
        mandatory = set(request.required_capabilities) | ({Capability.COMPLIANCE, Capability.CRITIC} if request.action_risk >= 0.50 else set())
        active = {
            capability
            for capability in active
            if capability in mandatory or request.expected_worker_value.get(capability, 1.0) >= 0.10
        }
        nodes = [
            TopologyNode(
                "supervisor",
                None,
                ("route", "checkpoint", "request_human"),
                ("shared_facts", "typed_outputs", "budget"),
                4,
                owns_state=True,
            )
        ]
        for capability in sorted(active, key=lambda item: item.value):
            contract = self.contracts[capability]
            nodes.append(
                TopologyNode(
                    f"capability-{capability.value}",
                    capability,
                    contract.permissions,
                    contract.input_fields,
                    contract.maximum_actions,
                )
            )
        if request.conflict_count:
            nodes.append(
                TopologyNode(
                    "arbiter",
                    Capability.CRITIC,
                    ("read_conflicts", "recommend_resolution"),
                    ("shared_facts", "conflict_graph"),
                    2,
                    arbiter=True,
                )
            )
        nodes.append(
            TopologyNode(
                "human-release",
                None,
                ("approve_release", "reject_release"),
                ("final_evidence", "risk_summary"),
                1,
                human=True,
            )
        )
        worker_ids = [node.node_id for node in nodes if node.capability is not None and not node.arbiter]
        dependencies = tuple(("supervisor", worker) for worker in worker_ids) + tuple((worker, "supervisor") for worker in worker_ids)
        # State-owner feedback edges are represented in the failure graph, not
        # the dependency DAG, to retain acyclicity.
        dependencies = tuple(("supervisor", worker) for worker in worker_ids)
        conflicts = tuple((worker_ids[index], worker_ids[index + 1]) for index in range(len(worker_ids) - 1) if request.conflict_count > index)
        failures = tuple((worker, "supervisor") for worker in worker_ids)
        return DynamicTopologyV1(
            topology_id=f"topology-{request.task_id}",
            revision=1,
            nodes=tuple(nodes),
            dependency_edges=dependencies,
            conflict_edges=conflicts,
            failure_edges=failures,
            search_mode=search_mode_for_phase(request.phase),
            maximum_parallel=min(request.maximum_parallel, max(1, len(worker_ids))),
            maximum_rounds=request.maximum_rounds,
            maximum_tokens=request.maximum_tokens,
            maximum_tool_calls=request.maximum_tool_calls,
            escalation_required=request.confidence < 0.40 or request.action_risk >= 0.80,
        )


@dataclass(frozen=True)
class BlackboardFact:
    fact_id: str
    key: str
    value: str
    source_sha256: str
    evidence_class: EvidenceClass
    approved: bool
    visible_to: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.fact_id.strip() or not self.key.strip() or not self.value.strip():
            raise V10ContractError("blackboard fact id key and value are required")
        _require_sha256(self.source_sha256, "source_sha256")
        if self.key in {"chain_of_thought", "hidden_reasoning", "private_scratchpad"}:
            raise V10ContractError("implicit reasoning cannot enter shared blackboard")


class SharedFactBlackboard:
    def __init__(self) -> None:
        self._facts: dict[str, BlackboardFact] = {}

    def add(self, fact: BlackboardFact) -> None:
        if fact.fact_id in self._facts:
            raise V10ContractError("blackboard fact id already exists")
        self._facts[fact.fact_id] = fact

    def read(self, node_id: str) -> tuple[BlackboardFact, ...]:
        return tuple(
            fact
            for fact in self._facts.values()
            if fact.approved and node_id in fact.visible_to
        )


@dataclass(frozen=True)
class CapabilityOutput:
    node_id: str
    capability: Capability
    payload: Mapping[str, object]
    evidence_sha256s: tuple[str, ...]
    uncertainty: float
    hidden_reasoning_persisted: bool = False

    def __post_init__(self) -> None:
        if not self.node_id.strip() or not self.payload:
            raise V10ContractError("capability output needs node and typed payload")
        for digest in self.evidence_sha256s:
            _require_sha256(digest, "evidence_sha256")
        _require_unit(self.uncertainty, "capability output uncertainty")
        if self.hidden_reasoning_persisted:
            raise V10ContractError("capability output cannot persist hidden reasoning")


@dataclass(frozen=True)
class ToolContract:
    tool_id: str
    capability: Capability
    input_schema_sha256: str
    output_schema_sha256: str
    destructive: bool
    networked: bool
    human_approval_required: bool

    def __post_init__(self) -> None:
        if not self.tool_id.strip():
            raise V10ContractError("tool contract needs identity")
        _require_sha256(self.input_schema_sha256, "input_schema_sha256")
        _require_sha256(self.output_schema_sha256, "output_schema_sha256")
        if self.destructive and not self.human_approval_required:
            raise V10ContractError("destructive tool requires human approval")


@dataclass(frozen=True)
class TopologyMutation:
    mutation_id: str
    parent_sha256: str
    operation: str
    node_id: str
    reason: str

    def __post_init__(self) -> None:
        _require_sha256(self.parent_sha256, "parent_sha256")
        if self.operation not in {"add", "remove"} or not self.node_id.strip() or not self.reason.strip():
            raise V10ContractError("topology mutation is invalid")


class TopologyHistory:
    def __init__(self, initial: DynamicTopologyV1) -> None:
        self._versions = [initial]
        self._events: list[TopologyMutation] = []

    @property
    def current(self) -> DynamicTopologyV1:
        return self._versions[-1]

    @property
    def events(self) -> tuple[TopologyMutation, ...]:
        return tuple(self._events)

    def remove_worker(self, node_id: str, *, reason: str) -> DynamicTopologyV1:
        current = self.current
        node = next((item for item in current.nodes if item.node_id == node_id), None)
        if node is None or node.owns_state or node.human:
            raise V10ContractError("only a specialist worker can be removed")
        remaining = tuple(item for item in current.nodes if item.node_id != node_id)
        def keep(edge: tuple[str, str]) -> bool:
            return node_id not in edge
        updated = replace(
            current,
            revision=current.revision + 1,
            nodes=remaining,
            dependency_edges=tuple(filter(keep, current.dependency_edges)),
            conflict_edges=tuple(filter(keep, current.conflict_edges)),
            failure_edges=tuple(filter(keep, current.failure_edges)),
        )
        self._events.append(TopologyMutation(f"mutation-{len(self._events) + 1}", current.digest, "remove", node_id, reason))
        self._versions.append(updated)
        return updated

    def rollback(self, revision: int) -> DynamicTopologyV1:
        target = next((item for item in self._versions if item.revision == revision), None)
        if target is None:
            raise V10ContractError("topology rollback revision is unknown")
        restored = replace(target, revision=self.current.revision + 1)
        self._events.append(TopologyMutation(f"mutation-{len(self._events) + 1}", self.current.digest, "add", "rollback-snapshot", f"rollback to revision {revision}"))
        self._versions.append(restored)
        return restored


@dataclass(frozen=True)
class Opinion:
    opinion_id: str
    normalized_claims: frozenset[str]
    utility: float

    def __post_init__(self) -> None:
        _require_unit(self.utility, "opinion utility")


def prune_duplicate_opinions(opinions: Sequence[Opinion]) -> tuple[Opinion, ...]:
    retained: dict[frozenset[str], Opinion] = {}
    for opinion in opinions:
        current = retained.get(opinion.normalized_claims)
        if current is None or (-opinion.utility, opinion.opinion_id) < (-current.utility, current.opinion_id):
            retained[opinion.normalized_claims] = opinion
    return tuple(sorted(retained.values(), key=lambda item: item.opinion_id))


@dataclass(frozen=True)
class ScopedObservation:
    observation_id: str
    relevance: float
    freshness: float
    approved: bool
    token_count: int

    def __post_init__(self) -> None:
        _require_unit(self.relevance, "observation relevance")
        _require_unit(self.freshness, "observation freshness")
        if self.token_count < 1:
            raise V10ContractError("observation token count must be positive")


def prune_observations(
    observations: Sequence[ScopedObservation],
    *,
    token_budget: int,
) -> tuple[ScopedObservation, ...]:
    if token_budget < 1:
        raise V10ContractError("observation token budget must be positive")
    ranked = sorted(
        (item for item in observations if item.approved),
        key=lambda item: (-(item.relevance * item.freshness), item.observation_id),
    )
    selected = []
    used = 0
    for item in ranked:
        if used + item.token_count <= token_budget:
            selected.append(item)
            used += item.token_count
    return tuple(selected)


def structural_entropy(action_allocations: Mapping[str, int]) -> float:
    if not action_allocations or any(value < 0 for value in action_allocations.values()):
        raise V10ContractError("structural entropy needs non-negative allocations")
    total = sum(action_allocations.values())
    active = sum(value > 0 for value in action_allocations.values())
    if total == 0 or active <= 1:
        return 0.0
    probabilities = [value / total for value in action_allocations.values() if value > 0]
    return -sum(value * math.log(value) for value in probabilities) / math.log(active)


class TopologyArm(str, Enum):
    DYNAMIC = "dynamic_topology"
    FIXED_SIX = "fixed_six_agent"
    SINGLE = "single_agent"


@dataclass(frozen=True)
class TopologyOutcome:
    arm: TopologyArm
    task_id: str
    success: bool
    tokens: int
    tool_calls: int
    latency_ms: float
    communication_events: int
    evidence_class: EvidenceClass

    def __post_init__(self) -> None:
        if not self.task_id.strip() or self.tokens < 1 or self.tool_calls < 0 or self.latency_ms < 0 or self.communication_events < 0:
            raise V10ContractError("topology outcome fields are invalid")


def evaluate_matched_topology_arms(outcomes: Sequence[TopologyOutcome]) -> Mapping[str, object]:
    if not outcomes:
        raise V10ContractError("topology evaluation needs outcomes")
    tasks_by_arm = {
        arm: {item.task_id for item in outcomes if item.arm is arm}
        for arm in TopologyArm
    }
    if len({frozenset(tasks) for tasks in tasks_by_arm.values()}) != 1 or not next(iter(tasks_by_arm.values())):
        raise V10ContractError("topology arms must use the same non-empty task set")
    report: dict[str, object] = {
        "evidence_class": EvidenceClass.SIMULATED.value if all(item.evidence_class is EvidenceClass.SIMULATED for item in outcomes) else EvidenceClass.OBSERVED.value,
        "arms": {},
    }
    for arm in TopologyArm:
        rows = [item for item in outcomes if item.arm is arm]
        report["arms"][arm.value] = {
            "success_rate": sum(item.success for item in rows) / len(rows),
            "mean_tokens": sum(item.tokens for item in rows) / len(rows),
            "mean_tool_calls": sum(item.tool_calls for item in rows) / len(rows),
            "mean_latency_ms": sum(item.latency_ms for item in rows) / len(rows),
            "mean_communication_events": sum(item.communication_events for item in rows) / len(rows),
        }
    return report


@dataclass(frozen=True)
class TopologyTraceEvent:
    sequence: int
    topology_sha256: str
    event_kind: str
    payload_sha256: str
    prior_event_sha256: str

    def __post_init__(self) -> None:
        for name in ("topology_sha256", "payload_sha256", "prior_event_sha256"):
            _require_sha256(getattr(self, name), name)
        if self.sequence < 0 or not self.event_kind.strip():
            raise V10ContractError("topology trace event is invalid")

    @property
    def digest(self) -> str:
        return stable_sha256(asdict(self))


def append_topology_trace(
    events: Sequence[TopologyTraceEvent],
    topology: DynamicTopologyV1,
    event_kind: str,
    payload: Mapping[str, object],
) -> tuple[TopologyTraceEvent, ...]:
    event = TopologyTraceEvent(
        sequence=len(events),
        topology_sha256=topology.digest,
        event_kind=event_kind,
        payload_sha256=stable_sha256(payload),
        prior_event_sha256=events[-1].digest if events else "0" * 64,
    )
    return tuple(events) + (event,)


def freeze_topology_v1() -> Mapping[str, object]:
    payload: dict[str, object] = {
        "schema": "ProofLaunchDynamicTopologyV1",
        "version": "1.0.0",
        "status": "frozen_contract_not_runtime_benchmarked",
        "capabilities": tuple(item.value for item in Capability),
        "search_modes": tuple(item.value for item in SearchMode),
        "controls": tuple(item.value for item in TopologyArm),
        "hard_limits": {"maximum_parallel": 3, "maximum_rounds": 8, "maximum_tokens": 16_000, "maximum_tool_calls": 20},
        "fixed_persona_chat": "prohibited",
        "shared_hidden_reasoning": "prohibited",
        "runtime_truth": {
            "live_agent_execution_observed": False,
            "dynamic_vs_fixed_result": None,
            "dynamic_vs_single_result": None,
            "selected_topology": None,
        },
        "truth_boundary": "Executable dynamic topology and synthetic matched-control mechanics only; no live Agent quality, latency, cost, or communication superiority is claimed.",
    }
    payload["content_sha256"] = stable_sha256(payload)
    return payload
