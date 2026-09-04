from __future__ import annotations

import pytest

from app.agents.vehicle_nature import VehicleNatureAgent
from app.rules.vehicle import VehicleNatureRuleGuard, VehicleRuleGuardrailError
from app.schemas.business import VehicleNatureClassification
from app.schemas.legal import LegalCitation


def test_technical_noncompliance_does_not_auto_classify_motor(legal_retriever):
    citations = [
        LegalCitation.from_chunk(chunk, 1.0)
        for chunk in legal_retriever.corpus.list_chunks()
    ]
    result = VehicleNatureAgent().run(
        facts=[
            {
                "fact_id": "FACT-GUARD-001",
                "statement": "两轮车辆最高设计车速为45 km/h",
                "subject": "两轮车辆",
                "predicate": "最高设计车速",
                "value": "45 km/h",
                "source_node_ids": ["NODE-GUARD-001"],
                "confidence": 0.95,
                "status": "verified",
            }
        ],
        legal_citations=citations,
        conflicts=[],
    )
    assessment = VehicleNatureRuleGuard().assess(result)
    assert result.classification is VehicleNatureClassification.SUSPECTED_MOTOR_VEHICLE
    assert assessment["technical_standard_conformity"]["non_compliant"] >= 1
    with pytest.raises(VehicleRuleGuardrailError):
        VehicleNatureRuleGuard().assess(
            result.model_copy(
                update={
                    "classification": VehicleNatureClassification.MOTOR_VEHICLE
                }
            )
        )
