from __future__ import annotations

import dataclasses
import hashlib
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

from prooflaunch_remix.benchmark_runner import (
    PHASE_ORDER,
    BenchmarkPhase,
    PermanentActivityError,
)
from prooflaunch_remix.competition_benchmark import ProductSpec
from prooflaunch_remix.radeon_matrix_adapter import (
    EXPECTED_MODEL_SUPPLY_CHAIN,
    MODEL_SUPPLY_CHAIN_SCHEMA,
    RadeonLocalCompetitionAdapter,
    RadeonMatrixAdapterSettings,
    load_radeon_adapter_settings,
    validate_gemma_retention,
)


ROOT = Path(__file__).resolve().parents[1]


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class HarnessAdapter(RadeonLocalCompetitionAdapter):
    def __init__(self, settings: RadeonMatrixAdapterSettings) -> None:
        super().__init__(settings)
        self.loaded: list[BenchmarkPhase] = []
        self.released = 0

    @staticmethod
    def _require_radeon() -> dict[str, object]:
        return {
            "torch_version": "test",
            "hip_version": "test",
            "device_name": "test Radeon",
            "total_vram_gb": 24.0,
        }

    def _load_phase_model(self, phase: BenchmarkPhase) -> str:
        self.loaded.append(phase)
        return f"test/{phase.value}"

    def _release_all(self) -> None:
        self.released += 1

    def _predict_emotion(self, text: str) -> str:
        del text
        return "joy"


class RadeonMatrixAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        raw_settings = json.loads(
            (ROOT / "config" / "radeon_matrix_adapter.json").read_text(
                encoding="utf-8"
            )
        )
        self.retention_path = self.root / "multimodal_retention.json"
        self.retention_path.write_text(
            json.dumps(
                {
                    "pre_accuracy": 0.90,
                    "post_accuracy": 0.89,
                    "minimum_post_accuracy": 0.85,
                    "maximum_allowed_drop": 0.03,
                }
            ),
            encoding="utf-8",
        )
        settings = RadeonMatrixAdapterSettings.from_mapping(raw_settings)
        self.settings = dataclasses.replace(
            settings,
            gemma_retention_path=str(self.retention_path),
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_settings_file_hash_binds_exact_bytes_and_identity(self) -> None:
        settings_path = ROOT / "config" / "radeon_matrix_adapter.json"
        packaged_settings_path = (
            ROOT
            / "src"
            / "prooflaunch_remix"
            / "radeon_matrix_adapter.default.json"
        )
        self.assertEqual(
            settings_path.read_bytes(),
            packaged_settings_path.read_bytes(),
        )
        settings, digest = load_radeon_adapter_settings(settings_path)
        self.assertEqual(digest, file_sha(settings_path))
        adapter = RadeonLocalCompetitionAdapter(
            settings,
            settings_sha256=digest,
        )
        identity = adapter.identity()
        self.assertEqual(identity["settings_sha256"], digest)
        self.assertFalse(identity["uses_closed_online_api"])
        self.assertEqual(len(identity["model_refs"]), 8)
        self.assertEqual(
            identity["model_supply_chain_schema"],
            MODEL_SUPPLY_CHAIN_SCHEMA,
        )
        self.assertEqual(len(identity["model_supply_chain"]), 7)
        self.assertTrue(
            all(
                "@" in model_ref
                for role, model_ref in identity["model_refs"].items()
                if role != "gemma"
            )
        )

    def test_reviewer_supply_chain_manifest_matches_runtime_lock(self) -> None:
        config_manifest = ROOT / "config" / "model_supply_chain.json"
        packaged_manifest = (
            ROOT / "src" / "prooflaunch_remix" / "model_supply_chain.json"
        )
        self.assertEqual(
            config_manifest.read_bytes(),
            packaged_manifest.read_bytes(),
        )
        manifest = json.loads(config_manifest.read_text(encoding="utf-8"))
        self.assertEqual(manifest["schema"], MODEL_SUPPLY_CHAIN_SCHEMA)
        self.assertEqual(
            {
                role: {
                    field: model[field]
                    for field in ("repo_id", "revision", "license")
                }
                for role, model in manifest["models"].items()
            },
            EXPECTED_MODEL_SUPPLY_CHAIN,
        )

    def test_revision_tamper_changes_identity_and_blocks_execution(self) -> None:
        clean = RadeonLocalCompetitionAdapter(self.settings)
        clean_identity = clean.identity()
        tampered_settings = dataclasses.replace(
            self.settings,
            qwen_model_revision="0" * 40,
        )
        tampered = HarnessAdapter(tampered_settings)
        tampered_identity = tampered.identity()
        self.assertNotEqual(
            clean_identity["model_supply_chain_sha256"],
            tampered_identity["model_supply_chain_sha256"],
        )
        self.assertEqual(
            tampered_settings.model_supply_chain_mismatches()[0]["role"],
            "qwen",
        )
        with self.assertRaisesRegex(
            PermanentActivityError,
            "supply chain diverges",
        ):
            tampered.load_phase(BenchmarkPhase.PREPARE_PRODUCTS)

    def test_settings_reject_mutable_or_malformed_revision(self) -> None:
        raw_settings = json.loads(
            (ROOT / "config" / "radeon_matrix_adapter.json").read_text(
                encoding="utf-8"
            )
        )
        raw_settings["qwen_model_revision"] = "main"
        with self.assertRaisesRegex(
            PermanentActivityError,
            "immutable 40-character",
        ):
            RadeonMatrixAdapterSettings.from_mapping(raw_settings)

    def test_settings_reject_non_ltx_frame_count(self) -> None:
        raw_settings = json.loads(
            (ROOT / "config" / "radeon_matrix_adapter.json").read_text(
                encoding="utf-8"
            )
        )
        raw_settings["video_frames"] = 96
        with self.assertRaisesRegex(
            PermanentActivityError,
            "8n\\+1",
        ):
            RadeonMatrixAdapterSettings.from_mapping(raw_settings)

    def test_adapter_passes_release_pins_to_every_external_loader(self) -> None:
        calls: dict[str, dict[str, object]] = {}

        def specialist(name: str):
            class Specialist:
                def __init__(self, **kwargs):
                    calls[name] = kwargs

                def load(self):
                    return None

            return Specialist

        class Pipeline:
            def __init__(self, name: str):
                self.name = name
                self.vae = types.SimpleNamespace(enable_tiling=lambda: None)

            def to(self, device):
                calls[self.name]["device"] = device
                return self

        class ImagePipeline:
            @classmethod
            def from_pretrained(cls, model_id, **kwargs):
                calls["image"] = {"model_id": model_id, **kwargs}
                return Pipeline("image")

        class VideoPipeline:
            @classmethod
            def from_pretrained(cls, model_id, **kwargs):
                calls["video"] = {"model_id": model_id, **kwargs}
                return Pipeline("video")

        diffusers = types.ModuleType("diffusers")
        diffusers.AutoPipelineForText2Image = ImagePipeline
        diffusers.LTXImageToVideoPipeline = VideoPipeline
        torch = types.ModuleType("torch")
        torch.float16 = object()
        torch.bfloat16 = object()
        settings = dataclasses.replace(self.settings, local_files_only=True)
        adapter = RadeonLocalCompetitionAdapter(settings)
        with (
            patch.dict(
                sys.modules,
                {"diffusers": diffusers, "torch": torch},
            ),
            patch(
                "prooflaunch_remix.radeon_matrix_adapter.LocalQwen3VLAnalyzer",
                specialist("qwen"),
            ),
            patch(
                "prooflaunch_remix.radeon_matrix_adapter.LocalGroundingDINO",
                specialist("grounding_dino"),
            ),
            patch(
                "prooflaunch_remix.radeon_matrix_adapter.HuggingFaceSigLIP2Scorer",
                specialist("siglip"),
            ),
            patch(
                "prooflaunch_remix.radeon_matrix_adapter.LocalSAM2VideoTracker",
                specialist("sam2"),
            ),
            patch(
                "prooflaunch_remix.radeon_matrix_adapter.LocalCLAPScorer",
                specialist("clap"),
            ),
        ):
            phase_roles = (
                (BenchmarkPhase.UNDERSTAND_PRODUCTS, "qwen"),
                (BenchmarkPhase.GROUND_PRODUCTS, "grounding_dino"),
                (BenchmarkPhase.GENERATE_STILLS, "image"),
                (BenchmarkPhase.AUDIT_STILLS, "siglip"),
                (BenchmarkPhase.GENERATE_VIDEOS, "video"),
                (BenchmarkPhase.TRACK_VIDEOS, "sam2"),
                (BenchmarkPhase.AUDIT_VIDEOS, "clap"),
            )
            for phase, role in phase_roles:
                model_ref = adapter._load_phase_model(phase)
                expected = settings.model_supply_chain()[role]
                self.assertEqual(
                    model_ref,
                    f"{expected['repo_id']}@{expected['revision']}",
                )
                self.assertEqual(
                    calls[role].get("revision"),
                    expected["revision"],
                )
                self.assertTrue(calls[role]["local_files_only"])

    def test_retention_gate_rejects_out_of_range_metrics(self) -> None:
        self.retention_path.write_text(
            json.dumps(
                {
                    "pre_accuracy": 1.2,
                    "post_accuracy": 0.89,
                    "minimum_post_accuracy": 0.85,
                    "maximum_allowed_drop": 0.03,
                }
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(
            PermanentActivityError,
            "out of range",
        ):
            validate_gemma_retention(self.retention_path)

    def test_all_nine_specialists_have_exclusive_lifecycle(self) -> None:
        adapter = HarnessAdapter(self.settings)
        for phase in PHASE_ORDER:
            loaded = adapter.load_phase(phase)
            self.assertEqual(loaded["phase"], phase.value)
            with self.assertRaisesRegex(PermanentActivityError, "resident"):
                adapter.load_phase(phase)
            adapter.release_phase(phase)
        self.assertEqual(adapter.loaded, list(PHASE_ORDER))
        self.assertEqual(adapter.released, len(PHASE_ORDER))
        self.assertIsNone(adapter.active_phase)

    def test_plan_is_bound_to_frozen_product_bytes(self) -> None:
        source = self.root / "product.png"
        Image.new("RGBA", (48, 32), (29, 101, 181, 255)).save(source)
        product = ProductSpec(
            product_id="blue-device",
            input_sha256=file_sha(source),
            rights="owned",
            source_locator="product.png",
        )
        prepared = {
            "artifact": {
                "id": "MED-001",
                "path": str(source),
                "role": "product_identity",
                "kind": "image",
                "mime_type": "image/png",
                "sha256": file_sha(source),
                "byte_size": source.stat().st_size,
                "rights": "owned",
            }
        }
        adapter = HarnessAdapter(self.settings)
        adapter.active_phase = BenchmarkPhase.PLAN_PRODUCTS
        plan = adapter.plan_product(
            product,
            prepared,
            {"summary": "A blue electronic device."},
            {"selected": {"box_xyxy": [0, 0, 48, 32]}},
        )
        self.assertEqual(plan["product_source_path"], str(source))
        self.assertEqual(plan["product_source_sha256"], product.input_sha256)
        prepared["artifact"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(
            PermanentActivityError,
            "diverges from the frozen manifest",
        ):
            adapter.plan_product(
                product,
                prepared,
                {"summary": "A blue electronic device."},
                {},
            )

    def test_compositor_preserves_opaque_product_pixels(self) -> None:
        product_path = self.root / "opaque-product.png"
        product = Image.new("RGBA", (48, 32), (0, 0, 0, 0))
        ImageDraw.Draw(product).rectangle((4, 4, 43, 27), fill=(21, 99, 177, 255))
        product.save(product_path)
        background = Image.new("RGB", (320, 320), (35, 27, 52))
        composed, layer, product_box = RadeonLocalCompetitionAdapter._compose_still(
            background=background,
            product_path=product_path,
            headline="Evidence-led launch",
        )
        output_path = self.root / "composed.png"
        layer_path = self.root / "layer.png"
        composed.save(output_path)
        layer.save(layer_path)
        mismatch = RadeonLocalCompetitionAdapter._opaque_product_mismatch(
            layer_path,
            output_path,
        )
        self.assertEqual(mismatch, 0.0)
        self.assertLess(product_box[0], product_box[2])
        self.assertLess(product_box[1], product_box[3])


if __name__ == "__main__":
    unittest.main()
