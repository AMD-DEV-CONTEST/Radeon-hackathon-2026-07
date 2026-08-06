#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data/gtm_case_funnel_v2/high-transparency-public-leads-wave8-v2.json"


CASES = (
    ("Socially", "Bootstrapped startup with public revenue and operating-cost breakdown", "https://www.indiehackers.com/post/37-year-old-bootstrapped-startup-founder-on-saving-smartly-not-aggressively-P8x3S4aA2SR2hp02x54o?commentId=ljEIfei0ZHm8Xerninex", "b2b.b2b_saas.horizontal_saas"),
    ("Flodesk", "Growing a fully bootstrapped email-marketing platform to $37M ARR", "https://www.indiehackers.com/post/tech/growing-a-fully-bootstrapped-email-marketing-platform-to-37m-arr-yEzvbRhw1NFn0lHedTWu", "b2b.martech_sales_tech.marketing_automation"),
    ("Spendbase", "Growing to an 8-figure ARR in three years with savings-based pricing", "https://www.indiehackers.com/post/growing-to-an-8-figure-arr-in-three-years-with-savings-based-pricing-RQZkdT4qgvFZ5wAtNuLA", "b2b.b2b_saas.finance_operations"),
    ("RightMessage", "Building, failing, rebuilding, and then hitting $30k MRR in a year", "https://www.indiehackers.com/post/tech/building-failing-rebuilding-and-then-hitting-30k-mrr-in-a-year-JpcXzLO5sk8IEHz50bPO", "b2b.martech_sales_tech.marketing_automation"),
    ("Post Bridge", "Hitting $35k MRR after struggling to make money online for four years", "https://www.indiehackers.com/post/hitting-35k-mrr-after-struggling-to-make-money-online-for-four-years-CNVpxrwIVqxcsfZ4fERw", "b2b.martech_sales_tech.marketing_automation"),
    ("Barn2", "Diversifying to break a $1.6M per year plateau", "https://www.indiehackers.com/post/tech/diversifying-to-break-a-1-6m-yr-plateau-D8QDyPuDzSuOQS7ux9nR", "b2b.developer_tools.application_development"),
    ("Parqet", "Bootstrapping a fintech product to $108k MRR by limiting it to a small market", "https://www.indiehackers.com/post/bootstrapping-a-fintech-product-to-108k-mrr-by-limiting-it-to-a-small-market-sQoTemyW9t7ZAOurFhZk", "b2c.personal_finance.investing"),
    ("EmailOctopus", "The marketing tactics that took EmailOctopus to over $3M in annual recurring revenue", "https://emailoctopus.com/blog/the-marketing-tactics-that-took-emailoctopus-to-over-3m-in-annual-revenue", "b2b.martech_sales_tech.marketing_automation"),
    ("Automatio", "Bootstrapped SaaS to approximately $50k revenue in less than one year", "https://www.indiehackers.com/post/bootstrapped-my-saas-to-50k-revenue-in-less-than-1-year-ama-840ba046d6", "b2b.developer_tools.application_development"),
    ("Buffer", "Top lessons from growing to $10 million ARR with first-year channel focus", "https://buffer.com/resources/top-10-learnings-growing-to-10-million-arr/", "b2b.martech_sales_tech.marketing_automation"),
)


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def main() -> int:
    records = []
    for company, title, source_url, route in CASES:
        records.append({
            "lead_id": "wave8-" + digest(source_url)[:16],
            "company": company,
            "title": title,
            "source_url": source_url,
            "provisional_subvertical_ids": [route],
            "source_family_ids": ["public_founder_interview_or_company_transparency"],
            "discovery_method": "model_assisted_public_search_result",
            "outcome_evidence_independence": "founder_or_company_attributed_not_independent",
            "human_classification_required": True,
            "automatic_promotion_allowed": False,
            "formal_candidate_quota_credit": 0,
            "independent_discovery_queries": [
                f'"{company}" revenue growth annual report newsroom',
                f'"{company}" marketing spend team costs founder interview',
                f'"{company}" customers traffic growth independent',
            ],
        })
    payload = {
        "schema": "ProofLaunchGTMHighTransparencyWave8LeadSetV2",
        "record_count": len(records),
        "formal_candidate_quota_credit": 0,
        "automatic_promotion_allowed": False,
        "records": records,
        "truth_boundary": "These are public high-transparency promotion leads, not admitted cases. Founder or company claims require independent corroboration, complete cost-component binding, episode resolution and named review.",
    }
    payload["content_sha256"] = digest(payload)
    atomic_write_text(OUTPUT, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(OUTPUT), "record_count": len(records), "content_sha256": payload["content_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
