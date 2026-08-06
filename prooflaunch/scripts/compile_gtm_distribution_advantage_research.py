#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text


ROOT = Path(__file__).resolve().parents[1]
OBSERVED_AT = "2026-08-02"


SOURCES = [
    {
        "source_id": "salesforce_goals_agent",
        "publisher": "Salesforce",
        "url": "https://www.salesforce.com/news/stories/agentic-marketing-teams-announcement/",
        "pattern": "Goals, guardrails, budgets and live signals constrain agentic planning and execution.",
        "derived_requirement": "Keep the campaign objective and budget as typed Graph inputs; require named-human approval before activation.",
    },
    {
        "source_id": "salesforce_agentic_optimization",
        "publisher": "Salesforce",
        "url": "https://www.salesforce.com/blog/agentic-marketing-optimization/",
        "pattern": "Optimization closes the loop between observed performance signals and the next planning cycle.",
        "derived_requirement": "Signal feedback may reprioritize the next run but may not silently mutate an active run.",
    },
    {
        "source_id": "hootsuite_suite",
        "publisher": "Hootsuite",
        "url": "https://www.hootsuite.com/suite",
        "pattern": "Insight, creation, scheduling, engagement and analytics are connected in one operating surface.",
        "derived_requirement": "The channel decision must remain bound to the production pack, calendar, release preview and outcome ledger.",
    },
    {
        "source_id": "hootsuite_perch",
        "publisher": "Hootsuite",
        "url": "https://www.hootsuite.com/perch",
        "pattern": "Social intelligence informs planning with cross-network conversation and trend signals.",
        "derived_requirement": "Admit only authorized aggregate platform signals and expose whether they changed the decision.",
    },
    {
        "source_id": "posthog_product_analytics",
        "publisher": "PostHog",
        "url": "https://posthog.com/",
        "pattern": "Analytics, experiments and data workflows share a product-level feedback loop.",
        "derived_requirement": "Treat channel scoring as an experiment prior, never as a forecast; preserve comparable holdouts and outcome provenance.",
    },
    {
        "source_id": "ahrefs_ai_visibility",
        "publisher": "Ahrefs",
        "url": "https://ahrefs.com/ai",
        "pattern": "AI visibility and share-of-voice monitoring complement classic search metrics.",
        "derived_requirement": "Represent search and AI-discovery evidence as observable signals, not guaranteed ranking or traffic.",
    },
    {
        "source_id": "salesforce_agentforce_platform",
        "publisher": "Salesforce",
        "url": "https://www.salesforce.com/platform/agentforce-platform",
        "pattern": "Governed agent platforms combine data, retrieval, tools and policy controls.",
        "derived_requirement": "Use deterministic Graph contracts, bounded node Loops and a cross-cutting Harness for authorization, validation and audit.",
    },
    {
        "source_id": "geo_stochastic_optimization_paper",
        "publisher": "arXiv",
        "url": "https://arxiv.org/abs/2607.14035",
        "pattern": "Generative-engine optimization is a stochastic, multi-stage measurement and optimization problem.",
        "derived_requirement": "Use repeated, source-bound GEO observations with uncertainty; forbid deterministic placement claims.",
    },
]


IMPLEMENTED_CONTRACTS = [
    {
        "contract_id": "typed_operating_context",
        "inputs": [
            "business_model",
            "lifecycle_stage",
            "budget_tier",
            "industry_risk",
            "company_scale",
            "brand_reach",
            "owned_audience_strength",
            "community_access",
            "partner_access",
            "content_capacity",
            "sales_motion",
        ],
        "evidence": "src/prooflaunch_remix/gtm_strategy.py",
    },
    {
        "contract_id": "shared_distribution_advantage_score",
        "inputs": [
            "typed_operating_context",
            "authorized_platform_signal_counts",
            "budget_hard_constraint",
        ],
        "evidence": "src/prooflaunch_remix/gtm_channel_portfolio.py",
    },
    {
        "contract_id": "graph_loop_harness_boundary",
        "inputs": [
            "deterministic_channel_frontier",
            "bounded_node_generation",
            "named_human_review",
            "next_run_only_reallocation",
        ],
        "evidence": "src/prooflaunch_remix/v10_submission_runtime.py",
    },
    {
        "contract_id": "cross_context_mechanical_evaluation",
        "inputs": [
            "48_core_contracts",
            "8_distribution_profiles",
            "5_authorized_signal_scenarios",
        ],
        "evidence": "evidence/v10/gtm-distribution-advantage-matrix-v2.json",
    },
]


def build_research_evidence() -> dict[str, object]:
    core: dict[str, object] = {
        "schema": "ProofLaunchDistributionAdvantageResearchV1",
        "observed_at": OBSERVED_AT,
        "research_method": "official_product_and_primary_research_pattern_comparison",
        "source_count": len(SOURCES),
        "sources": SOURCES,
        "implemented_contracts": IMPLEMENTED_CONTRACTS,
        "explicit_non_goals": [
            "no unsupported global_top_10 ranking",
            "no copying of proprietary product implementation or campaign content",
            "no automatic channel activation, publication, spend or live-run mutation",
            "no claim that a score predicts reach, lift, virality or revenue",
            "no claim that mechanical matrix coverage establishes 4A creative quality",
        ],
        "truth_boundary": (
            "This evidence compares externally visible product and research patterns "
            "against the implemented local contract. It is not an exhaustive market "
            "ranking, a reverse engineering claim, a human-preference result, a live "
            "campaign result or proof of 4A/Top-1 performance."
        ),
    }
    encoded = json.dumps(
        core,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    core["content_sha256"] = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    return core


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        default=str(
            ROOT / "evidence/v10/gtm-distribution-advantage-research-2026-08-02.json"
        ),
    )
    args = parser.parse_args()
    output = Path(args.output).resolve()
    try:
        output.relative_to(ROOT.resolve())
    except ValueError as error:
        raise SystemExit("output must remain inside the project root") from error
    evidence = build_research_evidence()
    atomic_write_text(
        output,
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    print(
        json.dumps(
            {
                "output": str(output),
                "source_count": evidence["source_count"],
                "content_sha256": evidence["content_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
