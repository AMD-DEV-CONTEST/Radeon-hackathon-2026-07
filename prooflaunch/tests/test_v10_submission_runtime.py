from __future__ import annotations

import hashlib
import io
import json
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZipFile

from PIL import Image, ImageDraw

from prooflaunch_remix.audience_pulse import LexicalAudiencePulse
from prooflaunch_remix.contracts import ReleaseApprovalKind, Stage
from prooflaunch_remix.gtm_learning_memory import (
    compile_project_learning_context,
    promoted_memory_payload,
)
from prooflaunch_remix.gtm_memory_capsule import issue_memory_capsule
from prooflaunch_remix.runtime import build_supervisor
from prooflaunch_remix.v10_submission_runtime import (
    AgencyRunWorker,
    ProductionAgencyService,
    ProductionLaunchRequest,
    ProductionRuntimeError,
)
from prooflaunch_remix.v10_submission_store import ConflictError, SubmissionStore


def _png_bytes() -> bytes:
    stream = io.BytesIO()
    image = Image.new("RGBA", (96, 128), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((8, 6, 88, 120), radius=14, fill=(240, 244, 255, 255))
    draw.rectangle((26, 28, 70, 84), fill=(24, 86, 170, 255))
    image.save(stream, format="PNG")
    return stream.getvalue()


def _supervisor_factory(event_sink):
    return build_supervisor(
        audience=LexicalAudiencePulse(),
        seed=20260803,
        canvas_overrides={"TikTok": (360, 640)},
        event_sink=event_sink,
    )


class ProductionAgentRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "production-store"
        self.store = SubmissionStore(self.root)
        self.worker = AgencyRunWorker(
            self.store,
            worker_id="runtime-test-worker",
            supervisor_factory=_supervisor_factory,
        )
        self.service = ProductionAgencyService(self.store, worker=self.worker)
        self.png = _png_bytes()
        self.png_sha256 = hashlib.sha256(self.png).hexdigest()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def upload_png(self) -> None:
        self.store.artifacts.put(
            io.BytesIO(self.png),
            expected_sha256=self.png_sha256,
            media_type="image/png",
        )

    def seed_conflicting_strategy_memories(self) -> None:
        applicability = {
            "industry": "unspecified",
            "business_model": "b2c",
            "lifecycle": "launch",
            "budget": "zero",
            "industry_risk": "standard",
            "market": "japan",
        }
        for index, directive in enumerate(
            (
                "continue_candidate_for_human_review",
                "revise_one_variable_then_retest",
            ),
            start=1,
        ):
            source_run_id = f"source-strategy-memory-{index}"
            self.store.create_run(
                source_run_id,
                {
                    "org_id": "org-local",
                    "project_id": "project-local",
                    "campaign_id": f"source-campaign-{index}",
                },
            )
            observation = {
                "observation_id": f"source-observation-{index}",
                "observation_sha256": str(index) * 64,
                "experiment_id": f"source-experiment-{index}",
                "strategy_plan_sha256": ("a" if index == 1 else "b") * 64,
                "channel": "short_video_organic",
                "derived_rates": {"qualified_action_rate": 0.1 + index / 100},
                "baseline_derived_rates": {"qualified_action_rate": 0.08},
                "evidence_class": "observational_attribution",
                "next_cycle_decision": directive,
                "observed_sample_gate_passed": True,
                "baseline_sample_gate_passed": True,
                "comparison_ready": True,
                "zero_budget_contract_breach": False,
            }
            self.store.record_learning_memory(
                memory_id=f"strategy-memory-{index}",
                org_id="org-local",
                project_id="project-local",
                source_run_id=source_run_id,
                observation_id=f"source-observation-{index}",
                approved_by=f"reviewer-{index}@example.test",
                reason="Approved aggregate memory for conflict-arbitration testing.",
                payload=promoted_memory_payload(
                    observation,
                    applicability_context=applicability,
                ),
                approved_at=datetime(
                    2026,
                    8,
                    2,
                    index,
                    tzinfo=timezone.utc,
                ),
            )

    def test_named_conflict_resolution_applies_only_to_later_frozen_run(self) -> None:
        self.seed_conflicting_strategy_memories()
        self.upload_png()
        source_run = self.service.create_run(
            self.payload(
                request_id="request-memory-conflict",
                campaign_id="campaign-memory-conflict",
            )
        )["run_id"]
        self.assertEqual(self.worker.process_one().status, "awaiting_release")
        source_strategy_path = self.worker._find_prepared_state(source_run)[0].output_path / (
            "gtm-strategy.json"
        )
        source_bytes_before = source_strategy_path.read_bytes()
        source_strategy = json.loads(source_bytes_before)
        decision = source_strategy["strategy_memory_decision"]
        application = source_strategy["strategy_memory_application"]
        self.assertEqual(decision["conflict_count"], 1)
        self.assertEqual(
            application["status"], "blocked_pending_named_human_resolution"
        )
        self.assertEqual(application["selected_directives"], [])

        resolution = self.service.resolve_strategy_memory_conflict(
            source_run,
            authenticated_resolver="Named GTM Owner",
            base_decision_sha256=decision["decision_sha256"],
            channel="short_video_organic",
            winner_memory_id="strategy-memory-2",
            reason="Select the later controlled aggregate result for the next run only.",
        )
        self.assertFalse(resolution["applies_to_source_run"])
        self.assertTrue(resolution["available_to_future_runs"])
        self.assertEqual(source_strategy_path.read_bytes(), source_bytes_before)
        source_cockpit = self.service.gtm_cockpit(source_run)
        self.assertEqual(
            source_cockpit["cross_device_memory"]["effective_application_status"],
            "blocked_pending_named_human_resolution",
        )
        self.assertTrue(
            source_cockpit["cross_device_memory"]["future_resolution_recorded"]
        )
        self.assertEqual(
            source_cockpit["next_best_actions"][0]["id"],
            "create_run_with_frozen_memory_resolution",
        )

        next_run = self.service.create_run(
            self.payload(
                request_id="request-memory-conflict-next",
                campaign_id="campaign-memory-conflict-next",
            )
        )["run_id"]
        frozen_resolutions = self.store.linked_artifact(
            next_run,
            "approved_strategy_memory_resolutions",
        )
        self.assertEqual(
            json.loads(
                self.store.artifacts.resolve_server_path(
                    frozen_resolutions.sha256
                ).read_text(encoding="utf-8")
            )["resolution_count"],
            1,
        )
        self.assertEqual(self.worker.process_one().status, "awaiting_release")
        next_strategy = self.strategy_json(next_run, "gtm-strategy.json")
        next_application = next_strategy["strategy_memory_application"]
        self.assertEqual(
            next_application["status"],
            "resolved_pending_named_human_application",
        )
        self.assertEqual(next_application["resolved_conflict_count"], 1)
        self.assertEqual(next_application["unresolved_conflict_channels"], [])
        self.assertEqual(
            next_application["selected_directives"][0]["memory_id"],
            "strategy-memory-2",
        )
        self.assertFalse(next_application["automatic_strategy_mutation_executed"])
        next_cockpit = self.service.gtm_cockpit(next_run)
        self.assertEqual(
            next_cockpit["cross_device_memory"]["effective_application_status"],
            "resolved_pending_named_human_application",
        )
        self.assertEqual(
            next_cockpit["cross_device_memory"]["resolved_conflict_count"], 1
        )

    def test_portable_learning_is_pending_until_review_then_enters_new_run_snapshot(self) -> None:
        context = compile_project_learning_context(
            [
                {
                    "memory_id": "portable-learning-001",
                    "memory_sha256": "d" * 64,
                    "source_run_id": "remote-run-001",
                    "observation_id": "remote-observation-001",
                    "approved_at": "2026-08-02T10:00:00Z",
                    "payload": {
                        "schema": "ProofLaunchPromotedLearningMemoryV1",
                        "experiment_id": "remote-experiment-001",
                        "channel": "owned-social",
                        "evidence_class": "aggregate_observation",
                        "next_cycle_decision": "revise_one_variable_then_retest",
                        "derived_rates": {"conversion_rate": 0.02},
                        "baseline_derived_rates": {"conversion_rate": 0.01},
                    },
                }
            ]
        )
        secret = b"runtime-portable-memory-secret-is-at-least-32"
        capsule = issue_memory_capsule(
            context,
            tenant_id="org-local",
            project_id="project-local",
            signing_secret=secret,
            issued_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
            ttl_seconds=2_592_000,
            nonce="3" * 32,
        )
        staged = self.service.import_memory_capsule(
            capsule,
            authenticated_tenant="org-local",
            signing_secret=secret,
        )
        self.assertEqual(staged["status"], "pending_review")
        self.assertEqual(
            self.service.project_learning_context("org-local", "project-local")[
                "memory_count"
            ],
            0,
        )
        reviewed = self.service.review_memory_capsule(
            str(capsule["capsule_id"]),
            authenticated_tenant="org-local",
            authenticated_reviewer="reviewer@example.test",
            decision="approve",
            reason="Approved this signed aggregate learning for the local project.",
        )
        self.assertEqual(reviewed["status"], "approved")
        merged = self.service.project_learning_context("org-local", "project-local")
        self.assertEqual(merged["memory_count"], 1)
        self.assertEqual(merged["memories"][0]["memory_id"], "portable-learning-001")

        self.upload_png()
        run_id = self.service.create_run(self.payload())["run_id"]
        linked = self.store.linked_artifact(run_id, "approved_learning_context")
        stored = json.loads(
            self.store.artifacts.resolve_server_path(linked.sha256).read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(stored["memory_count"], 1)
        self.assertFalse(stored["automatic_strategy_mutation_executed"])
        cockpit = self.service.gtm_cockpit(run_id)
        self.assertEqual(cockpit["cross_device_memory"]["inherited_memory_count"], 1)
        self.assertEqual(
            cockpit["cross_device_memory"]["latest_next_cycle_decision"],
            "revise_one_variable_then_retest",
        )
        self.assertTrue(cockpit["cross_device_memory"]["human_promoted_only"])
        self.assertTrue(cockpit["cross_device_memory"]["frozen_at_run_creation"])
        self.assertFalse(
            cockpit["cross_device_memory"][
                "automatic_strategy_mutation_executed"
            ]
        )
        self.assertEqual(
            cockpit["cross_device_memory"]["application_status"],
            "not_yet_compiled",
        )
        prepared = self.worker.process_one()
        self.assertEqual(prepared.status, "awaiting_release")
        prepared_cockpit = self.service.gtm_cockpit(run_id)
        self.assertEqual(
            prepared_cockpit["cross_device_memory"]["application_status"],
            "no_applicable_human_memory",
        )
        self.assertEqual(
            prepared_cockpit["cross_device_memory"]["eligible_memory_count"], 0
        )
        decision = self.strategy_json(run_id, "gtm-strategy.json")[
            "strategy_memory_decision"
        ]
        self.assertIn(
            "legacy_memory_missing_applicability_context",
            decision["candidates"][0]["hard_blockers"],
        )

    def payload(
        self,
        *,
        request_id: str = "request-001",
        campaign_id: str = "campaign-001",
        image_sha256: str | None = None,
        strategy: dict[str, object] | None = None,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "request_id": request_id,
            "campaign_id": campaign_id,
            "campaign": {
                "product_name": "Aster Arc",
                "specification_text": (
                    "Battery life up to 18 hours under the documented test protocol."
                ),
                "market": "Japan",
                "platform": "TikTok",
                "goal": "Launch one rights-clear, claim-safe social creative.",
                "target_emotion": "joy",
            },
            "input_artifacts": {
                "product_image": image_sha256 or self.png_sha256,
            },
            "rights": {
                "confirmed": True,
                "basis": "Owned first-party product photography.",
            },
            "maximum_actions": 12,
            "maximum_cost_usd": 0,
            "human_release_required": True,
            "data_class": "internal",
        }
        if strategy is not None:
            payload["strategy"] = strategy
        return payload

    def create_and_prepare(self, **payload_overrides):
        self.upload_png()
        snapshot = self.service.create_run(self.payload(**payload_overrides))
        self.assertEqual(snapshot["status"], "queued")
        result = self.worker.process_one()
        self.assertTrue(result.processed)
        self.assertEqual(result.phase, "prepare")
        self.assertEqual(result.status, "awaiting_release")
        return snapshot["run_id"]

    def strategy_json(self, run_id: str, name: str) -> dict[str, object]:
        try:
            _, relative = self.worker._find_prepared_state(run_id)
        except KeyError:
            _, relative = self.worker._find_latest_state(run_id)
        return json.loads((self.root / relative / name).read_text(encoding="utf-8"))

    def test_real_png_cas_prepare_stops_at_preview_without_bundle_then_releases(self) -> None:
        run_id = self.create_and_prepare()
        prepared = self.service.snapshot(run_id)
        self.assertEqual(prepared["status"], "awaiting_release")
        preview = self.service.preview(run_id)
        self.assertRegex(preview["preview_digest"], r"^[0-9a-f]{64}$")
        self.assertGreaterEqual(len(preview["assets"]), 1)

        state, output_relative = self.worker._find_prepared_state(run_id)
        output = self.root / output_relative
        self.assertEqual(state.stage, Stage.AWAITING_RELEASE)
        self.assertEqual(state.exports, [])
        self.assertFalse((output / "campaign-pack.zip").exists())
        with self.assertRaises(ConflictError):
            self.service.bundle_path(run_id)

        self.service.queue_release(
            run_id,
            decision="approve",
            reason="Human reviewed the exact persisted preview and source claim.",
            authenticated_approver="release-operator@example.test",
        )
        approval = self.store.get_approval(run_id)
        self.assertIsNotNone(approval)
        assert approval is not None
        self.assertEqual(approval.preview_sha256, preview["preview_digest"])
        self.assertEqual(approval.approver, "release-operator@example.test")
        self.assertEqual(approval.payload["kind"], ReleaseApprovalKind.HUMAN.value)
        self.assertRegex(approval.payload["strategy_plan_sha256"], r"^[0-9a-f]{64}$")
        self.assertRegex(
            approval.payload["gtm_artifact_set_sha256"], r"^[0-9a-f]{64}$"
        )
        self.assertRegex(
            approval.payload["production_preview_sha256"], r"^[0-9a-f]{64}$"
        )

        released = self.worker.process_one()
        self.assertEqual(released.phase, "release")
        self.assertEqual(released.status, "bundle_ready")
        self.assertEqual(self.service.snapshot(run_id)["status"], "bundle_ready")
        bundle = self.service.bundle_path(run_id)
        self.assertTrue(bundle.is_file())
        with ZipFile(bundle) as archive:
            self.assertEqual(
                set(archive.namelist()),
                {
                    "approval.json",
                    "approved-learning-context.json",
                    "approved-strategy-memory-resolutions.json",
                    "bundle-manifest.json",
                    "campaign-evidence-ledger.jsonl",
                    "campaign-pack.zip",
                    "campaign-state.json",
                    "channel-copy.json",
                    "landing-page-draft.json",
                    "lifecycle-email-draft.json",
                    "channel-portfolio.json",
                    "breakout-growth-loop.json",
                    "text-creative-challenger-plan.json",
                    "industry-gtm-profile.json",
                    "creative-strategy-kernel.json",
                    "editorial-quality-receipt.json",
                    "multimodal-direction-receipt.json",
                    "content-calendar.json",
                    "distribution-operations.json",
                    "revenue-journey-operations.json",
                    "mechanism-abstraction-register.json",
                    "promotion-governance.json",
                    "creative-signal-intelligence.json",
                    "effect-observations.json",
                    "revenue-economics.json",
                    "effect-readiness.json",
                    "events.jsonl",
                    "experiment.json",
                    "big-idea-and-message-hierarchy.json",
                    "brief-intelligence.json",
                    "product-evidence-register.json",
                    "gtm-production-pack.json",
                    "gtm-strategy.json",
                    "graph-loop-harness.json",
                    "analytics-plan.json",
                    "audio-production-brief.json",
                    "manual-release-instructions.json",
                    "request.json",
                    "run.json",
                    "seo-geo-faq-drafts.json",
                    "seo-geo-questions.json",
                    "seven-day-schedule.json",
                    "video-production-brief.json",
                },
            )
            manifest = json.loads(archive.read("bundle-manifest.json"))
            self.assertTrue(manifest["store_event_chain_verified"])
            self.assertTrue(manifest["campaign_ledger_verified_before_redaction"])
            self.assertTrue(manifest["bundled_campaign_ledger_is_redacted_view"])
            self.assertRegex(
                manifest["source_campaign_ledger_sha256"], r"^[0-9a-f]{64}$"
            )
            self.assertFalse(manifest["external_release_executed"])
            self.assertTrue(manifest["strategy_artifacts_are_drafts"])
            self.assertEqual(
                manifest["gtm_artifact_set_sha256"],
                approval.payload["gtm_artifact_set_sha256"],
            )
            self.assertFalse(manifest["effect_promotion_passed"])
            member_hashes = {
                item["name"]: item["sha256"] for item in manifest["members"]
            }
            for name in (
                "gtm-strategy.json",
                "brief-intelligence.json",
                "product-evidence-register.json",
                "seven-day-schedule.json",
                "seo-geo-questions.json",
                "experiment.json",
                "gtm-production-pack.json",
                "creative-signal-intelligence.json",
                "graph-loop-harness.json",
                "channel-copy.json",
                "landing-page-draft.json",
                "lifecycle-email-draft.json",
                "channel-portfolio.json",
                "breakout-growth-loop.json",
                "text-creative-challenger-plan.json",
                "industry-gtm-profile.json",
                "creative-strategy-kernel.json",
                "editorial-quality-receipt.json",
                "multimodal-direction-receipt.json",
                "content-calendar.json",
                "distribution-operations.json",
                "revenue-journey-operations.json",
                "mechanism-abstraction-register.json",
                "promotion-governance.json",
                "video-production-brief.json",
                "audio-production-brief.json",
                "analytics-plan.json",
                "approved-learning-context.json",
                "effect-observations.json",
                "revenue-economics.json",
                "effect-readiness.json",
            ):
                self.assertEqual(
                    member_hashes[name], hashlib.sha256(archive.read(name)).hexdigest()
                )
            with ZipFile(io.BytesIO(archive.read("campaign-pack.zip"))) as campaign:
                self.assertIn("campaign-pack.json", campaign.namelist())
                self.assertTrue(any(name.startswith("assets/") for name in campaign.namelist()))
        self.assertTrue((output / "evidence-ledger.jsonl").is_file())

    def test_approved_run_accepts_idempotent_effect_feedback_and_reseals_bundle(self) -> None:
        run_id = self.create_and_prepare()
        experiment = self.strategy_json(run_id, "experiment.json")
        _, relative = self.worker._find_prepared_state(run_id)
        strategy_sha256 = hashlib.sha256(
            (self.root / relative / "gtm-strategy.json").read_bytes()
        ).hexdigest()
        with self.assertRaises(ConflictError):
            self.service.record_effect_observation(run_id, {})

        self.service.queue_release(
            run_id,
            decision="approve",
            reason="Human approved this exact campaign and experiment.",
            authenticated_approver="effect-reviewer@example.test",
        )
        self.assertEqual(self.worker.process_one().status, "bundle_ready")
        observation = {
            "observation_id": "obs-effect-001",
            "experiment_id": experiment["attribution"]["experiment_id"],
            "strategy_plan_sha256": strategy_sha256,
            "source_kind": "first_party_analytics",
            "source_reference_sha256": "c" * 64,
            "channel": "short_video_organic",
            "window_start": "2026-07-29T00:00:00Z",
            "window_end": "2026-07-30T00:00:00Z",
            "assignment_method": "observational",
            "metrics": {
                "eligible_reach": 100,
                "qualified_actions": 12,
                "evidence_engagements": 30,
                "complaints": 1,
                "conversions": 5,
                "revenue_usd": 250.0,
                "spend_usd": 0.0,
            },
            "baseline_metrics": {
                "eligible_reach": 100,
                "qualified_actions": 8,
                "evidence_engagements": 20,
                "complaints": 1,
                "conversions": 3,
                "revenue_usd": 150.0,
                "spend_usd": 0.0,
            },
            "deduplicated": True,
            "bot_filter_applied": True,
        }
        first = self.service.record_effect_observation(run_id, observation)
        replay = self.service.record_effect_observation(run_id, observation)
        self.assertEqual(first["observation_sha256"], replay["observation_sha256"])
        collection = self.service.effect_observations(run_id)
        self.assertEqual(collection["observation_count"], 1)
        self.assertEqual(
            collection["latest_next_cycle_decision"],
            "continue_candidate_for_human_review",
        )
        self.assertFalse(collection["automatic_strategy_mutation_executed"])

        with self.assertRaisesRegex(ProductionRuntimeError, "unit-economics"):
            self.service.promote_effect_observation(
                run_id,
                "obs-effect-001",
                reason="Gross revenue alone is not admissible learning.",
                authenticated_approver="learning-reviewer@example.test",
            )
        economics_payload = {
            "economics_id": "economics-effect-001",
            "effect_observation_id": "obs-effect-001",
            "effect_observation_sha256": first["observation_sha256"],
            "source_reference_sha256": "e" * 64,
            "currency": "USD",
            "measurement_basis": "cash_collected",
            "candidate": {
                "conversions": 5,
                "gross_revenue_usd": 250.0,
                "discounts_usd": 5.0,
                "refunds_usd": 5.0,
                "chargebacks_usd": 0.0,
                "variable_cogs_usd": 50.0,
                "fulfillment_cost_usd": 20.0,
                "platform_fees_usd": 10.0,
                "media_spend_usd": 0.0,
                "model_cost_usd": 5.0,
                "operator_cost_usd": 15.0,
                "qualified_pipeline_usd": 1000.0,
            },
            "baseline": {
                "conversions": 3,
                "gross_revenue_usd": 150.0,
                "discounts_usd": 0.0,
                "refunds_usd": 3.0,
                "chargebacks_usd": 0.0,
                "variable_cogs_usd": 40.0,
                "fulfillment_cost_usd": 20.0,
                "platform_fees_usd": 7.0,
                "media_spend_usd": 0.0,
                "model_cost_usd": 5.0,
                "operator_cost_usd": 15.0,
                "qualified_pipeline_usd": 500.0,
            },
        }
        economics = self.service.record_revenue_economics(
            run_id, "obs-effect-001", economics_payload
        )
        economics_replay = self.service.record_revenue_economics(
            run_id, "obs-effect-001", economics_payload
        )
        self.assertEqual(
            economics["economics_sha256"], economics_replay["economics_sha256"]
        )
        self.assertTrue(economics["revenue_positive_feedback_ready"])
        self.assertFalse(economics["pipeline_counted_as_revenue"])

        promotion = self.service.promote_effect_observation(
            run_id,
            "obs-effect-001",
            reason="Use this aggregate comparison as a reviewable next-cycle input.",
            authenticated_approver="learning-reviewer@example.test",
        )
        promotion_replay = self.service.promote_effect_observation(
            run_id,
            "obs-effect-001",
            reason="Use this aggregate comparison as a reviewable next-cycle input.",
            authenticated_approver="learning-reviewer@example.test",
        )
        self.assertEqual(promotion["memory_sha256"], promotion_replay["memory_sha256"])
        self.assertEqual(
            promotion["payload"]["applicability_context"],
            {
                "budget": "zero",
                "business_model": "b2c",
                "industry": "unspecified",
                "industry_risk": "standard",
                "lifecycle": "launch",
                "market": "japan",
            },
        )
        self.assertEqual(
            self.service.learning_memories_for_run(run_id)["memory_count"], 1
        )

        conflict = json.loads(json.dumps(observation))
        conflict["metrics"]["qualified_actions"] = 13
        with self.assertRaises(ConflictError):
            self.service.record_effect_observation(run_id, conflict)

        with ZipFile(self.service.bundle_path(run_id)) as archive:
            sealed = json.loads(archive.read("effect-observations.json"))
            economics_collection = json.loads(archive.read("revenue-economics.json"))
            readiness = json.loads(archive.read("effect-readiness.json"))
            manifest = json.loads(archive.read("bundle-manifest.json"))
        self.assertEqual(sealed["observation_count"], 1)
        self.assertEqual(economics_collection["economics_count"], 1)
        self.assertEqual(
            economics_collection["positive_feedback_observation_count"], 1
        )
        self.assertFalse(economics_collection["pipeline_counted_as_revenue"])
        self.assertTrue(readiness["production_outcome_observation_completed"])
        self.assertEqual(readiness["production_observation_count"], 1)
        self.assertFalse(readiness["four_a_effect_claim_eligible"])
        self.assertFalse(manifest["effect_promotion_passed"])

        current_context = self.strategy_json(run_id, "approved-learning-context.json")
        self.assertEqual(current_context["memory_count"], 0)
        next_run_id = self.create_and_prepare(
            request_id="request-next-cycle",
            campaign_id="campaign-next-cycle",
        )
        next_context = self.strategy_json(
            next_run_id, "approved-learning-context.json"
        )
        next_experiment = self.strategy_json(next_run_id, "experiment.json")
        next_strategy = self.strategy_json(next_run_id, "gtm-strategy.json")
        next_calendar = self.strategy_json(next_run_id, "content-calendar.json")
        self.assertEqual(next_context["memory_count"], 1)
        self.assertEqual(
            next_context["latest_source_observation_id"], "obs-effect-001"
        )
        self.assertEqual(
            next_experiment["next_cycle_directive"],
            "continue_candidate_for_human_review",
        )
        self.assertFalse(next_experiment["automatic_strategy_mutation_executed"])
        memory_decision = next_strategy["strategy_memory_decision"]
        self.assertEqual(
            memory_decision["status"], "eligible_pending_human_application"
        )
        self.assertEqual(memory_decision["eligible_memory_count"], 1)
        self.assertEqual(memory_decision["conflict_count"], 0)
        self.assertEqual(
            memory_decision["recommended_directives"][0]["memory_id"],
            promotion["memory_id"],
        )
        self.assertTrue(memory_decision["human_application_required"])
        self.assertFalse(memory_decision["automatic_strategy_mutation_executed"])
        self.assertEqual(
            next_experiment["strategy_memory_decision_sha256"],
            memory_decision["decision_sha256"],
        )
        self.assertEqual(
            next_calendar["strategy_memory_decision"]["decision_sha256"],
            memory_decision["decision_sha256"],
        )

    def test_store_and_worker_restart_resume_prepared_and_queued_release(self) -> None:
        run_id = self.create_and_prepare()

        reopened_store = SubmissionStore(self.root)
        queueing_worker = AgencyRunWorker(
            reopened_store,
            worker_id="restart-queue-worker",
            supervisor_factory=_supervisor_factory,
        )
        queueing_service = ProductionAgencyService(reopened_store, worker=queueing_worker)
        self.assertEqual(queueing_service.snapshot(run_id)["status"], "awaiting_release")
        queueing_service.queue_release(
            run_id,
            decision="approve",
            reason="Persisted approval survives the process boundary.",
            authenticated_approver="restart-reviewer@example.test",
        )

        final_store = SubmissionStore(self.root)
        final_worker = AgencyRunWorker(
            final_store,
            worker_id="restart-release-worker",
            supervisor_factory=_supervisor_factory,
        )
        final_service = ProductionAgencyService(final_store, worker=final_worker)
        result = final_worker.process_one()
        self.assertEqual(result.status, "bundle_ready")
        self.assertTrue(final_service.bundle_path(run_id).is_file())
        self.assertTrue(final_store.verify_event_chain(run_id))

    def test_reject_is_terminal_and_never_creates_a_bundle(self) -> None:
        run_id = self.create_and_prepare()
        state, relative = self.worker._find_prepared_state(run_id)
        self.service.queue_release(
            run_id,
            decision="reject",
            reason="Human reviewer found the creative unsuitable for release.",
            authenticated_approver="release-operator@example.test",
        )
        result = self.worker.process_one()
        self.assertEqual(result.status, "rejected")
        self.assertEqual(self.service.snapshot(run_id)["status"], "rejected")
        self.assertEqual(self.worker._load_state(self.root / relative).stage, Stage.BLOCKED)
        self.assertFalse((self.root / relative / "campaign-pack.zip").exists())
        self.assertEqual(state.exports, [])
        with self.assertRaises(ConflictError):
            self.service.bundle_path(run_id)

    def test_asset_tampering_after_preview_fails_release_closed(self) -> None:
        run_id = self.create_and_prepare()
        state, relative = self.worker._find_prepared_state(run_id)
        Path(state.assets[0].path).write_bytes(b"tampered-after-human-preview")
        self.service.queue_release(
            run_id,
            decision="approve",
            reason="This decision must not authorize changed bytes.",
            authenticated_approver="release-operator@example.test",
        )
        result = self.worker.process_one()
        self.assertEqual(result.status, "failed")
        self.assertEqual(self.service.snapshot(run_id)["status"], "failed")
        self.assertFalse((self.root / relative / "campaign-pack.zip").exists())
        with self.assertRaises(ConflictError):
            self.service.bundle_path(run_id)

    def test_two_workers_do_not_execute_one_prepare_job_twice(self) -> None:
        self.upload_png()
        run_id = self.service.create_run(self.payload())["run_id"]
        workers = (
            AgencyRunWorker(
                SubmissionStore(self.root),
                worker_id="competing-worker-a",
                supervisor_factory=_supervisor_factory,
            ),
            AgencyRunWorker(
                SubmissionStore(self.root),
                worker_id="competing-worker-b",
                supervisor_factory=_supervisor_factory,
            ),
        )
        barrier = threading.Barrier(3)
        results = []

        def process(worker: AgencyRunWorker) -> None:
            barrier.wait()
            results.append(worker.process_one())

        threads = [threading.Thread(target=process, args=(worker,)) for worker in workers]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join(timeout=20)
            self.assertFalse(thread.is_alive())

        self.assertEqual(sum(result.processed for result in results), 1)
        self.assertEqual(self.store.get_run(run_id).status, "awaiting_release")
        self.assertEqual(self.store.get_job(f"prepare:{run_id}").attempts, 1)
        self.assertEqual(len(list((self.root / "runs" / run_id).glob("prepare-*"))), 1)

    def test_rights_hash_and_client_path_contracts_fail_closed(self) -> None:
        bad_rights = self.payload()
        bad_rights["rights"] = {"confirmed": False, "basis": "unknown"}
        with self.assertRaisesRegex(ProductionRuntimeError, "rights"):
            ProductionLaunchRequest.from_payload(bad_rights)

        bad_hash = self.payload(image_sha256="not-a-sha256")
        with self.assertRaisesRegex(ProductionRuntimeError, "SHA-256"):
            ProductionLaunchRequest.from_payload(bad_hash)

        client_path = self.payload()
        client_path["input_artifacts"] = {
            "product_image": self.png_sha256,
            "client_path": "/tmp/client-owned.png",
        }
        with self.assertRaisesRegex(ProductionRuntimeError, "only product_image"):
            ProductionLaunchRequest.from_payload(client_path)

        unclassified_signal = self.payload()
        unclassified_signal["input_artifacts"].update(
            {
                "creative_signal_snapshot": "1" * 64,
                "creative_signal_collection_receipt": "2" * 64,
            }
        )
        with self.assertRaisesRegex(ProductionRuntimeError, "field-level data class"):
            ProductionLaunchRequest.from_payload(unclassified_signal)

        non_public_signal = dict(unclassified_signal)
        non_public_signal["creative_signal_data_class"] = "internal"
        with self.assertRaisesRegex(ProductionRuntimeError, "must use the public"):
            ProductionLaunchRequest.from_payload(non_public_signal)

        self.upload_png()
        with self.assertRaises(KeyError):
            self.service.create_run(self.payload(image_sha256="f" * 64))

    def test_non_png_metadata_and_invalid_png_bytes_do_not_reach_release(self) -> None:
        non_png = b"plain text with a PNG-shaped claim"
        non_png_sha = hashlib.sha256(non_png).hexdigest()
        self.store.artifacts.put(
            io.BytesIO(non_png),
            expected_sha256=non_png_sha,
            media_type="text/plain",
        )
        with self.assertRaisesRegex(ProductionRuntimeError, "PNG only"):
            self.service.create_run(self.payload(image_sha256=non_png_sha))

        disguised = b"not an actual PNG"
        disguised_sha = hashlib.sha256(disguised).hexdigest()
        self.store.artifacts.put(
            io.BytesIO(disguised),
            expected_sha256=disguised_sha,
            media_type="image/png",
        )
        run_id = self.service.create_run(
            self.payload(
                request_id="request-invalid-png",
                campaign_id="campaign-invalid-png",
                image_sha256=disguised_sha,
            )
        )["run_id"]
        result = self.worker.process_one()
        self.assertEqual(result.status, "blocked")
        self.assertEqual(self.service.snapshot(run_id)["status"], "blocked")
        with self.assertRaises(ConflictError):
            self.service.bundle_path(run_id)

    def test_cas_content_or_metadata_path_tampering_fails_before_prepare(self) -> None:
        self.upload_png()
        run_id = self.service.create_run(self.payload())["run_id"]
        cas_path = self.store.artifacts.resolve_server_path(self.png_sha256)
        cas_path.write_bytes(b"changed-input")
        cas_path.chmod(0o600)
        result = self.worker.process_one()
        self.assertEqual(result.status, "failed")
        self.assertEqual(self.service.snapshot(run_id)["status"], "failed")
        self.assertEqual(list((self.root / "runs" / run_id).glob("prepare-*")), [])

    def test_backward_compatible_payload_uses_explicit_safe_strategy_defaults(self) -> None:
        launch = ProductionLaunchRequest.from_payload(self.payload())
        self.assertEqual(launch.business_model, "b2c")
        self.assertEqual(launch.lifecycle, "launch")
        self.assertEqual(launch.budget, "zero")
        self.assertEqual(launch.claim_assurance, "owner_attested")
        self.assertTrue(launch.human_release_required)

    def test_prepare_persists_all_four_auditable_strategy_artifacts(self) -> None:
        run_id = self.create_and_prepare()
        _, relative = self.worker._find_prepared_state(run_id)
        output = self.root / relative
        for name in (
            "gtm-strategy.json",
            "seven-day-schedule.json",
            "seo-geo-questions.json",
            "experiment.json",
        ):
            self.assertTrue((output / name).is_file(), name)
            self.assertEqual((output / name).stat().st_mode & 0o777, 0o600)

    def test_owner_attested_strategy_is_draft_unverified_and_not_durable_memory(self) -> None:
        run_id = self.create_and_prepare()
        plan = self.strategy_json(run_id, "gtm-strategy.json")
        self.assertEqual(plan["plan_status"], "draft_pending_human_release")
        self.assertEqual(plan["claim_assurance"]["source_status"], "owner_attested")
        self.assertTrue(plan["claim_assurance"]["owner_attested"])
        self.assertFalse(
            plan["claim_assurance"]["independently_verified_by_prooflaunch"]
        )
        self.assertEqual(plan["memory_receipt"]["kind"], "generated_draft")
        self.assertEqual(plan["memory_receipt"]["approval_status"], "pending")
        self.assertEqual(plan["memory_receipt"]["durable_count"], 0)
        self.assertEqual(
            plan["memory_receipt"]["durable_promotion_status"], "not_promoted"
        )
        self.assertFalse(plan["memory_receipt"]["source_storage_allowed"])
        adaptive = plan["adaptive_capability_plan"]
        self.assertEqual(adaptive["schema"], "ProofLaunchGTMAdaptiveCapabilityPlanV1")
        self.assertEqual(adaptive["compiled_context"]["dimensions"]["budget"], "zero")
        self.assertEqual(
            adaptive["compiled_context"]["lane_states"]["advertising_activation"],
            "EXCLUDED",
        )
        self.assertEqual(
            sum(
                state == "FOCUS"
                for state in adaptive["compiled_context"]["lane_states"].values()
            ),
            4,
        )
        self.assertEqual(adaptive["compiled_context"]["automatic_external_actions"], 0)
        self.assertTrue(adaptive["human_release_required"])
        self.assertFalse(adaptive["hardware_and_provider_in_plan_identity"])
        self.assertFalse(adaptive["automatic_publish_send_spend_or_strategy_mutation"])
        cockpit_strategy = self.service.gtm_cockpit(run_id)["strategy_and_channels"]
        self.assertEqual(cockpit_strategy["adaptive_context_id"], adaptive["compiled_context"]["context_id"])
        self.assertEqual(len(cockpit_strategy["adaptive_lane_states"]), 13)
        self.assertEqual(len(cockpit_strategy["adaptive_focus_lanes"]), 4)
        self.assertEqual(len(cockpit_strategy["adaptive_test_lanes"]), 4)
        self.assertEqual(
            cockpit_strategy["adaptive_distribution_aggregation"],
            "weakest_link_operating_floor",
        )
        self.assertFalse(cockpit_strategy["adaptive_hardware_and_provider_in_plan_identity"])
        self.assertTrue(cockpit_strategy["adaptive_human_release_required"])
        self.assertEqual(cockpit_strategy["adaptive_automatic_external_actions"], 0)

    def test_real_runs_compile_materially_different_bounded_plans_for_opposite_company_contexts(self) -> None:
        pre_pmf_run = self.create_and_prepare(
            request_id="request-b2b-pre-pmf-zero",
            campaign_id="campaign-b2b-pre-pmf-zero",
            strategy={
                "business_model": "b2b",
                "lifecycle": "pre_pmf",
                "budget": "zero",
                "company_scale": "startup",
                "brand_reach": "none",
                "owned_audience_strength": "none",
                "community_access": "none",
                "partner_access": "none",
                "content_capacity": "lean",
                "sales_motion": "sales_led",
            },
        )
        mature_run = self.create_and_prepare(
            request_id="request-b2c-mature-large",
            campaign_id="campaign-b2c-mature-large",
            strategy={
                "business_model": "b2c",
                "lifecycle": "mature",
                "budget": "scaled",
                "company_scale": "enterprise",
                "brand_reach": "strong",
                "owned_audience_strength": "strong",
                "community_access": "strong",
                "partner_access": "strong",
                "content_capacity": "studio",
                "sales_motion": "self_serve",
            },
        )

        pre_pmf = self.strategy_json(pre_pmf_run, "gtm-strategy.json")[
            "adaptive_capability_plan"
        ]["compiled_context"]
        mature = self.strategy_json(mature_run, "gtm-strategy.json")[
            "adaptive_capability_plan"
        ]["compiled_context"]

        self.assertNotEqual(pre_pmf["context_id"], mature["context_id"])
        self.assertNotEqual(pre_pmf["plan_sha256"], mature["plan_sha256"])
        self.assertNotEqual(pre_pmf["lane_states"], mature["lane_states"])
        self.assertNotEqual(
            pre_pmf["primary_growth_route"], mature["primary_growth_route"]
        )
        self.assertEqual(pre_pmf["lane_states"]["advertising_activation"], "EXCLUDED")
        self.assertFalse(pre_pmf["paid_activation_eligible_for_human_review"])
        self.assertTrue(mature["paid_activation_eligible_for_human_review"])
        self.assertEqual(pre_pmf["node_loop_iteration_cap"], 1)
        self.assertEqual(mature["node_loop_iteration_cap"], 3)
        self.assertEqual(
            pre_pmf["creative_candidate_count_per_focused_media_lane"], 2
        )
        self.assertEqual(
            mature["creative_candidate_count_per_focused_media_lane"], 4
        )
        self.assertEqual(pre_pmf["automatic_external_actions"], 0)
        self.assertEqual(mature["automatic_external_actions"], 0)

        mature_cockpit = self.service.gtm_cockpit(mature_run)[
            "strategy_and_channels"
        ]
        self.assertEqual(mature_cockpit["adaptive_context_id"], mature["context_id"])
        self.assertTrue(mature_cockpit["adaptive_human_release_required"])

    def test_prepare_compiles_channel_native_and_multimodal_production_drafts(self) -> None:
        run_id = self.create_and_prepare()
        channel_copy = self.strategy_json(run_id, "channel-copy.json")
        self.assertNotEqual(
            channel_copy["primary"]["rendered_text"],
            channel_copy["secondary"]["rendered_text"],
        )
        self.assertEqual(channel_copy["primary"]["truth_status"], "draft_only")
        self.assertFalse(channel_copy["primary"]["automated_publish_allowed"])
        video = self.strategy_json(run_id, "video-production-brief.json")
        audio = self.strategy_json(run_id, "audio-production-brief.json")
        self.assertEqual(video["truth_status"], "production_brief_only")
        self.assertEqual(audio["truth_status"], "production_brief_only")
        self.assertIn("3840x2160", video["delivery_spec"])
        self.assertIn("48 kHz", audio["mix_spec"])
        faqs = self.strategy_json(run_id, "seo-geo-faq-drafts.json")
        self.assertEqual(len(faqs["faqs"]), 4)
        self.assertTrue(
            all(
                item["citation"]["proof_claim_id"] == "claim-owner-001"
                for item in faqs["faqs"]
            )
        )

    def test_prepare_compiles_brief_intelligence_and_claim_level_release_gate(self) -> None:
        run_id = self.create_and_prepare()
        brief = self.strategy_json(run_id, "brief-intelligence.json")
        register = self.strategy_json(run_id, "product-evidence-register.json")
        strategy = self.strategy_json(run_id, "gtm-strategy.json")
        copy = self.strategy_json(run_id, "channel-copy.json")

        self.assertEqual(len(brief["growth_tensions"]), 1)
        self.assertEqual(
            brief["primary_growth_tension_id"],
            strategy["strategy"]["growth_tensions"][0]["tension_id"],
        )
        self.assertLessEqual(brief["critical_question_count"], 5)
        self.assertTrue(register["all_claims_draft_generation_eligible"])
        self.assertFalse(register["all_claims_public_release_eligible"])
        self.assertEqual(register["claim_count"], 1)
        self.assertIn("Owner-attested evidence", copy["primary"]["rendered_text"])
        self.assertNotIn("Approved evidence", copy["primary"]["rendered_text"])
        self.assertEqual(
            copy["primary"]["growth_tension_id"],
            brief["primary_growth_tension_id"],
        )
        cockpit = self.service.gtm_cockpit(run_id)
        self.assertEqual(cockpit["goal_diagnosis"]["product_claim_count"], 1)
        self.assertFalse(
            cockpit["goal_diagnosis"]["all_claims_public_release_eligible"]
        )
        self.assertEqual(
            cockpit["next_best_actions"][0]["id"],
            "resolve_product_claim_release_scope",
        )

    def test_preview_exposes_new_operating_kernels_without_upgrading_truth(self) -> None:
        run_id = self.create_and_prepare()
        preview = self.service.preview(run_id)
        kernels = preview["gtm_strategy"]["operating_kernels"]

        self.assertEqual(
            set(kernels),
            {
                "creative_strategy",
                "editorial_quality",
                "multimodal_direction",
                "distribution_operations",
                "revenue_journey",
                "mechanism_abstraction",
                "promotion_governance",
            },
        )
        self.assertEqual(kernels["creative_strategy"]["creative_territory_count"], 3)
        self.assertFalse(kernels["editorial_quality"]["direct_publishability_observed"])
        self.assertEqual(kernels["multimodal_direction"]["rendered_asset_count"], 0)
        self.assertFalse(kernels["distribution_operations"]["external_activation_executed"])
        self.assertFalse(kernels["revenue_journey"]["production_effect_observed"])
        self.assertEqual(kernels["mechanism_abstraction"]["case_count"], 0)
        self.assertFalse(kernels["promotion_governance"]["promotion_allowed"])

    def test_explicit_named_claim_scope_is_release_eligible_but_still_human_gated(self) -> None:
        run_id = self.create_and_prepare(
            request_id="request-verified-claim",
            campaign_id="campaign-verified-claim",
            strategy={
                "product_claims": [
                    {
                        "claim_id": "claim-performance-001",
                        "claim_type": "performance",
                        "claim_text": "Battery life up to 18 hours under the documented test protocol.",
                        "source_uri": "owner://lab/battery-protocol-001",
                        "source_sha256": "a" * 64,
                        "rights_status": "owner_approved",
                        "rights_reference": "Owned laboratory protocol and result.",
                        "release_scope": "campaign_public_channels",
                        "valid_from": "2026-08-01T00:00:00Z",
                        "approved_by": "Named Product Owner",
                    }
                ]
            },
        )
        register = self.strategy_json(run_id, "product-evidence-register.json")
        copy = self.strategy_json(run_id, "channel-copy.json")
        self.assertTrue(register["all_claims_public_release_eligible"])
        self.assertIn("Verified evidence", copy["primary"]["rendered_text"])
        self.assertTrue(copy["primary"]["human_release_required"])
        self.assertFalse(copy["primary"]["automated_publish_allowed"])

    def test_preview_exposes_the_approval_bound_channel_portfolio(self) -> None:
        run_id = self.create_and_prepare()
        preview = self.service.preview(run_id)
        portfolio = preview["gtm_strategy"]["channel_portfolio"]
        self.assertEqual(portfolio["schema"], "ProofLaunchChannelPortfolioV1")
        self.assertEqual(len(portfolio["portfolio"]), 12)
        self.assertEqual(
            portfolio["focus_channels"],
            [
                preview["gtm_strategy"]["primary_channel"],
                preview["gtm_strategy"]["secondary_channel"],
            ],
        )
        self.assertFalse(portfolio["external_activation_executed"])
        self.assertFalse(portfolio["automatic_strategy_mutation_executed"])
        workspace = preview["campaign_workspace"]
        self.assertEqual(workspace["schema"], "ProofLaunchCampaignWorkspacePublicV1")
        self.assertEqual(workspace["artifact_count"], 9)
        self.assertRegex(workspace["artifact_set_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(
            workspace["landing_page"]["schema"],
            "ProofLaunchLandingPageDraftV1",
        )
        self.assertEqual(
            workspace["lifecycle_email"]["schema"],
            "ProofLaunchLifecycleEmailDraftV1",
        )
        self.assertEqual(len(workspace["seo_geo"]["faqs"]), 4)
        self.assertGreater(len(workspace["analytics"]["metrics"]), 0)
        self.assertTrue(workspace["human_release_required"])
        self.assertFalse(workspace["automatic_publish_enabled"])
        self.assertFalse(workspace["automatic_send_enabled"])
        self.assertFalse(workspace["automatic_spend_enabled"])
        self.assertFalse(workspace["external_activation_executed"])

    def test_runtime_calendar_preserves_operator_timezone_and_approval_queue(self) -> None:
        run_id = self.create_and_prepare(strategy={"schedule_timezone": "Asia/Tokyo"})
        calendar = self.strategy_json(run_id, "content-calendar.json")
        self.assertEqual(calendar["timezone"], "Asia/Tokyo")
        self.assertEqual(len(calendar["slots"]), 7)
        self.assertEqual(len(calendar["approval_queue"]), 7)
        self.assertTrue(
            all(slot["scheduled_local"].endswith("+09:00") for slot in calendar["slots"])
        )
        preview = self.service.preview(run_id)
        self.assertEqual(
            preview["gtm_strategy"]["content_calendar"]["content_sha256"],
            calendar["content_sha256"],
        )

    def test_preview_exposes_approval_bound_breakout_growth_loop(self) -> None:
        run_id = self.create_and_prepare()
        breakout = self.strategy_json(run_id, "breakout-growth-loop.json")
        preview = self.service.preview(run_id)
        exposed = preview["gtm_strategy"]["breakout_growth_loop"]
        self.assertEqual(exposed["content_sha256"], breakout["content_sha256"])
        self.assertEqual(
            [step["step_id"] for step in exposed["steps"]],
            ["sense", "make", "seed", "convert", "learn"],
        )
        self.assertTrue(exposed["core_loop_functions_without_paid_media"])
        self.assertFalse(exposed["external_action_performed"])
        self.assertFalse(exposed["automatic_learning_promotion_enabled"])

    def test_preview_exposes_text_challenger_status_without_claiming_generation(self) -> None:
        run_id = self.create_and_prepare()
        persisted = self.strategy_json(run_id, "text-creative-challenger-plan.json")
        preview = self.service.preview(run_id)
        challenger = preview["gtm_strategy"]["text_creative_challenger"]
        self.assertEqual(challenger["content_sha256"], persisted["content_sha256"])
        self.assertEqual(challenger["territory_count"], 3)
        self.assertEqual(
            challenger["territory_ids"],
            ["decision_xray", "proof_before_promise", "voluntary_relay"],
        )
        self.assertTrue(challenger["official_first_required"])
        self.assertEqual(challenger["execution_policy"]["mode"], "sequential_fail_fast")
        self.assertEqual(challenger["execution_policy"]["maximum_concurrency"], 1)
        self.assertEqual(challenger["execution_policy"]["default_retry_rounds"], 0)
        alpha = challenger["creative_alpha_plan"]
        self.assertEqual(alpha["schema"], "ProofLaunchCreativeAlphaPlanV1")
        self.assertEqual(
            alpha["growth_case_radar_status"], "growth_case_research_required"
        )
        self.assertGreaterEqual(len(alpha["style_portfolio"]), 2)
        self.assertEqual(len(alpha["platform_grammars"]), 2)
        self.assertEqual(alpha["external_action_count"], 0)
        self.assertTrue(alpha["human_release_required"])
        cockpit_strategy = self.service.gtm_cockpit(run_id)["strategy_and_channels"]
        self.assertEqual(
            cockpit_strategy["creative_alpha_plan_sha256"],
            alpha["content_sha256"],
        )
        self.assertEqual(
            cockpit_strategy["creative_alpha_growth_case_status"],
            "growth_case_research_required",
        )
        self.assertEqual(
            cockpit_strategy["creative_alpha_style_ids"],
            [item["style_id"] for item in alpha["style_portfolio"]],
        )
        self.assertEqual(cockpit_strategy["creative_alpha_external_actions"], 0)
        self.assertTrue(
            cockpit_strategy["creative_alpha_human_release_required"]
        )
        self.assertFalse(challenger["winner_selected"])
        self.assertFalse(challenger["blind_review_completed"])
        self.assertFalse(challenger["external_publish_executed"])

    def test_runtime_rejects_unknown_schedule_timezone_before_queueing(self) -> None:
        self.upload_png()
        with self.assertRaisesRegex(ProductionRuntimeError, "installed IANA timezone"):
            self.service.create_run(
                self.payload(strategy={"schedule_timezone": "Mars/Olympus_Mons"})
            )

    def test_zero_budget_strategy_bans_paid_spam_and_automated_publish(self) -> None:
        run_id = self.create_and_prepare()
        plan = self.strategy_json(run_id, "gtm-strategy.json")
        self.assertEqual(plan["strategy"]["attribution"]["utm_medium"], "organic")
        schedule = self.strategy_json(run_id, "seven-day-schedule.json")
        self.assertFalse(schedule["automated_publish_allowed"])
        for constraint in schedule["channel_constraints"]:
            prohibited = set(constraint["prohibited_actions"])
            self.assertTrue(
                {"paid_placement", "media_spend", "spam", "automated_publish"}
                <= prohibited
            )
            self.assertFalse(constraint["automated_publish_allowed"])

    def test_schedule_is_exactly_seven_manual_human_release_days(self) -> None:
        run_id = self.create_and_prepare()
        schedule = self.strategy_json(run_id, "seven-day-schedule.json")
        self.assertEqual([item["day"] for item in schedule["items"]], list(range(1, 8)))
        self.assertTrue(
            all(
                item["release_mode"] == "human_review_then_manual_publish"
                for item in schedule["items"]
            )
        )

    def test_seo_geo_artifact_contains_questions_not_unreviewed_answers(self) -> None:
        run_id = self.create_and_prepare()
        plan = self.strategy_json(run_id, "seo-geo-questions.json")
        self.assertFalse(plan["answers_generated"])
        self.assertFalse(plan["keyword_stuffing_allowed"])
        self.assertEqual(len(plan["question_intents"]), 4)
        self.assertTrue(all(item.endswith("?") for item in plan["question_intents"]))

    def test_experiment_is_preregistered_draft_without_causal_or_observed_claims(self) -> None:
        run_id = self.create_and_prepare()
        experiment = self.strategy_json(run_id, "experiment.json")
        self.assertEqual(experiment["status"], "draft_not_started")
        self.assertFalse(experiment["causal_outcome_claim_allowed"])
        self.assertFalse(experiment["external_activation_executed"])
        self.assertEqual(experiment["observed_results"], [])
        self.assertIn(
            "not a causal revenue claim", experiment["attribution"]["interpretation"]
        )

    def test_optional_b2b_growth_dimensions_select_evidence_and_search_channels(self) -> None:
        run_id = self.create_and_prepare(
            strategy={
                "business_model": "b2b",
                "lifecycle": "growth",
                "budget": "zero",
                "audience_name": "revenue operations leaders",
            }
        )
        preview = self.service.preview(run_id)
        self.assertEqual(preview["gtm_strategy"]["primary_channel"], "search_education")
        self.assertEqual(
            preview["gtm_strategy"]["secondary_channel"], "customer_evidence"
        )
        self.assertFalse(preview["gtm_strategy"]["automated_publish_allowed"])

    def test_product_category_surface_persona_and_timing_reach_real_creative_plan(self) -> None:
        run_id = self.create_and_prepare(
            strategy={
                "business_model": "b2c",
                "lifecycle": "launch",
                "budget": "zero",
                "industry": "consumer health",
                "product_category": "Health and Fitness",
                "product_surface": "mobile_app",
                "audience_name": "first-time home fitness users",
                "audience_role": "switcher",
                "schedule_timezone": "Asia/Tokyo",
            }
        )
        preview = self.service.preview(run_id)
        alpha = preview["gtm_strategy"]["text_creative_challenger"][
            "creative_alpha_plan"
        ]
        self.assertEqual(alpha["context"]["product_category"], "Health and Fitness")
        self.assertEqual(alpha["context"]["product_surface"], "mobile_app")
        self.assertEqual(alpha["context"]["distribution_platform"], "TikTok")
        self.assertEqual(alpha["context"]["audience_role"], "switcher")
        self.assertEqual(
            alpha["distribution_platform_overlay"]["content_bias"][0],
            "short_video",
        )
        self.assertEqual(
            alpha["audience_decision_unit_contract"]["mode"],
            "b2c_use_moment_system",
        )
        language = alpha["market_language_contract"]
        self.assertEqual(
            language["context"]["resolved_reference_family"],
            "health_fitness_medical",
        )
        self.assertEqual(language["context"]["resolved_primary_role"], "switcher")
        self.assertEqual(language["platform_translation"]["primary_formats"][0], "short_video")
        self.assertFalse(language["budget_contract"]["paid_activation_allowed"])
        self.assertEqual(language["external_action_count"], 0)
        team = alpha["gtm_team_capability_contract"]
        self.assertEqual(team["full_skill_registry"]["role_count"], 22)
        self.assertEqual(team["full_skill_registry"]["atomic_skill_count"], 220)
        self.assertIn(
            "product_led_growth_lead",
            {item["role_id"] for item in team["active_virtual_team"]["roles"]},
        )
        self.assertEqual(alpha["publication_timing_contract"]["timezone"], "Asia/Tokyo")
        self.assertFalse(alpha["publication_timing_contract"]["automatic_publish_enabled"])
        self.assertFalse(alpha["self_evolution_contract"]["current_run_mutation_allowed"])
        self.assertEqual(
            self.service.gtm_cockpit(run_id)["operating_context"]["product_surface"],
            "mobile_app",
        )
        self.assertEqual(
            self.service.gtm_cockpit(run_id)["operating_context"]["audience_role"],
            "switcher",
        )
        self.assertEqual(
            self.service.gtm_cockpit(run_id)["strategy_and_channels"][
                "market_language_signature_sha256"
            ],
            language["language_signature_sha256"],
        )
        self.assertEqual(
            self.service.gtm_cockpit(run_id)["strategy_and_channels"][
                "gtm_team_capability_contract_sha256"
            ],
            team["content_sha256"],
        )
        self.assertEqual(
            self.service.gtm_cockpit(run_id)["operating_context"][
                "distribution_platform"
            ],
            "TikTok",
        )

    def test_verified_assurance_requires_a_named_claim_approver(self) -> None:
        with self.assertRaisesRegex(ProductionRuntimeError, "named claim_approved_by"):
            ProductionLaunchRequest.from_payload(
                self.payload(strategy={"claim_assurance": "verified"})
            )

    def test_high_regulation_requires_a_named_specialist_approver(self) -> None:
        with self.assertRaisesRegex(ProductionRuntimeError, "specialist approval"):
            ProductionLaunchRequest.from_payload(
                self.payload(strategy={"industry_risk": "high_regulation"})
            )

    def test_strategy_artifact_tampering_fails_before_recording_human_release(self) -> None:
        run_id = self.create_and_prepare()
        _, relative = self.worker._find_prepared_state(run_id)
        (self.root / relative / "gtm-strategy.json").write_text(
            '{"tampered":true}\n', encoding="utf-8"
        )
        with self.assertRaisesRegex(ProductionRuntimeError, "integrity failed"):
            self.service.queue_release(
                run_id,
                decision="approve",
                reason="Must not approve altered strategy bytes.",
                authenticated_approver="reviewer@example.test",
            )
        self.assertIsNone(self.store.get_approval(run_id))

    def test_campaign_workspace_tampering_fails_preview_and_human_release(self) -> None:
        run_id = self.create_and_prepare()
        _, relative = self.worker._find_prepared_state(run_id)
        (self.root / relative / "landing-page-draft.json").write_text(
            '{"tampered":true}\n', encoding="utf-8"
        )
        with self.assertRaisesRegex(ProductionRuntimeError, "integrity failed"):
            self.service.preview(run_id)
        with self.assertRaisesRegex(ProductionRuntimeError, "integrity failed"):
            self.service.queue_release(
                run_id,
                decision="approve",
                reason="Must not approve altered campaign workspace bytes.",
                authenticated_approver="reviewer@example.test",
            )
        self.assertIsNone(self.store.get_approval(run_id))

    def test_unsafe_outcome_guarantee_fails_strategy_gate_without_release(self) -> None:
        self.upload_png()
        payload = self.payload(request_id="unsafe-request", campaign_id="unsafe-campaign")
        payload["campaign"]["specification_text"] = "This will go viral and will drive revenue."
        run_id = self.service.create_run(payload)["run_id"]
        result = self.worker.process_one()
        self.assertEqual(result.status, "failed")
        self.assertEqual(self.service.snapshot(run_id)["status"], "failed")
        self.assertIsNone(self.store.get_approval(run_id))
        with self.assertRaises(ConflictError):
            self.service.bundle_path(run_id)

    def test_effect_readiness_is_truthful_and_never_promotes_mechanical_success(self) -> None:
        run_id = self.create_and_prepare()
        self.service.queue_release(
            run_id,
            decision="approve",
            reason="Approve local creative; effect claims remain blocked.",
            authenticated_approver="reviewer@example.test",
        )
        self.assertEqual(self.worker.process_one().status, "bundle_ready")
        with ZipFile(self.service.bundle_path(run_id)) as archive:
            readiness = json.loads(archive.read("effect-readiness.json"))
        self.assertEqual(len(readiness["capability_status"]), 8)
        self.assertEqual(
            set(readiness["capability_status"].values()), {"planned", "mechanical"}
        )
        self.assertFalse(readiness["promotion_passed"])
        self.assertFalse(readiness["four_a_effect_claim_eligible"])
        self.assertFalse(readiness["human_blind_evaluation_completed"])
        self.assertGreaterEqual(len(readiness["blockers"]), 5)


if __name__ == "__main__":
    unittest.main()
