#!/usr/bin/env python3
from __future__ import annotations

import json
from dataclasses import asdict
from enum import Enum
from pathlib import Path
from typing import Any

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.v10_cpt_contract import (
    BaseRevision,
    CPTContract,
    CPTExecutionSettings,
    CheckpointMetrics,
    LearningRatePolicy,
    ModelProfile,
    MonitorMetric,
    default_mix_schedule,
    default_objectives,
    planned_cpt_card,
    select_best_checkpoint,
)


ROOT = Path(__file__).resolve().parents[1]


def normalize(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {
            (key.value if isinstance(key, Enum) else str(key)): normalize(item)
            for key, item in value.items()
        }
    if isinstance(value, (tuple, list, set, frozenset)):
        return [normalize(item) for item in value]
    return value


def main() -> int:
    contract = CPTContract(
        base=BaseRevision(
            model_id="google/gemma-4-E4B-it",
            revision="1fe35ce743b357484b97a11646125adffee0b410",
            config_sha256="33b10c02df3c2e8536cf323d29d53262aaa2f4d11dbe19bc729373fbe90295d4",
            tokenizer_sha256="cc8d3a0ce36466ccc1278bf987df5f71db1719b9ca6b4118264f45cb627bfe0f",
            processor_sha256="32bdf45d2ad4cc29a0822ddd157a182de76644f0419a6228d151495256e9813c",
            artifact_hashes_observed=True,
        ),
        profile=ModelProfile.E4B,
        objectives=default_objectives(),
        schedule=default_mix_schedule(),
        learning_rates=LearningRatePolicy(
            vision_tower=0.0,
            connector=2e-4,
            language_model=2e-5,
            adapter=1e-4,
        ),
        settings=CPTExecutionSettings(
            packing=True,
            packing_resets_position_and_attention=True,
            gradient_checkpointing=True,
            gradient_accumulation_steps=8,
            bf16=True,
            deterministic_seed=42,
            maximum_wall_clock_hours=6.0,
            checkpoint_interval_steps=100,
            save_optimizer=True,
            save_scheduler=True,
            save_rng_state=True,
        ),
        monitor_metrics=tuple(MonitorMetric),
    )
    controlled_selection = select_best_checkpoint(
        (
            CheckpointMetrics("controlled-step-100", 100, 0.8, 0.9, 0.98, 0.98, 0.99, 0.97, 0.95),
            CheckpointMetrics("controlled-step-200", 200, 0.7, 0.95, 0.98, 0.98, 0.99, 0.97, 0.91),
            CheckpointMetrics("controlled-step-300", 300, 0.6, 1.0, 0.90, 0.98, 0.99, 0.99, 0.99),
        )
    )
    card = planned_cpt_card(contract)
    payload = {
        "schema": "ProofLaunchCPTExecutionContractV1",
        "contract": normalize(asdict(contract)),
        "contract_sha256": contract.digest,
        "alternate_profile": ModelProfile.E2B.value,
        "profile_selection_requires_observed_rocm_vram": True,
        "base_evaluation_receipt": None,
        "radeon_memory_receipt": None,
        "controlled_checkpoint_selection": normalize(asdict(controlled_selection)),
        "controlled_checkpoint_selection_is_training_evidence": False,
        "execution_status": "planned_not_executed",
    }
    config_path = ROOT / "config/cortex_x_v10_cpt_contract.json"
    card_path = ROOT / "evidence/v10/cpt-card.planned.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    card_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(config_path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    atomic_write_text(card_path, json.dumps(card, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {
                "status": payload["execution_status"],
                "objectives": len(contract.objectives),
                "schedule_stages": len(contract.schedule),
                "monitors": len(contract.monitor_metrics),
                "contract_sha256": contract.digest,
                "card": str(card_path.relative_to(ROOT)),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
