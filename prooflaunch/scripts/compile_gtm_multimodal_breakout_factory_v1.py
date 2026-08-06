#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.gtm_multimodal_breakout_factory import compile_multimodal_breakout_factory


ROOT = Path(__file__).resolve().parents[1]
DISTILLATION = ROOT / "evidence/v10/gtm-named-capability-distillation-v1.json"
CASE_SYSTEM = ROOT / "artifacts/gtm-last-mile-pk-v1/gtm-breakout-operator-v1/case-system-v2.json"
OUTPUT = ROOT / "evidence/v10/gtm-multimodal-breakout-factory-v1.json"


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _brief(*, model: str, platform: str, case_system: dict) -> dict[str, str]:
    b2b = model == "b2b"
    case = case_system["cases"][model]
    channel = next(row for row in case["channels"] if row["id"] == platform)
    activation = next(row for row in case["activation_wave"] if row["channel_id"] == platform)
    return {
        "brief_id": f"factory-{model}-{platform}", "business_model": model, "lifecycle": "launch",
        "industry": "enterprise AI software" if b2b else "consumer productivity",
        "category": "AI GTM employee" if b2b else "private memory ritual",
        "product_surface": "web_agent" if b2b else "mobile_app", "platform": platform,
        "audience": case["audience"],
        "decision_job": activation["job"],
        "tension": case["tension"],
        "approved_proof": channel["proof"],
        "brand_voice": "specific, restrained, useful, surprising", "budget": "zero",
    }


def main() -> None:
    distillation = json.loads(DISTILLATION.read_text(encoding="utf-8"))
    case_system = json.loads(CASE_SYSTEM.read_text(encoding="utf-8"))
    contexts = [
        _brief(model="b2b", platform="linkedin", case_system=case_system),
        _brief(model="b2b", platform="reddit", case_system=case_system),
        _brief(model="b2c", platform="tiktok", case_system=case_system),
        _brief(model="b2c", platform="instagram", case_system=case_system),
    ]
    factories = [compile_multimodal_breakout_factory(brief, named_capability_distillation=distillation) for brief in contexts]
    payload = {
        "schema": "ProofLaunchGTMMultimodalBreakoutFactoryPortfolioV1",
        "context_count": len(factories), "business_models": ["b2b", "b2c"],
        "platforms": ["linkedin", "reddit", "tiktok", "instagram"],
        "zero_budget_context_count": sum(row["zero_budget_mode"] for row in factories),
        "candidate_campaign_count": sum(len(row["candidate_campaigns"]) for row in factories),
        "model_ready_work_order_count": sum(row["model_call_budget"]["total"] for row in factories),
        "factories": factories, "produced_asset_count": 0, "external_action_count": 0,
        "truth_boundary": "The portfolio proves cross-context compilation of model-ready multimodal work orders. It does not prove rendered quality, organic effects or named-product wins.",
    }
    payload["content_sha256"] = hashlib.sha256(_canonical(payload)).hexdigest()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(OUTPUT, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "output": str(OUTPUT), "context_count": payload["context_count"],
        "candidate_campaign_count": payload["candidate_campaign_count"],
        "model_ready_work_order_count": payload["model_ready_work_order_count"],
        "content_sha256": payload["content_sha256"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
