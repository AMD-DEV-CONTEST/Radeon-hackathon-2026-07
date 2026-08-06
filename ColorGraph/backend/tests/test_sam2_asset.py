from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import cv2
import numpy as np

from colorgraph.domain.grade_graph import (
    ColorSpace,
    MediaInfo,
    TimeRange,
)
from colorgraph.evaluation.sam2_asset import generate_sam2_mask_asset
from colorgraph.evaluation.sam2_runtime import Sam2VideoRun
from colorgraph.grading.mask_integrity import MaskVideoInspection
from colorgraph.services.graph_builder import build_initial_graph
from colorgraph.vision.base import MaskPrediction


class _SemanticProvider:
    provider_id = "shi-labs/oneformer_ade20k_swin_large"

    def __init__(self, *_args, **_kwargs) -> None:
        self.released = False

    def predict_many(self, image, targets):
        width, height = image.size
        mask = np.zeros((height, width), dtype=np.float32)
        mask[:, : width // 2] = 0.9
        return {
            target: MaskPrediction(
                target=target,
                mask=mask,
                confidence=0.9,
                score_semantics="fixture",
                metadata={
                    "model_revision": "4a5bac8e64f82681a12db2e151a4c2f4ce6092b2",
                    "checkpoint_sha256": "7" * 64,
                    "checkpoint_hash_kind": "colorgraph.torch-state-dict/v1",
                    "probability_threshold": 0.3,
                },
            )
            for target in targets
        }

    def release_model(self) -> None:
        self.released = True


class _Runner:
    def __init__(self, *_args, **_kwargs) -> None:
        pass

    def run(self, frames, anchor_mask):
        height, width = anchor_mask.shape
        masks = np.stack(
            [
                np.full(
                    (height, width),
                    0.25 + index * 0.05,
                    dtype=np.float32,
                )
                for index in range(len(frames))
            ]
        )
        return Sam2VideoRun(
            masks=masks,
            object_presence_probabilities=np.full(
                len(frames),
                0.8,
                dtype=np.float32,
            ),
            resolved_revision="e" * 40,
            checkpoint_file_sha256="f" * 64,
            checkpoint_state_sha256="1" * 64,
            model_load_seconds=0.1,
            propagation_seconds=float(len(frames)) / 10,
            peak_gpu_memory_mb=512,
            memory_growth_mb=32,
            precision="float32",
        )


def _write_video(path: Path, frame_count: int = 7) -> None:
    writer = cv2.VideoWriter(
        str(path),
        cv2.VideoWriter_fourcc(*"FFV1"),
        5,
        (32, 16),
    )
    assert writer.isOpened()
    for index in range(frame_count):
        frame = np.full((16, 32, 3), index * 20, dtype=np.uint8)
        writer.write(frame)
    writer.release()


def _write_registry(path: Path) -> None:
    source = json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "docs"
            / "formal-model-source-registry-v1.json"
        ).read_text(encoding="utf-8")
    )
    for candidate in source["candidates"]:
        if candidate["candidate_id"] == "sam21":
            candidate["weights"]["revision"] = "e" * 40
        if candidate["candidate_id"] == "oneformer_ade20k_swin_large":
            candidate["weights"]["revision"] = (
                "4a5bac8e64f82681a12db2e151a4c2f4ce6092b2"
            )
    path.write_text(json.dumps(source), encoding="utf-8")


def _write_repository(path: Path) -> None:
    path.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "fixture@example.invalid"],
        cwd=path,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Fixture"],
        cwd=path,
        check=True,
    )
    (path / "LICENSE").write_text("fixture", encoding="utf-8")
    subprocess.run(["git", "add", "LICENSE"], cwd=path, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "fixture"],
        cwd=path,
        check=True,
    )


def test_windowed_sam2_asset_covers_every_frame_once(
    tmp_path: Path,
) -> None:
    video = tmp_path / "source.avi"
    _write_video(video)
    registry = tmp_path / "registry.json"
    _write_registry(registry)
    repository = tmp_path / "sam2"
    _write_repository(repository)
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        capture_output=True,
        check=True,
        text=True,
    ).stdout.strip()
    payload = json.loads(registry.read_text(encoding="utf-8"))
    sam = next(
        item for item in payload["candidates"] if item["candidate_id"] == "sam21"
    )
    sam["code"]["revision"] = revision
    registry.write_text(json.dumps(payload), encoding="utf-8")
    graph = build_initial_graph(
        project_id="sam2-asset-fixture",
        project_name="SAM 2 asset fixture",
        media=MediaInfo(
            path=str(video),
            duration_seconds=1.4,
            width=32,
            height=16,
            fps=5,
            frame_count=7,
            codec="ffv1",
            pixel_format="bgr0",
            bit_depth=8,
            input_color_space=ColorSpace.BT709_OETF,
        ),
        shot_ranges=[TimeRange(start_seconds=0, end_seconds=1.4)],
        representative_frames=[None],
    )

    def fake_encoder(root, target, fps, *, bit_depth):
        destination = Path(root) / f"{target}.mkv"
        destination.write_bytes(b"fixture-video")
        return destination

    def fake_video_inspector(path, **_kwargs):
        return MaskVideoInspection(
            frame_count=7,
            width=32,
            height=16,
            fps=5,
            pixel_format="gray",
            bits_per_raw_sample=8,
            sha256=hashlib.sha256(Path(path).read_bytes()).hexdigest(),
        )

    result = generate_sam2_mask_asset(
        registry,
        repository,
        video,
        graph,
        tmp_path / "masks",
        tmp_path / "report.json",
        window_frames=3,
        semantic_provider_factory=_SemanticProvider,
        runner_factory=_Runner,
        video_encoder=fake_encoder,
        video_inspector=fake_video_inspector,
    )

    assert result.observation.frame_count == 7
    assert [
        window.output_frame_count for window in result.observation.windows
    ] == [3, 2, 2]
    assert result.observation.semantic_anchor_count == 1
    assert result.observation.sam_checkpoint_file_sha256 == "f" * 64
    assert result.asset.metadata["tracking"]["window_overlap_frames"] == 1
    assert result.asset.metadata["target_aliases"] == [
        "mountain",
        "mask_mountain",
        "mask_sam21_mountain",
    ]
    assert result.asset.metadata["storage"]["sequence_retained"] is False
    assert not list((tmp_path / "masks" / result.asset.id).glob("*.png"))
    assert result.graph.masks[-1].id == "mask_sam21_mountain"
