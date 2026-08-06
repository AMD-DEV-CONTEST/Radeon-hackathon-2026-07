import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import torch
from PIL import Image
from pydantic import ValidationError

from colorgraph.agent.planner import TARGET_PATTERNS
from colorgraph.devices import TorchComputeBackend
from colorgraph.vision.semantic import (
    DEFAULT_LABEL_MAPPING_PATH,
    SEMANTIC_MAPPING_SCHEMA,
    OneFormerSemanticMaskProvider,
    SemanticMaskProvider,
    load_semantic_label_mapping,
    resolve_semantic_class_ids,
)


class _FakeProcessor:
    def __call__(self, **_: object) -> dict[str, torch.Tensor]:
        return {"pixel_values": torch.zeros((1, 3, 2, 4), dtype=torch.float32)}


class _FakeModel:
    def __init__(self) -> None:
        self.config = SimpleNamespace(
            id2label={0: "tree", 1: "earth"},
            _commit_hash="fake-model-revision",
        )

    def __call__(self, **_: object) -> SimpleNamespace:
        tree = torch.tensor([[8.0, 8.0, -8.0, -8.0], [8.0, 8.0, -8.0, -8.0]])
        earth = -tree
        return SimpleNamespace(logits=torch.stack((tree, earth)).unsqueeze(0))


class _FakeOneFormerProcessor:
    def __call__(
        self,
        *,
        images: Image.Image,
        task_inputs: list[str],
        return_tensors: str,
    ) -> dict[str, torch.Tensor]:
        assert images.mode == "RGB"
        assert task_inputs == ["semantic"]
        assert return_tensors == "pt"
        return {
            "pixel_values": torch.zeros(
                (1, 3, 2, 4),
                dtype=torch.float32,
            ),
            "task_inputs": torch.ones((1, 4), dtype=torch.int64),
        }

    def post_process_semantic_segmentation(
        self,
        outputs: object,
        *,
        target_sizes: list[tuple[int, int]],
        return_segmentation_scores: bool,
    ) -> list[SimpleNamespace]:
        assert outputs is not None
        assert target_sizes == [(2, 4)]
        assert return_segmentation_scores
        tree = torch.tensor(
            [[0.9, 0.9, 0.1, 0.1], [0.9, 0.9, 0.1, 0.1]]
        )
        water = 1 - tree
        return [
            SimpleNamespace(
                segmentation_scores=torch.stack((tree, water))
            )
        ]


class _FakeOneFormerModel:
    def __init__(self) -> None:
        self.config = SimpleNamespace(
            id2label={0: "tree", 1: "water"},
            _commit_hash="fake-oneformer-revision",
        )

    def __call__(self, **_: object) -> SimpleNamespace:
        return SimpleNamespace(class_queries_logits=torch.ones(1))


def test_default_mapping_separates_landscape_classes_without_alias_overlap() -> None:
    mapping, digest = load_semantic_label_mapping()
    targets = {target: set(aliases) for target, aliases in mapping.targets.items()}

    assert mapping.schema_version == SEMANTIC_MAPPING_SCHEMA
    assert len(digest) == 64
    assert "earth" in targets["land"]
    assert "earth" not in targets["vegetation"]
    assert targets["mountain"] == {"mountain", "hill"}
    assert targets["rock"] == {"rock", "stone"}
    assert targets["cliff"] == {"cliff"}
    assert targets["sand"] == {"sand"}
    all_aliases = [alias for aliases in targets.values() for alias in aliases]
    assert len(all_aliases) == len(set(all_aliases))


def test_mapping_rejects_alias_that_expands_two_targets(tmp_path: Path) -> None:
    payload = json.loads(DEFAULT_LABEL_MAPPING_PATH.read_text(encoding="utf-8"))
    payload["targets"]["vegetation"].append("earth")
    invalid = tmp_path / "invalid-semantic-map.json"
    invalid.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValidationError, match="belongs to both"):
        load_semantic_label_mapping(invalid)


def test_model_label_cannot_resolve_to_multiple_target_boundaries() -> None:
    with pytest.raises(ValueError, match="multiple semantic targets"):
        resolve_semantic_class_ids(
            {0: "earth, tree"},
            {
                "vegetation": frozenset({"tree"}),
                "land": frozenset({"earth"}),
            },
        )


def test_provider_resolves_earth_and_tree_to_separate_masks_with_score_evidence() -> None:
    provider = SemanticMaskProvider(
        TorchComputeBackend("cpu"),
        model_revision="a" * 40,
        probability_threshold=0.40,
    )
    provider.__dict__["_processor_and_model"] = (_FakeProcessor(), _FakeModel())
    assert provider.model_revision == "a" * 40

    predictions = provider.predict_many(
        Image.fromarray(np.full((2, 4, 3), 128, dtype=np.uint8), mode="RGB"),
        ["vegetation", "land", "cliff"],
    )

    assert provider._target_class_ids["vegetation"] == [0]
    assert provider._target_class_ids["land"] == [1]
    assert not np.allclose(
        predictions["vegetation"].mask,
        predictions["land"].mask,
    )
    for target, expected_label in (("vegetation", "tree"), ("land", "earth")):
        prediction = predictions[target]
        assert prediction.confidence > 0.99
        assert prediction.score_semantics == (
            "mean_model_probability_over_selected_pixels"
        )
        assert prediction.metadata["confidence_is_accuracy"] is False
        assert prediction.metadata["probability_threshold"] == 0.40
        assert prediction.metadata["class_labels"] == [expected_label]
        assert prediction.metadata["class_mapping_status"] == "resolved"
        assert prediction.metadata["model_revision"] == "fake-model-revision"
        assert prediction.metadata["label_mapping_version"] == "ade20k-landscape-v2"
        assert len(str(prediction.metadata["label_mapping_sha256"])) == 64
    assert predictions["cliff"].confidence == 0
    assert predictions["cliff"].metadata["class_ids"] == []
    assert predictions["cliff"].metadata["class_mapping_status"] == (
        "model_class_missing"
    )


def test_oneformer_provider_uses_semantic_task_and_score_maps() -> None:
    provider = OneFormerSemanticMaskProvider(
        TorchComputeBackend("cpu"),
        model_revision="b" * 40,
        probability_threshold=0.40,
    )
    provider.__dict__["_processor_and_model"] = (
        _FakeOneFormerProcessor(),
        _FakeOneFormerModel(),
    )

    predictions = provider.predict_many(
        Image.fromarray(
            np.full((2, 4, 3), 128, dtype=np.uint8),
            mode="RGB",
        ),
        ["vegetation", "water", "cliff"],
    )

    assert predictions["vegetation"].confidence == pytest.approx(0.9)
    assert predictions["water"].confidence == pytest.approx(0.9)
    assert predictions["cliff"].confidence == 0
    assert predictions["vegetation"].metadata[
        "oneformer_task_input"
    ] == "semantic"
    assert predictions["vegetation"].metadata["model_revision"] == (
        "fake-oneformer-revision"
    )
    assert predictions["vegetation"].score_semantics == (
        "mean_postprocessed_semantic_probability_over_selected_pixels"
    )


@pytest.mark.parametrize(
    ("text", "target"),
    [
        ("cool the mountain", "mountain"),
        ("add texture to the rock", "rock"),
        ("protect the cliff", "cliff"),
        ("warm the earth", "land"),
        ("reduce saturation on sand", "sand"),
    ],
)
def test_planner_semantic_patterns_keep_terrain_targets_separate(
    text: str,
    target: str,
) -> None:
    matches = {
        candidate
        for candidate, pattern in TARGET_PATTERNS.items()
        if pattern.search(text)
    }

    assert matches == {target}
