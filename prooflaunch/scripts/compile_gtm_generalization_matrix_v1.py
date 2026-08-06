#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text, sha256_file
from prooflaunch_remix.gtm_genome_learning_memory import verify_genome_learning_memory
from prooflaunch_remix.gtm_generative_execution_kernel import compile_generative_execution_kernel


ROOT = Path(__file__).resolve().parents[1]
MEMORY = ROOT / "evidence/v10/gtm-genome-learning-memory-v1.json"
OUTPUT = ROOT / "evidence/v10/gtm-generative-generalization-matrix-v1.json"
SURFACES = (
    "linkedin", "tiktok", "reddit", "youtube", "instagram", "x",
    "google_search", "bing_search", "chatgpt_answers", "claude_answers",
    "gemini_answers", "perplexity_answers", "copilot_answers",
)
LIFECYCLES = ("pre_pmf", "launch", "growth", "mature")
BUDGET_BY_LIFECYCLE = {
    "pre_pmf": "zero", "launch": "small", "growth": "scaled", "mature": "enterprise"
}


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _brief(*, business_model: str, lifecycle: str, platform: str) -> dict[str, str]:
    b2b = business_model == "b2b"
    return {
        "brief_id": f"generalization-{business_model}-{lifecycle}-{platform}",
        "business_model": business_model,
        "lifecycle": lifecycle,
        "industry": "enterprise AI software" if b2b else "consumer productivity",
        "category": "AI GTM employee" if b2b else "private memory ritual",
        "product_surface": "web_agent" if b2b else "mobile_app",
        "platform": platform,
        "audience": "revenue operators in committee review" if b2b else "privacy-conscious mobile creators",
        "decision_job": "choose whether to evaluate a traceable GTM operator" if b2b else "choose a private behavior worth repeating",
        "tension": "automation can hide weak evidence" if b2b else "public performance can erase private meaning",
        "approved_proof": "one owner-approved bounded product demonstration is available",
        "brand_voice": "specific, restrained, useful, surprising",
        "budget": BUDGET_BY_LIFECYCLE[lifecycle],
    }


def main() -> None:
    memory = json.loads(MEMORY.read_text(encoding="utf-8"))
    verify_genome_learning_memory(memory)
    rows = []
    total_blueprints = 0
    for business_model in ("b2b", "b2c"):
        for lifecycle in LIFECYCLES:
            for platform in SURFACES:
                brief = _brief(business_model=business_model, lifecycle=lifecycle, platform=platform)
                first = compile_generative_execution_kernel(brief, candidate_count=8, learning_memory=memory)
                prior = [row["genome_id"] for row in first["candidate_blueprints"]]
                second = compile_generative_execution_kernel(
                    brief, candidate_count=8, prior_genome_ids=prior, learning_memory=memory
                )
                overlap = set(prior) & {row["genome_id"] for row in second["candidate_blueprints"]}
                rows.append({
                    "context_id": brief["brief_id"],
                    "business_model": business_model,
                    "lifecycle": lifecycle,
                    "budget": brief["budget"],
                    "platform": platform,
                    "first_wave_kernel_sha256": first["content_sha256"],
                    "second_wave_kernel_sha256": second["content_sha256"],
                    "blueprint_design_space": first["creative_genome"]["blueprint_design_space"],
                    "first_wave_count": len(first["candidate_blueprints"]),
                    "second_wave_count": len(second["candidate_blueprints"]),
                    "next_wave_overlap_count": len(overlap),
                    "minimum_first_wave_axis_distance": first["creative_genome"]["minimum_pairwise_axis_distance"],
                    "learning_record_count": first["creative_genome"]["applicable_learning_record_count"],
                })
                total_blueprints += len(first["candidate_blueprints"]) + len(second["candidate_blueprints"])
    payload = {
        "schema": "ProofLaunchGTMGenerativeGeneralizationMatrixV1",
        "context_count": len(rows),
        "surface_count": len(SURFACES),
        "business_models": ["b2b", "b2c"],
        "lifecycles": list(LIFECYCLES),
        "budgets": [BUDGET_BY_LIFECYCLE[row] for row in LIFECYCLES],
        "compiled_blueprint_count": total_blueprints,
        "all_next_waves_zero_overlap": all(row["next_wave_overlap_count"] == 0 for row in rows),
        "all_batches_diverse": all(row["minimum_first_wave_axis_distance"] >= 3 for row in rows),
        "learning_memory_binding": {
            "path": MEMORY.relative_to(ROOT).as_posix(),
            "sha256": sha256_file(MEMORY),
            "content_sha256": memory["content_sha256"],
            "record_count": memory["record_count"],
        },
        "contexts": rows,
        "generated_content_count": 0,
        "external_action_count": 0,
        "breakout_claim_count": 0,
        "truth_boundary": "This matrix proves deterministic compilation, diversity and next-wave genome exclusion across declared contexts. It does not prove content quality, transfer effects, virality or market outcomes.",
    }
    payload["content_sha256"] = hashlib.sha256(_canonical(payload)).hexdigest()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(OUTPUT, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "output": str(OUTPUT), "context_count": len(rows), "compiled_blueprint_count": total_blueprints,
        "all_next_waves_zero_overlap": payload["all_next_waves_zero_overlap"],
        "content_sha256": payload["content_sha256"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
