from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from prooflaunch_remix.local_multimodal_renderer import (
    LocalMultimodalRenderer,
    LocalRenderError,
    MultimodalRenderSpec,
)


ROOT = Path(__file__).resolve().parents[1]


def _spec(**changes) -> MultimodalRenderSpec:
    values = {
        "campaign_id": "zero-budget-b2b-launch",
        "brand_name": "ProofLaunch",
        "headline": "Make the decision inspectable before asking for trust.",
        "proof": "Every visible claim is bound to an approved source and immutable digest.",
        "call_to_action": "Inspect the proof, then name the unresolved objection.",
        "evidence_sha256": hashlib.sha256(b"evidence").hexdigest(),
        "source_pack_sha256": hashlib.sha256(b"pack").hexdigest(),
        "rights_locator": "project-owned://prooflaunch/demo-v1",
        "voiceover_script": "Proof before promise. Inspect the evidence, then decide.",
        "accent_hex": "#7C5CFF",
    }
    values.update(changes)
    return MultimodalRenderSpec(**values)


class LocalMultimodalRendererTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.renderer = LocalMultimodalRenderer(project_root=ROOT)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_renders_content_addressed_image_and_caption_delivery(self) -> None:
        receipt = self.renderer.render(
            _spec(),
            self.root / "render",
            encode_video=False,
            synthesize_audio=False,
        )
        self.assertEqual(receipt.rendered_modalities, ("image", "text"))
        self.assertFalse(receipt.external_publish_executed)
        self.assertFalse(receipt.four_a_effect_proven)
        self.assertFalse(receipt.radeon_inference_executed)
        manifest = json.loads(Path(receipt.manifest_path).read_text())
        digest_basis = dict(manifest)
        claimed = digest_basis.pop("manifest_sha256")
        self.assertEqual(
            claimed,
            hashlib.sha256(
                json.dumps(digest_basis, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
        )
        for artifact in receipt.artifacts:
            path = Path(receipt.output_root) / artifact.relative_path
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), artifact.content_sha256)
        with Image.open(Path(receipt.output_root) / "hero-4k.png") as hero:
            self.assertEqual(hero.size, (3840, 2160))
        with Image.open(Path(receipt.output_root) / "social-1080x1350.png") as social:
            self.assertEqual(social.size, (1080, 1350))
        self.assertIn("not Radeon model output", manifest["truth_boundary"])

    def test_rejects_invalid_source_digest(self) -> None:
        with self.assertRaisesRegex(LocalRenderError, "source_pack_sha256"):
            self.renderer.render(
                _spec(source_pack_sha256="bad"),
                self.root / "render",
                encode_video=False,
                synthesize_audio=False,
            )

    def test_rejects_nonempty_output_directory(self) -> None:
        output = self.root / "render"
        output.mkdir()
        (output / "old.txt").write_text("old")
        with self.assertRaisesRegex(LocalRenderError, "must be empty"):
            self.renderer.render(
                _spec(),
                output,
                encode_video=False,
                synthesize_audio=False,
            )

    def test_rejects_layout_overflow_instead_of_silently_clipping(self) -> None:
        with self.assertRaisesRegex(LocalRenderError, "layout contract"):
            self.renderer.render(
                _spec(headline="x" * 181),
                self.root / "render",
                encode_video=False,
                synthesize_audio=False,
            )


if __name__ == "__main__":
    unittest.main()
