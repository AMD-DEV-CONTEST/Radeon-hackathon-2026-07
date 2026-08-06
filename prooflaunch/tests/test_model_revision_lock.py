from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import patch

from prooflaunch_remix.multimodal_models import (
    LocalCLAPScorer,
    LocalGroundingDINO,
    LocalQwen3VLAnalyzer,
    LocalSAM2VideoTracker,
)
from prooflaunch_remix.visual_semantics import HuggingFaceSigLIP2Scorer


REVISION = "a" * 40


class _LoadedModel:
    def to(self, device):
        self.device = device
        return self

    def eval(self):
        return self


def _loader(name: str):
    class Loader:
        calls: list[tuple[str, dict[str, object]]] = []

        @classmethod
        def from_pretrained(cls, model_id, **kwargs):
            cls.calls.append((model_id, kwargs))
            return _LoadedModel()

    Loader.__name__ = name
    return Loader


class ModelRevisionLockTests(unittest.TestCase):
    def setUp(self) -> None:
        self.loaders = {
            name: _loader(name)
            for name in (
                "AutoModel",
                "AutoModelForImageTextToText",
                "AutoModelForZeroShotObjectDetection",
                "AutoProcessor",
                "ClapModel",
                "Sam2VideoModel",
                "Sam2VideoProcessor",
            )
        }
        transformers = types.ModuleType("transformers")
        for name, loader in self.loaders.items():
            setattr(transformers, name, loader)
        torch = types.ModuleType("torch")
        torch.float16 = object()
        self.modules = {
            "torch": torch,
            "transformers": transformers,
        }

    def _assert_last_pin(self, loader_name: str, model_id: str) -> None:
        selected_id, kwargs = self.loaders[loader_name].calls[-1]
        self.assertEqual(selected_id, model_id)
        self.assertEqual(kwargs["revision"], REVISION)
        self.assertTrue(kwargs["local_files_only"])

    def test_transformers_models_and_processors_share_the_exact_pin(self) -> None:
        with patch.dict(sys.modules, self.modules):
            qwen = LocalQwen3VLAnalyzer(
                "test/qwen",
                revision=REVISION,
                local_files_only=True,
            )
            qwen.load()
            self._assert_last_pin("AutoProcessor", "test/qwen")
            self._assert_last_pin(
                "AutoModelForImageTextToText",
                "test/qwen",
            )
            self.assertEqual(qwen.model_ref, f"test/qwen@{REVISION}")

            dino = LocalGroundingDINO(
                "test/dino",
                revision=REVISION,
                local_files_only=True,
            )
            dino.load()
            self._assert_last_pin("AutoProcessor", "test/dino")
            self._assert_last_pin(
                "AutoModelForZeroShotObjectDetection",
                "test/dino",
            )

            sam2 = LocalSAM2VideoTracker(
                "test/sam2",
                revision=REVISION,
                local_files_only=True,
            )
            sam2.load()
            self._assert_last_pin("Sam2VideoProcessor", "test/sam2")
            self._assert_last_pin("Sam2VideoModel", "test/sam2")

            clap = LocalCLAPScorer(
                "test/clap",
                revision=REVISION,
                local_files_only=True,
            )
            clap.load()
            self._assert_last_pin("AutoProcessor", "test/clap")
            self._assert_last_pin("ClapModel", "test/clap")

            siglip = HuggingFaceSigLIP2Scorer(
                "test/siglip",
                revision=REVISION,
                local_files_only=True,
            )
            siglip.load()
            self._assert_last_pin("AutoProcessor", "test/siglip")
            self._assert_last_pin("AutoModel", "test/siglip")
            self.assertEqual(siglip.model_ref, f"test/siglip@{REVISION}")


if __name__ == "__main__":
    unittest.main()
