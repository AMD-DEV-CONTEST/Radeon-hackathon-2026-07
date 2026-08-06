#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.gtm_seed_candidate_normalization import (
    compile_seed_candidate_normalization,
    verify_seed_candidate_normalization,
)


ROOT = Path(__file__).resolve().parents[1]


DECISIONS = [
    {
        "team_id": "clay", "subvertical_id": "b2b.martech_sales_tech.revenue_intelligence", "business_model": "b2b",
        "product": "GTM enrichment and workflow platform", "campaign_or_motion": "community-to-pipeline growth system", "campaign_or_motion_id": "community-pipeline-2025-2026",
        "primary_audience": "GTM operators, revenue leaders, and enterprise buying committees", "observed_start": "2025-12-08", "observed_end": "2026-07-10",
        "company_scale": "mid_market", "lifecycle_state": "growth", "recency_bucket": "three_to_six_months", "outcome_type": "recent_breakout", "quota_market": "north_america",
        "platforms": ["linkedin", "owned_blog_newsletter"], "classification_basis": "Company sources identify a recent $100M ARR growth motion and current marketing system; mixed resource scope remains explicit.",
    },
    {
        "team_id": "mercury", "subvertical_id": "b2b.fintech_regtech.banking", "business_model": "b2b",
        "product": "Business banking platform", "campaign_or_motion": "founder-led annual trust and product narrative", "campaign_or_motion_id": "annual-letter-2025",
        "primary_audience": "Startup founders, finance operators, and business banking decision makers", "observed_start": "2025-02-01", "observed_end": "2026-02-05",
        "company_scale": "mid_market", "lifecycle_state": "growth", "recency_bucket": "six_to_twelve_months", "outcome_type": "durable_repeat", "quota_market": "north_america",
        "platforms": ["owned_blog_newsletter"], "classification_basis": "The company annual letter provides a bounded current operating period; paid and owned resource scope remains mixed.",
    },
    {
        "team_id": "solberg-manufacturing", "subvertical_id": "b2b.industrial_climate.manufacturing", "business_model": "b2b",
        "product": "Industrial filtration and manufacturing catalog", "campaign_or_motion": "digital B2B product discovery modernization", "campaign_or_motion_id": "catalog-modernization-2026",
        "primary_audience": "Industrial buyers, engineers, distributors, and procurement teams", "observed_start": "2025-07-01", "observed_end": "2026-07-01",
        "company_scale": "enterprise_or_mass_brand", "lifecycle_state": "mature", "recency_bucket": "three_to_six_months", "outcome_type": "turnaround", "quota_market": "north_america",
        "platforms": ["owned_blog_newsletter"], "classification_basis": "A dated platform case study identifies industrial catalog modernization and a bounded revenue result; vendor attribution remains noncausal.",
    },
    {
        "team_id": "tally", "subvertical_id": "b2b.b2b_saas.horizontal_saas", "business_model": "b2b",
        "product": "Online form builder", "campaign_or_motion": "freemium product badge and build-in-public loop", "campaign_or_motion_id": "bootstrapped-growth-2025-2026",
        "primary_audience": "Small teams, independent operators, and business software users", "observed_start": "2025-06-10", "observed_end": "2026-04-15",
        "company_scale": "small", "lifecycle_state": "growth", "recency_bucket": "three_to_six_months", "outcome_type": "durable_repeat", "quota_market": "europe_english",
        "platforms": ["owned_blog_newsletter"], "classification_basis": "Three company milestone posts expose a repeated bootstrapped growth motion, team size, product loop, and bounded revenue progression.",
    },
    {
        "team_id": "plausible", "subvertical_id": "b2b.ai_data_infrastructure.analytics_bi", "business_model": "b2b",
        "product": "Privacy-focused web analytics", "campaign_or_motion": "open-source credibility and customer-funded content discovery", "campaign_or_motion_id": "independent-growth-2026",
        "primary_audience": "Privacy-conscious website owners, developers, and analytics buyers", "observed_start": "2026-01-15", "observed_end": "2026-04-29",
        "company_scale": "small", "lifecycle_state": "growth", "recency_bucket": "three_to_six_months", "outcome_type": "durable_repeat", "quota_market": "europe_english",
        "platforms": ["owned_blog_newsletter"], "classification_basis": "Recent company posts explicitly describe independent operation and customer funding; no-paid claim stays primary-source bounded.",
    },
    {
        "team_id": "skimpies", "subvertical_id": "b2c.beauty_fashion.apparel", "business_model": "b2c",
        "product": "Apparel undergarment accessory", "campaign_or_motion": "founder-led TikTok Live community selling", "campaign_or_motion_id": "tiktok-live-2026",
        "primary_audience": "Women seeking an apparel fit and comfort solution", "observed_start": "2025-06-04", "observed_end": "2026-06-04",
        "company_scale": "small", "lifecycle_state": "growth", "recency_bucket": "three_to_six_months", "outcome_type": "recent_breakout", "quota_market": "anz",
        "platforms": ["tiktok", "owned_blog_newsletter"], "classification_basis": "The dated founder case identifies a TikTok Live mechanism and expressly reports no paid ads; it remains a vendor-hosted self-report.",
    },
    {
        "team_id": "fly-by-jing", "subvertical_id": "b2c.food_beverage.consumer_packaged_goods", "business_model": "b2c",
        "product": "Chili crisp and packaged foods", "campaign_or_motion": "founder story to retail distribution system", "campaign_or_motion_id": "retail-scale-2026",
        "primary_audience": "Flavor-seeking food consumers and retail category buyers", "observed_start": "2025-06-02", "observed_end": "2026-06-02",
        "company_scale": "mid_market", "lifecycle_state": "growth", "recency_bucket": "three_to_six_months", "outcome_type": "recent_breakout", "quota_market": "north_america",
        "platforms": ["owned_blog_newsletter"], "classification_basis": "A dated founder case identifies Kickstarter-to-retail progression and current distribution scale; resource scope is low-budget, not zero-budget.",
    },
    {
        "team_id": "therabody", "subvertical_id": "b2c.health_wellness.fitness", "business_model": "b2c",
        "product": "Percussive recovery devices", "campaign_or_motion": "inventor proof to category creation and retail scale", "campaign_or_motion_id": "category-proof-2026",
        "primary_audience": "Athletes, recovery consumers, practitioners, and retail buyers", "observed_start": "2025-06-16", "observed_end": "2026-06-16",
        "company_scale": "enterprise_or_mass_brand", "lifecycle_state": "mature", "recency_bucket": "three_to_six_months", "outcome_type": "durable_repeat", "quota_market": "north_america",
        "platforms": ["owned_blog_newsletter"], "classification_basis": "The dated founder case connects inventor proof, category formation, and unit scale; total media and channel contribution remain incomplete.",
    },
    {
        "team_id": "beehiiv", "subvertical_id": "b2c.creator_productivity.creator_tools", "business_model": "b2c",
        "product": "Newsletter publishing platform", "campaign_or_motion": "operator transparency and creator ecosystem growth", "campaign_or_motion_id": "company-story-2025",
        "primary_audience": "Newsletter creators, publishers, and independent media operators", "observed_start": "2022-11-17", "observed_end": "2025-11-19",
        "company_scale": "mid_market", "lifecycle_state": "growth", "recency_bucket": "six_to_twelve_months", "outcome_type": "durable_repeat", "quota_market": "north_america",
        "platforms": ["owned_blog_newsletter"], "classification_basis": "Company-authored operating chapters expose a multi-year product and distribution progression; current paid/organic separation remains incomplete.",
    },
    {
        "team_id": "lulu-and-georgia", "subvertical_id": "b2c.commerce_marketplaces.home_property", "business_model": "b2c",
        "product": "Home furnishings and decor", "campaign_or_motion": "editorial taste and disciplined debt-free brand growth", "campaign_or_motion_id": "home-brand-growth-2026",
        "primary_audience": "Design-conscious home shoppers and interior-design buyers", "observed_start": "2025-06-23", "observed_end": "2026-06-23",
        "company_scale": "enterprise_or_mass_brand", "lifecycle_state": "mature", "recency_bucket": "three_to_six_months", "outcome_type": "durable_repeat", "quota_market": "north_america",
        "platforms": ["owned_blog_newsletter"], "classification_basis": "The dated founder case reports debt-free scale and current growth; external investment and paid-media absence are not conflated.",
    },
    {
        "team_id": "437", "subvertical_id": "b2c.beauty_fashion.apparel", "business_model": "b2c",
        "product": "Activewear", "campaign_or_motion": "simplified assortment and influencer-led growth", "campaign_or_motion_id": "simplify-scale-2026",
        "primary_audience": "Style-conscious activewear consumers and creator-influenced shoppers", "observed_start": "2025-06-11", "observed_end": "2026-06-11",
        "company_scale": "small", "lifecycle_state": "growth", "recency_bucket": "three_to_six_months", "outcome_type": "recent_breakout", "quota_market": "north_america",
        "platforms": ["instagram", "owned_blog_newsletter"], "classification_basis": "A dated founder case reports bootstrapped eight-figure scale, assortment simplification, and influencer use; it remains platform-hosted self-report evidence.",
    },
    {
        "team_id": "candier", "subvertical_id": "b2c.food_beverage.consumer_packaged_goods", "business_model": "b2c",
        "product": "Giftable scented candles", "campaign_or_motion": "founder cold outreach to national retail distribution", "campaign_or_motion_id": "retail-outreach-2026",
        "primary_audience": "Gift shoppers, lifestyle consumers, and national retail category buyers", "observed_start": "2025-05-14", "observed_end": "2026-05-14",
        "company_scale": "small", "lifecycle_state": "growth", "recency_bucket": "three_to_six_months", "outcome_type": "recent_breakout", "quota_market": "north_america",
        "platforms": ["owned_blog_newsletter"], "classification_basis": "A dated founder case identifies direct retailer outreach and a bounded revenue milestone; PR-firm absence is not treated as zero total spend.",
    },
    {
        "team_id": "pashion-footwear", "subvertical_id": "b2c.beauty_fashion.apparel", "business_model": "b2c",
        "product": "Convertible high-heel footwear", "campaign_or_motion": "inventor problem story and product demonstration", "campaign_or_motion_id": "convertible-footwear-growth-2025",
        "primary_audience": "Occasion footwear buyers seeking comfort and versatility", "observed_start": "2024-11-06", "observed_end": "2025-11-06",
        "company_scale": "small", "lifecycle_state": "growth", "recency_bucket": "six_to_twelve_months", "outcome_type": "durable_repeat", "quota_market": "north_america",
        "platforms": ["owned_blog_newsletter"], "classification_basis": "A dated founder case links an inventor problem, demonstrable product, and eight-figure scale; the zero-paid statement stays primary-source bounded.",
    },
    {
        "team_id": "province-of-canada", "subvertical_id": "b2c.beauty_fashion.apparel", "business_model": "b2c",
        "product": "Made-in-Canada apparel and home goods", "campaign_or_motion": "daily organic content and local identity community", "campaign_or_motion_id": "organic-growth-2025",
        "primary_audience": "Consumers who value Canadian-made products and local brand identity", "observed_start": "2020-10-14", "observed_end": "2025-10-14",
        "company_scale": "small", "lifecycle_state": "growth", "recency_bucket": "six_to_twelve_months", "outcome_type": "durable_repeat", "quota_market": "north_america",
        "platforms": ["instagram", "owned_blog_newsletter"], "classification_basis": "A dated founder case reports five years of organic content and revenue progression; unpaid founder labor and platform dependence remain explicit costs.",
    },
    {
        "team_id": "shock-surplus", "subvertical_id": "b2c.commerce_marketplaces.general_ecommerce", "business_model": "b2c",
        "product": "Automotive suspension parts ecommerce", "campaign_or_motion": "expert fitment content and profit-disciplined commerce", "campaign_or_motion_id": "fitment-content-2026",
        "primary_audience": "Automotive enthusiasts and buyers needing reliable part fitment", "observed_start": "2025-06-09", "observed_end": "2026-06-09",
        "company_scale": "small", "lifecycle_state": "growth", "recency_bucket": "three_to_six_months", "outcome_type": "durable_repeat", "quota_market": "north_america",
        "platforms": ["youtube", "owned_blog_newsletter"], "classification_basis": "A dated founder case identifies an information-gap content system and eight-figure business; resource efficiency is disclosed without assuming zero spend.",
    },
]


def main() -> int:
    seed = json.loads((ROOT / "evidence/v10/gtm-breakout-quality-team-seed-v1.json").read_text(encoding="utf-8"))
    capture = json.loads((ROOT / "evidence/v10/gtm-public-case-source-capture-v1.json").read_text(encoding="utf-8"))
    payload = compile_seed_candidate_normalization(seed, capture, DECISIONS)
    verify_seed_candidate_normalization(payload)
    output = ROOT / "data/gtm_case_funnel_v2/candidates.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(output, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "output": str(output),
        "candidate_record_count": payload["candidate_count"],
        "quota_eligible_candidate_count": payload["quota_eligible_candidate_count"],
        "represented_subvertical_count": payload["distinct_subvertical_count"],
        "quota_eligible_distinct_subvertical_count": payload["quota_eligible_distinct_subvertical_count"],
        "content_sha256": payload["content_sha256"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
