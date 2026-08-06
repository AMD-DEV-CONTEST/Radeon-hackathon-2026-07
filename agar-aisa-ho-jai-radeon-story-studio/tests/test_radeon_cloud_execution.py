from __future__ import annotations

import json
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.episode_factory.radeon_cloud_execution import (
    JOB_SCHEMA,
    RadeonCloudJob,
    build_cloud_package,
    execute_cloud_package,
    inspect_cloud_package,
    verify_cloud_result,
)
from tools.episode_factory.radeon_runtime_discovery import (
    RadeonGpuObservation,
    RadeonRuntimeObservation,
    preflight_radeon_runtime,
)
from tools.episode_factory.rendering_engine import ExecutionPlan


class RadeonCloudExecutionTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.plan = ExecutionPlan(
            specification_id="a" * 64,
            backend="radeon-cloud",
            model={"id": "test"},
            resolved_request={"prompt": "frame", "seed": 7},
            output_contract={"formats": ["txt"]},
        )
        self.script = self.root / "render.py"
        self.script.write_text(
            "from pathlib import Path\n"
            "import argparse\n"
            "p=argparse.ArgumentParser();"
            "p.add_argument('--plan');p.add_argument('--output');a=p.parse_args()\n"
            "o=Path(a.output);o.mkdir(parents=True,exist_ok=True);"
            "(o/'frame.txt').write_text('radeon-cloud\\n')\n",
            encoding="utf-8",
        )
        self.job = RadeonCloudJob.from_mapping(
            {
                "schema_version": JOB_SCHEMA,
                "argv": [
                    "python3",
                    "render.py",
                    "--plan",
                    "../execution-plan.json",
                    "--output",
                    "../outputs",
                ],
                "environment": {"PYTHONHASHSEED": "0"},
                "working_directory": "payload",
                "output_paths": ["outputs"],
                "timeout_seconds": 10,
            }
        )

    def tearDown(self):
        self.temporary.cleanup()

    def package(self, name="package.tar.gz"):
        return build_cloud_package(
            execution_plan=self.plan,
            job=self.job,
            payload_files={"payload/render.py": self.script},
            destination=self.root / name,
        )

    def test_job_identity_is_deterministic(self):
        same = RadeonCloudJob.from_mapping(self.job.as_dict())
        self.assertEqual(self.job.job_id, same.job_id)

    def test_package_bytes_are_reproducible(self):
        first = self.package("first.tar.gz")
        second = self.package("second.tar.gz")
        self.assertEqual(first.read_bytes(), second.read_bytes())

    def test_package_inspection_verifies_all_entries(self):
        summary = inspect_cloud_package(self.package())
        self.assertEqual(summary["plan_id"], self.plan.plan_id)
        self.assertEqual(summary["job_id"], self.job.job_id)
        self.assertEqual(summary["entries"], 3)

    def test_absolute_payload_path_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "safe relative"):
            build_cloud_package(
                execution_plan=self.plan,
                job=self.job,
                payload_files={"/payload/render.py": self.script},
                destination=self.root / "bad.tar.gz",
            )

    def test_payload_must_live_under_payload_directory(self):
        with self.assertRaisesRegex(ValueError, "under payload"):
            build_cloud_package(
                execution_plan=self.plan,
                job=self.job,
                payload_files={"render.py": self.script},
                destination=self.root / "bad.tar.gz",
            )

    def test_tampered_package_is_rejected(self):
        package = self.package()
        extract = self.root / "extract"
        extract.mkdir()
        with tarfile.open(package, "r:gz") as archive:
            archive.extractall(extract, filter="data")
        (extract / "payload" / "render.py").write_text("tampered\n")
        tampered = self.root / "tampered.tar.gz"
        with tarfile.open(tampered, "w:gz") as archive:
            for path in sorted(extract.rglob("*")):
                if path.is_file():
                    archive.add(path, path.relative_to(extract).as_posix())
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            inspect_cloud_package(tampered)

    def test_cloud_runner_produces_verified_result(self):
        result_file = execute_cloud_package(
            self.package(),
            result_directory=self.root / "result",
            require_radeon=False,
        )
        result = verify_cloud_result(
            result_file,
            expected_plan_id=self.plan.plan_id,
        )
        self.assertEqual(result.status, "succeeded")
        self.assertEqual(len(result.outputs), 1)

    def test_radeon_preflight_identity_is_recorded_in_runtime_evidence(self):
        observation = RadeonRuntimeObservation(
            kernel_release="6.10.0-test",
            operating_system={"id": "ubuntu"},
            amdgpu_driver_loaded=True,
            amdgpu_driver_version="6.10.0-test",
            rocm_version="7.0.0",
            hip_version="7.0.0",
            rocminfo_available=True,
            rocm_smi_available=True,
            hipcc_available=True,
            amd_pci_devices=("0000:03:00.0 AMD Radeon Test GPU",),
            gpus=(
                RadeonGpuObservation(
                    architecture="gfx1100",
                    marketing_name="AMD Radeon Test GPU",
                    pci_address="0000:03:00.0",
                    vram_bytes=17163091968,
                ),
            ),
            command_evidence={},
        )
        expected_preflight_id = preflight_radeon_runtime(
            observation
        ).as_dict()["preflight_id"]

        with patch(
            "tools.episode_factory.radeon_cloud_execution."
            "discover_radeon_runtime",
            return_value=observation,
        ):
            result_file = execute_cloud_package(
                self.package(),
                result_directory=self.root / "radeon-result",
            )

        result = verify_cloud_result(
            result_file,
            expected_plan_id=self.plan.plan_id,
        )
        self.assertEqual(result.status, "succeeded")
        self.assertTrue(result.evidence["runtime"]["required"])
        self.assertTrue(result.evidence["runtime"]["ready"])
        self.assertEqual(
            result.evidence["runtime"]["preflight_id"],
            expected_preflight_id,
        )

    def test_result_artifact_tampering_is_detected(self):
        result_file = execute_cloud_package(
            self.package(),
            result_directory=self.root / "result",
            require_radeon=False,
        )
        payload = json.loads(result_file.read_text())
        artifact = self.root / "result" / payload["execution_result"]["outputs"][0]["path"]
        artifact.write_text("tampered\n")
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            verify_cloud_result(result_file)

    def test_nonzero_command_yields_failed_execution_result(self):
        failing = RadeonCloudJob.from_mapping(
            {
                **self.job.as_dict(),
                "argv": ["python3", "-c", "raise SystemExit(7)"],
            }
        )
        package = build_cloud_package(
            execution_plan=self.plan,
            job=failing,
            payload_files={"payload/render.py": self.script},
            destination=self.root / "failing.tar.gz",
        )
        result_file = execute_cloud_package(
            package,
            result_directory=self.root / "failed-result",
            require_radeon=False,
        )
        result = verify_cloud_result(result_file)
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error["code"], "nonzero-exit")

    def test_missing_declared_output_fails_closed(self):
        missing = RadeonCloudJob.from_mapping(
            {
                **self.job.as_dict(),
                "output_paths": ["missing"],
            }
        )
        package = build_cloud_package(
            execution_plan=self.plan,
            job=missing,
            payload_files={"payload/render.py": self.script},
            destination=self.root / "missing.tar.gz",
        )
        with self.assertRaisesRegex(RuntimeError, "declared output is missing"):
            execute_cloud_package(
                package,
                result_directory=self.root / "missing-result",
                require_radeon=False,
            )


if __name__ == "__main__":
    unittest.main()
