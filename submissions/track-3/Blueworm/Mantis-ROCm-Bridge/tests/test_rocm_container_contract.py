from __future__ import annotations

import copy
import unittest
from pathlib import Path

from mantis_rocm_bridge.contracts import (
    ContractError,
    load_json,
    validate_rocm_container_contract,
)


ROOT = Path(__file__).resolve().parents[1]


class RocmContainerContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.contract = load_json(ROOT / "configs/rocm-container-v1.json")

    def test_frozen_contract_is_valid(self) -> None:
        validate_rocm_container_contract(self.contract)

    def test_cuda_or_missing_device_drift_is_rejected(self) -> None:
        broken = copy.deepcopy(self.contract)
        broken["genesis"]["backend"] = "gs.cuda"
        with self.assertRaises(ContractError):
            validate_rocm_container_contract(broken)

        broken = copy.deepcopy(self.contract)
        broken["gpu_access"]["device_nodes"] = ["/dev/dri"]
        with self.assertRaises(ContractError):
            validate_rocm_container_contract(broken)

    def test_claim_receipts_cannot_be_disabled(self) -> None:
        broken = copy.deepcopy(self.contract)
        broken["image_digest_required_for_claim"] = False
        with self.assertRaises(ContractError):
            validate_rocm_container_contract(broken)

    def test_dockerfile_compose_and_constraints_match_contract(self) -> None:
        dockerfile = (ROOT / "docker/Dockerfile.rocm").read_text(encoding="utf-8")
        compose = (ROOT / "docker/compose.rocm.yaml").read_text(encoding="utf-8")
        constraints = (
            ROOT / "requirements/rocm-constraints-v1.txt"
        ).read_text(encoding="utf-8")
        for rendered in (dockerfile, compose):
            self.assertIn(self.contract["base_image"], rendered)
            self.assertIn(self.contract["genesis"]["version"], rendered)
            self.assertIn(self.contract["lerobot"]["revision"], rendered)
        for package, version in (
            ("numpy", self.contract["numpy_version"]),
            ("torch", self.contract["torch_version"]),
            ("torchvision", self.contract["torchvision_version"]),
            ("genesis-world", self.contract["genesis"]["version"]),
        ):
            self.assertIn(f"{package}=={version}", constraints)
        for device in self.contract["gpu_access"]["device_nodes"]:
            self.assertIn(device, compose)


if __name__ == "__main__":
    unittest.main()
