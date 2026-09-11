import math
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from parcel_sorter.capabilities import runtime_supported_handling_classes
from parcel_sorter.genesis_env import (
    build_tri_suction_mjcf,
    combine_rigid_body_with_cylinders_inertia,
)
from parcel_sorter.suction import (
    compliant_suction_wrench,
    create_attachment,
    inertia_scaled_rotational_gains,
    tri_cup_offsets,
)


class TriSuctionAssetTests(unittest.TestCase):
    def test_generates_three_physical_cups_and_combines_hand_inertia(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "assets").mkdir()
            source = root / "panda.xml"
            source.write_text(
                """<mujoco><compiler meshdir="assets"/><worldbody><body name="hand">
                <inertial mass="0.73" pos="-0.01 0 0.03" diaginertia="0.001 0.0025 0.0017"/>
                </body></worldbody></mujoco>""",
                encoding="utf-8",
            )
            output = root / "generated" / "panda_tri_suction.xml"
            build_tri_suction_mjcf(
                source,
                output,
                cup_radius_m=0.012,
                footprint_radius_m=0.025,
                cup_length_m=0.012,
                tip_offset_m=0.100,
                density_kg_m3=1100.0,
            )
            hand = ET.parse(output).getroot().find(".//body[@name='hand']")
            assert hand is not None
            collision = [
                geom for geom in hand.findall("geom")
                if geom.attrib["name"].endswith("_collision")
            ]
            self.assertEqual(len(collision), 3)
            self.assertTrue(all(geom.attrib["type"] == "cylinder" for geom in collision))
            inertial = hand.find("inertial")
            assert inertial is not None
            self.assertGreater(float(inertial.attrib["mass"]), 0.73)
            self.assertIn("fullinertia", inertial.attrib)

    def test_three_cup_footprint_is_equilateral(self) -> None:
        offsets = tri_cup_offsets(0.025)
        distances = sorted(
            math.dist(offsets[first], offsets[second])
            for first in range(3)
            for second in range(first + 1, 3)
        )
        self.assertAlmostEqual(distances[0], distances[1])
        self.assertAlmostEqual(distances[1], distances[2])

    def test_combined_cylinder_inertia_is_physical(self) -> None:
        mass, _, inertia = combine_rigid_body_with_cylinders_inertia(
            0.73,
            (-0.01, 0.0, 0.03),
            (0.001, 0.0025, 0.0017, 0.0, 0.0, 0.0),
            1100.0,
            0.012,
            0.012,
            tuple((x, y, 0.106) for x, y, _ in tri_cup_offsets(0.025)),
        )
        self.assertGreater(mass, 0.73)
        self.assertTrue(all(math.isfinite(value) for value in inertia))


class SuctionAttachmentTests(unittest.TestCase):
    def test_rotational_gains_scale_with_payload_inertia(self) -> None:
        light_stiffness, light_damping = inertia_scaled_rotational_gains(1.5e-5)
        heavy_stiffness, heavy_damping = inertia_scaled_rotational_gains(0.02)

        self.assertAlmostEqual(light_stiffness, 0.006)
        self.assertAlmostEqual(light_damping, 0.0006)
        self.assertEqual(heavy_stiffness, 5.0)
        self.assertAlmostEqual(heavy_damping, 2.0 * math.sqrt(0.1))

    def test_bounded_spring_wrench_and_break_gate(self) -> None:
        attachment = create_attachment(
            (0.0, 0.0, 0.20),
            (1.0, 0.0, 0.0, 0.0),
            (0.0, 0.0, 0.10),
            (1.0, 0.0, 0.0, 0.0),
            sealed_cup_count=3,
        )
        wrench = compliant_suction_wrench(
            attachment,
            (0.0, 0.0, 0.25),
            (1.0, 0.0, 0.0, 0.0),
            (0.0, 0.0, 0.10),
            (1.0, 0.0, 0.0, 0.0),
            (0.0, 0.0, 0.0),
            (0.0, 0.0, 0.0),
            translational_stiffness_n_m=1800.0,
            translational_damping_n_s_m=45.0,
            rotational_stiffness_nm_rad=4.0,
            rotational_damping_nm_s_rad=0.12,
            max_force_n=30.0,
            max_torque_nm=0.75,
            break_distance_m=0.10,
            break_angle_rad=0.70,
        )
        self.assertFalse(wrench.broken)
        self.assertLessEqual(math.sqrt(sum(value * value for value in wrench.force_world_n)), 30.0)
        broken = compliant_suction_wrench(
            attachment,
            (0.0, 0.0, 0.50),
            (1.0, 0.0, 0.0, 0.0),
            (0.0, 0.0, 0.10),
            (1.0, 0.0, 0.0, 0.0),
            (0.0, 0.0, 0.0),
            (0.0, 0.0, 0.0),
            translational_stiffness_n_m=1800.0,
            translational_damping_n_s_m=45.0,
            rotational_stiffness_nm_rad=4.0,
            rotational_damping_nm_s_rad=0.12,
            max_force_n=30.0,
            max_torque_nm=0.75,
            break_distance_m=0.10,
            break_angle_rad=0.70,
        )
        self.assertTrue(broken.broken)

    def test_single_round_cup_can_twist_about_its_surface_normal(self) -> None:
        attachment = create_attachment(
            (0.0, 0.0, 0.20),
            (1.0, 0.0, 0.0, 0.0),
            (0.0, 0.0, 0.10),
            (1.0, 0.0, 0.0, 0.0),
            sealed_cup_count=1,
        )
        half_turn = math.sqrt(0.5)
        wrench = compliant_suction_wrench(
            attachment,
            (0.0, 0.0, 0.20),
            (1.0, 0.0, 0.0, 0.0),
            (0.0, 0.0, 0.10),
            (half_turn, 0.0, 0.0, half_turn),
            (0.0, 0.0, 0.0),
            (0.0, 0.0, 0.0),
            translational_stiffness_n_m=800.0,
            translational_damping_n_s_m=18.0,
            rotational_stiffness_nm_rad=5.0,
            rotational_damping_nm_s_rad=0.25,
            max_force_n=30.0,
            max_torque_nm=0.75,
            break_distance_m=0.08,
            break_angle_rad=0.65,
            free_twist_axis_world=(0.0, 0.0, 1.0),
        )
        self.assertFalse(wrench.broken)
        self.assertAlmostEqual(wrench.orientation_error_rad, 0.0, places=6)
        self.assertEqual(wrench.torque_world_nm, (0.0, 0.0, 0.0))

    def test_suction_capability_requires_the_physical_variant(self) -> None:
        self.assertEqual(
            runtime_supported_handling_classes(tri_suction_enabled=False),
            {"parallel_jaw"},
        )
        self.assertEqual(
            runtime_supported_handling_classes(tri_suction_enabled=True),
            {"parallel_jaw", "suction_required"},
        )


if __name__ == "__main__":
    unittest.main()
