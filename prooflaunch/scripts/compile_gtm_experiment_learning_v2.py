#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.gtm_experiment_learning_v2 import compile_experiment_learning_bundle, verify_experiment_learning_bundle


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    monitoring = {key: 1 for key in ("creative_fatigue", "excessive_frequency", "negative_feedback", "audience_overlap", "cac_increase", "retention_decline")}
    experiments = [{"experiment_id": "synthetic-exp-1", "mechanism_id": "proof-led-demand", "audience_id": "synthetic-audience", "hypothesis": "A source-visible proof sequence increases qualified proof consumption.", "primary_metric": "qualified proof consumption", "guardrails": ["negative feedback"], "duration_days": 14, "sample_plan": "synthetic regression sample only", "cost_ceiling_usd": 0, "stop_rule": "Stop on guardrail breach or at the preregistered duration.", "factors_changed": ["creative"], "factorial_design": None, "attribution_design": "randomized_holdout", "causal_claim_planned": True, "monitoring_thresholds": monitoring}]
    outcomes = [{"experiment_id": "synthetic-exp-1", "result_status": "failed", "failure_reason": "Synthetic failure retained to prove negative-evidence handling.", "evidence_status": "synthetic_regression_fixture", "primary_metric_effect": None, "confidence_interval": None, "negative_signals": [{"signal_type": "comment_objection", "summary": "The proof boundary remained unclear to the synthetic reviewer.", "required_next_test": "Test a more explicit claim-to-source mapping."}], "human_verified": False}]
    memory = [{"experiment_id": "synthetic-exp-1", "memory_statement": "Synthetic candidate must not enter long-term memory.", "human_approval": None}]
    matrix = [{"mechanism_id": "proof-led-demand", "subvertical_id": "synthetic", "company_scale": "small", "lifecycle_state": "launch", "budget_tier": "zero_paid", "market": "north_america", "effect_metric": "synthetic fixture score", "effect_estimate": 0, "ci_lower": 0, "ci_upper": 0, "evidence_status": "synthetic_regression_fixture"}]
    allocations = [{"mechanism_id": "proof-led-demand", "exploration_share": .3, "exploitation_share": .7, "platform_shares": {"linkedin": .5, "owned": .5}, "creative_family_shares": {"documented_reality": .5, "useful_tool": .5}}]
    payload = compile_experiment_learning_bundle(experiments, outcomes, memory, matrix, allocations); verify_experiment_learning_bundle(payload)
    output = ROOT / "evidence/v10/gtm-experiment-learning-v2.json"
    atomic_write_text(output, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(output), "experiment_count": len(payload["experiments"]), "eval_task_count": len(payload["evaluation_tasks_from_negative_signals"]), "promoted_memory_count": payload["promoted_memory_count"], "content_sha256": payload["content_sha256"]}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__": raise SystemExit(main())
