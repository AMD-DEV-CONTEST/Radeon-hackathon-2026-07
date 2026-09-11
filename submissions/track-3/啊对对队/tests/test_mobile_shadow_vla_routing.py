import importlib.util
from pathlib import Path
import unittest

from scripts import collect_mobile_suction_dataset_rocm as collector


ROOT = Path(__file__).resolve().parents[1]
EVALUATOR_SPEC = importlib.util.spec_from_file_location(
    "evaluate_mobile_suction_lift_rocm",
    ROOT / "scripts" / "evaluate_mobile_suction_lift_rocm.py",
)
assert EVALUATOR_SPEC is not None and EVALUATOR_SPEC.loader is not None
EVALUATOR = importlib.util.module_from_spec(EVALUATOR_SPEC)
EVALUATOR_SPEC.loader.exec_module(EVALUATOR)


class MobileShadowVLARoutingTests(unittest.TestCase):
    def test_shadow_is_allowed_for_vla_grasp_mode_routing(self) -> None:
        self.assertIn("shadow", EVALUATOR.PI05_POLICY_MODES | {"shadow"})
        self.assertIn("shadow", collector.PI05_VLA_ROUTING_POLICY_MODES)

    def test_required_mode_mismatch_has_dedicated_failure_stage(self) -> None:
        self.assertEqual(
            EVALUATOR.grasp_mode_route_failure_stage(required=True, matched=False),
            "grasp_mode_route_mismatch_before_actuation",
        )
        self.assertIsNone(
            EVALUATOR.grasp_mode_route_failure_stage(required=True, matched=True)
        )
        self.assertIsNone(
            EVALUATOR.grasp_mode_route_failure_stage(required=False, matched=False)
        )

    def test_collection_prioritizes_route_mismatch_over_scene_stability(self) -> None:
        summary = {
            "success": False,
            "scene_stable": False,
            "vla_grasp_mode_selection": {
                "required": True,
                "routes_execution": True,
                "matched": False,
            },
        }
        self.assertEqual(
            collector._collection_failure_stage(0, summary),
            "grasp_mode_route_mismatch_before_actuation",
        )
        explicit_summary = {
            "success": False,
            "scene_stable": False,
            "failure_stage": "grasp_mode_route_mismatch_before_actuation",
        }
        self.assertEqual(
            collector._collection_failure_stage(0, explicit_summary),
            "grasp_mode_route_mismatch_before_actuation",
        )

    def test_non_required_mismatch_keeps_physical_failure_classification(self) -> None:
        summary = {
            "success": False,
            "scene_stable": False,
            "vla_grasp_mode_selection": {
                "required": False,
                "routes_execution": True,
                "matched": False,
            },
        }
        self.assertEqual(
            collector._collection_failure_stage(0, summary),
            "scene_stability_failure",
        )


if __name__ == "__main__":
    unittest.main()
