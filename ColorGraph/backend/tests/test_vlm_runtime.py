from __future__ import annotations

import hashlib
import json
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest
import torch
from PIL import Image

from colorgraph.agent.scene_understanding import LocalSceneAnalyzer
from colorgraph.agent.vlm_shadow import (
    VLMCalibrationInput,
    calibrate_vlm_shadow,
    score_vlm_shadow_embeddings,
)
from colorgraph.evaluation.vlm_runtime import (
    capture_vlm_runtime_observation,
)

MODEL_REVISION = "1" * 40


class _Backend:
    torch_device = torch.device("cpu")
    info = SimpleNamespace(runtime="cpu", name="Unit Test CPU")

    def inference_context(self, *, mixed_precision: bool = True):
        return nullcontext()


def _source_fixture() -> Path:
    return (
        Path(__file__).parent
        / "fixtures"
        / "evaluation"
        / "vlm_shadow_calibration_v1.json"
    )


def _calibration_artifacts(tmp_path: Path) -> tuple[Path, Path]:
    source_path = _source_fixture()
    source = VLMCalibrationInput.model_validate_json(
        source_path.read_bytes()
    )
    calibration = calibrate_vlm_shadow(source)
    calibration_path = tmp_path / "calibration.json"
    calibration_path.write_text(
        calibration.model_dump_json(indent=2),
        encoding="utf-8",
    )
    return calibration_path, source_path


def _frame_sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class _CompletedAnalyzer:
    def __init__(
        self,
        backend,
        model_id: str,
        model_revision: str,
        *,
        local_files_only: bool,
    ) -> None:
        assert backend.info.runtime == "cpu"
        assert model_revision == MODEL_REVISION
        assert local_files_only
        self.model_id = model_id
        self.model_revision = model_revision
        self.released = False

    def analyze_vlm_shadow(self, frame_paths, calibration, *, labels):
        dimension = len(labels)
        image_features = torch.zeros((len(frame_paths), dimension))
        image_features[:, 0] = 1
        return score_vlm_shadow_embeddings(
            image_features,
            torch.eye(dimension),
            frame_paths=[str(Path(path).resolve()) for path in frame_paths],
            frame_sha256=[_frame_sha256(path) for path in frame_paths],
            labels=labels,
            calibration=calibration,
            model_id=self.model_id,
            model_revision=self.model_revision,
            logit_scale=8,
            logit_bias=0,
        )

    def release_model(self) -> int:
        self.released = True
        return 1


class _BlockedAnalyzer(_CompletedAnalyzer):
    def analyze_vlm_shadow(self, frame_paths, calibration, *, labels):
        raise OSError("requested revision is absent from the local cache")


def test_vlm_runtime_observation_records_completed_local_run(
    tmp_path: Path,
) -> None:
    calibration_path, source_path = _calibration_artifacts(tmp_path)
    frame = tmp_path / "frame.png"
    Image.new("RGB", (8, 8), (80, 120, 160)).save(frame)
    output = tmp_path / "runtime-observation.json"

    report = capture_vlm_runtime_observation(
        calibration_path,
        source_path,
        [frame],
        output,
        backend=_Backend(),
        analyzer_factory=_CompletedAnalyzer,
    )

    assert report.status == "completed"
    assert report.local_files_only
    assert not report.network_access_allowed
    assert report.processing_fps is not None
    assert report.processing_fps > 0
    assert report.shadow_report is not None
    assert report.shadow_report.image_count == 1
    assert report.peak_gpu_memory_scope == "not_applicable"
    assert output.is_file()


def test_vlm_runtime_observation_persists_local_cache_blocker(
    tmp_path: Path,
) -> None:
    calibration_path, source_path = _calibration_artifacts(tmp_path)
    frame = tmp_path / "frame.png"
    Image.new("RGB", (8, 8), (40, 60, 80)).save(frame)
    output = tmp_path / "runtime-blocked.json"

    report = capture_vlm_runtime_observation(
        calibration_path,
        source_path,
        [frame],
        output,
        backend=_Backend(),
        analyzer_factory=_BlockedAnalyzer,
    )

    assert report.status == "blocked"
    assert report.blocker == (
        "model_or_runtime_dependency_not_available_locally"
    )
    assert "local cache" in str(report.error)
    assert report.shadow_report is None
    assert report.processing_fps is None
    persisted = json.loads(output.read_text(encoding="utf-8"))
    assert persisted["status"] == "blocked"
    assert persisted["default_model_authorized"] is False


def test_vlm_runtime_observation_recomputes_calibration_source(
    tmp_path: Path,
) -> None:
    calibration_path, source_path = _calibration_artifacts(tmp_path)
    modified = json.loads(source_path.read_text(encoding="utf-8"))
    modified["examples"][0]["raw_logits"]["terrain.mountain"] = 1.5
    modified_source = tmp_path / "modified-source.json"
    modified_source.write_text(
        json.dumps(modified),
        encoding="utf-8",
    )
    frame = tmp_path / "frame.png"
    Image.new("RGB", (8, 8), (1, 2, 3)).save(frame)

    with pytest.raises(ValueError, match="does not match"):
        capture_vlm_runtime_observation(
            calibration_path,
            modified_source,
            [frame],
            tmp_path / "must-not-exist.json",
            backend=_Backend(),
            analyzer_factory=_CompletedAnalyzer,
        )


def test_local_scene_analyzer_forwards_offline_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from transformers import AutoModel, AutoProcessor

    calls: list[tuple[str, str, dict[str, object]]] = []

    class MinimalModel(torch.nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.weight = torch.nn.Parameter(torch.ones(1))
            self.config = SimpleNamespace(_commit_hash=MODEL_REVISION)

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

    monkeypatch.setattr(AutoProcessor, "from_pretrained", load_processor)
    monkeypatch.setattr(AutoModel, "from_pretrained", load_model)
    analyzer = LocalSceneAnalyzer(
        _Backend(),
        model_id="google/siglip2-base-patch16-224",
        model_revision=MODEL_REVISION,
        local_files_only=True,
    )

    resource = analyzer._load_resource()

    assert resource.model_revision == MODEL_REVISION
    assert resource.checkpoint_sha256 is not None
    assert len(resource.checkpoint_sha256) == 64
    assert [call[0] for call in calls] == ["processor", "model"]
    assert all(call[2]["revision"] == MODEL_REVISION for call in calls)
    assert all(call[2]["local_files_only"] is True for call in calls)
