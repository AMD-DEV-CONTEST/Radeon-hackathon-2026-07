from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from mantis_rocm_bridge.asset_builder import materialize_fixed_base_asset
from mantis_rocm_bridge.contracts import ContractError
from mantis_rocm_bridge.rim_support_overlay import materialize_rim_support_overlay


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "tests/fixtures/fixed_source"
SOURCE = PACKAGE / "robot.urdf"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class RimSupportOverlayTests(unittest.TestCase):
    def _parent_and_plan(self, root: Path) -> tuple[Path, dict]:
        parent = root / "parent"
        manifest = materialize_fixed_base_asset(
            SOURCE,
            PACKAGE,
            parent,
            "base",
            ["arm_joint", "finger_joint"],
            ["finger_joint"],
            "fixture_fixed",
            acknowledge_unresolved_license_for_local_use=True,
        )
        plan = {
            "schema_version": 1,
            "status": "local_prototype_ready",
            "overlay_id": "fixture_shelf_v1",
            "source_asset": {
                "manifest_sha256": _sha256(parent / "manifest.json"),
                "output_urdf": manifest["output_urdf"],
                "output_urdf_sha256": manifest["output_urdf_sha256"],
                "required_distribution_allowed": False,
                "required_license_status": "unresolved_local_generation_only",
            },
            "geometry": {
                "shape": "box",
                "target_links": ["finger_link"],
                "collision_name": "support_collision",
                "visual_name": "support_visual",
                "size_xyz_m": [0.02, 0.01, 0.004],
                "origin_xyz_m": [0.05, 0.0, -0.01],
                "origin_rpy_rad": [0.0, 0.0, 0.0],
                "color_rgba": [0.1, 0.2, 0.3, 1.0],
            },
            "licensing": {
                "materialized_output_distribution_allowed": False,
            },
            "materialization": {
                "output_robot_name": "fixture_support",
                "output_urdf": "urdf/fixture_support.urdf",
                "overwrite_allowed": False,
            },
            "gates": {"claim_boundary": "fixture only"},
        }
        return parent, plan

    def test_materialization_adds_primitive_and_preserves_local_only_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            parent, plan = self._parent_and_plan(root)
            output = root / "overlay"
            manifest = materialize_rim_support_overlay(
                parent,
                output,
                plan,
                acknowledge_unresolved_license_for_local_use=True,
            )
            self.assertFalse(manifest["distribution_allowed"])
            self.assertTrue((output / "parent_manifest.json").is_file())
            robot = ET.parse(output / manifest["output_urdf"]).getroot()
            finger = robot.find("./link[@name='finger_link']")
            self.assertIsNotNone(finger)
            collision = finger.find("./collision[@name='support_collision']/geometry/box")
            self.assertIsNotNone(collision)
            self.assertEqual(collision.get("size"), "0.02 0.01 0.004")
            self.assertTrue(manifest["structural_audit"]["genesis_import_gate_pass"])
            with self.assertRaises(ContractError):
                materialize_rim_support_overlay(
                    parent,
                    output,
                    plan,
                    acknowledge_unresolved_license_for_local_use=True,
                )

    def test_materialization_requires_local_use_acknowledgement(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            parent, plan = self._parent_and_plan(root)
            with self.assertRaises(ContractError):
                materialize_rim_support_overlay(parent, root / "overlay", plan)

    def test_materialization_applies_per_link_orientation_override(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            parent, plan = self._parent_and_plan(root)
            plan["geometry"]["per_link_origin_rpy_rad"] = {
                "finger_link": [0.5, 0.0, 0.0]
            }
            output = root / "overlay"
            manifest = materialize_rim_support_overlay(
                parent,
                output,
                plan,
                acknowledge_unresolved_license_for_local_use=True,
            )
            robot = ET.parse(output / manifest["output_urdf"]).getroot()
            origin = robot.find(
                "./link[@name='finger_link']/collision[@name='support_collision']/origin"
            )
            self.assertIsNotNone(origin)
            self.assertEqual(origin.get("rpy"), "0.5 0.0 0.0")

    def test_materialization_adds_additional_primitive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            parent, plan = self._parent_and_plan(root)
            plan["geometry"]["additional_primitives"] = [
                {
                    "shape": "box",
                    "collision_name": "lip_collision",
                    "visual_name": "lip_visual",
                    "size_xyz_m": [0.004, 0.018, 0.01],
                    "origin_xyz_m": [0.07, 0.003, 0.0],
                    "origin_rpy_rad": [0.5, 0.0, 0.0],
                    "color_rgba": [0.8, 0.2, 0.1, 1.0],
                }
            ]
            output = root / "overlay"
            manifest = materialize_rim_support_overlay(
                parent,
                output,
                plan,
                acknowledge_unresolved_license_for_local_use=True,
            )
            robot = ET.parse(output / manifest["output_urdf"]).getroot()
            lip = robot.find(
                "./link[@name='finger_link']/collision[@name='lip_collision']/geometry/box"
            )
            self.assertIsNotNone(lip)
            self.assertEqual(lip.get("size"), "0.004 0.018 0.01")

    def test_parent_hash_drift_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            parent, plan = self._parent_and_plan(root)
            plan["source_asset"]["manifest_sha256"] = "0" * 64
            with self.assertRaises(ContractError):
                materialize_rim_support_overlay(
                    parent,
                    root / "overlay",
                    plan,
                    acknowledge_unresolved_license_for_local_use=True,
                )


if __name__ == "__main__":
    unittest.main()
