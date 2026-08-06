#!/usr/bin/env python3
from __future__ import annotations

import json
from dataclasses import asdict
from enum import Enum
from pathlib import Path
from typing import Any

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.v10_on_policy_distillation import (
    ExperimentBudget,
    FrozenRevisionPair,
    MonitoringThresholds,
    default_deployment_contract,
    default_method_specs,
    default_protection_policy,
    default_temporal_curriculum,
    planned_distillation_card,
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
    methods = default_method_specs()
    revisions = FrozenRevisionPair(
        teacher_revision="UNRESOLVED_PENDING_RIGHTS_AND_METHOD_SELECTION",
        student_revision="AI-ModelScope/Gemma-4-E4B-it@4f5f0c899a9b6d34c4b463f557c31c8ac6c767cc",
    )
    contract = {
        "methods": normalize([asdict(item) for item in methods]),
        "deployment_input": normalize(asdict(default_deployment_contract())),
        "protection_policy": normalize(asdict(default_protection_policy())),
        "temporal_curriculum": normalize(
            [asdict(item) for item in default_temporal_curriculum()]
        ),
        "experiment_budget": asdict(ExperimentBudget()),
        "monitoring_thresholds": asdict(MonitoringThresholds()),
        "revision_pair": asdict(revisions),
    }
    payload = {
        "schema": "ProofLaunchOnPolicyDistillationExecutionContractV1",
        "contract": contract,
        "contract_sha256": stable_sha256(contract),
        "research_sources": [
            {
                "name": "THUNLP OPD",
                "locator": "https://github.com/thunlp/OPD",
                "role": "teacher-student dynamics and recipe reference",
            },
            {
                "name": "TCOD",
                "locator": "https://github.com/kokolerk/TCOD",
                "role": "short-to-long temporal curriculum and trajectory-KL instability reference",
            },
            {
                "name": "TRL GKDTrainer",
                "locator": "https://huggingface.co/docs/trl/main/en/gkd_trainer",
                "role": "reusable GKD implementation surface",
            },
        ],
        "execution_status": "planned_not_executed",
        "teacher_revision_observed": False,
        "student_rollout_observed": False,
        "teacher_evaluation_observed": False,
        "training_observed": False,
    }
    config = ROOT / "config/cortex_x_v10_on_policy_distillation_contract.json"
    card = ROOT / "evidence/v10/on-policy-distillation-card.planned.json"
    atomic_write_text(config, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    atomic_write_text(
        card,
        json.dumps(
            planned_distillation_card(methods, revisions),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
    )
    print(
        json.dumps(
            {
                "status": payload["execution_status"],
                "method_count": len(methods),
                "stage_count": len(default_temporal_curriculum()),
                "contract_sha256": payload["contract_sha256"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
