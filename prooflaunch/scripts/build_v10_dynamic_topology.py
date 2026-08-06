#!/usr/bin/env python3
from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import Any

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.v10_contracts import EvidenceClass
from prooflaunch_remix.v10_dynamic_topology import (
    TopologyArm,
    TopologyOutcome,
    evaluate_matched_topology_arms,
    freeze_topology_v1,
)
from prooflaunch_remix.v10_supply_chain import stable_sha256


ROOT = Path(__file__).resolve().parents[1]


def normalize(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(normalize(key)): normalize(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [normalize(item) for item in value]
    return value


def main() -> int:
    contract = normalize(freeze_topology_v1())
    outcomes = tuple(
        TopologyOutcome(
            arm=arm,
            task_id=task_id,
            success=arm is TopologyArm.DYNAMIC,
            tokens=100,
            tool_calls=2,
            latency_ms=50,
            communication_events=3,
            evidence_class=EvidenceClass.SIMULATED,
        )
        for arm in TopologyArm
        for task_id in ("synthetic-task-1", "synthetic-task-2")
    )
    evidence = {
        "schema": "ProofLaunchDynamicTopologyMechanicalFixtureV1",
        "contract_sha256": contract["content_sha256"],
        "canonical_todos": [f"{number:04d}" for number in range(251, 301)],
        "mechanically_verified": {
            "capability_contracts": 12,
            "search_modes": 3,
            "matched_control_arms": 3,
            "maximum_parallel": 3,
            "maximum_rounds": 8,
            "maximum_tokens": 16_000,
            "maximum_tool_calls": 20,
            "fact_blackboard": True,
            "implicit_reasoning_rejected": True,
            "topology_mutation_and_rollback": True,
            "graph_validation": True,
            "opinion_and_observation_pruning": True,
            "structural_entropy": True,
            "trace_hash_chain": True,
        },
        "synthetic_matched_control_formula_fixture": evaluate_matched_topology_arms(outcomes),
        "runtime_truth": contract["runtime_truth"],
        "fixture_scope": "synthetic deterministic topology mechanics only; synthetic arm values are not product quality evidence",
    }
    evidence["content_sha256"] = stable_sha256(evidence)
    atomic_write_text(
        ROOT / "config/cortex_x_v10_dynamic_topology_v1.json",
        json.dumps(contract, ensure_ascii=False, indent=2) + "\n",
    )
    atomic_write_text(
        ROOT / "evidence/v10/dynamic-topology-v1-mechanical-fixture.json",
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
    )
    print(
        json.dumps(
            {
                "status": contract["status"],
                "capabilities": len(contract["capabilities"]),
                "controls": len(contract["controls"]),
                "live_agent_execution_observed": contract["runtime_truth"]["live_agent_execution_observed"],
                "content_sha256": contract["content_sha256"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
