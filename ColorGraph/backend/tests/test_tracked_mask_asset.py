from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
from PIL import Image

from colorgraph.domain.grade_graph import (
    ColorSpace,
    MediaInfo,
    TimeRange,
)
from colorgraph.evaluation.tracked_mask_asset import (
    TRACKED_MASK_ASSET_SCHEMA,
    TrackedMaskAssetObservation,
    generate_tracked_mask_asset_bundle,
)
from colorgraph.services.graph_builder import build_initial_graph
from colorgraph.vision.base import MaskPrediction


class _SemanticProvider:
    model_id = "formal/semantic"
    model_revision = "a" * 40
    provider_id = model_id
    supported_targets = frozenset({"sky"})
    backend = SimpleNamespace()

    def predict_many(
        self,
        image: Image.Image,
        targets: list[str],
    ) -> dict[str, MaskPrediction]:
        return {
            target: MaskPrediction(
                target=target,
                mask=np.full(
                    (image.height, image.width),
                    0.75,
                    dtype=np.float32,
                ),
                confidence=0.75,
                metadata={
                    "model_revision": self.model_revision,
                    "checkpoint_sha256": "b" * 64,
                    "checkpoint_hash_kind": (
                        "colorgraph.torch-state-dict/v1"
                    ),
                },
            )
            for target in targets
        }

    def release_model(self) -> int:
        return 0


class _DepthProvider:
    model_id = "formal/depth"
    model_revision = "c" * 40
    provider_id = model_id
    supported_targets = frozenset({"depth_far"})

    def reset_shot(self, _shot_id: str | None = None) -> None:
        return None

    def predict_many(
        self,
        image: Image.Image,
        targets: list[str],
    ) -> dict[str, MaskPrediction]:
        return {
            target: MaskPrediction(
                target=target,
                mask=np.full(
                    (image.height, image.width),
                    0.25,
                    dtype=np.float32,
                ),
                confidence=0.75,
                metadata={
                    "model_revision": self.model_revision,
                    "checkpoint_sha256": "d" * 64,
                    "checkpoint_hash_kind": (
                        "colorgraph.torch-state-dict/v1"
                    ),
                },
            )
            for target in targets
        }

    def release_model(self) -> int:
        return 0


def _write_source(path: Path) -> None:
    writer = cv2.VideoWriter(
        str(path),
        cv2.VideoWriter_fourcc(*"MJPG"),
        5,
        (8, 6),
    )
    if not writer.isOpened():
        raise RuntimeError("test MJPEG writer is unavailable")
    try:
        for value in (32, 64, 96, 128):
            writer.write(np.full((6, 8, 3), value, dtype=np.uint8))
    finally:
        writer.release()


def test_tracked_mask_bundle_freezes_model_and_source_identity(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.avi"
    _write_source(source)
    graph = build_initial_graph(
        project_id="tracked-mask-test",
        project_name="Tracked mask test",
        media=MediaInfo(
            path=str(source),
            duration_seconds=0.8,
            width=8,
            height=6,
            fps=5,
            frame_count=4,
            codec="mjpeg",
            pixel_format="yuvj420p",
            bit_depth=8,
            input_color_space=ColorSpace.BT709_OETF,
        ),
        shot_ranges=[TimeRange(start_seconds=0, end_seconds=0.8)],
        representative_frames=[None],
    )
    report_path = tmp_path / "observation.json"

    result = generate_tracked_mask_asset_bundle(
        source,
        graph,
        tmp_path / "masks",
        report_path,
        semantic_provider=_SemanticProvider(),  # type: ignore[arg-type]
        depth_provider=_DepthProvider(),  # type: ignore[arg-type]
        semantic_model_revision="a" * 40,
        depth_model_revision="c" * 40,
        targets=["sky", "depth_far"],
        inference_interval_seconds=1,
        storage_bit_depth=8,
    )

    loaded = TrackedMaskAssetObservation.model_validate_json(
        report_path.read_text(encoding="utf-8")
    )
    assert loaded.schema_version == TRACKED_MASK_ASSET_SCHEMA
    assert loaded.frame_count == 4
    assert loaded.inference_frames == 1
    assert len(loaded.source_sha256) == 64
    assert {asset.asset_id for asset in loaded.assets} == {
        "mask_sky",
        "mask_depth_far",
    }
    assert {
        asset.checkpoint_sha256 for asset in loaded.assets
    } == {"b" * 64, "d" * 64}
    assert all(asset.storage_bit_depth == 8 for asset in loaded.assets)
    installed = {
        asset.id: asset for asset in result.graph.masks
    }
    assert installed["mask_sky"].metadata["source_sha256"] == (
        loaded.source_sha256
    )
    assert installed["mask_depth_far"].metadata["source_sha256"] == (
        loaded.source_sha256
    )
