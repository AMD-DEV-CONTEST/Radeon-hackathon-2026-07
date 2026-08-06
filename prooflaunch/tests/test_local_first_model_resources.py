from __future__ import annotations

import unittest
import tempfile
from pathlib import Path

from scripts.discover_local_first_model_resources import (
    discover_huggingface,
    discover_native_capabilities,
    select_local_roles,
)


class LocalFirstModelResourceTests(unittest.TestCase):
    def test_local_roles_prefer_cached_higher_quality_assets(self) -> None:
        roles = select_local_roles(
            ["bge-m3:latest", "qwen2.5-coder:1.5b"],
            [
                "mlx-community/gemma-3-12b-it-4bit",
                "AbstractFramework/flux.2-klein-9b-8bit",
                "AbstractFramework/qwen-image-edit-2511-8bit",
                "dgrauet/ltx-2.3-mlx",
                "AbstractFramework/wan2.2-i2v-a14b-diffusers-bf16",
                "ByteDance-Seed/SeedVR2-7B",
                "mlx-community/Qwen3-TTS-12Hz-1.7B-VoiceDesign-bf16",
                "mlx-community/LongCat-AudioDiT-1B-bf16",
                "PaddlePaddle/PP-OCRv6_medium_rec",
            ],
        )
        self.assertEqual(roles["structured_text_baseline"], "mlx-community/gemma-3-12b-it-4bit")
        self.assertEqual(roles["semantic_memory_and_retrieval"], "bge-m3:latest")
        self.assertTrue(all(model is not None for model in roles.values()))

    def test_missing_assets_are_explicit_not_fabricated(self) -> None:
        roles = select_local_roles([], [])
        self.assertTrue(all(model is None for model in roles.values()))

    def test_native_vision_is_an_explicit_ocr_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            swift = root / "swift"
            swift.write_text("executable probe", encoding="utf-8")
            vision = root / "Vision.framework"
            vision.mkdir()
            native = discover_native_capabilities(swift=swift, vision_framework=vision)
            roles = select_local_roles([], [], native)
            self.assertEqual(roles["document_ocr"], "apple-vision/VNRecognizeTextRequest")

    def test_native_vision_requires_both_swift_and_framework(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            native = discover_native_capabilities(
                swift=root / "missing-swift",
                vision_framework=root / "missing-framework",
            )
            self.assertIsNone(native["document_ocr"])

    def test_refs_only_huggingface_cache_is_not_reported_as_executable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            hub = Path(temporary)
            shell = hub / "models--Example--refs-only"
            (shell / "refs").mkdir(parents=True)
            (shell / "refs/main").write_text("missing-snapshot", encoding="utf-8")
            materialized = hub / "models--Example--materialized"
            (materialized / "snapshots/revision").mkdir(parents=True)
            (materialized / "snapshots/revision/model.safetensors").write_bytes(b"weights")
            self.assertEqual(discover_huggingface(hub), ["Example/materialized"])


if __name__ == "__main__":
    unittest.main()
