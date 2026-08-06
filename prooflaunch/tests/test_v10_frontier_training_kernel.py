from __future__ import annotations

import unittest

from prooflaunch_remix.v10_frontier_landscape import ProductLane
from prooflaunch_remix.v10_frontier_training_kernel import (
    KernelLayer,
    LifecycleStage,
    default_frontier_training_kernel,
)


class FrontierTrainingKernelTests(unittest.TestCase):
    def test_research_covers_every_kernel_layer_and_product_lane(self) -> None:
        kernel = default_frontier_training_kernel()
        self.assertEqual({item.layer for item in kernel.mechanisms}, set(KernelLayer))
        self.assertEqual(
            set().union(*(item.applies_to for item in kernel.mechanisms)),
            set(ProductLane),
        )
        self.assertTrue(all(item.falsifier for item in kernel.mechanisms))
        self.assertTrue(
            all(item.evidence_boundary == "method_reference_not_reproduction" for item in kernel.mechanisms)
        )

    def test_all_eight_lanes_cover_the_same_full_lifecycle(self) -> None:
        kernel = default_frontier_training_kernel()
        self.assertEqual(len(kernel.lane_objectives), 8)
        self.assertTrue(
            all(item.lifecycle == tuple(LifecycleStage) for item in kernel.lane_objectives)
        )
        self.assertTrue(all(item.mechanical_gates for item in kernel.lane_objectives))
        self.assertTrue(all(item.human_gates for item in kernel.lane_objectives))

    def test_durable_runtime_is_checkpointed_idempotent_and_fail_closed(self) -> None:
        durable = default_frontier_training_kernel().durable_execution
        self.assertTrue(durable.checkpoint_after_every_state_change)
        self.assertTrue(durable.activity_idempotency_keys)
        self.assertTrue(durable.exact_resume_without_success_replay)
        self.assertTrue(durable.irreversible_action_requires_human)
        self.assertIn("rights_failure", durable.no_retry_classes)
        self.assertLessEqual(durable.maximum_agent_steps, 64)

    def test_named_failure_modes_are_specific_and_complete_enough_for_evals(self) -> None:
        failure_modes = default_frontier_training_kernel().failure_modes
        self.assertGreaterEqual(len(failure_modes), 10)
        self.assertIn("duplicate_non_idempotent_side_effect", failure_modes)
        self.assertIn("observational_metric_presented_as_causal_lift", failure_modes)
        self.assertIn("unlicensed_or_opted_out_training_source", failure_modes)

    def test_kernel_is_deterministic_and_content_addressed(self) -> None:
        first = default_frontier_training_kernel()
        second = default_frontier_training_kernel()
        self.assertEqual(first.digest, second.digest)
        self.assertEqual(len(first.digest), 64)
        self.assertEqual(first.to_dict(), second.to_dict())


if __name__ == "__main__":
    unittest.main()
