from __future__ import annotations

import tempfile

from app.demo.business_cases import (
    DEMO_DELIVERY_DATE,
    is_complete_synthetic_pdf,
    repair_experience_case_pdfs,
    seed_experience_case,
    synthetic_pdf_bytes,
    upgrade_experience_case_media,
)
from app.evidence.workspace import CaseWorkspace
from app.schemas.evidence import EvidenceNode, SourceKind, SourceRole


def test_generated_synthetic_pdf_has_complete_cross_reference_structure():
    content = synthetic_pdf_bytes(
        "demo_a",
        SourceRole.ACCIDENT_DETERMINATION,
        1,
    )

    assert is_complete_synthetic_pdf(content)
    assert len(content) > 1_000
    assert b"/Type /Page" in content
    assert b"SYNTHETIC DEMO MATERIAL" in content


def test_experience_case_contains_real_image_video_and_complete_pdfs(tmp_path):
    workspace = CaseWorkspace(tmp_path / "cases")
    case_id, scenario = seed_experience_case(workspace, "demo_c")

    sources = workspace.store(case_id).list_sources(case_id)
    pdfs = [source for source in sources if source.kind is SourceKind.PDF]

    assert len(sources) == len(scenario.roles)
    assert any(source.kind is SourceKind.IMAGE for source in sources)
    assert any(source.kind is SourceKind.VIDEO for source in sources)
    video = next(source for source in sources if source.kind is SourceKind.VIDEO)
    video_bytes = workspace.resolve_source(video).read_bytes()
    assert video.original_name.endswith(".mp4")
    assert video.media_type == "video/mp4"
    assert video_bytes[4:8] == b"ftyp"
    assert b"avc1" in video_bytes
    assert all(
        is_complete_synthetic_pdf(workspace.resolve_source(source).read_bytes())
        for source in pdfs
    )
    assert (
        len(
            [
                node
                for node in workspace.store(case_id).list_nodes(case_id)
                if node["node_type"] == "video_keyframe"
            ]
        )
        == 3
    )


def test_golden_experience_uses_august_judging_window(tmp_path):
    workspace = CaseWorkspace(tmp_path / "cases")
    case_id, _ = seed_experience_case(workspace, "demo_a")
    metadata = next(
        event["payload"]
        for event in reversed(workspace.store(case_id).list_audit_events(case_id))
        if event["event_type"] == "case_metadata_saved"
    )

    assert metadata["manual_delivery_date"] == DEMO_DELIVERY_DATE


def test_legacy_placeholder_pdf_is_repaired_with_audit_trail(tmp_path):
    workspace = CaseWorkspace(tmp_path / "cases")
    case_id, _ = seed_experience_case(workspace, "demo_b")
    source = workspace.store(case_id).list_sources(case_id)[0]
    path = workspace.resolve_source(source)
    path.write_bytes(b"%PDF-1.4\n% legacy placeholder\n%%EOF\n")

    repaired = repair_experience_case_pdfs(workspace, case_id, "demo_b")
    refreshed = workspace.store(case_id).get_source(source.source_id)

    assert repaired == 1
    assert is_complete_synthetic_pdf(workspace.resolve_source(refreshed).read_bytes())
    assert any(
        event["event_type"] == "synthetic_pdf_repaired"
        for event in workspace.store(case_id).list_audit_events(case_id)
    )


def test_legacy_scene_photo_pdf_is_upgraded_to_real_image(tmp_path):
    workspace = CaseWorkspace(tmp_path / "cases")
    case_id = workspace.create_case("CASE-LEGACY-MULTIMODAL")
    content = synthetic_pdf_bytes("demo_b", SourceRole.SCENE_PHOTO, 2)
    with tempfile.NamedTemporaryFile(suffix=".pdf") as fixture:
        fixture.write(content)
        fixture.flush()
        source = workspace.ingest_file(
            case_id,
            fixture.name,
            role=SourceRole.SCENE_PHOTO,
            original_name="02-scene_photo-synthetic.pdf",
        )
    workspace.store(case_id).add_node(
        EvidenceNode(
            node_id=f"NODE-{case_id}-02",
            case_id=case_id,
            source_id=source.source_id,
            node_type="document_text",
            locator={"page": 1, "synthetic": True},
        )
    )

    upgraded = upgrade_experience_case_media(workspace, case_id, "demo_b")
    refreshed = workspace.store(case_id).get_source(source.source_id)

    assert upgraded == 1
    assert refreshed.kind is SourceKind.IMAGE
    assert refreshed.original_name.endswith("-synthetic.jpg")
    assert workspace.resolve_source(refreshed).read_bytes().startswith(b"\xff\xd8\xff")
    assert (
        workspace.store(case_id).list_nodes(case_id, source.source_id)[0]["node_type"]
        == "image"
    )


def test_legacy_synthetic_avi_is_upgraded_to_mp4(tmp_path):
    workspace = CaseWorkspace(tmp_path / "cases")
    case_id, _ = seed_experience_case(workspace, "demo_c")
    source = next(
        item
        for item in workspace.store(case_id).list_sources(case_id)
        if item.role is SourceRole.DASHCAM_VIDEO
    )
    store = workspace.store(case_id)
    with store.transaction() as db:
        db.execute(
            "UPDATE source_files SET original_name = ? WHERE source_id = ?",
            ("02-dashcam_video-synthetic.avi", source.source_id),
        )

    upgraded = upgrade_experience_case_media(workspace, case_id, "demo_c")
    refreshed = store.get_source(source.source_id)

    assert upgraded == 1
    assert refreshed.original_name.endswith(".mp4")
    assert refreshed.media_type == "video/mp4"
    refreshed_bytes = workspace.resolve_source(refreshed).read_bytes()
    assert refreshed_bytes[4:8] == b"ftyp"
    assert b"avc1" in refreshed_bytes
