from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw

from prooflaunch_remix.audience_pulse import LexicalAudiencePulse
from prooflaunch_remix.audit import FourGateReleaseAuditor
from prooflaunch_remix.contracts import CampaignRequest, Stage
from prooflaunch_remix.evidence import SourceBoundEvidenceMiner
from prooflaunch_remix.files import sha256_file
from prooflaunch_remix.runtime import build_supervisor


class RealMultimodalPipelineTests(unittest.TestCase):
    def make_product(self, root: Path) -> Path:
        path = root / "product.png"
        image = Image.new("RGBA", (120, 160), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle(
            (10, 8, 110, 150), radius=18, fill=(245, 248, 255, 255)
        )
        draw.rectangle((30, 34, 90, 104), fill=(24, 96, 180, 255))
        draw.ellipse((46, 118, 74, 146), fill=(255, 184, 72, 255))
        image.save(path, format="PNG")
        return path

    def request(self, product: Path) -> CampaignRequest:
        return CampaignRequest(
            product_name="Aster Arc",
            product_image=str(product),
            specification_text=(
                "Battery life up to 18 hours under the documented test. "
                "Housing uses recycled aluminium."
            ),
            market="Japan",
            platform="TikTok",
            goal="launch",
            target_emotion="joy",
        )

    def supervisor(self, *, unsafe_first_pass: bool = False):
        return build_supervisor(
            audience=LexicalAudiencePulse(),
            seed=42,
            canvas_overrides={"TikTok": (360, 640)},
            unsafe_first_pass=unsafe_first_pass,
        )

    def test_real_png_pipeline_repairs_and_exports_verified_pack(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            product = self.make_product(root)
            state = self.supervisor(unsafe_first_pass=True).run(
                self.request(product),
                str(root / "run"),
                run_id="real-pipeline",
            )
            self.assertEqual(state.stage, Stage.DELIVER, state.blocked_reason)
            self.assertEqual(state.repair_count, 1)
            self.assertEqual(state.release_blockers, [])
            asset = Path(state.assets[0].path)
            self.assertTrue(asset.is_file())
            with Image.open(asset) as rendered:
                self.assertEqual(rendered.size, (360, 640))
            self.assertEqual(state.assets[0].metadata["backend_kind"], "deterministic_fallback")
            self.assertTrue(all(Path(path).is_file() for path in state.exports))
            archive = next(Path(path) for path in state.exports if path.endswith(".zip"))
            with zipfile.ZipFile(archive) as handle:
                self.assertIn("campaign-pack.json", handle.namelist())
                self.assertTrue(any(name.startswith("assets/") for name in handle.namelist()))

    def test_same_seed_produces_same_creative_hash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            product = self.make_product(root)
            first = self.supervisor().run(
                self.request(product), str(root / "one"), run_id="one"
            )
            second = self.supervisor().run(
                self.request(product), str(root / "two"), run_id="two"
            )
            self.assertEqual(first.stage, Stage.DELIVER, first.blocked_reason)
            self.assertEqual(second.stage, Stage.DELIVER, second.blocked_reason)
            self.assertEqual(
                sha256_file(first.assets[0].path),
                sha256_file(second.assets[0].path),
            )

    def test_protected_product_hash_survives_layout_repair(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            product = self.make_product(root)
            state = self.supervisor(unsafe_first_pass=True).run(
                self.request(product), str(root / "run"), run_id="identity-lock"
            )
            metadata = state.assets[0].metadata
            self.assertEqual(
                metadata["product_layer_sha256"],
                sha256_file(metadata["product_layer_path"]),
            )
            self.assertEqual(
                metadata["product_source_sha256"],
                sha256_file(product),
            )

    def test_final_asset_product_tampering_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            product = self.make_product(root)
            state = self.supervisor().run(
                self.request(product), str(root / "run"), run_id="tamper"
            )
            asset = state.assets[0]
            image = Image.open(asset.path).convert("RGB")
            draw = ImageDraw.Draw(image)
            x1, y1, x2, y2 = asset.metadata["product_box"]
            draw.rectangle((x1, y1, x2, y2), fill=(255, 0, 255))
            image.save(asset.path, format="PNG")
            findings = FourGateReleaseAuditor().audit(state)
            categories = {finding.category for finding in findings}
            self.assertIn("product_identity", categories)

    def test_exact_source_spans_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            product = self.make_product(root)
            request = self.request(product)
            claims = SourceBoundEvidenceMiner().extract(request)
            self.assertEqual(len(claims), 2)
            self.assertTrue(all(claim.approved for claim in claims))
            self.assertTrue(
                all(claim.source_span in request.specification_text for claim in claims)
            )

    def test_missing_product_fails_closed_and_checkpoints(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request = self.request(root / "missing.png")
            state = self.supervisor().run(
                request, str(root / "run"), run_id="missing-product"
            )
            self.assertEqual(state.stage, Stage.BLOCKED)
            self.assertIn("product image not found", state.blocked_reason or "")
            checkpoint = root / "run" / "campaign-checkpoint.json"
            self.assertTrue(checkpoint.is_file())
            self.assertEqual(
                json.loads(checkpoint.read_text())["stage"],
                "blocked",
            )


if __name__ == "__main__":
    unittest.main()
