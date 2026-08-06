from __future__ import annotations

import unittest
from pathlib import Path
from typing import Sequence
from unittest.mock import patch

from tools.episode_factory.radeon_runtime_discovery import (
    CommandResult,
    discover_radeon_runtime,
    execution_contract_fragment,
    preflight_radeon_runtime,
)


class FakeRunner:
    def __init__(self, responses):
        self.responses = responses

    def run(self, argv: Sequence[str]) -> CommandResult:
        key = tuple(argv)
        return self.responses.get(
            key,
            CommandResult(
                argv=key,
                available=False,
                returncode=None,
                stdout="",
                stderr="missing fixture",
            ),
        )


def result(argv, stdout="", returncode=0, available=True):
    return CommandResult(
        argv=tuple(argv),
        available=available,
        returncode=returncode,
        stdout=stdout,
        stderr="",
    )


class RadeonRuntimeDiscoveryTest(unittest.TestCase):
    def ready_runner(self):
        return FakeRunner(
            {
                ("lspci", "-D", "-nn"): result(
                    ("lspci", "-D", "-nn"),
                    "0000:03:00.0 VGA compatible controller: "
                    "Advanced Micro Devices, Inc. [AMD/ATI] Test GPU\n",
                ),
                ("rocminfo",): result(
                    ("rocminfo",),
                    """
Agent 2
  Name:                    gfx1100
  Marketing Name:          AMD Radeon Test GPU
  BDFID:                   0000:03:00.0
""",
                ),
                (
                    "rocm-smi",
                    "--showproductname",
                    "--showmeminfo",
                    "vram",
                ): result(
                    (
                        "rocm-smi",
                        "--showproductname",
                        "--showmeminfo",
                        "vram",
                    ),
                    "VRAM Total Memory (B): 17163091968\n",
                ),
                ("hipcc", "--version"): result(
                    ("hipcc", "--version"),
                    "HIP version: 7.0.0\n",
                ),
                ("modinfo", "-F", "version", "amdgpu"): result(
                    ("modinfo", "-F", "version", "amdgpu"),
                    "6.10.0-test\n",
                ),
                ("lsmod",): result(
                    ("lsmod",),
                    "Module Size Used by\namdgpu 123456 1\n",
                ),
            }
        )

    def reader(self, path: Path):
        values = {
            "/opt/rocm/.info/version": "7.0.0\n",
            "/etc/os-release": (
                'ID="ubuntu"\n'
                'VERSION_ID="24.04"\n'
                'PRETTY_NAME="Ubuntu 24.04"\n'
            ),
        }
        return values.get(str(path))

    def test_discovery_is_deterministic(self):
        first = discover_radeon_runtime(
            runner=self.ready_runner(),
            read_file=self.reader,
            kernel_release="6.10.0-test",
        )
        second = discover_radeon_runtime(
            runner=self.ready_runner(),
            read_file=self.reader,
            kernel_release="6.10.0-test",
        )

        self.assertEqual(first.observation_id, second.observation_id)
        self.assertEqual(first.gpus[0].architecture, "gfx1100")
        self.assertEqual(first.gpus[0].vram_bytes, 17163091968)

    def test_preflight_passes_for_complete_runtime(self):
        observation = discover_radeon_runtime(
            runner=self.ready_runner(),
            read_file=self.reader,
            kernel_release="6.10.0-test",
        )
        preflight = preflight_radeon_runtime(observation)

        self.assertTrue(preflight.ready)
        fragment = execution_contract_fragment(observation)
        self.assertEqual(fragment["gpu_arch"], "gfx1100")
        self.assertEqual(fragment["rocm_version"], "7.0.0")
        self.assertIn(
            "runtime_observation_id",
            fragment["environment"],
        )

    def test_container_detects_amdgpu_from_sysfs_without_lsmod(self):
        runner = self.ready_runner()
        runner.responses[("lsmod",)] = result(
            ("lsmod",),
            available=False,
            returncode=None,
        )

        with patch.object(
            Path,
            "is_dir",
            autospec=True,
            side_effect=lambda path: path == Path("/sys/module/amdgpu"),
        ) as is_dir:
            observation = discover_radeon_runtime(
                runner=runner,
                read_file=self.reader,
                kernel_release="6.10.0-test",
            )

        self.assertTrue(observation.amdgpu_driver_loaded)
        self.assertTrue(preflight_radeon_runtime(observation).ready)
        is_dir.assert_called_once_with(Path("/sys/module/amdgpu"))

    def test_preflight_fails_closed_without_runtime(self):
        observation = discover_radeon_runtime(
            runner=FakeRunner({}),
            read_file=lambda path: None,
            kernel_release="test",
        )
        preflight = preflight_radeon_runtime(observation)

        self.assertFalse(preflight.ready)
        with self.assertRaisesRegex(ValueError, "not ready"):
            execution_contract_fragment(observation)

    def test_multiple_architectures_are_not_implicitly_selected(self):
        runner = self.ready_runner()
        runner.responses[("rocminfo",)] = result(
            ("rocminfo",),
            """
Agent 2
  Name: gfx1100
  Marketing Name: GPU A

Agent 3
  Name: gfx1030
  Marketing Name: GPU B
""",
        )
        observation = discover_radeon_runtime(
            runner=runner,
            read_file=self.reader,
            kernel_release="6.10.0-test",
        )

        self.assertFalse(preflight_radeon_runtime(observation).ready)


if __name__ == "__main__":
    unittest.main()
