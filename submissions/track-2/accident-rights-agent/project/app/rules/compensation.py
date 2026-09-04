"""Traceable compensation-regime routing without unsupported amount estimates."""

from __future__ import annotations

from datetime import date
from typing import Any

from app.rules.repository import RuleRepository
from app.schemas.business import (
    CompensationRegime,
    LiabilityResult,
    VehicleNatureClassification,
    VehicleNatureResult,
)
from app.schemas.legal import LegalCitation
from app.schemas.rules import (
    CompensationRouteResult,
    InsuranceLayer,
    InsuranceLayerStatus,
)

REQUIRED_PAYMENT_INPUTS = {
    "policy_limits",
    "coverage_terms",
    "loss_amounts",
    "exclusions",
    "prior_payments",
}


class CompensationRegimeRouter:
    def __init__(self, rules: RuleRepository | None = None):
        self.rules = rules or RuleRepository()

    def route(
        self,
        *,
        vehicle_nature: VehicleNatureResult,
        liability: LiabilityResult,
        accident_parties: list[str] | None = None,
        policy_and_loss_data: dict[str, Any] | None = None,
        as_of_date: date,
        jurisdiction: str = "CN",
        legal_citations: list[LegalCitation] | None = None,
    ) -> CompensationRouteResult:
        regime_rule = self.rules.get(
            "RULE-CN-COMPENSATION-REGIME-2021",
            as_of_date=as_of_date,
            jurisdiction=jurisdiction,
        )
        insurance_rule = self.rules.get(
            "RULE-CN-INSURANCE-LAYER-2020",
            as_of_date=as_of_date,
            jurisdiction=jurisdiction,
        )
        classification = vehicle_nature.classification
        if classification is VehicleNatureClassification.MOTOR_VEHICLE:
            regime = CompensationRegime.MOTOR_VS_MOTOR
        elif classification is VehicleNatureClassification.NON_MOTOR_VEHICLE:
            regime = CompensationRegime.MOTOR_VS_NON_MOTOR_OR_PEDESTRIAN
        elif classification is VehicleNatureClassification.SUSPECTED_MOTOR_VEHICLE:
            regime = CompensationRegime.PENDING_VEHICLE_CLASSIFICATION
        else:
            regime = CompensationRegime.INSUFFICIENT_EVIDENCE

        uncertainty: list[str] = []
        if liability.compensation_regime is not regime:
            if regime in {
                CompensationRegime.PENDING_VEHICLE_CLASSIFICATION,
                CompensationRegime.INSUFFICIENT_EVIDENCE,
            }:
                uncertainty.append(
                    "车辆属性尚未确定，赔偿路径保持待定；未沿用更确定的旧路径。"
                )
            else:
                uncertainty.append(
                    "业务Agent赔偿路径与车辆属性路由不一致，需Verifier阻断。"
                )
        available = set((policy_and_loss_data or {}).keys())
        missing = sorted(REQUIRED_PAYMENT_INPUTS - available)
        payment = liability.insurance_payment_estimate.model_dump(mode="json")
        if missing:
            payment = {
                "status": "insufficient_data",
                "currency": "CNY",
                "estimated_amount": None,
                "required_inputs": missing,
                "explanation": "保单、限额、条款、损失、免责或既付金额不完整，禁止估算。",
            }
        citations = [
            item
            for item in (legal_citations or [])
            if item.document_id
            in {
                regime_rule.source_law_id,
                insurance_rule.source_law_id,
                "CN-REG-CALI-2019",
            }
        ]
        layer_status = (
            InsuranceLayerStatus.INSUFFICIENT_DATA
            if missing
            else InsuranceLayerStatus.APPLICABLE
        )
        pending_route = regime in {
            CompensationRegime.PENDING_VEHICLE_CLASSIFICATION,
            CompensationRegime.INSUFFICIENT_EVIDENCE,
        }
        if pending_route:
            layer_status = InsuranceLayerStatus.PENDING
        common = {
            "estimated_amount": None,
            "required_inputs": missing,
            "rule_ids": [insurance_rule.rule_id],
            "law_ids": [insurance_rule.source_law_id],
            "assumptions": [
                "保险责任仍受保单、责任限额、免责条款、损失项目和既付金额约束。"
            ],
        }
        compulsory = InsuranceLayer(status=layer_status, order=1, **common)
        commercial = InsuranceLayer(status=layer_status, order=2, **common)
        uncovered = InsuranceLayer(status=layer_status, order=3, **common)
        allocation = liability.civil_compensation_allocation.model_dump(mode="json")
        if pending_route:
            allocation = {
                **allocation,
                "status": "insufficient_evidence",
                "regime": regime.value,
                "share_ranges": [],
                "explanation": "车辆法律属性未确定，民事赔偿路径保持待定。",
            }
        return CompensationRouteResult(
            regime=regime,
            accident_responsibility=liability.accident_responsibility.model_dump(
                mode="json"
            ),
            civil_compensation_allocation=allocation,
            compulsory_insurance_layer=compulsory,
            commercial_insurance_layer=commercial,
            uninsured_or_uncovered_loss=uncovered,
            insurance_payment_estimate=payment,
            rule_ids=[regime_rule.rule_id, insurance_rule.rule_id],
            law_ids=[regime_rule.source_law_id, insurance_rule.source_law_id],
            legal_citations=citations,
            assumptions=[
                "事故责任、民事赔偿责任和保险赔付是三个不同对象。",
                "缺少完整保单与损失数据时不输出具体保险赔付金额。",
                f"事故双方类型输入：{accident_parties or ['motor_vehicle', 'two_wheeler']}",
            ],
            uncertainty=uncertainty,
        )
