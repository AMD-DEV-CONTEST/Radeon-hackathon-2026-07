from __future__ import annotations

import hashlib
from pathlib import Path

import cv2
import numpy as np
import pytest

from colorgraph.evaluation import sea_raft_runtime
from colorgraph.evaluation.sea_raft_runtime import (
    SeaRaftBridgeResult,
    capture_sea_raft_runtime_observation,
)

CODE_REVISION = "9137517ba24e628442aec097d3afe71d03503b75"
MODEL_REVISION = "eb97ef34ba5d856c3fa2cdcd073150c057ac8b69"
STATE_SHA256 = "d" * 64


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
        frame = np.full((8, 16, 3), 30 + index * 20, dtype=np.uint8)
        writer.write(frame)
    writer.release()


def _installation(
    tmp_path: Path,
) -> tuple[Path, Path, Path, str]:
    repository = tmp_path / "SEA-RAFT"
    config = repository / "config" / "eval" / "spring-M.json"
    config.parent.mkdir(parents=True)
    config.write_text('{"scale": -1, "iters": 4}', encoding="utf-8")
    (repository / "LICENSE").write_text(
        "BSD 3-Clause",
        encoding="utf-8",
    )
    snapshot = tmp_path / MODEL_REVISION
    snapshot.mkdir()
    (snapshot / "model.safetensors").write_bytes(b"checkpoint")
    torch_home = tmp_path / "torch-home"
    auxiliary = (
        torch_home / "hub" / "checkpoints" / "resnet34-b627a593.pth"
    )
    auxiliary.parent.mkdir(parents=True)
    auxiliary.write_bytes(b"resnet")
    auxiliary_sha256 = hashlib.sha256(b"resnet").hexdigest()
    return repository, snapshot, torch_home, auxiliary_sha256


class _CompletedRunner:
    def __init__(self, checkpoint: Path, config: Path) -> None:
        self.checkpoint = checkpoint
        self.config = config

    def run(
        self,
        video: Path,
        output: Path,
        maximum_pairs: int | None,
    ) -> SeaRaftBridgeResult:
        assert video.is_file()
        assert maximum_pairs is None
        pair_count = 3
        flows = np.zeros((pair_count, 2, 8, 16), dtype=np.float32)
        flows[:, 0] = 0.25
        uncertainties = np.full(
            (pair_count, 8, 16),
            1.2,
            dtype=np.float32,
        )
        occlusions = np.zeros(
            (pair_count, 8, 16),
            dtype=np.float32,
        )
        occlusions[:, :, -1] = 1
        np.savez_compressed(output, marker=np.asarray(1))
        return SeaRaftBridgeResult(
            flows=flows,
            uncertainties=uncertainties,
            occlusions=occlusions,
            pair_seconds=np.full(pair_count, 0.1, dtype=np.float64),
            runtime="cpu",
            precision="float32",
            model_load_seconds=0.2,
            inference_seconds=0.3,
            peak_cpu_memory_mb=100,
            peak_gpu_memory_mb=0,
            memory_growth_mb=0,
            checkpoint_file_sha256=sea_raft_runtime._sha256(
                self.checkpoint
            ),
            checkpoint_state_sha256=STATE_SHA256,
            config_sha256=sea_raft_runtime._sha256(self.config),
        )


class _BlockedRunner:
    def run(
        self,
        video: Path,
        output: Path,
        maximum_pairs: int | None,
    ) -> SeaRaftBridgeResult:
        raise OSError("unit-test runtime unavailable")


def test_sea_raft_runtime_records_flow_uncertainty_and_occlusion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    video = tmp_path / "clip.avi"
    _write_video(video)
    repository, snapshot, torch_home, auxiliary_sha256 = _installation(
        tmp_path
    )
    output = tmp_path / "flow.npz"
    report_path = tmp_path / "report.json"
    monkeypatch.setattr(
        sea_raft_runtime,
        "_repository_revision",
        lambda _: CODE_REVISION,
    )
    monkeypatch.setattr(
        sea_raft_runtime,
        "SEA_RAFT_RESNET34_SHA256",
        auxiliary_sha256,
    )

    def runner_factory(repository, snapshot, config, torch_home, python):
        return _CompletedRunner(
            snapshot / "model.safetensors",
            config,
        )

    report = capture_sea_raft_runtime_observation(
        _source_registry(),
        repository,
        snapshot,
        torch_home,
        video,
        output,
        report_path,
        maximum_pairs=None,
        runner_factory=runner_factory,
    )

    assert report.status == "completed"
    assert report.resolved_code_revision == CODE_REVISION
    assert report.resolved_model_revision == MODEL_REVISION
    assert report.checkpoint_state_sha256 == STATE_SHA256
    assert report.flows_shape == [3, 2, 8, 16]
    assert report.uncertainties_shape == [3, 8, 16]
    assert report.occlusions_shape == [3, 8, 16]
    assert report.pair_fps == pytest.approx(10)
    assert len(report.pairs) == 3
    assert report.pairs[0].mean_flow_magnitude_pixels == pytest.approx(
        0.25
    )
    assert report.pairs[0].mean_expected_laplace_scale == pytest.approx(
        1.2
    )
    assert report.pairs[0].occluded_fraction == pytest.approx(1 / 16)
    assert report.gold_quality_claim_authorized is False
    assert report.production_default_authorized is False
    assert output.is_file()
    assert report_path.is_file()


def test_sea_raft_runtime_persists_blocked_bridge_without_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    video = tmp_path / "clip.avi"
    _write_video(video)
    repository, snapshot, torch_home, auxiliary_sha256 = _installation(
        tmp_path
    )
    output = tmp_path / "flow.npz"
    report_path = tmp_path / "report.json"
    monkeypatch.setattr(
        sea_raft_runtime,
        "_repository_revision",
        lambda _: CODE_REVISION,
    )
    monkeypatch.setattr(
        sea_raft_runtime,
        "SEA_RAFT_RESNET34_SHA256",
        auxiliary_sha256,
    )

    report = capture_sea_raft_runtime_observation(
        _source_registry(),
        repository,
        snapshot,
        torch_home,
        video,
        output,
        report_path,
        maximum_pairs=None,
        runner_factory=lambda *_: _BlockedRunner(),
    )

    assert report.status == "blocked"
    assert report.blocker == (
        "model_or_runtime_dependency_not_available_locally"
    )
    assert report.pairs == []
    assert report.output_sha256 is None
    assert not output.exists()
    assert report_path.is_file()


def test_sea_raft_array_hash_binds_shape_and_values() -> None:
    first = np.zeros((2, 3), dtype=np.float32)
    second = np.zeros((3, 2), dtype=np.float32)
    third = first.copy()
    third[0, 0] = 1

    assert sea_raft_runtime._array_sha256(first) != (
        sea_raft_runtime._array_sha256(second)
    )
    assert sea_raft_runtime._array_sha256(first) != (
        sea_raft_runtime._array_sha256(third)
    )
