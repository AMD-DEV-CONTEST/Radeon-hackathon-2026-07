from __future__ import annotations

import json
import re
import unittest
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "web" / "index.html"
APP = ROOT / "web" / "app.js"
MANIFEST = ROOT / "web" / "site10x.manifest.json"


EXPECTED_SURFACES = {
    "1166": ("/control/world-state", "Campaign World State"),
    "1167": ("/control/trajectory", "Future trajectory"),
    "1168": ("/control/topology", "Agent topology"),
    "1169": ("/control/memory", "Memory inspector"),
    "1170": ("/control/distillation", "Distillation registry"),
    "1171": ("/control/training", "Training control"),
    "1172": ("/control/audit", "Audit control"),
    "1173": ("/control/repair", "Repair control"),
    "1174": ("/control/human-gate", "Human release gate"),
    "1175": ("/control/images", "Twelve-image browser"),
    "1176": ("/control/videos", "Generated media evidence"),
    "1177": ("/control/landing", "Landing-page preview"),
    "1178": ("/control/email", "Email preview"),
    "1179": ("/control/ledger", "Evidence Ledger"),
    "1180": ("/control/performance", "Radeon performance panel"),
}


class SurfaceParser(HTMLParser):
    VOID_ELEMENTS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self) -> None:
        super().__init__()
        self.surfaces: dict[str, dict[str, object]] = {}
        self._active: str | None = None
        self._depth = 0
        self.node_count = 0
        self.ids: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        self.node_count += 1
        if attributes.get("id"):
            self.ids.append(str(attributes["id"]))
        if tag == "section" and attributes.get("data-todo"):
            todo_id = str(attributes["data-todo"])
            self._active = todo_id
            self._depth = 1
            self.surfaces[todo_id] = {
                "route": attributes.get("data-route"),
                "text": [],
                "buttons": 0,
                "forms": 0,
            }
            return
        if self._active is not None:
            if tag not in self.VOID_ELEMENTS:
                self._depth += 1
            if tag == "button":
                self.surfaces[self._active]["buttons"] += 1
            if tag == "form":
                self.surfaces[self._active]["forms"] += 1

    def handle_endtag(self, tag: str) -> None:
        if self._active is None:
            return
        self._depth -= 1
        if self._depth == 0:
            self._active = None

    def handle_data(self, data: str) -> None:
        if self._active is not None and data.strip():
            self.surfaces[self._active]["text"].append(data.strip())


class Workstream24SurfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.index = INDEX.read_text(encoding="utf-8")
        cls.app = APP.read_text(encoding="utf-8")
        cls.manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        parser = SurfaceParser()
        parser.feed(cls.index)
        cls.surfaces = parser.surfaces
        cls.node_count = parser.node_count
        cls.ids = parser.ids

    def test_document_stays_within_dom_budget_and_has_unique_targets(self) -> None:
        self.assertLessEqual(self.node_count, self.manifest["performanceBudget"]["maxDomNodes"])
        self.assertEqual(len(self.ids), len(set(self.ids)))
        for todo_id, (route, _) in EXPECTED_SURFACES.items():
            self.assertIn(f'href="{route}"', self.index, todo_id)

    def test_mission_monument_joins_real_gtm_outputs_motion_and_truth_boundaries(self) -> None:
        styles = (ROOT / "web" / "styles.css").read_text(encoding="utf-8")
        self.assertIn('class="atelier-hero"', self.index)
        self.assertIn('class="atelier-hero__gates"', self.index)
        self.assertIn('class="output-forge"', self.index)
        self.assertIn('data-specimen-panel="b2b"', self.index)
        self.assertIn('data-specimen-panel="b2c"', self.index)
        self.assertIn("<strong>0</strong> named-human wins", self.index)
        self.assertIn("<strong>0</strong> production effects attributed", self.index)
        self.assertIn('href="/control/gtm-cockpit"', self.index)
        self.assertIn('typeof document.startViewTransition === "function"', self.app)
        self.assertIn('window.matchMedia("(prefers-reduced-motion: reduce)")', self.app)
        self.assertIn("IntersectionObserver", self.app)
        self.assertIn("@media (prefers-reduced-motion: reduce)", styles)
        self.assertIn("::view-transition-new(mission-surface)", styles)

    def test_all_fifteen_source_ordered_surfaces_are_unique_and_routable(self) -> None:
        self.assertEqual(tuple(self.surfaces), tuple(EXPECTED_SURFACES))
        declared_routes = [item["path"] for item in self.manifest["routes"]]
        for todo_id, (route, heading) in EXPECTED_SURFACES.items():
            surface = self.surfaces[todo_id]
            self.assertEqual(surface["route"], route)
            self.assertIn(route, declared_routes)
            self.assertIn(f'["{route}",', self.app)
            self.assertIn(heading, " ".join(surface["text"]))

    def test_world_state_future_trajectory_and_human_gate_bind_real_api_contracts(self) -> None:
        self.assertEqual(self.surfaces["1166"]["forms"], 1)
        self.assertIn('requestJson("/v1/runs"', self.app)
        self.assertIn('human_release_required: true', self.app)
        self.assertIn('data_class: "internal"', self.app)
        self.assertIn('name="product_category"', self.index)
        self.assertIn('name="product_surface"', self.index)
        self.assertIn('name="audience_role"', self.index)
        self.assertIn('name="claim_assurance"', self.index)
        self.assertIn('name="claim_approved_by"', self.index)
        self.assertIn('name="specialist_approved_by"', self.index)
        self.assertIn('product_category: String(formData.get("product_category")', self.app)
        self.assertIn('product_surface: String(formData.get("product_surface")', self.app)
        self.assertIn('audience_role: String(formData.get("audience_role")', self.app)
        self.assertIn('claim_assurance: claimAssurance', self.app)
        self.assertIn('claim_approved_by: claimApprovedBy', self.app)
        self.assertIn('specialist_approved_by: specialistApprovedBy', self.app)
        self.assertIn('verified claim assurance requires a named accountable claim approver', self.app)
        self.assertIn('high-regulation work requires a named qualified specialist approver', self.app)
        self.assertIn('/events`', self.app)
        self.assertEqual(self.surfaces["1174"]["forms"], 1)
        self.assertIn('/approvals`', self.app)
        self.assertIn("No hidden chain of thought", " ".join(self.surfaces["1167"]["text"]))

    def test_gtm_cockpit_joins_lifecycle_truth_without_claim_or_action_upgrade(self) -> None:
        cockpit = re.search(
            r'data-route="/control/gtm-cockpit"[\s\S]*?</section>',
            self.index,
        ).group(0)
        self.assertIn('href="/control/gtm-cockpit"', self.index)
        self.assertIn('id="gtm-cockpit-status"', cockpit)
        self.assertIn('id="cockpit-run-stage"', cockpit)
        self.assertIn('id="cockpit-context"', cockpit)
        self.assertIn('id="cockpit-channel-focus"', cockpit)
        self.assertIn('id="cockpit-workspace"', cockpit)
        self.assertIn('id="cockpit-effect"', cockpit)
        self.assertIn('id="cockpit-revenue"', cockpit)
        self.assertIn('id="cockpit-learning"', cockpit)
        self.assertIn('id="last-mile-quality-status"', cockpit)
        self.assertIn('id="last-mile-quality-lanes"', cockpit)
        self.assertIn('id="last-mile-quality-boundary"', cockpit)
        self.assertIn('id="platform-capability-status"', cockpit)
        self.assertIn('id="platform-capability-surface"', cockpit)
        self.assertIn('id="platform-capability-grid"', cockpit)
        self.assertIn('id="platform-capability-boundary"', cockpit)
        self.assertIn('id="integrated-campaign-status"', cockpit)
        self.assertIn('id="integrated-campaign-model"', cockpit)
        self.assertIn('id="integrated-campaign-core"', cockpit)
        self.assertIn('id="integrated-campaign-phases"', cockpit)
        self.assertIn('id="integrated-campaign-emails"', cockpit)
        self.assertIn('id="integrated-campaign-media"', cockpit)
        self.assertIn('id="integrated-campaign-experiments"', cockpit)
        self.assertIn('id="integrated-campaign-boundary"', cockpit)
        self.assertIn('id="codex-adaptation-status"', cockpit)
        self.assertIn('id="codex-adaptation-archetype"', cockpit)
        self.assertIn('id="codex-adaptation-core"', cockpit)
        self.assertIn('id="codex-adaptation-output"', cockpit)
        self.assertIn('id="codex-adaptation-boundary"', cockpit)
        self.assertIn('id="concrete-pk-status"', cockpit)
        self.assertIn('id="concrete-pk-categories"', cockpit)
        self.assertIn('id="concrete-pk-boundary"', cockpit)
        self.assertIn('id="named-baseline-status"', cockpit)
        self.assertIn('id="named-baseline-categories"', cockpit)
        self.assertIn('id="named-baseline-boundary"', cockpit)
        self.assertIn('id="cockpit-next-actions"', cockpit)
        self.assertEqual(cockpit.count('data-action="load-synthetic-lifecycle-demo"'), 1)
        self.assertIn("load synthetic proof", cockpit.lower())
        self.assertIn("cannot publish, send, spend, mutate strategy", cockpit)
        self.assertIn("No auto execution", cockpit)
        self.assertIn('["/control/gtm-cockpit",', self.app)
        self.assertIn('/gtm-cockpit`', self.app)
        self.assertIn('cockpit?.schema === "ProofLaunchGTMCockpitV1"', self.app)
        self.assertIn("computedDigest === suppliedDigest", self.app)
        self.assertIn('/v1/public-signal-pilot', self.app)
        self.assertIn('/v1/last-mile-production-quality', self.app)
        self.assertIn('ProofLaunchGTMProductionQualityEvaluationV1', self.app)
        self.assertIn('ladder.current_state', self.app)
        self.assertIn('/v1/platform-capability-showcase', self.app)
        self.assertIn('/v1/codex-integrated-campaign-portfolio', self.app)
        self.assertIn('/v1/codex-campaign-adaptation-summary', self.app)
        self.assertIn('summary.case_count === 456', self.app)
        self.assertIn('summary.model_call_count === 0', self.app)
        self.assertIn('summary.release_eligible_count === 0', self.app)
        self.assertIn('/v1/concrete-product-effect-pk', self.app)
        self.assertIn('/v1/named-product-baseline-capture-kit', self.app)
        self.assertIn('/v1/named-product-pk-portfolio', self.app)
        self.assertIn('/v1/named-product-challenger-admission', self.app)
        self.assertIn('/v1/gtm-hybrid-quality-control', self.app)
        self.assertIn('/v1/gtm-adaptive-capability-graph', self.app)
        self.assertIn('adaptiveGraph.coverage?.context_count === 6912', self.app)
        self.assertIn('adaptiveGraph.coverage?.lane_decision_count === 89856', self.app)
        self.assertIn('adaptiveGraph.executor_binding?.included_in_plan_identity === false', self.app)
        self.assertIn('adaptive_distribution_aggregation === "weakest_link_operating_floor"', self.app)
        self.assertIn('adaptive_hardware_and_provider_in_plan_identity === false', self.app)
        self.assertIn('adaptive_automatic_external_actions === 0', self.app)
        self.assertIn('creative_alpha_plan_sha256', self.app)
        self.assertIn('creative_alpha_style_ids?.length >= 2', self.app)
        self.assertIn('creative_alpha_platform_grammar_count === 2', self.app)
        self.assertIn('creative_alpha_external_actions === 0', self.app)
        self.assertIn('creative_alpha_human_release_required === true', self.app)
        self.assertIn('creative styles ${creativeStyles.join', self.app)
        self.assertIn('ProofLaunchGTMLastMileProductionQualityBenchmarkV1', self.app)
        self.assertIn('ProofLaunchPlatformCapabilityShowcasePublicV1', self.app)
        self.assertIn('showcase.candidate_count === 26', self.app)
        self.assertIn('showcase.pre_human_quality_pass_count === 26', self.app)
        self.assertIn('showcase.release_eligible_count === 0', self.app)
        self.assertIn('showcase.human_review_completed_count === 0', self.app)
        self.assertIn('showcase.production_effect_observed === false', self.app)
        self.assertIn('26/26 craft · 0 release eligible · 0 human/effect', self.app)
        self.assertIn('ProofLaunchCodexIntegratedCampaignPortfolioV1', self.app)
        self.assertIn('portfolio.platform_candidate_count === 26', self.app)
        self.assertIn('portfolio.email_count === 8', self.app)
        self.assertIn('portfolio.production_direction_count === 6', self.app)
        self.assertIn('portfolio.search_geo_node_count === 14', self.app)
        self.assertIn('portfolio.experiment_count === 8', self.app)
        self.assertIn('portfolio.release_eligible_count === 0', self.app)
        self.assertIn('portfolio.human_review_completed_count === 0', self.app)
        self.assertIn('portfolio.production_effect_observed === false', self.app)
        self.assertIn('2 systems · 26 native assets · 8 emails · 8 experiments', self.app)
        self.assertIn('ProofLaunchConcreteProductEffectPKLedgerV1', self.app)
        self.assertIn('ProofLaunchNamedProductBaselineCaptureKitPublicV1', self.app)
        self.assertIn('portfolio.completed_product_pk_rows === 0', self.app)
        self.assertIn('last_mile_generated_execution_quality', self.app)
        self.assertIn('portfolio.four_a_quality_proven === false', self.app)
        self.assertIn('portfolio.reference_product_row_count === 130', self.app)
        self.assertIn('0/130 named-product PK', self.app)
        self.assertIn('6,912 adaptive contexts · 13/13 local lanes · 130 PK slots · 0 wins', self.app)
        self.assertIn('ProofLaunchGTMHybridQualityControlPublicV1', self.app)
        self.assertIn('qualityControl.portfolio?.job_count === 130', self.app)
        self.assertIn('qualityControl.routing_invariants?.jobs_route_by_capability_not_vendor === true', self.app)
        self.assertIn('qualityControl.routing_invariants?.radeon_required_for_product_closure === false', self.app)
        self.assertIn('automatic_pk_promotion_enabled === false', self.app)
        self.assertIn('ProofLaunchPublicSignalGTMPilotPublicV1', self.app)
        self.assertIn('pilot.automatic_strategy_mutation_executed === false', self.app)
        self.assertIn('pilot.automatic_schedule_mutation_executed === false', self.app)
        self.assertIn('pilot.external_release_executed === false', self.app)
        self.assertIn("cockpit.four_a_effect_claim_eligible === false", self.app)
        self.assertIn("cockpit.top1_claim_eligible === false", self.app)
        self.assertIn("ProofLaunchGTMCapabilityEffectMatrixV1", self.app)
        self.assertIn("capability_effect_matrix?.capability_count === 11", self.app)
        self.assertIn("capability_effect_matrix?.generated_deliverable_count === observedGeneratedCount", self.app)
        self.assertIn("capability_effect_matrix?.named_human_quality_count === observedHumanCount", self.app)
        self.assertIn("capability_effect_matrix?.production_effect_attributed_count === 0", self.app)
        self.assertIn("${capabilityMatrix.generated_deliverable_count} run-bound generated deliverables", self.app)
        self.assertIn("automatic_strategy_mutation_enabled === false", self.app)
        self.assertIn('/v1/demo/synthetic-lifecycle', self.app)
        self.assertIn('demo?.schema === "ProofLaunchSyntheticLifecycleDemoV1"', self.app)
        self.assertIn('demo.production_effect_proven === false', self.app)
        self.assertIn('demo.four_a_effect_claim_eligible === false', self.app)
        self.assertIn("cross_device_memory?.human_promoted_only === true", self.app)
        self.assertIn("cross_device_memory?.frozen_at_run_creation === true", self.app)
        self.assertIn("cross_device_memory?.human_application_required === true", self.app)
        self.assertIn(
            "cross_device_memory?.automatic_strategy_mutation_executed === false",
            self.app,
        )
        self.assertIn(
            "cross_device_memory?.automatic_schedule_mutation_executed === false",
            self.app,
        )
        self.assertIn(
            "cross_device_memory?.automatic_budget_activation_executed === false",
            self.app,
        )
        self.assertIn("context-eligible", self.app)
        self.assertIn("human application required", self.app)
        self.assertIn('path === "/control/gtm-cockpit"', self.app)
        manifest_routes = {row["path"] for row in self.manifest["routes"]}
        self.assertIn("/control/gtm-cockpit", manifest_routes)

    def test_generated_media_surface_loads_hash_verified_campaign_pack_without_quality_upgrade(self) -> None:
        videos = " ".join(self.surfaces["1176"]["text"])
        self.assertIn("4K campaign film", videos)
        self.assertIn("named-human creative, business-effect and Radeon gates remain open", videos)
        self.assertIn('requestJson("/v1/local-campaign-pack")', self.app)
        self.assertIn("local-campaign-pack-mechanical-not-product", self.app)
        self.assertIn("four_a_preference_proven", self.app)
        self.assertIn("product_admission_passed", self.app)
        self.assertIn("08 FULL LIFECYCLE", self.app)
        self.assertIn("minimum_cases_per_failure_mode", self.app)
        self.assertIn("positive_paths_require_human_review", self.app)
        self.assertIn("12B STRATEGY PORTFOLIO", self.app)
        self.assertIn("PORTFOLIO CHANNELS", self.app)
        self.assertIn("PORTFOLIO MAX JACCARD", self.app)
        self.assertIn("PORTFOLIO UNIVERSAL CLAIM", self.app)
        self.assertIn("strategy_portfolio", self.app)

    def test_tenant_principal_is_session_bound_and_all_protected_fetches_are_authenticated(self) -> None:
        tenants = self.index.split('data-route="/admin/tenants"', 1)[1].split(
            'data-route="/admin/policies"', 1
        )[0]
        self.assertIn('id="tenant-session-form"', tenants)
        self.assertIn('type="password"', tenants)
        self.assertIn('minlength="24"', tenants)
        self.assertIn("server derives tenant identity", tenants)
        self.assertIn("sessionStorage", tenants)
        self.assertIn('const tenantSessionKey = "prooflaunch-tenant-token-v1"', self.app)
        self.assertIn("window.sessionStorage.setItem(tenantSessionKey, token)", self.app)
        self.assertNotIn("localStorage.setItem(tenantSessionKey", self.app)
        self.assertIn("Authorization: `Bearer ${state.tenantToken}`", self.app)
        self.assertIn("headers: tenantHeaders()", self.app)
        self.assertIn("ProofLaunchRunEventBatchV1", self.app)
        self.assertIn('"Last-Event-ID": String(state.lastEventId)', self.app)
        self.assertNotIn("new EventSource", self.app)
        self.assertIn("state.runId = null", self.app)

    def test_world_state_posts_progressive_strategy_diagnosis_without_weakening_gates(self) -> None:
        strategy_fields = (
            "business_model",
            "lifecycle",
            "budget",
            "industry",
            "industry_risk",
            "audience_name",
            "core_problem",
            "desired_outcome",
            "buying_context",
            "brand_purpose",
            "brand_promise",
            "brand_voice",
            "offer",
            "landing_url",
            "schedule_timezone",
        )
        world_state = re.search(
            r'data-todo="1166"[\s\S]*?</section>', self.index
        ).group(0)
        self.assertIn("<details", world_state)
        self.assertIn("Refine audience, brand, and offer", world_state)
        self.assertIn('name="budget"', world_state)
        self.assertIn('data-option-set="budget" data-selected="zero"', world_state)
        self.assertIn('budget: [["zero", "Zero media spend"]', self.app)
        for field in strategy_fields:
            self.assertIn(f'name="{field}"', world_state)
            self.assertIn(f'formData.get("{field}")', self.app)
        self.assertIn("strategy: {", self.app)
        self.assertIn('name="creative_signal_snapshot"', world_state)
        self.assertIn("stageCreativeSignalSnapshot", self.app)
        self.assertIn("creative_signal_snapshot: state.signalArtifact.sha256", self.app)
        self.assertIn('audience_problem: String(formData.get("core_problem")', self.app)
        self.assertIn('audience_outcome: String(formData.get("desired_outcome")', self.app)
        self.assertIn('customer_promise: String(formData.get("brand_promise")', self.app)
        self.assertIn('type="url"', world_state)
        self.assertIn("Reserved non-routable default", world_state)
        self.assertIn("rightsConfirmation", self.app)
        self.assertIn("human_release_required: true", self.app)
        self.assertNotRegex(world_state, r"(?i)(top.?1|viral|爆款|营收|revenue|guarantee)")

    def test_topology_memory_distillation_training_audit_and_repair_are_fail_closed(self) -> None:
        topology = " ".join(self.surfaces["1168"]["text"])
        self.assertIn("Fixed business topology", topology)
        self.assertIn("Audit-repair autonomy only", topology)
        self.assertIn("Authoritative state owner", topology)
        self.assertIn("No release permission", topology)
        memory = " ".join(self.surfaces["1169"]["text"])
        self.assertIn("Review gated", memory)
        self.assertIn("Import never applies immediately", memory)
        self.assertIn("Record immutable review", memory)
        self.assertIn("named operator must approve the exact capsule", memory)
        self.assertIn('requestJson("/v1/model-cards")', self.app)
        self.assertIn('path === "/control/videos") probeProductReadiness()', self.app)
        self.assertIn('path === "/control/training") {', self.app)
        self.assertIn("LOCAL MODEL EVIDENCE · HASH-BOUND READINESS", self.app)
        self.assertIn("8-CASE BENCHMARK STATUS", self.app)
        self.assertIn("BENCHMARK PREFLIGHT PASSED", self.app)
        self.assertIn("BENCHMARK BLOCKER", self.app)
        self.assertIn("PORTFOLIO HUMAN REVIEWS", self.app)
        self.assertIn("PORTFOLIO PROMOTION PASSED", self.app)
        self.assertIn('id="training-readiness-badge"', self.index)
        self.assertIn('id="training-evidence-output"', self.index)
        self.assertIn('requestJson("/v1/evals/leaderboard")', self.app)
        for todo_id in ("1171", "1172", "1173"):
            text = " ".join(self.surfaces[todo_id]["text"])
            self.assertRegex(text, r"(?i)(not observed|unresolved|blocked|bounded|absent)")

    def test_training_surface_runs_invitation_bound_five_human_blind_review(self) -> None:
        training = re.search(
            r'data-todo="1171"[\s\S]*?</section>\s*<a class="button',
            self.index,
        ).group(0)
        self.assertIn('id="blind-review-access-form"', training)
        self.assertIn('id="blind-review-task-list"', training)
        self.assertIn('id="blind-review-scope"', training)
        self.assertIn('data-option-set="blindScope" data-selected="portfolio"', training)
        self.assertIn("9-case portfolio · 54 pairs", self.app)
        self.assertIn("Campaign visual system · V5 vs V6", self.app)
        self.assertIn("Judge calibration · 100 cases / 300 labels", self.app)
        self.assertIn('type="password"', training)
        self.assertIn("assigns each invited reviewer 54 randomized pairs", training)
        self.assertIn('"/v1/portfolio-blind-review"', self.app)
        self.assertIn('"/v1/blind-review"', self.app)
        self.assertIn('"/v1/judge-calibration"', self.app)
        self.assertIn('"/v1/campaign-pack-blind-review"', self.app)
        self.assertIn('`${blindReviewBase(scope)}/status`', self.app)
        self.assertIn('`${blindReviewBase(scope)}/tasks?slot=', self.app)
        self.assertIn('`${base}/reviews`', self.app)
        self.assertIn('requestJson("/v1/blind-review/selections"', self.app)
        self.assertIn('"X-ProofLaunch-Reviewer-Token"', self.app)
        self.assertIn("blindReviewDigest(review)", self.app)
        self.assertIn("review_content_sha256: null", self.app)
        self.assertIn("ProofLaunchJudgeCalibrationHumanLabelV1", self.app)
        self.assertIn("judgeCalibrationAttestation", self.app)
        self.assertIn("Model prediction, provider identity, private mapping", self.app)
        self.assertIn("Submit immutable calibration label", self.app)
        self.assertIn("ProofLaunchCampaignPackVisualHumanReviewV1", self.app)
        self.assertIn("campaignPackReviewAttestation", self.app)
        self.assertIn("cross_format_extensibility", self.app)
        self.assertIn("Submit immutable campaign review", self.app)
        self.assertIn("Download offline review kit", self.app)
        self.assertIn("Submit returned review JSON", self.app)
        self.assertIn('/offline-kit?slot=', self.app)
        self.assertIn("returned review does not match this invitation-bound task", self.app)
        self.assertIn("Automatic switch=false; publish=false; premium/effect claim=false", self.app)
        self.assertIn('requestJson("/v1/launch-proof/status")', self.app)
        self.assertIn("LAUNCH PROOF CONTROL · DYNAMIC, FAIL-CLOSED", self.app)
        self.assertIn("CRAFT / TOP-1 / CAUSAL REVENUE", self.app)
        self.assertIn("GEMMA 3 12B CHALLENGER", self.app)
        self.assertIn("CHALLENGER HUMAN / EFFECT", self.app)
        self.assertIn("probeProductReadiness().then(() => probeLaunchProofControl())", self.app)
        self.assertIn("Candidate identity, provider, territory", training)
        self.assertIn("causal lift/revenue/Top-1 claim=false", self.app)
        self.assertIn("Human recommendation is not automatic winner selection", training)
        self.assertIn('id="blind-review-selection-form"', training)
        self.assertIn("Admit prompt seed only; no GPU, spend, publish, or effect claim", training)

    def test_workspace_create_hands_off_to_real_persisted_agent_run(self) -> None:
        create = re.search(
            r'data-route="/workspace/create"[\s\S]*?</section>\s*<section class="route-panel" data-route="/workspace/verify"',
            self.index,
        ).group(0)
        self.assertIn('id="create-run-handoff"', create)
        self.assertIn('href="/control/world-state"', create)
        self.assertIn("persisted Agent worker", create)
        self.assertIn("456 industry cases", create)
        self.assertIn("270 immutable reviews", create)
        self.assertNotIn("Enter waiting state", create)
        self.assertNotIn("Website runtime</dt><dd>Not connected", create)
        self.assertIn('setText("create-runtime-state"', self.app)
        self.assertIn("Brief saved and carried into Campaign World State", self.app)
        self.assertIn('updateCreateControls();', self.app)

    def test_twelve_image_slots_remain_empty_while_real_qualification_media_is_labeled(self) -> None:
        image_section = re.search(
            r'data-todo="1175"[\s\S]*?</section>', self.index
        ).group(0)
        video_section = re.search(
            r'data-todo="1176"[\s\S]*?</section>', self.index
        ).group(0)
        self.assertEqual(image_section.count("Not generated"), 12)
        self.assertNotRegex(image_section, r"<(?:img|video)\b")
        self.assertIn("<audio", video_section)
        self.assertIn("<video", video_section)
        self.assertIn("local generation path, not production quality", video_section)
        self.assertIn("product gate failed", video_section)
        self.assertIn("local-qualification-not-product", self.app)

    def test_channel_previews_cannot_publish_or_send(self) -> None:
        landing = " ".join(self.surfaces["1177"]["text"])
        email = " ".join(self.surfaces["1178"]["text"])
        self.assertIn("NON-PUBLISHABLE SOURCE-BOUND DRAFT", landing)
        self.assertIn("CTA disabled", landing)
        self.assertIn("send disabled", email)
        self.assertIn("No message has been sent", email)
        self.assertIn("renderCampaignWorkspace", self.app)
        self.assertIn("ProofLaunchCampaignWorkspacePublicV1", self.app)
        self.assertIn("ProofLaunchLandingPageDraftV1", self.app)
        self.assertIn("ProofLaunchLifecycleEmailDraftV1", self.app)
        self.assertIn("workspace.automatic_publish_enabled === false", self.app)
        self.assertIn("workspace.automatic_send_enabled === false", self.app)
        self.assertIn("workspace.automatic_spend_enabled === false", self.app)

    def test_channel_system_renders_the_approval_bound_runtime_portfolio(self) -> None:
        channels = self.index.split('data-route="/front/channels"', 1)[1].split(
            'data-route="/front/experiments"', 1
        )[0]
        self.assertIn('id="channel-portfolio-grid"', channels)
        self.assertIn('id="channel-portfolio-status"', channels)
        self.assertIn('id="channel-strategy-focus"', channels)
        self.assertIn('id="channel-strategy-market"', channels)
        self.assertIn('id="channel-strategy-budget"', channels)
        self.assertIn("renderChannelPortfolio(preview?.gtm_strategy?.channel_portfolio)", self.app)
        self.assertIn('id="industry-profile-status"', channels)
        self.assertIn('id="industry-profile-archetype"', channels)
        self.assertIn('id="industry-profile-conversion"', channels)
        self.assertIn('id="industry-profile-engine"', channels)
        self.assertIn('id="industry-profile-economics"', channels)
        self.assertIn(
            "renderIndustryGTMProfile(preview?.gtm_strategy?.industry_gtm_profile)",
            self.app,
        )
        self.assertIn('profile?.schema === "ProofLaunchIndustryGTMProfileV1"', self.app)
        self.assertIn("profile.external_activation_executed === false", self.app)
        self.assertIn("profile.automatic_budget_allocation_enabled === false", self.app)
        self.assertIn('portfolio?.schema !== "ProofLaunchChannelPortfolioV1"', self.app)
        self.assertIn("validRows.length !== 12", self.app)
        self.assertIn("automatic allocation disabled", self.app)
        self.assertIn('id="content-calendar-list"', channels)
        self.assertIn('id="content-calendar-status"', channels)
        self.assertIn("renderContentCalendar(preview?.gtm_strategy?.content_calendar)", self.app)
        self.assertIn('calendar?.schema === "ProofLaunchContentCalendarV1"', self.app)
        self.assertIn("0 auto publishes", self.app)
        self.assertIn('id="breakout-loop-steps"', channels)
        self.assertIn('id="breakout-loop-status"', channels)
        self.assertIn('id="breakout-loop-thesis"', channels)
        self.assertIn(
            "renderBreakoutGrowthLoop(preview?.gtm_strategy?.breakout_growth_loop)",
            self.app,
        )
        self.assertIn('loop?.schema === "ProofLaunchBreakoutGrowthLoopV1"', self.app)
        self.assertIn("core_loop_functions_without_paid_media", self.app)
        self.assertIn("0 auto actions", self.app)
        self.assertIn('id="creative-challenger-list"', channels)
        self.assertIn('id="creative-challenger-status"', channels)
        self.assertIn('id="creative-challenger-boundary"', channels)
        self.assertIn(
            "renderTextCreativeChallenger(preview?.gtm_strategy?.text_creative_challenger)",
            self.app,
        )
        self.assertIn('challenger.maximum_model_calls === 3', self.app)
        self.assertIn('challenger.execution_policy?.maximum_concurrency === 1', self.app)
        self.assertIn('challenger.execution_policy?.default_retry_rounds === 0', self.app)
        self.assertIn('gate.textContent = "NOT GENERATED"', self.app)
        self.assertNotIn("One strategy. Nine native expressions.", channels)

    def test_experiment_and_learning_surfaces_bind_aggregate_outcomes(self) -> None:
        experiment = self.index.split('data-route="/front/experiments"', 1)[1].split(
            'data-route="/front/learning"', 1
        )[0]
        learning = self.index.split('data-route="/front/learning"', 1)[1].split(
            'data-route="/front/visuals"', 1
        )[0]
        self.assertIn('id="effect-observation-form"', experiment)
        self.assertIn('name="source_reference_sha256"', experiment)
        self.assertIn('name="deduplicated"', experiment)
        self.assertIn('name="bot_filter_applied"', experiment)
        self.assertIn('id="learning-decision"', learning)
        self.assertIn('id="learning-promotion-form"', learning)
        self.assertIn('id="learning-promote-submit"', learning)
        self.assertIn('/outcomes`', self.app)
        self.assertIn('/production-observation-kit`', self.app)
        self.assertIn('Download production observation kit', self.app)
        self.assertIn('Load observation JSON', self.app)
        self.assertIn('Record publication receipt', self.app)
        self.assertIn('/publication-receipts`', self.app)
        self.assertIn('Submit economics JSON', self.app)
        self.assertIn('payload?.effect_observation_sha256 !== observation.observation_sha256', self.app)
        self.assertIn('/learning-memories`', self.app)
        self.assertIn('/promotions`', self.app)
        self.assertIn('automatic strategy changes', experiment)
        self.assertIn('state.effectContract.experiment_id', self.app)
        self.assertIn('state.effectContract.strategy_plan_sha256', self.app)
        self.assertIn('"X-ProofLaunch-Approval-Token": token', self.app)
        self.assertNotRegex(experiment, r'name="(?:email|user_id|username|comment|transcript)"')

    def test_public_creative_signals_require_hash_bound_collector_provenance(self) -> None:
        world_state = self.index.split('data-route="/control/world-state"', 1)[1].split(
            'data-route="/control/trajectory"', 1
        )[0]
        self.assertIn('name="creative_signal_snapshot"', world_state)
        self.assertIn('name="creative_signal_collection_receipt"', world_state)
        self.assertIn("stageCreativeSignalCollectionReceipt", self.app)
        self.assertIn("ProofLaunchOpenSourceSocialCollectionRunV2", self.app)
        self.assertIn("payload?.creative_signal_snapshot_sha256 !== snapshotContentSha256", self.app)
        self.assertIn("creative_signal_collection_receipt: state.signalReceiptArtifact.sha256", self.app)
        self.assertIn('data_class: "internal"', self.app)
        self.assertIn('creative_signal_data_class: "public"', self.app)
        self.assertIn("captcha_or_auth_bypass_attempted !== false", self.app)
        self.assertIn("raw_content_training_admitted !== false", self.app)

    def test_ledger_and_performance_use_measured_same_origin_endpoints(self) -> None:
        self.assertIn('/bundle`', self.app)
        self.assertIn('external release', " ".join(self.surfaces["1179"]["text"]).lower())
        self.assertIn('requestJson("/v1/health")', self.app)
        performance = " ".join(self.surfaces["1180"]["text"])
        self.assertIn("No telemetry", performance)
        self.assertIn("Not observed", performance)
        self.assertEqual(len(self.manifest["sameOriginApiRoutes"]), 60)
        self.assertIn("/v1/realtime-preset-campaigns", self.manifest["sameOriginApiRoutes"])
        self.assertIn("/v1/local-evaluation-session", self.manifest["sameOriginApiRoutes"])
        self.assertNotRegex(self.app, r"fetch\s*\(\s*[\"'`]https?://")

    def test_frontier_console_is_one_end_to_end_generation_and_output_workspace(self) -> None:
        frontier = self.index.split('data-route="/control/frontier-gtm"', 1)[1].split(
            'data-route="/spec"', 1
        )[0]
        self.assertEqual(frontier.count("data-frontier-flow-step="), 6)
        self.assertEqual(frontier.count("data-frontier-flow-action="), 6)
        self.assertIn('id="frontier-stage-guide"', frontier)
        self.assertIn('id="contest-fit-panel"', frontier)
        self.assertIn('Track 1 submission fit', frontier)
        self.assertIn('Multimodal AI', frontier)
        self.assertEqual(frontier.count("data-frontier-recipe="), 5)
        self.assertIn('id="generate-realtime-campaign"', frontier)
        self.assertIn('Run creative council', frontier)
        self.assertIn('id="frontier-cloud-submit"', frontier)
        self.assertIn('class="frontier-brief-details frontier-wide"', frontier)
        self.assertEqual(frontier.count("data-frontier-output-tab="), 4)
        self.assertEqual(frontier.count("data-frontier-output-panel="), 4)
        self.assertIn('every option below is clickable', frontier)
        self.assertIn('id="frontier-media-gallery"', frontier)
        self.assertIn('id="frontier-agent-orchestration"', frontier)
        self.assertIn('id="frontier-platform-kits"', frontier)
        self.assertIn('Agent strategy', frontier)
        self.assertIn('Platform kits', frontier)
        self.assertIn('12 genomes · 6 nodes · 3 finalists', frontier)
        self.assertIn('id="frontier-download-manifest"', frontier)
        self.assertIn('id="inspector-open-assets"', self.index)
        self.assertIn('void runRealtimePresetCampaign(form, button)', self.app)
        self.assertIn('selectFrontierOutputTab("assets")', self.app)
        self.assertIn('showFrontierStageGuide', self.app)
        self.assertIn('renderFrontierInspector(frontierCurrentResult, manifest)', self.app)
        self.assertIn('renderFrontierAgentOrchestration(result.agent_orchestration)', self.app)
        self.assertIn('renderFrontierPlatformKits(result)', self.app)
        self.assertIn('realtime-preset-v8-${identity}', self.app)
        self.assertIn('id="frontier-uniqueness-receipt"', frontier)
        self.assertIn('new Blob([`${JSON.stringify(frontierCurrentResult, null, 2)}', self.app)


if __name__ == "__main__":
    unittest.main()
