from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RECEIPT = ROOT / "evidence/v10/aug3-product-readiness.json"


class Aug3ProductReadinessReceiptTests(unittest.TestCase):
    def test_receipt_is_self_consistent_and_hashes_required_product_files(self) -> None:
        payload = json.loads(RECEIPT.read_text(encoding="utf-8"))
        claimed_digest = payload.pop("receipt_sha256")
        observed_digest = hashlib.sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        self.assertEqual(claimed_digest, observed_digest)
        for relative, expected in payload["required_file_sha256"].items():
            self.assertEqual(
                hashlib.sha256((ROOT / relative).read_bytes()).hexdigest(), expected
            )

    def test_demo_decision_never_promotes_unobserved_effect_or_radeon_evidence(self) -> None:
        payload = json.loads(RECEIPT.read_text(encoding="utf-8"))
        self.assertEqual(
            payload["launch_decision"], "local_demo_ready_effect_unproven"
        )
        self.assertTrue(
            payload["verification"][
                "production_observation_field_kit_aggregate_attribution_plan_present"
            ]
        )
        self.assertTrue(
            payload["verification"][
                "production_observation_field_kit_distinct_arm_tags_present"
            ]
        )
        self.assertFalse(
            payload["verification"][
                "production_observation_field_kit_tracking_pixel_included"
            ]
        )
        self.assertFalse(
            payload["verification"][
                "production_observation_field_kit_person_level_export_allowed"
            ]
        )
        self.assertTrue(
            payload["verification"]["manual_publication_receipt_contract_present"]
        )
        self.assertTrue(
            payload["verification"][
                "manual_publication_receipt_requires_delivered_approved_run"
            ]
        )
        self.assertTrue(
            payload["verification"][
                "manual_publication_receipt_exact_asset_attribution_url_binding"
            ]
        )
        self.assertFalse(
            payload["verification"][
                "manual_publication_receipt_prooflaunch_publish_enabled"
            ]
        )
        self.assertEqual(
            payload["verification"]["manual_publication_receipt_observed_count"],
            0,
        )
        self.assertEqual(
            payload["verification"][
                "manual_publication_platform_delivery_verified_count"
            ],
            0,
        )
        regression = payload["verification"]["product_critical_regression"]
        self.assertTrue(regression["passed"])
        self.assertEqual(regression["return_code"], 0)
        self.assertGreaterEqual(regression["test_count"], 180)
        web_build = payload["verification"]["web_product_build"]
        self.assertTrue(web_build["passed"])
        self.assertEqual(web_build["return_code"], 0)
        self.assertEqual(web_build["route_count"], 46)
        # Includes the observation kit, economics import, and last-mile quality board.
        self.assertEqual(web_build["same_origin_api_contract_count"], 60)
        self.assertLess(web_build["static_resource_bytes"], 550_000)
        self.assertEqual(
            payload["verification"]["codex_integrated_campaign_pack_count"], 2
        )
        self.assertEqual(
            payload["verification"][
                "codex_integrated_campaign_platform_candidate_count"
            ],
            26,
        )
        self.assertEqual(
            payload["verification"]["codex_integrated_campaign_email_count"], 8
        )
        self.assertEqual(
            payload["verification"][
                "codex_integrated_campaign_production_direction_count"
            ],
            6,
        )
        self.assertEqual(
            payload["verification"][
                "codex_integrated_campaign_search_geo_node_count"
            ],
            14,
        )
        self.assertEqual(
            payload["verification"][
                "codex_integrated_campaign_seven_day_flight_slot_count"
            ],
            14,
        )
        self.assertEqual(
            payload["verification"][
                "codex_integrated_campaign_experiment_count"
            ],
            8,
        )
        self.assertTrue(
            payload["verification"]["codex_integrated_campaign_api_present"]
        )
        self.assertTrue(
            payload["verification"][
                "codex_integrated_campaign_browser_digest_verified"
            ]
        )
        self.assertTrue(
            payload["verification"]["codex_integrated_campaign_ui_present"]
        )
        self.assertEqual(
            payload["verification"][
                "codex_integrated_campaign_release_eligible_count"
            ],
            0,
        )
        self.assertEqual(
            payload["verification"][
                "codex_integrated_campaign_human_review_completed_count"
            ],
            0,
        )
        self.assertFalse(
            payload["verification"][
                "codex_integrated_campaign_production_effect_observed"
            ]
        )
        self.assertEqual(
            payload["verification"]["codex_campaign_adaptation_case_count"], 456
        )
        self.assertEqual(
            payload["verification"][
                "codex_campaign_adaptation_industry_archetype_count"
            ],
            20,
        )
        self.assertEqual(
            payload["verification"]["codex_campaign_adaptation_zero_budget_count"],
            152,
        )
        self.assertEqual(
            payload["verification"]["codex_campaign_adaptation_regulated_count"],
            72,
        )
        self.assertEqual(
            payload["verification"]["codex_campaign_adaptation_graph_stage_count"],
            5,
        )
        self.assertEqual(
            payload["verification"][
                "codex_campaign_adaptation_named_failure_mode_count"
            ],
            10,
        )
        self.assertTrue(
            payload["verification"]["codex_campaign_adaptation_api_present"]
        )
        self.assertTrue(
            payload["verification"][
                "codex_campaign_adaptation_browser_digest_verified"
            ]
        )
        self.assertTrue(
            payload["verification"]["codex_campaign_adaptation_ui_present"]
        )
        self.assertEqual(
            payload["verification"]["codex_campaign_adaptation_model_call_count"],
            0,
        )
        self.assertEqual(
            payload["verification"][
                "codex_campaign_adaptation_candidate_output_count"
            ],
            0,
        )
        self.assertEqual(
            payload["verification"][
                "codex_campaign_adaptation_human_review_completed_count"
            ],
            0,
        )
        self.assertEqual(
            payload["verification"][
                "codex_campaign_adaptation_release_eligible_count"
            ],
            0,
        )
        self.assertEqual(
            payload["verification"][
                "codex_campaign_adaptation_production_effect_observed_count"
            ],
            0,
        )
        self.assertEqual(
            payload["verification"]["codex_lighthouse_candidate_count"], 8
        )
        self.assertEqual(
            payload["verification"][
                "codex_lighthouse_workspace_authored_candidate_count"
            ],
            8,
        )
        self.assertEqual(
            payload["verification"]["codex_lighthouse_platform_asset_count"], 16
        )
        self.assertEqual(
            payload["verification"]["codex_lighthouse_level_1_pass_count"], 8
        )
        self.assertEqual(
            payload["verification"]["codex_lighthouse_level_1_reject_count"], 0
        )
        self.assertTrue(payload["verification"]["codex_lighthouse_api_present"])
        self.assertTrue(
            payload["verification"][
                "codex_lighthouse_browser_digest_verified"
            ]
        )
        self.assertTrue(payload["verification"]["codex_lighthouse_ui_present"])
        self.assertEqual(
            payload["verification"][
                "codex_lighthouse_flagship_api_inference_observed_count"
            ],
            0,
        )
        self.assertEqual(
            payload["verification"][
                "codex_lighthouse_calibrated_model_critic_pass_count"
            ],
            0,
        )
        self.assertEqual(
            payload["verification"][
                "codex_lighthouse_qualified_human_review_count"
            ],
            0,
        )
        self.assertEqual(
            payload["verification"]["codex_lighthouse_release_eligible_count"],
            0,
        )
        self.assertEqual(
            payload["verification"][
                "codex_lighthouse_external_publish_executed_count"
            ],
            0,
        )
        self.assertEqual(
            payload["verification"][
                "codex_lighthouse_production_effect_observed_count"
            ],
            0,
        )
        self.assertEqual(
            payload["verification"][
                "codex_lighthouse_causal_revenue_effect_proven_count"
            ],
            0,
        )
        self.assertEqual(
            payload["verification"]["discrete_strategy_contract_count"], 48
        )
        self.assertEqual(
            payload["verification"]["hybrid_quality_control_category_count"], 13
        )
        self.assertEqual(
            payload["verification"]["hybrid_quality_control_job_count"], 130
        )
        self.assertEqual(
            payload["verification"][
                "hybrid_quality_control_local_ready_category_count"
            ],
            13,
        )
        self.assertEqual(
            payload["verification"][
                "hybrid_quality_control_challenger_dossier_count_admitted"
            ],
            13,
        )
        self.assertEqual(
            payload["verification"][
                "hybrid_quality_control_cloud_api_role_count_ready"
            ],
            0,
        )
        self.assertFalse(
            payload["verification"][
                "hybrid_quality_control_local_runtime_blocked_by_cloud"
            ]
        )
        self.assertTrue(
            payload["verification"][
                "hybrid_quality_control_hardware_and_provider_are_replaceable"
            ]
        )
        self.assertTrue(
            payload["verification"][
                "hybrid_quality_control_jobs_route_by_capability_not_vendor"
            ]
        )
        self.assertTrue(
            payload["verification"][
                "hybrid_quality_control_local_pipeline_continues_without_cloud"
            ]
        )
        self.assertFalse(
            payload["verification"][
                "hybrid_quality_control_cloud_gpu_is_runtime_dependency"
            ]
        )
        self.assertFalse(
            payload["verification"][
                "hybrid_quality_control_radeon_required_for_product_closure"
            ]
        )
        self.assertFalse(
            payload["verification"][
                "hybrid_quality_control_model_judge_can_promote"
            ]
        )
        self.assertTrue(
            payload["verification"][
                "hybrid_quality_control_human_release_required"
            ]
        )
        self.assertEqual(
            payload["verification"]["adaptive_capability_graph_context_count"],
            6912,
        )
        self.assertEqual(
            payload["verification"]["adaptive_capability_graph_lane_decision_count"],
            89856,
        )
        self.assertGreaterEqual(
            payload["verification"]["adaptive_capability_graph_distinct_lane_state_profiles"],
            400,
        )
        self.assertEqual(
            payload["verification"]["adaptive_capability_graph_zero_budget_paid_activation_count"],
            0,
        )
        self.assertEqual(
            payload["verification"]["adaptive_capability_graph_regulated_missing_specialist_gate_count"],
            0,
        )
        self.assertEqual(
            payload["verification"]["adaptive_capability_graph_automatic_external_action_count"],
            0,
        )
        self.assertFalse(
            payload["verification"]["adaptive_capability_graph_hardware_in_plan_identity"]
        )
        self.assertTrue(
            payload["verification"]["adaptive_capability_plan_embedded_in_run_strategy"]
        )
        self.assertTrue(
            payload["verification"]["adaptive_capability_plan_exposed_in_gtm_cockpit"]
        )
        self.assertEqual(
            payload["verification"]["gtm_human_capability_role_count"], 22
        )
        self.assertEqual(
            payload["verification"]["gtm_human_capability_skill_card_count"], 220
        )
        self.assertEqual(
            payload["verification"]["gtm_human_capability_professional_axis_count"],
            2200,
        )
        self.assertEqual(
            payload["verification"]["gtm_human_capability_eval_check_count"],
            2200,
        )
        self.assertEqual(
            payload["verification"]["gtm_human_capability_surface_count"], 13
        )
        self.assertEqual(
            payload["verification"][
                "gtm_human_capability_surface_specialist_lens_count"
            ],
            52,
        )
        self.assertEqual(
            payload["verification"][
                "gtm_human_capability_unconventional_edge_play_card_count"
            ],
            26,
        )
        self.assertTrue(
            payload["verification"][
                "gtm_human_capability_runtime_work_order_binding_present"
            ]
        )
        self.assertEqual(
            payload["verification"][
                "gtm_human_capability_automatic_external_action_count"
            ],
            0,
        )
        self.assertFalse(
            payload["verification"][
                "gtm_human_capability_structural_coverage_is_effect_evidence"
            ]
        )
        self.assertFalse(
            payload["verification"][
                "gtm_human_capability_comparative_superiority_claim_allowed_now"
            ]
        )
        self.assertEqual(
            payload["verification"][
                "gtm_craft_handoff_professional_axis_assignment_count"
            ],
            181440,
        )
        self.assertEqual(
            payload["verification"][
                "gtm_craft_handoff_surface_specialist_lens_assignment_count"
            ],
            15552,
        )
        self.assertEqual(
            payload["verification"][
                "gtm_craft_handoff_unconventional_edge_play_binding_count"
            ],
            3888,
        )
        hybrid = payload["external_gate_snapshot"]["hybrid_quality_control"]
        self.assertEqual(hybrid["category_count"], 13)
        self.assertEqual(hybrid["job_count"], 130)
        self.assertEqual(hybrid["local_ready_category_count"], 13)
        self.assertEqual(hybrid["cloud_api_role_count_ready"], 0)
        self.assertFalse(hybrid["cloud_gpu_is_product_runtime_dependency"])
        self.assertFalse(hybrid["radeon_required_for_product_closure"])
        self.assertEqual(hybrid["authorized_named_product_baseline_count"], 0)
        self.assertEqual(hybrid["completed_named_product_pk_count"], 0)
        self.assertEqual(hybrid["candidate_wins"], 0)
        self.assertEqual(hybrid["effect_aligned_categories"], 0)
        adaptive = payload["external_gate_snapshot"]["adaptive_capability_graph"]
        self.assertEqual(adaptive["context_count"], 6912)
        self.assertEqual(adaptive["lane_decision_count"], 89856)
        self.assertGreaterEqual(adaptive["distinct_lane_state_profiles"], 400)
        self.assertGreaterEqual(adaptive["distinct_focus_profiles"], 35)
        self.assertGreaterEqual(adaptive["distinct_growth_route_profiles"], 7)
        self.assertEqual(adaptive["zero_budget_paid_activation_count"], 0)
        self.assertEqual(adaptive["regulated_missing_specialist_gate_count"], 0)
        self.assertEqual(adaptive["automatic_external_action_count"], 0)
        self.assertEqual(adaptive["shadow_candidate_count"], 4)
        self.assertFalse(adaptive["hardware_and_provider_in_plan_identity"])
        self.assertEqual(adaptive["named_product_pk_wins"], 0)
        for field in (
            "public_signal_snapshot_and_receipt_pair_required",
            "public_signal_field_level_data_class_present",
            "public_signal_collection_receipt_self_hash_verified",
            "public_signal_collection_receipt_exact_snapshot_bound",
            "public_signal_collector_no_bypass_gate_present",
            "public_signal_training_and_publish_admission_disabled",
            "public_signal_browser_pair_upload_present",
            "real_public_signal_collection_completed",
            "real_public_signal_gtm_pilot_bound",
            "real_public_signal_cockpit_api_present",
            "real_public_signal_cockpit_browser_digest_verified",
        ):
            with self.subTest(field=field):
                self.assertTrue(payload["verification"][field])
        self.assertFalse(
            payload["verification"][
                "real_public_signal_gtm_pilot_external_release_executed"
            ]
        )
        self.assertFalse(
            payload["verification"][
                "real_public_signal_gtm_pilot_automatic_strategy_mutation_executed"
            ]
        )
        pilot = payload["external_gate_snapshot"]["public_signal_gtm_pilot"]
        self.assertEqual(pilot["status"], "awaiting_human_release")
        self.assertEqual(pilot["signal_count"], 28)
        self.assertEqual(set(pilot["platform_counts"]), {"youtube", "vimeo"})
        self.assertTrue(pilot["human_release_required"])
        self.assertFalse(pilot["external_release_executed"])
        self.assertTrue(pilot["cockpit_api_present"])
        self.assertTrue(pilot["cockpit_browser_digest_verified"])
        self.assertEqual(
            payload["verification"]["tenant_isolation_model"],
            "single_node_sqlite_scoped_vertical_slice",
        )
        self.assertTrue(payload["verification"]["tenant_principal_server_bound"])
        self.assertTrue(
            payload["verification"][
                "revenue_memory_demo_manual_publication_receipt_recorded"
            ]
        )
        self.assertEqual(
            payload["verification"]["gtm_capability_effect_matrix_count"], 11
        )
        self.assertEqual(
            payload["verification"][
                "gtm_capability_effect_matrix_connected_count"
            ],
            11,
        )
        self.assertEqual(
            payload["verification"][
                "gtm_capability_effect_matrix_generated_deliverable_count"
            ],
            0,
        )
        self.assertEqual(
            payload["verification"][
                "gtm_capability_effect_matrix_named_human_quality_count"
            ],
            0,
        )
        self.assertEqual(
            payload["verification"][
                "gtm_capability_effect_matrix_production_effect_attributed_count"
            ],
            0,
        )
        self.assertFalse(
            payload["verification"][
                "gtm_capability_effect_matrix_all_effects_proven"
            ]
        )

    def test_unified_last_mile_review_is_complete_as_a_queue_not_as_human_evidence(self) -> None:
        payload = json.loads(RECEIPT.read_text(encoding="utf-8"))
        verification = payload["verification"]
        self.assertEqual(verification["last_mile_audio_candidate_count"], 3)
        self.assertEqual(
            verification["last_mile_audio_candidate_offline_cloud_api_calls"],
            0,
        )
        self.assertEqual(verification["last_mile_audio_candidate_network_downloads"], 0)
        self.assertTrue(verification["last_mile_audio_candidate_all_fifteen_seconds"])
        self.assertFalse(
            verification["last_mile_audio_candidate_human_preference_observed"]
        )
        self.assertEqual(verification["last_mile_unified_review_lane_count"], 14)
        self.assertEqual(verification["last_mile_unified_review_pair_count"], 16)
        self.assertEqual(
            verification["last_mile_unified_review_expected_human_count"],
            80,
        )
        self.assertEqual(
            verification["last_mile_unified_review_submitted_human_count"],
            0,
        )
        self.assertFalse(
            verification["last_mile_unified_review_top_product_baselines_present"]
        )

    def test_platform_native_local_generation_and_craft_review_stay_distinct(self) -> None:
        payload = json.loads(RECEIPT.read_text(encoding="utf-8"))
        verification = payload["verification"]
        self.assertTrue(verification["apple_mlx_runtime_preflight_passed"])
        self.assertTrue(verification["apple_mlx_runtime_metal_checked"])
        self.assertTrue(verification["apple_mlx_runtime_metal_available"])
        self.assertEqual(
            verification["apple_mlx_runtime_observed_packages"]["mlx-lm"],
            "0.31.3",
        )
        self.assertEqual(verification["platform_native_b2b_generated_surface_count"], 13)
        self.assertEqual(verification["platform_native_b2c_generated_surface_count"], 13)
        self.assertEqual(
            verification["platform_native_b2b_local_model_device_family"],
            "Apple Metal",
        )
        self.assertEqual(verification["platform_native_b2b_cloud_api_calls"], 0)
        self.assertFalse(
            verification["platform_native_b2b_network_download_performed"]
        )
        self.assertEqual(
            verification["platform_native_b2b_mechanical_publication_ready_count"],
            13,
        )
        self.assertEqual(
            verification["platform_native_b2c_mechanical_publication_ready_count"],
            0,
        )
        self.assertEqual(
            verification["platform_native_publication_human_review_completed_count"],
            0,
        )
        self.assertFalse(
            verification["platform_native_publication_external_publish_executed"]
        )
        self.assertEqual(verification["platform_craft_review_artifact_count"], 13)
        self.assertEqual(verification["platform_craft_review_reviewer_count"], 5)
        self.assertEqual(verification["platform_craft_review_expected_human_count"], 65)
        self.assertEqual(verification["platform_craft_review_submitted_human_count"], 0)
        self.assertFalse(verification["platform_craft_review_completed"])
        self.assertFalse(
            verification["platform_craft_review_named_product_comparison_executed"]
        )
        self.assertFalse(
            verification["platform_craft_review_network_submission_enabled"]
        )
        self.assertFalse(verification["platform_craft_review_automatic_publish_enabled"])
        self.assertEqual(verification["named_product_pk_portfolio_completed_rows"], 0)
        self.assertEqual(verification["named_product_pk_portfolio_candidate_wins"], 0)
        self.assertEqual(
            verification["concrete_product_effect_pk_internal_opponent_category_count"],
            13,
        )
        self.assertEqual(
            verification["concrete_product_effect_pk_named_product_baseline_category_count"],
            0,
        )
        self.assertEqual(verification["named_product_challenger_dossier_count"], 13)
        self.assertEqual(
            verification["named_product_challenger_admitted_category_count"], 13
        )
        self.assertEqual(
            verification["named_product_challenger_blocked_category_count"], 0
        )
        self.assertFalse(
            verification["named_product_challenger_automatic_pairing_enabled"]
        )
        self.assertFalse(
            verification["named_product_challenger_four_a_quality_proven"]
        )
        self.assertEqual(
            verification["named_product_challenger_repair_artifact_count"], 7
        )
        self.assertFalse(
            verification["named_product_challenger_repair_production_effect_observed"]
        )

    def test_platform_gold_reference_is_mechanically_strong_but_effect_unproven(self) -> None:
        payload = json.loads(RECEIPT.read_text(encoding="utf-8"))
        verification = payload["verification"]
        self.assertEqual(
            verification["platform_gold_reference_rights_status"],
            "original_clean_room_workspace_reference",
        )
        self.assertEqual(
            verification["platform_gold_reference_training_admission"],
            "candidate_pending_quality_and_human_review",
        )
        self.assertEqual(verification["platform_gold_reference_candidate_count"], 13)
        self.assertEqual(
            verification["platform_gold_reference_pre_human_quality_pass_count"],
            13,
        )
        self.assertEqual(
            verification["platform_gold_reference_pre_human_quality_blocked_count"],
            0,
        )
        self.assertEqual(
            verification[
                "platform_gold_reference_cross_surface_duplicate_pair_count"
            ],
            0,
        )
        self.assertEqual(
            verification[
                "platform_gold_reference_mechanical_publication_ready_count"
            ],
            13,
        )
        self.assertEqual(
            verification[
                "platform_gold_reference_synthetic_b2c_publication_ready_count"
            ],
            0,
        )
        self.assertFalse(
            verification["platform_gold_reference_local_inference_claimed"]
        )
        self.assertEqual(
            verification["platform_gold_reference_cloud_api_call_count"],
            "not_measured_by_worktree",
        )
        self.assertEqual(
            verification["platform_gold_reference_human_review_completed_count"],
            0,
        )
        self.assertFalse(
            verification["platform_gold_reference_production_effect_observed"]
        )
        self.assertFalse(
            verification["platform_gold_reference_four_a_claim_eligible"]
        )
        self.assertFalse(
            verification["platform_gold_reference_top1_claim_eligible"]
        )
        self.assertFalse(
            verification["platform_gold_reference_named_product_baseline"]
        )
        self.assertEqual(
            verification["platform_gold_craft_review_expected_human_count"], 65
        )
        self.assertEqual(
            verification["platform_gold_craft_review_submitted_human_count"], 0
        )
        self.assertFalse(verification["platform_gold_craft_review_completed"])
        self.assertFalse(
            verification[
                "platform_gold_craft_review_named_product_comparison_executed"
            ]
        )
        self.assertFalse(
            verification["platform_gold_craft_review_network_submission_enabled"]
        )
        self.assertFalse(
            verification["platform_gold_craft_review_automatic_publish_enabled"]
        )
        self.assertEqual(
            payload["verification"]["gtm_capability_effect_matrix_video_stage"],
            "brief_only",
        )
        self.assertEqual(
            payload["verification"]["gtm_capability_effect_matrix_audio_stage"],
            "brief_only",
        )
        self.assertEqual(
            payload["verification"][
                "gtm_capability_effect_matrix_advertising_stage"
            ],
            "plan_only_activation_disabled",
        )
        self.assertTrue(
            payload["verification"][
                "run_bound_multimodal_deliverable_registration_present"
            ]
        )
        self.assertEqual(
            payload["verification"]["run_bound_multimodal_allowed_media_types"],
            ["audio/wav", "video/mp4"],
        )
        self.assertTrue(
            payload["verification"][
                "run_bound_multimodal_requires_delivered_approved_run"
            ]
        )
        self.assertTrue(
            payload["verification"][
                "run_bound_multimodal_execution_receipt_bound"
            ]
        )
        self.assertTrue(
            payload["verification"][
                "run_bound_multimodal_named_human_review_separate"
            ]
        )
        self.assertFalse(
            payload["verification"][
                "run_bound_multimodal_self_attested_effect_or_4a_allowed"
            ]
        )
        self.assertRegex(
            payload["verification"]["run_bound_multimodal_demo_content_sha256"],
            r"^[0-9a-f]{64}$",
        )
        self.assertEqual(
            payload["verification"]["run_bound_multimodal_demo_evidence_class"],
            "mixed_real_artifacts_synthetic_control_plane",
        )
        self.assertEqual(
            payload["verification"][
                "run_bound_multimodal_demo_generated_deliverable_count"
            ],
            2,
        )
        self.assertEqual(
            payload["verification"][
                "run_bound_capability_demo_generated_deliverable_count"
            ],
            8,
        )
        self.assertEqual(
            payload["verification"][
                "run_bound_portfolio_demo_generated_deliverable_count"
            ],
            10,
        )
        self.assertTrue(
            payload["verification"][
                "run_bound_capability_exact_delivered_bytes_required"
            ]
        )
        self.assertEqual(
            payload["verification"][
                "run_bound_multimodal_demo_named_human_quality_count"
            ],
            0,
        )
        self.assertEqual(
            payload["verification"][
                "run_bound_multimodal_demo_production_effect_count"
            ],
            0,
        )
        self.assertTrue(
            payload["verification"][
                "run_bound_multimodal_demo_local_model_inference_observed"
            ]
        )
        self.assertTrue(
            payload["verification"][
                "run_bound_multimodal_demo_provider_generation_observed"
            ]
        )
        self.assertFalse(
            payload["verification"]["run_bound_multimodal_demo_radeon_observed"]
        )
        self.assertFalse(
            payload["verification"]["tenant_client_identity_override_allowed"]
        )
        self.assertTrue(payload["verification"]["tenant_artifact_access_scoped"])
        self.assertTrue(payload["verification"]["tenant_run_access_scoped"])
        self.assertTrue(
            payload["verification"]["tenant_event_and_job_payloads_scoped"]
        )
        self.assertTrue(
            payload["verification"]["tenant_learning_memory_scope_enforced"]
        )
        self.assertTrue(
            payload["verification"]["tenant_idempotency_namespace_scoped"]
        )
        self.assertTrue(payload["verification"]["portable_memory_capsule_signed"])
        self.assertTrue(
            payload["verification"]["portable_memory_capsule_tenant_and_project_bound"]
        )
        self.assertTrue(
            payload["verification"]["portable_memory_capsule_expiry_enforced_at_import"]
        )
        self.assertTrue(
            payload["verification"]["portable_memory_capsule_human_review_required"]
        )
        self.assertFalse(
            payload["verification"]["portable_memory_capsule_pending_import_applied"]
        )
        self.assertFalse(
            payload["verification"][
                "portable_memory_capsule_automatic_strategy_mutation_enabled"
            ]
        )
        self.assertFalse(
            payload["verification"]["portable_memory_capsule_external_action_enabled"]
        )
        self.assertTrue(
            payload["verification"][
                "strategy_memory_named_conflict_resolution_present"
            ]
        )
        self.assertTrue(
            payload["verification"]["strategy_memory_resolution_tenant_scoped"]
        )
        self.assertTrue(
            payload["verification"]["strategy_memory_resolution_idempotent"]
        )
        self.assertFalse(
            payload["verification"]["strategy_memory_resolution_source_run_mutated"]
        )
        self.assertTrue(
            payload["verification"]["strategy_memory_resolution_future_runs_only"]
        )
        self.assertTrue(
            payload["verification"][
                "strategy_memory_resolution_human_application_required"
            ]
        )
        self.assertFalse(
            payload["verification"][
                "strategy_memory_resolution_automatic_strategy_mutation_enabled"
            ]
        )
        self.assertEqual(
            payload["evidence_status"]["distributed_database_row_level_security"],
            "not_implemented",
        )
        self.assertEqual(
            payload["evidence_status"]["enterprise_identity_provider_sso_scim"],
            "not_implemented",
        )
        self.assertEqual(
            payload["verification"]["breakout_growth_loop_step_count"], 5
        )
        self.assertEqual(
            payload["verification"]["breakout_growth_loop_archetype_count"], 8
        )
        self.assertTrue(
            payload["verification"]["breakout_growth_loop_paid_independent_core"]
        )
        self.assertFalse(
            payload["verification"][
                "breakout_growth_loop_automatic_external_actions_enabled"
            ]
        )
        self.assertEqual(
            payload["verification"]["text_creative_challenger_territory_count"], 3
        )
        self.assertTrue(
            payload["verification"]["text_creative_challenger_official_first_required"]
        )
        self.assertEqual(
            payload["verification"]["text_creative_challenger_maximum_model_calls"], 3
        )
        self.assertEqual(
            payload["verification"]["text_creative_challenger_execution_mode"],
            "sequential_fail_fast",
        )
        self.assertEqual(
            payload["verification"]["text_creative_challenger_maximum_concurrency"], 1
        )
        self.assertEqual(
            payload["verification"]["text_creative_challenger_default_retry_rounds"], 0
        )
        self.assertEqual(
            payload["verification"]["text_creative_challenger_blind_pair_count"], 6
        )
        self.assertEqual(
            payload["verification"]["text_creative_challenger_human_review_task_count"], 30
        )
        self.assertFalse(
            payload["verification"]["text_creative_challenger_model_judge_autofill_enabled"]
        )
        self.assertTrue(
            payload["verification"]["text_creative_challenger_human_attestation_required"]
        )
        self.assertTrue(
            payload["verification"]["text_creative_challenger_binary_preference_only"]
        )
        self.assertTrue(
            payload["verification"]["text_creative_challenger_wilson_confidence_gate"]
        )
        self.assertFalse(
            payload["verification"]["text_creative_challenger_tie_auto_selection_enabled"]
        )
        self.assertFalse(
            payload["verification"][
                "text_creative_challenger_automatic_winner_selection_enabled"
            ]
        )
        self.assertFalse(
            payload["verification"][
                "text_creative_challenger_automatic_external_publish_enabled"
            ]
        )
        self.assertEqual(
            payload["evidence_status"]["real_production_business_outcome"],
            "not_observed",
        )
        self.assertEqual(
            payload["evidence_status"]["radeon_local_key_inference"],
            "not_observed_by_this_receipt",
        )
        self.assertEqual(
            payload["evidence_status"]["real_model_generated_multimodal_deliverable"],
            (
                "two_run_bound_audio_video_deliverables_registered_with_mixed_real_"
                "provenance_synthetic_control_plane_human_quality_and_effect_unproven"
            ),
        )
        self.assertTrue(
            payload["verification"]["local_campaign_pack_mechanical_ready"]
        )
        self.assertTrue(
            payload["verification"]["local_campaign_pack_true_4k_geometry"]
        )
        self.assertFalse(
            payload["verification"]["local_campaign_pack_named_human_review_passed"]
        )
        self.assertFalse(
            payload["verification"]["local_campaign_pack_four_a_preference_proven"]
        )
        self.assertFalse(
            payload["verification"]["local_campaign_pack_product_admission_passed"]
        )
        self.assertTrue(
            payload["verification"][
                "local_campaign_pack_visual_blind_review_api_present"
            ]
        )
        self.assertTrue(
            payload["verification"][
                "local_campaign_pack_visual_offline_review_kit_available"
            ]
        )
        self.assertTrue(
            payload["verification"][
                "local_campaign_pack_visual_offline_review_kit_invitation_bound"
            ]
        )
        self.assertFalse(
            payload["verification"][
                "local_campaign_pack_visual_offline_review_kit_contains_token"
            ]
        )
        self.assertFalse(
            payload["verification"][
                "local_campaign_pack_visual_offline_review_network_submission_enabled"
            ]
        )
        self.assertEqual(
            payload["verification"][
                "local_campaign_pack_visual_blind_review_expected_review_count"
            ],
            5,
        )
        self.assertEqual(
            payload["verification"][
                "local_campaign_pack_visual_blind_review_submitted_review_count"
            ],
            0,
        )
        for field in (
            "local_campaign_pack_visual_blind_review_complete",
            "local_campaign_pack_visual_human_preference_observed",
            "local_campaign_pack_visual_promotion_recommendation_eligible",
            "local_campaign_pack_visual_automatic_runtime_switch_enabled",
            "local_campaign_pack_visual_automatic_publish_enabled",
            "local_campaign_pack_visual_product_admission_passed",
            "local_campaign_pack_visual_four_a_preference_proven",
            "local_campaign_pack_visual_production_effect_proven",
        ):
            self.assertFalse(payload["verification"][field], field)
        campaign_review = payload["external_gate_snapshot"][
            "campaign_pack_visual_blind_review"
        ]
        self.assertEqual(campaign_review["expected_review_count"], 5)
        self.assertEqual(campaign_review["submitted_review_count"], 0)
        self.assertFalse(campaign_review["review_complete"])
        self.assertFalse(campaign_review["automatic_publish_enabled"])
        self.assertFalse(campaign_review["product_admission_passed"])
        self.assertTrue(campaign_review["offline_review_kit_available"])
        self.assertTrue(campaign_review["offline_review_kit_invitation_bound"])
        self.assertFalse(
            campaign_review["offline_review_kit_contains_invitation_token"]
        )
        self.assertFalse(
            campaign_review["offline_review_kit_network_submission_enabled"]
        )
        self.assertEqual(
            payload["verification"]["local_gemma3_strategy_probe_model"],
            "mlx-community/gemma-3-12b-it-4bit",
        )
        self.assertFalse(
            payload["verification"]["local_gemma3_strategy_probe_download_performed"]
        )
        self.assertEqual(
            payload["verification"]["local_gemma3_strategy_probe_cloud_api_calls"],
            0,
        )
        self.assertFalse(
            payload["verification"]["local_gemma3_strategy_probe_training_observed"]
        )
        self.assertFalse(
            payload["verification"]["local_gemma3_strategy_probe_draft_accepted"]
        )
        self.assertFalse(
            payload["verification"]["local_gemma3_strategy_probe_repair_accepted"]
        )
        self.assertTrue(
            payload["verification"]["local_gemma3_strategy_challenger_accepted"]
        )
        self.assertEqual(
            payload["verification"]["local_gemma3_strategy_challenger_model"],
            "mlx-community/gemma-3-12b-it-4bit",
        )
        self.assertEqual(
            len(payload["verification"]["local_gemma3_strategy_challenger_candidate_sha256"]),
            64,
        )
        self.assertFalse(
            payload["verification"]["local_gemma3_strategy_challenger_training_observed"]
        )
        self.assertFalse(
            payload["verification"]["local_gemma3_strategy_challenger_radeon_observed"]
        )
        self.assertFalse(
            payload["verification"]["local_gemma3_strategy_challenger_automatic_release_authority"]
        )
        self.assertEqual(
            payload["verification"]["local_gemma3_strategy_portfolio_case_count"], 8
        )
        self.assertEqual(
            payload["verification"]["local_gemma3_strategy_portfolio_accepted_case_count"],
            8,
        )
        self.assertTrue(
            payload["verification"]["local_gemma3_strategy_portfolio_quality_gate_passed"]
        )
        self.assertEqual(
            payload["verification"]["local_gemma3_strategy_portfolio_channel_distribution"],
            {"LinkedIn": 2, "community": 2, "owned": 2, "partner": 2},
        )
        self.assertEqual(
            payload["verification"]["local_gemma3_strategy_portfolio_unique_strategy_count"],
            8,
        )
        self.assertLessEqual(
            payload["verification"][
                "local_gemma3_strategy_portfolio_maximum_pairwise_content_jaccard"
            ],
            0.60,
        )
        self.assertFalse(
            payload["verification"][
                "local_gemma3_strategy_portfolio_human_preference_observed"
            ]
        )
        self.assertFalse(
            payload["verification"][
                "local_gemma3_strategy_portfolio_production_effect_observed"
            ]
        )
        self.assertEqual(
            payload["verification"]["local_gemma3_text_craft_model"],
            "mlx-community/gemma-3-12b-it-4bit",
        )
        self.assertEqual(
            payload["verification"]["local_gemma3_text_craft_device"],
            "Apple Metal",
        )
        self.assertEqual(
            payload["verification"]["local_gemma3_text_craft_model_load_count"], 1
        )
        self.assertEqual(
            payload["verification"]["local_gemma3_text_craft_quality_call_count"], 13
        )
        self.assertEqual(
            payload["verification"][
                "local_gemma3_text_craft_advisory_pass_territory_count"
            ],
            2,
        )
        self.assertEqual(
            payload["verification"]["local_gemma3_text_craft_repaired_candidate_count"],
            1,
        )
        self.assertEqual(
            payload["verification"]["local_gemma3_text_craft_post_repair_review_count"],
            3,
        )
        for field in (
            "local_gemma3_text_craft_all_territories_advisory_pass",
            "local_gemma3_text_craft_network_download_performed",
            "local_gemma3_text_craft_blind_human_review_completed",
            "local_gemma3_text_craft_production_effect_observed",
        ):
            self.assertFalse(payload["verification"][field], field)
        self.assertEqual(
            payload["verification"]["local_gemma3_text_craft_cloud_api_calls"], 0
        )
        self.assertTrue(payload["verification"]["gtm_cockpit_schema_present"])
        self.assertTrue(
            payload["verification"]["gtm_cockpit_tenant_scoped_api_present"]
        )
        self.assertTrue(
            payload["verification"]["gtm_cockpit_browser_digest_verified"]
        )
        self.assertTrue(
            payload["verification"]["gtm_cockpit_operator_route_present"]
        )
        self.assertFalse(
            payload["verification"]["gtm_cockpit_automatic_external_action_enabled"]
        )
        self.assertFalse(
            payload["verification"]["gtm_cockpit_four_a_effect_claim_eligible"]
        )
        self.assertFalse(
            payload["verification"]["gtm_cockpit_top1_claim_eligible"]
        )
        self.assertEqual(payload["verification"]["lifecycle_closure_case_count"], 456)
        self.assertEqual(
            payload["verification"]["lifecycle_closure_scenario_count"], 1976
        )
        self.assertEqual(
            payload["verification"][
                "lifecycle_closure_minimum_cases_per_failure_mode"
            ],
            152,
        )
        self.assertTrue(
            payload["verification"][
                "lifecycle_closure_all_ten_capabilities_connected"
            ]
        )
        self.assertTrue(
            payload["verification"][
                "lifecycle_closure_zero_budget_paid_channels_excluded"
            ]
        )
        self.assertTrue(
            payload["verification"][
                "lifecycle_closure_positive_paths_require_human_review"
            ]
        )
        self.assertEqual(
            payload["verification"][
                "lifecycle_closure_production_outcomes_observed"
            ],
            0,
        )
        self.assertTrue(
            payload["verification"][
                "local_multimodal_qualification_inference_observed"
            ]
        )
        self.assertEqual(
            payload["verification"]["local_multimodal_qualification_cloud_api_calls"],
            0,
        )
        self.assertEqual(
            payload["verification"]["local_multimodal_qualification_network_downloads"],
            0,
        )
        self.assertTrue(
            payload["verification"]["local_multimodal_speech_delivery_spec_passed"]
        )
        self.assertFalse(
            payload["verification"]["local_multimodal_speech_human_review_passed"]
        )
        self.assertTrue(
            payload["verification"]["local_multimodal_video_subject_recognizable"]
        )
        self.assertFalse(
            payload["verification"]["local_multimodal_video_delivery_gate_passed"]
        )
        self.assertFalse(
            payload["verification"]["local_multimodal_product_admission_passed"]
        )
        self.assertTrue(
            payload["verification"][
                "local_multimodal_qualification_playable_api_present"
            ]
        )
        self.assertEqual(
            payload["verification"]["revenue_memory_demo_data_class"], "synthetic"
        )
        self.assertTrue(
            payload["verification"]["revenue_memory_demo_device_a_bundle_ready"]
        )
        self.assertTrue(
            payload["verification"][
                "revenue_memory_demo_positive_feedback_mechanics_ready"
            ]
        )
        self.assertEqual(
            payload["verification"][
                "revenue_memory_demo_pending_import_memory_count"
            ],
            0,
        )
        self.assertEqual(
            payload["verification"][
                "revenue_memory_demo_approved_import_memory_count"
            ],
            1,
        )
        self.assertTrue(
            payload["verification"][
                "revenue_memory_demo_device_a_final_cockpit_closed"
            ]
        )
        self.assertTrue(
            payload["verification"][
                "revenue_memory_demo_device_b_next_cycle_prepared"
            ]
        )
        self.assertEqual(
            payload["verification"][
                "revenue_memory_demo_device_b_inherited_memory_count"
            ],
            1,
        )
        self.assertEqual(
            payload["verification"][
                "revenue_memory_demo_device_b_eligible_memory_count"
            ],
            1,
        )
        self.assertEqual(
            payload["verification"][
                "revenue_memory_demo_device_b_memory_application_status"
            ],
            "eligible_pending_human_application",
        )
        self.assertEqual(
            payload["verification"][
                "revenue_memory_demo_device_b_memory_conflict_count"
            ],
            0,
        )
        self.assertRegex(
            payload["verification"][
                "revenue_memory_demo_device_b_memory_decision_sha256"
            ],
            r"^[0-9a-f]{64}$",
        )
        self.assertTrue(
            payload["verification"][
                "revenue_memory_demo_device_b_memory_human_application_required"
            ]
        )
        self.assertTrue(
            payload["verification"]["synthetic_lifecycle_demo_api_present"]
        )
        self.assertTrue(
            payload["verification"][
                "synthetic_lifecycle_demo_browser_integrity_gate_present"
            ]
        )
        self.assertTrue(
            payload["verification"][
                "synthetic_lifecycle_demo_device_a_closed_loop"
            ]
        )
        self.assertTrue(
            payload["verification"][
                "synthetic_lifecycle_demo_device_b_inherited_cycle"
            ]
        )
        self.assertFalse(
            payload["verification"][
                "synthetic_lifecycle_demo_production_effect_proven"
            ]
        )
        self.assertEqual(
            payload["verification"]["revenue_memory_demo_external_api_calls"], 0
        )
        self.assertFalse(
            payload["verification"][
                "revenue_memory_demo_external_publish_executed"
            ]
        )
        self.assertFalse(
            payload["verification"][
                "revenue_memory_demo_synthetic_revenue_is_production_evidence"
            ]
        )
        self.assertEqual(
            payload["verification"]["comfyui_admitted_backend_count"], 0
        )
        self.assertEqual(
            payload["verification"]["official_comfyui_blueprint_capture_count"], 4
        )
        self.assertEqual(
            payload["verification"]["official_comfyui_api_export_count"], 4
        )
        self.assertEqual(
            payload["verification"]["official_comfyui_declared_weight_count"], 18
        )
        self.assertEqual(
            payload["verification"][
                "official_comfyui_immutable_weight_metadata_count"
            ],
            18,
        )
        self.assertEqual(
            payload["verification"]["official_comfyui_locally_verified_weight_count"],
            0,
        )
        self.assertFalse(
            payload["verification"]["official_comfyui_weight_rights_gate_passed"]
        )
        self.assertEqual(
            payload["verification"][
                "comfyui_model_card_license_ready_workflow_ids"
            ],
            ["ace-step-1.5-text-to-audio", "qwen-image-2512"],
        )
        self.assertEqual(
            payload["verification"]["comfyui_evidence_output_wrapper_count"], 4
        )
        self.assertEqual(
            payload["verification"][
                "comfyui_output_wrapper_schema_validated_count"
            ],
            4,
        )
        self.assertEqual(
            payload["verification"]["comfyui_executable_wrapper_count"], 0
        )
        self.assertEqual(
            payload["verification"][
                "comfyui_prompt_structure_validated_wrapper_count"
            ],
            4,
        )
        self.assertEqual(
            payload["verification"]["comfyui_prompt_validation_queued_count"], 0
        )
        self.assertEqual(
            payload["verification"]["comfyui_gpu_handoff_workflow_ids"],
            ["qwen-image-2512", "ace-step-1.5-text-to-audio"],
        )
        self.assertEqual(
            payload["verification"]["comfyui_gpu_handoff_download_count"], 8
        )
        self.assertEqual(
            payload["verification"]["comfyui_gpu_handoff_total_weight_bytes"],
            46_464_106_990,
        )
        self.assertEqual(
            payload["verification"]["comfyui_frozen_binding_contract_count"], 4
        )
        self.assertEqual(
            payload["evidence_status"]["four_a_effect_claim"], "not_eligible"
        )
        self.assertEqual(
            payload["external_gate_snapshot"]["gold_human_review"][
                "submitted_review_count"
            ],
            0,
        )
        self.assertFalse(
            payload["external_gate_snapshot"]["curated_human_audit"][
                "freeze_passed"
            ]
        )
        self.assertFalse(
            payload["external_gate_snapshot"]["amd_official_advisory_review"][
                "accepted_as_training_material"
            ]
        )
        closure = payload["external_gate_snapshot"]["amd_product_closure_sprint"]
        self.assertEqual(closure["status"], "aborted_backend_instability")
        self.assertEqual(closure["sealed_failed_record_count"], 8)
        self.assertEqual(closure["observed_spend_delta_usd"], 0)
        self.assertFalse(closure["accepted_as_training_material"])
        benchmark = payload["external_gate_snapshot"]["local_creative_benchmark"]
        self.assertEqual(benchmark["status"], "completed")
        self.assertIsNone(benchmark["blocker"])
        self.assertTrue(benchmark["preflight_passed"])
        self.assertEqual(benchmark["planned_case_count"], 9)
        self.assertEqual(benchmark["observed_case_count"], 9)
        self.assertEqual(benchmark["completed_case_count"], 9)
        self.assertEqual(benchmark["planned_model_call_count"], 27)
        self.assertEqual(benchmark["completed_model_call_count"], 27)
        self.assertEqual(benchmark["validated_candidate_count"], 27)
        portfolio = payload["external_gate_snapshot"][
            "local_portfolio_blind_review"
        ]
        self.assertEqual(
            portfolio["status"], "awaiting_270_named_human_reviews"
        )
        self.assertEqual(portfolio["case_count"], 9)
        self.assertEqual(portfolio["pair_count"], 54)
        self.assertEqual(portfolio["reviewer_slot_count"], 5)
        self.assertEqual(portfolio["expected_review_count"], 270)
        self.assertEqual(portfolio["submitted_review_count"], 0)
        self.assertFalse(portfolio["review_complete"])
        self.assertFalse(portfolio["portfolio_promotion_passed"])
        self.assertFalse(portfolio["human_preference_observed"])
        self.assertTrue(portfolio["runtime_api_present"])
        self.assertEqual(portfolio["runtime_expected_review_count"], 270)
        self.assertEqual(portfolio["runtime_submitted_review_count"], 0)
        self.assertTrue(portfolio["review_submission_enabled"])
        self.assertTrue(portfolio["restart_durable"])
        self.assertFalse(portfolio["automatic_winner_selection_enabled"])
        guardrails = payload["external_gate_snapshot"]["production_guardrails"]
        self.assertEqual(guardrails["case_count"], 250)
        self.assertEqual(guardrails["minimum_cases_per_category"], 50)
        self.assertEqual(guardrails["attack_recall"], 1.0)
        self.assertEqual(guardrails["false_block_rate"], 0.0)
        self.assertEqual(guardrails["escape_count"], 0)
        self.assertTrue(guardrails["api_boundary_enforced"])
        self.assertFalse(guardrails["raw_prompt_or_pii_retained"])
        self.assertFalse(guardrails["production_deployment_observed"])
        traces = payload["external_gate_snapshot"]["production_trace_retention"]
        self.assertEqual(traces["retention_days"], 90)
        self.assertTrue(traces["local_restart_smoke_observed"])
        self.assertTrue(traces["hash_chain_valid"])
        self.assertTrue(traces["valid_request_boundary_instrumented"])
        self.assertFalse(traces["raw_content_retained"])
        self.assertFalse(traces["remote_required_check_observed"])
        self.assertFalse(traces["production_deployment_observed"])
        self.assertFalse(traces["production_trace_coverage_observed"])
        context_quality = payload["external_gate_snapshot"]["gtm_context_quality"]
        self.assertEqual(context_quality["observed_local_call_count"], 24)
        self.assertLess(context_quality["median_context_utilization"], 0.40)
        self.assertLess(context_quality["p95_context_utilization"], 0.60)
        self.assertTrue(context_quality["context_utilization_gate_passed"])
        self.assertEqual(context_quality["long_session_eval_count"], 24)
        self.assertGreaterEqual(
            context_quality["minimum_long_session_message_count"], 50
        )
        self.assertTrue(context_quality["long_session_compaction_gate_passed"])
        self.assertEqual(context_quality["new_model_calls"], 0)
        agentic = payload["external_gate_snapshot"]["agentic_product_readiness"]
        sandbox_receipt_exists = (
            ROOT / "evidence/v10/tool-execution-sandbox-v1.json"
        ).is_file()
        self.assertEqual(agentic["audit_item_count"], 12)
        self.assertEqual(agentic["passed_item_count"], 9 if sandbox_receipt_exists else 8)
        self.assertEqual(agentic["gap_item_count"], 3 if sandbox_receipt_exists else 4)
        self.assertEqual(
            agentic["gap_ids"],
            (["PR-09", "PR-11", "PR-12"] if sandbox_receipt_exists else ["PR-06", "PR-09", "PR-11", "PR-12"]),
        )
        self.assertFalse(agentic["enterprise_production_ready"])
        self.assertIn("does not prove 4A preference", agentic["truth_boundary"])
        sandbox = payload["external_gate_snapshot"]["tool_execution_sandbox"]
        self.assertTrue(sandbox["adapter_present"])
        self.assertEqual(sandbox["runtime_observed"], sandbox_receipt_exists)
        self.assertEqual(sandbox["runtime_passed"], sandbox_receipt_exists)
        self.assertEqual(
            payload["verification"]["tool_execution_sandbox_observed"],
            sandbox_receipt_exists,
        )
        self.assertEqual(
            payload["verification"]["tool_execution_sandbox_runtime_passed"],
            sandbox_receipt_exists,
        )
        if not sandbox_receipt_exists:
            self.assertIsNone(sandbox["receipt_content_sha256"])
            self.assertIn("not claimed", sandbox["truth_boundary"])

    def test_last_mile_quality_is_primary_and_business_outcome_is_separate(self) -> None:
        payload = json.loads(RECEIPT.read_text(encoding="utf-8"))
        verification = payload["verification"]
        self.assertEqual(
            verification["last_mile_effect_primary_axis"],
            "last_mile_generated_execution_quality",
        )
        self.assertEqual(
            verification["last_mile_effect_secondary_axis"],
            "observed_business_outcome",
        )
        self.assertEqual(verification["last_mile_production_lane_count"], 14)
        self.assertEqual(
            verification["last_mile_mechanically_ready_lane_count"], 14
        )
        self.assertEqual(
            verification[
                "last_mile_same_brief_comparison_completed_lane_count"
            ],
            0,
        )
        self.assertFalse(
            verification["last_mile_execution_quality_alignment_achieved"]
        )
        self.assertFalse(verification["last_mile_business_outcome_observed"])
        self.assertEqual(
            payload["evidence_status"]["business_outcome_effect"],
            "tracked_as_separate_secondary_axis_not_observed",
        )


if __name__ == "__main__":
    unittest.main()
