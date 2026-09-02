from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from pathlib import Path

import cv2
import numpy as np
import pytest
import torch

from colorgraph.evaluation import autoshot_runtime
from colorgraph.evaluation.autoshot_runtime import (
    AutoShotBridgeResult,
    bind_autoshot_runtime_to_shot_bundle,
    capture_autoshot_runtime_observation,
)
from colorgraph.evaluation.shot_shadow import (
    ShotDatasetEvidence,
    ShotEvaluationItem,
    ShotEvent,
    ShotModelArtifacts,
    ShotModelRun,
    ShotShadowBundle,
)
from colorgraph.vision.autoshot_bridge import _positive_run_peaks
from colorgraph.vision.model_lifecycle import torch_state_dict_sha256

CODE_REVISION = "7" * 40


class _CompletedRunner:
    def __init__(
        self,
        checkpoint_file_sha256: str,
        checkpoint_state_sha256: str,
    ) -> None:
        self.checkpoint_file_sha256 = checkpoint_file_sha256
        self.checkpoint_state_sha256 = checkpoint_state_sha256

    def run(
        self,
        video: Path,
        threshold: float,
    ) -> AutoShotBridgeResult:
        assert video.is_file()
        assert threshold == pytest.approx(0.296)
        probability = np.full(60, 0.01, dtype=np.float32)
        probability[28:31] = [0.4, 0.95, 0.35]
        return AutoShotBridgeResult(
            single_frame_probability=probability,
            predicted_boundaries=np.asarray([29], dtype=np.int32),
            batch_seconds=np.asarray([0.02, 0.02], dtype=np.float64),
            runtime="cpu",
            device_name="Unit Test CPU",
            precision="float32",
            model_load_seconds=0.1,
            inference_seconds=0.04,
            peak_cpu_memory_mb=64,
            peak_gpu_memory_mb=0,
            memory_growth_mb=0,
            checkpoint_file_sha256=self.checkpoint_file_sha256,
            checkpoint_state_sha256=self.checkpoint_state_sha256,
            threshold=threshold,
        )


class _BlockedRunner:
    def run(
        self,
        video: Path,
        threshold: float,
    ) -> AutoShotBridgeResult:
        raise OSError("unit-test runtime unavailable")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_video(path: Path) -> None:
    writer = cv2.VideoWriter(
        str(path),
        cv2.VideoWriter_fourcc(*"MJPG"),
        10,
        (16, 8),
    )
    assert writer.isOpened()
    for index in range(60):
        writer.write(
            np.full((8, 16, 3), 30 if index < 30 else 220, dtype=np.uint8)
        )
    writer.release()


def _write_installation(
    tmp_path: Path,
) -> tuple[Path, Path, str]:
    repository = tmp_path / "AutoShot"
    repository.mkdir()
    (repository / "LICENSE").write_text("MIT", encoding="utf-8")
    state = OrderedDict(
        {
            "weight": torch.arange(6, dtype=torch.float32).reshape(2, 3),
            "counter": torch.tensor(2, dtype=torch.int64),
        }
    )
    checkpoint = repository / "ckpt_0_200_0.pth"
    torch.save({"net": state}, checkpoint)
    return repository, checkpoint, torch_state_dict_sha256(state)


def _write_registry(
    path: Path,
    checkpoint: Path,
    state_sha256: str,
) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": (
                    "colorgraph.shot-model-source-registry/v1"
                ),
                "checked_on": "2026-07-30",
                "candidates": [
                    {
                        "candidate_id": "autoshot",
                        "code": {
                            "url": "https://example.test/code",
                            "revision": CODE_REVISION,
                            "license_id": "MIT",
                            "commercial_use_allowed": True,
                            "redistribution_allowed": True,
                        },
                        "runtime_checkpoint": {
                            "documented_filename": "ckpt_0_200_0.pth",
                            "share_url": "https://example.test/share",
                            "retrieved_on": "2026-07-30",
                            "source_is_mutable": True,
                            "immutable_revision": None,
                            "file_sha256": _sha256(checkpoint),
                            "size_bytes": checkpoint.stat().st_size,
                            "loaded_state_sha256": state_sha256,
                            "hash_kind": (
                                "colorgraph.torch-state-dict/v1"
                            ),
                            "checkpoint_container_key": "net",
                            "state_entry_count": 2,
                            "strict_model_load_verified": True,
                            "upstream_declared_license_id": None,
                            "project_authorization": {
                                "authorization_id": (
                                    "user-authorized-project-use"
                                ),
                                "project_use_allowed": True,
                                "commercial_use_allowed": True,
                                "redistribution_allowed": False,
                            },
                        },
                        "identity_note": (
                            "Mutable upstream share, locally frozen identity."
                        ),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def test_autoshot_runtime_records_authorization_and_predictions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    video = tmp_path / "clip.avi"
    output = tmp_path / "predictions.npz"
    report_path = tmp_path / "report.json"
    registry = tmp_path / "registry.json"
    _write_video(video)
    repository, checkpoint, state_sha256 = _write_installation(tmp_path)
    _write_registry(registry, checkpoint, state_sha256)
    monkeypatch.setattr(
        autoshot_runtime,
        "_repository_revision",
        lambda _: CODE_REVISION,
    )

    report = capture_autoshot_runtime_observation(
        registry,
        repository,
        checkpoint,
        video,
        output,
        report_path,
        runner_factory=lambda *_: _CompletedRunner(
            _sha256(checkpoint),
            state_sha256,
        ),
    )

    assert report.status == "completed"
    assert report.resolved_code_revision == CODE_REVISION
    assert report.strict_model_load_verified
    assert report.project_use_authorized
    assert report.upstream_checkpoint_license_id is None
    assert not report.checkpoint_redistribution_authorized
    assert report.checkpoint_state_sha256 == state_sha256
    assert report.predicted_boundaries == [29]
    assert report.probability_shape == [60]
    assert report.inference_fps == pytest.approx(1500)
    assert report.gold_quality_claim_authorized is False
    assert report.production_default_authorized is False
    assert output.is_file()
    assert report_path.is_file()

    bundle = ShotShadowBundle(
        created_at="2026-07-30T00:00:00Z",
        dataset=ShotDatasetEvidence(
            evidence_class="engineering_fixture",
            test_frozen_at="2026-07-30T00:00:00Z",
            annotation_guideline_version="unit-test/v1",
        ),
        items=[
            ShotEvaluationItem(
                item_id="clip",
                source_group_id="unit-test",
                media_origin="procedural",
                media_sha256=_sha256(video),
                annotation_sha256="f" * 64,
                frame_count=60,
                fps=10,
                events=[
                    ShotEvent(
                        event_id="cut",
                        kind="hard_cut",
                        start_frame=29,
                        end_frame=29,
                    )
                ],
            )
        ],
        runs=[
            ShotModelRun(
                model_id="autoshot",
                status="blocked",
                artifacts=ShotModelArtifacts(
                    code_url="https://example.test/code",
                    code_license_id="MIT",
                    code_commercial_use_allowed=True,
                    source_revision=CODE_REVISION,
                    weights_required=True,
                    weights_url="https://example.test/share",
                    weights_license_id="user-authorized-project-use",
                    weights_commercial_use_allowed=True,
                    checkpoint_sha256=_sha256(checkpoint),
                ),
                blocker="unit-test pending runtime",
            )
        ],
    )
    bound = bind_autoshot_runtime_to_shot_bundle(
        bundle,
        report,
        item_id="clip",
    )
    assert bound.runs[0].status == "completed"
    assert bound.runs[0].observations[0].predicted_boundaries == [29]
    assert (
        bound.runs[0].artifacts.weights_license_id
        == "user-authorized-project-use"
    )


def test_autoshot_runtime_persists_blocker_without_predictions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    video = tmp_path / "clip.avi"
    output = tmp_path / "predictions.npz"
    report_path = tmp_path / "report.json"
    registry = tmp_path / "registry.json"
    _write_video(video)
    repository, checkpoint, state_sha256 = _write_installation(tmp_path)
    _write_registry(registry, checkpoint, state_sha256)
    monkeypatch.setattr(
        autoshot_runtime,
        "_repository_revision",
        lambda _: CODE_REVISION,
    )

    report = capture_autoshot_runtime_observation(
        registry,
        repository,
        checkpoint,
        video,
        output,
        report_path,
        runner_factory=lambda *_: _BlockedRunner(),
    )

    assert report.status == "blocked"
    assert report.blocker == (
        "model_or_runtime_dependency_not_available_locally"
    )
    assert report.predicted_boundaries == []
    assert report.output_sha256 is None
    assert not output.exists()
    assert report_path.is_file()


def test_autoshot_positive_runs_choose_probability_peak() -> None:
    probabilities = np.asarray(
        [0.1, 0.4, 0.9, 0.5, 0.1, 0.8, 0.2],
        dtype=np.float32,
    )

    assert _positive_run_peaks(probabilities, 0.296).tolist() == [2, 5]
