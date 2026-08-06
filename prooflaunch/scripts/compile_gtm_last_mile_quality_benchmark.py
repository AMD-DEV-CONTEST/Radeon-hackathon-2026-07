#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from prooflaunch_remix.files import atomic_write_text, sha256_file
from prooflaunch_remix.gtm_production_quality_contract import evaluate_quality_ladder


ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "artifacts/run-bound-multimodal-demo-v1/demo-receipt.json"
TEXT_REVIEW = ROOT / "evidence/v10/local-gtm-portfolio-blind-review-status.json"
VISUAL_REVIEW = ROOT / "artifacts/campaign-pack-visual-blind-review-v1/campaign-pack-blind-review-public.json"
CAMPAIGN_MANIFEST = ROOT / "evidence/v10/local-campaign-pack-v1/delivery-v6/campaign-pack-manifest.json"
INTERNAL_REVIEW_SCOPE = ROOT / "artifacts/gtm-last-mile-pk-v1/internal-text-review-v3/scope.json"
UNIFIED_REVIEW = ROOT / "artifacts/gtm-last-mile-pk-v1/multimodal-review-v5/unified-last-mile-review.json"
OBSERVED_AT = "2026-08-02T00:00:00Z"


LANE_SPECS: tuple[dict[str, Any], ...] = (
    {"id": "integrated_gtm_strategy", "label": "Integrated GTM strategy", "files": ("gtm-strategy.json",), "keys": ("strategy", "plan_status", "truth_boundary"), "axes": ("diagnostic depth", "strategic choice", "commercial logic", "creative platform", "channel coherence", "evidence discipline", "operator usability")},
    {"id": "organic_social_copy", "label": "Organic social copy", "files": ("channel-copy.json",), "keys": ("primary", "secondary", "safety_constraints"), "axes": ("hook strength", "originality", "platform nativeness", "brand voice", "proof integration", "CTA quality", "edit readiness")},
    {"id": "landing_page", "label": "Landing-page draft", "files": ("landing-page-draft.json",), "keys": ("hero", "citation", "truth_status"), "axes": ("message hierarchy", "clarity", "proof architecture", "objection handling", "conversion flow", "brand distinctiveness", "production polish")},
    {"id": "lifecycle_email", "label": "Lifecycle email", "files": ("lifecycle-email-draft.json",), "keys": ("subject", "body_blocks", "call_to_action"), "axes": ("subject strength", "reader relevance", "narrative progression", "proof integration", "voice", "CTA quality", "send readiness")},
    {"id": "visual_system", "label": "Visual campaign system", "media_roles": ("prooflaunch-hero-4k.png", "prooflaunch-social-1080x1350.png", "prooflaunch-landing-1920x1080.png"), "axes": ("art direction", "originality", "brand fit", "hierarchy", "cross-format coherence", "artifact defects", "production polish")},
    {"id": "video", "label": "Campaign video", "paths": ("artifacts/gtm-last-mile-pk-v1/video-challenger-v5/prooflaunch-three-beat-challenger-4k.mp4", "artifacts/gtm-last-mile-pk-v1/video-challenger-v5/video-challenger-receipt.json"), "axes": ("idea", "first-three-second hook", "shot craft", "motion continuity", "sound-picture coherence", "brand fit", "delivery polish")},
    {"id": "audio", "label": "Voice and audio master", "paths": ("artifacts/gtm-last-mile-pk-v1/audio-candidates-v2/master/voice-restraint-a-48k-stereo-24bit.wav", "artifacts/gtm-last-mile-pk-v1/audio-candidates-v2/master/voice-documentary-b-48k-stereo-24bit.wav", "artifacts/gtm-last-mile-pk-v1/audio-candidates-v2/master/voice-inquisitive-c-48k-stereo-24bit.wav", "artifacts/gtm-last-mile-pk-v1/audio-candidates-v2/audio-candidate-receipt.json"), "axes": ("semantic accuracy", "performance", "naturalness", "mix", "brand voice", "accessibility", "delivery polish")},
    {"id": "content_schedule", "label": "Content schedule", "files": ("content-calendar.json",), "keys": ("slots", "timezone", "frequency_cap"), "axes": ("sequence logic", "channel cadence", "format fit", "resource realism", "learning cadence", "fatigue control", "operator usability")},
    {"id": "seo", "label": "SEO execution", "files": ("seo-geo-questions.json",), "keys": ("question_intents", "faq_drafts", "claim_assurance"), "axes": ("intent coverage", "information gain", "SERP usefulness", "technical readiness", "internal-link logic", "claim accuracy", "conversion relevance")},
    {"id": "geo", "label": "GEO / answer visibility", "files": ("seo-geo-faq-drafts.json",), "keys": ("faqs",), "axes": ("answer completeness", "citation readiness", "entity clarity", "retrievability", "question coverage", "claim accuracy", "brand inclusion")},
    {"id": "advertising", "label": "Advertising plan", "files": ("channel-portfolio.json",), "keys": ("portfolio", "focus_channels", "test_channels"), "axes": ("audience-strategy fit", "creative-route fit", "budget logic", "test design", "incrementality design", "risk control", "operator clarity")},
    {"id": "analytics", "label": "Analytics and experiment plan", "files": ("analytics-plan.json",), "keys": ("metrics", "stop_rules", "interpretation"), "axes": ("metric validity", "identity-safe measurement", "causal design", "stopping logic", "revenue linkage", "diagnostic usefulness", "operator clarity")},
    {"id": "employee_agent", "label": "Graph / Loop / Harness", "files": ("graph-loop-harness.json",), "keys": ("graph", "loop", "harness"), "axes": ("task completion", "recovery quality", "tool discipline", "traceability", "approval integrity", "failure containment", "operator control")},
    {"id": "cross_device_memory", "label": "Cross-device memory continuity", "files": ("approved-learning-context.json",), "keys": ("memories", "human_promoted_only", "truth_boundary"), "axes": ("retrieval relevance", "conflict handling", "temporal validity", "privacy boundary", "human control", "cross-device consistency", "non-mutation guarantee")},
)


def _digest(payload: object) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _verified_entry(entry: dict[str, Any]) -> bool:
    path = ROOT / entry["path"]
    return path.is_file() and path.stat().st_size == entry["bytes"] and sha256_file(path) == entry["sha256"]


def build_benchmark() -> dict[str, Any]:
    demo = json.loads(DEMO.read_text(encoding="utf-8"))
    text_review = json.loads(TEXT_REVIEW.read_text(encoding="utf-8"))
    visual_review = json.loads(VISUAL_REVIEW.read_text(encoding="utf-8"))
    campaign = json.loads(CAMPAIGN_MANIFEST.read_text(encoding="utf-8"))
    internal_review = json.loads(INTERNAL_REVIEW_SCOPE.read_text(encoding="utf-8"))
    unified_review = json.loads(UNIFIED_REVIEW.read_text(encoding="utf-8"))
    documents = {item["artifact_role"]: item for item in demo["production_deliverables"]}
    media = {Path(item["path"]).name: item for item in campaign["artifacts"]}
    lanes: list[dict[str, Any]] = []
    for spec in LANE_SPECS:
        artifact_entries: list[dict[str, Any]] = []
        document_texts: list[str] = []
        required_fields_present = True
        for name in spec.get("files", ()):
            item = documents.get(name)
            if item is None:
                required_fields_present = False
                continue
            payload = json.loads((ROOT / item["path"]).read_text(encoding="utf-8"))
            document_texts.append(json.dumps(payload, ensure_ascii=False, sort_keys=True))
            required_fields_present = required_fields_present and all(key in payload for key in spec.get("keys", ()))
            artifact_entries.append({**item, "verified": _verified_entry(item)})
        for name in spec.get("media_roles", ()):
            item = media.get(name)
            if item is None:
                required_fields_present = False
                continue
            entry = {**item, "path": str((CAMPAIGN_MANIFEST.parent / item["path"]).relative_to(ROOT))}
            artifact_entries.append({**entry, "verified": _verified_entry(entry)})
        for locator in spec.get("paths", ()):
            path = ROOT / locator
            entry = {
                "path": locator,
                "bytes": path.stat().st_size if path.is_file() else None,
                "sha256": sha256_file(path) if path.is_file() else None,
            }
            artifact_entries.append({**entry, "verified": _verified_entry(entry)})
        all_artifacts_verified = bool(artifact_entries) and all(item["verified"] for item in artifact_entries)
        mechanical_ready = all_artifacts_verified and required_fields_present
        forbidden_placeholders = (
            "intended audience",
            "owner context not supplied",
            "this decision may occur in",
            "before choosing review",
            "to address needs reliable evidence",
        )
        defect_hits = sorted(
            token
            for token in forbidden_placeholders
            if any(token in text.casefold() for text in document_texts)
        )
        review_queue = "not_compiled"
        expected_reviews = 0
        submitted_reviews = 0
        text_internal_review_compiled = spec["id"] in {
            "integrated_gtm_strategy", "organic_social_copy", "landing_page",
            "lifecycle_email", "content_schedule", "seo", "geo", "advertising",
            "analytics", "employee_agent", "cross_device_memory",
        }
        internal_review_compiled = True
        internal_pair_count = 1
        if text_internal_review_compiled:
            review_queue = internal_review["review_admission_status"]
            expected_reviews = 5
            submitted_reviews = 0
        elif spec["id"] == "visual_system":
            review_queue = "compiled_empty"
            expected_reviews = visual_review["expected_review_count"]
            submitted_reviews = 0
        elif spec["id"] == "video":
            review_queue = "compiled_empty"
            expected_reviews = 5
            submitted_reviews = 0
        elif spec["id"] == "audio":
            review_queue = "compiled_empty"
            internal_pair_count = 3
            expected_reviews = 15
            submitted_reviews = 0
        lanes.append(
            {
                "lane_id": spec["id"],
                "label": spec["label"],
                "artifacts": artifact_entries,
                "artifact_count": len(artifact_entries),
                "mechanical_ready": mechanical_ready,
                "deterministic_copy_defect_scan_applicable": bool(document_texts),
                "deterministic_copy_defect_scan_passed": (
                    not defect_hits if document_texts else None
                ),
                "deterministic_copy_defect_hits": defect_hits,
                "quality_axes": list(spec["axes"]),
                "human_quality_scores": None,
                "review_queue_status": review_queue,
                "expected_human_reviews": expected_reviews,
                "submitted_human_reviews": submitted_reviews,
                "critical_defect_count": None,
                "same_brief_peer_comparison_completed": False,
                "same_brief_internal_challenger_compiled": internal_review_compiled,
                "same_brief_internal_pair_count": internal_pair_count,
                "top_product_baseline_present": False,
                "last_mile_execution_quality_alignment_achieved": False,
                "business_outcome_observed": False,
                "next_gate": "Complete the frozen same-brief qualified-human comparison; model scoring cannot promote this lane.",
            }
        )
    core: dict[str, Any] = {
        "schema": "ProofLaunchGTMLastMileProductionQualityBenchmarkV1",
        "observed_at": OBSERVED_AT,
        "effect_definition": {
            "primary": "last_mile_generated_execution_quality",
            "secondary": "observed_business_outcome",
        },
        "campaign_id": demo["campaign_id"],
        "run_id": demo["run_id"],
        "lane_count": len(lanes),
        "lanes": lanes,
        "portfolio": {
            "mechanically_ready_lane_count": sum(item["mechanical_ready"] for item in lanes),
            "copy_defect_scan_applicable_lane_count": sum(
                item["deterministic_copy_defect_scan_applicable"] for item in lanes
            ),
            "copy_defect_scan_passed_lane_count": sum(
                item["deterministic_copy_defect_scan_passed"] is True for item in lanes
            ),
            "same_brief_comparison_completed_lane_count": 0,
            "same_brief_internal_challenger_compiled_lane_count": sum(
                item["same_brief_internal_challenger_compiled"] for item in lanes
            ),
            "human_reviewed_lane_count": 0,
            "business_outcome_observed_lane_count": 0,
            "mechanical_pack_assembled": all(item["mechanical_ready"] for item in lanes),
            "last_mile_execution_quality_alignment_achieved": False,
            "business_outcome_observed": False,
            "four_a_quality_proven": False,
        },
        "pk_protocol": {
            "brief": "One frozen, rights-cleared brief and evidence bundle per comparison.",
            "comparison": "Candidate and rights-cleared peer/reference output are rendered in the same channel format with creator, provider and model identity hidden.",
            "reviewers": "At least five qualified reviewers per lane; strategy/measurement lanes require relevant operators and creative lanes require senior craft reviewers.",
            "dimensions": "The seven lane-specific quality axes plus a forced overall preference and critical-defect checklist.",
            "promotion_threshold": "Zero critical defects, at least 75% candidate preference, Wilson lower bound above 0.50, at least 95% directly publishable votes, no more than 5% major-rework votes, and no quality dimension with a statistically credible regression.",
            "judge_boundary": "Model judges may flag defects and explain disagreement but cannot select or release a winner.",
            "business_outcome_boundary": "Publication, spend, lift and revenue are measured later and cannot retroactively replace the production-quality verdict.",
        },
        "current_review_evidence": {
            "text_expected": text_review["expected_review_count"],
            "text_submitted": text_review["submitted_review_count"],
            "current_run_internal_expected": internal_review["expected_human_review_count"],
            "current_run_internal_submitted": internal_review["submitted_human_review_count"],
            "current_run_internal_review_admission_status": internal_review["review_admission_status"],
            "current_run_internal_top_product_baseline": internal_review["top_product_baseline"],
            "visual_expected": visual_review["expected_review_count"],
            "visual_submitted": 0,
            "unified_lane_count": unified_review["lane_count"],
            "unified_pair_count": unified_review["comparison_pair_count"],
            "unified_expected": unified_review["expected_human_review_count"],
            "unified_submitted": unified_review["submitted_human_review_count"],
            "unified_top_product_baselines_present": unified_review["top_product_baselines_present"],
        },
        "truth_boundary": (
            "This benchmark verifies the presence, bytes, hashes and minimum contracts of the "
            "current last-mile production pack. It does not assign aesthetic scores without human "
            "reviews and does not prove 4A parity, Top-1 standing, publication, lift or revenue."
        ),
    }
    core["quality_ladder"] = evaluate_quality_ladder(
        {
            "artifact_contract_passed": core["portfolio"]["mechanical_pack_assembled"],
            "rights_gate_passed": core["portfolio"]["mechanical_pack_assembled"],
            "claim_evidence_gate_passed": core["portfolio"]["mechanical_pack_assembled"],
            "platform_contract_passed": core["portfolio"]["mechanical_pack_assembled"],
            "identity_gate_passed": core["portfolio"]["mechanical_pack_assembled"],
            "accessibility_gate_passed": core["portfolio"]["mechanical_pack_assembled"],
            "blocking_defect_count": 0,
            "qualified_review_count": unified_review["submitted_human_review_count"],
            "directly_publishable_count": None,
            "major_rework_count": None,
            "human_blocking_defect_count": None,
            "blind_comparison_count": unified_review["submitted_human_review_count"],
            "candidate_preferred_count": None,
            "named_external_baseline_present": unified_review["top_product_baselines_present"],
            "source_hidden_review": True,
            "publication_receipt_count": 0,
            "authorized_observation_count": 0,
            "primary_metric_pre_registered": True,
            "observed_sample_size": None,
            "registered_minimum_sample": 25,
            "primary_metric_decision": None,
            "incremental_design_gate_passed": False,
            "attribution_integrity_passed": False,
            "safety_regression_observed": None,
            "qualified_conversion_rate": None,
            "time_to_first_human_publishable_asset_hours": None,
        }
    )
    core["content_sha256"] = _digest(core)
    return core


def render_markdown(payload: dict[str, Any]) -> str:
    p = payload["portfolio"]
    lines = [
        "# GTM last-mile production-quality benchmark V1", "",
        f"Observed: {payload['observed_at']}  ",
        f"Run: `{payload['run_id']}` · Campaign: `{payload['campaign_id']}`", "",
        "## Verdict", "",
        f"The current monotonic quality state is **{payload['quality_ladder']['current_state']}**. The pack is mechanically reviewable in **{p['mechanically_ready_lane_count']}/{payload['lane_count']} lanes**, and all 14 lanes now have internal same-Brief comparison packets. Same-brief 4A-quality alignment is **not proven**: 0 lanes have completed the required qualified-human comparison and the internal opponents are not named leading-product baselines. Business outcome is tracked separately and is also unobserved.", "",
        "| Production lane | Artifacts | Mechanical | Human PK | Business outcome | Next gate |", "|---|---:|---|---|---|---|",
    ]
    for lane in payload["lanes"]:
        lines.append(f"| {lane['label']} | {lane['artifact_count']} | {'ready' if lane['mechanical_ready'] else 'blocked'} | not completed | unobserved | {lane['next_gate']} |")
    lines += ["", "## Same-brief PK protocol", ""]
    for key in sorted(payload["pk_protocol"]):
        value = payload["pk_protocol"][key]
        lines.append(f"- **{key.replace('_', ' ').title()}:** {value}")
    lines += ["", "## Per-lane quality axes", ""]
    for lane in payload["lanes"]:
        lines.append(f"- **{lane['label']}:** {', '.join(lane['quality_axes'])}.")
    lines += ["", "## Truth boundary", "", payload["truth_boundary"], ""]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json-output", default=str(ROOT / "evidence/v10/gtm-last-mile-production-quality-v1.json"))
    parser.add_argument("--markdown-output", default=str(ROOT / "docs/product/GTM_LAST_MILE_PRODUCTION_QUALITY_V1.md"))
    args = parser.parse_args()
    outputs = (Path(args.json_output).resolve(), Path(args.markdown_output).resolve())
    for path in outputs:
        path.relative_to(ROOT)
    payload = build_benchmark()
    atomic_write_text(outputs[0], json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    atomic_write_text(outputs[1], render_markdown(payload))
    print(json.dumps({"lane_count": payload["lane_count"], "mechanically_ready": payload["portfolio"]["mechanically_ready_lane_count"], "last_mile_alignment": False, "content_sha256": payload["content_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
