from __future__ import annotations

from datetime import date

from app.agents.liability import LiabilityAgent
from app.agents.vehicle_nature import VehicleNatureAgent
from app.rules.compensation import CompensationRegimeRouter
from app.schemas.legal import LegalCitation


def test_pending_vehicle_nature_keeps_compensation_pending_and_amount_unknown(
    legal_retriever,
):
    citations = [
        LegalCitation.from_chunk(chunk, 1.0)
        for chunk in legal_retriever.corpus.list_chunks()
    ]
    facts = [
        {
            "fact_id": "FACT-ROUTE-001",
            "statement": "两轮车辆最高设计车速为45 km/h",
            "subject": "两轮车辆",
            "predicate": "最高设计车速",
            "value": "45 km/h",
            "source_node_ids": ["NODE-ROUTE-001"],
            "confidence": 0.95,
            "status": "verified",
        }
    ]
    vehicle = VehicleNatureAgent().run(
        facts=facts,
        legal_citations=citations,
        conflicts=[],
    )
    liability = LiabilityAgent().run(
        facts=facts,
        legal_citations=citations,
        vehicle_nature=vehicle,
        conflicts=[],
    )
    result = CompensationRegimeRouter().route(
        vehicle_nature=vehicle,
        liability=liability,
        policy_and_loss_data={},
        as_of_date=date(2026, 7, 20),
        legal_citations=citations,
    )
    assert result.regime.value == "pending_vehicle_classification"
    assert result.insurance_payment_estimate["status"] == "insufficient_data"
    assert result.insurance_payment_estimate["estimated_amount"] is None
    assert result.compulsory_insurance_layer.status.value == "pending"
    assert result.accident_responsibility != result.insurance_payment_estimate
