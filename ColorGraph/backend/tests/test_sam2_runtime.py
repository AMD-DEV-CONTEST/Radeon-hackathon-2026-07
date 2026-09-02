from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest
import torch
from PIL import Image

from colorgraph.evaluation import sam2_runtime
from colorgraph.evaluation.sam2_runtime import (
    SAM2_MODEL_ID,
    Sam2VideoRun,
    capture_sam2_runtime_observation,
)
from colorgraph.vision.base import MaskPrediction

SAM_CODE_REVISION = "2b90b9f5ceec907a1c18123530e92e794ad901a4"
SAM_MODEL_REVISION = "ee5bba1d82bb8749febdf90f45e84b687142ba03"
SEMANTIC_REVISION = "4a5bac8e64f82681a12db2e151a4c2f4ce6092b2"
SEMANTIC_CHECKPOINT_SHA256 = "a" * 64
SAM_FILE_SHA256 = "b" * 64
SAM_STATE_SHA256 = "c" * 64


class _Backend:
    torch_device = torch.device("cpu")
    info = SimpleNamespace(runtime="cpu", name="Unit Test CPU")

    def inference_context(self, *, mixed_precision: bool = True):
        return nullcontext()


class _SemanticProvider:
    def __init__(
        self,
        backend,
        model_id: str,
        *,
        model_revision: str,
        local_files_only: bool,
    ) -> None:
        assert backend.info.runtime == "cpu"
        assert model_id == "shi-labs/oneformer_ade20k_swin_large"
        assert model_revision == SEMANTIC_REVISION
        assert local_files_only

    def predict_many(
        self,
        image: Image.Image,
        targets: list[str],
    ) -> dict[str, MaskPrediction]:
        assert targets == ["mountain"]
        mask = np.full((image.height, image.width), 0.1, dtype=np.float32)
        mask[:, : image.width // 2] = 0.9
        return {
            "mountain": MaskPrediction(
                target="mountain",
                mask=mask,
                confidence=0.8,
                score_semantics="unit-test-probability",
                metadata={
                    "model_revision": SEMANTIC_REVISION,
                    "checkpoint_sha256": SEMANTIC_CHECKPOINT_SHA256,
                    "checkpoint_hash_kind": (
                        "colorgraph.torch-state-dict/v1"
                    ),
                    "probability_threshold": 0.5,
                },
            )
        }

    def release_model(self) -> int:
        return 1


class _CompletedRunner:
    def run(
        self,
        frames: list[Image.Image],
        anchor_mask: np.ndarray,
    ) -> Sam2VideoRun:
        assert anchor_mask.dtype == np.uint8
        assert float(anchor_mask.mean()) == pytest.approx(0.5)
        masks = np.full(
            (len(frames), frames[0].height, frames[0].width),
            0.1,
            dtype=np.float32,
        )
        masks[:, :, : frames[0].width // 2] = 0.9
        return Sam2VideoRun(
            masks=masks,
            object_presence_probabilities=np.full(
                len(frames),
                0.95,
                dtype=np.float32,
            ),
            resolved_revision=SAM_MODEL_REVISION,
            checkpoint_file_sha256=SAM_FILE_SHA256,
            checkpoint_state_sha256=SAM_STATE_SHA256,
            model_load_seconds=0.1,
            propagation_seconds=0.2,
            peak_gpu_memory_mb=0,
            memory_growth_mb=0,
            precision="float32",
        )


class _BlockedRunner:
    def run(
        self,
        frames: list[Image.Image],
        anchor_mask: np.ndarray,
    ) -> Sam2VideoRun:
        raise OSError("unit-test checkpoint unavailable")


def _source_registry() -> Path:
    return Path(__file__).parents[2] / "docs" / (
        "formal-model-source-registry-v1.json"
    )


def _write_video(path: Path) -> None:
    writer = cv2.VideoWriter(
        str(path),
        cv2.VideoWriter_fourcc(*"MJPG"),
        4,
        (16, 8),
    )
    assert writer.isOpened()
    for index in range(4):
        writer.write(
            np.full((8, 16, 3), 40 + index * 20, dtype=np.uint8)
        )
    writer.release()


def _repository(tmp_path: Path) -> Path:
    repository = tmp_path / "sam2"
    repository.mkdir()
    (repository / "LICENSE").write_text(
        "Apache License 2.0",
        encoding="utf-8",
    )
    return repository


def _runner_factory(backend, model_id: str, revision: str):
    assert backend.info.runtime == "cpu"
    assert model_id == SAM2_MODEL_ID
    assert revision == SAM_MODEL_REVISION
    return _CompletedRunner()


def test_sam2_runtime_records_exact_semantic_anchor_and_masks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    video = tmp_path / "clip.avi"
    masks = tmp_path / "masks.npz"
    report_path = tmp_path / "report.json"
    _write_video(video)
    repository = _repository(tmp_path)
    monkeypatch.setattr(
        sam2_runtime,
        "_repository_revision",
        lambda _: SAM_CODE_REVISION,
    )

    report = capture_sam2_runtime_observation(
        _source_registry(),
        repository,
        video,
        masks,
        report_path,
        semantic_candidate_id="oneformer_ade20k_swin_large",
        semantic_target="mountain",
        maximum_frames=None,
        backend=_Backend(),
        semantic_provider_factory=_SemanticProvider,
        runner_factory=_runner_factory,
    )

    assert report.status == "completed"
    assert report.resolved_code_revision == SAM_CODE_REVISION
    assert report.resolved_semantic_revision == SEMANTIC_REVISION
    assert report.semantic_checkpoint_sha256 == SEMANTIC_CHECKPOINT_SHA256
    assert report.anchor_probability_threshold == 0.5
    assert report.anchor_selected_fraction == pytest.approx(0.5)
    assert report.resolved_sam_revision == SAM_MODEL_REVISION
    assert report.sam_checkpoint_file_sha256 == SAM_FILE_SHA256
    assert report.sam_checkpoint_state_sha256 == SAM_STATE_SHA256
    assert report.masks_shape == [4, 8, 16]
    assert len(report.frames) == 4
    assert report.mean_adjacent_binary_iou == pytest.approx(1)
    assert report.gold_quality_claim_authorized is False
    assert report.production_default_authorized is False
    assert masks.is_file()
    assert report_path.is_file()
    with np.load(masks) as archive:
        assert archive["masks"].shape == (4, 8, 16)
        assert archive["masks"].dtype == np.float32


def test_sam2_runtime_persists_blocked_model_without_stale_masks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    video = tmp_path / "clip.avi"
    masks = tmp_path / "masks.npz"
    report_path = tmp_path / "report.json"
    _write_video(video)
    repository = _repository(tmp_path)
    monkeypatch.setattr(
        sam2_runtime,
        "_repository_revision",
        lambda _: SAM_CODE_REVISION,
    )

    report = capture_sam2_runtime_observation(
        _source_registry(),
        repository,
        video,
        masks,
        report_path,
        backend=_Backend(),
        semantic_provider_factory=_SemanticProvider,
        runner_factory=lambda *_: _BlockedRunner(),
    )

    assert report.status == "blocked"
    assert report.blocker == (
        "model_or_runtime_dependency_not_available_locally"
    )
    assert report.frames == []
    assert report.masks_sha256 is None
    assert not masks.exists()
    assert report_path.is_file()


def test_sam2_binary_iou_handles_empty_and_disjoint_masks() -> None:
    empty = np.zeros((3, 4), dtype=np.float32)
    left = empty.copy()
    right = empty.copy()
    left[:, :2] = 1
    right[:, 2:] = 1

    assert sam2_runtime._binary_iou(empty, empty) == 1
    assert sam2_runtime._binary_iou(left, right) == 0
