from __future__ import annotations

from app.agents.intake import assess_business_intake
from app.evidence.workspace import CaseWorkspace
from app.schemas.business import MaterialCategory


def test_business_intake_lists_uploaded_missing_and_blocking(demo_case_b):
    workspace, case_id = demo_case_b
    exported = workspace.store(case_id).export_case(case_id)
    result = assess_business_intake(
        workspace.store(case_id).list_sources(case_id),
        exported["facts"],
        evidence_nodes=exported["evidence_nodes"],
        conflicts=exported["conflicts"],
    )

    uploaded = {item.category for item in result.uploaded_materials}
    assert MaterialCategory.ACCIDENT_DETERMINATION in uploaded
    assert MaterialCategory.SCENE_PHOTOS in uploaded
    assert MaterialCategory.VEHICLE_TECHNICAL_PARAMETERS in uploaded
    assert any(
        item.category is MaterialCategory.VEHICLE_REGISTRATION_PLATE
        for item in result.missing_required_materials
    )
    assert any(
        item.code == "NO_CORE_VEHICLE_NATURE_EVIDENCE"
        for item in result.blocking_issues
    )
    assert all(
        item.reason
        and item.required_for
        and item.collection_method
        and item.related_agent
        for item in result.next_collection_actions
    )
    assert result.can_continue_analysis is True
    assert result.route_hint == "evidence_ready"


def test_business_intake_routes_empty_case_to_missing_evidence(tmp_path):
    workspace = CaseWorkspace(tmp_path / "empty")
    workspace.create_case("CASE-EMPTY")
    result = assess_business_intake([], [], evidence_nodes=[], conflicts=[])

    assert result.can_continue_analysis is False
    assert result.route_hint == "missing_evidence"
    assert any(
        item.code == "NO_RECONSTRUCTED_EVIDENCE" for item in result.blocking_issues
    )
