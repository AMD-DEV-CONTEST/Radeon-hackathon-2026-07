from __future__ import annotations

import hashlib
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest
import torch
from PIL import Image

from colorgraph.evaluation import cutie_runtime
from colorgraph.evaluation.cutie_runtime import (
    CUTIE_CHECKPOINT_MD5,
    CutieBridgeResult,
    capture_cutie_runtime_observation,
)
from colorgraph.vision.base import MaskPrediction

CUTIE_CODE_REVISION = "ec5cdd4cf16f75c73ad785a2f96fb97dbad4125a"
SEMANTIC_REVISION = "4a5bac8e64f82681a12db2e151a4c2f4ce6092b2"
SEMANTIC_CHECKPOINT_SHA256 = "a" * 64
CUTIE_STATE_SHA256 = "b" * 64
CUTIE_CONFIG_SHA256 = "c" * 64


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
    def __init__(
        self,
        checkpoint_sha256: str,
        resnet18_sha256: str,
        resnet50_sha256: str,
    ) -> None:
        self.checkpoint_sha256 = checkpoint_sha256
        self.resnet18_sha256 = resnet18_sha256
        self.resnet50_sha256 = resnet50_sha256

    def run(
        self,
        video: Path,
        anchor_mask: np.ndarray,
        maximum_frames: int | None,
        maximum_internal_size: int,
    ) -> CutieBridgeResult:
        assert video.is_file()
        assert maximum_frames is None
        assert maximum_internal_size == 360
        assert anchor_mask.dtype == np.uint8
        assert float(anchor_mask.mean()) == pytest.approx(0.5)
        masks = np.full((4, 8, 16), 0.1, dtype=np.float32)
        masks[:, :, :8] = 0.9
        return CutieBridgeResult(
            masks=masks,
            frame_seconds=np.full(4, 0.05, dtype=np.float64),
            runtime="cpu",
            precision="float32",
            model_load_seconds=0.1,
            inference_seconds=0.2,
            peak_cpu_memory_mb=64,
            peak_gpu_memory_mb=0,
            memory_growth_mb=0,
            checkpoint_file_md5=CUTIE_CHECKPOINT_MD5,
            checkpoint_file_sha256=self.checkpoint_sha256,
            checkpoint_state_sha256=CUTIE_STATE_SHA256,
            configuration_sha256=CUTIE_CONFIG_SHA256,
            resnet18_sha256=self.resnet18_sha256,
            resnet50_sha256=self.resnet50_sha256,
            maximum_internal_size=maximum_internal_size,
        )


class _BlockedRunner:
    def run(
        self,
        video: Path,
        anchor_mask: np.ndarray,
        maximum_frames: int | None,
        maximum_internal_size: int,
    ) -> CutieBridgeResult:
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
    repository = tmp_path / "Cutie"
    (repository / "weights").mkdir(parents=True)
    (repository / "resnet").mkdir()
    (repository / "LICENSE").write_text("MIT", encoding="utf-8")
    (repository / "weights" / "cutie-base-mega.pth").write_bytes(
        b"unit-test-cutie"
    )
    (repository / "resnet" / "resnet18-5c106cde.pth").write_bytes(
        b"unit-test-resnet18"
    )
    (repository / "resnet" / "resnet50-19c8e357.pth").write_bytes(
        b"unit-test-resnet50"
    )
    return repository


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_cutie_runtime_records_exact_anchor_weights_and_temporal_metrics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    video = tmp_path / "clip.avi"
    masks = tmp_path / "masks.npz"
    report_path = tmp_path / "report.json"
    _write_video(video)
    repository = _repository(tmp_path)
    weights = repository / "weights" / "cutie-base-mega.pth"
    resnet18 = repository / "resnet" / "resnet18-5c106cde.pth"
    resnet50 = repository / "resnet" / "resnet50-19c8e357.pth"
    resnet18_sha256 = _sha256(resnet18)
    resnet50_sha256 = _sha256(resnet50)
    monkeypatch.setattr(
        cutie_runtime,
        "_repository_revision",
        lambda _: CUTIE_CODE_REVISION,
    )
    monkeypatch.setattr(
        cutie_runtime,
        "_md5",
        lambda _: CUTIE_CHECKPOINT_MD5,
    )
    monkeypatch.setattr(
        cutie_runtime,
        "CUTIE_RESNET18_SHA256",
        resnet18_sha256,
    )
    monkeypatch.setattr(
        cutie_runtime,
        "CUTIE_RESNET50_SHA256",
        resnet50_sha256,
    )

    report = capture_cutie_runtime_observation(
        _source_registry(),
        repository,
        video,
        masks,
        report_path,
        semantic_candidate_id="oneformer_ade20k_swin_large",
        semantic_target="mountain",
        maximum_frames=None,
        maximum_internal_size=360,
        backend=_Backend(),
        semantic_provider_factory=_SemanticProvider,
        runner_factory=lambda *_: _CompletedRunner(
            _sha256(weights),
            resnet18_sha256,
            resnet50_sha256,
        ),
    )

    assert report.status == "completed"
    assert report.resolved_code_revision == CUTIE_CODE_REVISION
    assert report.resolved_semantic_revision == SEMANTIC_REVISION
    assert report.semantic_checkpoint_sha256 == SEMANTIC_CHECKPOINT_SHA256
    assert report.anchor_selected_fraction == pytest.approx(0.5)
    assert report.checkpoint_file_md5 == CUTIE_CHECKPOINT_MD5
    assert report.checkpoint_state_sha256 == CUTIE_STATE_SHA256
    assert report.masks_shape == [4, 8, 16]
    assert report.mean_adjacent_binary_iou == pytest.approx(1)
    assert report.final_anchor_binary_iou == pytest.approx(1)
    assert report.selected_fraction_drift == pytest.approx(0)
    assert report.weights_license_review_complete is False
    assert report.gold_quality_claim_authorized is False
    assert report.production_default_authorized is False
    assert masks.is_file()
    assert report_path.is_file()
    with np.load(masks) as archive:
        assert archive["masks"].shape == (4, 8, 16)
        assert archive["masks"].dtype == np.float32


def test_cutie_runtime_persists_blocker_without_stale_masks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    video = tmp_path / "clip.avi"
    masks = tmp_path / "masks.npz"
    report_path = tmp_path / "report.json"
    _write_video(video)
    repository = _repository(tmp_path)
    monkeypatch.setattr(
        cutie_runtime,
        "_repository_revision",
        lambda _: CUTIE_CODE_REVISION,
    )

    report = capture_cutie_runtime_observation(
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


def test_cutie_binary_iou_handles_empty_and_disjoint_masks() -> None:
    empty = np.zeros((3, 4), dtype=np.float32)
    left = empty.copy()
    right = empty.copy()
    left[:, :2] = 1
    right[:, 2:] = 1

    assert cutie_runtime._binary_iou(empty, empty) == 1
    assert cutie_runtime._binary_iou(left, right) == 0
