from __future__ import annotations

import json
import unittest
from pathlib import Path

from prooflaunch_remix.v10_contracts import V10ContractError
from prooflaunch_remix.v10_open_materials import (
    Admission,
    MaterialKind,
    OpenMaterial,
    OpenMaterialBundle,
)
from prooflaunch_remix.v10_source_bundle import (
    SourceBundleRecord,
    validate_source_bundle,
)


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data/v10_open_materials/manifest.json"
AUDIT = ROOT / "evidence/v10/open-materials-v1-audit.json"


def record(**overrides) -> OpenMaterial:
    values = dict(
        source_id="scene-01",
        kind=MaterialKind.SCENE_VISUAL,
        title="CC0 scene",
        asset_url="https://assets.example/scene.jpg",
        evidence_url="https://rights.example/scene",
        license_id="CC0-1.0",
        license_url="https://creativecommons.org/publicdomain/zero/1.0/",
        revision="asset-sha1-abc",
        upstream_digest_algorithm="sha1",
        upstream_digest="a" * 40,
        media_type="image/jpeg",
        attribution="Fixture author",
        asset_granular_license_verified=True,
        commercial_allowed=True,
        derivatives_allowed=True,
        redistribution_allowed=True,
        training_allowed=True,
    )
    values.update(overrides)
    return OpenMaterial(**values)


class OpenMaterialTests(unittest.TestCase):
    def test_media_requires_asset_granular_license_evidence(self) -> None:
        with self.assertRaisesRegex(V10ContractError, "asset-granular"):
            record(asset_granular_license_verified=False)

    def test_public_locator_does_not_override_unapproved_training_license(self) -> None:
        with self.assertRaisesRegex(V10ContractError, "unapproved license"):
            record(license_id="LicenseRef-Visible-Only")

    def test_trademark_material_is_reference_only_and_never_training(self) -> None:
        brand = record(
            source_id="brand-01",
            kind=MaterialKind.BRAND,
            license_id="LicenseRef-LF-Trademark-Guidelines",
            training_allowed=False,
            commercial_allowed=False,
            trademark_hold=True,
        )
        self.assertEqual(brand.admission, Admission.REFERENCE_ONLY)
        with self.assertRaisesRegex(V10ContractError, "trademark-held"):
            record(trademark_hold=True)

    def test_bundle_requires_all_eight_material_kinds_and_unique_ids(self) -> None:
        rows = tuple(
            record(source_id=f"record-{kind.value}", kind=kind)
            for kind in MaterialKind
        )
        bundle = OpenMaterialBundle(rows)
        self.assertEqual(bundle.counts(), {kind.value: 1 for kind in MaterialKind})
        with self.assertRaisesRegex(V10ContractError, "unique"):
            OpenMaterialBundle(rows + (rows[0],))
        with self.assertRaisesRegex(V10ContractError, "misses kinds"):
            OpenMaterialBundle(rows[:-1])

    def test_generated_manifest_has_three_records_per_kind_and_no_scale_claim(self) -> None:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(manifest["record_count"], 24)
        self.assertEqual(set(manifest["counts"]), {kind.value for kind in MaterialKind})
        self.assertTrue(all(value == 3 for value in manifest["counts"].values()))
        self.assertFalse(manifest["target_complete"])
        self.assertFalse(manifest["promotion_eligible"])

    def test_audit_keeps_brand_records_out_of_training(self) -> None:
        audit = json.loads(AUDIT.read_text(encoding="utf-8"))
        self.assertEqual(audit["mechanically_verified"]["asset_records"], 24)
        self.assertEqual(audit["mechanically_verified"]["material_kinds"], 8)
        self.assertEqual(audit["mechanically_verified"]["records_per_kind"], 3)
        self.assertEqual(audit["mechanically_verified"]["brand_training_admissions"], 0)
        self.assertEqual(audit["runtime_truth"]["downloaded_asset_bytes_saved"], 0)
        self.assertFalse(audit["runtime_truth"]["agency_corpus_v2_frozen"])

    def test_2000_source_bundle_is_real_unique_diverse_and_not_a_corpus_freeze(self) -> None:
        source_path = ROOT / "data/v10_source_bundle/sources.jsonl"
        manifest_path = ROOT / "data/v10_source_bundle/manifest.json"
        rows = []
        for line in source_path.read_text(encoding="utf-8").splitlines():
            payload = json.loads(line)
            payload.pop("identity_sha256")
            rows.append(SourceBundleRecord(**payload))
        verified = validate_source_bundle(tuple(rows))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(verified["source_count"], 2_000)
        self.assertEqual(verified["unique_source_ids"], 2_000)
        self.assertEqual(verified["unique_upstream_identities"], 2_000)
        self.assertLessEqual(verified["maximum_provider_share"], 0.40)
        self.assertGreaterEqual(len(verified["provider_counts"]), 5)
        self.assertGreaterEqual(verified["training_admitted_count"], 1_980)
        self.assertEqual(manifest["source_count"], 2_000)
        self.assertTrue(manifest["source_bundle_2000_complete"])
        self.assertFalse(manifest["agency_corpus_v2_frozen"])
        self.assertEqual(manifest["raw_asset_bytes_vendored"], 0)


if __name__ == "__main__":
    unittest.main()
