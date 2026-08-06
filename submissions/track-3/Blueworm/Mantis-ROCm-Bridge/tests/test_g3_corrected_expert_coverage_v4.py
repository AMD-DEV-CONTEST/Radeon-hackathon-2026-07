from __future__ import annotations

import importlib.util
import json
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
CONTRACT_PATH = ROOT / "configs/g3-corrected-expert-coverage-v4.json"
AUTHORIZATION_PATH = (
    ROOT / "configs/g3-corrected-expert-execution-authorization-v5.json"
)


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


CORE = load_module(
    "g3_corrected_expert_core_v4",
    ROOT / "tools/run_genesis_stack_bowls_scripted_g1.py",
)
WRAPPER = load_module(
    "g3_corrected_expert_wrapper_v4",
    ROOT / "tools/run_genesis_stack_bowls_corrected_expert.py",
)
DIAGNOSTIC_DRIVER_PATH = (
    ROOT
    / ".ops/wip/g3-corrected-expert-coverage-20260728"
    / "run_g3_corrected_expert_diagnostic_20260728_v4.py"
)
DIAGNOSTIC_SUPERVISOR_PATH = (
    ROOT
    / ".ops/wip/g3-corrected-expert-coverage-20260728"
    / "run_g3_corrected_expert_diagnostic_supervisor_20260728_v4.sh"
)
DIAGNOSTIC_DRIVER = load_module(
    "g3_corrected_expert_diagnostic_driver_v4",
    DIAGNOSTIC_DRIVER_PATH,
)


class CorrectedExpertCoverageContractTests(unittest.TestCase):
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
        seed: int,
        generation_mode: str,
        capture: bool,
        backend: str = "cpu",
        cuda_visible_devices: str | None = "",
        contract: dict | None = None,
        authorization: dict | None = None,
    ) -> str:
        return CORE.validate_corrected_expert_execution_contract(
            contract or self.contract,
            authorization or self.authorization,
            planning_contract_sha256=self.contract_sha256,
            seed=seed,
            generation_mode=generation_mode,
            capture=capture,
            backend=backend,
            cuda_visible_devices=cuda_visible_devices,
        )

    def test_frozen_diagnostic_and_collection_seed_orders(self) -> None:
        policy = self.contract["seed_policy"]
        self.assertEqual(
            tuple(policy["diagnostic_panel"]["seeds_in_order"]),
            CORE.G3_CORRECTED_EXPERT_DIAGNOSTIC_SEEDS,
        )
        self.assertEqual(
            tuple(policy["collection_panel"]["seeds_in_order"]),
            CORE.G3_CORRECTED_EXPERT_COLLECTION_SEEDS,
        )

    def test_seed_patterns_recompute_exactly(self) -> None:
        policy = self.contract["seed_policy"]
        for panel_name in ("diagnostic_panel", "collection_panel"):
            panel = policy[panel_name]
            for seed in panel["seeds_in_order"]:
                pattern = [
                    arm_for_bowl_x(pose.position_xyz_m[0])
                    for pose in sample_source_reset_poses(seed=seed)
                ]
                self.assertEqual(pattern, panel["patterns"][str(seed)])

    def test_diagnostic_requires_probe_without_capture(self) -> None:
        for seed in CORE.G3_CORRECTED_EXPERT_DIAGNOSTIC_SEEDS:
            self.assertEqual(
                self.validate(
                    seed=seed,
                    generation_mode="probe",
                    capture=False,
                ),
                "diagnostic",
            )
        with self.assertRaises(RuntimeError):
            self.validate(
                seed=CORE.G3_CORRECTED_EXPERT_DIAGNOSTIC_SEEDS[0],
                generation_mode="replay",
                capture=True,
            )

    def test_collection_probe_and_capture_are_separate(self) -> None:
        seed = CORE.G3_CORRECTED_EXPERT_COLLECTION_SEEDS[0]
        self.assertEqual(
            self.validate(
                seed=seed,
                generation_mode="probe",
                capture=False,
            ),
            "collection_probe",
        )
        self.assertEqual(
            self.validate(
                seed=seed,
                generation_mode="replay",
                capture=True,
            ),
            "collection_capture",
        )
        with self.assertRaises(RuntimeError):
            self.validate(
                seed=seed,
                generation_mode="replay",
                capture=False,
            )

    def test_unknown_seed_gpu_and_online_modes_fail_closed(self) -> None:
        for kwargs in (
            {"seed": 1401, "generation_mode": "probe", "capture": False},
            {
                "seed": CORE.G3_CORRECTED_EXPERT_COLLECTION_SEEDS[0],
                "generation_mode": "online",
                "capture": False,
            },
            {
                "seed": CORE.G3_CORRECTED_EXPERT_COLLECTION_SEEDS[0],
                "generation_mode": "probe",
                "capture": False,
                "backend": "cuda",
            },
            {
                "seed": CORE.G3_CORRECTED_EXPERT_COLLECTION_SEEDS[0],
                "generation_mode": "probe",
                "capture": False,
                "cuda_visible_devices": None,
            },
        ):
            with self.assertRaises(RuntimeError):
                self.validate(**kwargs)

    def test_authorization_hash_and_export_boundary_fail_closed(self) -> None:
        drifted = json.loads(json.dumps(self.authorization))
        drifted["planning_contract_sha256"] = "0" * 64
        with self.assertRaises(RuntimeError):
            self.validate(
                seed=CORE.G3_CORRECTED_EXPERT_DIAGNOSTIC_SEEDS[0],
                generation_mode="probe",
                capture=False,
                authorization=drifted,
            )
        drifted = json.loads(json.dumps(self.authorization))
        drifted["authorized_actions"]["train"] = True
        with self.assertRaises(RuntimeError):
            self.validate(
                seed=CORE.G3_CORRECTED_EXPERT_DIAGNOSTIC_SEEDS[0],
                generation_mode="probe",
                capture=False,
                authorization=drifted,
            )

    def test_core_source_receipts_both_contract_hashes(self) -> None:
        source = (
            ROOT / "tools/run_genesis_stack_bowls_scripted_g1.py"
        ).read_text(encoding="utf-8")
        self.assertIn('"corrected_expert_contract_sha256"', source)
        self.assertIn('"corrected_expert_authorization_sha256"', source)
        self.assertIn('"corrected_expert_phase"', source)


class CorrectedExpertWrapperTests(unittest.TestCase):
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

    def parse(
        self,
        paths: dict[str, Path],
        *,
        seed: int,
        phase: str,
        replay_plan: Path | None = None,
    ):
        values = [
            str(paths["mantis"]),
            str(paths["bowl"]),
            "--ops-root",
            str(paths["ops"]),
            "--run-id",
            f"run-{seed}-{phase}",
            "--seed",
            str(seed),
            "--phase",
            phase,
            "--core-tool",
            str(paths["core"]),
            "--r3-contract",
            str(paths["r3"]),
            "--corrected-contract",
            str(paths["contract"]),
            "--execution-authorization",
            str(paths["authorization"]),
        ]
        if replay_plan is not None:
            values.extend(["--replay-plan", str(replay_plan)])
        return WRAPPER.build_parser().parse_args(values)

    def test_diagnostic_command_forces_schedule_and_contracts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self.make_paths(Path(tmp))
            args = self.parse(paths, seed=1285, phase="diagnostic")
            command = WRAPPER.build_core_command(
                args,
                python_executable="/python",
            )
            self.assertIn("--generation-mode", command)
            self.assertEqual(
                command[command.index("--generation-mode") + 1],
                "probe",
            )
            self.assertIn("coupled_descent_slerp", command)
            self.assertIn("--corrected-expert-contract", command)
            self.assertIn("--corrected-expert-authorization", command)
            self.assertNotIn("--capture", command)

    def test_capture_command_requires_frozen_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self.make_paths(Path(tmp))
            plan = Path(tmp) / "replay_plan.json"
            plan.write_text("{}", encoding="utf-8")
            args = self.parse(
                paths,
                seed=1251,
                phase="capture",
                replay_plan=plan,
            )
            command = WRAPPER.build_core_command(args)
            self.assertEqual(
                command[command.index("--generation-mode") + 1],
                "replay",
            )
            self.assertIn("--replay-plan", command)
            self.assertIn("--capture", command)

    def test_phase_and_seed_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self.make_paths(Path(tmp))
            args = self.parse(paths, seed=1285, phase="probe")
            with self.assertRaises(ValueError):
                WRAPPER.build_core_command(args)


class CorrectedExpertDiagnosticDriverTests(unittest.TestCase):
    def row(self, seed: int, *, success: bool = True) -> dict:
        return {
            "seed": seed,
            "transition_receipt_valid": True,
            "corrected_transition_collision": False,
            "safety_failure": False,
            "infrastructure_failure": False,
            "capture_artifact_count": 0,
            "full_strict_success": success,
        }

    def test_pinned_hashes_preserve_predecessor_identity(self) -> None:
        for relative, expected in DIAGNOSTIC_DRIVER.EXPECTED_HASHES.items():
            if relative == DIAGNOSTIC_DRIVER.CORE_RELATIVE:
                self.assertEqual(
                    expected,
                    "24c9708e3f4c102f660bc6f4445adbe4865559dcf5b2a163e351ce168560ac5e",
                )
            else:
                self.assertEqual(sha256_file(ROOT / relative), expected)

    def test_diagnostic_terminal_requires_three_full_successes(self) -> None:
        rows = [
            self.row(seed, success=index < 3)
            for index, seed in enumerate(DIAGNOSTIC_DRIVER.SEEDS)
        ]
        self.assertEqual(
            DIAGNOSTIC_DRIVER.classify_terminal(rows),
            "COMPLETE_CORRECTED_EXPERT_DIAGNOSTIC_ACCEPTED",
        )
        rows[2]["full_strict_success"] = False
        self.assertEqual(
            DIAGNOSTIC_DRIVER.classify_terminal(rows),
            "COMPLETE_CORRECTED_EXPERT_COVERAGE_REJECTED",
        )

    def test_infrastructure_and_capture_fail_evidence_gate(self) -> None:
        rows = [self.row(seed) for seed in DIAGNOSTIC_DRIVER.SEEDS]
        rows[0]["infrastructure_failure"] = True
        self.assertEqual(
            DIAGNOSTIC_DRIVER.classify_terminal(rows),
            "FAILED_EVIDENCE_GATE",
        )
        rows = [self.row(seed) for seed in DIAGNOSTIC_DRIVER.SEEDS]
        rows[0]["capture_artifact_count"] = 1
        self.assertEqual(
            DIAGNOSTIC_DRIVER.classify_terminal(rows),
            "FAILED_EVIDENCE_GATE",
        )

    def test_failure_categories_are_bounded(self) -> None:
        self.assertEqual(
            DIAGNOSTIC_DRIVER.failure_category(
                "bowl3 placement misses level 2: position=[]"
            ),
            "downstream_placement_predicate",
        )
        self.assertEqual(
            DIAGNOSTIC_DRIVER.failure_category(
                "strict terminal stability did not reach the required 12"
            ),
            "strict_terminal_stability",
        )
        self.assertEqual(
            DIAGNOSTIC_DRIVER.failure_category("physics divergence"),
            "safety",
        )
        self.assertEqual(
            DIAGNOSTIC_DRIVER.failure_category("unexpected"),
            "unclassified_failure",
        )

    def test_write_exclusive_refuses_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "evidence.txt"
            DIAGNOSTIC_DRIVER.write_exclusive(path, "first\n")
            with self.assertRaises(FileExistsError):
                DIAGNOSTIC_DRIVER.write_exclusive(path, "second\n")
            self.assertEqual(path.read_text(encoding="utf-8"), "first\n")

    def test_supervisor_is_cpu_isolated_and_non_destructive(self) -> None:
        source = DIAGNOSTIC_SUPERVISOR_PATH.read_text(encoding="utf-8")
        self.assertIn("set -o noclobber", source)
        self.assertIn('CUDA_VISIBLE_DEVICES=""', source)
        self.assertIn("PACKAGE.SHA256SUMS", source)
        self.assertIn("supervisor_final_evidence.SHA256SUMS", source)
        self.assertNotIn("kill ", source)
        self.assertNotIn("rm -", source)


if __name__ == "__main__":
    unittest.main()
