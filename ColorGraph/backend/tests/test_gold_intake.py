import hashlib
from pathlib import Path

import pytest
from pydantic import ValidationError

from colorgraph.domain.grade_graph import ColorSpace, TimeRange
from colorgraph.evaluation.intake import (
    GoldSourceInspectionReport,
    GoldSourceRegistry,
    create_annotation_work_pack,
    load_source_registry,
    source_registry_status,
)
from colorgraph.evaluation.manifest import MediaOrigin
from colorgraph.media.probe import VideoFrameTiming


def _registry_path() -> Path:
    return (
        Path(__file__).parents[1]
        / "data"
        / "gold_set_intake_v1"
        / "source_candidates.json"
    )


def test_checked_in_real_source_registry_is_strict_and_license_aware() -> None:
    registry = load_source_registry(_registry_path())

    assert registry.schema_version == "colorgraph.gold-source-candidates/v1"
    assert len(registry.candidates) == 6
    assert all(
        candidate.commercial_use_allowed
        for candidate in registry.candidates
    )
    public_candidates = [
        candidate
        for candidate in registry.candidates
        if candidate.source_page_url is not None
    ]
    assert len(public_candidates) == 5
    assert all(
        str(candidate.source_page_url).startswith(
            "https://commons.wikimedia.org/"
        )
        for candidate in public_candidates
    )
    private_candidate = next(
        candidate
        for candidate in registry.candidates
        if candidate.id
        == "licensed-mediastorm-dji-mavic3-pro-cine-dlog"
    )
    assert private_candidate.source_page_url is None
    assert private_candidate.media_url is None
    assert private_candidate.license_url is None
    assert private_candidate.license_evidence_path == (
        "licenses/mediastorm-personal-commercial-license-user-attestation.md"
    )
    assert private_candidate.media_origin == MediaOrigin.LICENSED_STOCK
    assert not private_candidate.redistribution_allowed
    assert private_candidate.declared_input_color_space == ColorSpace.LOG
    assert private_candidate.declared_log_profile == (
        "dji_mavic3_dlog_rec709_v1"
    )
    assert {
        candidate.camera
        for candidate in registry.candidates
        if "not specified" not in candidate.camera
    } == {
        "Apple iPhone X",
        "Canon EOS M3",
        "DJI Mavic 3 Pro Cine",
        "DJI Phantom 2 Vision+ / DJI FC200",
        "Sony DSC-RX10 III",
    }


def test_source_registry_status_never_treats_missing_media_as_ready(
    tmp_path: Path,
) -> None:
    status = source_registry_status(_registry_path(), root=tmp_path)

    assert status.candidates == 6
    assert status.documented_camera_candidates == 5
    assert status.downloaded_candidates == 0
    assert len(status.missing_candidates) == 6
    assert not status.zero_byte_candidates
    assert status.missing_license_evidence_candidates == [
        "licensed-mediastorm-dji-mavic3-pro-cine-dlog"
    ]
    assert not status.zero_byte_license_evidence_candidates
    assert not status.ready_for_annotation


def test_source_registry_rejects_duplicate_source_groups() -> None:
    registry = load_source_registry(_registry_path())
    payload = registry.model_dump(mode="json")
    payload["candidates"][1]["source_group_id"] = payload["candidates"][0][
        "source_group_id"
    ]

    with pytest.raises(
        ValidationError,
        match="source candidate groups must be unique",
    ):
        GoldSourceRegistry.model_validate(payload)


def test_private_source_requires_contained_license_evidence() -> None:
    registry = load_source_registry(_registry_path())
    payload = registry.model_dump(mode="json")
    private_candidate = next(
        candidate
        for candidate in payload["candidates"]
        if candidate["source_page_url"] is None
    )
    private_candidate["license_evidence_path"] = None

    with pytest.raises(
        ValidationError,
        match="public source page or contained private license evidence",
    ):
        GoldSourceRegistry.model_validate(payload)

    private_candidate["license_evidence_path"] = "../outside.md"
    with pytest.raises(
        ValidationError,
        match="license evidence path must be relative and contained",
    ):
        GoldSourceRegistry.model_validate(payload)


def test_declared_log_input_requires_a_profile() -> None:
    registry = load_source_registry(_registry_path())
    payload = registry.model_dump(mode="json")
    private_candidate = next(
        candidate
        for candidate in payload["candidates"]
        if candidate["source_page_url"] is None
    )
    private_candidate["declared_log_profile"] = None

    with pytest.raises(
        ValidationError,
        match="declared Log input requires a declared Log profile",
    ):
        GoldSourceRegistry.model_validate(payload)


def _write_synthetic_inspection(tmp_path: Path) -> tuple[Path, Path]:
    checked_in = (
        _registry_path().parent / "intake-inspection.json"
    )
    report = GoldSourceInspectionReport.model_validate_json(
        checked_in.read_text(encoding="utf-8")
    )
    media_root = tmp_path / "media"
    media_root.mkdir()
    media_path = media_root / "source.bin"
    media_path.write_bytes(b"frame-accurate-source")
    timing_digest = hashlib.sha256()
    for index in range(4):
        timing_digest.update(
            f"{index}\0{index * 0.04:.12f}\0{0.04:.12f}\n".encode()
        )
    source = report.sources[0].model_copy(
        update={
            "local_media_path": "media/source.bin",
            "media_sha256": hashlib.sha256(
                media_path.read_bytes()
            ).hexdigest(),
            "probe": report.sources[0].probe.model_copy(
                update={"frame_count": 4}
            ),
            "frame_timing_count": 4,
            "frame_timing_sha256": timing_digest.hexdigest(),
            "draft_shot_ranges": [
                TimeRange(start_seconds=0.04, end_seconds=0.12)
            ],
        }
    )
    synthetic = report.model_copy(
        update={"sources": [source], "total_source_groups": 1, "total_draft_shots": 1}
    )
    inspection_path = tmp_path / "inspection.json"
    inspection_path.write_text(
        synthetic.model_dump_json(indent=2),
        encoding="utf-8",
    )
    return inspection_path, media_path


def test_annotation_work_pack_freezes_exact_frame_timing_and_roles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inspection_path, _ = _write_synthetic_inspection(tmp_path)
    timings = [
        VideoFrameTiming(index * 0.04, 0.04)
        for index in range(4)
    ]
    monkeypatch.setattr(
        "colorgraph.evaluation.intake.probe_frame_timings",
        lambda _: timings,
    )

    pack = create_annotation_work_pack(
        inspection_path,
        tmp_path / "work-pack.json",
        root=tmp_path,
    )

    assert pack.annotation_guideline_version == (
        "colorgraph.landscape-annotation/v1"
    )
    assert pack.required_roles == ["annotator", "independent_reviewer"]
    assert len(pack.items) == 1
    item = pack.items[0]
    assert item.frame_count == 4
    assert [timing.frame_index for timing in item.frame_timings] == [0, 1, 2, 3]
    assert [timing.timeline_seconds for timing in item.frame_timings] == [
        0.0,
        0.04,
        0.08,
        0.12,
    ]
    assert item.draft_ranges[0].first_frame_index == 1
    assert item.draft_ranges[0].last_frame_index == 2
    assert item.truth_status == "pending_independent_human_annotation"


def test_annotation_work_pack_rejects_changed_source_media(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inspection_path, media_path = _write_synthetic_inspection(tmp_path)
    media_path.write_bytes(b"changed-after-inspection")
    monkeypatch.setattr(
        "colorgraph.evaluation.intake.probe_frame_timings",
        lambda _: [VideoFrameTiming(0.0, 0.04)],
    )

    with pytest.raises(ValueError, match="checksum changed"):
        create_annotation_work_pack(
            inspection_path,
            tmp_path / "work-pack.json",
            root=tmp_path,
        )
