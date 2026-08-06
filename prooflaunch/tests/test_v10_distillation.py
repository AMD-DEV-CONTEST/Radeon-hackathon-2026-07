from __future__ import annotations

import unittest

from prooflaunch_remix.v10_contracts import V10ContractError
from prooflaunch_remix.v10_distillation import (
    DistillationAdmissionStatus,
    DistillationEpisodeV1,
    DistillationSignal,
    DistillationSignalKind,
    FrozenModelRef,
    OutputRightsStatus,
    TeacherStudentDiagnostics,
)


SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
SHA_E = "e" * 64


def model(model_id: str) -> FrozenModelRef:
    return FrozenModelRef(
        provider="frozen-provider",
        model_id=model_id,
        revision="1" * 40,
        revision_verified=True,
        license_id="Apache-2.0",
    )


def diagnostics(**overrides: float) -> TeacherStudentDiagnostics:
    values = {
        "top_k_support_overlap": 0.70,
        "token_advantage": 0.10,
        "teacher_information_gain": 0.20,
        "privileged_context_divergence": 0.10,
        "calibration_error": 0.02,
        "student_overconfidence_rate": 0.01,
        "high_entropy_fork_retention": 0.99,
        "reconsideration_retention": 0.99,
        "verification_retention": 0.99,
        "backtracking_retention": 0.99,
        "style_token_kl": 0.04,
    }
    values.update(overrides)
    return TeacherStudentDiagnostics(**values)


def episode(
    *,
    rights: OutputRightsStatus = OutputRightsStatus.APPROVED,
    diagnostic: TeacherStudentDiagnostics | None = None,
    hidden_reasoning_persisted: bool = False,
    competition_core_eligible: bool = False,
) -> DistillationEpisodeV1:
    return DistillationEpisodeV1(
        episode_id="distill-0001",
        teacher=model("teacher"),
        student=model("student"),
        privileged_context_sha256=SHA_A,
        deployment_context_sha256=SHA_B,
        teacher_response_sha256=SHA_C,
        source_todo_sha256=SHA_D,
        signals=(
            DistillationSignal(
                kind=DistillationSignalKind.TOKEN,
                artifact_sha256=SHA_E,
                source_locator="private/distill/token-signal.safetensors",
                sample_count=64,
                privileged_only=True,
            ),
        ),
        diagnostics=diagnostic or diagnostics(),
        output_rights_status=rights,
        created_at="2026-07-30T09:45:00Z",
        hidden_reasoning_persisted=hidden_reasoning_persisted,
        competition_core_eligible=competition_core_eligible,
    )


class V10DistillationEpisodeTests(unittest.TestCase):
    def test_complete_source_bound_episode_is_admitted(self) -> None:
        decision = episode().evaluate()
        self.assertTrue(decision.admitted)
        self.assertEqual(decision.status, DistillationAdmissionStatus.ADMIT)
        self.assertEqual(decision.failures, ())
        self.assertEqual(len(decision.episode_digest), 64)

    def test_current_tokenfactory_rights_status_is_fail_closed(self) -> None:
        decision = episode(
            rights=OutputRightsStatus.REVIEW_REQUIRED,
        ).evaluate()
        self.assertFalse(decision.admitted)
        self.assertIn(
            "output rights are rights_review_required",
            decision.failures,
        )

    def test_compatibility_information_and_correction_gates_are_independent(
        self,
    ) -> None:
        decision = episode(
            diagnostic=diagnostics(
                top_k_support_overlap=0.05,
                token_advantage=-0.10,
                teacher_information_gain=0.0,
                privileged_context_divergence=0.60,
                high_entropy_fork_retention=0.80,
                reconsideration_retention=0.79,
                verification_retention=0.78,
                backtracking_retention=0.77,
                style_token_kl=0.30,
            )
        ).evaluate()
        self.assertFalse(decision.admitted)
        self.assertIn(
            "teacher/student top-k support overlap is too low",
            decision.failures,
        )
        self.assertIn(
            "teacher information gain is below threshold",
            decision.failures,
        )
        self.assertIn(
            "teacher token advantage is below threshold",
            decision.failures,
        )
        self.assertIn(
            "privileged/deployment context divergence exceeds threshold",
            decision.failures,
        )
        self.assertIn("high-entropy fork retention regressed", decision.failures)
        self.assertIn("reconsideration retention regressed", decision.failures)
        self.assertIn("verification retention regressed", decision.failures)
        self.assertIn("backtracking retention regressed", decision.failures)
        self.assertIn(
            "style-token KL exceeds the clipping gate",
            decision.failures,
        )

    def test_hidden_reasoning_and_competition_core_substitution_are_denied(
        self,
    ) -> None:
        decision = episode(
            hidden_reasoning_persisted=True,
            competition_core_eligible=True,
        ).evaluate()
        self.assertFalse(decision.admitted)
        self.assertIn("hidden reasoning must not be persisted", decision.failures)
        self.assertIn(
            "external distillation episode cannot be competition-core evidence",
            decision.failures,
        )

    def test_privileged_signal_requires_distinct_deployment_context(self) -> None:
        with self.assertRaises(V10ContractError):
            DistillationEpisodeV1(
                episode_id="invalid",
                teacher=model("teacher"),
                student=model("student"),
                privileged_context_sha256=SHA_A,
                deployment_context_sha256=SHA_A,
                teacher_response_sha256=SHA_C,
                source_todo_sha256=SHA_D,
                signals=(
                    DistillationSignal(
                        kind=DistillationSignalKind.FEATURE,
                        artifact_sha256=SHA_E,
                        source_locator="private/distill/feature.safetensors",
                        sample_count=1,
                        privileged_only=True,
                    ),
                ),
                diagnostics=diagnostics(),
                output_rights_status=OutputRightsStatus.APPROVED,
                created_at="2026-07-30T09:45:00Z",
            )

    def test_signal_kinds_cover_all_declared_distillation_axes(self) -> None:
        self.assertEqual(
            {kind.value for kind in DistillationSignalKind},
            {
                "token",
                "feature",
                "reward",
                "trajectory",
                "region",
                "workflow",
                "uncertainty",
            },
        )


if __name__ == "__main__":
    unittest.main()
