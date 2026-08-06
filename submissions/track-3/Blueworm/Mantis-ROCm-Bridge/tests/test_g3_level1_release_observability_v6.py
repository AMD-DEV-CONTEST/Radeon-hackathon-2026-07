from __future__ import annotations

import copy
import importlib.util
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

from mantis_rocm_bridge.genesis_smoke import sha256_file
from mantis_rocm_bridge.stack_bowls_env import (
    arm_for_bowl_x,
    sample_source_reset_poses,
)


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "configs/g3-level1-release-observability-v6.json"
AUTHORIZATION_PATH = (
    ROOT / "configs/g3-level1-release-execution-authorization-v7.json"
)
DRIVER_PATH = (
    ROOT
    / ".ops/wip/g3-level1-release-observability-20260728"
    / "run_g3_level1_release_observability_20260728_v6.py"
)
SUPERVISOR_PATH = (
    ROOT
    / ".ops/wip/g3-level1-release-observability-20260728"
    / "run_g3_level1_release_observability_supervisor_20260728_v6.sh"
)


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


CORE = load_module(
    "g3_level1_release_core_v6",
    ROOT / "tools/run_genesis_stack_bowls_scripted_g1.py",
)
WRAPPER = load_module(
    "g3_level1_release_wrapper_v6",
    ROOT / "tools/run_genesis_stack_bowls_level1_release_diagnostic.py",
)
DRIVER = load_module("g3_level1_release_driver_v6", DRIVER_PATH)


class Level1ReleaseContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        cls.authorization = json.loads(
            AUTHORIZATION_PATH.read_text(encoding="utf-8")
        )
        cls.contract_sha256 = sha256_file(CONTRACT_PATH)

    def validate(
        self,
        *,
        seed: int = 1423,
        generation_mode: str = "probe",
        capture: bool = False,
        backend: str = "cpu",
        cuda_visible_devices: str | None = "",
        contract: dict | None = None,
        authorization: dict | None = None,
    ) -> str:
        return CORE.validate_level1_release_execution_contract(
            contract if contract is not None else self.contract,
            authorization if authorization is not None else self.authorization,
            planning_contract_sha256=self.contract_sha256,
            seed=seed,
            generation_mode=generation_mode,
            capture=capture,
            backend=backend,
            cuda_visible_devices=cuda_visible_devices,
        )

    def test_authorization_binds_exact_contract(self) -> None:
        self.assertEqual(
            self.authorization["planning_contract_sha256"],
            self.contract_sha256,
        )
        self.assertEqual(
            tuple(self.authorization["diagnostic_seed_order"]),
            CORE.G3_LEVEL1_RELEASE_DIAGNOSTIC_SEEDS,
        )

    def test_seed_panel_and_strata_recompute_exactly(self) -> None:
        panel = self.contract["diagnostic_panel"]
        far: list[int] = []
        near: list[int] = []
        for seed in range(
            panel["scan_range_inclusive"][0],
            panel["scan_range_inclusive"][1] + 1,
        ):
            reset = sorted(
                sample_source_reset_poses(seed=seed),
                key=lambda pose: pose.position_xyz_m[1],
            )
            pattern = [
                arm_for_bowl_x(pose.position_xyz_m[0]) for pose in reset
            ]
            if pattern != panel["pattern"]:
                continue
            x, y, _ = reset[1].position_xyz_m
            radius = math.hypot(x, y)
            if radius >= 0.22 and len(far) < 4:
                far.append(seed)
            if radius <= 0.15 and len(near) < 4:
                near.append(seed)
            frozen = panel["seed_rows"].get(str(seed))
            if frozen is not None:
                self.assertAlmostEqual(frozen["bowl2_xy_m"][0], x)
                self.assertAlmostEqual(frozen["bowl2_xy_m"][1], y)
                self.assertAlmostEqual(frozen["bowl2_radius_m"], radius)
        self.assertEqual(tuple(far + near), DRIVER.SEEDS)

    def test_exact_cpu_probe_panel_is_accepted(self) -> None:
        for seed in DRIVER.SEEDS:
            self.assertEqual(
                self.validate(seed=seed),
                "level1_release_observability",
            )

    def test_unknown_seed_gpu_capture_and_online_fail_closed(self) -> None:
        for values in (
            {"seed": 1424},
            {"backend": "cuda"},
            {"cuda_visible_devices": None},
            {"capture": True},
            {"generation_mode": "online"},
            {"generation_mode": "replay"},
        ):
            with self.assertRaises(RuntimeError):
                self.validate(**values)

    def test_authorization_mutation_and_seed_order_fail_closed(self) -> None:
        drifted = copy.deepcopy(self.authorization)
        drifted["planning_contract_sha256"] = "0" * 64
        with self.assertRaises(RuntimeError):
            self.validate(authorization=drifted)
        drifted = copy.deepcopy(self.authorization)
        drifted["authorized_actions"]["change_controller"] = True
        with self.assertRaises(RuntimeError):
            self.validate(authorization=drifted)
        drifted_contract = copy.deepcopy(self.contract)
        drifted_contract["diagnostic_panel"]["seeds_in_order"].reverse()
        with self.assertRaises(RuntimeError):
            self.validate(contract=drifted_contract)

    def test_core_source_binds_success_progress_and_failure(self) -> None:
        source = (
            ROOT / "tools/run_genesis_stack_bowls_scripted_g1.py"
        ).read_text(encoding="utf-8")
        self.assertGreaterEqual(
            source.count('"level1_release_contract_sha256"'),
            5,
        )
        self.assertGreaterEqual(
            source.count('"level1_release_authorization_sha256"'),
            5,
        )
        self.assertIn(
            "level1-release observability advanced the control clock",
            source,
        )
        self.assertEqual(
            source.count(
                "level1_release_observability = begin_release_observability("
            ),
            2,
        )
        self.assertEqual(
            source.count(
                "level1_release_observability: dict[str, Any] | None = None"
            ),
            1,
        )


class QuaternionAndPoseTests(unittest.TestCase):
    def test_normalization_is_sign_invariant(self) -> None:
        first = CORE.normalize_quaternion_wxyz([2.0, -1.0, 0.0, 0.0])
        second = CORE.normalize_quaternion_wxyz([-2.0, 1.0, 0.0, 0.0])
        self.assertEqual(first, second)
        self.assertAlmostEqual(sum(value * value for value in first), 1.0)

    def test_identity_relative_pose(self) -> None:
        relative = CORE.relative_pose_wxyz(
            reference_position_xyz_m=[1.0, 2.0, 3.0],
            reference_quaternion_wxyz=[1.0, 0.0, 0.0, 0.0],
            target_position_xyz_m=[1.1, 2.2, 3.3],
            target_quaternion_wxyz=[-1.0, 0.0, 0.0, 0.0],
        )
        for actual, expected in zip(
            relative["translation_xyz_m"],
            [0.1, 0.2, 0.3],
        ):
            self.assertAlmostEqual(actual, expected)
        self.assertEqual(relative["quaternion_wxyz"], [1.0, 0.0, 0.0, 0.0])

    def test_reference_rotation_is_applied(self) -> None:
        half = math.sqrt(0.5)
        relative = CORE.relative_pose_wxyz(
            reference_position_xyz_m=[0.0, 0.0, 0.0],
            reference_quaternion_wxyz=[half, 0.0, 0.0, half],
            target_position_xyz_m=[0.0, 1.0, 0.0],
            target_quaternion_wxyz=[half, 0.0, 0.0, half],
        )
        self.assertAlmostEqual(relative["translation_xyz_m"][0], 1.0)
        self.assertAlmostEqual(relative["translation_xyz_m"][1], 0.0)
        self.assertAlmostEqual(relative["translation_xyz_m"][2], 0.0)
        self.assertEqual(relative["quaternion_wxyz"], [1.0, 0.0, 0.0, 0.0])

    def test_pose_delta_treats_q_and_minus_q_as_same_rotation(self) -> None:
        delta = CORE.pose_delta_wxyz(
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 0.0, 0.0],
            [-1.0, 0.0, 0.0, 0.0],
        )
        self.assertEqual(delta["rotation_angle_rad"], 0.0)

    def test_malformed_and_nonfinite_inputs_fail(self) -> None:
        for function, arguments in (
            (CORE.normalize_quaternion_wxyz, ([0.0, 0.0, 0.0, 0.0],)),
            (CORE.normalize_quaternion_wxyz, ([1.0, 0.0, math.inf, 0.0],)),
            (CORE.rotate_vector_wxyz, ([1.0, 0.0, 0.0, 0.0], [1.0, 2.0])),
        ):
            with self.assertRaises(ValueError):
                function(*arguments)


class Level1ReleaseWrapperTests(unittest.TestCase):
    def make_paths(self, root: Path) -> dict[str, Path]:
        paths = {
            "mantis": root / "mantis.urdf",
            "bowl": root / "bowl",
            "core": root / "core.py",
            "r3": root / "r3.json",
            "contract": root / "contract.json",
            "authorization": root / "authorization.json",
            "ops": root / "ops",
        }
        (paths["bowl"] / "urdf").mkdir(parents=True)
        for path in (
            paths["mantis"],
            paths["core"],
            paths["r3"],
            paths["contract"],
            paths["authorization"],
            paths["bowl"] / "urdf/robotwin_002_bowl_model3.urdf",
        ):
            path.write_text("x", encoding="utf-8")
        return paths

    def parse(self, paths: dict[str, Path], seed: int = 1423):
        return WRAPPER.build_parser().parse_args(
            [
                str(paths["mantis"]),
                str(paths["bowl"]),
                "--ops-root",
                str(paths["ops"]),
                "--run-id",
                f"release-{seed}",
                "--seed",
                str(seed),
                "--core-tool",
                str(paths["core"]),
                "--r3-contract",
                str(paths["r3"]),
                "--diagnostic-contract",
                str(paths["contract"]),
                "--execution-authorization",
                str(paths["authorization"]),
            ]
        )

    def test_command_forces_cpu_probe_no_capture_and_contracts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self.make_paths(Path(tmp))
            command = WRAPPER.build_core_command(
                self.parse(paths),
                python_executable="/python",
            )
            self.assertEqual(command[command.index("--backend") + 1], "cpu")
            self.assertEqual(
                command[command.index("--generation-mode") + 1],
                "probe",
            )
            self.assertEqual(
                command[
                    command.index(
                        "--consecutive-left-orientation-schedule"
                    )
                    + 1
                ],
                "coupled_descent_slerp",
            )
            self.assertIn("--level1-release-diagnostic-contract", command)
            self.assertIn("--level1-release-diagnostic-authorization", command)
            self.assertNotIn("--capture", command)
            self.assertNotIn("--corrected-expert-contract", command)

    def test_seed_and_policy_limit_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self.make_paths(Path(tmp))
            with self.assertRaises(ValueError):
                WRAPPER.build_core_command(self.parse(paths, seed=1424))
            args = self.parse(paths)
            args.probe_max_policy_steps = 1199
            with self.assertRaises(ValueError):
                WRAPPER.build_core_command(args)


class Level1ReleaseDriverTests(unittest.TestCase):
    def row(
        self,
        seed: int,
        *,
        release_class: str = "stable_control",
        observed: bool = True,
    ) -> dict:
        return {
            "seed": seed,
            "stratum": DRIVER.STRATA[seed],
            "level1_observed": observed,
            "observation_valid": observed,
            "release_class": release_class if observed else None,
            "safety_failure": False,
            "infrastructure_failure": False,
            "capture_artifact_count": 0,
        }

    def synthetic_progress(self, seed: int = 1423) -> dict:
        snapshots: list[dict] = []
        z_values = (0.75, 0.75, 0.774, 0.747, 0.7445)
        for index, (label, weld, z_value) in enumerate(
            zip(DRIVER.SNAPSHOT_LABELS, DRIVER.WELD_STATES, z_values)
        ):
            snapshot = {
                "label": label,
                "policy_step": 100 + index,
                "physics_step": 400 + index,
                "weld_registered": weld,
                "suction_link_position_xyz_m": [0.0, 0.0, 0.8],
                "suction_link_quaternion_wxyz": [1.0, 0.0, 0.0, 0.0],
                "bowl_position_xyz_m": [0.0, 0.0, z_value],
                "bowl_quaternion_wxyz": [1.0, 0.0, 0.0, 0.0],
                "selected_bowl_contact_pairs": [],
                "selected_bowl_contact_pair_count": 0,
                "active_side_clamp_links_in_contact": [],
                "observer_policy_step_delta": 0,
                "observer_physics_step_delta": 0,
            }
            snapshot["bowl_in_suction_frame"] = CORE.relative_pose_wxyz(
                reference_position_xyz_m=snapshot[
                    "suction_link_position_xyz_m"
                ],
                reference_quaternion_wxyz=snapshot[
                    "suction_link_quaternion_wxyz"
                ],
                target_position_xyz_m=snapshot["bowl_position_xyz_m"],
                target_quaternion_wxyz=snapshot["bowl_quaternion_wxyz"],
            )
            snapshots.append(snapshot)
        release_drop = (z_values[2] - z_values[3]) * 1000.0
        post_drop = (z_values[3] - z_values[4]) * 1000.0
        observation = {
            "schema_version": 1,
            "work_package_id": "WP-G3-CORR-011",
            "observability_schema": "relative_pose_and_contact_trace_v1",
            "level": 1,
            "bowl": "bowl2",
            "assigned_side": "left",
            "suction_link": "left_clamp_link6",
            "snapshots": snapshots,
            "derived_metrics": {
                "release_drop_mm": release_drop,
                "post_release_to_placed_drop_mm": post_drop,
            },
            "observer_advanced_clock": False,
        }
        return {
            "schema_version": 1,
            "seed": seed,
            "generation_mode": "probe",
            "level1_release_work_package_id": "WP-G3-CORR-011",
            "level1_release_phase": "level1_release_observability",
            "level1_release_contract_sha256": DRIVER.EXPECTED_HASHES[
                DRIVER.CONTRACT_RELATIVE
            ],
            "level1_release_authorization_sha256": DRIVER.EXPECTED_HASHES[
                DRIVER.AUTHORIZATION_RELATIVE
            ],
            "bowl_data": {
                "stack_level": 1,
                "bowl": "bowl2",
                "assigned_side": "left",
                "level1_release_contract_sha256": DRIVER.EXPECTED_HASHES[
                    DRIVER.CONTRACT_RELATIVE
                ],
                "level1_release_authorization_sha256": DRIVER.EXPECTED_HASHES[
                    DRIVER.AUTHORIZATION_RELATIVE
                ],
                "level1_release_observability": observation,
            },
        }

    def test_independent_observation_audit_and_classification(self) -> None:
        result = DRIVER.validate_level1_observation(
            self.synthetic_progress(),
            seed=1423,
            contract_sha256=DRIVER.EXPECTED_HASHES[
                DRIVER.CONTRACT_RELATIVE
            ],
            authorization_sha256=DRIVER.EXPECTED_HASHES[
                DRIVER.AUTHORIZATION_RELATIVE
            ],
        )
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["release_class"], "release_drop_case")
        self.assertAlmostEqual(result["release_drop_mm"], 27.0)

    def test_observer_clock_and_hash_drift_fail_audit(self) -> None:
        progress = self.synthetic_progress()
        progress["level1_release_contract_sha256"] = "0" * 64
        progress["bowl_data"]["level1_release_observability"]["snapshots"][0][
            "observer_policy_step_delta"
        ] = 1
        result = DRIVER.validate_level1_observation(
            progress,
            seed=1423,
            contract_sha256=DRIVER.EXPECTED_HASHES[
                DRIVER.CONTRACT_RELATIVE
            ],
            authorization_sha256=DRIVER.EXPECTED_HASHES[
                DRIVER.AUTHORIZATION_RELATIVE
            ],
        )
        self.assertFalse(result["valid"])
        self.assertTrue(
            any("binding mismatch" in error for error in result["errors"])
        )
        self.assertTrue(
            any("advanced clock" in error for error in result["errors"])
        )

    def test_terminal_accepts_only_complete_contrast(self) -> None:
        rows = [self.row(seed) for seed in DRIVER.SEEDS]
        rows[4]["release_class"] = "release_drop_case"
        self.assertEqual(
            DRIVER.classify_terminal(rows),
            "COMPLETE_LEVEL1_RELEASE_OBSERVABILITY_ACCEPTED",
        )
        rows[4]["release_class"] = "stable_control"
        self.assertEqual(
            DRIVER.classify_terminal(rows),
            "COMPLETE_LEVEL1_RELEASE_OBSERVABILITY_INCONCLUSIVE",
        )

    def test_six_observations_require_two_per_stratum(self) -> None:
        rows = [self.row(seed) for seed in DRIVER.SEEDS]
        rows[0]["release_class"] = "release_drop_case"
        rows[1]["level1_observed"] = False
        rows[1]["observation_valid"] = False
        rows[4]["level1_observed"] = False
        rows[4]["observation_valid"] = False
        self.assertEqual(
            DRIVER.classify_terminal(rows),
            "COMPLETE_LEVEL1_RELEASE_OBSERVABILITY_ACCEPTED",
        )
        rows[5]["level1_observed"] = False
        rows[5]["observation_valid"] = False
        self.assertEqual(
            DRIVER.classify_terminal(rows),
            "COMPLETE_LEVEL1_RELEASE_OBSERVABILITY_INCONCLUSIVE",
        )

    def test_infrastructure_capture_and_safety_terminals(self) -> None:
        rows = [self.row(seed) for seed in DRIVER.SEEDS]
        rows[0]["infrastructure_failure"] = True
        self.assertEqual(
            DRIVER.classify_terminal(rows),
            "FAILED_EVIDENCE_GATE",
        )
        rows = [self.row(seed) for seed in DRIVER.SEEDS]
        rows[0]["capture_artifact_count"] = 1
        self.assertEqual(
            DRIVER.classify_terminal(rows),
            "FAILED_EVIDENCE_GATE",
        )
        rows = [self.row(seed) for seed in DRIVER.SEEDS]
        rows[0]["safety_failure"] = True
        self.assertEqual(
            DRIVER.classify_terminal(rows),
            "COMPLETE_LEVEL1_RELEASE_OBSERVABILITY_REJECTED",
        )

    def test_failure_taxonomy_distinguishes_transition_order(self) -> None:
        self.assertEqual(
            DRIVER.failure_category("bowl1 placement misses level 0: x"),
            "pre_transition_placement_predicate",
        )
        self.assertEqual(
            DRIVER.failure_category("bowl2 placement misses level 1: x"),
            "pre_transition_placement_predicate",
        )
        self.assertEqual(
            DRIVER.failure_category("bowl3 placement misses level 2: x"),
            "post_transition_placement_predicate",
        )

    def test_pinned_hashes_match_local_implementation(self) -> None:
        for relative, expected in DRIVER.EXPECTED_HASHES.items():
            if relative == DRIVER.CORE_RELATIVE:
                self.assertEqual(
                    expected,
                    "736c485b0d570f8e5e09e489b615877429c05f081cd73215f7842e48de65126b",
                )
                continue
            self.assertEqual(sha256_file(ROOT / relative), expected)

    def test_no_clobber_supervisor_is_cpu_isolated(self) -> None:
        source = SUPERVISOR_PATH.read_text(encoding="utf-8")
        self.assertIn("set -o noclobber", source)
        self.assertIn('CUDA_VISIBLE_DEVICES=""', source)
        self.assertIn("PACKAGE.SHA256SUMS", source)
        self.assertIn("supervisor_final_evidence.SHA256SUMS", source)
        self.assertNotIn("kill ", source)
        self.assertNotIn("rm -", source)

    def test_recovery_driver_fails_fast_on_evidence_failure(self) -> None:
        source = DRIVER_PATH.read_text(encoding="utf-8")
        self.assertIn('BATCH / "fail_fast.json"', source)
        self.assertIn(
            'row.get("infrastructure_failure") is True',
            source,
        )
        self.assertIn(
            'int(row.get("capture_artifact_count", 0)) != 0',
            source,
        )

    def test_recovery_targets_are_version_separated(self) -> None:
        self.assertTrue(
            str(DRIVER.PRIOR_CODE_GATE_RECOVERY_TARGET).endswith(
                "code-gate-20260728-v7"
            )
        )
        self.assertTrue(
            str(DRIVER.PRIOR_RUNTIME_CODE_GATE_TARGET).endswith(
                "code-gate-20260728-v8"
            )
        )
        self.assertTrue(str(DRIVER.CODE_GATE).endswith("code-gate-20260728-v9"))

    def test_actual_recovery_overlays_pass_pure_static_validation(self) -> None:
        recovery = json.loads(
            (ROOT / DRIVER.CODE_GATE_RECOVERY_RELATIVE).read_text(
                encoding="utf-8"
            )
        )
        runtime = json.loads(
            (ROOT / DRIVER.RUNTIME_RECOVERY_RELATIVE).read_text(
                encoding="utf-8"
            )
        )
        static = json.loads(
            (ROOT / DRIVER.STATIC_ADMISSION_RECOVERY_RELATIVE).read_text(
                encoding="utf-8"
            )
        )
        DRIVER.validate_recovery_overlays(recovery, runtime, static)
        drifted = copy.deepcopy(static)
        drifted["replacement"]["code_gate_root"] = str(
            DRIVER.PRIOR_RUNTIME_CODE_GATE_TARGET
        )
        with self.assertRaises(RuntimeError):
            DRIVER.validate_recovery_overlays(recovery, runtime, drifted)


if __name__ == "__main__":
    unittest.main()
