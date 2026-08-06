#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from prooflaunch_remix.gtm_breakout_mechanism_routing import compile_breakout_mechanism_routing, verify_breakout_mechanism_routing


VERTICAL_BLUEPRINTS = {
    "developer_tools": ["inspectable-trust-moat", "product-carries-distribution", "expertise-content-commerce", "geo-authentic-mention-flywheel"],
    "ai_data_infrastructure": ["inspectable-trust-moat", "expertise-content-commerce", "adaptive-vertical-pods", "quality-to-economics-experiment"],
    "cybersecurity": ["inspectable-trust-moat", "expertise-content-commerce", "targeted-earned-distribution", "adaptive-vertical-pods"],
    "b2b_saas": ["self-serve-to-expansion", "product-carries-distribution", "community-to-owned-demand", "geo-authentic-mention-flywheel"],
    "fintech_regtech": ["inspectable-trust-moat", "adaptive-vertical-pods", "retention-service-moat", "quality-to-economics-experiment"],
    "martech_sales_tech": ["community-to-owned-demand", "self-serve-to-expansion", "adaptive-vertical-pods", "organic-proof-to-paid-amplification"],
    "hr_future_of_work": ["value-before-offer-sequence", "community-to-owned-demand", "adaptive-vertical-pods", "retention-service-moat"],
    "professional_services": ["professional-authority-to-recurring-contract", "long-cycle-proof-assisted-selling", "paid-dependence-to-owned-intent-reset", "adaptive-vertical-pods", "targeted-earned-distribution"],
    "industrial_climate": ["technical-specification-to-qualified-demand", "channel-partner-demand-and-execution-loop", "b2b-self-service-reorder-engine", "long-cycle-proof-assisted-selling", "inspectable-trust-moat"],
    "healthcare_life_sciences": ["inspectable-trust-moat", "expertise-content-commerce", "quality-to-economics-experiment", "adaptive-vertical-pods"],
    "consumer_ai_mobile_apps": ["product-carries-distribution", "quality-to-economics-experiment", "community-to-owned-demand", "geo-authentic-mention-flywheel"],
    "personal_finance": ["inspectable-trust-moat", "value-before-offer-sequence", "quality-to-economics-experiment", "retention-service-moat"],
    "health_wellness": ["expertise-content-commerce", "product-carries-distribution", "category-reframe-and-occasion-expansion", "retention-service-moat"],
    "education_language": ["quality-to-economics-experiment", "community-to-owned-demand", "value-before-offer-sequence", "product-carries-distribution"],
    "gaming_entertainment": ["community-to-owned-demand", "platform-native-live-group-chat", "product-carries-distribution", "value-before-offer-sequence"],
    "commerce_marketplaces": ["b2b-self-service-reorder-engine", "organic-proof-to-paid-amplification", "platform-native-live-group-chat", "retention-service-moat", "targeted-earned-distribution"],
    "beauty_fashion": ["category-reframe-and-occasion-expansion", "platform-native-live-group-chat", "organic-proof-to-paid-amplification", "channel-concentration-reset"],
    "food_beverage": ["category-reframe-and-occasion-expansion", "community-to-owned-demand", "targeted-earned-distribution", "value-before-offer-sequence"],
    "travel_hospitality": ["value-before-offer-sequence", "community-to-owned-demand", "geo-authentic-mention-flywheel", "targeted-earned-distribution"],
    "creator_productivity": ["product-carries-distribution", "community-to-owned-demand", "self-serve-to-expansion", "geo-authentic-mention-flywheel"],
}

LIFECYCLE_BLUEPRINTS = {
    "pre_pmf": ["inspectable-trust-moat", "technical-specification-to-qualified-demand", "targeted-earned-distribution", "value-before-offer-sequence"],
    "launch": ["product-carries-distribution", "paid-dependence-to-owned-intent-reset", "channel-concentration-reset", "community-to-owned-demand"],
    "growth": ["organic-proof-to-paid-amplification", "channel-partner-demand-and-execution-loop", "self-serve-to-expansion", "quality-to-economics-experiment"],
    "mature": ["b2b-self-service-reorder-engine", "professional-authority-to-recurring-contract", "adaptive-vertical-pods", "retention-service-moat", "category-reframe-and-occasion-expansion"],
}

PLATFORM_BLUEPRINTS = {
    "linkedin": ["professional-authority-to-recurring-contract", "technical-specification-to-qualified-demand", "adaptive-vertical-pods", "expertise-content-commerce", "inspectable-trust-moat", "targeted-earned-distribution", "community-to-owned-demand"],
    "youtube": ["long-cycle-proof-assisted-selling", "technical-specification-to-qualified-demand", "expertise-content-commerce", "product-carries-distribution", "value-before-offer-sequence", "organic-proof-to-paid-amplification"],
    "tiktok": ["platform-native-live-group-chat", "product-carries-distribution", "category-reframe-and-occasion-expansion", "organic-proof-to-paid-amplification"],
    "instagram": ["product-carries-distribution", "category-reframe-and-occasion-expansion", "community-to-owned-demand", "organic-proof-to-paid-amplification"],
    "reddit": ["long-cycle-proof-assisted-selling", "technical-specification-to-qualified-demand", "inspectable-trust-moat", "expertise-content-commerce", "geo-authentic-mention-flywheel", "value-before-offer-sequence"],
    "x": ["value-before-offer-sequence", "community-to-owned-demand", "inspectable-trust-moat", "targeted-earned-distribution"],
    "facebook": ["community-to-owned-demand", "platform-native-live-group-chat", "retention-service-moat", "value-before-offer-sequence"],
    "pinterest": ["product-carries-distribution", "category-reframe-and-occasion-expansion", "value-before-offer-sequence", "geo-authentic-mention-flywheel"],
    "bluesky": ["value-before-offer-sequence", "community-to-owned-demand", "inspectable-trust-moat"],
    "mastodon": ["inspectable-trust-moat", "expertise-content-commerce", "community-to-owned-demand"],
    "podcast_rss": ["expertise-content-commerce", "value-before-offer-sequence", "category-reframe-and-occasion-expansion"],
    "owned_blog_newsletter": ["paid-dependence-to-owned-intent-reset", "professional-authority-to-recurring-contract", "long-cycle-proof-assisted-selling", "value-before-offer-sequence", "geo-authentic-mention-flywheel", "expertise-content-commerce", "retention-service-moat", "community-to-owned-demand"],
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Route breakout mechanisms across the 140 segment-market cells and 168 platform-market lanes.")
    parser.add_argument("--sampling", type=Path, default=Path("evidence/v10/gtm-global-organic-signal-sampling-standard-v1.json"))
    parser.add_argument("--distillation", type=Path, default=Path("evidence/v10/gtm-breakout-mechanism-distillation-v1.json"))
    parser.add_argument("--output", type=Path, default=Path("evidence/v10/gtm-breakout-mechanism-routing-v1.json"))
    args = parser.parse_args()
    sampling = json.loads(args.sampling.read_text(encoding="utf-8"))
    distillation = json.loads(args.distillation.read_text(encoding="utf-8"))
    payload = compile_breakout_mechanism_routing(sampling, distillation, vertical_blueprints=VERTICAL_BLUEPRINTS, lifecycle_blueprints=LIFECYCLE_BLUEPRINTS, platform_blueprints=PLATFORM_BLUEPRINTS, compiled_at="2026-08-04T00:00:00-04:00")
    verify_breakout_mechanism_routing(payload)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "segment_market_routes": payload["segment_market_route_count"], "platform_market_routes": payload["platform_market_route_count"], "content_sha256": payload["content_sha256"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
