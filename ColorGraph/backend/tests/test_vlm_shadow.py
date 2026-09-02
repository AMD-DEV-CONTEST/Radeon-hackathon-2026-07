from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

import pytest
import torch
from PIL import Image
from pydantic import ValidationError

from colorgraph.agent.scene_understanding import LocalSceneAnalyzer
from colorgraph.agent.vlm_shadow import (
    VLMCalibrationExample,
    VLMCalibrationInput,
    VLMLabelSpec,
    calibrate_vlm_shadow,
    score_vlm_shadow_embeddings,
)
from colorgraph.vision.model_lifecycle import clear_inference_caches

MODEL_ID = "google/siglip2-test"
MODEL_REVISION = "f" * 40
LABELS = [
    VLMLabelSpec(
        label_id="terrain.mountain",
        category="terrain",
        prompt="This is a mountain.",
    ),
    VLMLabelSpec(
        label_id="terrain.forest",
        category="terrain",
        prompt="This is a forest.",
    ),
    VLMLabelSpec(
        label_id="lighting.overcast",
        category="lighting",
        prompt="This has overcast light.",
    ),
    VLMLabelSpec(
        label_id="intent.natural",
        category="intent",
        prompt="A natural treatment supports this.",
    ),
]


def _calibration_input() -> VLMCalibrationInput:
    logits = [
        (
            "known-mixed",
            {
                "terrain.mountain": 4.0,
                "terrain.forest": 3.0,
                "lighting.overcast": 3.0,
                "intent.natural": 2.0,
            },
            ["terrain.mountain", "terrain.forest", "lighting.overcast", "intent.natural"],
            0.8,
            False,
        ),
        (
            "known-mountain",
            {
                "terrain.mountain": 3.0,
                "terrain.forest": -3.0,
                "lighting.overcast": -2.0,
                "intent.natural": 2.0,
            },
            ["terrain.mountain", "intent.natural"],
            0.7,
            False,
        ),
        (
            "known-forest",
            {
                "terrain.mountain": -3.0,
                "terrain.forest": 3.0,
                "lighting.overcast": 2.0,
                "intent.natural": -2.0,
            },
            ["terrain.forest", "lighting.overcast"],
            0.65,
            False,
        ),
        (
            "known-overcast",
            {
                "terrain.mountain": -2.0,
                "terrain.forest": -2.0,
                "lighting.overcast": 3.0,
                "intent.natural": -2.0,
            },
            ["lighting.overcast"],
            0.6,
            False,
        ),
        (
            "ood",
            {
                "terrain.mountain": -4.0,
                "terrain.forest": -4.0,
                "lighting.overcast": -4.0,
                "intent.natural": -4.0,
            },
            [],
            0.05,
            True,
        ),
    ]
    return VLMCalibrationInput(
        model_id=MODEL_ID,
        model_revision=MODEL_REVISION,
        status="bootstrap_not_gold",
        labels=LABELS,
        examples=[
            VLMCalibrationExample(
                sample_id=sample_id,
                split="calibration",
                raw_logits=raw_logits,
                positive_label_ids=positives,
                max_cosine=max_cosine,
                is_ood=is_ood,
            )
            for sample_id, raw_logits, positives, max_cosine, is_ood in logits
        ],
    )


def test_calibration_uses_only_calibration_split_and_freezes_thresholds() -> None:
    calibration = calibrate_vlm_shadow(_calibration_input())

    assert calibration.source_split == "calibration"
    assert calibration.status == "bootstrap_not_gold"
    assert set(calibration.label_thresholds) == {
        label.label_id for label in LABELS
    }
    assert calibration.temperature > 0
    assert calibration.ood_balanced_accuracy == 1

    payload = _calibration_input().model_dump(mode="json")
    payload["examples"][0]["split"] = "test"
    with pytest.raises(ValidationError):
        VLMCalibrationInput.model_validate(payload)


def test_independent_sigmoid_supports_multilabel_and_explicit_ood() -> None:
    calibration = calibrate_vlm_shadow(_calibration_input())
    image_features = torch.tensor(
        [
            [1.0, 1.0, 1.0, 1.0],
            [-1.0, -1.0, -1.0, -1.0],
        ]
    )
    text_features = torch.eye(4)

    report = score_vlm_shadow_embeddings(
        image_features,
        text_features,
        frame_paths=["known.png", "ood.png"],
        frame_sha256=["a" * 64, "b" * 64],
        labels=LABELS,
        calibration=calibration,
        model_id=MODEL_ID,
        model_revision=MODEL_REVISION,
        logit_scale=8,
        logit_bias=0,
        checkpoint_sha256="c" * 64,
        checkpoint_hash_kind="colorgraph.torch-state-dict/v1",
    )

    known, ood = report.frames
    assert known.ood is False
    assert known.selected_by_category["terrain"] == [
        "terrain.mountain",
        "terrain.forest",
    ]
    assert known.unknown_categories == []
    assert ood.ood is True
    assert ood.unknown_categories == ["terrain", "lighting", "intent"]
    assert all(not score.selected for score in ood.scores)
    assert report.probability_semantics == "independent_sigmoid"
    assert report.technical_risk_prompts_excluded is True
    assert report.checkpoint_sha256 == "c" * 64
    assert report.checkpoint_hash_kind == "colorgraph.torch-state-dict/v1"


def test_runtime_identity_must_match_calibration() -> None:
    calibration = calibrate_vlm_shadow(_calibration_input())

    with pytest.raises(ValueError, match="identity"):
        score_vlm_shadow_embeddings(
            torch.ones((1, 4)),
            torch.eye(4),
            frame_paths=["frame.png"],
            frame_sha256=["a" * 64],
            labels=LABELS,
            calibration=calibration,
            model_id=MODEL_ID,
            model_revision="e" * 40,
            logit_scale=1,
            logit_bias=0,
        )


def test_runtime_checkpoint_must_match_frozen_calibration() -> None:
    calibration_input = _calibration_input().model_copy(
        update={
            "checkpoint_sha256": "c" * 64,
            "checkpoint_hash_kind": "colorgraph.torch-state-dict/v1",
        }
    )
    calibration = calibrate_vlm_shadow(
        VLMCalibrationInput.model_validate(
            calibration_input.model_dump(mode="python")
        )
    )

    with pytest.raises(ValueError, match="checkpoint identity"):
        score_vlm_shadow_embeddings(
            torch.ones((1, 4)),
            torch.eye(4),
            frame_paths=["frame.png"],
            frame_sha256=["a" * 64],
            labels=LABELS,
            calibration=calibration,
            model_id=MODEL_ID,
            model_revision=MODEL_REVISION,
            logit_scale=1,
            logit_bias=0,
            checkpoint_sha256="d" * 64,
            checkpoint_hash_kind="colorgraph.torch-state-dict/v1",
        )


class _FakeBackend:
    torch_device = torch.device("cpu")
    info = SimpleNamespace(runtime="cpu")

    def inference_context(self, *, mixed_precision: bool = True):
        return nullcontext()


class _SiglipProcessor:
    def __init__(self) -> None:
        self.image_batches = 0
        self.text_batches = 0
        self.text_options: dict[str, object] = {}

    def __call__(
        self,
        *,
        images=None,
        text=None,
        return_tensors: str,
        padding=False,
        max_length=None,
        truncation=False,
    ):
        assert return_tensors == "pt"
        if images is not None:
            self.image_batches += 1
            values = []
            for image in images:
                red, green, blue = image.resize((1, 1)).getpixel((0, 0))
                values.append([red, green, blue, 255])
            return {"pixel_values": torch.tensor(values, dtype=torch.float32)}
        self.text_batches += 1
        self.text_options = {
            "padding": padding,
            "max_length": max_length,
            "truncation": truncation,
        }
        return {
            "input_ids": torch.arange(len(text), dtype=torch.long).view(-1, 1)
        }


class _SiglipModel:
    def __init__(self) -> None:
        self.config = SimpleNamespace(
            _commit_hash=MODEL_REVISION,
            model_type="siglip2",
        )
        self.logit_scale = torch.tensor(float(torch.log(torch.tensor(8.0))))
        self.logit_bias = torch.tensor(0.0)
        self.image_calls = 0
        self.text_calls = 0

    def get_image_features(self, *, pixel_values: torch.Tensor) -> torch.Tensor:
        self.image_calls += 1
        return pixel_values

    def get_text_features(self, *, input_ids: torch.Tensor) -> torch.Tensor:
        self.text_calls += 1
        return torch.nn.functional.one_hot(
            input_ids[:, 0],
            num_classes=4,
        ).float()


def test_local_analyzer_encodes_images_and_all_texts_once(tmp_path) -> None:
    clear_inference_caches()
    processor = _SiglipProcessor()
    model = _SiglipModel()
    analyzer = LocalSceneAnalyzer(_FakeBackend(), model_id=MODEL_ID)
    analyzer._processor_and_model = (processor, model)
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    Image.new("RGB", (8, 8), (255, 255, 255)).save(first)
    Image.new("RGB", (8, 8), (0, 0, 0)).save(second)

    report = analyzer.analyze_vlm_shadow(
        [first, second],
        calibrate_vlm_shadow(_calibration_input()),
        labels=tuple(LABELS),
    )

    assert report.image_count == 2
    assert report.text_prompt_count == 4
    assert model.image_calls == 1
    assert model.text_calls == 1
    assert processor.image_batches == 1
    assert processor.text_batches == 1
    assert processor.text_options == {
        "padding": "max_length",
        "max_length": 64,
        "truncation": True,
    }
    assert all(
        score.category in {"terrain", "lighting", "intent"}
        for frame in report.frames
        for score in frame.scores
    )
