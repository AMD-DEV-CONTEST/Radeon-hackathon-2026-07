from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from mantis_rocm_bridge.contracts import ContractError
from mantis_rocm_bridge.urdf_compiler import (
    BUNDLE_FILENAMES,
    compile_port_bundle,
    inspect_urdf,
    validate_semantic_sidecar,
    validate_task_pack,
    verify_bundle,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/urdf_compiler"
CLI = ROOT / "tools/compile_robot_urdf.py"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _hash_tree(path: Path) -> dict[str, str]:
    return {
        item.relative_to(path).as_posix(): hashlib.sha256(item.read_bytes()).hexdigest()
        for item in sorted(path.rglob("*"))
        if item.is_file()
    }


class UrdfInspectionTests(unittest.TestCase):
    def test_supported_fixture_morphologies(self) -> None:
        cases = {
            "single6.urdf": (1, [6]),
            "single7.urdf": (1, [7]),
            "bimanual7.urdf": (2, [7, 7]),
        }
        for filename, expected in cases.items():
            with self.subTest(filename=filename):
                result = inspect_urdf(FIXTURES / filename)
                morphology = result["morphology"]
                self.assertTrue(morphology["supported"])
                self.assertEqual(morphology["arm_count"], expected[0])
                self.assertEqual(morphology["dof_per_arm"], expected[1])

    def test_bimanual_fixture_excludes_shared_waist_from_arm_dof(self) -> None:
        result = inspect_urdf(FIXTURES / "bimanual7.urdf")
        selected = result["morphology"]["selected_candidate"]
        self.assertEqual(selected["shared_actuated_prefix"], ["waist_joint"])
        self.assertNotIn("waist_joint", selected["arms"][0]["joint_names"])
        self.assertNotIn("waist_joint", selected["arms"][1]["joint_names"])

    def test_inspection_does_not_persist_absolute_source_path(self) -> None:
        source = (FIXTURES / "single6.urdf").resolve()
        payload = json.dumps(inspect_urdf(source), sort_keys=True)
        self.assertNotIn(source.as_posix(), payload)
        self.assertEqual(set(inspect_urdf(source)["source_urdf"]), {"sha256", "size_bytes"})

    def test_inspection_is_deterministic(self) -> None:
        source = FIXTURES / "bimanual7.urdf"
        self.assertEqual(inspect_urdf(source), inspect_urdf(source))

    def test_unresolved_semantics_are_explicit(self) -> None:
        result = inspect_urdf(FIXTURES / "single6.urdf")
        unresolved = " ".join(result["unresolved_semantics"])
        for required in ("controller", "safety", "camera", "task", "gripper", "rights"):
            self.assertIn(required, unresolved)

    def test_malformed_xml_is_rejected(self) -> None:
        self._assert_invalid("<robot")

    def test_doctype_and_entity_are_rejected(self) -> None:
        self._assert_invalid(
            '<!DOCTYPE robot [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>'
            '<robot name="bad"><link name="base"/></robot>'
        )

    def test_duplicate_links_are_rejected(self) -> None:
        self._assert_invalid(
            '<robot name="bad"><link name="base"/><link name="base"/></robot>'
        )

    def test_duplicate_joints_are_rejected(self) -> None:
        self._assert_invalid(
            """
            <robot name="bad">
              <link name="a"/><link name="b"/><link name="c"/>
              <joint name="j" type="fixed"><parent link="a"/><child link="b"/></joint>
              <joint name="j" type="fixed"><parent link="b"/><child link="c"/></joint>
            </robot>
            """
        )

    def test_disconnected_links_are_rejected(self) -> None:
        self._assert_invalid('<robot name="bad"><link name="a"/><link name="b"/></robot>')

    def test_cyclic_topology_is_rejected(self) -> None:
        self._assert_invalid(
            """
            <robot name="bad">
              <link name="a"/><link name="b"/>
              <joint name="ab" type="fixed"><parent link="a"/><child link="b"/></joint>
              <joint name="ba" type="fixed"><parent link="b"/><child link="a"/></joint>
            </robot>
            """
        )

    def test_parallel_parent_topology_is_rejected(self) -> None:
        self._assert_invalid(
            """
            <robot name="bad">
              <link name="a"/><link name="b"/><link name="c"/>
              <joint name="ac" type="fixed"><parent link="a"/><child link="c"/></joint>
              <joint name="bc" type="fixed"><parent link="b"/><child link="c"/></joint>
            </robot>
            """
        )

    def test_floating_joint_is_rejected(self) -> None:
        self._assert_invalid(
            """
            <robot name="bad">
              <link name="a"/><link name="b"/>
              <joint name="floating" type="floating">
                <parent link="a"/><child link="b"/>
              </joint>
            </robot>
            """
        )

    def test_bad_joint_limit_is_rejected(self) -> None:
        self._assert_invalid(
            """
            <robot name="bad">
              <link name="a"/><link name="b"/>
              <joint name="j" type="revolute">
                <parent link="a"/><child link="b"/>
                <limit lower="2" upper="-2" effort="1" velocity="1"/>
              </joint>
            </robot>
            """
        )

    def test_cyclic_mimic_is_rejected(self) -> None:
        self._assert_invalid(
            """
            <robot name="bad">
              <link name="a"/><link name="b"/><link name="c"/>
              <joint name="j1" type="continuous">
                <parent link="a"/><child link="b"/><limit effort="1" velocity="1"/>
                <mimic joint="j2"/>
              </joint>
              <joint name="j2" type="continuous">
                <parent link="b"/><child link="c"/><limit effort="1" velocity="1"/>
                <mimic joint="j1"/>
              </joint>
            </robot>
            """
        )

    def _assert_invalid(self, content: str) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "bad.urdf"
            path.write_text(content, encoding="utf-8")
            with self.assertRaises(ContractError):
                inspect_urdf(path)


class UrdfCompilerContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.urdf = FIXTURES / "single6.urdf"
        self.sidecar_path = FIXTURES / "single6-semantics.json"
        self.task_path = FIXTURES / "task.json"
        self.ir = inspect_urdf(self.urdf)
        self.sidecar = _load(self.sidecar_path)
        self.task = _load(self.task_path)

    def test_checked_in_semantics_and_task_validate(self) -> None:
        semantics = validate_semantic_sidecar(self.sidecar, self.ir)
        task = validate_task_pack(self.task)
        self.assertEqual(semantics["robot_id"], "fixture-single6")
        self.assertEqual(task["act"]["evaluation_seeds"], self.task["act"]["evaluation_seeds"])

    def test_sidecar_rejects_unknown_arm_chain(self) -> None:
        broken = copy.deepcopy(self.sidecar)
        broken["arms"][0]["joint_names"][-1] = "joint5"
        with self.assertRaises(ContractError):
            validate_semantic_sidecar(broken, self.ir)

    def test_sidecar_rejects_wrong_end_effector(self) -> None:
        broken = copy.deepcopy(self.sidecar)
        broken["arms"][0]["end_effector_link"] = "link5"
        with self.assertRaises(ContractError):
            validate_semantic_sidecar(broken, self.ir)

    def test_sidecar_rejects_missing_safety_semantics(self) -> None:
        broken = copy.deepcopy(self.sidecar)
        del broken["safety"]["emergency_stop"]
        with self.assertRaises(ContractError):
            validate_semantic_sidecar(broken, self.ir)

    def test_task_rejects_nonperfect_expert_dataset(self) -> None:
        broken = copy.deepcopy(self.task)
        broken["dataset"]["expert_success_fraction"] = 0.9
        with self.assertRaises(ContractError):
            validate_task_pack(broken)

    def test_task_requires_exactly_ten_unique_g3_seeds(self) -> None:
        broken = copy.deepcopy(self.task)
        broken["act"]["evaluation_seeds"][-1] = broken["act"]["evaluation_seeds"][0]
        with self.assertRaises(ContractError):
            validate_task_pack(broken)

    def test_compile_creates_exact_verified_eleven_file_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "bundle"
            manifest = compile_port_bundle(
                self.urdf, self.sidecar_path, self.task_path, output
            )
            self.assertEqual(
                sorted(item.name for item in output.iterdir()),
                sorted(BUNDLE_FILENAMES),
            )
            self.assertEqual(manifest["file_count_excluding_manifest"], 10)
            self.assertEqual(verify_bundle(output)["file_count"], 11)
            self.assertIn("genesis-port-spec.json", BUNDLE_FILENAMES)
            self.assertNotIn("genesis-adapter.json", BUNDLE_FILENAMES)

    def test_generated_runtime_fails_on_hash_mismatch_before_genesis_import(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "bundle"
            compile_port_bundle(self.urdf, self.sidecar_path, self.task_path, output)
            spec_path = output / "genesis-port-spec.json"
            spec = _load(spec_path)
            spec["urdf_sha256"] = "0" * 64
            spec_path.write_text(
                json.dumps(spec, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            receipt = Path(temporary) / "receipt.json"
            process = subprocess.run(
                [
                    sys.executable,
                    str(output / "run-genesis-port.py"),
                    "--spec",
                    str(spec_path),
                    "--urdf",
                    str(self.urdf),
                    "--backend",
                    "cpu",
                    "--output",
                    str(receipt),
                ],
                cwd=ROOT,
                env={**os.environ, "PYTHONPATH": ""},
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(process.returncode, 2)
            self.assertIn("URDF SHA-256 disagrees", process.stderr)
            self.assertNotIn("ModuleNotFoundError", process.stderr)
            self.assertFalse(receipt.exists())

    def test_generated_runtime_loads_maps_and_steps_with_fake_genesis(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "bundle"
            compile_port_bundle(self.urdf, self.sidecar_path, self.task_path, output)
            fake = root / "fake"
            fake.mkdir()
            (fake / "genesis.py").write_text(
                """
__version__ = "fake-test"
cpu = object()

def init(**kwargs):
    assert kwargs["backend"] is cpu

class _SimOptions:
    def __init__(self, dt):
        self.dt = dt

class _Options:
    SimOptions = _SimOptions

options = _Options()

class _URDF:
    def __init__(self, file, fixed):
        assert fixed is True
        self.file = file

class _Morphs:
    URDF = _URDF

morphs = _Morphs()

class _Joint:
    def __init__(self, index):
        self.dofs_idx_local = [index]

class _Robot:
    def __init__(self):
        self._joints = {}

    def get_joint(self, name):
        if name not in self._joints:
            self._joints[name] = _Joint(len(self._joints))
        return self._joints[name]

    def get_dofs_position(self, dofs_idx_local):
        return [0.0 for _ in dofs_idx_local]

class Scene:
    def __init__(self, sim_options, show_viewer):
        assert show_viewer is False
        self.robot = _Robot()
        self.steps = 0

    def add_entity(self, morph):
        return self.robot

    def build(self):
        return None

    def step(self):
        self.steps += 1
""".lstrip(),
                encoding="utf-8",
            )
            receipt_path = root / "receipt.json"
            process = subprocess.run(
                [
                    sys.executable,
                    str(output / "run-genesis-port.py"),
                    "--urdf",
                    str(self.urdf),
                    "--backend",
                    "cpu",
                    "--steps",
                    "3",
                    "--output",
                    str(receipt_path),
                ],
                cwd=ROOT,
                env={**os.environ, "PYTHONPATH": str(fake)},
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(process.returncode, 0, process.stderr)
            receipt = _load(receipt_path)
            self.assertEqual(receipt["status"], "runtime_port_verified")
            self.assertEqual(receipt["backend_active"], "cpu")
            self.assertEqual(receipt["mapped_dof_count"], 6)
            self.assertFalse(receipt["controller_commands_issued"])
            self.assertFalse(receipt["amd_runtime_claim"])

    def test_rocm_tuning_plan_is_morphology_derived_and_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "bundle"
            compile_port_bundle(self.urdf, self.sidecar_path, self.task_path, output)
            plan = _load(output / "rocm-tuning-plan.json")
            profile = _load(output / "robot-port-profile.json")
            quality = _load(output / "quality-gates.json")
            self.assertEqual(
                plan["morphology"]["policy_state_dimension"],
                profile["policy_interface"]["state_dimension"],
            )
            self.assertEqual(
                plan["morphology"]["policy_action_dimension"],
                profile["policy_interface"]["action_dimension"],
            )
            self.assertEqual(
                plan["maximum_promotion_state"], "ROCM_TUNING_MEASURED"
            )
            self.assertFalse(plan["amd_deployable"])
            self.assertFalse(quality["runtime_port_gate"]["passed"])
            self.assertFalse(quality["rocm_tuning_gate"]["passed"])

    def test_bundle_is_deterministic_across_output_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            first = Path(temporary) / "first"
            second = Path(temporary) / "second"
            compile_port_bundle(self.urdf, self.sidecar_path, self.task_path, first)
            compile_port_bundle(self.urdf, self.sidecar_path, self.task_path, second)
            self.assertEqual(_hash_tree(first), _hash_tree(second))

    def test_compile_refuses_existing_output_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "bundle"
            output.mkdir()
            sentinel = output / "keep.txt"
            sentinel.write_text("preserve", encoding="utf-8")
            before = _hash_tree(output)
            with self.assertRaises(ContractError):
                compile_port_bundle(
                    self.urdf, self.sidecar_path, self.task_path, output
                )
            self.assertEqual(_hash_tree(output), before)

    def test_failed_compile_publishes_no_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            broken_sidecar = Path(temporary) / "broken.json"
            broken_sidecar.write_text("{}", encoding="utf-8")
            output = Path(temporary) / "bundle"
            with self.assertRaises(ContractError):
                compile_port_bundle(self.urdf, broken_sidecar, self.task_path, output)
            self.assertFalse(output.exists())
            self.assertEqual(list(Path(temporary).glob(".bundle.partial-*")), [])

    def test_manifest_tamper_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "bundle"
            compile_port_bundle(self.urdf, self.sidecar_path, self.task_path, output)
            target = output / "quality-gates.json"
            target.write_text(target.read_text(encoding="utf-8") + "\n", encoding="utf-8")
            with self.assertRaises(ContractError):
                verify_bundle(output)

    def test_policy_dimensions_are_morphology_independent_task_space(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            single = Path(temporary) / "single"
            bimanual = Path(temporary) / "bimanual"
            compile_port_bundle(self.urdf, self.sidecar_path, self.task_path, single)
            compile_port_bundle(
                FIXTURES / "bimanual7.urdf",
                FIXTURES / "bimanual7-semantics.json",
                self.task_path,
                bimanual,
            )
            single_profile = _load(single / "robot-port-profile.json")
            bimanual_profile = _load(bimanual / "robot-port-profile.json")
            self.assertEqual(
                single_profile["policy_interface"]["action_dimension"], 6
            )
            self.assertEqual(
                bimanual_profile["policy_interface"]["action_dimension"], 12
            )
            self.assertFalse(
                bimanual_profile["policy_interface"][
                    "native_joint_action_head_reuse_allowed"
                ]
            )

    def test_act_quality_gate_is_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "bundle"
            compile_port_bundle(self.urdf, self.sidecar_path, self.task_path, output)
            quality = _load(output / "quality-gates.json")
            self.assertEqual(quality["closedloop_gate"]["g3_minimum_successes"], 6)
            self.assertEqual(quality["closedloop_gate"]["g3_maximum_safety_failures"], 0)
            self.assertEqual(quality["closedloop_gate"]["competitive_target_successes"], 8)
            self.assertFalse(quality["amd_deployable"])
            self.assertEqual(
                quality["existing_mantis_baseline"]["status"],
                "ACT_OPENLOOP_PASS_ONLY",
            )
            self.assertEqual(quality["existing_mantis_baseline"]["successes"], 0)

    def test_cli_inspect_is_read_only_and_structured(self) -> None:
        before = _hash_tree(FIXTURES)
        process = subprocess.run(
            [sys.executable, str(CLI), "inspect", str(self.urdf)],
            cwd=ROOT,
            env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(json.loads(process.stdout)["kind"], "embodiment_ir")
        self.assertEqual(_hash_tree(FIXTURES), before)

    def test_cli_error_is_json_and_nonzero(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            bad = Path(temporary) / "bad.urdf"
            bad.write_text("<not-robot/>", encoding="utf-8")
            process = subprocess.run(
                [sys.executable, str(CLI), "inspect", str(bad)],
                cwd=ROOT,
                env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(process.returncode, 2)
            error = json.loads(process.stderr)
            self.assertFalse(error["valid"])
            self.assertEqual(error["error_type"], "ContractError")


if __name__ == "__main__":
    unittest.main()
