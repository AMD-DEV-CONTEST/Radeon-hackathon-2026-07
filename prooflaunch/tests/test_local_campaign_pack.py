from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from prooflaunch_remix.files import sha256_file
from prooflaunch_remix.local_campaign_pack import (
    LocalCampaignPackError,
    LocalCampaignPackSpec,
    render_local_campaign_pack,
)


class LocalCampaignPackTests(unittest.TestCase):
    def _fixture(self, root: Path) -> tuple[Path, Path, LocalCampaignPackSpec]:
        source = root / "source.png"
        Image.new("RGB", (1536, 864), (18, 25, 44)).save(source)
        metadata = root / "source.metadata.json"
        metadata.write_text(
            json.dumps(
                {
                    "model": "fixture/qwen-image",
                    "seed": 42,
                    "steps": 4,
                    "guidance": 1.0,
                    "precision": "bf16",
                    "quantize": 8,
                    "generation_time_seconds": 1.0,
                }
            ),
            encoding="utf-8",
        )
        spec = LocalCampaignPackSpec(
            campaign_id="campaign-fixture",
            brand_name="ProofLaunch",
            eyebrow="Evidence before scale",
            headline="Turn proof into the next growth decision.",
            proof="A source-bound proof line.",
            call_to_action="Inspect the evidence. →",
            evidence_sha256="a" * 64,
            source_image_sha256=sha256_file(source),
            source_metadata_sha256=sha256_file(metadata),
            expected_model_id="fixture/qwen-image",
            rights_locator="project-owned://fixture",
            seed=42,
        )
        return source, metadata, spec

    def test_static_delivery_is_source_bound_and_true_4k(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, metadata, spec = self._fixture(root)
            manifest = render_local_campaign_pack(
                spec,
                project_root=root,
                source_image=source,
                source_metadata=metadata,
                output_dir=root / "delivery",
            )
            self.assertEqual(len(manifest["artifacts"]), 3)
            self.assertTrue(manifest["quality_gates"]["hero_true_4k_geometry"])
            self.assertTrue(manifest["quality_gates"]["mechanical_campaign_pack_ready"])
            self.assertFalse(manifest["quality_gates"]["product_admission_passed"])
            self.assertEqual(manifest["source_generation"]["cloud_api_calls"], 0)
            self.assertFalse(manifest["external_publish_executed"])

    def test_source_digest_model_and_nonempty_output_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, metadata, spec = self._fixture(root)
            bad_digest = LocalCampaignPackSpec(
                **{**spec.__dict__, "source_image_sha256": "b" * 64}
            )
            with self.assertRaises(LocalCampaignPackError):
                render_local_campaign_pack(
                    bad_digest,
                    project_root=root,
                    source_image=source,
                    source_metadata=metadata,
                    output_dir=root / "digest-fail",
                )
            bad_model = LocalCampaignPackSpec(
                **{**spec.__dict__, "expected_model_id": "wrong/model"}
            )
            with self.assertRaises(LocalCampaignPackError):
                render_local_campaign_pack(
                    bad_model,
                    project_root=root,
                    source_image=source,
                    source_metadata=metadata,
                    output_dir=root / "model-fail",
                )
            occupied = root / "occupied"
            occupied.mkdir()
            (occupied / "keep.txt").write_text("keep", encoding="utf-8")
            with self.assertRaises(LocalCampaignPackError):
                render_local_campaign_pack(
                    spec,
                    project_root=root,
                    source_image=source,
                    source_metadata=metadata,
                    output_dir=occupied,
                )


if __name__ == "__main__":
    unittest.main()
