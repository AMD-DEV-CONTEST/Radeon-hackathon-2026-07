from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Mapping

from .contracts import Stage
from .ledger import canonical_json


class GraphLoopHarnessError(ValueError):
    """A fixed workflow, bounded loop, or global harness invariant failed."""


@dataclass(frozen=True)
class GraphLoopHarnessContract:
    """Executable L2 control contract for the production GTM vertical slice.

    The graph owns business flow, the loop owns only audit repair, and the
    harness owns permissions, budgets, approval, durability and trace rules.
    It is deliberately independent of the model and accelerator backend.
    """

    graph: Mapping[str, tuple[str, ...]]
    loop_node: str
    loop_max_iterations: int
    retryable_failures: tuple[str, ...]
    no_retry_failures: tuple[str, ...]
    maximum_actions: int
    maximum_cost_usd: float
    permitted_effects: tuple[str, ...]
    prohibited_effects: tuple[str, ...]
    human_approval_before: tuple[str, ...]

    def __post_init__(self) -> None:
        expected = {stage.value for stage in Stage}
        if set(self.graph) != expected:
            raise GraphLoopHarnessError("graph must declare every workflow stage")
        for source, targets in self.graph.items():
            if not targets or not set(targets).issubset(expected):
                raise GraphLoopHarnessError(f"invalid graph edges from {source}")
        if self.loop_node != Stage.REPAIR.value or self.loop_max_iterations != 2:
            raise GraphLoopHarnessError("only the two-round repair loop is autonomous")
        if set(self.retryable_failures) & set(self.no_retry_failures):
            raise GraphLoopHarnessError("retry and no-retry failure classes overlap")
        if not 5 <= self.maximum_actions <= 24:
            raise GraphLoopHarnessError("production action budget must be in [5, 24]")
        if self.maximum_cost_usd != 0:
            raise GraphLoopHarnessError("the local product slice has a zero spend cap")
        if "external_publish" not in self.prohibited_effects:
            raise GraphLoopHarnessError("external publishing must be prohibited")
        if "release" not in self.human_approval_before:
            raise GraphLoopHarnessError("release must require human approval")

    def allows_transition(self, source: Stage, target: Stage) -> bool:
        return target.value in self.graph[source.value]

    def require_transition(self, source: Stage, target: Stage) -> None:
        if not self.allows_transition(source, target):
            raise GraphLoopHarnessError(
                f"graph transition is forbidden: {source.value} -> {target.value}"
            )

    def receipt(self) -> dict[str, object]:
        core: dict[str, object] = {
            "schema": "ProofLaunchGraphLoopHarnessV1",
            "autonomy_level": "L2_deterministic_workflow",
            "graph": {key: list(value) for key, value in sorted(self.graph.items())},
            "loop": {
                "node": self.loop_node,
                "maximum_iterations": self.loop_max_iterations,
                "retryable_failures": list(self.retryable_failures),
                "no_retry_failures": list(self.no_retry_failures),
                "termination": [
                    "all_release_blockers_cleared",
                    "iteration_budget_exhausted_then_block",
                    "non_retryable_failure_then_block",
                ],
            },
            "harness": {
                "authoritative_state_owner": "Supervisor",
                "state_store": "SQLite_WAL_CAS_event_hash_chain",
                "maximum_actions": self.maximum_actions,
                "maximum_cost_usd": self.maximum_cost_usd,
                "permitted_effects": list(self.permitted_effects),
                "prohibited_effects": list(self.prohibited_effects),
                "human_approval_before": list(self.human_approval_before),
                "idempotency_required": True,
                "content_bound_approval_required": True,
                "fail_closed": True,
                "model_backend_independent": True,
            },
            "truth_boundary": (
                "This receipt proves the declared deterministic control contract and "
                "mechanical validation only. It does not prove model quality, external "
                "publication, 4A creative preference, causal lift or revenue."
            ),
        }
        core["contract_sha256"] = hashlib.sha256(
            canonical_json(core).encode("utf-8")
        ).hexdigest()
        return core


def production_graph_loop_harness(
    *, maximum_actions: int, maximum_cost_usd: float
) -> GraphLoopHarnessContract:
    return GraphLoopHarnessContract(
        graph={
            Stage.EVIDENCE.value: (Stage.PLAN.value, Stage.BLOCKED.value),
            Stage.PLAN.value: (Stage.CREATE.value, Stage.BLOCKED.value),
            Stage.CREATE.value: (Stage.AUDIT.value, Stage.BLOCKED.value),
            Stage.AUDIT.value: (
                Stage.REPAIR.value,
                Stage.AWAITING_RELEASE.value,
                Stage.BLOCKED.value,
            ),
            Stage.REPAIR.value: (Stage.AUDIT.value, Stage.BLOCKED.value),
            Stage.AWAITING_RELEASE.value: (Stage.DELIVER.value, Stage.BLOCKED.value),
            Stage.DELIVER.value: (Stage.DELIVER.value,),
            Stage.BLOCKED.value: (Stage.BLOCKED.value,),
        },
        loop_node=Stage.REPAIR.value,
        loop_max_iterations=2,
        retryable_failures=("quality_finding", "render_validation_failure"),
        no_retry_failures=(
            "permission_denied",
            "schema_error",
            "rights_failure",
            "approval_mismatch",
        ),
        maximum_actions=maximum_actions,
        maximum_cost_usd=maximum_cost_usd,
        permitted_effects=(
            "local_source_read",
            "local_draft_write",
            "local_render",
            "local_audit",
            "local_content_addressed_bundle",
        ),
        prohibited_effects=(
            "external_publish",
            "outbound_message",
            "media_spend",
            "destructive_delete",
            "credential_exposure",
        ),
        human_approval_before=("release", "external_publish", "spend", "send"),
    )
