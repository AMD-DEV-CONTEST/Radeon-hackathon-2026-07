import math
from pathlib import Path
import xml.etree.ElementTree as ET

from radeon_home.mjcf_mobile_pipeline import (
    OBJECT_PROFILES,
    PlanarPose,
    SlipDetector,
    WORK_SURFACE_NEAR_EDGE_M,
    WORK_SURFACE_SIZE_M,
    delivery_pose_with_payload_heading,
    docking_pose,
    prepare_planar_franka_mjcf,
    unload_instability_reasons,
    work_surface_center_local_x,
)


def test_planar_pose_round_trip() -> None:
    pose = PlanarPose(2.0, -1.5, math.pi / 2)
    local = [0.34, -0.08, 0.78]
    world = pose.local_to_world(local)
    assert all(
        math.isclose(actual, expected, abs_tol=1e-9)
        for actual, expected in zip(world, [2.08, -1.16, 0.78])
    )
    assert all(
        math.isclose(actual, expected, abs_tol=1e-9)
        for actual, expected in zip(pose.world_to_local(world), local)
    )


def test_docking_pose_faces_nearest_furniture() -> None:
    north = docking_pose("bedside_table")
    south = docking_pose("trash_bin")
    assert math.isclose(north.yaw, math.pi / 2)
    assert math.isclose(south.yaw, -math.pi / 2)
    assert north.local_to_world([0.5, 0.0])[1] > north.y
    assert south.local_to_world([0.5, 0.0])[1] < south.y


def test_delivery_pose_preserves_loaded_heading() -> None:
    pickup = docking_pose("bedside_table")
    delivery = delivery_pose_with_payload_heading("bedside_table", "trash_bin")
    assert delivery.x == 2.0
    assert delivery.y == -2.0
    assert delivery.yaw == pickup.yaw


def test_work_surface_starts_beyond_mobile_arm_base() -> None:
    center = work_surface_center_local_x()
    near_edge = center - WORK_SURFACE_SIZE_M[0] / 2.0
    assert math.isclose(near_edge, WORK_SURFACE_NEAR_EDGE_M)
    assert near_edge >= 0.18


def test_object_profiles_have_graspable_geometry_and_requested_variety() -> None:
    assert len(OBJECT_PROFILES) == 5
    masses = {profile.mass_kg for profile in OBJECT_PROFILES.values()}
    sizes = {profile.size_xyz_m for profile in OBJECT_PROFILES.values()}
    assert len(masses) == 5
    assert len(sizes) == 5
    for profile in OBJECT_PROFILES.values():
        assert max(profile.size_xyz_m[:2]) <= 0.06
        assert profile.mass_kg > 0
        assert profile.density_kg_m3 > 0


def test_slip_detector_requires_sustained_drift() -> None:
    detector = SlipDetector(
        (0.0, 0.0, -0.10),
        drift_threshold_m=0.02,
        velocity_threshold_m_s=10.0,
        consecutive_required=2,
    )
    assert detector.observe([0.0, 0.0, -0.10]) is None
    assert detector.observe([0.0, 0.0, -0.125]) is None
    event = detector.observe([0.0, 0.0, -0.126])
    assert event is not None
    assert event["trigger"] == "relative_drift"
    assert event["drift_m"] >= 0.02


def test_slip_detector_reset_clears_trigger_streak() -> None:
    detector = SlipDetector(
        (0.0, 0.0, -0.10),
        drift_threshold_m=0.02,
        consecutive_required=2,
    )
    assert detector.observe([0.0, 0.0, -0.13]) is None
    detector.reset_observation([0.0, 0.0, -0.10])
    assert detector.observe([0.0, 0.0, -0.13]) is None


def test_unload_instability_reports_independent_pre_loss_signals() -> None:
    assert unload_instability_reasons(
        bilateral_contact=False,
        relative_drift_m=0.013,
        hand_payload_distance_m=0.17,
        drift_threshold_m=0.012,
        preloss_distance_m=0.165,
    ) == [
        "bilateral_finger_contact_lost",
        "hand_relative_payload_drift",
        "preloss_distance_threshold",
    ]
    assert (
        unload_instability_reasons(
            bilateral_contact=True,
            relative_drift_m=0.003,
            hand_payload_distance_m=0.12,
            drift_threshold_m=0.012,
            preloss_distance_m=0.165,
        )
        == []
    )


def test_prepare_planar_mjcf_preserves_finger_pads(tmp_path: Path) -> None:
    source_dir = tmp_path / "reference" / "assets" / "robots" / "franka"
    source_dir.mkdir(parents=True)
    source = source_dir / "panda.xml"
    source.write_text(
        """<mujoco><compiler meshdir="assets"/><default>
        <default class="fingertip_pad_collision_1"><geom type="box"/></default>
        </default><worldbody><body name="link0"><inertial mass="1"/>
        <geom mesh="link0_c" class="collision"/>
        <body name="left_finger"/><body name="right_finger"/>
        </body></worldbody></mujoco>""",
        encoding="utf-8",
    )
    generated = prepare_planar_franka_mjcf(tmp_path / "reference", tmp_path / "out")
    root = ET.parse(generated).getroot()
    joint_names = {
        joint.attrib["name"]
        for joint in root.findall("./worldbody/body[@name='link0']/joint")
    }
    assert joint_names == {"base_x", "base_y", "base_yaw"}
    assert root.find(".//default[@class='fingertip_pad_collision_1']") is not None
    link0_collision = root.find(
        "./worldbody/body[@name='link0']/geom[@mesh='link0_c']"
    )
    assert link0_collision is not None
    assert link0_collision.attrib["contype"] == "0"
    assert link0_collision.attrib["conaffinity"] == "0"
    root_proxy = root.find(
        "./worldbody/body[@name='link0']/geom"
        "[@name='mobile_root_collision_proxy']"
    )
    assert root_proxy is not None
    assert root_proxy.attrib["type"] == "cylinder"
    assert root_proxy.attrib["size"] == "0.22 0.10"
    assert root_proxy.attrib["pos"] == "0 0 -0.65"
    assert root_proxy.attrib.get("contype") != "0"
    support_tray = root.find(
        "./worldbody/body[@name='link0']/body"
        "[@name='payload_tray_body']/geom"
        "[@name='mobile_payload_support_tray']"
    )
    assert support_tray is not None
    assert support_tray.attrib["type"] == "box"
    assert support_tray.attrib.get("contype") != "0"
    tray_joint = root.find(
        "./worldbody/body[@name='link0']/body"
        "[@name='payload_tray_body']/joint[@name='tray_slide']"
    )
    assert tray_joint is not None
    assert tray_joint.attrib["range"] == "0 0.46"
    compiler = root.find("compiler")
    assert compiler is not None
    assert Path(compiler.attrib["meshdir"]).is_absolute()
