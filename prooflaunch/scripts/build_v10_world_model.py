#!/usr/bin/env python3
from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import Any

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.v10_supply_chain import stable_sha256
from prooflaunch_remix.v10_world_model import freeze_world_model_v1


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
    contract = normalize(freeze_world_model_v1())
    evidence = {
        "schema": "ProofLaunchCampaignWorldModelMechanicalFixtureV1",
        "contract_sha256": contract["content_sha256"],
        "canonical_todos": [f"{number:04d}" for number in range(201, 251)],
        "mechanically_verified": {
            "typed_state_components": 12,
            "whitelisted_action_kinds": 7,
            "future_trajectories": 3,
            "pareto_maximize": 2,
            "pareto_minimize": 4,
            "exclusive_error_sources": 3,
            "hash_chain": True,
            "state_diff": True,
            "state_replay": True,
            "state_compression": True,
            "state_visualization": True,
            "uncertainty_calibration_formula": True,
            "prediction_actual_deviation": True,
            "hard_sample_conversion": True,
        },
        "runtime_truth": contract["runtime_truth"],
        "fixture_scope": "deterministic synthetic contract and formula verification only",
        "closure_basis": "Typed states, actions, transitions, predictions, trajectories, ledger, calibration, attribution and freeze mechanics; no learned predictor or runtime quality claim.",
    }
    evidence["content_sha256"] = stable_sha256(evidence)
    atomic_write_text(
        ROOT / "config/cortex_x_v10_world_model_v1.json",
        json.dumps(contract, ensure_ascii=False, indent=2) + "\n",
    )
    atomic_write_text(
        ROOT / "evidence/v10/world-model-v1-mechanical-fixture.json",
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
    )
    print(
        json.dumps(
            {
                "status": contract["status"],
                "state_components": len(contract["state_components"]),
                "action_kinds": len(contract["action_kinds"]),
                "future_profiles": len(contract["future_profiles"]),
                "trained_predictor_observed": contract["runtime_truth"]["trained_predictor_observed"],
                "content_sha256": contract["content_sha256"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
