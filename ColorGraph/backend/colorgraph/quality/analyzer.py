from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from colorgraph.domain.grade_graph import GradeGraph, NodeType
from colorgraph.grading.mask_integrity import SUPPORTED_MASK_ASSET_SCHEMAS
from colorgraph.media.probe import MediaProbeError, probe_frame_timings, probe_media
from colorgraph.quality.banding import BANDING_METRIC_VERSION, cambi_equivalent_score
from colorgraph.quality.models import (
    AuxiliaryQualityScore,
    AuxiliaryScoreKind,
    CheckStatus,
    QualityCategory,
    QualityCheck,
    QualityReport,
)
from colorgraph.quality.temporal_motion import (
    TEMPORAL_METRIC_VERSION,
    TemporalQualityEvidence,
    analyze_video_temporal,
)


def _luma(frame: np.ndarray) -> np.ndarray:
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    return rgb[..., 0] * 0.2126 + rgb[..., 1] * 0.7152 + rgb[..., 2] * 0.0722


def _frame_metrics(frame: np.ndarray) -> dict[str, float]:
    small = cv2.resize(frame, (320, 180), interpolation=cv2.INTER_AREA)
    luma = _luma(small)
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    saturation = hsv[..., 1].astype(np.float32) / 255.0
    edges = (
        cv2.Sobel(luma, cv2.CV_32F, 1, 0) ** 2
        + cv2.Sobel(
            luma,
            cv2.CV_32F,
            0,
            1,
        )
        ** 2
    )
    return {
        "highlight_clip": float((luma >= 0.985).mean()),
        "shadow_clip": float((luma <= 0.012).mean()),
        "oversaturation": float((saturation >= 0.96).mean()),
        "mean_luma": float(luma.mean()),
        "edge_energy": float(np.sqrt(edges).mean()),
        "banding_risk": cambi_equivalent_score(luma),
        "non_finite_ratio": float(1 - np.isfinite(luma).mean()),
        "decoded_gamut_outside_ratio": float(((luma < 0) | (luma > 1)).mean()),
    }


def _sample_video(
    path: Path,
    *,
    sample_fps: float,
) -> tuple[list[dict[str, float]], float]:
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise RuntimeError(f"OpenCV could not open {path}")
    fps = float(capture.get(cv2.CAP_PROP_FPS))
    if fps <= 0:
        capture.release()
        raise RuntimeError(f"{path} does not report a valid frame rate")
    interval = max(1, round(fps / sample_fps))
    metrics: list[dict[str, float]] = []
    frame_index = 0
    try:
        while True:
            success, frame = capture.read()
            if not success:
                break
            if frame_index % interval == 0:
                metrics.append(_frame_metrics(frame))
            frame_index += 1
    finally:
        capture.release()
    return metrics, interval / fps


def _status(value: float, warning: float, failure: float) -> CheckStatus:
    if value >= failure:
        return CheckStatus.FAIL
    if value >= warning:
        return CheckStatus.WARN
    return CheckStatus.PASS


def _make_check(
    *,
    identifier: str,
    label: str,
    value: float,
    warning: float,
    failure: float,
    unit: str,
    detail: str,
    category: QualityCategory = QualityCategory.HARD_TECHNICAL,
    metric_version: str = "colorgraph.quality/v2",
) -> QualityCheck:
    return QualityCheck(
        id=identifier,
        label=label,
        status=_status(value, warning, failure),
        value=round(value, 6),
        threshold=failure,
        unit=unit,
        detail=detail,
        category=category,
        metric_version=metric_version,
    )


def _boolean_check(
    *,
    identifier: str,
    label: str,
    passed: bool | None,
    detail: str,
) -> QualityCheck:
    return QualityCheck(
        id=identifier,
        label=label,
        status=(
            CheckStatus.WARN
            if passed is None
            else (CheckStatus.PASS if passed else CheckStatus.FAIL)
        ),
        value=1.0 if passed else 0.0,
        threshold=1.0,
        unit="boolean",
        detail=detail,
        category=QualityCategory.HARD_TECHNICAL,
        metric_version="colorgraph.delivery-integrity/v1",
    )


def _delivery_checks(
    output_path: Path,
    graph: GradeGraph | None,
    output_metrics: list[dict[str, float]],
    *,
    expected_frame_count: int | None = None,
) -> list[QualityCheck]:
    non_finite = max(item["non_finite_ratio"] for item in output_metrics)
    gamut_outside = max(item["decoded_gamut_outside_ratio"] for item in output_metrics)
    checks = [
        _make_check(
            identifier="finite_values",
            label="有限值",
            value=non_finite,
            warning=1e-12,
            failure=1e-9,
            unit="ratio",
            detail="解码输出中的 NaN/Inf 像素比例",
            metric_version="colorgraph.decoded-finite/v1",
        ),
        _make_check(
            identifier="output_gamut",
            label="合法输出范围",
            value=gamut_outside,
            warning=1e-12,
            failure=1e-9,
            unit="ratio",
            detail="解码输出落在归一化显示范围外的样本比例",
            metric_version="colorgraph.decoded-gamut/v1",
        ),
        _boolean_check(
            identifier="asset_integrity",
            label="输出资产完整性",
            passed=output_path.is_file() and output_path.stat().st_size > 0,
            detail="输出文件必须存在且非空",
        ),
    ]
    input_nodes = (
        []
        if graph is None
        else [
            node for node in graph.nodes if node.type == NodeType.INPUT_TRANSFORM and node.enabled
        ]
    )
    output_nodes = (
        []
        if graph is None
        else [
            node for node in graph.nodes if node.type == NodeType.OUTPUT_TRANSFORM and node.enabled
        ]
    )
    checks.append(
        _boolean_check(
            identifier="color_pipeline_schema",
            label="色彩管线 schema",
            passed=None if graph is None else len(input_nodes) == 1 and len(output_nodes) == 1,
            detail=(
                "未提供 Grade Graph，无法验证 Input/Output Transform"
                if graph is None
                else "Grade Graph 必须且只能启用一对 Input/Output Transform"
            ),
        )
    )
    try:
        media = probe_media(output_path)
        metadata_valid = (
            (media.color_primaries or "").lower() == "bt709"
            and (media.color_transfer or "").lower() == "bt709"
            and (media.color_matrix or "").lower() == "bt709"
        )
        checks.append(
            _boolean_check(
                identifier="metadata",
                label="交付色彩元数据",
                passed=metadata_valid,
                detail=(
                    "输出必须显式标记 BT.709 primaries/transfer/matrix；"
                    f"observed={media.color_primaries}/"
                    f"{media.color_transfer}/{media.color_matrix}"
                ),
            )
        )
        checks.append(
            _boolean_check(
                identifier="encoding",
                label="交付编码",
                passed=(
                    media.codec != "unknown"
                    and media.pixel_format is not None
                    and (media.bit_depth or 0) >= 8
                ),
                detail=(
                    f"codec={media.codec}; pixel_format={media.pixel_format}; "
                    f"bit_depth={media.bit_depth}"
                ),
            )
        )
        timings = probe_frame_timings(output_path)
        expected_frames = (
            expected_frame_count
            if expected_frame_count is not None
            else (graph.media.frame_count if graph is not None else None)
        )
        pts_valid = expected_frames is None or len(timings) == expected_frames
        checks.append(
            _boolean_check(
                identifier="frame_pts",
                label="帧数与 PTS",
                passed=pts_valid,
                detail=(
                    f"严格递增 PTS 共 {len(timings)} 帧；"
                    f"expected={expected_frames if expected_frames is not None else 'unknown'}"
                ),
            )
        )
    except (MediaProbeError, OSError, ValueError) as exc:
        checks.extend(
            [
                _boolean_check(
                    identifier="metadata",
                    label="交付色彩元数据",
                    passed=False,
                    detail=f"无法验证输出元数据：{type(exc).__name__}",
                ),
                _boolean_check(
                    identifier="frame_pts",
                    label="帧数与 PTS",
                    passed=False,
                    detail=f"无法验证输出 PTS：{type(exc).__name__}",
                ),
                _boolean_check(
                    identifier="encoding",
                    label="交付编码",
                    passed=False,
                    detail=f"无法验证输出编码：{type(exc).__name__}",
                ),
            ]
        )
    return checks


def _cut_intervals(graph: GradeGraph | None) -> list[float]:
    if graph is None:
        return []
    return [shot.time_range.start_seconds for shot in graph.shots[1:]]


def _read_video_frame(capture: cv2.VideoCapture, frame_index: int) -> np.ndarray | None:
    capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
    success, frame = capture.read()
    return frame if success else None


def _resize_frame_to_delivery(
    frame: np.ndarray,
    *,
    width: int,
    height: int,
) -> np.ndarray:
    """Normalize a source frame into the delivery raster for pixel comparisons."""
    source_height, source_width = frame.shape[:2]
    if (source_width, source_height) == (width, height):
        return frame
    interpolation = (
        cv2.INTER_AREA if width <= source_width and height <= source_height else cv2.INTER_LINEAR
    )
    return cv2.resize(
        frame,
        (width, height),
        interpolation=interpolation,
    )


def _empty_mask_artifact_metrics() -> dict[str, float]:
    return {
        "mask_jitter": 0.0,
        "mask_halo": 0.0,
        "sky_banding": 0.0,
        "mask_frames_decoded": 0.0,
        "mask_transition_samples": 0.0,
        "sky_mask_samples": 0.0,
        "sky_boundary_samples": 0.0,
        "sky_banding_samples": 0.0,
    }


def _normalize_mask_plane(mask: np.ndarray) -> np.ndarray:
    plane = np.asarray(mask)
    if plane.ndim == 3:
        plane = cv2.cvtColor(plane, cv2.COLOR_BGR2GRAY)
    if plane.ndim != 2:
        raise ValueError(f"mask frame must be single-channel; got shape {plane.shape}")
    if plane.dtype == np.uint8:
        normalized = plane.astype(np.float32) / 255.0
    elif plane.dtype == np.uint16:
        normalized = plane.astype(np.float32) / 65535.0
    elif np.issubdtype(plane.dtype, np.floating):
        normalized = plane.astype(np.float32)
    else:
        raise ValueError(f"unsupported mask frame dtype: {plane.dtype}")
    if not np.isfinite(normalized).all():
        raise ValueError("mask frame contains non-finite samples")
    return np.clip(normalized, 0.0, 1.0)


def _legacy_mask_frame(asset: object, frame_index: int) -> np.ndarray | None:
    root = Path(str(asset.path))
    path = root / f"{frame_index:06d}.png"
    if not path.is_file():
        return None
    frame = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    return None if frame is None else _normalize_mask_plane(frame)


def _uses_integrity_mask_storage(graph: GradeGraph) -> bool:
    schemas = [
        (
            asset.metadata.get("schema")
            if isinstance(getattr(asset, "metadata", None), dict)
            else None
        )
        for asset in graph.masks
    ]
    if not any(schema is not None for schema in schemas):
        return False
    unsupported = [schema for schema in schemas if schema not in SUPPORTED_MASK_ASSET_SCHEMAS]
    if unsupported:
        raise ValueError(
            "quality analysis cannot mix integrity-addressed masks with "
            f"missing or unsupported schemas: {unsupported}"
        )
    return True


def _jitter_sample_indices(frame_count: int) -> set[int]:
    if frame_count < 2:
        return set()
    sample_step = max(1, frame_count // 160)
    return set(range(0, frame_count, sample_step))


def _sky_sample_indices(frame_count: int) -> set[int]:
    if frame_count <= 0:
        return set()
    return {
        int(index)
        for index in np.linspace(
            0,
            frame_count - 1,
            min(12, frame_count),
        )
    }


def _decode_integrity_mask_samples(
    graph: GradeGraph,
    *,
    cut_frames: set[int],
    sky_asset: object | None,
) -> tuple[list[float], dict[int, np.ndarray], int, int]:
    # VideoRenderer already performs the expensive checksum/storage verification.
    # Quality analysis still uses the canonical decoder and fails on decode errors,
    # while avoiding a second full scan of every mask asset.
    from colorgraph.grading.masks import GraphMaskResolver

    jitter_indices = {
        asset.id: _jitter_sample_indices(int(asset.frame_count or graph.media.frame_count))
        for asset in graph.masks
    }
    sky_indices = (
        _sky_sample_indices(int(sky_asset.frame_count or graph.media.frame_count))
        if sky_asset is not None
        else set()
    )
    requested_indices = sorted(set().union(*jitter_indices.values(), sky_indices))
    jitter_values: list[float] = []
    sky_masks: dict[int, np.ndarray] = {}
    previous_masks: dict[str, np.ndarray] = {}
    previous_indices: dict[str, int] = {}
    decoded_frames = 0
    transition_samples = 0
    resolver = GraphMaskResolver(
        graph,
        verify_storage=False,
        include_unreferenced_assets=True,
    )
    try:
        for frame_index in requested_indices:
            loaded = resolver.load_batch([frame_index])
            for asset in graph.masks:
                if frame_index not in jitter_indices[asset.id]:
                    continue
                tensor = loaded.get(asset.id)
                if tensor is None:
                    raise RuntimeError(f"mask resolver omitted quality asset {asset.id!r}")
                normalized = cv2.resize(
                    _normalize_mask_plane(tensor[0].detach().cpu().numpy()),
                    (160, 90),
                    interpolation=cv2.INTER_AREA,
                )
                decoded_frames += 1
                previous = previous_masks.get(asset.id)
                previous_index = previous_indices.get(asset.id)
                crosses_cut = previous_index is not None and any(
                    previous_index <= cut <= frame_index for cut in cut_frames
                )
                if previous is not None and not crosses_cut:
                    jitter_values.append(float(np.abs(normalized - previous).mean()))
                    transition_samples += 1
                previous_masks[asset.id] = normalized
                previous_indices[asset.id] = frame_index

            if sky_asset is not None and frame_index in sky_indices:
                tensor = loaded.get(sky_asset.id)
                if tensor is None:
                    raise RuntimeError(f"mask resolver omitted sky asset {sky_asset.id!r}")
                sky_masks[frame_index] = _normalize_mask_plane(tensor[0].detach().cpu().numpy())
    finally:
        resolver.close()
    return jitter_values, sky_masks, decoded_frames, transition_samples


def _decode_legacy_mask_samples(
    graph: GradeGraph,
    *,
    cut_frames: set[int],
    sky_asset: object | None,
) -> tuple[list[float], dict[int, np.ndarray], int, int]:
    jitter_values: list[float] = []
    decoded_frames = 0
    transition_samples = 0
    for asset in graph.masks:
        frame_count = int(asset.frame_count or graph.media.frame_count)
        previous: np.ndarray | None = None
        previous_index: int | None = None
        for frame_index in sorted(_jitter_sample_indices(frame_count)):
            mask = _legacy_mask_frame(asset, frame_index)
            if mask is None:
                continue
            normalized = cv2.resize(
                mask,
                (160, 90),
                interpolation=cv2.INTER_AREA,
            )
            decoded_frames += 1
            crosses_cut = previous_index is not None and any(
                previous_index <= cut <= frame_index for cut in cut_frames
            )
            if previous is not None and not crosses_cut:
                jitter_values.append(float(np.abs(normalized - previous).mean()))
                transition_samples += 1
            previous = normalized
            previous_index = frame_index

    sky_masks: dict[int, np.ndarray] = {}
    if sky_asset is not None:
        frame_count = int(sky_asset.frame_count or graph.media.frame_count)
        for frame_index in sorted(_sky_sample_indices(frame_count)):
            mask = _legacy_mask_frame(sky_asset, frame_index)
            if mask is not None:
                sky_masks[frame_index] = mask
    return jitter_values, sky_masks, decoded_frames, transition_samples


def _mask_artifact_metrics(
    source_path: Path,
    output_path: Path,
    graph: GradeGraph | None,
) -> dict[str, float]:
    if graph is None or not graph.masks:
        return _empty_mask_artifact_metrics()
    cut_frames = {
        round(shot.time_range.start_seconds * graph.media.fps) for shot in graph.shots[1:]
    }
    sky_asset = next((asset for asset in graph.masks if asset.target == "sky"), None)
    if _uses_integrity_mask_storage(graph):
        (
            jitter_values,
            sky_masks,
            mask_frames_decoded,
            mask_transition_samples,
        ) = _decode_integrity_mask_samples(
            graph,
            cut_frames=cut_frames,
            sky_asset=sky_asset,
        )
    else:
        (
            jitter_values,
            sky_masks,
            mask_frames_decoded,
            mask_transition_samples,
        ) = _decode_legacy_mask_samples(
            graph,
            cut_frames=cut_frames,
            sky_asset=sky_asset,
        )

    halo_values: list[float] = []
    banding_values: list[float] = []
    sky_mask_samples = 0
    sky_boundary_samples = 0
    sky_banding_samples = 0
    if sky_asset is not None and sky_masks:
        source_capture = cv2.VideoCapture(str(source_path))
        output_capture = cv2.VideoCapture(str(output_path))
        try:
            source_fps = float(source_capture.get(cv2.CAP_PROP_FPS))
            output_fps = float(output_capture.get(cv2.CAP_PROP_FPS))
            if source_fps <= 0 or output_fps <= 0:
                raise RuntimeError(
                    "source/output video does not report a valid frame rate "
                    "for mask artifact analysis"
                )
            for frame_index, mask in sorted(sky_masks.items()):
                source_frame = _read_video_frame(source_capture, frame_index)
                output_frame_index = round(frame_index * output_fps / source_fps)
                output_frame = _read_video_frame(
                    output_capture,
                    output_frame_index,
                )
                if source_frame is None or output_frame is None:
                    continue
                sky_mask_samples += 1
                height, width = output_frame.shape[:2]
                source_frame = _resize_frame_to_delivery(
                    source_frame,
                    width=width,
                    height=height,
                )
                mask = cv2.resize(
                    mask,
                    (width, height),
                    interpolation=cv2.INTER_LINEAR,
                ).astype(np.float32)
                binary = (mask > 0.35).astype(np.uint8)
                kernel = np.ones((5, 5), dtype=np.uint8)
                boundary = cv2.dilate(binary, kernel) - cv2.erode(binary, kernel)
                source_luma = _luma(source_frame)
                output_luma = _luma(output_frame)
                grade_delta = output_luma - source_luma
                halo_map = np.abs(cv2.Laplacian(grade_delta, cv2.CV_32F))
                if boundary.any():
                    halo_values.append(float(np.percentile(halo_map[boundary > 0], 95)))
                    sky_boundary_samples += 1

                sky_pixels = np.round(output_luma[binary > 0] * 255).astype(np.uint8)
                if sky_pixels.size >= 128:
                    low = int(np.percentile(sky_pixels, 2))
                    high = int(np.percentile(sky_pixels, 98))
                    tonal_range = max(1, high - low + 1)
                    occupied = np.unique(
                        sky_pixels[(sky_pixels >= low) & (sky_pixels <= high)]
                    ).size
                    banding_values.append(max(0.0, 1 - occupied / min(tonal_range, 64)))
                    sky_banding_samples += 1
        finally:
            source_capture.release()
            output_capture.release()

    return {
        "mask_jitter": (float(np.percentile(jitter_values, 95)) if jitter_values else 0.0),
        "mask_halo": float(np.percentile(halo_values, 95)) if halo_values else 0.0,
        "sky_banding": (float(np.percentile(banding_values, 95)) if banding_values else 0.0),
        "mask_frames_decoded": float(mask_frames_decoded),
        "mask_transition_samples": float(mask_transition_samples),
        "sky_mask_samples": float(sky_mask_samples),
        "sky_boundary_samples": float(sky_boundary_samples),
        "sky_banding_samples": float(sky_banding_samples),
    }


def _temporal_flicker(
    output_metrics: list[dict[str, float]],
    sample_period: float,
    cuts: list[float],
) -> float:
    changes: list[float] = []
    for index in range(1, len(output_metrics)):
        time_seconds = index * sample_period
        previous_time = time_seconds - sample_period
        crosses_cut = any(
            abs(time_seconds - cut) <= sample_period or abs(previous_time - cut) <= sample_period
            for cut in cuts
        )
        if not crosses_cut:
            changes.append(
                abs(output_metrics[index]["mean_luma"] - output_metrics[index - 1]["mean_luma"])
            )
    return float(np.percentile(changes, 95)) if changes else 0.0


def analyze_video_quality(
    source: str | Path,
    output: str | Path,
    *,
    graph: GradeGraph | None = None,
    sample_fps: float = 5.0,
    auxiliary_scores: list[AuxiliaryQualityScore] | None = None,
    expected_frame_count: int | None = None,
) -> QualityReport:
    source_path = Path(source).resolve()
    output_path = Path(output).resolve()
    source_metrics, _ = _sample_video(source_path, sample_fps=sample_fps)
    output_metrics, sample_period = _sample_video(output_path, sample_fps=sample_fps)
    sample_count = min(len(source_metrics), len(output_metrics))
    if sample_count == 0:
        raise RuntimeError("no frames were available for quality analysis")
    source_metrics = source_metrics[:sample_count]
    output_metrics = output_metrics[:sample_count]

    highlight_clip = float(np.percentile([item["highlight_clip"] for item in output_metrics], 95))
    shadow_clip = float(np.percentile([item["shadow_clip"] for item in output_metrics], 95))
    oversaturation = float(np.percentile([item["oversaturation"] for item in output_metrics], 95))
    legacy_flicker = _temporal_flicker(
        output_metrics,
        sample_period,
        _cut_intervals(graph),
    )
    temporal_evidence: TemporalQualityEvidence | None = None
    try:
        candidate_evidence = analyze_video_temporal(
            source_path,
            output_path,
            graph=graph,
            sample_fps=sample_fps,
        )
        if candidate_evidence.analyzed_transitions:
            temporal_evidence = candidate_evidence
    except (OSError, RuntimeError, TypeError, ValueError):
        # Preserve analysis for legacy assets while making the fallback explicit:
        # absent evidence is never presented as motion-compensated evidence.
        temporal_evidence = None
    flicker = temporal_evidence.flicker_p95 if temporal_evidence is not None else legacy_flicker
    structure_ratios = [
        output_item["edge_energy"] / max(source_item["edge_energy"], 1e-6)
        for source_item, output_item in zip(
            source_metrics,
            output_metrics,
            strict=True,
        )
    ]
    structure_loss = max(0.0, 1 - float(np.median(structure_ratios)))
    banding_risk = float(np.percentile([item["banding_risk"] for item in output_metrics], 95))
    artifact_metrics = _mask_artifact_metrics(
        source_path,
        output_path,
        graph,
    )
    if temporal_evidence is not None and temporal_evidence.mask_observations:
        artifact_metrics["mask_jitter"] = temporal_evidence.mask_jitter_p95

    checks = [
        *_delivery_checks(
            output_path,
            graph,
            output_metrics,
            expected_frame_count=expected_frame_count,
        ),
        _make_check(
            identifier="highlight_clipping",
            label="高光剪裁",
            value=highlight_clip,
            warning=0.015,
            failure=0.04,
            unit="ratio",
            detail="输出帧中接近纯白的像素比例（95 分位）",
        ),
        _make_check(
            identifier="shadow_crush",
            label="阴影压死",
            value=shadow_clip,
            warning=0.025,
            failure=0.07,
            unit="ratio",
            detail="输出帧中接近纯黑的像素比例（95 分位）",
        ),
        _make_check(
            identifier="oversaturation",
            label="过饱和",
            value=oversaturation,
            warning=0.025,
            failure=0.08,
            unit="ratio",
            detail="HSV 饱和度接近上限的像素比例（95 分位）",
            category=QualityCategory.PERCEPTUAL_RISK,
        ),
        _make_check(
            identifier="temporal_flicker",
            label="时间闪烁",
            value=flicker,
            warning=0.035,
            failure=0.08,
            unit="luma_delta",
            detail=(
                "源视频光流补偿后的调色贡献变化；硬切、源曝光和场景运动单独分类"
                if temporal_evidence is not None
                else "运动证据不可用；回退到排除硬切后的相邻采样帧平均亮度变化"
            ),
            category=QualityCategory.PERCEPTUAL_RISK,
            metric_version=(
                TEMPORAL_METRIC_VERSION
                if temporal_evidence is not None
                else "colorgraph.quality/legacy-temporal-mean/v1"
            ),
        ),
        _make_check(
            identifier="structure_loss",
            label="结构损失",
            value=structure_loss,
            warning=0.18,
            failure=0.35,
            unit="edge_ratio_loss",
            detail="相对输入的梯度能量损失",
            category=QualityCategory.PERCEPTUAL_RISK,
        ),
        _make_check(
            identifier="banding_risk",
            label="色带风险",
            value=banding_risk,
            warning=0.18,
            failure=0.30,
            unit="cambi_equivalent_0_1",
            detail=(
                "多尺度色阶稀疏、平坦度与低对比轮廓联合风险；"
                "这是版本化 CAMBI 等价指标，不冒充 Netflix CAMBI"
            ),
            category=QualityCategory.PERCEPTUAL_RISK,
            metric_version=BANDING_METRIC_VERSION,
        ),
        _make_check(
            identifier="mask_jitter",
            label="蒙版抖动",
            value=artifact_metrics["mask_jitter"],
            warning=0.06,
            failure=0.13,
            unit=(
                "motion_compensated_boundary_delta"
                if temporal_evidence is not None and temporal_evidence.mask_observations
                else "mean_absolute_delta"
            ),
            detail=(
                "源视频光流补偿后的蒙版及边界变化（95 分位）"
                if temporal_evidence is not None and temporal_evidence.mask_observations
                else "运动证据不可用；使用未配准的逐帧蒙版变化（95 分位）"
            ),
            category=QualityCategory.PERCEPTUAL_RISK,
            metric_version=(
                TEMPORAL_METRIC_VERSION
                if temporal_evidence is not None and temporal_evidence.mask_observations
                else "colorgraph.quality/legacy-mask-mae/v1"
            ),
        ),
        _make_check(
            identifier="mask_halo",
            label="蒙版光晕",
            value=artifact_metrics["mask_halo"],
            warning=0.10,
            failure=0.20,
            unit="boundary_laplacian",
            detail="天空蒙版边界附近由调色引入的亮度二阶变化",
            category=QualityCategory.PERCEPTUAL_RISK,
        ),
        _make_check(
            identifier="sky_banding",
            label="天空色带",
            value=artifact_metrics["sky_banding"],
            warning=0.55,
            failure=0.78,
            unit="quantization_risk",
            detail="天空有效亮度区间的量化级占用不足风险",
            category=QualityCategory.PERCEPTUAL_RISK,
            metric_version="colorgraph.sky-level-occupancy/v1",
        ),
    ]
    supplied_auxiliary = list(auxiliary_scores or [])
    uncalibrated = [item.id for item in supplied_auxiliary if not item.domain_calibrated]
    if uncalibrated:
        raise ValueError(
            "auxiliary quality scores require domain calibration before use: "
            f"{sorted(uncalibrated)}"
        )
    penalties = {
        CheckStatus.PASS: 0,
        CheckStatus.WARN: 6,
        CheckStatus.FAIL: 18,
    }
    technical_checks = [
        check for check in checks if check.category == QualityCategory.HARD_TECHNICAL
    ]
    risk_checks = [check for check in checks if check.category == QualityCategory.PERCEPTUAL_RISK]
    technical_score = max(
        0,
        100 - sum(penalties[check.status] for check in technical_checks),
    )
    perceptual_risk_score = max(
        0,
        100 - sum(penalties[check.status] for check in risk_checks),
    )
    score = round(technical_score * 0.75 + perceptual_risk_score * 0.25)
    hard_passed = all(check.status != CheckStatus.FAIL for check in technical_checks)
    failures = [check.label for check in technical_checks if check.status == CheckStatus.FAIL]
    risks = [
        check.label for check in risk_checks if check.status in {CheckStatus.WARN, CheckStatus.FAIL}
    ]
    warnings = [check.label for check in technical_checks if check.status == CheckStatus.WARN]
    if failures:
        summary = f"技术硬检查未通过：{'、'.join(failures)}"
    elif risks:
        summary = f"技术硬检查通过；感知风险需复核：{'、'.join(risks)}"
    elif warnings:
        summary = f"技术硬检查通过；未知项需复核：{'、'.join(warnings)}"
    else:
        summary = "技术硬检查通过，未发现显著感知风险"
    return QualityReport(
        source_path=str(source_path),
        output_path=str(output_path),
        sampled_frames=sample_count,
        score=score,
        hard_checks_passed=hard_passed,
        checks=checks,
        summary=summary,
        metrics={
            "highlight_clip_p95": highlight_clip,
            "shadow_clip_p95": shadow_clip,
            "oversaturation_p95": oversaturation,
            "flicker_p95": flicker,
            "raw_flicker_p95": (
                temporal_evidence.raw_flicker_p95
                if temporal_evidence is not None
                else legacy_flicker
            ),
            "structure_loss": structure_loss,
            "banding_risk_p95": banding_risk,
            **{f"auxiliary.{item.id}": item.value for item in supplied_auxiliary},
            **artifact_metrics,
            **(
                {
                    "raw_mask_jitter_p95": temporal_evidence.raw_mask_jitter_p95,
                    "motion_valid_flow_ratio": temporal_evidence.mean_valid_flow_ratio,
                    "source_change_suppressed_transitions": float(
                        temporal_evidence.suppressed_source_change_transitions
                    ),
                }
                if temporal_evidence is not None
                else {}
            ),
        },
        technical_score=technical_score,
        perceptual_risk_score=perceptual_risk_score,
        technical_hard_failures=[
            check.id for check in technical_checks if check.status == CheckStatus.FAIL
        ],
        perceptual_risks=[
            check.id
            for check in risk_checks
            if check.status in {CheckStatus.WARN, CheckStatus.FAIL}
        ],
        auxiliary_scores=supplied_auxiliary,
        aesthetic_preferences=[
            item
            for item in supplied_auxiliary
            if item.kind == AuxiliaryScoreKind.AESTHETIC_PREFERENCE
        ],
        temporal_evidence=temporal_evidence,
    )
