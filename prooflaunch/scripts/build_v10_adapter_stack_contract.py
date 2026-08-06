#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.v10_adapter_stack import (
    AdapterCapability,
    MergeMethod,
    planned_adapter_stack_card,
    planned_capability_templates,
)
from prooflaunch_remix.v10_supply_chain import stable_sha256


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    contract = {
        "schema": "ProofLaunchAdapterStackExecutionContractV1",
        "capabilities": [item.value for item in AdapterCapability],
        "capability_templates": planned_capability_templates(),
        "routing_axes": ["task", "uncertainty", "market", "risk"],
        "hotswap_backend": "peft.utils.hotswap.hotswap_adapter",
        "cache_policy": "byte_bounded_lru_protect_active",
        "registry_policy": "append_only_content_addressed_version_and_rollback",
        "merge_arms": [item.value for item in MergeMethod],
        "merge_default": MergeMethod.NO_MERGE.value,
        "merge_promotion_gates": [
            "capability_interference",
            "safety_regression",
            "claim_regression",
            "visual_regression",
        ],
        "quantization_policy": "unverified_main_model_quantization_forbidden",
        "residency_policy": "one_heavy_base_model_and_measured_90_percent_peak_budget",
        "research_sources": [
            {
                "name": "PEFT hotswapping adapters",
                "locator": "https://huggingface.co/docs/peft/package_reference/hotswap",
                "role": "official LoRA in-place hotswap semantics and compatibility limits",
            },
            {
                "name": "PEFT model merging",
                "locator": "https://huggingface.co/docs/peft/developer_guides/model_merging",
                "role": "official weighted, TIES and DARE adapter merge interfaces",
            },
            {
                "name": "TIES-Merging",
                "locator": "https://arxiv.org/abs/2306.01708",
                "role": "trim, sign election and disjoint merge research baseline",
            },
            {
                "name": "DARE",
                "locator": "https://arxiv.org/abs/2311.03099",
                "role": "drop-and-rescale merge preprocessing research baseline",
            },
        ],
        "execution_status": "control_plane_verified_training_not_executed",
        "training_observed": False,
        "merge_observed": False,
        "radeon_runtime_observed": False,
    }
    payload = {**contract, "contract_sha256": stable_sha256(contract)}
    atomic_write_text(
        ROOT / "config/cortex_x_v10_adapter_stack_contract.json",
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
    )
    atomic_write_text(
        ROOT / "evidence/v10/adapter-pseudo-moe-card.planned.json",
        json.dumps(planned_adapter_stack_card(), ensure_ascii=False, indent=2) + "\n",
    )
    print(json.dumps({"status": payload["execution_status"], "contract_sha256": payload["contract_sha256"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
