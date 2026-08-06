from __future__ import annotations

import json
import unittest
from pathlib import Path

from prooflaunch_remix.v10_free_cloud_router import compile_free_cloud_execution_plan


ROOT = Path(__file__).resolve().parents[1]
PANEL = json.loads(
    (ROOT / "config/cortex_x_v10_frontier_api_panel.json").read_text(encoding="utf-8")
)


class FreeCloudRouterTests(unittest.TestCase):
    def test_no_credentials_fails_closed_without_disabling_local_first(self) -> None:
        plan = compile_free_cloud_execution_plan(
            PANEL,
            credential_state={},
            auxiliary_state={},
            compute_session_state={},
            observed_at="2026-08-02",
        )
        self.assertEqual(plan["selected_api_candidate_count"], 0)
        self.assertEqual(plan["qualification_request_ceiling"], 0)
        self.assertIsNone(plan["selected_weight_training_route"])
        self.assertIsNone(plan["selected_short_inference_route"])
        self.assertEqual(len(plan["free_compute_priority"]), 8)
        self.assertEqual(plan["status"], "cloud_blocked_local_pipeline_remains_ready")
        self.assertTrue(plan["local_first"])
        self.assertFalse(plan["paid_fallback_enabled"])
        self.assertFalse(
            plan["recommended_activation"]["inference_is_weight_training"]
        )
        self.assertEqual(
            [
                row["provider"]
                for row in plan["recommended_activation"]["minimum_api_bundle"]
            ],
            ["groq", "google_ai_studio", "openrouter"],
        )
        self.assertEqual(
            plan["recommended_activation"]["weight_training_bundle"][0]["provider"],
            "lightning_ai_studios",
        )

    def test_available_keys_are_combined_by_role_and_provider_independence(self) -> None:
        plan = compile_free_cloud_execution_plan(
            PANEL,
            credential_state={
                "GROQ_API_KEY": True,
                "GEMINI_API_KEY": True,
                "OPENROUTER_API_KEY": True,
                "LIGHTNING_API_KEY": True,
                "CLOUDFLARE_API_TOKEN": True,
            },
            auxiliary_state={
                "LIGHTNING_FREE_ONLY_ACK": True,
                "CLOUDFLARE_ACCOUNT_ID": True,
            },
            compute_session_state={"LIGHTNING_API_KEY": True},
            observed_at="2026-08-02",
        )
        self.assertEqual(plan["ready_api_role_count"], 4)
        self.assertEqual(plan["selected_weight_training_route"], "lightning_ai_studios")
        self.assertLessEqual(
            plan["qualification_request_ceiling"],
            plan["free_route_daily_request_limit"],
        )
        for role in plan["api_roles"].values():
            providers = [row["provider"] for row in role["routes"]]
            self.assertEqual(len(providers), len(set(providers)))
            self.assertTrue(all(row["release_authority"] is False for row in role["routes"]))

        multimodal = plan["api_roles"]["multimodal_understanding"]["routes"]
        self.assertIn("google_ai_studio", {row["provider"] for row in multimodal})
        self.assertIn("openrouter", {row["provider"] for row in multimodal})
        self.assertNotIn("github_models", {row["provider"] for row in multimodal})
        structured = plan["api_roles"]["structured_agent_draft"]["routes"]
        self.assertEqual(
            {row["provider"] for row in structured},
            {"groq", "cloudflare_workers_ai"},
        )

        retired_github_only = compile_free_cloud_execution_plan(
            PANEL,
            credential_state={"GITHUB_MODELS_TOKEN": True},
            auxiliary_state={},
            compute_session_state={},
            observed_at="2026-08-02",
        )
        self.assertEqual(retired_github_only["selected_api_candidate_count"], 0)

    def test_cloudflare_and_lightning_require_explicit_auxiliary_guards(self) -> None:
        blocked = compile_free_cloud_execution_plan(
            PANEL,
            credential_state={
                "CLOUDFLARE_API_TOKEN": True,
                "LIGHTNING_API_KEY": True,
            },
            auxiliary_state={},
            compute_session_state={},
            observed_at="2026-08-02",
        )
        selected = set(blocked["selected_api_candidate_ids"])
        self.assertNotIn("cloudflare-gpt-oss-120b-free-allocation", selected)
        self.assertNotIn("cloudflare-gemma-4-26b-free-allocation", selected)
        self.assertNotIn("lightning-nemotron-3-ultra-free", selected)

    def test_nvidia_free_multimodal_route_prefers_the_frozen_diffusiongemma_identity(self) -> None:
        plan = compile_free_cloud_execution_plan(
            PANEL,
            credential_state={"NVIDIA_API_KEY": True},
            auxiliary_state={},
            compute_session_state={},
            observed_at="2026-08-02",
        )
        routes = plan["api_roles"]["multimodal_understanding"]["routes"]
        self.assertEqual(
            [row["candidate_id"] for row in routes],
            ["nvidia-diffusiongemma-26b-free"],
        )
        self.assertEqual(routes[0]["api_model"], "google/diffusiongemma-26b-a4b-it")
        self.assertEqual(routes[0]["maximum_call_cost_usd"], 0.0)
        self.assertFalse(routes[0]["release_authority"])

    def test_lightning_has_priority_when_multiple_training_sessions_are_ready(self) -> None:
        plan = compile_free_cloud_execution_plan(
            PANEL,
            credential_state={},
            auxiliary_state={},
            compute_session_state={
                "KAGGLE_CONFIG_PRESENT": True,
                "LIGHTNING_API_KEY": True,
                "MODAL_CONFIG_PRESENT": True,
            },
            observed_at="2026-08-02",
        )
        self.assertEqual(plan["selected_weight_training_route"], "lightning_ai_studios")
        self.assertEqual(plan["weight_training_status"], "ready_checkpointed_free_gpu")

    def test_modelscope_is_training_eligible_and_precedes_generic_serverless_gpu(self) -> None:
        plan = compile_free_cloud_execution_plan(
            PANEL,
            credential_state={},
            auxiliary_state={},
            compute_session_state={
                "MODELSCOPE_NOTEBOOK_SESSION_READY": True,
                "MODAL_CONFIG_PRESENT": True,
                "KAGGLE_CONFIG_PRESENT": True,
            },
            observed_at="2026-08-02",
        )
        self.assertEqual(plan["selected_weight_training_route"], "modelscope_notebook")
        route = next(
            row
            for row in plan["free_compute_priority"]
            if row["provider"] == "modelscope_notebook"
        )
        self.assertTrue(route["weight_training_eligible"])
        self.assertTrue(route["short_inference_eligible"])

    def test_cerebras_trial_credentials_do_not_enter_zero_cost_routes(self) -> None:
        plan = compile_free_cloud_execution_plan(
            PANEL,
            credential_state={"CEREBRAS_API_KEY": True},
            auxiliary_state={},
            compute_session_state={},
            observed_at="2026-08-02",
        )
        self.assertEqual(plan["selected_api_candidate_count"], 0)
        self.assertEqual(plan["qualification_request_ceiling"], 0)

    def test_all_compute_routes_are_classified_without_promoting_demo_only_gpu(self) -> None:
        plan = compile_free_cloud_execution_plan(
            PANEL,
            credential_state={},
            auxiliary_state={},
            compute_session_state={
                "HF_TOKEN": True,
                "HF_ZEROGPU_SPACE_READY": True,
                "NVIDIA_LAUNCHPAD_SESSION_READY": True,
            },
            observed_at="2026-08-02",
        )
        routes = {row["provider"]: row for row in plan["free_compute_priority"]}
        self.assertEqual(len(routes), 8)
        self.assertTrue(routes["huggingface_zerogpu"]["session_ready"])
        self.assertTrue(routes["huggingface_zerogpu"]["short_inference_eligible"])
        self.assertFalse(routes["huggingface_zerogpu"]["weight_training_eligible"])
        self.assertTrue(routes["nvidia_launchpad"]["session_ready"])
        self.assertFalse(routes["nvidia_launchpad"]["short_inference_eligible"])
        self.assertFalse(routes["nvidia_launchpad"]["weight_training_eligible"])
        self.assertEqual(plan["selected_short_inference_route"], "huggingface_zerogpu")
        self.assertIsNone(plan["selected_weight_training_route"])

    def test_colab_can_be_selected_but_is_lower_priority_than_credit_backed_routes(self) -> None:
        colab_only = compile_free_cloud_execution_plan(
            PANEL,
            credential_state={},
            auxiliary_state={},
            compute_session_state={"GOOGLE_COLAB_SESSION_READY": True},
            observed_at="2026-08-02",
        )
        self.assertEqual(colab_only["selected_weight_training_route"], "google_colab_free")

        modal_and_colab = compile_free_cloud_execution_plan(
            PANEL,
            credential_state={},
            auxiliary_state={},
            compute_session_state={
                "MODAL_CONFIG_PRESENT": True,
                "GOOGLE_COLAB_SESSION_READY": True,
            },
            observed_at="2026-08-02",
        )
        self.assertEqual(modal_and_colab["selected_weight_training_route"], "modal_starter")


if __name__ == "__main__":
    unittest.main()
