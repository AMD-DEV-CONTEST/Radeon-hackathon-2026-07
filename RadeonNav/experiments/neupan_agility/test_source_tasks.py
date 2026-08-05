from __future__ import annotations

import xml.etree.ElementTree as ET

import mujoco
import numpy as np
import pytest

from source_tasks import (
    TASKS,
    TASK_ORDER,
    SourceProxyTerrainCfg,
    configured_fragment,
    goal_delta_yaw,
    proxy_height_scan,
    proxy_sampler,
    source_episode_complete,
)


def test_source_task_contracts() -> None:
    assert TASK_ORDER == (
        "frame",
        "tunnel",
        "poles",
        "bar_jump",
        "tire_jump",
        "seesaw",
    )
    expected_peaks = {
        "frame": 0.33,
        "tunnel": 0.4,
        "poles": 1.0,
        "bar_jump": 0.42,
        "tire_jump": 1.5,
        "seesaw": 0.26,
    }
    for name, spec in TASKS.items():
        output = SourceProxyTerrainCfg(task=name, size=(8.0, 8.0)).function(
            0.0, np.random.default_rng(7)
        )
        heights = output.heightfield.physical_heights_xy()
        assert heights.shape == (160, 160)
        assert float(heights.max()) == pytest.approx(expected_peaks[name])
        assert spec.fragment_file.is_file()
        root = ET.parse(spec.fragment_file).getroot()
        assert root.tag == "mujoco"
        if name in {"bar_jump", "tire_jump"}:
            joint = root.find(".//joint")
            assert joint is not None
            assert joint.attrib["stiffness"] == "20000"
            assert joint.attrib["damping"] == "1000"
            assert float(joint.attrib["springref"]) == pytest.approx(
                0.20 if name == "bar_jump" else 0.475
            )
        if name == "tire_jump":
            ring = root.findall(".//geom[@type='capsule']")
            assert len(ring) == 16
            assert all(geom.attrib["size"] == "0.03" for geom in ring)
        if name == "seesaw":
            joint = root.find(".//joint")
            assert joint is not None
            assert joint.attrib["limited"] == "true"
            assert joint.attrib["range"] == "-0.16745 0.16745"
            assert joint.attrib["armature"] == "0.01"
            base = root.find(".//body[@name='source_seesaw_base']")
            board = root.find(
                ".//body[@name='source_seesaw_base']"
                "/body[@name='source_seesaw_board']"
            )
            assert base is not None
            assert board is not None
            inertial = root.find(".//body[@name='source_seesaw_board']/inertial")
            assert inertial is not None
            assert inertial.attrib["diaginertia"] == "10.668 10.833 0.17"
            collision = board.find("./geom[@name='source_seesaw_board_collision']")
            assert collision is not None
            assert collision.attrib["type"] == "box"
            assert collision.attrib["pos"] == "0 0 0.015"
            assert collision.attrib["size"] == "1.5 0.3 0.015"
            exclude = root.find("./contact/exclude")
            assert exclude is not None
            assert exclude.attrib == {
                "body1": "source_seesaw_base",
                "body2": "source_seesaw_board",
            }
            assert mujoco.MjModel.from_xml_path(str(spec.fragment_file)).nq == 1

    spec = TASKS["frame"]
    delta, goal_index, timer = goal_delta_yaw(
        spec,
        np.asarray([[*spec.start_xy, 0.42]], dtype=np.float32),
        np.asarray([[1.0, 0.0, 0.0, 0.0]], dtype=np.float32),
        0,
        0,
    )
    assert goal_index == 0
    assert timer == 1
    assert not source_episode_complete(spec, goal_index, timer)
    assert source_episode_complete(spec, len(spec.goals) - 1, 2)
    np.testing.assert_allclose(delta, 0.0, atol=1.0e-6)

    scan = proxy_height_scan(
        np.asarray([[*spec.start_xy, 0.42]], dtype=np.float32),
        np.asarray([[1.0, 0.0, 0.0, 0.0]], dtype=np.float32),
        proxy_sampler("frame"),
    )
    assert scan.shape == (1, 132)
    assert np.isfinite(scan).all()

    low_bar = SourceProxyTerrainCfg(
        task="bar_jump", bar_height=0.20, size=(8.0, 8.0)
    ).function(0.0, np.random.default_rng(7))
    high_bar = SourceProxyTerrainCfg(
        task="bar_jump", bar_height=0.25, size=(8.0, 8.0)
    ).function(0.0, np.random.default_rng(7))
    center = tuple(value // 2 for value in low_bar.heightfield.noise.shape)
    assert low_bar.heightfield.noise[center] * 0.005 == pytest.approx(0.20)
    assert high_bar.heightfield.noise[center] * 0.005 == pytest.approx(0.25)

    with configured_fragment(TASKS["bar_jump"], bar_height=0.25) as fragment:
        model = mujoco.MjModel.from_xml_path(str(fragment))
        joint_id = mujoco.mj_name2id(
            model, mujoco.mjtObj.mjOBJ_JOINT, "source_bar_joint"
        )
        assert model.qpos_spring[model.jnt_qposadr[joint_id]] == pytest.approx(0.25)
