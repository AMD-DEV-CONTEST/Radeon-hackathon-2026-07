#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.v10_gtm_employee import Channel, planned_gtm_skill_card
from prooflaunch_remix.v10_supply_chain import stable_sha256


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    contract = {
        "schema": "ProofLaunch4AGtmEmployeeExecutionContractV1",
        "channels": [item.value for item in Channel],
        "verified_mechanisms": [
            "cross_channel_consistency",
            "cross_channel_non_repetition",
            "performance_hypothesis",
            "ab_plan",
            "creative_fatigue_plan",
            "audience_learning_plan",
        ],
        "claim_policy": "objective_claims_require_prior_located_substantiation",
        "experiment_policy": "one_changed_variable_randomized_arms_srm_gate_human_release",
        "research_sources": [
            {
                "name": "FTC Advertising Substantiation Policy",
                "locator": "https://www.ftc.gov/legal-library/browse/ftc-policy-statement-regarding-advertising-substantiation",
                "role": "prior substantiation boundary for express and implied objective claims",
            },
            {
                "name": "Google Ads experiments guidance",
                "locator": "https://support.google.com/google-ads/answer/7281575",
                "role": "clear hypothesis, isolated variable and preselected metric experiment baseline",
            },
        ],
        "execution_status": "output_contracts_verified_distillation_not_executed",
        "distillation_observed": False,
        "five_rater_evaluation_observed": False,
    }
    payload = {**contract, "contract_sha256": stable_sha256(contract)}
    atomic_write_text(
        ROOT / "config/cortex_x_v10_gtm_employee_contract.json",
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
    )
    atomic_write_text(
        ROOT / "evidence/v10/gtm-skill-card.planned.json",
        json.dumps(planned_gtm_skill_card(), ensure_ascii=False, indent=2) + "\n",
    )
    print(json.dumps({"status": payload["execution_status"], "contract_sha256": payload["contract_sha256"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
