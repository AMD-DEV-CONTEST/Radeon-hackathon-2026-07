"""Guardrails separating technical non-compliance from legal vehicle nature."""

from __future__ import annotations

from typing import Any

from app.rules.repository import RuleRepository
from app.schemas.business import (
    FactorStatus,
    TechnicalComparisonStatus,
    VehicleNatureClassification,
    VehicleNatureResult,
)


class VehicleRuleGuardrailError(ValueError):
    pass


class VehicleNatureRuleGuard:
    def __init__(self, rules: RuleRepository | None = None):
        self.rules = rules or RuleRepository()

    def assess(self, result: VehicleNatureResult) -> dict[str, Any]:
        technical = {
            status.value: sum(
                item.status is status
                for item in result.parameter_comparison
            )
            for status in TechnicalComparisonStatus
        }
        registration_supports_motor = any(
            item.status is FactorStatus.SUPPORTS_MOTOR
            for item in result.registration_and_management_factors
        )
        appraisal_supports_motor = any(
            item.status is FactorStatus.SUPPORTS_MOTOR
            for item in result.appraisal_factors
        )
        if (
            result.classification is VehicleNatureClassification.MOTOR_VEHICLE
            and not (registration_supports_motor or appraisal_supports_motor)
        ):
            raise VehicleRuleGuardrailError(
                "Technical non-compliance alone cannot produce motor_vehicle."
            )
        if (
            technical[TechnicalComparisonStatus.NON_COMPLIANT.value] > 0
            and not (registration_supports_motor or appraisal_supports_motor)
            and result.classification is VehicleNatureClassification.MOTOR_VEHICLE
        ):
            raise VehicleRuleGuardrailError("Forbidden rule: non-compliant = motor.")
        return {
            "rule_id": "RULE-CN-VEHICLE-NATURE-GUARDRAIL-2024",
            "technical_standard_conformity": technical,
            "registration_management_factors": [
                item.model_dump(mode="json")
                for item in result.registration_and_management_factors
            ],
            "appraisal_factors": [
                item.model_dump(mode="json") for item in result.appraisal_factors
            ],
            "modification_factors": [
                item.model_dump(mode="json")
                for item in result.registration_and_management_factors
                if "改装" in item.factor or "限速" in item.factor
            ],
            "legal_classification": result.classification.value,
            "warning": (
                "技术标准符合性与法律属性认定已分离；缺少登记、号牌、鉴定"
                "或属地管理证据时必须保留疑似机动车/证据不足状态。"
            ),
        }
