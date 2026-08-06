import json
from pathlib import Path

import pytest

from colorgraph.domain.grade_graph import (
    ColorSpace,
    GradeGraph,
    MetadataConfidence,
    MetadataSource,
)
from colorgraph.grading.color import SONY_SLOG3_SGAMUT3CINE
from colorgraph.media import probe as probe_module
from colorgraph.media.metadata import apply_color_management_override
from colorgraph.media.probe import _parse_frame_rate
from colorgraph.storage import ProjectStore

FIXTURES = Path(__file__).parent / "fixtures" / "ffprobe"


def _probe_fixture(name: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    payload = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    source = tmp_path / f"{Path(name).stem}.mov"
    source.write_bytes(b"ffprobe fixture")
    monkeypatch.setattr(probe_module, "_run_ffprobe", lambda _: payload)
    return probe_module.probe_media(source)


def test_parse_fractional_frame_rate() -> None:
    assert round(_parse_frame_rate("30000/1001"), 3) == 29.97


def test_rec709_fixture_preserves_declared_color_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    media = _probe_fixture("rec709_8bit.json", tmp_path, monkeypatch)

    assert media.color_range == "limited"
    assert media.color_primaries == "bt709"
    assert media.color_transfer == "bt709"
    assert media.color_matrix == "bt709"
    assert media.bit_depth == 8
    assert media.chroma_subsampling == "4:2:0"
    assert media.chroma_location == "left"
    assert media.input_color_space == ColorSpace.BT709_OETF
    assert media.metadata_evidence.color_transfer.source == MetadataSource.STREAM
    assert media.metadata_evidence.color_transfer.confidence == MetadataConfidence.HIGH
    assert not media.metadata_evidence.color_transfer.conflict


def test_camera_log_fixture_uses_explicit_profile_and_keeps_missing_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probed = _probe_fixture("camera_log_10bit.json", tmp_path, monkeypatch)
    media = apply_color_management_override(
        probed,
        ColorSpace.LOG,
        SONY_SLOG3_SGAMUT3CINE,
    )

    assert media.bit_depth == 10
    assert media.chroma_subsampling == "4:2:2"
    assert media.color_primaries is None
    assert media.color_transfer is None
    assert media.color_matrix is None
    assert media.metadata_evidence.color_transfer.source == MetadataSource.MISSING
    assert media.metadata_evidence.color_transfer.confidence == MetadataConfidence.UNKNOWN
    assert media.input_color_space == ColorSpace.LOG
    assert media.source_log_profile == SONY_SLOG3_SGAMUT3CINE
    assert media.metadata_evidence.input_color_space.source == MetadataSource.USER_OVERRIDE
    assert media.metadata_evidence.source_log_profile.source == MetadataSource.USER_OVERRIDE


def test_hdr10_fixture_reads_pixel_depth_and_first_frame_side_data(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    media = _probe_fixture("hdr10_10bit.json", tmp_path, monkeypatch)

    assert media.color_range == "limited"
    assert media.color_primaries == "bt2020"
    assert media.color_transfer == "smpte2084"
    assert media.color_matrix == "bt2020nc"
    assert media.bit_depth == 10
    assert media.chroma_subsampling == "4:2:0"
    assert media.metadata_evidence.bit_depth.source == MetadataSource.PIXEL_FORMAT
    assert media.metadata_evidence.bit_depth.confidence == MetadataConfidence.MEDIUM
    assert media.hdr_metadata.format == "hdr10"
    assert media.hdr_metadata.mastering_display is not None
    assert media.hdr_metadata.mastering_display.red.x == pytest.approx(0.708)
    assert media.hdr_metadata.mastering_display.max_luminance == pytest.approx(1000)
    assert media.hdr_metadata.content_light is not None
    assert media.hdr_metadata.content_light.max_content_light_level == 1000
    assert media.hdr_metadata.content_light.max_frame_average_light_level == 400
    assert media.metadata_evidence.hdr_metadata.source == MetadataSource.SIDE_DATA
    assert media.metadata_evidence.input_color_space.conflict
    assert "unsupported" in (media.metadata_evidence.input_color_space.note or "")


def test_stream_metadata_wins_over_conflicting_container_tags(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    media = _probe_fixture("conflicting_color_tags.json", tmp_path, monkeypatch)

    assert media.color_range == "limited"
    assert media.color_primaries == "bt709"
    assert media.color_transfer == "bt709"
    assert media.metadata_evidence.color_range.conflict
    assert media.metadata_evidence.color_primaries.conflict
    assert media.metadata_evidence.color_transfer.conflict
    assert media.metadata_evidence.color_transfer.source == MetadataSource.STREAM


def test_user_override_records_a_transfer_conflict_without_discarding_stream_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probed = _probe_fixture("rec709_8bit.json", tmp_path, monkeypatch)
    media = apply_color_management_override(
        probed,
        ColorSpace.LOG,
        SONY_SLOG3_SGAMUT3CINE,
    )

    assert media.color_transfer == "bt709"
    assert media.input_color_space == ColorSpace.LOG
    assert media.metadata_evidence.input_color_space.conflict
    assert media.metadata_evidence.input_color_space.source == MetadataSource.USER_OVERRIDE
    assert "overrides incompatible" in (media.metadata_evidence.input_color_space.note or "")


def test_media_color_metadata_round_trips_through_project_storage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    media = _probe_fixture("hdr10_10bit.json", tmp_path, monkeypatch)
    store = ProjectStore(tmp_path / "projects")
    project = store.create("HDR metadata")
    graph = GradeGraph(
        id="graph_hdr_metadata",
        project_id=project.id,
        project_name="HDR metadata",
        media=media,
    )

    store.save_graph(project, graph)
    restored = store.load_graph(project.id)

    assert restored.media == media
    assert restored.media.hdr_metadata.mastering_display is not None
    assert restored.media.metadata_evidence.hdr_metadata.source == MetadataSource.SIDE_DATA
