from __future__ import annotations

import unittest

from prooflaunch_remix.audit import FourGateReleaseAuditor
from prooflaunch_remix.contracts import CampaignRequest, CampaignState, CreativeAsset
from prooflaunch_remix.model_registry import ModelRoutingError, RadeonModelRouter
from prooflaunch_remix.visual_semantics import SemanticScore


class ModelRouterTests(unittest.TestCase):
    def test_required_multimodal_roles_are_sequential_and_local(self) -> None:
        report = RadeonModelRouter().report(
            available_vram_gb=24,
            roles=("affect_critic", "image_generation", "image_text_scoring"),
        )
        self.assertEqual(len(report["phases"]), 3)
        self.assertEqual(report["co_resident_models"], 1)
        self.assertTrue(report["local_only"])
        self.assertFalse(report["closed_online_api_on_core_path"])
        self.assertTrue(all(phase["unload_after"] for phase in report["phases"]))

    def test_low_vram_fails_instead_of_silently_routing_online(self) -> None:
        with self.assertRaises(ModelRoutingError):
            RadeonModelRouter().plan(
                available_vram_gb=4,
                required_roles=("image_generation",),
            )

    def test_candidate_model_cannot_enter_required_plan_by_default(self) -> None:
        with self.assertRaises(ModelRoutingError):
            RadeonModelRouter().plan(
                available_vram_gb=24,
                required_roles=("open_set_detection",),
            )


class SemanticGateTests(unittest.TestCase):
    class FakeScorer:
        def __init__(self, passed: bool) -> None:
            self.passed = passed

        def score(self, *, image_path: str, product_name: str) -> SemanticScore:
            del image_path, product_name
            return SemanticScore(
                passed=self.passed,
                model_ref="fake/local-scorer",
                positive_probability=0.8 if self.passed else 0.2,
                strongest_negative_probability=0.1 if self.passed else 0.6,
                margin=0.7 if self.passed else -0.4,
                labels=("positive", "negative"),
                probabilities=(0.8, 0.2) if self.passed else (0.2, 0.8),
                limitations=("test double",),
            )

    @staticmethod
    def state() -> CampaignState:
        return CampaignState(
            run_id="semantic-gate",
            request=CampaignRequest(
                product_name="Aster Arc",
                product_image="product.png",
                specification_text="Documented claim.",
                market="Japan",
                platform="TikTok",
                goal="launch",
            ),
            output_dir=".",
            assets=[
                CreativeAsset(
                    id="AST-001",
                    path="creative.png",
                    aspect_ratio="9:16",
                    seed=42,
                    model_ref="generator",
                )
            ],
        )

    def test_failed_semantic_score_becomes_release_finding(self) -> None:
        auditor = FourGateReleaseAuditor(semantic_scorer=self.FakeScorer(False))
        state = self.state()
        findings = auditor._semantic_gate(state, state.assets[0])
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].category, "visual_semantics")
        self.assertFalse(state.assets[0].metadata["semantic_score"]["passed"])

    def test_passing_semantic_score_is_available_to_auditor(self) -> None:
        auditor = FourGateReleaseAuditor(semantic_scorer=self.FakeScorer(True))
        state = self.state()
        findings = auditor._semantic_gate(state, state.assets[0])
        self.assertEqual(findings, [])
        self.assertTrue(state.assets[0].metadata["semantic_score"]["passed"])


if __name__ == "__main__":
    unittest.main()
