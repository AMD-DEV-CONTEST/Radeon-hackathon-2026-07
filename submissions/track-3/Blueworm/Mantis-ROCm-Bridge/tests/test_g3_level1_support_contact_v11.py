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
from mantis_rocm_bridge.support_contact import (
    SNAPSHOT_LABELS,
    validate_support_contact_observation,
)


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = (
    ROOT / "configs/g3-level1-support-contact-observability-v11.json"
)
AUTHORIZATION_PATH = (
    ROOT / "configs/g3-level1-support-contact-execution-authorization-v12.json"
)


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


CORE = load_module(
    "g3_level1_support_contact_core_v11",
    ROOT / "tools/run_genesis_stack_bowls_scripted_g1.py",
)
WRAPPER = load_module(
    "g3_level1_support_contact_wrapper_v11",
    ROOT / "tools/run_genesis_stack_bowls_level1_support_contact.py",
)
DRIVER_PATH = (
    ROOT
    / ".ops/wip/g3-level1-support-contact-observability-20260728"
    / "run_g3_level1_support_contact_20260728_v11.py"
)
SUPERVISOR_PATH = (
    ROOT
    / ".ops/wip/g3-level1-support-contact-observability-20260728"
    / "run_g3_level1_support_contact_supervisor_20260728_v11.sh"
)
DRIVER = load_module("g3_level1_support_contact_driver_v11", DRIVER_PATH)


def make_observation(*, pre_pairs: int = 1, post_pairs: int = 1) -> dict:
    snapshots = []
    physics_steps = [10, 10, 80, 95, 120]
    for label, physics_step in zip(SNAPSHOT_LABELS, physics_steps):
        pair_count = (
            pre_pairs
            if label == "final_pre_release"
            else post_pairs
            if label == "immediate_post_release"
            else 0
        )
        pairs = [
            "bowl1:base_link <> bowl2:base_link"
            for _ in range(pair_count)
        ]
        snapshots.append(
            {
                "label": label,
                "physics_step": physics_step,
                "observer_policy_step_delta": 0,
                "observer_physics_step_delta": 0,
                "support_contact_query_applicable": True,
                "supporting_bowl_name": "bowl1",
                "support_contact_pairs": pairs,
                "support_contact_pair_count": len(pairs),
                "support_contact_diagnostics": {
                    "penetration": {"shape": [pair_count], "values": [0.0] * pair_count},
                    "force_a": {"shape": [pair_count, 3], "values": [0.0] * (3 * pair_count)},
                    "force_b": {"shape": [pair_count, 3], "values": [0.0] * (3 * pair_count)},
                    "normal": {"shape": [pair_count, 3], "values": [0.0] * (3 * pair_count)},
                    "position": {"shape": [pair_count, 3], "values": [0.0] * (3 * pair_count)},
                },
                "contact_cache_source_physics_step": physics_step,
                "contact_cache_semantics": "most_recent_scene_step",
            }
        )
    return {
        "observability_schema": "relative_pose_robot_and_support_contact_trace_v2",
        "level": 1,
        "bowl": "bowl2",
        "snapshots": snapshots,
    }


class SupportContactContractTests(unittest.TestCase):
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
        seed: int = 1602,
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
            CORE.G3_LEVEL1_SUPPORT_CONTACT_DIAGNOSTIC_SEEDS,
        )

    def test_first_eight_fresh_rll_seeds_recompute_exactly(self) -> None:
        panel = self.contract["diagnostic_panel"]
        rows = []
        for seed in range(*(
            panel["scan_range_inclusive"][0],
            panel["scan_range_inclusive"][1] + 1,
        )):
            reset = sorted(
                sample_source_reset_poses(seed=seed),
                key=lambda pose: pose.position_xyz_m[1],
            )
            if [
                arm_for_bowl_x(pose.position_xyz_m[0]) for pose in reset
            ] != panel["pattern"]:
                continue
            x, y, _ = reset[1].position_xyz_m
            rows.append((seed, x, y, math.hypot(x, y)))
            if len(rows) == 8:
                break
        self.assertEqual(
            tuple(row[0] for row in rows),
            CORE.G3_LEVEL1_SUPPORT_CONTACT_DIAGNOSTIC_SEEDS,
        )
        for seed, x, y, radius in rows:
            frozen = panel["seed_rows"][str(seed)]
            self.assertAlmostEqual(frozen["bowl2_xy_m"][0], x)
            self.assertAlmostEqual(frozen["bowl2_xy_m"][1], y)
            self.assertAlmostEqual(frozen["bowl2_radius_m"], radius)

    def test_exact_panel_is_authorized(self) -> None:
        for seed in CORE.G3_LEVEL1_SUPPORT_CONTACT_DIAGNOSTIC_SEEDS:
            self.assertEqual(
                self.validate(seed=seed),
                "level1_support_contact_observability",
            )

    def test_unknown_seed_gpu_capture_online_and_api_drift_fail(self) -> None:
        for values in (
            {"seed": 1603},
            {"backend": "cuda"},
            {"cuda_visible_devices": None},
            {"capture": True},
            {"generation_mode": "online"},
        ):
            with self.assertRaises(RuntimeError):
                self.validate(**values)
        drifted = copy.deepcopy(self.contract)
        drifted["genesis_contact_api"][
            "same_step_weld_registration_or_deletion_comparison_is_instantaneous"
        ] = True
        with self.assertRaises(RuntimeError):
            self.validate(contract=drifted)

    def test_authorization_forbids_downstream_mutation(self) -> None:
        drifted = copy.deepcopy(self.authorization)
        drifted["authorized_actions"]["change_controller"] = True
        with self.assertRaises(RuntimeError):
            self.validate(authorization=drifted)

    def test_core_contains_direct_entity_query_and_dynamic_identity(self) -> None:
        source = (
            ROOT / "tools/run_genesis_stack_bowls_scripted_g1.py"
        ).read_text(encoding="utf-8")
        self.assertEqual(
            source.count(
                "selected_bowl.get_contacts(\n"
                "                    with_entity=supporting_bowl"
            ),
            1,
        )
        self.assertIn('"support_contact_diagnostics"', source)
        self.assertIn('"contact_cache_source_physics_step"', source)
        self.assertIn(
            'level1_release_contract["work_package_id"]',
            source,
        )


class SupportContactAuditTests(unittest.TestCase):
    def test_valid_observation_reports_pre_and_post_support(self) -> None:
        result = validate_support_contact_observation(
            make_observation(pre_pairs=1, post_pairs=0)
        )
        self.assertTrue(result["pre_release_support_contact_present"])
        self.assertFalse(result["post_release_support_contact_present"])
        self.assertTrue(result["same_step_weld_snapshots_noncausal"])

    def test_entity_clock_cache_and_finite_fail_closed(self) -> None:
        mutations = []
        wrong_entity = make_observation()
        wrong_entity["snapshots"][2]["support_contact_pairs"] = [
            "bowl2:base_link <> bowl3:base_link"
        ]
        mutations.append(wrong_entity)
        clock = make_observation()
        clock["snapshots"][2]["observer_physics_step_delta"] = 1
        mutations.append(clock)
        cache = make_observation()
        cache["snapshots"][2]["contact_cache_source_physics_step"] = 79
        mutations.append(cache)
        nonfinite = make_observation()
        nonfinite["snapshots"][2]["support_contact_diagnostics"]["force_a"][
            "values"
        ] = [float("nan")]
        mutations.append(nonfinite)
        no_advanced_release = make_observation()
        no_advanced_release["snapshots"][3]["physics_step"] = 80
        no_advanced_release["snapshots"][3][
            "contact_cache_source_physics_step"
        ] = 80
        mutations.append(no_advanced_release)
        for observation in mutations:
            with self.assertRaises(ValueError):
                validate_support_contact_observation(observation)


class SupportContactWrapperTests(unittest.TestCase):
    def test_wrapper_forces_cpu_probe_and_frozen_contracts(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            urdf = root / "mantis.urdf"
            bowl_root = root / "bowl"
            bowl_urdf = (
                bowl_root / "urdf/robotwin_002_bowl_model3.urdf"
            )
            bowl_urdf.parent.mkdir(parents=True)
            for path in (
                urdf,
                bowl_urdf,
                ROOT / "configs/g3-left-interbowl-coupled-descent-dynamic-v3.json",
            ):
                if not path.exists():
                    path.write_text("x", encoding="utf-8")
            args = WRAPPER.build_parser().parse_args(
                [
                    str(urdf),
                    str(bowl_root),
                    "--ops-root",
                    str(root / "ops"),
                    "--run-id",
                    "support-v11",
                    "--seed",
                    "1602",
                ]
            )
            command = WRAPPER.build_core_command(
                args,
                python_executable="/usr/bin/python3",
            )
        self.assertIn("--backend", command)
        self.assertEqual(command[command.index("--backend") + 1], "cpu")
        self.assertEqual(
            command[command.index("--generation-mode") + 1],
            "probe",
        )
        self.assertNotIn("--capture", command)
        self.assertIn(str(CONTRACT_PATH), command)
        self.assertIn(str(AUTHORIZATION_PATH), command)


class SupportContactDriverTests(unittest.TestCase):
    def rows(
        self,
        *,
        drop_count: int = 1,
        stable_count: int = 7,
    ) -> list[dict]:
        classes = (
            ["release_drop_case"] * drop_count
            + ["stable_control"] * stable_count
        )
        return [
            {
                "seed": seed,
                "level1_observed": True,
                "observation_valid": True,
                "release_class": release_class,
                "safety_failure": False,
                "infrastructure_failure": False,
                "capture_artifact_count": 0,
            }
            for seed, release_class in zip(DRIVER.SEEDS, classes)
        ]

    def test_terminal_requires_exact_panel_contrast_and_clean_evidence(self) -> None:
        self.assertEqual(
            DRIVER.classify_terminal(self.rows()),
            "COMPLETE_LEVEL1_SUPPORT_CONTACT_OBSERVABILITY_ACCEPTED",
        )
        self.assertEqual(
            DRIVER.classify_terminal(
                self.rows(drop_count=0, stable_count=8)
            ),
            "COMPLETE_LEVEL1_SUPPORT_CONTACT_OBSERVABILITY_INCONCLUSIVE",
        )
        failed = self.rows()
        failed[0]["infrastructure_failure"] = True
        self.assertEqual(
            DRIVER.classify_terminal(failed),
            "FAILED_EVIDENCE_GATE",
        )
        unsafe = self.rows()
        unsafe[0]["safety_failure"] = True
        self.assertEqual(
            DRIVER.classify_terminal(unsafe),
            "COMPLETE_LEVEL1_SUPPORT_CONTACT_OBSERVABILITY_REJECTED",
        )

    def test_driver_pins_current_implementation(self) -> None:
        self.assertNotIn("REPLACE_", DRIVER_PATH.read_text(encoding="utf-8"))
        for relative, expected in DRIVER.EXPECTED_HASHES.items():
            self.assertEqual(sha256_file(ROOT / relative), expected)

    def test_driver_fails_fast_and_supervisor_is_cpu_no_clobber(self) -> None:
        driver_source = DRIVER_PATH.read_text(encoding="utf-8")
        self.assertIn('BATCH / "fail_fast.json"', driver_source)
        self.assertIn(
            'row.get("infrastructure_failure") is True',
            driver_source,
        )
        supervisor = SUPERVISOR_PATH.read_text(encoding="utf-8")
        self.assertIn("set -o noclobber", supervisor)
        self.assertIn('CUDA_VISIBLE_DEVICES=""', supervisor)
        self.assertIn("supervisor_final_evidence.SHA256SUMS", supervisor)
        self.assertNotIn("kill ", supervisor)
        self.assertNotIn("rm -", supervisor)


if __name__ == "__main__":
    unittest.main()
