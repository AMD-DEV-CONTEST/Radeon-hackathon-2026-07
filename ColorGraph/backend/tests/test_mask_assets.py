import subprocess
from pathlib import Path

import cv2
import numpy as np
import pytest
import torch
from PIL import Image

from colorgraph.domain.grade_graph import (
    ColorSpace,
    MaskAsset,
    MediaInfo,
    NodeType,
    SpatialKind,
    SpatialScope,
    TimeRange,
)
from colorgraph.grading.mask_integrity import (
    MASK_ASSET_SCHEMA,
    MissingFramePolicy,
    inspect_mask_sequence,
    inspect_mask_video,
)
from colorgraph.grading.masks import GraphMaskResolver
from colorgraph.services.graph_builder import build_initial_graph
from colorgraph.services.mask_nodes import ensure_default_mask_nodes
from colorgraph.vision.base import MaskPrediction
from colorgraph.vision.video_masks import VideoMaskGenerator


def _graph(*, frame_count: int = 3, fps: float = 25):
    duration = frame_count / fps
    return build_initial_graph(
        project_id="mask-integrity",
        project_name="Mask Integrity",
        media=MediaInfo(
            path="source.avi",
            duration_seconds=duration,
            width=8,
            height=6,
            fps=fps,
            frame_count=frame_count,
            codec="mjpeg",
            input_color_space=ColorSpace.BT709_OETF,
        ),
        shot_ranges=[
            TimeRange(start_seconds=0, end_seconds=duration)
        ],
        representative_frames=[Path("frame.jpg")],
    )


def _write_frame(
    path: Path,
    value: int,
    *,
    width: int = 4,
    height: int = 3,
    bit_depth: int = 8,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = np.full(
        (height, width),
        value,
        dtype=np.uint16 if bit_depth == 16 else np.uint8,
    )
    assert cv2.imwrite(str(path), frame)


def _attach_sequence_asset(
    graph,
    root: Path,
    *,
    checksum: str,
    frame_count: int = 3,
    width: int = 4,
    height: int = 3,
    fps: float = 25,
    aliases: list[str] | None = None,
    bit_depth: int = 8,
) -> MaskAsset:
    asset = MaskAsset(
        id="mask_sky",
        kind=SpatialKind.SEMANTIC,
        target="sky",
        path=str(root),
        frame_count=frame_count,
        metadata={
            "schema": MASK_ASSET_SCHEMA,
            "target": "sky",
            "target_aliases": aliases or ["sky", "mask_sky"],
            "file_pattern": "{frame_index:06d}.png",
            "storage": {
                "sequence_format": "png",
                "sample_dtype": "uint16" if bit_depth == 16 else "uint8",
                "bit_depth": bit_depth,
                "quantization_levels": 1 << bit_depth,
                "maximum_quantization_error": 0.5 / ((1 << bit_depth) - 1),
                "preferred_decode": "sequence",
                "video_pixel_format": "gray16le" if bit_depth == 16 else "gray",
            },
            "frame_count": frame_count,
            "file_count": len(list(root.glob("*.png"))),
            "width": width,
            "height": height,
            "fps": fps,
            "sequence_sha256": checksum,
            "decode_verified": True,
            "missing_frame_policy": "error",
        },
    )
    graph.masks = [asset]
    balance = next(
        node
        for node in graph.nodes
        if node.type == NodeType.BALANCE
    )
    balance.spatial_scope = SpatialScope(
        kind=SpatialKind.SEMANTIC,
        target="sky",
        mask_asset_id=asset.id,
    )
    return asset


def _attach_shared_target_assets(
    graph,
    root: Path,
    *,
    checksum: str,
) -> tuple[MaskAsset, MaskAsset]:
    base = _attach_sequence_asset(graph, root, checksum=checksum)

    def candidate(asset_id: str) -> MaskAsset:
        metadata = {
            **base.metadata,
            "target_aliases": [asset_id, "sky", "mask_sky"],
        }
        return base.model_copy(
            deep=True,
            update={"id": asset_id, "metadata": metadata},
        )

    primary = candidate("mask_sky_primary")
    alternative = candidate("mask_sky_alternative")
    graph.masks = [primary, alternative]
    return primary, alternative


def _complete_sequence(root: Path) -> str:
    for index, value in enumerate((32, 96, 192)):
        _write_frame(root / f"{index:06d}.png", value)
    return inspect_mask_sequence(
        root,
        expected_frame_count=3,
        expected_width=4,
        expected_height=3,
    ).sha256


def test_missing_mask_frame_is_an_error_instead_of_a_zero_mask(tmp_path: Path) -> None:
    root = tmp_path / "sky"
    checksum = _complete_sequence(root)
    (root / "000001.png").unlink()
    graph = _graph()
    _attach_sequence_asset(graph, root, checksum=checksum)

    resolver = GraphMaskResolver(graph)
    with pytest.raises(FileNotFoundError, match="missing frames"):
        resolver.load_batch([0, 1, 2])


def test_hold_last_requires_explicit_policy_and_reuses_previous_frame(
    tmp_path: Path,
) -> None:
    root = tmp_path / "sky"
    _complete_sequence(root)
    (root / "000001.png").unlink()
    inspection = inspect_mask_sequence(
        root,
        expected_frame_count=3,
        expected_width=4,
        expected_height=3,
        missing_frame_policy=MissingFramePolicy.HOLD_LAST,
    )
    graph = _graph()
    _attach_sequence_asset(graph, root, checksum=inspection.sha256)

    resolver = GraphMaskResolver(
        graph,
        missing_frame_policy=MissingFramePolicy.HOLD_LAST,
    )
    loaded = resolver.load_batch([0, 1, 2])["mask_sky"]

    assert loaded.shape == (3, 3, 4)
    assert np.allclose(loaded[1].numpy(), loaded[0].numpy())
    assert not np.allclose(loaded[2].numpy(), loaded[1].numpy())


@pytest.mark.parametrize(
    ("mutation", "error"),
    [
        ("wrong_size", "has shape"),
        ("corrupt", "could not decode"),
        ("checksum", "checksum mismatch"),
    ],
)
def test_mask_asset_rejects_wrong_size_corruption_and_checksum_changes(
    tmp_path: Path,
    mutation: str,
    error: str,
) -> None:
    root = tmp_path / mutation
    checksum = _complete_sequence(root)
    if mutation == "wrong_size":
        _write_frame(root / "000001.png", 80, width=5, height=3)
    elif mutation == "corrupt":
        (root / "000001.png").write_bytes(b"not a png")
    else:
        checksum = "0" * 64
    graph = _graph()
    _attach_sequence_asset(graph, root, checksum=checksum)

    resolver = GraphMaskResolver(graph)
    with pytest.raises((RuntimeError, ValueError), match=error):
        resolver.load_batch([0, 1, 2])


def test_interactive_resolver_can_skip_full_sequence_checksum_scan(
    tmp_path: Path,
) -> None:
    root = tmp_path / "interactive"
    _complete_sequence(root)
    graph = _graph()
    _attach_sequence_asset(graph, root, checksum="0" * 64)

    resolver = GraphMaskResolver(graph, verify_storage=False)
    loaded = resolver.load_batch([0])["mask_sky"]

    assert loaded.shape == (1, 3, 4)
    assert loaded.mean().item() == pytest.approx(32 / 255)


def test_uint16_sequence_preserves_soft_edge_samples(tmp_path: Path) -> None:
    root = tmp_path / "soft-edge-16"
    root.mkdir()
    source = np.asarray(
        [[0, 1, 257], [32768, 65534, 65535]],
        dtype=np.uint16,
    )
    assert cv2.imwrite(str(root / "000000.png"), source)
    inspection = inspect_mask_sequence(
        root,
        expected_frame_count=1,
        expected_width=3,
        expected_height=2,
        expected_bit_depth=16,
    )
    graph = _graph(frame_count=1)
    _attach_sequence_asset(
        graph,
        root,
        checksum=inspection.sha256,
        frame_count=1,
        width=3,
        height=2,
        bit_depth=16,
    )

    loaded = GraphMaskResolver(
        graph,
        sequence_decode_workers=1,
    ).load_batch([0])["mask_sky"][0]

    assert inspection.bit_depth == 16
    assert inspection.sample_dtype == "uint16"
    assert inspection.maximum_quantization_error == pytest.approx(0.5 / 65535)
    np.testing.assert_allclose(
        loaded.numpy(),
        source.astype(np.float32) / 65535,
        rtol=0,
        atol=0,
    )


def test_uint16_ffv1_decoder_preserves_random_access_samples(
    tmp_path: Path,
) -> None:
    root = tmp_path / "ffv1-mask"
    sequence_root = root / "sky"
    sequence_root.mkdir(parents=True)
    samples = [0, 1025, 32768, 65535]
    for frame_index, sample in enumerate(samples):
        frame = np.full((3, 4), sample, dtype=np.uint16)
        assert cv2.imwrite(
            str(sequence_root / f"{frame_index:06d}.png"),
            frame,
        )
    video_path = root / "sky.mkv"
    completed = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-framerate",
            "5",
            "-i",
            str(sequence_root / "%06d.png"),
            "-c:v",
            "ffv1",
            "-level",
            "3",
            "-pix_fmt",
            "gray16le",
            str(video_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    inspection = inspect_mask_video(
        video_path,
        expected_frame_count=4,
        expected_width=4,
        expected_height=3,
        expected_fps=5,
        expected_pixel_format="gray16le",
    )
    for path in sequence_root.glob("*.png"):
        path.unlink()

    graph = _graph(frame_count=4, fps=5)
    asset = MaskAsset(
        id="mask_sky",
        kind=SpatialKind.SEMANTIC,
        target="sky",
        path=str(sequence_root),
        frame_count=4,
        metadata={
            "schema": MASK_ASSET_SCHEMA,
            "target": "sky",
            "target_aliases": ["sky", "mask_sky"],
            "file_pattern": None,
            "storage": {
                "primary": "ffv1_video",
                "sequence_format": "png",
                "sample_dtype": "uint16",
                "bit_depth": 16,
                "quantization_levels": 65536,
                "maximum_quantization_error": 0.5 / 65535,
                "preferred_decode": "video_ffmpeg",
                "sequence_retained": False,
                "video_pixel_format": "gray16le",
            },
            "frame_count": 4,
            "file_count": 0,
            "width": 4,
            "height": 3,
            "fps": 5,
            "sequence_sha256": None,
            "video_path": str(video_path),
            "video_sha256": inspection.sha256,
            "decode_verified": True,
            "missing_frame_policy": "error",
        },
    )
    graph.masks = [asset]
    balance = next(node for node in graph.nodes if node.type == NodeType.BALANCE)
    balance.spatial_scope = SpatialScope(
        kind=SpatialKind.SEMANTIC,
        target="sky",
        mask_asset_id=asset.id,
    )
    resolver = GraphMaskResolver(graph)
    try:
        loaded = resolver.load_batch([3, 1, 2, 0])["mask_sky"]
    finally:
        resolver.close()

    expected = torch.tensor(
        [samples[index] / 65535 for index in (3, 1, 2, 0)],
        dtype=torch.float32,
    )
    assert torch.equal(loaded[:, 0, 0], expected)


def test_mask_metadata_validates_frame_count_fps_and_aliases(tmp_path: Path) -> None:
    root = tmp_path / "sky"
    checksum = _complete_sequence(root)

    frame_graph = _graph()
    _attach_sequence_asset(
        frame_graph,
        root,
        checksum=checksum,
        frame_count=2,
    )
    with pytest.raises(ValueError, match="project media has 3"):
        GraphMaskResolver(frame_graph)

    fps_graph = _graph()
    _attach_sequence_asset(fps_graph, root, checksum=checksum, fps=24)
    with pytest.raises(ValueError, match="does not match project fps"):
        GraphMaskResolver(fps_graph)

    alias_graph = _graph()
    _attach_sequence_asset(
        alias_graph,
        root,
        checksum=checksum,
        aliases=["mask_sky"],
    )
    with pytest.raises(ValueError, match="both id and target aliases"):
        GraphMaskResolver(alias_graph)


def test_shared_alias_selects_directly_referenced_asset(tmp_path: Path) -> None:
    root = tmp_path / "sky"
    checksum = _complete_sequence(root)
    graph = _graph()
    primary, alternative = _attach_shared_target_assets(
        graph,
        root,
        checksum=checksum,
    )
    balance = next(node for node in graph.nodes if node.type == NodeType.BALANCE)
    balance.spatial_scope = SpatialScope(
        kind=SpatialKind.SEMANTIC,
        target="sky",
        mask_asset_id=primary.id,
    )

    resolver = GraphMaskResolver(graph, verify_storage=False)
    try:
        assert set(resolver.assets) == {primary.id}
        assert resolver._aliases["sky"] == primary.id
    finally:
        resolver.close()

    resolver = GraphMaskResolver(
        graph,
        verify_storage=False,
        include_unreferenced_assets=True,
    )
    try:
        assert set(resolver.assets) == {primary.id, alternative.id}
        assert "sky" not in resolver._aliases
    finally:
        resolver.close()


def test_expression_rejects_ambiguous_mask_alias(tmp_path: Path) -> None:
    root = tmp_path / "sky"
    checksum = _complete_sequence(root)
    graph = _graph()
    primary, alternative = _attach_shared_target_assets(
        graph,
        root,
        checksum=checksum,
    )
    balance = next(node for node in graph.nodes if node.type == NodeType.BALANCE)
    balance.spatial_scope = SpatialScope(
        kind=SpatialKind.COMPOSITE,
        target="composite",
        expression="sky",
    )

    with pytest.raises(
        ValueError,
        match=(
            rf"alias 'sky' is ambiguous across assets "
            rf"\['{alternative.id}', '{primary.id}'\]"
        ),
    ):
        GraphMaskResolver(graph, verify_storage=False)


def test_expression_prefers_unique_directly_referenced_alias_owner(
    tmp_path: Path,
) -> None:
    root = tmp_path / "sky"
    checksum = _complete_sequence(root)
    graph = _graph()
    primary, _alternative = _attach_shared_target_assets(
        graph,
        root,
        checksum=checksum,
    )
    direct_node = next(node for node in graph.nodes if node.type == NodeType.BALANCE)
    expression_node = next(node for node in graph.nodes if node.id != direct_node.id)
    direct_node.spatial_scope = SpatialScope(
        kind=SpatialKind.SEMANTIC,
        target="sky",
        mask_asset_id=primary.id,
    )
    expression_node.spatial_scope = SpatialScope(
        kind=SpatialKind.COMPOSITE,
        target="composite",
        expression="sky",
    )

    resolver = GraphMaskResolver(graph, verify_storage=False)
    try:
        assert set(resolver.assets) == {primary.id}
        assert resolver._aliases["sky"] == primary.id
    finally:
        resolver.close()


class _FakeSemanticProvider:
    supported_targets = frozenset({"sky", "water"})
    provider_id = "fake-semantic/v1"

    def predict_many(
        self,
        image: Image.Image,
        targets: list[str],
    ) -> dict[str, MaskPrediction]:
        width, height = image.size
        mask = np.linspace(0, 1, width, dtype=np.float32)
        mask = np.broadcast_to(mask, (height, width)).copy()
        return {
            target: MaskPrediction(
                target=target,
                mask=mask,
                confidence=0.9,
                metadata={
                    "model_revision": "a" * 40,
                    "checkpoint_sha256": "b" * 64,
                    "checkpoint_hash_kind": "colorgraph.torch-state-dict/v1",
                },
            )
            for target in targets
        }


class _FakeDepthProvider:
    supported_targets = frozenset()
    provider_id = "fake-depth/v1"

    def predict_many(
        self,
        image: Image.Image,
        targets: list[str],
    ) -> dict[str, MaskPrediction]:
        assert not targets
        return {}


def _write_source_video(path: Path, *, frame_count: int = 4, fps: float = 5) -> None:
    writer = cv2.VideoWriter(
        str(path),
        cv2.VideoWriter_fourcc(*"MJPG"),
        fps,
        (8, 6),
    )
    if not writer.isOpened():
        pytest.skip("OpenCV MJPEG writer is unavailable")
    try:
        for index in range(frame_count):
            frame = np.full((6, 8, 3), 30 + index * 40, dtype=np.uint8)
            writer.write(frame)
    finally:
        writer.release()


def test_generated_asset_records_truthful_tracking_and_verified_integrity(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.avi"
    _write_source_video(source)
    graph = _graph(frame_count=4, fps=5)
    graph.media.path = str(source)

    result = VideoMaskGenerator(
        _FakeSemanticProvider(),  # type: ignore[arg-type]
        _FakeDepthProvider(),  # type: ignore[arg-type]
    ).generate(
        source,
        graph,
        tmp_path / "masks",
        targets=["sky"],
        inference_interval_seconds=1,
        maximum_edge=640,
    )

    assert result.frame_count == 4
    asset = result.graph.masks[0]
    metadata = asset.metadata
    assert metadata["schema"] == MASK_ASSET_SCHEMA
    assert metadata["target_aliases"] == ["sky", "mask_sky"]
    assert metadata["confidence_is_accuracy"] is False
    assert (
        metadata["confidence_semantics"]
        == "provider_defined_confidence_not_accuracy"
    )
    assert metadata["prediction_evidence"] == {
        "model_revision": "a" * 40,
        "checkpoint_sha256": "b" * 64,
        "checkpoint_hash_kind": "colorgraph.torch-state-dict/v1",
    }
    assert metadata["model_revision"] == "a" * 40
    assert metadata["checkpoint_sha256"] == "b" * 64
    assert metadata["checkpoint_hash_kind"] == "colorgraph.torch-state-dict/v1"
    assert metadata["frame_count"] == 4
    assert metadata["file_count"] == 0
    assert metadata["decode_verified"] is True
    assert metadata["storage"]["bit_depth"] == 16
    assert metadata["storage"]["sample_dtype"] == "uint16"
    assert metadata["storage"]["primary"] == "ffv1_video"
    assert metadata["storage"]["preferred_decode"] == "video_ffmpeg"
    assert metadata["storage"]["sequence_retained"] is False
    assert metadata["storage"]["video_pixel_format"] == "gray16le"
    assert metadata["storage"]["maximum_quantization_error"] == pytest.approx(
        0.5 / 65535
    )
    assert metadata["sequence_sha256"] is None
    assert len(str(metadata["transient_sequence_sha256"])) == 64
    assert len(str(metadata["video_sha256"])) == 64
    assert metadata["tracking"] == {
        "algorithm": "farneback_backward_flow_warp",
        "flow_direction": "current_to_previous",
        "reanchor": "periodic_model_inference",
        "anchor_model_weight": 0.82,
        "anchor_propagated_weight": 0.18,
        "bidirectional_consistency": False,
    }
    assert not list((tmp_path / "masks" / "sky").glob("*.png"))
    inspect_mask_video(
        str(metadata["video_path"]),
        expected_frame_count=4,
        expected_width=8,
        expected_height=6,
        expected_fps=5,
        expected_sha256=str(metadata["video_sha256"]),
    )

    graph_with_node = ensure_default_mask_nodes(result.graph)
    resolver = GraphMaskResolver(graph_with_node)
    loaded = resolver.load_batch([0, 1, 2, 3])
    assert loaded["mask_sky"].shape == (4, 6, 8)


def test_generation_computes_optical_flow_once_per_frame_for_multiple_targets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from colorgraph.vision import video_masks

    source = tmp_path / "source.avi"
    _write_source_video(source)
    graph = _graph(frame_count=4, fps=5)
    graph.media.path = str(source)
    original = video_masks._calculate_backward_flow
    flow_calls = 0

    def counted_backward_flow(
        previous_gray: np.ndarray,
        current_gray: np.ndarray,
    ) -> np.ndarray:
        nonlocal flow_calls
        flow_calls += 1
        return original(previous_gray, current_gray)

    monkeypatch.setattr(
        video_masks,
        "_calculate_backward_flow",
        counted_backward_flow,
    )

    VideoMaskGenerator(
        _FakeSemanticProvider(),  # type: ignore[arg-type]
        _FakeDepthProvider(),  # type: ignore[arg-type]
    ).generate(
        source,
        graph,
        tmp_path / "masks",
        targets=["sky", "water"],
        inference_interval_seconds=1,
        maximum_edge=640,
    )

    assert flow_calls == 3


def test_generation_skips_optical_flow_at_shot_boundaries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from colorgraph.vision import video_masks

    source = tmp_path / "source.avi"
    _write_source_video(source)
    duration = 4 / 5
    graph = build_initial_graph(
        project_id="mask-two-shots",
        project_name="Mask Two Shots",
        media=MediaInfo(
            path=str(source),
            duration_seconds=duration,
            width=8,
            height=6,
            fps=5,
            frame_count=4,
            codec="mjpeg",
            input_color_space=ColorSpace.BT709_OETF,
        ),
        shot_ranges=[
            TimeRange(start_seconds=0, end_seconds=2 / 5),
            TimeRange(start_seconds=2 / 5, end_seconds=duration),
        ],
        representative_frames=[Path("frame-0.jpg"), Path("frame-1.jpg")],
    )
    original = video_masks._calculate_backward_flow
    flow_calls = 0

    def counted_backward_flow(
        previous_gray: np.ndarray,
        current_gray: np.ndarray,
    ) -> np.ndarray:
        nonlocal flow_calls
        flow_calls += 1
        return original(previous_gray, current_gray)

    monkeypatch.setattr(
        video_masks,
        "_calculate_backward_flow",
        counted_backward_flow,
    )

    VideoMaskGenerator(
        _FakeSemanticProvider(),  # type: ignore[arg-type]
        _FakeDepthProvider(),  # type: ignore[arg-type]
    ).generate(
        source,
        graph,
        tmp_path / "masks",
        targets=["sky", "water"],
        inference_interval_seconds=1,
        maximum_edge=640,
    )

    # Frames 0 and 2 are shot-start anchors. Only frames 1 and 3 need flow.
    assert flow_calls == 2


def test_shared_optical_flow_is_bit_exact_with_per_target_baseline() -> None:
    from colorgraph.vision import video_masks

    rng = np.random.default_rng(20260729)
    previous_gray = rng.integers(0, 256, size=(72, 128), dtype=np.uint8)
    current_gray = np.roll(previous_gray, shift=(1, 3), axis=(0, 1))
    masks = [
        rng.random((72, 128), dtype=np.float32)
        for _ in range(5)
    ]

    baseline = [
        video_masks._propagate_mask(
            mask,
            video_masks._calculate_backward_flow(
                previous_gray,
                current_gray,
            ),
        )
        for mask in masks
    ]
    shared_flow = video_masks._calculate_backward_flow(
        previous_gray,
        current_gray,
    )
    optimized = [
        video_masks._propagate_mask(mask, shared_flow)
        for mask in masks
    ]

    for expected, actual in zip(baseline, optimized, strict=True):
        np.testing.assert_array_equal(actual, expected)
