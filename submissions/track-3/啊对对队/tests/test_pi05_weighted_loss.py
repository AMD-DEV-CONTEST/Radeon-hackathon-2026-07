import unittest

import torch

from parcel_sorter.pi05_weighted_loss import (
    PI05_MODE_FLOW_LOSS_WEIGHTING_SCOPE,
    PI05_STAGE_LOSS_WEIGHTING_SCOPE,
    apply_pi05_mode_flow_loss_weights,
    apply_pi05_stage_loss_weights,
    pi05_absolute_action_weights,
    pi05_incremental_action_weights,
    pi05_residual_action_weights,
    reduce_pi05_mode_classification,
    reduce_pi05_mode_head_classification,
    reduce_weighted_pi05_losses,
)


class PI05WeightedLossTests(unittest.TestCase):
    def test_fused_mode_head_requires_one_mode_per_chunk(self) -> None:
        targets = torch.zeros(2, 3, 14)
        targets[0, :, 9:12] = torch.tensor([1.0, -1.0, -1.0])
        targets[1, :, 9:12] = torch.tensor([-1.0, 1.0, -1.0])
        logits = torch.tensor([[3.0, 0.0, -1.0], [0.0, 2.0, -1.0]])

        loss, payload = reduce_pi05_mode_head_classification(
            logits, targets, reduction="mean"
        )

        self.assertGreaterEqual(loss.item(), 0.0)
        self.assertEqual(payload["mode_head_accuracy"], 1.0)
        targets[0, 1, 9:12] = torch.tensor([-1.0, -1.0, 1.0])
        with self.assertRaisesRegex(ValueError, "constant"):
            reduce_pi05_mode_head_classification(logits, targets, reduction="mean")

    def test_mode_cross_entropy_rewards_correct_denoised_action_margin(self) -> None:
        targets = torch.zeros(1, 2, 14)
        targets[:, :, 9:12] = torch.tensor([1.0, -1.0, -1.0])
        correct = targets.clone()
        wrong = targets.clone()
        wrong[:, :, 9:12] = torch.tensor([-1.0, -1.0, 1.0])

        correct_loss, correct_payload = reduce_pi05_mode_classification(
            correct, targets, reduction="mean"
        )
        wrong_loss, wrong_payload = reduce_pi05_mode_classification(
            wrong, targets, reduction="mean"
        )

        self.assertLess(correct_loss.item(), wrong_loss.item())
        self.assertEqual(correct_payload["mode_accuracy"], 1.0)
        self.assertEqual(wrong_payload["mode_accuracy"], 0.0)
        self.assertGreater(correct_payload["mode_margin"], 0.0)

    def test_mode_weighting_preserves_scale_and_emphasizes_mode_dimensions(self) -> None:
        losses = torch.tensor([[[1.0, 3.0]]])

        loss, payload = reduce_weighted_pi05_losses(
            losses, (1.0, 3.0), reduction="mean"
        )

        self.assertAlmostEqual(loss.item(), 2.5)
        self.assertEqual(payload["weighted_loss_per_dim"], [1.0, 9.0])

    def test_mode_head_class_weights_balance_frame_frequency(self) -> None:
        targets = torch.zeros(2, 2, 14)
        targets[0, :, 9:12] = torch.tensor([1.0, -1.0, -1.0])
        targets[1, :, 9:12] = torch.tensor([-1.0, -1.0, 1.0])
        logits = torch.zeros(2, 3)

        losses, _payload = reduce_pi05_mode_head_classification(
            logits,
            targets,
            class_weights=(0.5, 1.0, 2.0),
            reduction="none",
        )

        self.assertAlmostEqual(losses[1].item() / losses[0].item(), 4.0)

    def test_residual_contract_weights_only_mode_logits(self) -> None:
        weights = pi05_residual_action_weights(4.0)

        self.assertEqual(len(weights), 14)
        self.assertEqual(weights[9:12], (4.0, 4.0, 4.0))
        self.assertEqual(sum(value != 1.0 for value in weights), 3)

    def test_absolute_contract_uses_mode_channels_nineteen_to_twenty_one(self) -> None:
        weights = pi05_absolute_action_weights(4.0)
        targets = torch.zeros(1, 2, 23)
        targets[:, :, 19:22] = torch.tensor([-1.0, 1.0, -1.0])
        logits = torch.tensor([[0.0, 2.0, -1.0]])

        loss, payload = reduce_pi05_mode_head_classification(
            logits,
            targets,
            mode_slice=slice(19, 22),
            reduction="mean",
        )

        self.assertEqual(len(weights), 23)
        self.assertEqual(weights[19:22], (4.0, 4.0, 4.0))
        self.assertGreaterEqual(loss.item(), 0.0)
        self.assertEqual(payload["mode_head_accuracy"], 1.0)

    def test_incremental_contract_uses_mode_channels_seventeen_to_nineteen(self) -> None:
        weights = pi05_incremental_action_weights(4.0)

        self.assertEqual(len(weights), 21)
        self.assertEqual(weights[17:20], (4.0, 4.0, 4.0))
        self.assertEqual(sum(value != 1.0 for value in weights), 3)

    def test_stage_weighting_uses_current_stage_channel(self) -> None:
        per_sample = torch.tensor([1.0, 1.0, 1.0])
        state = torch.full((3, 80), -1.0)
        state[0, 56] = 1.0
        state[1, 57] = 1.0
        state[2, 61] = 1.0

        weighted, payload = apply_pi05_stage_loss_weights(
            per_sample,
            state,
            (2.0, 1.5, 1.0, 0.75, 0.5, 0.25),
        )

        self.assertEqual(weighted.tolist(), [2.0, 1.5, 0.25])
        self.assertEqual(payload["stage_batch_counts"], [1, 1, 0, 0, 0, 1])
        self.assertAlmostEqual(payload["stage_unweighted_loss"], 1.0)

    def test_stage_weighting_rejects_invalid_contract(self) -> None:
        state = torch.zeros(1, 80)
        state[0, 56] = 1.0

        with self.assertRaisesRegex(ValueError, "six positive"):
            apply_pi05_stage_loss_weights(
                torch.ones(1), state, (1.0, 1.0, 1.0, 1.0, 0.0, 1.0)
            )

    def test_mode_flow_weighting_uses_target_mode_without_batch_renormalization(self) -> None:
        per_sample = torch.tensor([2.0, 2.0, 2.0])
        targets = torch.zeros(3, 2, 14)
        targets[0, :, 9:12] = torch.tensor([1.0, -1.0, -1.0])
        targets[1, :, 9:12] = torch.tensor([-1.0, 1.0, -1.0])
        targets[2, :, 9:12] = torch.tensor([-1.0, -1.0, 1.0])

        weighted, payload = apply_pi05_mode_flow_loss_weights(
            per_sample,
            targets,
            (0.75, 1.0, 1.5),
            population_normalizer=1.0,
        )

        self.assertEqual(weighted.tolist(), [1.5, 2.0, 3.0])
        self.assertEqual(payload["mode_flow_batch_counts"], [1, 1, 1])
        self.assertAlmostEqual(payload["mode_flow_input_loss"], 2.0)
        self.assertAlmostEqual(
            payload["mode_flow_weighted_loss"], 13.0 / 6.0, places=6
        )

    def test_mode_flow_weighting_rejects_mode_changes_inside_a_chunk(self) -> None:
        targets = torch.zeros(1, 2, 14)
        targets[0, 0, 9:12] = torch.tensor([1.0, -1.0, -1.0])
        targets[0, 1, 9:12] = torch.tensor([-1.0, 1.0, -1.0])

        with self.assertRaisesRegex(ValueError, "constant"):
            apply_pi05_mode_flow_loss_weights(
                torch.ones(1),
                targets,
                (0.75, 1.0, 1.5),
                population_normalizer=1.0,
            )

    def test_b3_sw_stage_weights_preserve_dataset_expected_loss_scale(self) -> None:
        counts = (780, 809, 900, 2296, 786, 300)
        weights = (
            2.035714286,
            2.035714286,
            1.221428571,
            0.407142857,
            0.610714286,
            0.407142857,
        )

        expected_scale = sum(
            count * weight for count, weight in zip(counts, weights, strict=True)
        ) / sum(counts)

        self.assertAlmostEqual(expected_scale, 1.0, places=8)
        self.assertEqual(
            PI05_STAGE_LOSS_WEIGHTING_SCOPE,
            "flow_loss_only_before_auxiliary_losses_v1",
        )
        self.assertEqual(
            PI05_MODE_FLOW_LOSS_WEIGHTING_SCOPE,
            "target_grasp_mode_flow_loss_only_before_auxiliary_losses_v1",
        )


if __name__ == "__main__":
    unittest.main()
