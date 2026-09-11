from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from parcel_sorter.mobile_bimanual import (
    ARM_JOINT_NAMES,
    BASE_JOINT_NAMES,
    END_EFFECTOR_LINK_NAMES,
    FINGER_JOINT_NAMES,
    MOBILE_TRI_SUCTION_TIP_OFFSET_M,
    PlanarObstacle,
    assign_bimanual_roles,
    build_mobile_bimanual_mjcf,
    joint_dof_indices,
    planar_base_command,
    plan_detour_waypoints,
)
from parcel_sorter.parcel_routing import classify_and_route


class MobileBimanualTests(unittest.TestCase):
    def test_declares_disjoint_dual_arm_control_contract(self) -> None:
        self.assertEqual(len(ARM_JOINT_NAMES["left"]), 7)
        self.assertEqual(len(ARM_JOINT_NAMES["right"]), 7)
        self.assertEqual(len(FINGER_JOINT_NAMES["left"]), 2)
        self.assertEqual(len(FINGER_JOINT_NAMES["right"]), 2)
        self.assertEqual(set(ARM_JOINT_NAMES["left"]) & set(ARM_JOINT_NAMES["right"]), set())
        self.assertEqual(END_EFFECTOR_LINK_NAMES["left"], "panda0_gripper")
        self.assertEqual(END_EFFECTOR_LINK_NAMES["right"], "panda1_gripper")

    def test_named_joint_resolution_rejects_duplicate_dofs(self) -> None:
        class Joint:
            def __init__(self, index: int) -> None:
                self.dofs_idx_local = (index,)

        class Robot:
            def __init__(self, mapping: dict[str, int]) -> None:
                self.mapping = mapping

            def get_joint(self, name: str) -> Joint:
                return Joint(self.mapping[name])

        robot = Robot({"a": 3, "b": 7, "duplicate": 3})
        self.assertEqual(joint_dof_indices(robot, ("a", "b")), (3, 7))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            joint_dof_indices(robot, ("a", "duplicate"))

    def test_planar_controller_is_bounded_and_stops_at_goal(self) -> None:
        command = planar_base_command((0.0, 0.0, 0.0), (1.0, 1.0))
        self.assertLessEqual((command.velocity_x_m_s**2 + command.velocity_y_m_s**2) ** 0.5, 0.5)
        self.assertFalse(command.reached)
        self.assertTrue(planar_base_command((1.0, 1.0, 0.0), (1.0, 1.0)).reached)

    def test_large_or_heavy_parcels_receive_two_arms(self) -> None:
        assignment = assign_bimanual_roles(
            parcel_lateral_y_m=0.1,
            parcel_longest_dimension_m=0.50,
            parcel_mass_kg=1.0,
        )
        self.assertEqual(assignment.mode, "cooperative_carry")
        self.assertEqual({assignment.primary_arm, assignment.support_arm}, {"left", "right"})

    def test_routes_geometry_and_fragile_profiles(self) -> None:
        tube = classify_and_route(
            profile_id="mailing_tube",
            shape="cylinder",
            handling_class="parallel_jaw",
            dimensions_m=(0.25, 0.05, 0.05),
            mass_kg=0.4,
        )
        fragile = classify_and_route(
            profile_id="electronics_box",
            shape="box",
            handling_class="parallel_jaw",
            dimensions_m=(0.2, 0.1, 0.08),
            mass_kg=0.7,
        )
        self.assertEqual(tube.destination, "tube_rack")
        self.assertEqual(fragile.destination, "fragile_bin")

    def test_navigation_detours_around_inflated_obstacle(self) -> None:
        route = plan_detour_waypoints(
            (0.0, 0.0),
            (1.2, 0.0),
            (PlanarObstacle((0.6, 0.0), (0.12, 0.25)),),
            clearance_m=0.20,
        )
        self.assertEqual(route[-1], (1.2, 0.0))
        self.assertEqual(len(route), 3)
        self.assertGreater(abs(route[0][1]), 0.25)

    def test_generates_three_dof_wheeled_bi_franka_asset(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assets = root / "assets"
            assets.mkdir()
            for name in ("basic_scene.xml", "assets.xml", "gripper_assets.xml", "actuator0.xml", "actuator1.xml"):
                (assets / name).write_text("<mujoco/>", encoding="utf-8")
            source = root / "bi-franka.xml"
            source.write_text(
                """<mujoco><include file="assets/basic_scene.xml"/><include file="assets/assets.xml"/>
                <include file="assets/gripper_assets.xml"/><compiler meshdir=""/><worldbody>
                <body name="torso"><body name="leftarm"/><body name="rightarm"/></body></worldbody>
                <include file="assets/actuator0.xml"/><include file="assets/actuator1.xml"/></mujoco>""",
                encoding="utf-8",
            )
            output = root / "generated" / "mobile.xml"
            build_mobile_bimanual_mjcf(source, output)
            model = ET.parse(output).getroot()
            joints = {joint.attrib["name"] for joint in model.findall(".//joint")}
            geoms = {geom.attrib.get("name") for geom in model.findall(".//geom")}
            self.assertTrue(set(BASE_JOINT_NAMES).issubset(joints))
            self.assertIn("mobile_chassis_collision", geoms)
            self.assertEqual(len([name for name in geoms if name and name.startswith("mobile_wheel_")]), 4)

    def test_generates_hybrid_tri_suction_and_v_cradle_chain_assets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assets = root / "assets"
            assets.mkdir()
            for name in ("basic_scene.xml", "assets.xml", "gripper_assets.xml", "actuator0.xml", "actuator1.xml"):
                (assets / name).write_text("<mujoco/>", encoding="utf-8")
            (assets / "chain0.xml").write_text(
                '<mujocoinclude><body name="panda0_gripper">'
                '<geom name="stock_hand_collision" class="panda_col"/>'
                '<body name="panda0_leftfinger">'
                '<geom name="stock_finger_visual" class="panda_viz"/>'
                '<geom name="stock_finger_collision" type="box"/>'
                '</body></body></mujocoinclude>',
                encoding="utf-8",
            )
            (assets / "chain1.xml").write_text(
                '<mujocoinclude><body name="panda1_gripper"/></mujocoinclude>',
                encoding="utf-8",
            )
            source = root / "bi-franka.xml"
            source.write_text(
                """<mujoco><include file="assets/basic_scene.xml"/><compiler meshdir=""/>
                <worldbody><body name="torso"><body name="leftarm"><include file="assets/chain0.xml"/></body>
                <body name="rightarm"><include file="assets/chain1.xml"/></body></body></worldbody>
                <include file="assets/actuator0.xml"/><include file="assets/actuator1.xml"/></mujoco>""",
                encoding="utf-8",
            )
            output = root / "generated" / "mobile.xml"
            build_mobile_bimanual_mjcf(
                source,
                output,
                left_tri_suction=True,
                right_v_cradle=True,
            )
            model = ET.parse(output).getroot()
            left_include = model.find(".//body[@name='leftarm']/include")
            right_include = model.find(".//body[@name='rightarm']/include")
            self.assertIsNotNone(left_include)
            self.assertIsNotNone(right_include)
            left_geoms = ET.parse(left_include.attrib["file"]).getroot().findall(".//geom")
            right_geoms = ET.parse(right_include.attrib["file"]).getroot().findall(".//geom")
            self.assertEqual(
                len([geom for geom in left_geoms if "suction_cup" in geom.attrib.get("name", "") and "collision" in geom.attrib.get("name", "")]),
                3,
            )
            cup_collision_geoms = [
                geom
                for geom in left_geoms
                if "suction_cup" in geom.attrib.get("name", "")
                and "collision" in geom.attrib.get("name", "")
            ]
            cup_tips = [
                float(geom.attrib["pos"].split()[2])
                + float(geom.attrib["size"].split()[1])
                for geom in cup_collision_geoms
            ]
            self.assertTrue(
                all(
                    abs(tip - MOBILE_TRI_SUCTION_TIP_OFFSET_M) < 1e-9
                    for tip in cup_tips
                )
            )
            self.assertEqual(
                len(
                    [
                        geom
                        for geom in left_geoms
                        if "suction_stem" in geom.attrib.get("name", "")
                        and geom.attrib.get("contype") == "0"
                        and geom.attrib.get("conaffinity") == "0"
                    ]
                ),
                3,
            )
            self.assertEqual(
                len([geom for geom in right_geoms if "v_cradle" in geom.attrib.get("name", "") and "collision" in geom.attrib.get("name", "")]),
                2,
            )
            cradle_collision_geoms = [
                geom
                for geom in right_geoms
                if "v_cradle" in geom.attrib.get("name", "")
                and "collision" in geom.attrib.get("name", "")
            ]
            self.assertTrue(
                all(geom.attrib["size"] == "0.012 0.050 0.070" for geom in cradle_collision_geoms)
            )
            self.assertTrue(
                all(geom.attrib["pos"].endswith(" 0 0.204") for geom in cradle_collision_geoms)
            )
            left_root = ET.parse(left_include.attrib["file"]).getroot()
            gripper = left_root.find(".//body[@name='panda0_gripper']")
            self.assertIsNotNone(gripper)
            self.assertFalse(
                any(
                    geom.attrib.get("name", "").startswith("stock_finger")
                    for geom in gripper.findall("./body//geom")
                )
            )
            stock_collision_geoms = [
                geom
                for geom in gripper.findall("./geom") + gripper.findall("./body//geom")
                if "suction_cup" not in geom.attrib.get("name", "")
                and not geom.attrib.get("class", "").endswith("_viz")
            ]
            self.assertTrue(stock_collision_geoms)
            self.assertTrue(
                all(
                    geom.attrib.get("contype") == "0"
                    and geom.attrib.get("conaffinity") == "0"
                    for geom in stock_collision_geoms
                )
            )


if __name__ == "__main__":
    unittest.main()
