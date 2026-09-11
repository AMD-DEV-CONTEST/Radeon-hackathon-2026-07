import math
import unittest

from parcel_sorter.mobile_grasp_routing import (
    radial_side_grasp_quaternion,
    route_mobile_grasp,
    top_down_grasp_quaternion,
    top_suction_active_cup_indices,
)
from parcel_sorter.suction import rotate_vector


class MobileGraspRoutingTests(unittest.TestCase):
    def test_top_down_orientation_preserves_normal_and_tracks_yaw(self) -> None:
        quaternion = top_down_grasp_quaternion(math.pi / 2.0)

        tool_normal = rotate_vector(quaternion, (0.0, 0.0, 1.0))
        footprint_x = rotate_vector(quaternion, (1.0, 0.0, 0.0))
        self.assertAlmostEqual(tool_normal[2], -1.0)
        self.assertAlmostEqual(footprint_x[1], 1.0)

    def test_top_suction_uses_balanced_cup_subsets(self) -> None:
        self.assertEqual(top_suction_active_cup_indices(1), (0,))
        self.assertEqual(top_suction_active_cup_indices(2), (1, 2))
        self.assertEqual(top_suction_active_cup_indices(3), (0, 1, 2))

    def test_side_orientation_points_radially_with_vertical_footprint(self) -> None:
        quaternion = radial_side_grasp_quaternion()

        tool_normal = rotate_vector(quaternion, (0.0, 0.0, 1.0))
        footprint_y = rotate_vector(quaternion, (0.0, 1.0, 0.0))
        self.assertAlmostEqual(tool_normal[1], 1.0)
        self.assertAlmostEqual(footprint_y[2], -1.0)

    def test_flat_and_small_boxes_use_top_suction_with_area_aware_cups(self) -> None:
        micro = route_mobile_grasp(
            shape="box",
            orientation_mode="yaw",
            size_m=(0.064, 0.038, 0.029),
            mass_kg=0.08,
            handling_class="parallel_jaw",
        )
        mailer = route_mobile_grasp(
            shape="box",
            orientation_mode="yaw",
            size_m=(0.24, 0.07, 0.02),
            mass_kg=0.20,
            handling_class="suction_required",
        )
        self.assertEqual((micro.mode, micro.minimum_sealed_cups), ("top_suction", 1))
        self.assertEqual((mailer.mode, mailer.minimum_sealed_cups), ("top_suction", 1))

    def test_top_cup_count_respects_physical_footprint(self) -> None:
        narrow = route_mobile_grasp(
            shape="box",
            orientation_mode="yaw",
            size_m=(0.080, 0.0475, 0.04),
            mass_kg=0.2,
            handling_class="parallel_jaw",
        )
        wide_and_heavy = route_mobile_grasp(
            shape="box",
            orientation_mode="yaw",
            size_m=(0.12, 0.08, 0.04),
            mass_kg=1.5,
            handling_class="parallel_jaw",
        )
        self.assertEqual(narrow.minimum_sealed_cups, 1)
        self.assertEqual(wide_and_heavy.minimum_sealed_cups, 3)

    def test_insufficient_top_area_escalates_to_cradle(self) -> None:
        route = route_mobile_grasp(
            shape="box",
            orientation_mode="yaw",
            size_m=(0.080, 0.0475, 0.04),
            mass_kg=1.0,
            handling_class="parallel_jaw",
        )
        self.assertEqual(route.mode, "cooperative_cradle")
        self.assertTrue(route.cooperative_cradle)

    def test_upright_cylinder_uses_side_suction(self) -> None:
        route = route_mobile_grasp(
            shape="cylinder",
            orientation_mode="upright",
            size_m=(0.06, 0.06, 0.14),
            mass_kg=0.6,
            handling_class="parallel_jaw",
        )
        self.assertEqual(route.mode, "side_suction")
        self.assertFalse(route.cooperative_cradle)
        self.assertEqual(route.minimum_sealed_cups, 2)

    def test_horizontal_cylinder_always_uses_cradle(self) -> None:
        route = route_mobile_grasp(
            shape="cylinder",
            orientation_mode="horizontal",
            size_m=(0.15, 0.04, 0.04),
            mass_kg=0.10,
            handling_class="parallel_jaw",
        )
        self.assertEqual(route.mode, "cooperative_cradle")
        self.assertTrue(route.cooperative_cradle)

    def test_heavy_or_oversized_box_uses_cradle(self) -> None:
        heavy = route_mobile_grasp(
            shape="box",
            orientation_mode="yaw",
            size_m=(0.36, 0.24, 0.12),
            mass_kg=3.63,
            handling_class="suction_required",
        )
        oversized = route_mobile_grasp(
            shape="box",
            orientation_mode="yaw",
            size_m=(0.62, 0.30, 0.08),
            mass_kg=1.0,
            handling_class="suction_required",
        )
        self.assertTrue(heavy.cooperative_cradle)
        self.assertTrue(oversized.cooperative_cradle)


if __name__ == "__main__":
    unittest.main()
