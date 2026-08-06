from __future__ import annotations

import json
import tempfile
import unittest
from types import ModuleType
from unittest.mock import patch
from pathlib import Path
from typing import Any, Mapping

from PIL import Image

from tools.episode_factory.amd_story_studio import (
    ACCEPTANCE_SCHEMA_VERSION,
    DiffusersRocmRuntime,
    SCHEMA_VERSION,
    StoryStudioManifest,
    finalize_storyboard,
    run_story_studio,
)
from tools.episode_factory.manage_amd_story_studio import prepare_package
from tools.episode_factory.radeon_cloud_execution import inspect_cloud_package


class FakeRuntime:
    def __init__(self) -> None:
        self.loaded = False
        self.text_seeds: list[int] = []
        self.image_seeds: list[int] = []
        self.reset_called = False

    def runtime_evidence(self) -> Mapping[str, Any]:
        return {
            "torch_version": "test",
            "hip_version": "7.2-test",
            "device_name": "Fake AMD Radeon",
            "device_count": 1,
        }

    def load(self, model: Any) -> Mapping[str, Any]:
        self.loaded = True
        return {
            "resolved_revision": "a" * 40,
            "load_seconds": 0.1,
            "requested_dtype": model.dtype,
            "component_dtypes": {
                "unet": model.dtype,
                "text_encoder": model.dtype,
                "text_encoder_2": model.dtype,
                "vae": model.dtype,
            },
            "verified_core_dtype": True,
            "vae_upcast_is_explicit": False,
        }

    def generate_text(self, **kwargs: Any) -> Image.Image:
        self.text_seeds.append(kwargs["seed"])
        return Image.new("RGB", (kwargs["width"], kwargs["height"]), "white")

    def generate_image(self, **kwargs: Any) -> Image.Image:
        self.image_seeds.append(kwargs["seed"])
        self.assert_reference(kwargs["reference_image"])
        return Image.new("RGB", (kwargs["width"], kwargs["height"]), "gray")

    @staticmethod
    def assert_reference(value: Any) -> None:
        if not isinstance(value, Image.Image):
            raise AssertionError("expected a PIL reference image")

    def synchronize(self) -> None:
        return None

    def reset_peak_memory(self) -> None:
        self.reset_called = True

    def peak_memory(self) -> Mapping[str, Any]:
        return {
            "max_memory_allocated_bytes": 10,
            "max_memory_reserved_bytes": 20,
        }


def manifest_mapping() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "project_id": "demo",
        "title": "Demo",
        "model": {
            "id": "example/model",
            "revision": "a" * 40,
            "dtype": "float16",
            "variant": "fp16",
            "inference_steps": 4,
            "guidance_scale": 0.0,
            "warmup_images": 1,
        },
        "canvas": {"width": 256, "height": 256},
        "style_prompt": "animated educational style",
        "negative_prompt": "",
        "scenes": [
            {
                "scene_id": "reference",
                "label": "REFERENCE",
                "prompt": "one fictional character",
                "seed": 10,
                "variants": 2,
                "generation_mode": "text_to_image",
                "reference_scene_id": None,
                "strength": None,
                "content_class": "reference_character",
                "include_in_storyboard": False,
                "required_review_checks": [
                    "safety",
                    "semantic",
                    "continuity",
                ],
            },
            {
                "scene_id": "reaction",
                "label": "REACT SAFELY",
                "prompt": "the same fictional character steps back",
                "seed": 20,
                "variants": 2,
                "generation_mode": "image_to_image",
                "reference_scene_id": "reference",
                "strength": 0.45,
                "content_class": "character_only",
                "include_in_storyboard": True,
                "required_review_checks": [
                    "safety",
                    "semantic",
                    "continuity",
                ],
            },
        ],
        "assembly": {
            "require_single_lineage": True,
            "require_modular_safety_partition": True,
        },
    }


def complete_review(review_path: Path, *, mixed_lineage: bool = False) -> None:
    review = json.loads(review_path.read_text(encoding="utf-8"))
    review["reviewer"] = "Test Reviewer"
    review["reviewed_at"] = "2026-08-03T03:00:00+00:00"
    for decision in review["decisions"]:
        selected_lineage = 2 if mixed_lineage and decision["scene_id"] == "reaction" else 1
        decision["selected"] = decision["lineage"] == selected_lineage
        if decision["selected"]:
            decision["safety"] = "pass"
            decision["semantic"] = "pass"
            decision["continuity"] = "pass"
            decision["reasons"] = []
        else:
            decision["safety"] = "pass"
            decision["semantic"] = "reject"
            decision["continuity"] = "reject"
            decision["reasons"] = ["not selected after editorial comparison"]
    review_path.write_text(
        json.dumps(review, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


class StoryStudioTest(unittest.TestCase):
    def test_manifest_identity_is_deterministic(self) -> None:
        first = StoryStudioManifest.from_mapping(manifest_mapping())
        second = StoryStudioManifest.from_mapping(manifest_mapping())
        self.assertEqual(first.manifest_id, second.manifest_id)
        self.assertEqual(first.total_images, 4)

    def test_duplicate_scene_id_is_rejected(self) -> None:
        value = manifest_mapping()
        value["scenes"][1]["scene_id"] = "reference"
        with self.assertRaisesRegex(ValueError, "unique"):
            StoryStudioManifest.from_mapping(value)

    def test_reference_must_point_to_earlier_scene(self) -> None:
        value = manifest_mapping()
        value["scenes"] = list(reversed(value["scenes"]))
        with self.assertRaisesRegex(ValueError, "earlier"):
            StoryStudioManifest.from_mapping(value)

    def test_ineffective_negative_prompt_is_rejected(self) -> None:
        value = manifest_mapping()
        value["negative_prompt"] = "unsafe"
        with self.assertRaisesRegex(ValueError, "ineffective"):
            StoryStudioManifest.from_mapping(value)

    def test_cpu_fake_run_records_dtype_warmup_and_reference_generation(self) -> None:
        manifest = StoryStudioManifest.from_mapping(manifest_mapping())
        runtime = FakeRuntime()
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "outputs"
            report_path = run_story_studio(manifest, output, runtime=runtime)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertTrue(runtime.loaded)
            self.assertTrue(runtime.reset_called)
            self.assertEqual(runtime.text_seeds, [10000010, 10, 11])
            self.assertEqual(runtime.image_seeds, [20, 21])
            self.assertEqual(report["performance"]["candidate_count"], 4)
            self.assertEqual(report["performance"]["warmup_count"], 1)
            self.assertTrue(report["model"]["verified_core_dtype"])
            self.assertEqual(report["model"]["component_dtypes"]["vae"], "float16")
            self.assertFalse(report["model"]["vae_upcast_is_explicit"])
            self.assertEqual(report["acceptance"]["technical"]["status"], "pass")
            self.assertEqual(report["acceptance"]["overall"], "pending")
            self.assertTrue((output / "contact-sheet.png").is_file())
            self.assertTrue((output / "review-template.json").is_file())
            for record in report["outputs"]:
                self.assertTrue((output / record["output"]).is_file())

    def test_diffusers_runtime_does_not_eagerly_upcast_vae(self) -> None:
        class FakeParameter:
            dtype = "torch.float16"

        class FakeComponent:
            def __init__(self) -> None:
                self.to_calls: list[dict[str, Any]] = []

            def parameters(self) -> Any:
                return iter([FakeParameter()])

            def to(self, **kwargs: Any) -> "FakeComponent":
                self.to_calls.append(kwargs)
                return self

        class FakePipeline:
            def __init__(self) -> None:
                self.unet = FakeComponent()
                self.text_encoder = FakeComponent()
                self.text_encoder_2 = FakeComponent()
                self.vae = FakeComponent()
                self.device: str | None = None

            def to(self, device: str) -> "FakePipeline":
                self.device = device
                return self

            def set_progress_bar_config(self, *, disable: bool) -> None:
                self.progress_disabled = disable

        pipeline = FakePipeline()
        captured: dict[str, Any] = {}

        class FakeAutoPipeline:
            @classmethod
            def from_pretrained(cls, model_id: str, **kwargs: Any) -> FakePipeline:
                captured["model_id"] = model_id
                captured["kwargs"] = kwargs
                return pipeline

        class FakeTorch:
            float16 = object()
            float32 = object()

        diffusers = ModuleType("diffusers")
        diffusers.AutoPipelineForText2Image = FakeAutoPipeline  # type: ignore[attr-defined]
        hub = ModuleType("huggingface_hub")
        hub.HfApi = object  # type: ignore[attr-defined]

        runtime = DiffusersRocmRuntime.__new__(DiffusersRocmRuntime)
        runtime.torch = FakeTorch()
        runtime.text_pipeline = None
        runtime.image_pipeline = None
        runtime.resolved_revision = None
        runtime.synchronize = lambda: None  # type: ignore[method-assign]

        manifest = StoryStudioManifest.from_mapping(manifest_mapping())
        with patch.dict(
            "sys.modules",
            {"diffusers": diffusers, "huggingface_hub": hub},
        ):
            evidence = runtime.load(manifest.model)

        self.assertEqual(pipeline.device, "cuda")
        self.assertEqual(pipeline.vae.to_calls, [])
        self.assertIs(captured["kwargs"]["torch_dtype"], FakeTorch.float16)
        self.assertEqual(evidence["component_dtypes"]["vae"], "float16")
        self.assertFalse(evidence["vae_upcast_is_explicit"])
        self.assertTrue(evidence["verified_core_dtype"])

    def test_finalize_requires_passed_human_review(self) -> None:
        manifest = StoryStudioManifest.from_mapping(manifest_mapping())
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "run"
            report_path = run_story_studio(
                manifest,
                output,
                runtime=FakeRuntime(),
            )
            with self.assertRaisesRegex(ValueError, "reviewer"):
                finalize_storyboard(
                    manifest,
                    report_path,
                    output / "review-template.json",
                    root / "final",
                )

    def test_finalize_writes_accepted_storyboard_and_metadata_only_rejections(self) -> None:
        manifest = StoryStudioManifest.from_mapping(manifest_mapping())
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_root = root / "run"
            report_path = run_story_studio(
                manifest,
                run_root,
                runtime=FakeRuntime(),
            )
            review_path = run_root / "review-template.json"
            complete_review(review_path)
            acceptance_path = finalize_storyboard(
                manifest,
                report_path,
                review_path,
                root / "final",
            )
            acceptance = json.loads(acceptance_path.read_text(encoding="utf-8"))
            self.assertEqual(
                acceptance["schema_version"],
                ACCEPTANCE_SCHEMA_VERSION,
            )
            self.assertEqual(acceptance["overall"], "pass")
            self.assertEqual(acceptance["single_lineage"], [1])
            self.assertTrue((root / "final" / "accepted-storyboard.png").is_file())
            rejected = json.loads(
                (root / "final" / "rejected-candidates.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertFalse(rejected["images_embedded"])
            self.assertEqual(len(rejected["candidates"]), 2)

    def test_finalize_rejects_mixed_character_lineages(self) -> None:
        manifest = StoryStudioManifest.from_mapping(manifest_mapping())
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_root = root / "run"
            report_path = run_story_studio(
                manifest,
                run_root,
                runtime=FakeRuntime(),
            )
            review_path = run_root / "review-template.json"
            complete_review(review_path, mixed_lineage=True)
            with self.assertRaisesRegex(ValueError, "consistent lineage"):
                finalize_storyboard(
                    manifest,
                    report_path,
                    review_path,
                    root / "final",
                )

    def test_prepare_builds_reproducible_cloud_package(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path = root / "manifest.json"
            manifest_path.write_text(
                json.dumps(manifest_mapping()),
                encoding="utf-8",
            )
            first = prepare_package(
                manifest_path=manifest_path,
                output_directory=root / "first",
                remote_python="/workspace/venv/bin/python",
                timeout_seconds=600,
            )
            second = prepare_package(
                manifest_path=manifest_path,
                output_directory=root / "second",
                remote_python="/workspace/venv/bin/python",
                timeout_seconds=600,
            )
            self.assertEqual(first["plan_id"], second["plan_id"])
            self.assertEqual(
                first["package"]["sha256"],
                second["package"]["sha256"],
            )
            inspected = inspect_cloud_package(Path(first["package"]["path"]))
            self.assertEqual(inspected["backend"], "radeon-cloud")
            self.assertEqual(inspected["output_paths"], ["outputs"])


if __name__ == "__main__":
    unittest.main()
