from __future__ import annotations

import json
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import torch
from PIL import Image

from colorgraph.evaluation.semantic_runtime import (
    SEMANTIC_RUNTIME_MODEL_IDS,
    capture_semantic_runtime_observation,
)
from colorgraph.vision.base import MaskPrediction
from colorgraph.vision.semantic import (
    SemanticMaskProvider,
    load_semantic_label_mapping,
)

MODEL_REVISIONS = {
    "nvidia/segformer-b0-finetuned-ade-512-512": (
        "489d5cd81a0b59fab9b7ea758d3548ebe99677da"
    ),
    "nvidia/segformer-b5-finetuned-ade-640-640": (
        "739f5d4692954e4a185eac280dec1ba5a7d52f1d"
    ),
    "shi-labs/oneformer_ade20k_swin_large": (
        "4a5bac8e64f82681a12db2e151a4c2f4ce6092b2"
    ),
}
CHECKPOINT_SHA256 = "c" * 64


class _Backend:
    torch_device = torch.device("cpu")
    info = SimpleNamespace(runtime="cpu", name="Unit Test CPU")

    def inference_context(self, *, mixed_precision: bool = True):
        return nullcontext()


def _source_registry() -> Path:
    return Path(__file__).parents[2] / "docs" / (
        "formal-model-source-registry-v1.json"
    )


class _CompletedProvider:
    def __init__(
        self,
        backend,
        model_id: str,
        *,
        model_revision: str,
        label_mapping_path: str | Path,
        local_files_only: bool,
    ) -> None:
        assert backend.info.runtime == "cpu"
        assert local_files_only
        assert MODEL_REVISIONS[model_id] == model_revision
        self.model_id = model_id
        self.model_revision = model_revision
        _, self.label_mapping_sha256 = load_semantic_label_mapping(
            label_mapping_path
        )

    def predict_many(self, image: Image.Image, targets: list[str]):
        assert image.mode == "RGB"
        predictions: dict[str, MaskPrediction] = {}
        for index, target in enumerate(targets, start=1):
            mask = np.full(
                (image.height, image.width),
                index / 10,
                dtype=np.float32,
            )
            predictions[target] = MaskPrediction(
                target=target,
                mask=mask,
                confidence=index / 10,
                metadata={
                    "model_revision": self.model_revision,
                    "checkpoint_sha256": CHECKPOINT_SHA256,
                    "checkpoint_hash_kind": (
                        "colorgraph.torch-state-dict/v1"
                    ),
                    "label_mapping_sha256": (
                        self.label_mapping_sha256
                    ),
                    "probability_threshold": 0.30,
                    "class_ids": [index],
                    "class_labels": [f"class-{index}"],
                    "class_mapping_status": "resolved",
                },
                score_semantics=(
                    "mean_model_probability_over_selected_pixels"
                ),
            )
        return predictions

    def release_model(self) -> int:
        return 1


class _BlockedProvider:
    def __init__(self, *args, **kwargs) -> None:
        raise OSError("upstream error text must not be persisted")


def test_semantic_runtime_records_completed_exact_local_run(
    tmp_path: Path,
) -> None:
    frame = tmp_path / "frame.png"
    Image.new("RGB", (12, 8), (80, 120, 160)).save(frame)
    output = tmp_path / "semantic-runtime.json"

    report = capture_semantic_runtime_observation(
        _source_registry(),
        "current_segformer_b0",
        [frame],
        output,
        backend=_Backend(),
        provider_factory=_CompletedProvider,
    )

    assert report.status == "completed"
    assert report.model_id == SEMANTIC_RUNTIME_MODEL_IDS[
        "current_segformer_b0"
    ]
    assert report.requested_model_revision == MODEL_REVISIONS[
        report.model_id
    ]
    assert report.resolved_model_revision == (
        report.requested_model_revision
    )
    assert report.checkpoint_sha256 == CHECKPOINT_SHA256
    assert report.local_files_only
    assert not report.network_access_allowed
    assert not report.gold_quality_claim_authorized
    assert not report.commercial_default_authorized
    assert report.processing_fps is not None
    assert report.processing_fps > 0
    assert len(report.predictions) == 1
    assert len(report.predictions[0].targets) == 3
    assert output.is_file()


@pytest.mark.parametrize(
    "candidate_id",
    ("segformer_b5", "oneformer_ade20k_swin_large"),
)
def test_semantic_runtime_persists_sanitized_local_cache_blocker(
    tmp_path: Path,
    candidate_id: str,
) -> None:
    frame = tmp_path / "frame.png"
    Image.new("RGB", (8, 8), (20, 40, 60)).save(frame)
    output = tmp_path / "semantic-blocked.json"

    report = capture_semantic_runtime_observation(
        _source_registry(),
        candidate_id,
        [frame],
        output,
        backend=_Backend(),
        provider_factory=_BlockedProvider,
    )

    assert report.status == "blocked"
    assert report.blocker == (
        "model_or_runtime_dependency_not_available_locally"
    )
    assert report.error == (
        "OSError: exact model/revision is unavailable in the local cache"
    )
    assert "upstream" not in report.error
    assert not report.predictions
    assert report.processing_fps is None
    persisted = json.loads(output.read_text(encoding="utf-8"))
    assert persisted["status"] == "blocked"
    assert persisted["commercial_default_authorized"] is False


def test_semantic_runtime_rejects_registry_model_revision_mismatch(
    tmp_path: Path,
) -> None:
    manifest = json.loads(
        _source_registry().read_text(encoding="utf-8")
    )
    candidate = next(
        item
        for item in manifest["candidates"]
        if item["candidate_id"] == "segformer_b5"
    )
    candidate["weights"]["url"] = (
        "https://huggingface.co/nvidia/"
        "segformer-b5-finetuned-ade-640-640/tree/"
        + "0" * 40
    )
    modified = tmp_path / "modified-registry.json"
    modified.write_text(json.dumps(manifest), encoding="utf-8")
    frame = tmp_path / "frame.png"
    Image.new("RGB", (8, 8), (1, 2, 3)).save(frame)

    with pytest.raises(ValueError, match="does not bind"):
        capture_semantic_runtime_observation(
            modified,
            "segformer_b5",
            [frame],
            tmp_path / "must-not-exist.json",
            backend=_Backend(),
            provider_factory=_CompletedProvider,
        )


def test_semantic_provider_forwards_offline_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from transformers import (
        AutoImageProcessor,
        AutoModelForSemanticSegmentation,
    )

    calls: list[tuple[str, str, dict[str, object]]] = []

    class MinimalModel(torch.nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.weight = torch.nn.Parameter(torch.ones(1))
            self.config = SimpleNamespace(
                _commit_hash=MODEL_REVISIONS[
                    SEMANTIC_RUNTIME_MODEL_IDS[
                        "current_segformer_b0"
                    ]
                ]
            )

    def load_processor(
        model_id: str,
        **options: object,
    ) -> object:
        calls.append(("processor", model_id, options))
        return object()

    def load_model(
        model_id: str,
        **options: object,
    ) -> MinimalModel:
        calls.append(("model", model_id, options))
        return MinimalModel()

    monkeypatch.setattr(
        AutoImageProcessor,
        "from_pretrained",
        load_processor,
    )
    monkeypatch.setattr(
        AutoModelForSemanticSegmentation,
        "from_pretrained",
        load_model,
    )
    model_id = SEMANTIC_RUNTIME_MODEL_IDS[
        "current_segformer_b0"
    ]
    revision = MODEL_REVISIONS[model_id]
    provider = SemanticMaskProvider(
        _Backend(),
        model_id=model_id,
        model_revision=revision,
        local_files_only=True,
    )

    resource = provider._load_resource()

    assert resource.model_revision == revision
    assert resource.checkpoint_sha256 is not None
    assert len(resource.checkpoint_sha256) == 64
    assert [call[0] for call in calls] == ["processor", "model"]
    assert all(call[2]["revision"] == revision for call in calls)
    assert all(call[2]["local_files_only"] is True for call in calls)


def test_oneformer_provider_forwards_offline_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from transformers import (
        OneFormerForUniversalSegmentation,
        OneFormerProcessor,
    )

    calls: list[tuple[str, str, dict[str, object]]] = []
    model_id = SEMANTIC_RUNTIME_MODEL_IDS[
        "oneformer_ade20k_swin_large"
    ]
    revision = MODEL_REVISIONS[model_id]

    class MinimalModel(torch.nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.weight = torch.nn.Parameter(torch.ones(1))
            self.config = SimpleNamespace(_commit_hash=revision)

    def load_processor(
        requested_model_id: str,
        **options: object,
    ) -> object:
        calls.append(("processor", requested_model_id, options))
        return object()

    def load_model(
        requested_model_id: str,
        **options: object,
    ) -> MinimalModel:
        calls.append(("model", requested_model_id, options))
        return MinimalModel()

    monkeypatch.setattr(
        OneFormerProcessor,
        "from_pretrained",
        load_processor,
    )
    monkeypatch.setattr(
        OneFormerForUniversalSegmentation,
        "from_pretrained",
        load_model,
    )
    from colorgraph.vision.semantic import (
        OneFormerSemanticMaskProvider,
    )

    provider = OneFormerSemanticMaskProvider(
        _Backend(),
        model_id=model_id,
        model_revision=revision,
        local_files_only=True,
    )

    resource = provider._load_resource()

    assert resource.model_revision == revision
    assert resource.checkpoint_sha256 is not None
    assert len(resource.checkpoint_sha256) == 64
    assert [call[0] for call in calls] == ["processor", "model"]
    assert all(call[2]["revision"] == revision for call in calls)
    assert all(call[2]["local_files_only"] is True for call in calls)
