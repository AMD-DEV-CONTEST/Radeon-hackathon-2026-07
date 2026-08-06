from __future__ import annotations

import json
from pathlib import Path
import unittest

from prooflaunch_remix.gtm_breakout_mechanism_routing import compile_breakout_mechanism_routing, verify_breakout_mechanism_routing
from scripts.compile_gtm_breakout_mechanism_routing import LIFECYCLE_BLUEPRINTS, PLATFORM_BLUEPRINTS, VERTICAL_BLUEPRINTS


class BreakoutMechanismRoutingTests(unittest.TestCase):
    def test_full_routing_coverage_and_bounds(self):
        sampling = json.loads(Path("evidence/v10/gtm-global-organic-signal-sampling-standard-v1.json").read_text(encoding="utf-8"))
        distillation = json.loads(Path("evidence/v10/gtm-breakout-mechanism-distillation-v1.json").read_text(encoding="utf-8"))
        payload = compile_breakout_mechanism_routing(sampling, distillation, vertical_blueprints=VERTICAL_BLUEPRINTS, lifecycle_blueprints=LIFECYCLE_BLUEPRINTS, platform_blueprints=PLATFORM_BLUEPRINTS, compiled_at="2026-08-04T00:00:00-04:00")
        verify_breakout_mechanism_routing(payload)
        self.assertEqual(payload["segment_market_route_count"], 140)
        self.assertEqual(payload["platform_market_route_count"], 168)
        self.assertTrue(all(len(route["lifecycle_blueprint_routes"]) == 4 for route in payload["segment_market_routes"]))
        self.assertTrue(all(route["source_copy_reuse_allowed"] is False for route in payload["platform_market_routes"]))


if __name__ == "__main__":
    unittest.main()
