from __future__ import annotations

import unittest

from prooflaunch_remix.v10_agentomnia import Capability
from prooflaunch_remix.v10_frontier_landscape import (
    ProductLane,
    default_frontier_landscape,
)


class FrontierLandscapeTests(unittest.TestCase):
    def test_eight_lanes_each_have_ten_non_ranked_product_references(self) -> None:
        landscape = default_frontier_landscape()
        self.assertEqual(len(landscape.lanes), 8)
        self.assertEqual({item.lane for item in landscape.lanes}, set(ProductLane))
        self.assertTrue(all(len(item.products) == 10 for item in landscape.lanes))
        self.assertEqual(
            landscape.ranking_claim,
            "comparison_set_not_a_global_rank_claim",
        )

    def test_product_outputs_are_explicitly_excluded_from_training_assets(self) -> None:
        landscape = default_frontier_landscape()
        self.assertIn("not corpus assets", landscape.training_policy)
        self.assertIn("licensed", landscape.training_policy)

    def test_every_lane_includes_planning_tool_and_reliability_capabilities(self) -> None:
        landscape = default_frontier_landscape()
        required = {
            Capability.PLANNING_DECISION,
            Capability.TOOL_USE,
            Capability.RELIABILITY_SAFETY,
        }
        self.assertTrue(
            all(required.issubset(item.required_capabilities) for item in landscape.lanes)
        )

    def test_landscape_is_content_addressed(self) -> None:
        landscape = default_frontier_landscape()
        self.assertEqual(len(landscape.digest), 64)
        self.assertEqual(landscape.digest, default_frontier_landscape().digest)


if __name__ == "__main__":
    unittest.main()
