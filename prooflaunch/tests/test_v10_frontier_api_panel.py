from __future__ import annotations

import json
import unittest
from pathlib import Path

from prooflaunch_remix.v10_contracts import V10ContractError
from prooflaunch_remix.v10_frontier_api_panel import (
    AccessClass,
    AgenticObservation,
    CapabilityLane,
    FrontierModel,
    MiniMaxVideoRequest,
    OpenWeightStatus,
    admitted_candidates,
    rank_agentic_observations,
    request_ceiling,
)


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config/cortex_x_v10_frontier_api_panel.json"
PREFLIGHT = ROOT / "evidence/v10/frontier-api-panel-preflight.json"
AVAILABILITY = ROOT / "evidence/v10/frontier-free-api-availability-2026-07-31.json"
REGISTRY = ROOT / "config/frontier-free-api-candidates.2026-07-31.json"
BRIEF = "b" * 64


def candidate(candidate_id: str = "candidate-a") -> FrontierModel:
    return FrontierModel(
        candidate_id,
        "provider",
        "model",
        "https://api.example.com/v1/chat/completions",
        CapabilityLane.AGENTIC_GTM,
        AccessClass.DEVELOPER_CREDITS,
        "EXAMPLE_API_KEY",
        0.1,
        "https://docs.example.com/model",
        "2026-07-31",
        True,
        OpenWeightStatus.UNKNOWN,
    )


class FrontierPanelTests(unittest.TestCase):
    def test_zero_cost_is_an_explicit_access_class_not_a_paid_model_claim(self) -> None:
        free = FrontierModel(
            **{
                **candidate("free").__dict__,
                "access_class": AccessClass.ZERO_COST_RATE_LIMITED,
                "maximum_call_cost_usd": 0.0,
            }
        )
        self.assertEqual(free.maximum_call_cost_usd, 0.0)
        with self.assertRaises(V10ContractError):
            FrontierModel(**{**candidate("false-free").__dict__, "maximum_call_cost_usd": 0.0})
        with self.assertRaises(V10ContractError):
            FrontierModel(
                **{
                    **candidate("priced-free").__dict__,
                    "access_class": AccessClass.ZERO_COST_RATE_LIMITED,
                }
            )

    def test_successive_halving_free_panel_stays_inside_daily_limit(self) -> None:
        self.assertEqual(request_ceiling(19), 37)
        with self.assertRaises(V10ContractError):
            request_ceiling(0)

    def test_external_models_cannot_be_marked_as_competition_core(self) -> None:
        with self.assertRaises(V10ContractError):
            FrontierModel(
                **{
                    **candidate().__dict__,
                    "competition_core_allowed": True,
                }
            )

    def test_admission_requires_catalog_observation_and_environment_credential(self) -> None:
        found = candidate("found")
        missing = FrontierModel(**{**candidate("missing").__dict__, "catalog_observed": False})
        self.assertEqual(
            admitted_candidates(
                (found, missing),
                credential_env_present={"EXAMPLE_API_KEY": True},
            ),
            (found,),
        )
        self.assertEqual(
            admitted_candidates(
                (found,),
                credential_env_present={"EXAMPLE_API_KEY": False},
            ),
            (),
        )

    def test_agentic_rank_is_hard_gate_first_then_cost_latency(self) -> None:
        valid_slow = AgenticObservation("slow", BRIEF, True, True, True, True, True, 4, 4, 2000, 0.02)
        valid_fast = AgenticObservation("fast", BRIEF, True, True, True, True, True, 4, 4, 1000, 0.02)
        invalid = AgenticObservation("cheap-invalid", BRIEF, True, False, True, True, True, 4, 4, 10, 0.0)
        ranked = rank_agentic_observations((valid_slow, invalid, valid_fast))
        self.assertEqual([item.candidate_id for item in ranked], ["fast", "slow"])
        with self.assertRaises(V10ContractError):
            rank_agentic_observations((valid_fast, AgenticObservation("other", "c" * 64, True, True, True, True, True, 4, 4, 1, 0)))

    def test_minimax_video_uses_the_documented_h3_contract(self) -> None:
        request = MiniMaxVideoRequest("GTM launch film", duration_seconds=5)
        self.assertEqual(request.payload()["model"], "MiniMax-H3")
        self.assertEqual(request.payload()["resolution"], "2K")
        self.assertEqual(request.payload()["content"][0]["type"], "text")
        with self.assertRaises(V10ContractError):
            MiniMaxVideoRequest("GTM launch film", duration_seconds=16)
        with self.assertRaises(V10ContractError):
            MiniMaxVideoRequest("GTM launch film", resolution="1080P")
        with self.assertRaises(V10ContractError):
            MiniMaxVideoRequest("GTM launch film", first_frame_image="file:///private.png")
        hailuo = MiniMaxVideoRequest(
            "legacy GTM film",
            model="MiniMax-Hailuo-2.3",
            duration_seconds=6,
            resolution="1080P",
        )
        self.assertEqual(hailuo.payload()["model"], "MiniMax-Hailuo-2.3")

    def test_panel_separates_sponsored_paid_and_open_weight_truth(self) -> None:
        panel = json.loads(CONFIG.read_text(encoding="utf-8"))
        ids = {item["candidate_id"] for item in panel["candidates"]}
        self.assertIn("amd-deepseek-v4-flash-0731", ids)
        self.assertIn("amd-minimax-m3", ids)
        self.assertIn("minimax-direct-m27", ids)
        self.assertIn("minimax-direct-m27-highspeed", ids)
        self.assertIn("minimax-direct-m3", ids)
        self.assertIn("minimax-direct-hailuo-23", ids)
        self.assertIn("minimax-direct-h3", ids)
        self.assertIn("openrouter-nemotron-3-ultra-free", ids)
        self.assertIn("openrouter-nemotron-3-omni-free", ids)
        self.assertIn("openrouter-nemotron-nano-12b-vl-free", ids)
        self.assertNotIn("openrouter-poolside-laguna-xs-free", ids)
        self.assertIn("openrouter-gemma-4-26b-free", ids)
        self.assertIn("cloudflare-gemma-4-26b-free-allocation", ids)
        self.assertIn("nvidia-deepseek-v4-pro-free", ids)
        self.assertIn("nvidia-kimi-k26-free", ids)
        self.assertIn("nvidia-diffusiongemma-26b-free", ids)
        self.assertIn("sambanova-gemma-4-31b-preview-free", ids)
        self.assertIn("mistral-large-latest-free-mode", ids)
        self.assertIn("cerebras-gpt-oss-120b-trial-credit", ids)
        self.assertIn("cerebras-zai-glm-47-trial-credit", ids)
        self.assertNotIn("github-models-gpt-4p1-free-v2", ids)
        self.assertIn("lightning-nemotron-3-ultra-free", ids)
        self.assertIn("cohere-command-a-plus-evaluation", ids)
        self.assertIn("huggingface-gpt-oss-120b-monthly-credit", ids)
        self.assertIn("dashscope-qwen37-max-new-user-credit", ids)
        hailuo = next(item for item in panel["candidates"] if item["candidate_id"] == "minimax-direct-hailuo-23")
        self.assertEqual(hailuo["lane"], "video_generation")
        self.assertEqual(hailuo["access_class"], "direct_payg")
        self.assertEqual(hailuo["open_weight_status"], "not_open_weight")
        h3 = next(item for item in panel["candidates"] if item["candidate_id"] == "minimax-direct-h3")
        self.assertTrue(h3["catalog_observed"])
        self.assertEqual(h3["endpoint"], "https://api.minimax.io/v2/video_generation")
        self.assertEqual(h3["access_class"], "direct_payg")
        minimax = next(item for item in panel["candidates"] if item["candidate_id"] == "minimax-direct-m27")
        self.assertEqual(minimax["api_model"], "MiniMax-M2.7")
        self.assertEqual(minimax["endpoint"], "https://api.minimax.io/v1/chat/completions")
        self.assertEqual(minimax["access_class"], "direct_payg")
        free = [
            item for item in panel["candidates"]
            if item["access_class"] == "zero_cost_rate_limited"
        ]
        self.assertEqual(len(free), 31)
        providers = {row["provider"] for row in panel["candidates"]}
        self.assertIn("google_ai_studio", providers)
        self.assertIn("cloudflare_workers_ai", providers)
        self.assertIn("cerebras", providers)
        self.assertIn("lightning_model_api", providers)
        self.assertNotIn("github_models", providers)
        self.assertIn("cohere", providers)
        self.assertIn("huggingface_inference_providers", providers)
        self.assertIn("alibaba_model_studio", providers)
        self.assertEqual(
            {row["provider"] for row in panel["free_compute_matrix"]},
            {
                "kaggle_notebooks",
                "lightning_ai_studios",
                "modelscope_notebook",
                "modal_starter",
                "google_colab_free",
                "huggingface_zerogpu",
                "nvidia_launchpad",
                "amazon_sagemaker_studio_lab_existing_accounts",
            },
        )
        self.assertNotIn(
            "cerebras",
            panel["selection_policy"]["additional_official_free_routes"],
        )
        self.assertTrue(
            panel["selection_policy"]["official_developer_credit_routes"]["cerebras"]["verified_payment_method_required"]
        )
        self.assertEqual(
            panel["selection_policy"]["workload_assignment"]["dynamic_exploration_only"],
            ["openrouter-dynamic-free"],
        )
        self.assertIn(
            "lightning-nemotron-3-ultra-free",
            panel["selection_policy"]["workload_assignment"]["long_context_red_team"],
        )
        self.assertEqual(
            panel["selection_policy"]["additional_official_free_routes"]["lightning_model_api"]["free_tokens_per_month"],
            30_000_000,
        )
        self.assertEqual(
            panel["combined_execution_plan"]["gpu_priority"][:3],
            ["lightning_ai_studios", "modelscope_notebook", "modal_starter"],
        )
        self.assertTrue(
            panel["combined_execution_plan"]["checkpoint_contract"]["export_before_stop_or_switch"]
        )
        self.assertNotIn(
            "github_models",
            panel["selection_policy"]["additional_official_free_routes"],
        )
        self.assertIn(
            "github_models",
            {row["provider"] for row in panel["excluded_route_observations"]},
        )
        self.assertIn(
            "fixed_model_identity_required_for_frozen_promotion",
            panel["selection_policy"]["routing_invariants"],
        )
        self.assertEqual(
            panel["openrouter_catalog_observation"]["exact_zero_cost_variants_in_panel"],
            12,
        )
        self.assertEqual(panel["openrouter_catalog_observation"]["exact_zero_cost_variant_count"], 18)
        self.assertEqual(len(panel["openrouter_catalog_observation"]["specialist_variants_not_in_chat_qualification"]), 6)
        self.assertTrue(all(item["maximum_call_cost_usd"] == 0 for item in free))
        self.assertLessEqual(panel["selection_policy"]["free_route_request_ceiling"], 50)
        self.assertTrue(all(item["competition_core_allowed"] is False for item in panel["candidates"]))

    def test_current_preflight_records_no_secret_and_no_fabricated_live_call(self) -> None:
        preflight = json.loads(PREFLIGHT.read_text(encoding="utf-8"))
        self.assertEqual(preflight["live_calls_executed"], 0)
        self.assertFalse(preflight["deepseek_direct_api_free_claim"])
        self.assertFalse(preflight["minimax_direct_api_free_claim"])
        self.assertEqual(preflight["free_candidate_count"], 31)
        self.assertEqual(preflight["free_qualification_candidate_count"], 29)
        self.assertEqual(preflight["free_panel_request_ceiling"], 47)
        self.assertLessEqual(preflight["free_panel_request_ceiling"], preflight["free_panel_daily_limit"])
        self.assertTrue(all(value is False for value in preflight["credential_environment_present"].values()))
        self.assertTrue(all(isinstance(value, bool) for value in preflight["credential_environment_present"].values()))
        runner = (ROOT / "scripts/run_v10_frontier_free_api_sprint.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('str(row["api_key_env"])', runner)
        self.assertIn("blocked_missing_free_api_credentials", runner)
        self.assertNotIn("blocked_missing_OPENROUTER_API_KEY", runner)
        self.assertIn("_frozen_promotion_ids", runner)
        self.assertIn('!= "openrouter/free"', runner)
        self.assertIn("LIGHTNING_FREE_ONLY_ACK", runner)

    def test_historical_receipts_and_current_panel_all_exclude_retired_github_models(self) -> None:
        availability = json.loads(AVAILABILITY.read_text(encoding="utf-8"))
        registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
        self.assertEqual(availability["github_models_probe"]["http_status"], 410)
        self.assertFalse(availability["github_models_probe"]["admitted"])
        self.assertEqual(
            availability["minimax_h3_observation"]["access_class"],
            "direct_payg",
        )
        self.assertFalse(
            availability["minimax_h3_observation"]["live_generation_submitted"]
        )
        github = next(
            item for item in registry["candidates"]
            if item["provider"] == "github_models"
        )
        self.assertEqual(github["catalog_probe_http_status"], 410)
        self.assertTrue(github["execution_status"].startswith("permanently_excluded"))
        current_panel = json.loads(CONFIG.read_text(encoding="utf-8"))
        self.assertNotIn(
            "github_models",
            {item["provider"] for item in current_panel["candidates"]},
        )
        retired = next(
            item for item in current_panel["excluded_route_observations"]
            if item["provider"] == "github_models"
        )
        self.assertEqual(
            retired["execution_status"],
            "retired_globally_no_executable_route",
        )
        self.assertEqual(
            set(availability["openrouter_catalog_observation"]["fixed_price_nonfree_rows_excluded"]),
            {"google/lyria-3-clip-preview", "google/lyria-3-pro-preview"},
        )
        self.assertEqual(
            availability["official_free_route_observations"]["panel_free_candidate_count"],
            27,
        )
        self.assertEqual(
            set(availability["official_free_route_observations"]["providers"]),
            {"openrouter", "groq", "nvidia_nim", "sambanova", "mistral"},
        )


if __name__ == "__main__":
    unittest.main()
