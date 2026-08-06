from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import numpy as np
import pytest

from colorgraph.domain.grade_graph import (
    ColorSpace,
    GradeNode,
    MaskAsset,
    MediaInfo,
    NodeType,
    ScopeLevel,
    SpatialKind,
    SpatialScope,
    TemporalScope,
    TimeRange,
)
from colorgraph.evaluation import production_benchmark
from colorgraph.evaluation.production_benchmark import (
    REQUIRED_PROFILES,
    REQUIRED_THERMAL_STATES,
    REQUIRED_VARIANTS,
    BenchmarkMaskModel,
    BenchmarkSource,
    ProductionBenchmarkCase,
    ProgressLatencyTracker,
    prepare_benchmark_graph,
    required_case_keys,
    summarize_benchmark_report,
)
from colorgraph.quality import QualityReport
from colorgraph.services.graph_builder import build_initial_graph


def _benchmark_graph():
    graph = build_initial_graph(
        project_id="production-benchmark",
        project_name="Production benchmark",
        media=MediaInfo(
            path="source.mov",
            duration_seconds=125,
            width=3840,
            height=2160,
            fps=24,
            frame_count=3000,
            codec="prores",
            pixel_format="yuv422p10le",
            bit_depth=10,
            input_color_space=ColorSpace.BT709_OETF,
        ),
        shot_ranges=[TimeRange(start_seconds=0, end_seconds=125)],
        representative_frames=[None],
    )
    assets = [
        MaskAsset(
            id="mask_sky",
            kind=SpatialKind.SEMANTIC,
            target="sky",
            path="masks/sky",
            frame_count=3000,
            metadata={
                "schema": "colorgraph.mask-asset/v3",
                "provider": "nvidia/segformer-b0",
                "tracking": {"algorithm": "farneback_backward_flow_warp"},
                "target_aliases": ["mask_sky", "sky"],
            },
        ),
        MaskAsset(
            id="mask_depth",
            kind=SpatialKind.DEPTH,
            target="depth_far",
            path="masks/depth",
            frame_count=3000,
            metadata={
                "schema": "colorgraph.mask-asset/v3",
                "provider": "depth-anything/Depth-Anything-V2-Small-hf",
                "tracking": {"algorithm": "farneback_backward_flow_warp"},
                "target_aliases": ["mask_depth", "depth_far"],
            },
        ),
        MaskAsset(
            id="mask_sam",
            kind=SpatialKind.PROMPTED,
            target="subject",
            path="masks/sam",
            frame_count=3000,
            metadata={
                "schema": "colorgraph.mask-asset/v3",
                "provider": "facebook/sam2.1-hiera-small",
                "tracking": {"algorithm": "sam_2.1_video_propagation"},
                "target_aliases": ["mask_sam", "subject"],
            },
        ),
    ]
    graph.masks = assets
    order = max(node.order for node in graph.nodes) + 1
    for index, asset in enumerate(assets):
        graph.nodes.append(
            GradeNode(
                id=f"grade_{asset.target}",
                type=NodeType.MASKED_GRADE,
                label=f"Grade {asset.target}",
                order=order + index,
                temporal_scope=TemporalScope(
                    level=ScopeLevel.PROJECT,
                    project_id=graph.project_id,
                ),
                spatial_scope=SpatialScope(
                    kind=asset.kind,
                    target=asset.target,
                    mask_asset_id=asset.id,
                ),
                parameters={"exposure": 0.1},
            )
        )
    return graph


def test_prepare_benchmark_graph_isolates_every_mask_variant() -> None:
    graph = _benchmark_graph()
    expected = {
        "no_mask": set(),
        "farneback": {"mask_sky"},
        "vda": {"mask_depth"},
        "sam21": {"mask_sam"},
        "current_combined": {"mask_sky", "mask_depth", "mask_sam"},
    }

    for variant, asset_ids in expected.items():
        prepared, models, blocker = prepare_benchmark_graph(graph, variant)
        assert blocker is None
        assert prepared is not None
        assert {asset.id for asset in prepared.masks} == asset_ids
        assert {model.asset_id for model in models} == asset_ids
        assert all(not model.provenance_complete for model in models)
        assert all("model_revision_missing" in model.provenance_blockers for model in models)
        for node in prepared.nodes:
            mask_id = node.spatial_scope.mask_asset_id
            if mask_id is not None:
                assert node.enabled is (mask_id in asset_ids)

    assert {asset.id for asset in graph.masks} == {
        "mask_sky",
        "mask_depth",
        "mask_sam",
    }


def test_benchmark_descriptor_accepts_nested_prediction_provenance() -> None:
    graph = _benchmark_graph()
    graph.masks[0].metadata.update(
        {
            "prediction_evidence": {
                "model_revision": "a" * 40,
                "checkpoint_sha256": "b" * 64,
            },
            "video_sha256": "c" * 64,
        }
    )

    prepared, models, blocker = prepare_benchmark_graph(graph, "farneback")

    assert prepared is not None
    assert blocker is None
    assert len(models) == 1
    assert models[0].model_revision == "a" * 40
    assert models[0].checkpoint_sha256 == "b" * 64
    assert models[0].asset_content_sha256 == "c" * 64
    assert models[0].provenance_complete is True
    assert models[0].provenance_blockers == []


def test_prepare_benchmark_graph_blocks_missing_sam21() -> None:
    graph = _benchmark_graph()
    graph.masks = [asset for asset in graph.masks if asset.id != "mask_sam"]
    graph.nodes = [node for node in graph.nodes if node.spatial_scope.mask_asset_id != "mask_sam"]

    prepared, models, blocker = prepare_benchmark_graph(graph, "sam21")

    assert prepared is None
    assert models == []
    assert blocker == "no audited SAM 2.1 video mask asset is installed"


def test_sam21_variant_can_replace_a_same_target_current_mask() -> None:
    graph = _benchmark_graph()
    current = graph.masks[0]
    sam = graph.masks[2]
    sam.target = current.target
    sam.metadata["target_aliases"] = [
        sam.id,
        sam.target,
        current.id,
    ]
    sam_node = next(
        node
        for node in graph.nodes
        if node.spatial_scope.mask_asset_id == sam.id
    )
    sam_node.enabled = False
    current_node = next(
        node
        for node in graph.nodes
        if node.spatial_scope.mask_asset_id == current.id
    )

    prepared, _, blocker = prepare_benchmark_graph(graph, "sam21")

    assert blocker is None
    assert prepared is not None
    prepared_current = next(
        node for node in prepared.nodes if node.id == current_node.id
    )
    assert prepared_current.enabled is True
    assert prepared_current.spatial_scope.mask_asset_id == sam.id
    assert prepared_current.spatial_scope.kind == sam.kind
    assert prepared_current.spatial_scope.target == sam.target


def test_current_combined_ignores_an_installed_but_unreferenced_mask() -> None:
    graph = _benchmark_graph()
    unused = graph.masks[2].model_copy(
        update={
            "id": "mask_sam_unused",
            "target": graph.masks[0].target,
            "metadata": {
                **graph.masks[2].metadata,
                "target_aliases": ["mask_sam_unused", "mask_sky"],
            },
        },
        deep=True,
    )
    graph.masks.append(unused)

    prepared, models, blocker = prepare_benchmark_graph(
        graph,
        "current_combined",
    )

    assert blocker is None
    assert prepared is not None
    assert {asset.id for asset in prepared.masks} == {
        "mask_sky",
        "mask_depth",
        "mask_sam",
    }
    assert {model.asset_id for model in models} == {
        "mask_sky",
        "mask_depth",
        "mask_sam",
    }


def test_progress_latency_tracker_reports_frame_equivalent_p95() -> None:
    values = iter([0.0, 0.1, 0.3, 0.7])
    tracker = ProgressLatencyTracker(clock=lambda: next(values))

    tracker(0, 10)
    tracker(4, 10)
    tracker(8, 10)
    tracker(10, 10)

    assert tracker.frame_latency_ms == pytest.approx([25.0, 50.0, 200.0])
    assert tracker.p95_ms == pytest.approx(
        float(np.percentile(np.asarray([25.0, 50.0, 200.0]), 95))
    )


def test_segmented_benchmark_does_not_require_full_source_timing_scan() -> None:
    source = _source()

    assert not production_benchmark._requires_full_source_timings(
        source,
        start_seconds=0,
        end_seconds=1,
    )
    assert production_benchmark._requires_full_source_timings(
        source,
        start_seconds=0,
        end_seconds=source.duration_seconds,
    )


def test_software_snapshot_freezes_tool_and_driver_versions(
    monkeypatch,
) -> None:
    responses = {
        (
            production_benchmark.settings.ffmpeg_binary,
            "-version",
        ): "ffmpeg version 8.0\nconfiguration",
        (
            production_benchmark.settings.ffprobe_binary,
            "-version",
        ): "ffprobe version 8.0\nconfiguration",
        (
            "nvidia-smi",
            "--query-gpu=driver_version",
            "--format=csv,noheader",
        ): "610.47\n610.47\n",
    }

    def run(command, **_kwargs):
        return SimpleNamespace(
            returncode=0,
            stdout=responses[tuple(command)],
        )

    monkeypatch.setattr(production_benchmark.subprocess, "run", run)

    snapshot = production_benchmark._software_snapshot()

    assert snapshot["ffmpeg_version"] == "ffmpeg version 8.0"
    assert snapshot["ffprobe_version"] == "ffprobe version 8.0"
    assert snapshot["nvidia_driver_version"] == "610.47"


def _completed_case(case_key: str) -> ProductionBenchmarkCase:
    variant, profile, thermal = case_key.split(":")
    quality_required = variant == "current_combined" and thermal == "warm"
    now = datetime.now(UTC)
    return ProductionBenchmarkCase(
        case_key=case_key,
        input_digest="a" * 64,
        status="completed",
        variant=variant,
        profile=profile,
        thermal_state=thermal,
        graph_digest="b" * 64,
        verify_mask_storage=thermal == "cold",
        output_path=f"output/{case_key}.mp4",
        output_sha256="c" * 64,
        output_bytes=100,
        frame_count=3600,
        elapsed_seconds=60,
        processing_fps=60,
        encoder="encoder",
        quality_checked=quality_required,
        quality_score=100 if quality_required else None,
        hard_quality_checks_passed=True if quality_required else None,
        quality_report_path=(
            f"output/{case_key}.quality.json" if quality_required else None
        ),
        quality_report_sha256="d" * 64 if quality_required else None,
        started_at=now,
        completed_at=now,
    )


def _source() -> BenchmarkSource:
    return BenchmarkSource(
        project_id="licensed-production-project",
        path="source.mov",
        size_bytes=1_000_000,
        modified_time_ns=1,
        sha256="d" * 64,
        width=3840,
        height=2160,
        fps=30,
        duration_seconds=125,
        frame_count=3750,
        codec="prores",
        pixel_format="yuv422p10le",
        real_long_media_qualified=True,
    )


def test_checkpoint_reuses_when_only_unused_source_graph_state_changed(
    tmp_path,
) -> None:
    source = _source()
    case_key = "no_mask:proxy_1080p:cold"
    variant_digest = "b" * 64
    prior_source_digest = "e" * 64
    current_source_digest = "f" * 64
    profile = production_benchmark.PROFILE_PRESETS["proxy_1080p"]
    prior_input_digest = production_benchmark._case_digest(
        source=source,
        source_graph_digest=prior_source_digest,
        variant_graph_digest=variant_digest,
        variant="no_mask",
        profile=profile,
        thermal_state="cold",
        start_seconds=0,
        end_seconds=125,
    )
    output = tmp_path / "render.mp4"
    output.write_bytes(b"verified render")
    prior_case = _completed_case(case_key).model_copy(
        update={
            "input_digest": prior_input_digest,
            "graph_digest": variant_digest,
            "output_path": str(output),
            "output_sha256": production_benchmark._file_sha256(output),
            "output_bytes": output.stat().st_size,
        }
    )
    prior_report = summarize_benchmark_report(
        created_at=datetime.now(UTC),
        run_id="prior",
        source=source,
        source_graph_digest=prior_source_digest,
        render_start_seconds=0,
        render_end_seconds=125,
        hardware={"runtime": "cuda"},
        software={"torch": "test"},
        requested_variants=["no_mask"],
        requested_profiles=["proxy_1080p"],
        requested_thermal_states=["cold"],
        cases=[prior_case],
        quality_checks_required=False,
    )

    compatible_digest = production_benchmark._compatible_prior_input_digest(
        prior_report,
        source=source,
        case_key=case_key,
        variant_graph_digest=variant_digest,
        variant="no_mask",
        profile=profile,
        thermal_state="cold",
        batch_size=4,
        start_seconds=0,
        end_seconds=125,
    )
    current_input_digest = production_benchmark._case_digest(
        source=source,
        source_graph_digest=current_source_digest,
        variant_graph_digest=variant_digest,
        variant="no_mask",
        profile=profile,
        thermal_state="cold",
        start_seconds=0,
        end_seconds=125,
    )
    sidecar = tmp_path / "case.json"
    sidecar.write_text(prior_case.model_dump_json(), encoding="utf-8")

    resumed = production_benchmark._load_checkpoint(
        sidecar,
        input_digest=current_input_digest,
        compatible_input_digests=(compatible_digest,),
        expected_case_key=case_key,
        expected_graph_digest=variant_digest,
    )

    assert compatible_digest == prior_input_digest
    assert resumed is not None
    assert resumed.input_digest == current_input_digest
    assert resumed.resumed_from_input_digest == prior_input_digest
    assert resumed.measurement_origin == "compatible_checkpoint"
    assert (
        resumed.checkpoint_reuse_reason
        == "source_graph_changed_variant_graph_unchanged"
    )
    assert resumed.resumed_from_checkpoint is True
    sidecar.write_text(resumed.model_dump_json(), encoding="utf-8")
    revalidated = production_benchmark._load_checkpoint(
        sidecar,
        input_digest=current_input_digest,
        expected_case_key=case_key,
        expected_graph_digest=variant_digest,
        expected_batch_size=4,
    )
    assert revalidated is not None
    assert revalidated.resumed_from_input_digest == prior_input_digest
    assert revalidated.measurement_origin == "compatible_checkpoint"
    assert (
        revalidated.checkpoint_reuse_reason
        == "source_graph_changed_variant_graph_unchanged"
    )
    assert (
        production_benchmark._compatible_prior_input_digest(
            prior_report,
            source=source,
            case_key=case_key,
            variant_graph_digest="0" * 64,
            variant="no_mask",
            profile=profile,
            thermal_state="cold",
            batch_size=4,
            start_seconds=0,
            end_seconds=125,
        )
        is None
    )
    assert (
        production_benchmark._load_checkpoint(
            sidecar,
            input_digest=current_input_digest,
            compatible_input_digests=(compatible_digest,),
            expected_case_key=case_key,
            expected_graph_digest=variant_digest,
            expected_batch_size=8,
        )
        is None
    )


def test_checkpoint_binds_and_validates_quality_report_hash(tmp_path) -> None:
    case_key = "current_combined:proxy_1080p:warm"
    output = tmp_path / "render.mp4"
    output.write_bytes(b"verified quality render")
    quality_path = tmp_path / "render.quality.json"
    quality = QualityReport(
        source_path=str(tmp_path / "source.mov"),
        output_path=str(output),
        sampled_frames=1,
        score=100,
        hard_checks_passed=True,
        checks=[],
        summary="quality fixture",
    )
    quality_path.write_text(quality.model_dump_json(), encoding="utf-8")
    case = _completed_case(case_key).model_copy(
        update={
            "output_path": str(output),
            "output_sha256": production_benchmark._file_sha256(output),
            "output_bytes": output.stat().st_size,
            "quality_report_path": str(quality_path),
            "quality_report_sha256": None,
        }
    )
    sidecar = tmp_path / "case.json"
    sidecar.write_text(case.model_dump_json(), encoding="utf-8")

    resumed = production_benchmark._load_checkpoint(
        sidecar,
        input_digest=case.input_digest,
        expected_case_key=case_key,
        expected_graph_digest=case.graph_digest,
        expected_batch_size=4,
    )

    assert resumed is not None
    assert resumed.quality_report_sha256 == production_benchmark._file_sha256(
        quality_path
    )

    quality_path.write_text("{}", encoding="utf-8")
    assert (
        production_benchmark._load_checkpoint(
            sidecar,
            input_digest=case.input_digest,
            expected_case_key=case_key,
            expected_graph_digest=case.graph_digest,
            expected_batch_size=4,
        )
        is None
    )


def test_full_matrix_is_required_before_production_claim() -> None:
    keys = required_case_keys()
    cases = [_completed_case(key) for key in keys]
    report = summarize_benchmark_report(
        created_at=datetime.now(UTC),
        run_id="run",
        source=_source(),
        source_graph_digest="e" * 64,
        render_start_seconds=0,
        render_end_seconds=125,
        hardware={"runtime": "cuda"},
        software={"torch": "test"},
        requested_variants=REQUIRED_VARIANTS,
        requested_profiles=REQUIRED_PROFILES,
        requested_thermal_states=REQUIRED_THERMAL_STATES,
        cases=cases,
        quality_checks_required=True,
    )

    assert report.status == "complete"
    assert report.production_claim_allowed is True
    assert report.completed_coverage == sorted(keys)
    assert report.missing_coverage == []

    sam_key = "sam21:master_4k:warm"
    partial_cases = [case for case in cases if case.case_key != sam_key]
    now = datetime.now(UTC)
    partial_cases.append(
        ProductionBenchmarkCase(
            case_key=sam_key,
            input_digest="a" * 64,
            status="blocked",
            variant="sam21",
            profile="master_4k",
            thermal_state="warm",
            graph_digest="b" * 64,
            verify_mask_storage=False,
            blocker="no audited SAM 2.1 video mask asset is installed",
            started_at=now,
            completed_at=now,
        )
    )
    partial = summarize_benchmark_report(
        created_at=datetime.now(UTC),
        run_id="run",
        source=_source(),
        source_graph_digest="e" * 64,
        render_start_seconds=0,
        render_end_seconds=125,
        hardware={"runtime": "cuda"},
        software={"torch": "test"},
        requested_variants=REQUIRED_VARIANTS,
        requested_profiles=REQUIRED_PROFILES,
        requested_thermal_states=REQUIRED_THERMAL_STATES,
        cases=partial_cases,
        quality_checks_required=True,
    )

    assert partial.status == "partial"
    assert partial.production_claim_allowed is False
    assert partial.blocked_coverage == [sam_key]


def test_incomplete_mask_model_provenance_blocks_production_claim() -> None:
    keys = required_case_keys()
    cases = [_completed_case(key) for key in keys]
    affected_key = "farneback:master_4k:warm"
    affected_index = next(
        index for index, case in enumerate(cases) if case.case_key == affected_key
    )
    cases[affected_index] = cases[affected_index].model_copy(
        update={
            "mask_models": [
                BenchmarkMaskModel(
                    asset_id="mask_sky",
                    kind="semantic",
                    target="sky",
                    provider="nvidia/segformer-b0",
                    tracking_algorithm="farneback_backward_flow_warp",
                    asset_schema="colorgraph.mask-asset/v3",
                    asset_content_sha256="f" * 64,
                    metadata_sha256="e" * 64,
                    provenance_complete=False,
                    provenance_blockers=[
                        "model_revision_missing",
                        "checkpoint_sha256_missing",
                    ],
                )
            ]
        }
    )

    report = summarize_benchmark_report(
        created_at=datetime.now(UTC),
        run_id="run",
        source=_source(),
        source_graph_digest="e" * 64,
        render_start_seconds=0,
        render_end_seconds=125,
        hardware={"runtime": "cuda"},
        software={"torch": "test"},
        requested_variants=REQUIRED_VARIANTS,
        requested_profiles=REQUIRED_PROFILES,
        requested_thermal_states=REQUIRED_THERMAL_STATES,
        cases=cases,
        quality_checks_required=True,
    )

    assert report.model_provenance_complete is False
    assert report.model_provenance_blockers[affected_key] == [
        "mask_sky:checkpoint_sha256_missing",
        "mask_sky:model_revision_missing",
    ]
    assert report.production_claim_allowed is False
