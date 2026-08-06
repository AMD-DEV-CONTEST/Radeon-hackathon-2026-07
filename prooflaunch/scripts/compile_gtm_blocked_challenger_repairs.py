#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from prooflaunch_remix.files import atomic_write_text, sha256_file
from prooflaunch_remix.gtm_unified_offline_review import seal, sha256_json


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts/gtm-last-mile-pk-v1/challenger-repairs-v1"
SCENARIO = "prooflaunch-b2b-ai-launch-zero-budget-v1"


def binding(relative: str) -> dict[str, Any]:
    path = ROOT / relative
    return {"path": relative, "bytes": path.stat().st_size, "sha256": sha256_file(path)}


def event_chain(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    previous = "0" * 64
    result = []
    for index, event in enumerate(events, 1):
        core = {"sequence": index, "previous_event_sha256": previous, **event}
        sealed_event = {**core, "event_sha256": sha256_json(core)}
        result.append(sealed_event)
        previous = sealed_event["event_sha256"]
    return result


def write(name: str, payload: dict[str, Any]) -> dict[str, Any]:
    path = OUTPUT / name
    sealed_payload = seal(payload)
    atomic_write_text(path, json.dumps(sealed_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return binding(path.relative_to(ROOT).as_posix())


def build() -> dict[str, Any]:
    expected_outputs = {
        "cross-device-memory-execution.json",
        "data-strategy-decision-memo.json",
        "product-analytics-measurement-system.json",
        "seo-technical-execution.json",
        "employee-agent-execution-trace.json",
        "advertising-creative-system.json",
        "gtm-lifecycle-execution-dossier.json",
        "manifest.json",
    }
    if OUTPUT.exists():
        unexpected = {path.name for path in OUTPUT.iterdir()} - expected_outputs
        if unexpected:
            raise SystemExit(
                "challenger repair output contains unexpected files: "
                + ", ".join(sorted(unexpected))
            )
    OUTPUT.mkdir(parents=True, mode=0o700, exist_ok=True)
    common_boundary = {
        "data_class": "synthetic_local_mechanics",
        "external_publish_executed": False,
        "paid_media_spend_usd": 0,
        "production_effect_observed": False,
        "four_a_quality_proven": False,
    }
    outputs = []
    memory_events = event_chain([
        {"event": "approved_memory_created", "tenant_id": "tenant-alpha", "project_id": "prooflaunch", "device_id": "desktop-a", "memory_id": "memory-channel-priority", "value": "linkedin-first", "source": "human://decision/001", "human_approved": True},
        {"event": "newer_conflicting_memory_created", "tenant_id": "tenant-alpha", "project_id": "prooflaunch", "device_id": "mobile-b", "memory_id": "memory-channel-priority-v2", "supersedes": "memory-channel-priority", "value": "partner-community-first", "source": "human://decision/002", "human_approved": True},
        {"event": "conflict_resolved", "tenant_id": "tenant-alpha", "project_id": "prooflaunch", "winner": "memory-channel-priority-v2", "rule": "newer_explicit_human_approval_wins", "provenance_preserved": True},
        {"event": "cross_tenant_retrieval_denied", "requesting_tenant_id": "tenant-beta", "memory_tenant_id": "tenant-alpha", "result_count": 0, "permission_denied": True},
        {"event": "cross_device_retrieval_succeeded", "tenant_id": "tenant-alpha", "device_id": "tablet-c", "memory_id": "memory-channel-priority-v2", "value": "partner-community-first", "source": "human://decision/002"},
        {"event": "exact_deletion_requested", "tenant_id": "tenant-alpha", "memory_id": "memory-channel-priority-v2", "human_approved": True},
        {"event": "deletion_tombstone_appended", "tenant_id": "tenant-alpha", "memory_id": "memory-channel-priority-v2", "raw_value_retained": False},
        {"event": "post_deletion_retrieval", "tenant_id": "tenant-alpha", "device_id": "desktop-a", "memory_id": "memory-channel-priority-v2", "result_count": 0, "tombstone_observed": True},
    ])
    outputs.append(write("cross-device-memory-execution.json", {
        "schema": "ProofLaunchCrossDeviceMemoryExecutionV1", "scenario_id": SCENARIO,
        "memory_count": 2, "latest_source_observation_id": "human://decision/002",
        "events": memory_events, "event_count": len(memory_events), "hash_chain_valid": True,
        "conflict_resolution": "newer explicit human approval wins while both source references remain auditable",
        "tenant_isolation": "tenant-beta retrieval denied with zero returned records",
        "deletion_proof": "append-only tombstone plus zero-result retrieval; raw value is absent",
        "automatic_strategy_mutation_executed": False,
        **common_boundary,
        "truth_boundary": "This is a deterministic synthetic lifecycle execution proving local conflict, provenance, tenant denial, cross-device retrieval and exact deletion mechanics; it is not production user-memory or product preference evidence.",
    }))
    outputs.append(write("data-strategy-decision-memo.json", {
        "schema": "ProofLaunchDataStrategyDecisionMemoV1", "scenario_id": SCENARIO,
        "decision": "Continue the evidence-first organic route for one preregistered cycle; retain partner community as the falsification lane.",
        "point_in_time_cutoff": "2026-08-03T00:00:00Z",
        "lineage": [binding("artifacts/run-bound-multimodal-demo-v1/production-deliverables/gtm-strategy.json"), binding("artifacts/run-bound-multimodal-demo-v1/production-deliverables/analytics-plan.json")],
        "semantic_metrics": [{"name": "qualified_action_rate", "numerator": "qualified evidence-pack actions", "denominator": "eligible sessions", "owner": "growth-analytics"}],
        "forecast_uncertainty": {"status": "unobserved", "interval": None, "reason": "no production outcome sample; prohibit fabricated forecast precision"},
        "scenarios": [
            {"name": "downside", "trigger": "critical defect or qualified action below floor", "action": "stop and repair"},
            {"name": "base", "trigger": "safe but interval crosses decision threshold", "action": "continue bounded test"},
            {"name": "upside", "trigger": "safe interval clears threshold", "action": "request human scale decision"},
        ],
        "reversible_recommendation": {"action": "run one zero-spend cycle", "rollback": "restore prior channel order", "automatic_execution": False},
        "source_drill_through_required": True, "causal_claim_allowed": False,
        **common_boundary,
        "truth_boundary": "This memo is decision-ready but explicitly data-sparse: it preserves lineage, uncertainty and reversibility without inventing production lift.",
    }))
    outputs.append(write("product-analytics-measurement-system.json", {
        "schema": "ProofLaunchProductAnalyticsMeasurementSystemV1", "scenario_id": SCENARIO,
        "identity_model": {"person_level_export": False, "tenant_scoped_anonymous_id": True, "consent_required": True},
        "event_contract": ["evidence_viewed", "proof_opened", "qualified_action", "design_partner_accepted", "refund_or_reversal"],
        "funnel": ["eligible_session", "evidence_viewed", "proof_opened", "qualified_action"],
        "cohort": {"assignment_time": "first eligible exposure", "point_in_time_features_only": True, "window_days": 14},
        "randomized_holdout": {"unit": "tenant-scoped eligible session", "allocation": {"evidence_first": 0.5, "control": 0.5}, "sticky_assignment": True},
        "pre_registered_stop_rules": ["stop on rights/privacy/safety failure", "do not peek before 14 days and 25 eligible sessions per arm", "stop if instrumentation loss exceeds 5%"],
        "revenue_reconciliation": {"pipeline_is_revenue": False, "net_revenue": "gross - discounts - refunds - chargebacks - taxes - variable delivery cost", "source_binding_required": True},
        "incrementality": {"estimator": "intention_to_treat", "observed": False, "causal_claim_allowed": False},
        **common_boundary,
        "truth_boundary": "This is an executable measurement contract, not an observed funnel, cohort, experiment result, causal lift or production revenue receipt.",
    }))
    outputs.append(write("seo-technical-execution.json", {
        "schema": "ProofLaunchSEOTechnicalExecutionV1", "scenario_id": SCENARIO,
        "owned_page": {"intent": "governed GTM employee evidence", "title": "Inspect a Governed GTM Employee Before You Trust It", "canonical": "https://example.invalid/prooflaunch/evidence", "indexability": "index_after_human_release_only"},
        "structured_data": {"types": ["SoftwareApplication", "FAQPage"], "claim_citations_required": True, "validation_status": "draft_not_deployed"},
        "internal_link_graph": [{"from": "/", "to": "/prooflaunch/evidence", "anchor": "inspect the evidence"}, {"from": "/prooflaunch/evidence", "to": "/design-partner", "anchor": "review design-partner criteria"}],
        "performance_audit": {"replay_command": "npm run build", "static_resource_bytes": 375526, "same_origin_api_contracts": 51, "runtime_external_resources": 0, "lighthouse_observed": False},
        "crawl_audit": {"declared_route_count": 45, "broken_internal_routes_observed": 0, "robots_or_sitemap_deployment_observed": False},
        "content_brief": {"answer_first": True, "keyword_stuffing_allowed": False, "duplicate_intent_policy": "one canonical owner per intent"},
        "measured_organic_delta": None,
        **common_boundary,
        "truth_boundary": "This dossier proves the replayable local technical and content contract. Deployment, crawling, indexing, ranking and organic lift remain unobserved.",
    }))
    agent_events = event_chain([
        {"event": "mission_started", "node": "evidence", "effect": "local_source_read"},
        {"event": "node_completed", "node": "plan", "next": "create"},
        {"event": "forced_tool_failure", "node": "create", "failure_class": "render_validation_failure", "retryable": True},
        {"event": "repair_loop_entered", "node": "repair", "iteration": 1, "maximum_iterations": 2},
        {"event": "recovery_trace", "node": "audit", "repair_verified": True, "next": "awaiting_release"},
        {"event": "approval_denial", "node": "awaiting_release", "reason": "content-bound approval token intentionally mismatched", "external_action_executed": False},
        {"event": "audit_event", "node": "blocked", "terminal": True, "publish": False, "send": False, "spend": False},
    ])
    outputs.append(write("employee-agent-execution-trace.json", {
        "schema": "ProofLaunchEmployeeAgentExecutionTraceV1", "scenario_id": SCENARIO,
        "graph": ["evidence", "plan", "create", "audit", "repair", "audit", "awaiting_release", "blocked"],
        "loop": {"node": "repair", "iterations_used": 1, "maximum_iterations": 2},
        "harness": {"maximum_actions": 12, "maximum_cost_usd": 0, "approval_required": True, "fail_closed": True},
        "events": agent_events, "event_count": len(agent_events), "hash_chain_valid": True,
        "forced_tool_failure_observed": True, "recovery_trace_observed": True, "approval_denial_observed": True,
        "external_action_executed": False,
        **common_boundary,
        "truth_boundary": "This deterministic synthetic mission exercises Graph flow, bounded repair, a forced tool failure, recovery and approval denial. It proves mechanics, not autonomous business quality or external completion.",
    }))
    outputs.append(write("advertising-creative-system.json", {
        "schema": "ProofLaunchAdvertisingCreativeSystemV1", "scenario_id": SCENARIO,
        "objective": "qualified evidence-pack inspection", "budget": {"currency": "USD", "amount": 0, "activation_authorized": False},
        "audience": {"include": ["B2B AI founders", "GTM leaders"], "audience_exclusions": ["existing design partners", "employees", "recent converters", "under-age or sensitive-trait segments"]},
        "creative_routes": [
            {"route": "decision_xray", "hook": "Your GTM plan is not a strategy until every claim has a source.", "visual": "decision graph with visible evidence edges", "cta": "Inspect the decision"},
            {"route": "proof_before_promise", "hook": "Do not trust the launch deck. Open the evidence pack.", "visual": "sealed proof object opening into source cards", "cta": "Challenge the proof"},
            {"route": "controlled_breakout", "hook": "Zero media budget. One falsifiable idea. Seven days to earn the next decision.", "visual": "three-channel experiment board with stop rules", "cta": "Review the experiment"},
        ],
        "formats": ["1:1 feed", "4:5 feed", "9:16 short video", "responsive search"],
        "incrementality_design": {"holdout": "10% eligible audience when spend is later approved", "primary_metric": "incremental qualified action", "attribution_only_is_causal": False},
        "brand_safety": {"blocked_claims": ["guaranteed growth", "Top-1", "4A-proven", "causal revenue lift"], "placement_exclusions_required": True},
        "pacing": {"mode": "draft_only", "cross_channel_cap": 3, "automatic_reallocation": False},
        "human_authority": {"spend": True, "publish": True, "audience_change": True},
        **common_boundary,
        "truth_boundary": "This is a complete inactive advertising system for human review. It contains no platform activation, impression, spend, lift or revenue observation.",
    }))
    outputs.append(write("gtm-lifecycle-execution-dossier.json", {
        "schema": "ProofLaunchGTMLifecycleExecutionDossierV1", "scenario_id": SCENARIO,
        "diagnosis": "Founder-led B2B AI launch, pre-PMF, zero paid-media budget, owner-attested proof only.",
        "strategy_binding": binding("artifacts/run-bound-multimodal-demo-v1/production-deliverables/gtm-strategy.json"),
        "asset_bindings": [binding("artifacts/run-bound-multimodal-demo-v1/production-deliverables/channel-copy.json"), binding("evidence/v10/local-campaign-pack-v1/delivery-v6/prooflaunch-hero-4k.png"), binding("artifacts/gtm-last-mile-pk-v1/video-challenger-v5/prooflaunch-three-beat-challenger-4k.mp4")],
        "approval_receipt": {"class": "synthetic_mechanics", "release_status": "approved_bundle_ready", "external_publish": False},
        "experiment_observation": {"class": "synthetic", "source": binding("evidence/v10/gtm-revenue-memory-demo.json"), "production_outcome": False, "causal_claim_allowed": False},
        "next_cycle_recommendation": {"decision": "continue_candidate_for_human_review", "change": "retain evidence-first route; test partner-community falsification lane", "human_application_required": True},
        "cross_device_memory": {"source": "cross-device-memory-execution.json", "automatic_strategy_mutation": False},
        "lifecycle_stages_covered": ["diagnosis", "strategy", "creation", "audit", "approval", "delivery_bundle", "observation", "learning", "next-cycle recommendation"],
        **common_boundary,
        "truth_boundary": "This dossier joins real local artifacts with explicitly synthetic approval, observation and learning mechanics. It is not production publication, effect, revenue, 4A preference or Top-product evidence.",
    }))
    manifest = seal({
        "schema": "ProofLaunchBlockedChallengerRepairPackV1", "scenario_id": SCENARIO,
        "repair_artifact_count": len(outputs), "artifacts": outputs,
        "external_actions": 0, "production_effect_observed": False, "four_a_quality_proven": False,
        "truth_boundary": "Seven previously thin challenger lanes now have complete, content-addressed same-brief material. Synthetic mechanics remain labeled and cannot substitute for named-product human preference or production effect.",
    })
    atomic_write_text(OUTPUT / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return manifest


def main() -> int:
    result = build()
    print(json.dumps({"repair_artifact_count": result["repair_artifact_count"], "content_sha256": result["content_sha256"], "output": str(OUTPUT)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
