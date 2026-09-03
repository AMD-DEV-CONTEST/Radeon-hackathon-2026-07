from __future__ import annotations

import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from mantis_rocm_bridge.asset_builder import materialize_fixed_base_asset, plan_fixed_base_asset
from mantis_rocm_bridge.contracts import ContractError


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "tests/fixtures/fixed_source"
SOURCE = PACKAGE / "robot.urdf"


class AssetBuilderTests(unittest.TestCase):
    def test_plan_excludes_nonpolicy_subtree_and_resolves_full_meshes(self) -> None:
        plan = plan_fixed_base_asset(
            SOURCE, PACKAGE, "base", ["arm_joint", "finger_joint"], "fixture_fixed"
        )
        self.assertEqual(plan["selected_link_count"], 3)
        self.assertEqual(plan["selected_joint_count"], 2)
        self.assertEqual(plan["excluded_joint_count"], 1)
        self.assertEqual(plan["unique_mesh_count"], 3)
        self.assertTrue(all(path.startswith("meshes_full/") for path in plan["mesh_sources"].values()))

    def test_materialization_is_non_overwriting_and_structurally_clean(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "asset-v1"
            manifest = materialize_fixed_base_asset(
                SOURCE,
                PACKAGE,
                output,
                "base",
                ["arm_joint", "finger_joint"],
                ["finger_joint"],
                "fixture_fixed",
                acknowledge_unresolved_license_for_local_use=True,
            )
            self.assertTrue(manifest["structural_audit"]["genesis_import_gate_pass"])
            generated = ET.parse(output / "urdf/mantis_fixed_base.urdf").getroot()
            self.assertEqual([joint.get("name") for joint in generated.findall("joint")], [
                "arm_joint",
                "finger_joint",
            ])
            self.assertNotIn("neck_link", [link.get("name") for link in generated.findall("link")])
            stored = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
            self.assertFalse(stored["distribution_allowed"])
            self.assertEqual(
                stored["structural_audit"]["urdf"], "urdf/mantis_fixed_base.urdf"
            )
            with self.assertRaises(ContractError):
                materialize_fixed_base_asset(
                    SOURCE,
                    PACKAGE,
                    output,
                    "base",
                    ["arm_joint", "finger_joint"],
                    ["finger_joint"],
                    "fixture_fixed",
                    acknowledge_unresolved_license_for_local_use=True,
                )

    def test_materialization_requires_license_acknowledgement(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(ContractError):
                materialize_fixed_base_asset(
                    SOURCE,
                    PACKAGE,
                    Path(temporary) / "asset-v1",
                    "base",
                    ["arm_joint", "finger_joint"],
                    ["finger_joint"],
                    "fixture_fixed",
                )


if __name__ == "__main__":
    unittest.main()
