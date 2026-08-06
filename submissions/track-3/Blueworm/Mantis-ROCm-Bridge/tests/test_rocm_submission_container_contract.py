from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class RocmSubmissionContainerContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.contract = json.loads(
            (ROOT / "configs/rocm-submission-container-v2.json").read_text()
        )

    def test_public_candidate_is_not_mislabeled_as_official_runtime(self) -> None:
        self.assertEqual(self.contract["role"], "submission_reproduction_candidate")
        self.assertEqual(
            self.contract["runtime_relation"],
            "forward_port_from_official_rocm_7_2_1_experiment_runtime",
        )
        self.assertIn("ROCm 7.2.4", self.contract["known_divergence"])
        self.assertIn("ROCm 7.2.1", self.contract["known_divergence"])
        self.assertTrue(self.contract["image_digest_required_for_claim"])
        self.assertTrue(self.contract["clean_room_runtime_receipt_required"])

    def test_files_match_frozen_container_contract(self) -> None:
        dockerfile = (
            ROOT / "docker/Dockerfile.rocm-submission"
        ).read_text(encoding="utf-8")
        compose = (
            ROOT / "docker/compose.rocm-submission.yaml"
        ).read_text(encoding="utf-8")
        constraints = (
            ROOT / "requirements/rocm-submission-constraints-v2.txt"
        ).read_text(encoding="utf-8")
        for rendered in (dockerfile, compose):
            self.assertIn(self.contract["base_image"], rendered)
            self.assertIn(self.contract["genesis"]["revision"], rendered)
            self.assertIn(self.contract["lerobot"]["revision"], rendered)
        for package, version in (
            ("torch", self.contract["torch_version"]),
            ("torchvision", self.contract["torchvision_version"]),
            ("numpy", self.contract["numpy_version"]),
            ("scikit-image", self.contract["scikit_image_version"]),
            ("lerobot", self.contract["lerobot"]["version"]),
        ):
            self.assertIn(f"{package}=={version}", constraints)
        for device in self.contract["gpu_access"]["device_nodes"]:
            self.assertIn(device, compose)

    def test_private_payloads_are_external_mounts(self) -> None:
        dockerfile = (
            ROOT / "docker/Dockerfile.rocm-submission"
        ).read_text(encoding="utf-8")
        compose = (
            ROOT / "docker/compose.rocm-submission.yaml"
        ).read_text(encoding="utf-8")
        self.assertNotIn("COPY datasets", dockerfile)
        self.assertNotIn("COPY checkpoints", dockerfile)
        self.assertNotIn("COPY local_assets", dockerfile)
        self.assertIn("/workspace/runtime", compose)


if __name__ == "__main__":
    unittest.main()
