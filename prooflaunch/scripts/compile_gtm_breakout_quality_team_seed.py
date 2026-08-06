#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from prooflaunch_remix.gtm_breakout_quality_team_seed import (
    compile_breakout_quality_team_seed,
    verify_breakout_quality_team_seed,
)


CASES = [
    {
        "team_id": "clay",
        "team_name": "Clay",
        "business_model": "b2b",
        "cold_start_budget_tier": "mixed_budget",
        "cold_start_budget_window": "current motion discloses events and billboards; cold-start spend is not quantified",
        "transferable_mechanism_tags": ["community-to-pipeline", "education-and-certification", "executive-distribution", "partner-ecosystem", "self-serve-to-enterprise"],
        "promotion_status": "mechanism_distillation_ready",
        "evidence_grade": "primary_company_self_report",
        "reported_outcomes": [
            "$100M ARR after growing from $1M in roughly two years",
            "enterprise NRR above 200% and no reported enterprise churn",
            "enterprise ARR roughly tripled in nine months",
            "6M organic LinkedIn impressions in one quarter and more than half of pipeline attributed to marketing",
            "about 60% self-serve and 40% sales-led revenue",
        ],
        "observable_mechanism": (
            "User education, certifications, clubs, partner agencies, executive distribution, events, and demand-capture "
            "programs form a community-to-pipeline loop; the company explicitly reports no cold outbound in the current motion."
        ),
        "evidence_dimensions": {
            "hard_outcome": "verified",
            "current_operation": "verified",
            "recent_three_to_six_month_breakout": "verified",
            "channel_mechanism": "verified",
            "retention_or_repeatability": "verified",
            "paid_organic_resource_scope": "partial",
        },
        "blocking_caveat": "Events and billboards are disclosed; total spend and organic-versus-paid pipeline shares are incomplete.",
        "sources": [
            {"url": "https://www.clay.com/blog/100m-arr", "source_type": "official_company_post", "published": "2025-12-08"},
            {"url": "https://www.clay.com/blog/behind-the-scenes-of-clays-marketing-and-growth", "source_type": "official_company_post", "published": "2026-07-10"},
        ],
    },
    {
        "team_id": "learna-codeway",
        "team_name": "Learna / Codeway",
        "business_model": "b2c",
        "cold_start_budget_tier": "undisclosed",
        "cold_start_budget_window": "18-month outcome window; acquisition spend is not disclosed",
        "transferable_mechanism_tags": ["quality-to-business-metric", "production-ab-test", "multimodal-retention-optimization"],
        "promotion_status": "mechanism_distillation_ready",
        "evidence_grade": "official_vendor_case_study",
        "reported_outcomes": [
            "45M users, 7M monthly active users, and $90M ARR in 18 months",
            "production A/B test reported 9% higher trial conversion and 10% higher customer lifetime value",
        ],
        "observable_mechanism": (
            "Treat a core multimodal quality variable as a business lever, run a production experiment, and connect model/output "
            "quality directly to trial conversion and lifetime value instead of subjective preference alone."
        ),
        "evidence_dimensions": {
            "hard_outcome": "verified",
            "current_operation": "verified",
            "recent_three_to_six_month_breakout": "verified",
            "channel_mechanism": "partial",
            "retention_or_repeatability": "verified",
            "paid_organic_resource_scope": "missing",
        },
        "blocking_caveat": "The source is a vendor case study; acquisition channels, media spend, cohort retention, and independent corroboration are absent.",
        "sources": [
            {"url": "https://elevenlabs.io/blog/webinar-recap-how-learna-scales-voice-learning-with-elevenlabs", "source_type": "official_vendor_case_study", "published": "2026-04-01"}
        ],
    },
    {
        "team_id": "gamma",
        "team_name": "Gamma",
        "business_model": "mixed",
        "cold_start_budget_tier": "capital_efficient",
        "cold_start_budget_window": "reported profitable growth to $100M ARR with $23M initial funding and about 50 employees",
        "transferable_mechanism_tags": ["lean-team", "artifact-creation-loop", "product-led-utility"],
        "promotion_status": "outcome_seed_only",
        "evidence_grade": "primary_company_self_report",
        "reported_outcomes": [
            "$100M ARR while profitable for two years",
            "70M users, 400M created artifacts, and more than 1M artifacts created daily",
            "about 50 employees and $23M of initial funding reported before the milestone",
        ],
        "observable_mechanism": "Lean-team, product-utility and artifact-creation flywheel is visible, but acquisition-channel causality is not.",
        "evidence_dimensions": {
            "hard_outcome": "verified",
            "current_operation": "verified",
            "recent_three_to_six_month_breakout": "partial",
            "channel_mechanism": "partial",
            "retention_or_repeatability": "partial",
            "paid_organic_resource_scope": "partial",
        },
        "blocking_caveat": "No paid-versus-organic split, cohort retention, or independent revenue corroboration in the source.",
        "sources": [
            {"url": "https://gamma.app/insights/how-we-built-a-usd100m-business-differently", "source_type": "official_company_post", "published": "2025-11-10"}
        ],
    },
    {
        "team_id": "lovable",
        "team_name": "Lovable",
        "business_model": "mixed",
        "cold_start_budget_tier": "undisclosed",
        "cold_start_budget_window": "first-year ARR and production velocity disclosed; acquisition spend is not",
        "transferable_mechanism_tags": ["builder-ecosystem", "creation-loop", "output-as-distribution"],
        "promotion_status": "outcome_seed_only",
        "evidence_grade": "primary_company_self_report",
        "reported_outcomes": [
            "$100M ARR eight months after the first $1M and $200M ARR four months later",
            "100,000 projects built daily and 5M daily visits to Lovable-built products",
        ],
        "observable_mechanism": "Output velocity and builder ecosystem are visible, but the acquisition and retention mechanism remains under-audited.",
        "evidence_dimensions": {
            "hard_outcome": "verified",
            "current_operation": "verified",
            "recent_three_to_six_month_breakout": "partial",
            "channel_mechanism": "partial",
            "retention_or_repeatability": "partial",
            "paid_organic_resource_scope": "missing",
        },
        "blocking_caveat": "ARR and usage are company self-reports; paid acquisition, cohorts, retention, and channel attribution are missing.",
        "sources": [
            {"url": "https://lovable.dev/blog/agent", "source_type": "official_company_post", "published": "2025-07-23"},
            {"url": "https://lovable.dev/blog/one-year-of-lovable", "source_type": "official_company_post", "published": "2025-11-18"},
        ],
    },
    {
        "team_id": "vanta",
        "team_name": "Vanta",
        "business_model": "b2b",
        "cold_start_budget_tier": "undisclosed",
        "cold_start_budget_window": "ARR acceleration disclosed; acquisition resources are not",
        "transferable_mechanism_tags": ["category-trust", "customer-expansion"],
        "promotion_status": "outcome_seed_only",
        "evidence_grade": "primary_company_self_report",
        "reported_outcomes": [
            "$300M ARR in April 2026 after moving from $200M in nine months",
            "company reports growth rate increasing in each of the preceding four quarters",
        ],
        "observable_mechanism": "Compounding customer expansion is asserted, but the source does not expose an auditable distribution mechanism.",
        "evidence_dimensions": {
            "hard_outcome": "verified",
            "current_operation": "verified",
            "recent_three_to_six_month_breakout": "verified",
            "channel_mechanism": "missing",
            "retention_or_repeatability": "partial",
            "paid_organic_resource_scope": "missing",
        },
        "blocking_caveat": "No channel attribution, retention metric, paid/organic split, or independent revenue corroboration in the source.",
        "sources": [
            {"url": "https://www.vanta.com/resources/vanta-crosses-300m-in-arr-as-growth-accelerates", "source_type": "official_company_post", "published": "2026-04-29"}
        ],
    },
    {
        "team_id": "duolingo",
        "team_name": "Duolingo",
        "business_model": "b2c",
        "cold_start_budget_tier": "mature_scaled",
        "cold_start_budget_window": "public-company scale; not a cold-start comparator",
        "transferable_mechanism_tags": ["engagement-compounding", "daily-use-loop"],
        "promotion_status": "outcome_seed_only",
        "evidence_grade": "public_company_investor_report",
        "reported_outcomes": [
            "surpassed 50M daily active users in 2025",
            "Q3 2025 reported 36% year-over-year DAU growth alongside revenue growth",
        ],
        "observable_mechanism": "Public-company growth and engagement are strong controls, but this source set does not isolate the creative or organic GTM mechanism.",
        "evidence_dimensions": {
            "hard_outcome": "verified",
            "current_operation": "verified",
            "recent_three_to_six_month_breakout": "partial",
            "channel_mechanism": "missing",
            "retention_or_repeatability": "partial",
            "paid_organic_resource_scope": "missing",
        },
        "blocking_caveat": "Established public-company scale is not comparable to a zero-budget startup; channel and spend attribution require separate filings and experiments.",
        "sources": [
            {"url": "https://investors.duolingo.com/static-files/68ebeff8-63c8-46a8-a88f-73b93c9dbdb3", "source_type": "official_investor_release", "published": "2025-11-05"},
            {"url": "https://investors.duolingo.com/node/11641/pdf", "source_type": "official_investor_report", "published": "2026-02-26"},
        ],
    },
    {
        "team_id": "cursor",
        "team_name": "Cursor",
        "business_model": "mixed",
        "cold_start_budget_tier": "undisclosed",
        "cold_start_budget_window": "outcome disclosed outside the recent window; channel resources are absent",
        "transferable_mechanism_tags": ["workflow-embedded-product-led-adoption"],
        "promotion_status": "outcome_seed_only",
        "evidence_grade": "primary_company_self_report",
        "reported_outcomes": ["more than $500M ARR and use by over half of the Fortune 500 as reported in June 2025"],
        "observable_mechanism": "Strong product demand is visible; recent channel, retention, efficiency, and creative mechanisms are not exposed by this source.",
        "evidence_dimensions": {
            "hard_outcome": "verified",
            "current_operation": "partial",
            "recent_three_to_six_month_breakout": "missing",
            "channel_mechanism": "missing",
            "retention_or_repeatability": "partial",
            "paid_organic_resource_scope": "missing",
        },
        "blocking_caveat": "The outcome source is outside the recent 3–6 month window and supplies no acquisition, retention, or paid/organic evidence.",
        "sources": [
            {"url": "https://cursor.com/en-US/blog/series-c", "source_type": "official_company_post", "published": "2025-06-06"}
        ],
    },
    {
        "team_id": "tally",
        "team_name": "Tally",
        "business_model": "b2b",
        "cold_start_budget_tier": "cold_start_low_budget",
        "cold_start_budget_window": "bootstrapped from launch; five years to $5M ARR with an 11-person team",
        "reported_zero_paid_media": False,
        "transferable_mechanism_tags": ["generous-freemium", "product-badge-loop", "word-of-mouth", "build-in-public", "community-co-creation", "geo-ai-discovery"],
        "promotion_status": "mechanism_distillation_ready",
        "evidence_grade": "primary_company_self_report",
        "reported_outcomes": [
            "$5M ARR by April 2026 with an 11-person, fully bootstrapped team",
            "$4M ARR by October 2025 after reaching $2M in February and $3M in June 2025",
            "more than 800,000 users reported at the $3M milestone",
            "about 2% of users upgrade, while free forms carry a Made with Tally distribution badge",
        ],
        "observable_mechanism": (
            "A generous free product removes time-to-value friction; each published form carries distribution, community feedback "
            "co-builds the roadmap, public operating updates create trust, and authentic UGC improves search and AI discovery."
        ),
        "evidence_dimensions": {
            "hard_outcome": "verified",
            "current_operation": "verified",
            "recent_three_to_six_month_breakout": "verified",
            "channel_mechanism": "verified",
            "retention_or_repeatability": "partial",
            "paid_organic_resource_scope": "partial",
        },
        "blocking_caveat": "Bootstrapping and low-budget operation are explicit, but full media spend, cohort retention, CAC, and independent revenue corroboration remain missing.",
        "sources": [
            {"url": "https://blog.tally.so/the-road-from-4m-to-5m-arr/", "source_type": "official_company_post", "published": "2026-04-15"},
            {"url": "https://blog.tally.so/how-we-grew-tally-to-4m-arr-fully-bootstrapped/", "source_type": "official_company_post", "published": "2025-10-15"},
            {"url": "https://blog.tally.so/from-2-to-3m-arr-how-we-bootstrapped-tally-with-a-tiny-team/", "source_type": "official_company_post", "published": "2025-06-10"},
        ],
    },
    {
        "team_id": "plausible",
        "team_name": "Plausible Analytics",
        "business_model": "b2b",
        "cold_start_budget_tier": "cold_start_zero_paid",
        "cold_start_budget_window": "company reports no paid advertising and subscriber-funded operation",
        "reported_zero_paid_media": True,
        "transferable_mechanism_tags": ["open-source-credibility", "privacy-positioning", "content-discovery", "word-of-mouth", "customer-funded-focus"],
        "promotion_status": "mechanism_distillation_ready",
        "evidence_grade": "primary_company_self_report",
        "reported_outcomes": [
            "$1M ARR in three years with a four-person bootstrapped team and more than 7,000 paying subscribers",
            "a ten-person core team remained sustainably profitable in 2026",
            "the company reports that growth came from content, product use, and word of mouth without ads",
        ],
        "observable_mechanism": (
            "A sharp privacy promise, inspectable open-source proof, product usefulness, educational content, and customer advocacy "
            "compound without retargeting, aggressive funnels, sales calls, or advertising."
        ),
        "evidence_dimensions": {
            "hard_outcome": "verified",
            "current_operation": "verified",
            "recent_three_to_six_month_breakout": "partial",
            "channel_mechanism": "verified",
            "retention_or_repeatability": "partial",
            "paid_organic_resource_scope": "verified",
        },
        "blocking_caveat": "Zero-paid and revenue statements are company self-reports; recent breakout velocity, cohort retention, and independent financial corroboration are incomplete.",
        "sources": [
            {"url": "https://plausible.io/blog/open-source-saas", "source_type": "official_company_post", "published": "2022-06-22"},
            {"url": "https://plausible.io/blog/customers-not-investors", "source_type": "official_company_post", "published": "2026-01-15"},
            {"url": "https://plausible.io/blog/ignore-startup-advice", "source_type": "official_company_post", "published": "2026-04-29"},
        ],
    },
    {
        "team_id": "province-of-canada",
        "team_name": "Province of Canada",
        "business_model": "b2c",
        "cold_start_budget_tier": "cold_start_zero_paid",
        "cold_start_budget_window": "founder reports no ad spend during the first five years",
        "reported_zero_paid_media": True,
        "transferable_mechanism_tags": ["daily-value-content", "identity-community", "owned-email-audience", "organic-before-paid", "local-retail-community"],
        "promotion_status": "mechanism_distillation_ready",
        "evidence_grade": "official_platform_founder_case_study",
        "reported_outcomes": [
            "grew a $1,500 starting investment to months above $100,000 in revenue",
            "founder reports the first five years were built without ad spend",
            "daily non-product tweets and emails built a Canadian identity and community before paid amplification",
        ],
        "observable_mechanism": (
            "Publish daily identity-reinforcing value before asking for a sale, convert social discovery into an owned email relationship, "
            "and introduce tightly measured paid amplification only after organic demand and community trust exist."
        ),
        "evidence_dimensions": {
            "hard_outcome": "verified",
            "current_operation": "verified",
            "recent_three_to_six_month_breakout": "partial",
            "channel_mechanism": "verified",
            "retention_or_repeatability": "partial",
            "paid_organic_resource_scope": "verified",
        },
        "blocking_caveat": "The case is a Shopify/founder report, not audited financial evidence; five-year growth is durable but not a 6–12 month breakout.",
        "sources": [
            {"url": "https://www.shopify.com/sg/blog/province-of-canada-organic-growth-playbook", "source_type": "official_platform_founder_case_study", "published": "2025-10-14"}
        ],
    },
    {
        "team_id": "pashion-footwear",
        "team_name": "Pashion Footwear",
        "business_model": "b2c",
        "cold_start_budget_tier": "cold_start_zero_paid",
        "cold_start_budget_window": "Shopify founder case study reports an eight-figure brand with zero ad spend",
        "reported_zero_paid_media": True,
        "transferable_mechanism_tags": ["founder-led-short-video", "product-demonstration", "problem-origin-story", "visual-transformation"],
        "promotion_status": "mechanism_distillation_ready",
        "evidence_grade": "official_platform_founder_case_study",
        "reported_outcomes": [
            "reported eight-figure company with 19% profit margins and zero ad spend",
            "founder-led TikTok audience approached one million followers",
        ],
        "observable_mechanism": (
            "A visually legible product transformation, founder problem-origin story, and repeated short-form demonstration make the "
            "product itself the content hook and distribution object."
        ),
        "evidence_dimensions": {
            "hard_outcome": "verified",
            "current_operation": "verified",
            "recent_three_to_six_month_breakout": "partial",
            "channel_mechanism": "verified",
            "retention_or_repeatability": "partial",
            "paid_organic_resource_scope": "verified",
        },
        "blocking_caveat": "Shopify and founder report the outcomes; revenue window, repeat purchase, cohort retention, and independent spend audit are absent.",
        "sources": [
            {"url": "https://www.shopify.com/ng/blog/pashion-footwear-turning-pain-into-profits", "source_type": "official_platform_founder_case_study", "published": "2025-11-06"}
        ],
    },
    {
        "team_id": "beehiiv",
        "team_name": "beehiiv",
        "business_model": "mixed",
        "cold_start_budget_tier": "mixed_budget",
        "cold_start_budget_window": "fast early organic/product growth followed by sales and brand-awareness investment",
        "reported_zero_paid_media": False,
        "transferable_mechanism_tags": ["owned-audience-infrastructure", "creator-success-loop", "public-operating-story", "integrated-monetization", "product-release-moments"],
        "promotion_status": "mechanism_distillation_ready",
        "evidence_grade": "primary_company_self_report",
        "reported_outcomes": [
            "approached $1M ARR after one year with average 55% monthly growth",
            "$20M ARR in July 2025 and $32M annualized revenue by November 2025",
            "more than 3B emails per month and over $45M of reported platform creator earnings",
        ],
        "observable_mechanism": (
            "Founder credibility from Morning Brew, public operating narratives, integrated referral/analytics/monetization primitives, "
            "creator success stories, and concentrated release moments form an owned-audience growth system."
        ),
        "evidence_dimensions": {
            "hard_outcome": "verified",
            "current_operation": "verified",
            "recent_three_to_six_month_breakout": "partial",
            "channel_mechanism": "verified",
            "retention_or_repeatability": "partial",
            "paid_organic_resource_scope": "partial",
        },
        "blocking_caveat": "Later brand awareness and sales investment are disclosed, but channel-level spend, retention, CAC, and independent revenue verification remain incomplete.",
        "sources": [
            {"url": "https://www.beehiiv.com/blog/the-beehiiv-story-chapter-1", "source_type": "official_company_post", "published": "2022-11-17"},
            {"url": "https://www.beehiiv.com/blog/the-beehiiv-story-chapter-4", "source_type": "official_company_post", "published": "2025-11-19"},
        ],
    },
    {
        "team_id": "buffer",
        "team_name": "Buffer",
        "business_model": "b2b",
        "cold_start_budget_tier": "capital_efficient",
        "cold_start_budget_window": "mature transparent operation; current cold-start comparability is limited",
        "reported_zero_paid_media": False,
        "transferable_mechanism_tags": ["radical-transparency", "continuous-compounding", "customer-experience-iteration", "public-metrics"],
        "promotion_status": "outcome_seed_only",
        "evidence_grade": "primary_company_financial_disclosure",
        "reported_outcomes": [
            "$23.37M ARR, 69,760 customers, 74 staff, and positive monthly net income in December 2025",
            "$22.46M full-year 2025 revenue, up 31% year over year, after twelve consecutive months of revenue growth",
        ],
        "observable_mechanism": "Transparent monthly metrics and repeated customer-experience iteration are visible, but channel causality is not isolated.",
        "evidence_dimensions": {
            "hard_outcome": "verified",
            "current_operation": "verified",
            "recent_three_to_six_month_breakout": "partial",
            "channel_mechanism": "partial",
            "retention_or_repeatability": "partial",
            "paid_organic_resource_scope": "partial",
        },
        "blocking_caveat": "The financial disclosure is unusually strong, but acquisition mix, spend, cohort retention, and a specific breakout mechanism remain incomplete.",
        "sources": [
            {"url": "https://buffer.com/shareholders/december-2025", "source_type": "official_company_financial_disclosure", "published": "2026-01-20"},
            {"url": "https://buffer.com/shareholders", "source_type": "official_company_metrics_archive", "published": "continuous"},
        ],
    },
    {
        "team_id": "mercury",
        "team_name": "Mercury",
        "business_model": "b2b",
        "cold_start_budget_tier": "mixed_budget",
        "cold_start_budget_window": "scaled, funded financial platform; useful for adaptive GTM pods rather than zero-budget transfer",
        "reported_zero_paid_media": False,
        "transferable_mechanism_tags": ["multi-product-expansion", "cross-functional-gtm-pods", "learn-before-scale", "vertical-context-adaptation", "unit-economics-gating"],
        "promotion_status": "mechanism_distillation_ready",
        "evidence_grade": "primary_company_self_report",
        "reported_outcomes": [
            "$650M annualized revenue by September 2025 with three consecutive years of GAAP profitability",
            "customer growth reached 50% year over year and transaction volume reached $248B, up 59%",
            "more than 300,000 customers, NPS 73.8, and 73% of new customers outside AI or tech startups",
        ],
        "observable_mechanism": (
            "Cross-functional pods listen before scaling, adapt the same horizontal product to vertical decision contexts, test channel "
            "and creative differences, and expand only where acquisition cost, depth of use, and lifetime value work together."
        ),
        "evidence_dimensions": {
            "hard_outcome": "verified",
            "current_operation": "verified",
            "recent_three_to_six_month_breakout": "partial",
            "channel_mechanism": "verified",
            "retention_or_repeatability": "verified",
            "paid_organic_resource_scope": "partial",
        },
        "blocking_caveat": "The company describes its decision system but does not publish channel spend, CAC, cohort retention, or independent attribution by vertical.",
        "sources": [
            {"url": "https://mercury.com/blog/annual-letter-2025", "source_type": "official_company_annual_letter", "published": "2026-02-05"}
        ],
    },
    {
        "team_id": "canva",
        "team_name": "Canva",
        "business_model": "mixed",
        "cold_start_budget_tier": "mature_scaled",
        "cold_start_budget_window": "global scaled platform; not a cold-start resource comparator",
        "reported_zero_paid_media": False,
        "transferable_mechanism_tags": ["template-ecosystem", "collaborative-artifact-loop", "community-scale", "multi-format-expansion"],
        "promotion_status": "outcome_seed_only",
        "evidence_grade": "primary_company_self_report",
        "reported_outcomes": ["$3.5B revenue and 260M monthly users reported for 2025"],
        "observable_mechanism": "Community, reusable design systems, collaboration, and multi-format creation are visible, but current GTM attribution is not.",
        "evidence_dimensions": {
            "hard_outcome": "verified",
            "current_operation": "verified",
            "recent_three_to_six_month_breakout": "partial",
            "channel_mechanism": "partial",
            "retention_or_repeatability": "partial",
            "paid_organic_resource_scope": "missing",
        },
        "blocking_caveat": "Mature platform scale, acquisition mix, retention cohorts, and resource scope make direct cold-start transfer unsafe without further decomposition.",
        "sources": [
            {"url": "https://www.canva.com/newsroom/news/canva-2025-wrap/", "source_type": "official_company_year_review", "published": "2025-12-18"}
        ],
    },
    {
        "team_id": "lulu-and-georgia",
        "team_name": "Lulu and Georgia",
        "business_model": "b2c",
        "cold_start_budget_tier": "capital_efficient",
        "cold_start_budget_window": "bootstrapped with no debt or outside investment; media spend is not fully disclosed",
        "reported_zero_paid_media": False,
        "transferable_mechanism_tags": ["service-led-retention", "inventory-discipline", "repeat-purchase", "profitable-compounding"],
        "promotion_status": "mechanism_distillation_ready",
        "evidence_grade": "official_platform_founder_case_study",
        "reported_outcomes": [
            "bootstrapped nine-figure home brand growing 20% to 30% annually",
            "reported 52% repeat-purchase rate, roughly double the stated industry average",
            "built without debt or outside investment",
        ],
        "observable_mechanism": "Free design service, disciplined inventory bets, and customer experience turn a low-frequency home category into unusually strong repeat purchasing.",
        "evidence_dimensions": {
            "hard_outcome": "verified", "current_operation": "verified", "recent_three_to_six_month_breakout": "partial",
            "channel_mechanism": "partial", "retention_or_repeatability": "verified", "paid_organic_resource_scope": "partial"
        },
        "blocking_caveat": "The source is a Shopify/founder case study; channel mix, media spend, cohort definition, and audited revenue remain undisclosed.",
        "sources": [{"url": "https://www.shopify.com/au/blog/lulu-and-georgia-from-side-hustle-to-home-goods-empire", "source_type": "official_platform_founder_case_study", "published": "2026-06-23"}],
    },
    {
        "team_id": "437",
        "team_name": "437",
        "business_model": "b2c",
        "cold_start_budget_tier": "cold_start_low_budget",
        "cold_start_budget_window": "turnaround reached eight figures within six months after canceling agencies and narrowing to two channels",
        "reported_zero_paid_media": False,
        "transferable_mechanism_tags": ["channel-focus", "organic-social", "committed-ambassadors", "creative-constraint", "inventory-reframing"],
        "promotion_status": "mechanism_distillation_ready",
        "evidence_grade": "official_platform_founder_case_study",
        "reported_outcomes": [
            "bootstrapped activewear brand reached eight figures within six months of simplifying",
            "focused on owned organic social and a small set of repeated influencer relationships",
            "a 12-in-1 product reframing generated millions over subsequent years",
        ],
        "observable_mechanism": "Cut channel and agency sprawl, reclaim in-house craft, turn an existing product constraint into demonstrable versatility, and favor a few committed ambassadors over one-off posts.",
        "evidence_dimensions": {
            "hard_outcome": "verified", "current_operation": "verified", "recent_three_to_six_month_breakout": "verified",
            "channel_mechanism": "verified", "retention_or_repeatability": "partial", "paid_organic_resource_scope": "partial"
        },
        "blocking_caveat": "The six-month turnaround is founder-reported; channel spend, margin, cohort retention, and influencer compensation are not fully quantified.",
        "sources": [{"url": "https://www.shopify.com/blog/437-simplify-to-scale", "source_type": "official_platform_founder_case_study", "published": "2026-06-11"}],
    },
    {
        "team_id": "therabody",
        "team_name": "Therabody",
        "business_model": "b2c",
        "cold_start_budget_tier": "cold_start_low_budget",
        "cold_start_budget_window": "eight-year one-to-one credibility phase before scaled distribution",
        "reported_zero_paid_media": False,
        "transferable_mechanism_tags": ["founder-origin-proof", "expert-seeding", "one-to-one-credibility", "category-naming", "feedback-led-product"],
        "promotion_status": "mechanism_distillation_ready",
        "evidence_grade": "official_platform_founder_case_study",
        "reported_outcomes": ["more than 6.5M Theragun devices sold", "reported number-one position in percussive therapy", "five prototypes and eight years of credibility-building before scale"],
        "observable_mechanism": "Solve the founder's real problem, iterate with practitioners, seed one credible expert at a time, and let a distinctive product action become the category verb.",
        "evidence_dimensions": {
            "hard_outcome": "verified", "current_operation": "verified", "recent_three_to_six_month_breakout": "partial",
            "channel_mechanism": "verified", "retention_or_repeatability": "verified", "paid_organic_resource_scope": "partial"
        },
        "blocking_caveat": "Long-horizon category creation is not a rapid cold-start precedent; historical spend, sell-through, and independent category-share data are incomplete.",
        "sources": [{"url": "https://www.shopify.com/au/blog/therabody-garage-experiment-to-global-recovery-brand", "source_type": "official_platform_founder_case_study", "published": "2026-06-16"}],
    },
    {
        "team_id": "fly-by-jing",
        "team_name": "Fly By Jing",
        "business_model": "b2c",
        "cold_start_budget_tier": "cold_start_low_budget",
        "cold_start_budget_window": "supper-club and Kickstarter origin before national retail scale",
        "reported_zero_paid_media": False,
        "transferable_mechanism_tags": ["category-education", "cultural-identity", "occasion-expansion", "community-defense", "sampling-and-popups"],
        "promotion_status": "mechanism_distillation_ready",
        "evidence_grade": "official_platform_founder_case_study",
        "reported_outcomes": ["eight-figure brand distributed in 12,000 U.S. stores", "one of the most-funded food projects on Kickstarter", "national distribution including Target, Walmart, and Whole Foods"],
        "observable_mechanism": "Turn cultural undervaluation into a sharp category thesis, prove taste through supper clubs and sampling, and expand unfamiliar usage into familiar occasions rather than lecturing the audience.",
        "evidence_dimensions": {
            "hard_outcome": "verified", "current_operation": "verified", "recent_three_to_six_month_breakout": "partial",
            "channel_mechanism": "verified", "retention_or_repeatability": "partial", "paid_organic_resource_scope": "partial"
        },
        "blocking_caveat": "The case exposes category and distribution strategy but not paid spend, repeat purchase, margin, or channel incrementality.",
        "sources": [{"url": "https://www.shopify.com/blog/fly-by-jing-recipe-for-success", "source_type": "official_platform_founder_case_study", "published": "2026-06-02"}],
    },
    {
        "team_id": "shock-surplus",
        "team_name": "ShockSurplus",
        "business_model": "mixed",
        "cold_start_budget_tier": "capital_efficient",
        "cold_start_budget_window": "bootstrapped education-first business; later boosts proven organic winners",
        "reported_zero_paid_media": False,
        "transferable_mechanism_tags": ["expert-content-moat", "long-consideration-nurture", "organic-to-paid-amplification", "human-authority", "segment-specific-email"],
        "promotion_status": "mechanism_distillation_ready",
        "evidence_grade": "official_platform_founder_case_study",
        "reported_outcomes": ["bootstrapped eight-figure automotive parts business", "email contributes 18% to 20% of revenue", "roughly 75% of the content operation now runs without the founder"],
        "observable_mechanism": "Independently test opaque products, turn each video into durable written evidence, capture owned intent, nurture for three to six months, and pay to amplify only organic outliers.",
        "evidence_dimensions": {
            "hard_outcome": "verified", "current_operation": "verified", "recent_three_to_six_month_breakout": "partial",
            "channel_mechanism": "verified", "retention_or_repeatability": "verified", "paid_organic_resource_scope": "partial"
        },
        "blocking_caveat": "Attribution across 60–150 day journeys remains explicitly unresolved; spend, margins, and incremental lift of boosts are not published.",
        "sources": [{"url": "https://www.shopify.com/blog/Shock-Surplus-profit-over-revenue", "source_type": "official_platform_founder_case_study", "published": "2026-06-09"}],
    },
    {
        "team_id": "skimpies",
        "team_name": "Skimpies",
        "business_model": "b2c",
        "cold_start_budget_tier": "cold_start_zero_paid",
        "cold_start_budget_window": "six-month TikTok cold start with no paid platform spend",
        "reported_zero_paid_media": True,
        "transferable_mechanism_tags": ["platform-native-live", "group-chat-interaction", "before-after-hook", "founder-performance", "organic-before-paid"],
        "promotion_status": "mechanism_distillation_ready",
        "evidence_grade": "official_platform_founder_case_study",
        "reported_outcomes": ["number-one TikTok brand after six months of organic live selling", "$60,000 from a ten-hour warehouse livestream", "an eight-second before/after video reached 6M views and doubled sales in 24 hours"],
        "observable_mechanism": "Treat TikTok as an interactive group chat, front-load the visual transformation, show up live daily, and earn trust before introducing paid amplification.",
        "evidence_dimensions": {
            "hard_outcome": "verified", "current_operation": "verified", "recent_three_to_six_month_breakout": "verified",
            "channel_mechanism": "verified", "retention_or_repeatability": "partial", "paid_organic_resource_scope": "verified"
        },
        "blocking_caveat": "Founder labor and family support were substantial; repeat purchase, margin, burnout cost, and independent TikTok attribution are incomplete.",
        "sources": [{"url": "https://www.shopify.com/uk/blog/skimpies-pathway-to-number-one", "source_type": "official_platform_founder_case_study", "published": "2026-06-04"}],
    },
    {
        "team_id": "candier",
        "team_name": "Candier",
        "business_model": "b2c",
        "cold_start_budget_tier": "cold_start_low_budget",
        "cold_start_budget_window": "founder-led targeted outreach without PR firm, sales team, or networking events",
        "reported_zero_paid_media": False,
        "transferable_mechanism_tags": ["targeted-gifting", "editor-outreach", "retail-buyer-outreach", "distinctive-copy", "founder-led-distribution"],
        "promotion_status": "mechanism_distillation_ready",
        "evidence_grade": "official_platform_founder_case_study",
        "reported_outcomes": ["nearly $14M business stocked at Target, Whole Foods, and Ulta", "repeated earned appearances on major U.S. morning shows", "built without a PR firm or sales team"],
        "observable_mechanism": "Build a distinctive product voice, map the exact editors and retail buyers who can carry it, send short personalized pitches or gifts, and compound earned credibility into distribution.",
        "evidence_dimensions": {
            "hard_outcome": "verified", "current_operation": "verified", "recent_three_to_six_month_breakout": "partial",
            "channel_mechanism": "verified", "retention_or_repeatability": "verified", "paid_organic_resource_scope": "partial"
        },
        "blocking_caveat": "Founder outreach is observable, but gifting cost, response denominator, wholesale economics, repeat purchase, and independent revenue validation are absent.",
        "sources": [{"url": "https://www.shopify.com/in/blog/candier-sassy-candles-serious-business", "source_type": "official_platform_founder_case_study", "published": "2026-05-14"}],
    },
    {
        "team_id": "solberg-manufacturing",
        "team_name": "Solberg Manufacturing",
        "business_model": "b2b",
        "sector_focus": "industrial manufacturing and distribution",
        "cold_start_budget_tier": "mature_scaled",
        "cold_start_budget_window": "six-month post-launch measurement at an established global manufacturer; implementation cost is undisclosed",
        "reported_zero_paid_media": False,
        "transferable_mechanism_tags": ["technical-product-discovery", "b2b-self-service", "seo-safe-migration", "reorder-loop", "global-catalog-localization"],
        "promotion_status": "mechanism_distillation_ready",
        "evidence_grade": "official_platform_customer_case_study",
        "reported_outcomes": ["15.2% web revenue growth year over year six months after launch", "13.0% online order-volume growth year over year", "6.9% average-order-value growth after launch", "92/100 Lighthouse SEO score with Core Web Vitals passing at launch"],
        "observable_mechanism": "Consolidate 3,600 technical products and 8,700 assets, preserve specification-led organic discovery, add metric and imperial comparison tools, and let business buyers find, order, view history, and reorder without phone or email friction.",
        "evidence_dimensions": {
            "hard_outcome": "verified", "current_operation": "verified", "recent_three_to_six_month_breakout": "verified",
            "channel_mechanism": "verified", "retention_or_repeatability": "partial", "paid_organic_resource_scope": "partial"
        },
        "blocking_caveat": "Shopify and its implementation partner report the results; media mix, project cost, cohort repeat rate, margin, and independent revenue audit are absent.",
        "sources": [{"url": "https://www.shopify.com/in/case-studies/solberg-manufacturing", "source_type": "official_platform_customer_case_study", "published": "2026-07-01"}],
    },
    {
        "team_id": "reposit-power",
        "team_name": "Reposit Power",
        "business_model": "b2b2c",
        "sector_focus": "energy equipment and installer distribution",
        "cold_start_budget_tier": "capital_efficient",
        "cold_start_budget_window": "small-team distribution reset measured across five weeks to eighteen months; software and labor cost are undisclosed",
        "reported_zero_paid_media": False,
        "transferable_mechanism_tags": ["installer-channel-positioning", "persona-research", "full-funnel-diagnostics", "sales-workflow-engine", "market-fit-correction"],
        "promotion_status": "mechanism_distillation_ready",
        "evidence_grade": "official_platform_customer_case_study",
        "reported_outcomes": ["sales activity increased from 20 to 1,000 calls per week", "monthly sales increased from 2 to 35 within five weeks", "sales meetings increased from 6 to 40 per week", "15% month-to-month growth and a reported 3:1 LTV-to-CAC ratio"],
        "observable_mechanism": "Use installer-adjacent education to create direct demand, inspect the full funnel to detect positioning failure, research buyer personas, simplify the offer, and join sales, implementation, service, and queue metrics in one operating loop.",
        "evidence_dimensions": {
            "hard_outcome": "verified", "current_operation": "verified", "recent_three_to_six_month_breakout": "partial",
            "channel_mechanism": "verified", "retention_or_repeatability": "verified", "paid_organic_resource_scope": "partial"
        },
        "blocking_caveat": "The source is a vendor case study and calls are activity rather than revenue; media spend, gross margin, CAC definition, and independent validation are incomplete.",
        "sources": [{"url": "https://www.hubspot.com/case-studies/reposit-power", "source_type": "official_platform_customer_case_study", "published": "undated"}],
    },
    {
        "team_id": "wingtra",
        "team_name": "Wingtra",
        "business_model": "b2b",
        "sector_focus": "drone manufacturing and surveying equipment",
        "cold_start_budget_tier": "undisclosed",
        "cold_start_budget_window": "four-month content conversion window; team and paid-channel costs are not disclosed",
        "reported_zero_paid_media": False,
        "transferable_mechanism_tags": ["technical-category-education", "surveying-use-cases", "content-to-form", "subscriber-to-lead", "expert-buyer-enablement"],
        "promotion_status": "mechanism_distillation_ready",
        "evidence_grade": "official_platform_customer_case_study",
        "reported_outcomes": ["20% traffic growth", "40% lead growth", "content-campaign conversion rate reported up 40% in four months"],
        "observable_mechanism": "Teach a traditional surveying market how the new equipment changes field work, measure each technical article through subscriber and form conversion, and use the resulting evidence to prioritize demand-generating topics.",
        "evidence_dimensions": {
            "hard_outcome": "verified", "current_operation": "verified", "recent_three_to_six_month_breakout": "partial",
            "channel_mechanism": "verified", "retention_or_repeatability": "partial", "paid_organic_resource_scope": "missing"
        },
        "blocking_caveat": "The vendor case reports traffic and leads rather than orders, margin, retention, or revenue; date, spend, and independent corroboration are incomplete.",
        "sources": [{"url": "https://www.hubspot.com/case-studies/wingtra", "source_type": "official_platform_customer_case_study", "published": "undated"}],
    },
    {
        "team_id": "viessmann",
        "team_name": "Viessmann",
        "business_model": "b2b2c",
        "sector_focus": "HVAC manufacturing and partner distribution",
        "cold_start_budget_tier": "mature_scaled",
        "cold_start_budget_window": "established global manufacturer; implementation and media costs are not disclosed",
        "reported_zero_paid_media": False,
        "transferable_mechanism_tags": ["partner-to-end-user", "lead-qualification", "conversion-automation", "manufacturer-demand-capture"],
        "promotion_status": "mechanism_distillation_ready",
        "evidence_grade": "official_platform_customer_case_study",
        "reported_outcomes": ["15% revenue increase", "57% conversion-rate increase", "16% increase in new leads year over year"],
        "observable_mechanism": "Replace undifferentiated partner communication with measurable end-user journeys, qualify intent, and pass decision-ready demand into the manufacturer and partner sales system.",
        "evidence_dimensions": {
            "hard_outcome": "verified", "current_operation": "verified", "recent_three_to_six_month_breakout": "missing",
            "channel_mechanism": "partial", "retention_or_repeatability": "partial", "paid_organic_resource_scope": "missing"
        },
        "blocking_caveat": "This is a mature-enterprise vendor case; outcome window, spend, partner contribution, margin, retention, and independent causal validation are missing.",
        "sources": [{"url": "https://www.hubspot.com/case-studies/viessmann", "source_type": "official_platform_customer_case_study", "published": "undated"}],
    },
    {
        "team_id": "insinkerator",
        "team_name": "InSinkErator",
        "business_model": "mixed",
        "sector_focus": "home and commercial equipment manufacturing",
        "cold_start_budget_tier": "mature_scaled",
        "cold_start_budget_window": "established manufacturer bringing digital marketing in-house; agency and internal cost are undisclosed",
        "reported_zero_paid_media": False,
        "transferable_mechanism_tags": ["in-house-demand-engine", "first-party-data", "content-to-commerce", "transaction-value-expansion"],
        "promotion_status": "mechanism_distillation_ready",
        "evidence_grade": "official_platform_customer_case_study",
        "reported_outcomes": ["27% revenue increase", "39% average-transaction-value increase", "20% website-traffic increase"],
        "observable_mechanism": "Move slow, expensive agency execution and spreadsheet-held customer data in-house, connect content and first-party journeys to commerce, and optimize for transaction value and revenue rather than publishing volume.",
        "evidence_dimensions": {
            "hard_outcome": "verified", "current_operation": "verified", "recent_three_to_six_month_breakout": "missing",
            "channel_mechanism": "verified", "retention_or_repeatability": "partial", "paid_organic_resource_scope": "partial"
        },
        "blocking_caveat": "The historical vendor case does not disclose time window, media mix, margin, repeat purchase, implementation cost, or independent attribution.",
        "sources": [{"url": "https://www.hubspot.com/case-studies/insinkerator", "source_type": "official_platform_customer_case_study", "published": "undated"}],
    },
    {
        "team_id": "rever-vn",
        "team_name": "Rever",
        "business_model": "mixed",
        "sector_focus": "real-estate brokerage",
        "cold_start_budget_tier": "capital_efficient",
        "cold_start_budget_window": "ten-month shift away from expensive paid and outbound dependence; residual spend is not quantified",
        "reported_zero_paid_media": False,
        "transferable_mechanism_tags": ["paid-dependence-reset", "local-intent-seo", "clear-cta", "lead-routing", "sales-marketing-visibility"],
        "promotion_status": "mechanism_distillation_ready",
        "evidence_grade": "official_platform_customer_case_study",
        "reported_outcomes": ["600% revenue increase in ten months", "100% traffic increase in three months", "1,500 additional leads per month"],
        "observable_mechanism": "Replace reach-first paid dependence with local-intent landing pages, explicit calls to action, automated lead routing, and shared journey visibility so content, lead quality, and closed deals can be improved together.",
        "evidence_dimensions": {
            "hard_outcome": "verified", "current_operation": "verified", "recent_three_to_six_month_breakout": "partial",
            "channel_mechanism": "verified", "retention_or_repeatability": "partial", "paid_organic_resource_scope": "partial"
        },
        "blocking_caveat": "The vendor case is historical and does not disclose baseline revenue, remaining paid spend, property-cycle effects, closed-deal denominator, retention, or independent audit.",
        "sources": [{"url": "https://www.hubspot.com/case-studies/rever-vn", "source_type": "official_platform_customer_case_study", "published": "undated"}],
    },
    {
        "team_id": "smash-my-trash",
        "team_name": "Smash My Trash",
        "business_model": "b2b",
        "sector_focus": "commercial waste services and franchising",
        "cold_start_budget_tier": "mixed_budget",
        "cold_start_budget_window": "twelve-month franchise expansion using enterprise sales and marketing tooling; total resource cost is undisclosed",
        "reported_zero_paid_media": False,
        "transferable_mechanism_tags": ["franchise-demand-routing", "quote-contract-automation", "territory-performance", "distributed-sales-enablement", "relationship-continuity"],
        "promotion_status": "mechanism_distillation_ready",
        "evidence_grade": "official_platform_customer_case_study",
        "reported_outcomes": ["288% revenue growth in twelve months", "95% lead growth in twelve months", "9,000 deals created and 2,900 closed", "locations grew from 12 to about 165"],
        "observable_mechanism": "Standardize quote, e-signature, contract, and lead-routing workflows across locally different franchisees; expose territory and salesperson movement; and preserve account context through staff or ownership transitions.",
        "evidence_dimensions": {
            "hard_outcome": "verified", "current_operation": "verified", "recent_three_to_six_month_breakout": "partial",
            "channel_mechanism": "verified", "retention_or_repeatability": "verified", "paid_organic_resource_scope": "partial"
        },
        "blocking_caveat": "The vendor case cannot isolate platform effect from rapid franchise expansion; media spend, franchise economics, cohort retention, and independently audited revenue are absent.",
        "sources": [{"url": "https://www.hubspot.com/case-studies/smash-my-trash-case-study", "source_type": "official_platform_customer_case_study", "published": "undated"}],
    },
    {
        "team_id": "fbi-buildings",
        "team_name": "FBi Buildings",
        "business_model": "b2b2c",
        "sector_focus": "post-frame construction",
        "cold_start_budget_tier": "mixed_budget",
        "cold_start_budget_window": "six-month initial signal and two-year operating outcome with software and consulting support",
        "reported_zero_paid_media": False,
        "transferable_mechanism_tags": ["buyer-question-library", "pricing-transparency", "technical-comparison-video", "long-cycle-attribution", "sales-content-enablement"],
        "promotion_status": "mechanism_distillation_ready",
        "evidence_grade": "official_consultancy_customer_case_study",
        "reported_outcomes": ["reported $5M turnaround in profit over two years", "687% lead increase and 722% organic-traffic increase", "one financing article attributed $20,000 in revenue", "a steel-comparison video helped close a reported $113,278 project after an eighteen-month journey"],
        "observable_mechanism": "Turn recurring buyer questions about price, financing, materials, and comparisons into two to three inspectable articles or videos each week; equip sales with the exact proof needed to defend premium bids and preserve multi-touch attribution across long projects.",
        "evidence_dimensions": {
            "hard_outcome": "verified", "current_operation": "verified", "recent_three_to_six_month_breakout": "missing",
            "channel_mechanism": "verified", "retention_or_repeatability": "verified", "paid_organic_resource_scope": "partial"
        },
        "blocking_caveat": "The consulting provider authored this historical case; consulting cost, paid contribution, margin definition, counterfactual, repeat contracts, and independent financial validation are incomplete.",
        "sources": [{"url": "https://www.impactplus.com/endless-customers-coaching/success-stories/fbi-buildings", "source_type": "official_consultancy_customer_case_study", "published": "undated"}],
    },
    {
        "team_id": "2030-builders",
        "team_name": "2030 Builders",
        "business_model": "b2b",
        "sector_focus": "sustainability professional services",
        "cold_start_budget_tier": "cold_start_low_budget",
        "cold_start_budget_window": "1-25-person startup replacing manual outreach; annual tool spend and labor are partially exposed",
        "reported_zero_paid_media": False,
        "transferable_mechanism_tags": ["stage-based-nurture", "lean-team-automation", "manual-outreach-replacement", "revenue-attribution", "resource-efficiency"],
        "promotion_status": "mechanism_distillation_ready",
        "evidence_grade": "official_platform_customer_case_study",
        "reported_outcomes": ["33% of company revenue attributed to lead generation and nurturing", "$50,000 annual headcount cost avoided", "20% marketing-team efficiency increase", "reported 8:1 revenue-to-platform-spend relationship"],
        "observable_mechanism": "Replace founder-heavy manual search with stage-specific communication, shared customer context, and lean-team automation; measure contribution as sourced revenue and avoided capacity rather than contact volume.",
        "evidence_dimensions": {
            "hard_outcome": "verified", "current_operation": "verified", "recent_three_to_six_month_breakout": "partial",
            "channel_mechanism": "verified", "retention_or_repeatability": "partial", "paid_organic_resource_scope": "verified"
        },
        "blocking_caveat": "The vendor case uses founder-reported attribution and labels an 8:1 ratio as 80% ROI; paid media, gross margin, retention, and independent financial validation are absent.",
        "sources": [{"url": "https://www.hubspot.com/case-studies/2030-builders-hubspot-starter-customer-platform-drives-one-third-of-the-startup-2030-builders-total-revenue", "source_type": "official_platform_customer_case_study", "published": "undated"}],
    },
    {
        "team_id": "pure-bookkeeping",
        "team_name": "Pure Bookkeeping",
        "business_model": "b2b",
        "sector_focus": "accounting enablement and professional services",
        "cold_start_budget_tier": "cold_start_low_budget",
        "cold_start_budget_window": "1-25-person North American expansion with ROI reported inside ninety days",
        "reported_zero_paid_media": False,
        "transferable_mechanism_tags": ["seminar-to-digital", "license-sales", "rapid-onboarding", "workflow-automation", "geographic-expansion"],
        "promotion_status": "mechanism_distillation_ready",
        "evidence_grade": "official_platform_customer_case_study",
        "reported_outcomes": ["more licenses sold in ninety days than in the entire prior year", "ROI reported inside ninety days", "30-customer onboarding reduced from about one month to a few days"],
        "observable_mechanism": "Translate a seminar-led expert offer into a geographically scalable nurture and sales journey, automate repetitive follow-up and onboarding, and protect expert time for client results.",
        "evidence_dimensions": {
            "hard_outcome": "verified", "current_operation": "verified", "recent_three_to_six_month_breakout": "partial",
            "channel_mechanism": "verified", "retention_or_repeatability": "verified", "paid_organic_resource_scope": "partial"
        },
        "blocking_caveat": "The case is vendor-authored; absolute sales, platform and labor cost, paid media, retention, margin, and independent verification are not disclosed.",
        "sources": [{"url": "https://www.hubspot.com/case-studies/pure-bookkeeping", "source_type": "official_platform_customer_case_study", "published": "undated"}],
    },
    {
        "team_id": "strategic-ic",
        "team_name": "Strategic IC",
        "business_model": "b2b",
        "sector_focus": "B2B professional services",
        "cold_start_budget_tier": "capital_efficient",
        "cold_start_budget_window": "inbound-led service growth over roughly two years; labor and tool cost are incomplete",
        "reported_zero_paid_media": False,
        "transferable_mechanism_tags": ["authority-to-retainer", "persona-led-content", "organic-nurture", "proof-reporting", "contract-expansion"],
        "promotion_status": "mechanism_distillation_ready",
        "evidence_grade": "official_platform_customer_case_study",
        "reported_outcomes": ["50% year-over-year revenue increase", "100% of clients on retainers", "35% increase in average retainer value", "80% of customers reported sourced through social and organic inbound nurture"],
        "observable_mechanism": "Define high-value buyer problems, publish full-funnel expertise, nurture organic and social demand until sales readiness, and use client-visible outcome reporting to convert projects into longer, higher-value retainers.",
        "evidence_dimensions": {
            "hard_outcome": "verified", "current_operation": "verified", "recent_three_to_six_month_breakout": "missing",
            "channel_mechanism": "verified", "retention_or_repeatability": "verified", "paid_organic_resource_scope": "partial"
        },
        "blocking_caveat": "The platform partner case is historical and self-reported; partner referrals, service labor, margin, paid spend, client cohorts, and independent revenue audit are absent.",
        "sources": [{"url": "https://www.hubspot.com/case-studies/strategic-ic", "source_type": "official_platform_customer_case_study", "published": "undated"}],
    },
    {
        "team_id": "beard-and-blade-wholesale",
        "team_name": "Beard & Blade Wholesale",
        "business_model": "mixed",
        "sector_focus": "wholesale distribution",
        "cold_start_budget_tier": "capital_efficient",
        "cold_start_budget_window": "one-year wholesale-channel expansion using an existing retail catalog and inventory pool",
        "reported_zero_paid_media": False,
        "transferable_mechanism_tags": ["b2b-self-service", "shared-inventory", "customer-specific-pricing", "bulk-assortment", "reorder-visibility"],
        "promotion_status": "mechanism_distillation_ready",
        "evidence_grade": "official_platform_customer_case_study",
        "reported_outcomes": ["wholesale revenue increased 100% in roughly one year", "$296 wholesale average order value, five times the reported $49 retail average", "retail sales increased 35% year over year"],
        "observable_mechanism": "Use one catalog and inventory pool to give qualified wholesale buyers self-service access, account-specific products and volume pricing, order tracking, and normal warehouse fulfillment; curate only products that fit bulk purchase rather than exposing everything.",
        "evidence_dimensions": {
            "hard_outcome": "verified", "current_operation": "verified", "recent_three_to_six_month_breakout": "missing",
            "channel_mechanism": "verified", "retention_or_repeatability": "verified", "paid_organic_resource_scope": "partial"
        },
        "blocking_caveat": "This is a historical platform case; implementation cost, buyer cohorts, repeat-order rate, margin, media mix, and independent revenue validation are absent.",
        "sources": [{"url": "https://www.shopify.com/uk/enterprise/blog/beard-blade-doubled-wholesale-ecommerce-after-replatforming-from-magento/", "source_type": "official_platform_customer_case_study", "published": "2018-01-31"}],
    },
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Compile a bounded, evidence-labeled breakout quality-team seed.")
    parser.add_argument("--output", type=Path, default=Path("evidence/v10/gtm-breakout-quality-team-seed-v1.json"))
    args = parser.parse_args()
    payload = compile_breakout_quality_team_seed(CASES, captured_at="2026-08-04T00:00:00-04:00")
    verify_breakout_quality_team_seed(payload)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "team_count": payload["team_count"], "status_counts": payload["promotion_status_counts"], "content_sha256": payload["content_sha256"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
