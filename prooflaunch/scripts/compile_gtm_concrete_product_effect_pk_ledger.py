#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from prooflaunch_remix.files import atomic_write_text, sha256_file


ROOT = Path(__file__).resolve().parents[1]
BENCHMARK = ROOT / "evidence/v10/gtm-ten-peer-effect-alignment-benchmark-v1.json"
RADAR = ROOT / "config/gtm_open_source_capability_radar_v1.json"
OBSERVED_AT = "2026-08-02T00:00:00Z"
INTERNAL_REVIEW_LOCATORS = {
    "image_generation_editing": "artifacts/campaign-pack-visual-blind-review-v1",
    "video_generation_production": "artifacts/gtm-last-mile-pk-v1/multimodal-review-v5/video",
    "audio_voice_music": "artifacts/gtm-last-mile-pk-v1/multimodal-review-v5/audio",
}
DEFAULT_INTERNAL_REVIEW_LOCATOR = "artifacts/gtm-last-mile-pk-v1/internal-text-review-v3"


CATEGORY_EXECUTION: dict[str, dict[str, Any]] = {
    "cross_device_memory": {
        "deliverables": (
            "artifacts/gtm-last-mile-pk-v1/control-plane-super-challengers-v1/cross-device-memory-execution-system.json",
            "artifacts/run-bound-multimodal-demo-v1/production-deliverables/approved-learning-context.json",
            "artifacts/gtm-last-mile-pk-v1/challenger-repairs-v1/cross-device-memory-execution.json",
        ),
        "same_brief_task": "Carry one approved insight across desktop and mobile, resolve a newer contradictory fact, expose provenance, then delete it exactly.",
        "pk_question": "Which system retrieves the useful fact with its source, resolves conflict correctly, preserves tenant/privacy boundaries and proves deletion without hidden mutation?",
        "reuse": ("mem0", "graphiti", "memos", "neo4j_agent_memory", "qwen3_embedding"),
    },
    "data_strategy_intelligence": {
        "deliverables": (
            "artifacts/gtm-last-mile-pk-v1/decision-intelligence-super-challengers-v1/data-strategy-decision-memo.json",
            "evidence/v10/prooflaunch-front-stage-brief-v1.json",
            "artifacts/gtm-last-mile-pk-v1/claim-trial-experience-v1/receipt.json",
        ),
        "same_brief_task": "Examine the frozen ProofLaunch 4A/virality claim, identify risk signals and missing evidence fields, produce a bounded rewrite and define the next evidence collection decision without inventing effect.",
        "pk_question": "Which output turns the same unsupported claim into the clearest source-bound decision, uncertainty boundary, missing-witness list and reversible next evidence action?",
        "reuse": ("duckdb", "polars", "openlineage", "feast", "great_expectations", "docling", "graphrag"),
    },
    "content_scheduling_operations": {
        "deliverables": (
            "artifacts/gtm-last-mile-pk-v1/scheduling-source-hidden-candidate-v1/scheduling-execution.json",
            "artifacts/gtm-last-mile-pk-v1/content-scheduling-super-challenger-v1/content-calendar.json",
            "artifacts/gtm-last-mile-pk-v1/claim-trial-experience-v1/launch-pack.json",
            "artifacts/gtm-last-mile-pk-v1/claim-trial-campaign-board-v1/index.html",
        ),
        "same_brief_task": "Schedule the frozen Claim Trial launch as one LinkedIn self-cross-examination, one 15-second vertical demonstration and one source-ready answer object, with human release and failure recovery.",
        "pk_question": "Which schedule preserves one coherent conflict, uses each surface natively, is executable tomorrow and avoids filler, fatigue and unapproved release?",
        "reuse": ("postiz", "temporal", "openlineage"),
    },
    "image_generation_editing": {
        "deliverables": (
            "evidence/v10/local-campaign-pack-v1/delivery-v9-rejection-rule/prooflaunch-hero-4k.png",
            "evidence/v10/local-campaign-pack-v1/delivery-v9-rejection-rule/prooflaunch-social-1080x1350.png",
            "evidence/v10/local-campaign-pack-v1/delivery-v9-rejection-rule/prooflaunch-landing-1920x1080.png",
        ),
        "same_brief_task": "Turn the frozen self-rejected 4A/virality claim into one screenshotable 1080×1350 Claim Trial verdict card that exposes the missing proof without turning into a compliance slide.",
        "pk_question": "Which 4:5 asset makes the claim, conflict, verdict and evidence gap legible within one feed glance while remaining distinctive, shareable and free of visible craft defects?",
        "reuse": ("comfyui", "qwen_image", "flux2", "paddleocr", "sam2", "open_clip"),
    },
    "video_generation_production": {
        "deliverables": (
            "artifacts/gtm-last-mile-pk-v1/video-challenger-v8-40-asset-interview/landscape_4k/prooflaunch-40-asset-interview-landscape_4k.mp4",
            "artifacts/gtm-last-mile-pk-v1/video-challenger-v8-40-asset-interview/vertical_4k/prooflaunch-40-asset-interview-vertical_4k.mp4",
            "artifacts/gtm-last-mile-pk-v1/video-challenger-v8-40-asset-interview/video-challenger-receipt.json",
            "artifacts/gtm-last-mile-pk-v1/claim-trial-video-v1/prooflaunch-claim-trial-vertical-4k.mp4",
            "artifacts/gtm-last-mile-pk-v1/claim-trial-video-v1/prooflaunch-claim-trial.vtt",
            "artifacts/gtm-last-mile-pk-v1/claim-trial-video-v1/receipt.json",
        ),
        "same_brief_task": "Produce the frozen 15-second Claim Trial in vertical 4K: the product puts its own 4A claim under oath, delivers NO WITNESS, then replaces hype with the bounded product truth.",
        "pk_question": "Which film makes the self-indictment understandable in three seconds, lands the verdict with stronger timing and turns the bounded rewrite into a credible participation CTA?",
        "reuse": ("comfyui", "wan22", "ltx2", "vbench", "mova"),
    },
    "audio_voice_music": {
        "deliverables": ("artifacts/gtm-last-mile-pk-v1/claim-trial-audio-v1/master/voice-cross-examiner-a-48k-stereo-24bit.wav", "artifacts/gtm-last-mile-pk-v1/claim-trial-audio-v1/master/voice-documentary-b-48k-stereo-24bit.wav", "artifacts/gtm-last-mile-pk-v1/claim-trial-audio-v1/master/voice-founder-c-48k-stereo-24bit.wav", "artifacts/gtm-last-mile-pk-v1/claim-trial-audio-v1/audio-candidate-receipt.json"),
        "same_brief_task": "Deliver the identical frozen script as three consent-safe voice directions, align transcript, master to the declared loudness/format and retain one blind-review finalist.",
        "pk_question": "Which master is more intelligible, human, emotionally appropriate, speaker-consistent and mix-ready while preserving exact semantic meaning?",
        "reuse": ("qwen3_tts", "ace_step15", "whisper", "whisperx", "step_audio_editx"),
    },
    "text_content_generation": {
        "deliverables": (
            "artifacts/gtm-last-mile-pk-v1/text-super-challenger-v1/channel-copy.json",
            "artifacts/gtm-last-mile-pk-v1/text-super-challenger-v1/landing-page-draft.json",
            "artifacts/gtm-last-mile-pk-v1/text-super-challenger-v1/lifecycle-email-draft.json",
            "evidence/v10/prooflaunch-front-stage-brief-v1.json",
            "artifacts/gtm-last-mile-pk-v1/claim-trial-experience-v1/launch-pack.json",
            "artifacts/gtm-last-mile-pk-v1/claim-trial-experience-v1/index.html",
        ),
        "same_brief_task": "Turn ProofLaunch rejecting its own unsupported 4A/virality claim into a LinkedIn-native launch post, interactive landing narrative, jury question and retrial CTA without dulling the conflict.",
        "pk_question": "Which copy is more ownable, specific and platform-native; demonstrates the product rather than listing features; and earns a qualified reply without unsupported effect language?",
        "reuse": ("dspy", "promptfoo", "qwen3_embedding", "cleanlab"),
    },
    "product_marketing_analytics": {
        "deliverables": (
            "artifacts/gtm-last-mile-pk-v1/decision-intelligence-super-challengers-v1/product-analytics-measurement-system.json",
            "evidence/v10/prooflaunch-front-stage-brief-v1.json",
            "artifacts/gtm-last-mile-pk-v1/claim-trial-campaign-board-v1/receipt.json",
        ),
        "same_brief_task": "Instrument the Claim Trial from exposure through trial completion, verdict save/share, witness supplied and retrial, with identity-safe events and no reach-to-revenue attribution theatre.",
        "pk_question": "Which plan distinguishes curiosity from useful evidence contribution, supports funnel/cohort diagnosis and can test incrementality without inventing causality or revenue?",
        "reuse": ("posthog", "growthbook", "duckdb", "polars", "openlineage", "dowhy"),
    },
    "geo_ai_visibility": {
        "deliverables": (
            "artifacts/gtm-last-mile-pk-v1/search-answer-super-challengers-v1/seo-geo-faq-drafts.json",
            "evidence/v10/prooflaunch-front-stage-brief-v1.json",
            "artifacts/gtm-last-mile-pk-v1/claim-trial-experience-v1/index.html",
        ),
        "same_brief_task": "Answer ‘Has ProofLaunch proven 4A quality or guaranteed virality?’ with a direct NO, the exact missing evidence, the bounded product truth and a reusable source/limitation structure.",
        "pk_question": "Which answer is clearer, more complete, source-ready, entity-consistent and retrievable by answer engines without keyword padding or unsupported claims?",
        "reuse": ("open_seo", "siteone", "networkx", "qwen3_embedding", "qwen3_vl_embedding"),
    },
    "seo_operations": {
        "deliverables": (
            "artifacts/gtm-last-mile-pk-v1/search-answer-super-challengers-v1/seo-technical-execution.json",
            "artifacts/gtm-last-mile-pk-v1/claim-trial-experience-v1/index.html",
            "artifacts/gtm-last-mile-pk-v1/claim-trial-experience-v1/receipt.json",
        ),
        "same_brief_task": "Turn the frozen Claim Trial into a crawlable owned page that resolves the 4A/virality substantiation intent, exposes limitations and provides a retriable evidence path rather than thin keyword copy.",
        "pk_question": "Which execution resolves intent with more information gain and arrives technically crawlable, fast, accessible, non-duplicative and measurable?",
        "reuse": ("siteone", "lighthouse", "open_seo", "networkx", "playwright"),
    },
    "employee_agent_platforms": {
        "deliverables": (
            "artifacts/gtm-last-mile-pk-v1/control-plane-super-challengers-v1/employee-agent-mission-system.json",
            "artifacts/run-bound-multimodal-demo-v1/production-deliverables/graph-loop-harness.json",
            "artifacts/gtm-last-mile-pk-v1/challenger-repairs-v1/employee-agent-execution-trace.json",
            "artifacts/gtm-last-mile-pk-v1/claim-trial-experience-v1/claim-trial-engine.mjs",
            "artifacts/gtm-last-mile-pk-v1/claim-trial-experience-v1/receipt.json",
        ),
        "same_brief_task": "Ask the GTM employee to publish its own frozen 4A/virality claim; require it to detect unsupported language, refuse release, identify missing witnesses and produce a bounded rewrite without operator prompting.",
        "pk_question": "Which agent demonstrates more senior judgment by challenging its own brief, preserving evidence and authority boundaries, producing a useful repair and refusing unsupported release?",
        "reuse": ("pydantic_ai", "temporal", "playwright", "browser_use", "openllmetry", "opa"),
    },
    "advertising_activation": {
        "deliverables": (
            "artifacts/gtm-last-mile-pk-v1/control-plane-super-challengers-v1/advertising-activation-review-system.json",
            "artifacts/run-bound-multimodal-demo-v1/production-deliverables/channel-portfolio.json",
            "artifacts/gtm-last-mile-pk-v1/gemma3-last-mile-challenger.json",
            "artifacts/gtm-last-mile-pk-v1/challenger-repairs-v1/advertising-creative-system.json",
            "artifacts/gtm-last-mile-pk-v1/claim-trial-experience-v1/share-card-1080x1350.png",
            "artifacts/gtm-last-mile-pk-v1/claim-trial-experience-v1/launch-pack.json",
        ),
        "same_brief_task": "Adapt the frozen Claim Trial self-indictment into a no-spend creative challenger with explicit audience exclusions, effect boundaries and human activation authority; do not activate or infer performance.",
        "pk_question": "Which plan offers stronger creative diversity and objective/audience fit while making pacing, incrementality, safety and human spend authority unambiguous?",
        "reuse": ("meridian", "dowhy", "econml", "causalml", "vowpal_wabbit", "opa"),
    },
    "gtm_lifecycle_orchestration": {
        "deliverables": (
            "artifacts/gtm-last-mile-pk-v1/gtm-lifecycle-super-challenger-v1/gtm-lifecycle-execution-dossier.json",
            "evidence/v10/prooflaunch-front-stage-brief-v1.json",
            "artifacts/gtm-last-mile-pk-v1/claim-trial-campaign-board-v1/index.html",
            "artifacts/gtm-last-mile-pk-v1/claim-trial-campaign-board-v1/receipt.json",
        ),
        "same_brief_task": "Carry the frozen self-claim from diagnosis through Claim Trial, bounded rewrite, interactive experience, 4:5 card, 4K short, voice options, human release gate, observation contract and evidence-triggered retrial.",
        "pk_question": "Which system keeps one ownable idea coherent across the entire lifecycle, delivers stronger native artifacts, preserves release authority and turns a new witness into a sharper next cycle?",
        "reuse": ("pydantic_ai", "temporal", "dspy", "posthog", "growthbook", "meridian", "openlineage"),
    },
}


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _artifact(path: str) -> dict[str, Any]:
    target = ROOT / path
    return {
        "path": path,
        "exists": target.is_file(),
        "bytes": target.stat().st_size if target.is_file() else None,
        "sha256": sha256_file(target) if target.is_file() else None,
    }


def build() -> dict[str, Any]:
    benchmark = json.loads(BENCHMARK.read_text(encoding="utf-8"))
    radar = json.loads(RADAR.read_text(encoding="utf-8"))
    projects = radar["projects"]
    rows: list[dict[str, Any]] = []
    categories: list[dict[str, Any]] = []
    for category in benchmark["categories"]:
        category_id = category["category_id"]
        execution = CATEGORY_EXECUTION[category_id]
        internal_review_locator = INTERNAL_REVIEW_LOCATORS.get(
            category_id,
            DEFAULT_INTERNAL_REVIEW_LOCATOR,
        )
        artifacts = [_artifact(path) for path in execution["deliverables"]]
        oss = []
        for project_id in execution["reuse"]:
            metadata = projects[project_id]
            oss.append({"project_id": project_id, **metadata})
        for product in category["reference_products"]:
            rows.append(
                {
                    "category_id": category_id,
                    "reference_product": product["name"],
                    "reference_product_url": product["official_or_primary_url"],
                    "reference_capability": product["reference_capability"],
                    "same_brief_task": execution["same_brief_task"],
                    "effect_pk_question": execution["pk_question"],
                    "quality_axes": category["benchmark_axes"],
                    "candidate_artifacts": artifacts,
                    "open_source_reuse": oss,
                    "internal_same_brief_review_packet": internal_review_locator,
                    "internal_same_brief_opponent_compiled": True,
                    "named_product_baseline_present": False,
                    "comparison_status": "not_completed",
                    "qualified_human_review_count": 0,
                    "candidate_preference_rate": None,
                    "wilson_lower_95": None,
                    "critical_defect_count": None,
                    "effect_alignment_achieved": False,
                    "next_action": category["next_action"],
                }
            )
        categories.append(
            {
                "category_id": category_id,
                "reference_product_count": len(category["reference_products"]),
                "candidate_artifact_count": len(artifacts),
                "candidate_artifacts_present": all(item["exists"] for item in artifacts),
                "open_source_project_count": len(oss),
                "open_source_projects": oss,
                "internal_same_brief_review_packet": internal_review_locator,
                "internal_same_brief_opponent_compiled": True,
                "named_product_baseline_present": False,
                "same_brief_task": execution["same_brief_task"],
                "effect_pk_question": execution["pk_question"],
                "quality_axes": category["benchmark_axes"],
                "comparison_completed_count": 0,
                "effect_alignment_achieved": False,
            }
        )
    core: dict[str, Any] = {
        "schema": "ProofLaunchConcreteProductEffectPKLedgerV1",
        "observed_at": OBSERVED_AT,
        "category_count": len(categories),
        "reference_product_row_count": len(rows),
        "categories": categories,
        "product_pk_rows": rows,
        "acceptance_gate": {
            "same_brief_required": True,
            "identity_hidden": True,
            "minimum_qualified_reviewers_per_lane": 5,
            "zero_critical_defects_required": True,
            "minimum_candidate_preference_rate": 0.75,
            "minimum_wilson_lower_95_exclusive": 0.50,
            "minimum_candidate_publishable_rate": 0.95,
            "maximum_candidate_major_rework_rate": 0.05,
            "model_judge_can_promote": False,
            "product_integration_can_substitute_for_effect_pk": False,
        },
        "portfolio": {
            "categories_with_candidate_artifacts_present": sum(item["candidate_artifacts_present"] for item in categories),
            "categories_with_internal_same_brief_opponent": sum(item["internal_same_brief_opponent_compiled"] for item in categories),
            "categories_with_named_product_baseline": sum(item["named_product_baseline_present"] for item in categories),
            "completed_product_pk_rows": 0,
            "effect_aligned_categories": 0,
            "open_source_reuse_is_pinned_not_vendor_copying": True,
        },
        "truth_boundary": (
            "This ledger makes every product and last-mile effect comparison explicit and binds "
            "candidate artifacts to pinned open-source reuse. Product naming, artifact presence and "
            "open-source integration are not preference evidence. All 130 product rows remain "
            "uncompleted until rights-cleared same-brief outputs receive qualified human review."
        ),
    }
    core["content_sha256"] = _digest(core)
    return core


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Concrete product and last-mile effect PK ledger V1",
        "",
        f"**Scope:** {payload['category_count']} categories · {payload['reference_product_row_count']} named product rows · 0 completed product PK rows.",
        "",
        "Integration is not effect proof. All categories have an internal same-Brief opponent packet, but each named-product row still needs a rights-cleared product output and five qualified, identity-hidden human reviews.",
        "",
        "| Category | Ten products | Concrete same-brief execution | Last-mile effect PK | Pinned OSS reuse | Candidate evidence | Current verdict |",
        "|---|---|---|---|---|---|---|",
    ]
    rows_by_category: dict[str, list[dict[str, Any]]] = {}
    for row in payload["product_pk_rows"]:
        rows_by_category.setdefault(row["category_id"], []).append(row)
    for category in payload["categories"]:
        rows = rows_by_category[category["category_id"]]
        products = "; ".join(row["reference_product"] for row in rows)
        oss = "; ".join(item["project_id"] for item in category["open_source_projects"])
        artifacts = "<br>".join(item["path"] for item in rows[0]["candidate_artifacts"])
        lines.append(
            f"| {category['category_id']} | {products} | {category['same_brief_task']} | "
            f"{category['effect_pk_question']} | {oss} | {artifacts} | **NOT PROVEN — 0/10 product rows reviewed** |"
        )
    lines += ["", "## Per-product capability rows", ""]
    for row in payload["product_pk_rows"]:
        lines += [
            f"### {row['category_id']} × {row['reference_product']}",
            "",
            f"- Reference capability: {row['reference_capability']}",
            f"- Same-brief task: {row['same_brief_task']}",
            f"- Effect question: {row['effect_pk_question']}",
            f"- Quality axes: {', '.join(row['quality_axes'])}",
            f"- Internal opponent packet: `{row['internal_same_brief_review_packet']}`; named-product baseline present: false.",
            f"- Current status: **{row['comparison_status']}**; human reviews 0; effect alignment false.",
            "",
        ]
    lines += ["## Truth boundary", "", payload["truth_boundary"], ""]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json-output", default=str(ROOT / "evidence/v10/gtm-concrete-product-effect-pk-ledger-v1.json"))
    parser.add_argument("--markdown-output", default=str(ROOT / "docs/product/GTM_CONCRETE_PRODUCT_EFFECT_PK_LEDGER_V1.md"))
    args = parser.parse_args()
    json_output = Path(args.json_output).resolve()
    markdown_output = Path(args.markdown_output).resolve()
    json_output.relative_to(ROOT)
    markdown_output.relative_to(ROOT)
    payload = build()
    atomic_write_text(json_output, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    atomic_write_text(markdown_output, render_markdown(payload))
    print(json.dumps({"category_count": payload["category_count"], "product_rows": payload["reference_product_row_count"], "completed": 0, "content_sha256": payload["content_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
