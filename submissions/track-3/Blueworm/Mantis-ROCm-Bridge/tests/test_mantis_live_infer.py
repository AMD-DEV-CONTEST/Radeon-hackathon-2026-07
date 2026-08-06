from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools/mantis_live_infer.py"
SPEC = importlib.util.spec_from_file_location("mantis_live_infer", TOOL)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class _Index:
    def __init__(self, value: int) -> None:
        self.dofs_idx_local = [value]


class _Robot:
    def __init__(self, names: list[str]) -> None:
        self._indices = {name: index + 10 for index, name in enumerate(names)}
        self.requested: list[int] | None = None

    def get_joint(self, name: str) -> _Index:
        return _Index(self._indices[name])

    def get_dofs_position(self, *, dofs_idx_local: list[int]) -> list[float]:
        self.requested = list(dofs_idx_local)
        return [float(value) for value in dofs_idx_local]


class MantisLiveInferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = TOOL.read_text(encoding="utf-8")
        cls.port = json.loads((ROOT / "configs/mantis-port-config.json").read_text())

    def test_import_is_lightweight_and_main_guarded(self) -> None:
        self.assertTrue(callable(MODULE.main))
        self.assertTrue(callable(MODULE.build_parser))
        self.assertNotIn("import torch\n", self.source.split("def execute", 1)[0])
        self.assertIn('if __name__ == "__main__":', self.source)

    def test_fresh_output_rejects_relative_and_existing_paths(self) -> None:
        with self.assertRaises(MODULE.LiveInferenceError):
            MODULE.require_fresh_output("relative/output")
        with tempfile.TemporaryDirectory() as directory:
            existing = Path(directory) / "existing"
            existing.mkdir()
            with self.assertRaises(MODULE.LiveInferenceError):
                MODULE.require_fresh_output(str(existing))
            fresh = Path(directory) / "fresh"
            self.assertEqual(
                MODULE.require_fresh_output(str(fresh)),
                fresh.parent.resolve() / fresh.name,
            )

    def test_named_dof_readback_preserves_contract_order(self) -> None:
        names = list(self.port["target"]["physical_joint_order"])
        robot = _Robot(names)
        indices = MODULE.resolve_dof_indices(robot, names)
        self.assertEqual(indices, list(range(10, 28)))
        values = MODULE.read_named_dofs(robot, indices)
        self.assertEqual(values, [float(value) for value in indices])
        self.assertEqual(robot.requested, indices)

    def test_virtual_grippers_are_bounded_by_named_channels(self) -> None:
        order = list(self.port["target"]["joint_order"])
        action = [0.0] * len(order)
        left = order.index("left_gripper_joint")
        right = order.index("right_gripper_joint")
        action[left] = -0.25
        action[right] = 1.25
        bounded, diagnostics = MODULE.bound_virtual_grippers(action, self.port)
        self.assertEqual(bounded[left], 0.0)
        self.assertEqual(bounded[right], 1.0)
        self.assertEqual({row["name"] for row in diagnostics}, {
            "left_gripper_joint", "right_gripper_joint"
        })
        self.assertTrue(all(row["changed"] for row in diagnostics))

    def test_readback_tolerance_is_contract_derived_and_override_is_exact(self) -> None:
        self.assertEqual(MODULE.resolve_readback_tolerance(self.port, None), 0.003)
        self.assertEqual(MODULE.resolve_readback_tolerance(self.port, 0.003), 0.003)
        with self.assertRaises(MODULE.LiveInferenceError):
            MODULE.resolve_readback_tolerance(self.port, 0.004)

    def test_default_tolerance_survives_parser_and_path_validation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bowl = root / "bowl"
            (bowl / "urdf").mkdir(parents=True)
            pretrained = root / "pretrained"
            pretrained.mkdir()
            files = {
                "urdf": root / "mantis.urdf",
                "bowl_urdf": bowl / "urdf/robotwin_002_bowl_model3.urdf",
                "bowl_manifest": bowl / "manifest.json",
                "ffmpeg": root / "ffmpeg",
            }
            files.update(
                {
                    name: pretrained / name
                    for name in (
                        "config.json",
                        "model.safetensors",
                        "policy_preprocessor.json",
                        "policy_postprocessor.json",
                    )
                }
            )
            for path in files.values():
                path.write_text("fixture", encoding="utf-8")
            args = MODULE.build_parser().parse_args(
                [
                    "--urdf",
                    str(files["urdf"]),
                    "--bowl-asset-root",
                    str(bowl),
                    "--pretrained-model",
                    str(pretrained),
                    "--port-config",
                    str(ROOT / "configs/mantis-port-config.json"),
                    "--camera-contract",
                    str(ROOT / "configs/camera-extrinsics-v1.json"),
                    "--scene-contract",
                    str(ROOT / "configs/stack-bowls-genesis-v1.json"),
                    "--source-task",
                    str(ROOT / "configs/source-task-stack-bowls-three.json"),
                    "--seed",
                    "101",
                    "--output-dir",
                    str(root / "output"),
                    "--ffmpeg",
                    str(files["ffmpeg"]),
                ]
            )
            self.assertIsNone(args.readback_range_tolerance)
            paths = MODULE.validate_args(args)
            self.assertEqual(paths["output_dir"], root.resolve() / "output")

    def test_nonfinite_or_wrong_dimension_fails_closed(self) -> None:
        with self.assertRaises(MODULE.LiveInferenceError):
            MODULE.validate_finite_vector([0.0] * 15, expected=16, label="state")
        with self.assertRaises(MODULE.LiveInferenceError):
            MODULE.validate_finite_vector(
                [0.0] * 15 + [float("nan")], expected=16, label="state"
            )

    def test_saved_processors_and_exact_new_runtime_are_required(self) -> None:
        self.assertIn("make_pre_post_processors", self.source)
        self.assertIn("policy_cfg=policy.config", self.source)
        self.assertIn("pretrained_path=str(paths[\"pretrained_model\"])", self.source)
        self.assertIn("local_files_only=True", self.source)
        self.assertIn('EXPECTED_LEROBOT_VERSION = "0.6.2"', self.source)
        self.assertIn('EXPECTED_GENESIS_VERSION = "1.3.0"', self.source)
        self.assertNotIn('EXPECTED_LEROBOT_VERSION = "0.4.4"', self.source)
        self.assertNotIn('EXPECTED_GENESIS_VERSION = "1.2.3"', self.source)

    def test_three_real_cameras_named_mapping_home_and_actuation_are_encoded(self) -> None:
        self.assertIn("genesis_wrist_mounts(camera_contract)", self.source)
        self.assertIn("camera.attach(", self.source)
        self.assertIn("render_once(cameras, np)", self.source)
        self.assertIn("project_physical_to_virtual(", self.source)
        self.assertIn("physical_pose(port, 1.0)", self.source)
        self.assertIn("dofs_idx_local=indices", self.source)
        self.assertNotIn("torch.zeros", self.source)
        self.assertNotIn("qphys[:16]", self.source)

    def test_frozen_three_bowl_scene_and_dynamics_are_encoded(self) -> None:
        parser = MODULE.build_parser()
        required = {
            action.dest
            for action in parser._actions
            if getattr(action, "required", False)
        }
        self.assertTrue(
            {
                "bowl_asset_root",
                "scene_contract",
                "source_task",
                "seed",
            }.issubset(required)
        )
        for marker in (
            "validate_genesis_scene_contract",
            "sample_source_reset_poses(seed=args.seed)",
            "robotwin_002_bowl_model3.urdf",
            "for pose in reset_poses",
            "bowl_friction_coefficient",
            "finger_friction_coefficient",
            "set_dofs_kp",
            "set_dofs_kv",
            "set_dofs_force_range",
            "apply_allowed_collision_filter(scene, robot, np)",
            "ALLOWED_PROXIMAL_COLLISION_LINKS",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.source)
        self.assertNotIn("gs.morphs.Box", self.source)
        self.assertNotIn("--base-y", self.source)
        self.assertNotIn("--base-z", self.source)
        self.assertNotIn("--table-z", self.source)

    def test_policy_physics_schedule_is_contract_derived(self) -> None:
        self.assertIn('scene_contract["control"]["physics_dt_s"]', self.source)
        self.assertIn('scene_contract["control"]["policy_hz"]', self.source)
        self.assertIn("target_physics_steps = math.ceil(", self.source)
        self.assertNotIn("--physics-steps-per-action", self.source)

    def test_no_motion_or_overwrite_fallback_exists(self) -> None:
        lowered = self.source.lower()
        self.assertNotIn("synthetic motion", lowered)
        self.assertNotIn("holding motion", lowered)
        self.assertNotIn("os.system", self.source)
        self.assertNotIn('"-y"', self.source)
        self.assertNotIn("todo", lowered)
        self.assertIn("exist_ok=False", self.source)
        self.assertIn("write_text_exclusive", self.source)

    def test_terminal_evidence_surface_is_present(self) -> None:
        for name in (
            "started.json",
            "command.txt",
            "environment.json",
            "input_files.SHA256SUMS",
            "policy_steps.jsonl",
            "scene.json",
            "finished_at_utc.txt",
            "exit_code.txt",
            "status",
            "SHA256SUMS",
        ):
            with self.subTest(name=name):
                self.assertIn(name, self.source)


if __name__ == "__main__":
    unittest.main()
