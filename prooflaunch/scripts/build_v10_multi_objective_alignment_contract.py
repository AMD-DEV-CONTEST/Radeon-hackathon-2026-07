#!/usr/bin/env python3
from __future__ import annotations

import json
from dataclasses import asdict
from enum import Enum
from pathlib import Path
from typing import Any

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.v10_multi_objective_alignment import (
    AlignmentBudget,
    AlignmentMonitorThresholds,
    VerifierQuorumPolicy,
    default_alignment_methods,
    default_safety_policy,
    planned_alignment_card,
)
from prooflaunch_remix.v10_supply_chain import stable_sha256


ROOT = Path(__file__).resolve().parents[1]


def normalize(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {normalize(key): normalize(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [normalize(item) for item in value]
    return value


def main() -> int:
    contract = {
        "reward_selection": normalize(asdict(default_safety_policy())),
        "alignment_methods": normalize([asdict(item) for item in default_alignment_methods()]),
        "experiment_budget": asdict(AlignmentBudget()),
        "monitoring_thresholds": asdict(AlignmentMonitorThresholds()),
        "verifier_quorum": normalize(asdict(VerifierQuorumPolicy())),
        "rich_feedback_kinds": ["audit_feedback", "tool_error_feedback", "human_critique_feedback"],
    }
    payload = {
        "schema": "ProofLaunchMultiObjectiveAlignmentExecutionContractV1",
        "contract": contract,
        "contract_sha256": stable_sha256(contract),
        "research_sources": [
            {"name": "TextGrad", "locator": "https://arxiv.org/abs/2406.07496", "role": "rich textual feedback as executable optimization signal"},
            {"name": "ORPO", "locator": "https://arxiv.org/abs/2403.07691", "role": "reference-free preference-aligned SFT baseline"},
            {"name": "SimPO", "locator": "https://arxiv.org/abs/2405.14734", "role": "length-normalized reference-free margin baseline"},
            {"name": "MDPO", "locator": "https://arxiv.org/abs/2406.11839", "role": "multimodal conditional preference baseline"},
            {"name": "DeepSeekMath GRPO", "locator": "https://arxiv.org/abs/2402.03300", "role": "group-relative policy optimization baseline"},
        ],
        "execution_status": "planned_not_executed",
        "rollout_observed": False,
        "training_observed": False,
        "verifier_observed": False,
        "human_spotcheck_observed": False,
    }
    config = ROOT / "config/cortex_x_v10_multi_objective_alignment_contract.json"
    card = ROOT / "evidence/v10/multi-objective-alignment-card.planned.json"
    atomic_write_text(config, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    atomic_write_text(card, json.dumps(planned_alignment_card(), ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": payload["execution_status"], "reward_dimensions": 13, "method_count": 4, "contract_sha256": payload["contract_sha256"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

