from __future__ import annotations

from datetime import date, datetime

from app.schemas.evidence import SourceRole
from app.services.case_service import CaseService


def test_upload_video_image_pdf_and_create_case(tmp_path, golden_ui_runtime):
    service = CaseService(tmp_path / "cases")
    golden = golden_ui_runtime.cases.export_case(golden_ui_runtime.case_id)
    source_by_kind = {}
    for source in golden["sources"]:
        kind = getattr(source["kind"], "value", source["kind"])
        source_by_kind.setdefault(kind, source)
    paths = []
    for kind in ("pdf", "image", "video"):
        record = golden_ui_runtime.cases.workspace.store(
            golden_ui_runtime.case_id
        ).get_source(source_by_kind[kind]["source_id"])
        paths.append(
            golden_ui_runtime.cases.workspace.resolve_source(record)
        )

    summary = service.create_case(
        accident_time=datetime.fromisoformat("2026-07-20T08:30:00+08:00"),
        location="合成测试路口",
        jurisdiction="CN",
        manual_delivery_date=date(2026, 7, 28),
        files=paths,
        default_role=SourceRole.OTHER,
    )

    sources = service.sources(summary.metadata.case_id)
    assert {item.kind for item in sources} == {"pdf", "image", "video"}
    assert all(len(item.sha256) == 64 for item in sources)
    assert all(item.source_id.startswith("SRC-") for item in sources)
    assert summary.metadata.manual_delivery_date == date(2026, 7, 28)


def test_manual_role_correction_is_audited(tmp_path, golden_ui_runtime):
    service = CaseService(tmp_path / "cases")
    source = golden_ui_runtime.cases.sources(golden_ui_runtime.case_id)[0]
    original = golden_ui_runtime.cases.workspace.resolve_source(
        golden_ui_runtime.cases.workspace.store(
            golden_ui_runtime.case_id
        ).get_source(source.source_id)
    )
    summary = service.create_case(files=[original])
    created = service.sources(summary.metadata.case_id)[0]
    corrected = service.update_source_role(
        summary.metadata.case_id,
        created.source_id,
        SourceRole.ACCIDENT_DETERMINATION,
    )
    assert corrected.role == SourceRole.ACCIDENT_DETERMINATION.value
    events = service.export_case(summary.metadata.case_id)["audit_events"]
    assert any(item["event_type"] == "source_role_updated" for item in events)
