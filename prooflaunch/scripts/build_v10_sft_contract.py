#!/usr/bin/env python3
from __future__ import annotations

import json
from dataclasses import asdict
from enum import Enum
from pathlib import Path
from typing import Any

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.v10_sft_contract import (
    CANONICAL_STAGE_ORDER,
    ComparisonMetric,
    SFTContract,
    build_controlled_replay,
    default_input_curriculum,
    default_loss_policy,
    default_stage_definitions,
    default_trainer_contracts,
    planned_sft_card,
)


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
    contract = SFTContract(
        stages=default_stage_definitions(),
        inputs=default_input_curriculum(),
        loss_policy=default_loss_policy(),
        trainers=default_trainer_contracts(),
        comparison_metrics=tuple(ComparisonMetric),
    )
    replay = build_controlled_replay(CANONICAL_STAGE_ORDER)
    payload = {
        "schema": "ProofLaunchSFTExecutionContractV1",
        "contract": normalize(asdict(contract)),
        "contract_sha256": contract.digest,
        "controlled_replay": normalize(asdict(replay)),
        "controlled_replay_sha256": replay.digest,
        "controlled_replay_is_training_evidence": False,
        "execution_status": "planned_not_executed",
    }
    config = ROOT / "config/cortex_x_v10_sft_contract.json"
    card = ROOT / "evidence/v10/sft-card.planned.json"
    atomic_write_text(config, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    atomic_write_text(
        card,
        json.dumps(planned_sft_card(contract), ensure_ascii=False, indent=2) + "\n",
    )
    print(
        json.dumps(
            {
                "status": payload["execution_status"],
                "stages": len(contract.stages),
                "input_phases": len(contract.inputs),
                "trainer_variants": len(contract.trainers),
                "contract_sha256": contract.digest,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
