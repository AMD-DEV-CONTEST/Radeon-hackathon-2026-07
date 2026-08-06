from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from mantis_rocm_bridge.bowl_asset import materialize_bowl_asset, validate_bowl_source
from mantis_rocm_bridge.contracts import ContractError, load_json


ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class BowlAssetTests(unittest.TestCase):
    def make_source(self, root: Path):
        paths = {
            "visual": root / "assets/objects/002_bowl/visual/base3.glb",
            "collision": root / "assets/objects/002_bowl/collision/base3.glb",
            "metadata": root / "assets/objects/002_bowl/model_data3.json",
            "license": root / "LICENSE",
        }
        for path in paths.values():
            path.parent.mkdir(parents=True, exist_ok=True)
        paths["visual"].write_bytes(b"glTFvisual-fixture")
        paths["collision"].write_bytes(b"glTFcollision-fixture")
        paths["metadata"].write_text(json.dumps({"scale": [0.05, 0.05, 0.05]}), encoding="utf-8")
        paths["license"].write_text(
            "MIT License\n\nCopyright (c) 2025 Tianxing Chen (fixture)\n",
            encoding="utf-8",
        )
        plan = copy.deepcopy(load_json(ROOT / "configs/bowl-asset-plan.json"))
        for role, path in paths.items():
            plan["files"][role]["sha256"] = sha256(path)
        plan["source"]["license_file_sha256"] = sha256(paths["license"])
        return paths, plan

    def test_materialization_is_licensed_non_overwriting_and_structural(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name) / "source"
            _, plan = self.make_source(root)
            output = Path(name) / "bowl-v1"
            hashes = validate_bowl_source(root, plan)
            manifest = materialize_bowl_asset(root, output, plan)
            self.assertEqual(manifest["source_sha256"], hashes)
            self.assertTrue(manifest["distribution_allowed"])
            self.assertTrue((output / "THIRD_PARTY_LICENSES/RoboTwin-MIT.txt").is_file())
            urdf = ET.parse(output / manifest["output_urdf"]).getroot()
            self.assertEqual(urdf.find(".//mass").get("value"), str(plan["source_physics_receipt"]["mass_kg"]))
            with self.assertRaises(ContractError):
                materialize_bowl_asset(root, output, plan)

    def test_hash_or_license_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name) / "source"
            paths, plan = self.make_source(root)
            paths["visual"].write_bytes(b"glTFchanged")
            with self.assertRaises(ContractError):
                validate_bowl_source(root, plan)
            paths, plan = self.make_source(root)
            plan["source"]["license"] = "unknown"
            with self.assertRaises(ContractError):
                validate_bowl_source(root, plan)


if __name__ == "__main__":
    unittest.main()
