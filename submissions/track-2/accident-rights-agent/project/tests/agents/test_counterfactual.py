from __future__ import annotations

from app.agents.liability import LiabilityAgent
from app.agents.vehicle_nature import VehicleNatureAgent
from app.schemas.legal import LegalCitation


def test_counterfactuals_cover_five_key_evidence_types_without_fabrication(
    legal_retriever,
):
    citations = [
        LegalCitation.from_chunk(chunk, 1.0)
        for chunk in legal_retriever.corpus.list_chunks()
    ]
    vehicle = VehicleNatureAgent().run(
        facts=[],
        legal_citations=citations,
        conflicts=[],
    )
    result = LiabilityAgent().run(
        facts=[],
        legal_citations=citations,
        vehicle_nature=vehicle,
        conflicts=[],
    )
    by_type = {item.evidence_type: item for item in result.counterfactual_analysis}
    assert set(by_type) == {
        "intersection_surveillance",
        "original_dashcam",
        "vehicle_nature_appraisal",
        "signal_phase",
        "collision_point_and_brake_marks",
    }
    assert all(item.current_status == "missing" for item in by_type.values())
    assert all(len(item.branches) >= 2 for item in by_type.values())
    assert all(
        branch.condition.startswith("若")
        for item in by_type.values()
        for branch in item.branches
    )
