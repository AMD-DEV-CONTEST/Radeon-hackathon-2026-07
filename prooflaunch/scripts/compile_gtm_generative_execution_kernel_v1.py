#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text, sha256_file
from prooflaunch_remix.gtm_genome_learning_memory import verify_genome_learning_memory
from prooflaunch_remix.gtm_generative_execution_kernel import compile_generative_execution_kernel


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "artifacts/gtm-last-mile-pk-v1/gtm-breakout-operator-v1/case-system-v2.json"
OUTPUT = ROOT / "evidence/v10/gtm-generative-execution-kernel-v1.json"
LEARNING_MEMORY = ROOT / "evidence/v10/gtm-genome-learning-memory-v1.json"


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def brief(source: dict, *, business_model: str, platform: str) -> dict[str, str]:
    case = source["cases"][business_model]
    channel = next(row for row in case["channels"] if row["id"] == platform)
    if business_model == "b2b":
        return {
            "brief_id": f"prooflaunch-{platform}-generalization-v1", "business_model": "b2b", "lifecycle": "launch",
            "industry": "AI software", "category": "AI GTM employee", "product_surface": "web_agent", "platform": platform,
            "audience": case["audience"], "decision_job": "decide whether an AI GTM employee deserves a design-partner evaluation",
            "tension": case["tension"], "approved_proof": channel["proof"], "brand_voice": "specific, calm, unexpected, operator-led", "budget": "zero",
        }
    return {
        "brief_id": f"private-memory-{platform}-generalization-v1", "business_model": "b2c", "lifecycle": "launch",
        "industry": "consumer productivity", "category": "private memory ritual", "product_surface": "mobile_app", "platform": platform,
        "audience": case["audience"], "decision_job": "choose a low-pressure private memory behavior worth repeating",
        "tension": case["tension"], "approved_proof": channel["proof"], "brand_voice": "intimate, restrained, surprising, non-performative", "budget": "zero",
    }


def main() -> None:
    if not SOURCE.is_file():
        raise SystemExit(f"missing generative-kernel source: {SOURCE}")
    if not LEARNING_MEMORY.is_file():
        raise SystemExit(f"missing human-approved learning memory: {LEARNING_MEMORY}")
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    learning_memory = json.loads(LEARNING_MEMORY.read_text(encoding="utf-8"))
    verify_genome_learning_memory(learning_memory)
    contexts = [
        brief(source, business_model="b2b", platform="linkedin"),
        brief(source, business_model="b2b", platform="reddit"),
        brief(source, business_model="b2c", platform="tiktok"),
        brief(source, business_model="b2c", platform="instagram"),
    ]
    kernels = [
        compile_generative_execution_kernel(context, candidate_count=24, learning_memory=learning_memory)
        for context in contexts
    ]
    prior = [row["genome_id"] for row in kernels[2]["candidate_blueprints"]]
    prior_set = set(prior)
    next_wave = compile_generative_execution_kernel(
        contexts[2], prior_genome_ids=prior, candidate_count=24, learning_memory=learning_memory
    )
    payload = {
        "schema": "ProofLaunchGTMGenerativeExecutionPortfolioV1",
        "source_case_system_sha256": source["content_sha256"],
        "context_count": len(kernels),
        "business_models": ["b2b", "b2c"],
        "platforms": ["linkedin", "reddit", "tiktok", "instagram"],
        "candidate_blueprint_count": sum(len(kernel["candidate_blueprints"]) for kernel in kernels),
        "next_wave_nonrepeating_candidate_count": len(next_wave["candidate_blueprints"]),
        "next_wave_overlap_count": len(prior_set & {row["genome_id"] for row in next_wave["candidate_blueprints"]}),
        "kernels": kernels,
        "next_wave_tiktok": next_wave,
        "generated_content_count": 0,
        "external_action_count": 0,
        "named_product_win_count": 0,
        "learning_memory_status": "empty_awaiting_named_human_approved_effect_evidence",
        "learning_memory_binding": {
            "path": LEARNING_MEMORY.relative_to(ROOT).as_posix(),
            "sha256": sha256_file(LEARNING_MEMORY),
            "content_sha256": learning_memory["content_sha256"],
            "record_count": learning_memory["record_count"],
        },
        "truth_boundary": "This portfolio proves reusable, non-repeating creative blueprint compilation across four B2B/B2C platform contexts. It does not prove the blueprints have been instantiated, published, preferred or turned into breakout effects.",
        "source_binding": {"path": SOURCE.relative_to(ROOT).as_posix(), "sha256": sha256_file(SOURCE)},
    }
    payload["content_sha256"] = hashlib.sha256(canonical(payload)).hexdigest()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(OUTPUT, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(OUTPUT), "candidate_blueprint_count": payload["candidate_blueprint_count"], "next_wave_overlap_count": payload["next_wave_overlap_count"], "content_sha256": payload["content_sha256"]}, sort_keys=True))


if __name__ == "__main__":
    main()
