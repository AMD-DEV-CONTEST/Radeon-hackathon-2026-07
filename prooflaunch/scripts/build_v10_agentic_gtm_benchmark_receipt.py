from __future__ import annotations

import json
from pathlib import Path

from prooflaunch_remix.v10_agentic_gtm_benchmark import score_agentic_gtm_output


ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "data" / "tokenfactory_teacher_v10" / "_agentic_benchmark" / "accepted-outputs.json"
OUTPUT = ROOT / "evidence" / "v10" / "agentic-gtm-flagship-benchmark-2026-07-31.json"


def main() -> None:
    batch = json.loads(INPUT.read_text(encoding="utf-8"))
    scored = []
    for item in batch["outputs"]:
        score = score_agentic_gtm_output(json.dumps(item["output"], ensure_ascii=False))
        scored.append(
            {
                "model": item["model"],
                "visible_output_sha256": item["visible_output_sha256"],
                "latency_ms": item["latency_ms"],
                "cost_usd": item["cost_usd"],
                "score": score.as_dict(),
            }
        )
    receipt = {
        "schema": "ProofLaunchAgenticGtmFlagshipBenchmarkV1",
        "observed_at": batch["observed_at"],
        "provider": batch["provider"],
        "catalog": {
            "models": [
                "Qwen3.6-35B-A3B",
                "DeepSeek-V4-Flash",
                "MiniCPM5-1B",
                "MiniMax-M3",
                "dynamic-model-minicpm-v46/MiniCPM-V46",
            ],
            "minimax_h3_observed": False,
            "minimax_m3_observed": True,
        },
        "request_summary": {
            "requests": 8,
            "errors": 0,
            "prompt_tokens": 2277,
            "completion_tokens": 8520,
            "reasoning_tokens": 2616,
            "total_tokens": 10797,
            "cost_usd": 0.00678734015673399,
            "daily_budget_usd": 10,
            "daily_remaining_usd": 9.993212659843266,
            "kv_cache_hit_tokens": 0,
            "cache_write_tokens": 0,
        },
        "attempt_outcomes": [
            {"model": "Qwen3.6-35B-A3B", "attempts": 2, "http_200": 2, "accepted": False, "reason": "visible content empty after reasoning consumed both output budgets"},
            {"model": "DeepSeek-V4-Flash", "attempts": 2, "http_200": 2, "accepted": True, "reason": "repair attempt passed the strict GTM contract"},
            {"model": "MiniCPM5-1B", "attempts": 1, "http_200": 1, "accepted": False, "reason": "only 3 of 9 required top-level fields"},
            {"model": "MiniMax-M3", "attempts": 2, "http_200": 2, "accepted": False, "reason": "both JSON outputs truncated"},
            {"model": "dynamic-model-minicpm-v46/MiniCPM-V46", "attempts": 1, "http_200": 1, "accepted": False, "reason": "fast baseline lacks executable tool calls and a dependency-aware DAG"},
        ],
        "scored_preserved_outputs": scored,
        "selected_teacher_candidate": "DeepSeek-V4-Flash",
        "training_admission": {
            "status": "blocked",
            "reason": "no active executable Radeon GPU instance, the Token Factory fine-tuning jobs route returned HTTP 404, and provider-output training rights remain under review",
            "token_factory_fine_tuning_jobs_get_status": 404,
            "real_training_executed": False,
        },
        "truth_boundary": {
            "real_external_inference_observed": True,
            "real_agentic_gtm_candidate_observed": True,
            "local_radeon_inference_observed": False,
            "model_training_observed": False,
            "competition_core_eligible": False,
            "credential_persisted": False,
            "raw_outputs_public_archive_eligible": False,
        },
    }
    OUTPUT.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(OUTPUT), "selected": receipt["selected_teacher_candidate"]}))


if __name__ == "__main__":
    main()
