"""Vehicle legal-nature agent built on evidence, rules, and legal citations."""

from __future__ import annotations

from datetime import date
from typing import Any

from app.agents.model_adapter import (
    AgentModelAdapter,
    DeterministicAgentModelAdapter,
)
from app.schemas.business import (
    EvidenceGap,
    EvidenceReference,
    FactorStatus,
    MaterialCategory,
    Priority,
    TechnicalComparisonStatus,
    VehicleFactor,
    VehicleNatureClassification,
    VehicleNatureHypothesis,
    VehicleNatureResult,
)
from app.schemas.legal import LegalCitation
from app.tools.vehicle_rules import VehicleParameterRuleEngine

VEHICLE_LEGAL_DOCUMENTS = {
    "CN-LAW-RTSA-2021",
    "CN-GB-17761-2024",
    "CN-GA-802-2019",
    "CN-GB-7258-2017",
    "CN-CASE-E-BIKE-ATTR-2023",
}


class VehicleNatureAgent:
    def __init__(
        self,
        *,
        rule_engine: VehicleParameterRuleEngine | None = None,
        model_adapter: AgentModelAdapter | None = None,
    ):
        self.rule_engine = rule_engine or VehicleParameterRuleEngine()
        self.model_adapter = model_adapter or DeterministicAgentModelAdapter()

    def run(
        self,
        *,
        facts: list[dict[str, Any]],
        legal_citations: list[LegalCitation],
        conflicts: list[dict[str, Any]] | None = None,
        accident_date: date | None = None,
    ) -> VehicleNatureResult:
        conflicts = conflicts or []
        disputed_ids = {
            str(fact_id)
            for conflict in conflicts
            for fact_id in conflict.get("fact_ids", [])
        }
        parameter_comparison = self.rule_engine.compare(
            facts,
            accident_date=accident_date,
            disputed_fact_ids=disputed_ids,
        )
        registration = self._registration_factors(facts, disputed_ids)
        appraisals = self._appraisal_factors(facts, disputed_ids)
        legal_basis = [
            item
            for item in legal_citations
            if item.document_id in VEHICLE_LEGAL_DOCUMENTS
        ]

        motor_fact_ids = _factor_fact_ids(
            [*registration, *appraisals], FactorStatus.SUPPORTS_MOTOR
        )
        non_motor_fact_ids = _factor_fact_ids(
            [*registration, *appraisals], FactorStatus.SUPPORTS_NON_MOTOR
        )
        disputed_factor_ids = _factor_fact_ids(
            [*registration, *appraisals], FactorStatus.DISPUTED
        )
        non_compliant = [
            item
            for item in parameter_comparison
            if item.status is TechnicalComparisonStatus.NON_COMPLIANT
        ]
        conflicting_parameters = [
            item
            for item in parameter_comparison
            if item.status is TechnicalComparisonStatus.CONFLICTING
        ]
        technical_fact_ids = {
            fact_id for item in non_compliant for fact_id in item.fact_ids
        }
        has_core_evidence = bool(motor_fact_ids or non_motor_fact_ids)
        material_conflict = bool(
            disputed_factor_ids
            or conflicting_parameters
            or (motor_fact_ids and non_motor_fact_ids)
        )

        if motor_fact_ids and not non_motor_fact_ids and not material_conflict:
            classification = VehicleNatureClassification.MOTOR_VEHICLE
            confidence = (
                0.90
                if any(
                    item.factor == "vehicle_nature_appraisal"
                    and item.status is FactorStatus.SUPPORTS_MOTOR
                    for item in appraisals
                )
                else 0.84
            )
            conclusion_status = "qualified"
        elif (
            non_motor_fact_ids
            and not motor_fact_ids
            and not non_compliant
            and not material_conflict
        ):
            classification = VehicleNatureClassification.NON_MOTOR_VEHICLE
            confidence = 0.82
            conclusion_status = "qualified"
        elif non_compliant or material_conflict:
            classification = VehicleNatureClassification.SUSPECTED_MOTOR_VEHICLE
            confidence = 0.52 if material_conflict else 0.66
            conclusion_status = "disputed" if material_conflict else "qualified"
        else:
            classification = VehicleNatureClassification.INSUFFICIENT_EVIDENCE
            confidence = 0.28 if not has_core_evidence else 0.40
            conclusion_status = "blocked"

        if (
            classification
            in {
                VehicleNatureClassification.MOTOR_VEHICLE,
                VehicleNatureClassification.NON_MOTOR_VEHICLE,
            }
            and not legal_basis
        ):
            classification = (
                VehicleNatureClassification.SUSPECTED_MOTOR_VEHICLE
                if technical_fact_ids or motor_fact_ids
                else VehicleNatureClassification.INSUFFICIENT_EVIDENCE
            )
            confidence = min(confidence, 0.45)
            conclusion_status = "blocked"

        missing = self._missing_evidence(
            registration=registration,
            appraisals=appraisals,
            parameter_comparison=parameter_comparison,
            has_legal_basis=bool(legal_basis),
        )
        supporting_ids: set[str]
        contradicting_ids: set[str]
        if classification is VehicleNatureClassification.MOTOR_VEHICLE:
            supporting_ids = set(motor_fact_ids)
            contradicting_ids = set(non_motor_fact_ids)
        elif classification is VehicleNatureClassification.NON_MOTOR_VEHICLE:
            supporting_ids = set(non_motor_fact_ids)
            contradicting_ids = set(motor_fact_ids) | technical_fact_ids
        elif classification is VehicleNatureClassification.SUSPECTED_MOTOR_VEHICLE:
            supporting_ids = technical_fact_ids | set(motor_fact_ids)
            contradicting_ids = set(non_motor_fact_ids)
        else:
            supporting_ids = set()
            contradicting_ids = set(disputed_factor_ids)
        supporting = _references(facts, supporting_ids)
        contradicting = _references(facts, contradicting_ids)
        alternatives = self._hypotheses(
            classification=classification,
            supporting_ids=sorted(supporting_ids),
            contradicting_ids=sorted(contradicting_ids),
            missing=[str(item.category) for item in missing],
        )
        summary = {
            "classification": classification.value,
            "technical_non_compliant": [item.parameter for item in non_compliant],
            "management_motor_fact_ids": sorted(motor_fact_ids),
            "management_non_motor_fact_ids": sorted(non_motor_fact_ids),
            "disputed_fact_ids": sorted(disputed_factor_ids),
            "ruleset_id": self.rule_engine.ruleset_id,
        }
        explanation = self.model_adapter.explain("vehicle_nature", {"summary": summary})
        return VehicleNatureResult(
            classification=classification,
            confidence=round(confidence, 4),
            conclusion_status=conclusion_status,
            supporting_facts=supporting,
            contradicting_facts=contradicting,
            missing_evidence=missing,
            parameter_comparison=parameter_comparison,
            registration_and_management_factors=registration,
            appraisal_factors=appraisals,
            legal_basis=legal_basis,
            alternative_hypotheses=alternatives,
            warning=(
                "技术参数比较只说明特定标准的符合性，不直接替代车辆法律属性判断；"
                "登记管理、产品属性、鉴定意见、改装证据、事故日期和属地规则需综合审查。"
            ),
            explanation=explanation,
        )

    @staticmethod
    def _registration_factors(
        facts: list[dict[str, Any]], disputed_ids: set[str]
    ) -> list[VehicleFactor]:
        matching = [
            item
            for item in facts
            if any(
                keyword in _fact_text(item)
                for keyword in ("登记类型", "号牌类型", "车辆登记", "行驶证")
            )
        ]
        if not matching:
            return [
                VehicleFactor(
                    factor="registration_and_plate",
                    status=FactorStatus.UNKNOWN,
                    explanation="未发现可引用的登记或号牌事实。",
                )
            ]
        result: list[VehicleFactor] = []
        for fact in matching:
            text = _fact_text(fact)
            fact_id = str(fact["fact_id"])
            if fact_id in disputed_ids:
                status = FactorStatus.DISPUTED
            elif "非机动车" in text or "电动自行车" in text:
                status = FactorStatus.SUPPORTS_NON_MOTOR
            elif "机动车" in text or "摩托车" in text:
                status = FactorStatus.SUPPORTS_MOTOR
            else:
                status = FactorStatus.NEUTRAL
            result.append(
                VehicleFactor(
                    factor="registration_and_plate",
                    status=status,
                    explanation=fact.get("statement") or text,
                    fact_ids=[fact_id],
                    evidence_ids=list(fact.get("source_node_ids", [])),
                )
            )
        return result

    @staticmethod
    def _appraisal_factors(
        facts: list[dict[str, Any]], disputed_ids: set[str]
    ) -> list[VehicleFactor]:
        matching = [
            item
            for item in facts
            if any(
                keyword in _fact_text(item)
                for keyword in (
                    "车辆属性鉴定",
                    "鉴定意见",
                    "鉴定为机动车",
                    "鉴定为非机动车",
                )
            )
        ]
        if not matching:
            return [
                VehicleFactor(
                    factor="vehicle_nature_appraisal",
                    status=FactorStatus.UNKNOWN,
                    explanation="未发现车辆属性鉴定意见。",
                )
            ]
        result: list[VehicleFactor] = []
        for fact in matching:
            text = _fact_text(fact)
            fact_id = str(fact["fact_id"])
            if fact_id in disputed_ids:
                status = FactorStatus.DISPUTED
            elif "非机动车" in text:
                status = FactorStatus.SUPPORTS_NON_MOTOR
            elif "机动车" in text:
                status = FactorStatus.SUPPORTS_MOTOR
            else:
                status = FactorStatus.NEUTRAL
            result.append(
                VehicleFactor(
                    factor="vehicle_nature_appraisal",
                    status=status,
                    explanation=fact.get("statement") or text,
                    fact_ids=[fact_id],
                    evidence_ids=list(fact.get("source_node_ids", [])),
                )
            )
        return result

    @staticmethod
    def _missing_evidence(
        *,
        registration: list[VehicleFactor],
        appraisals: list[VehicleFactor],
        parameter_comparison: list[Any],
        has_legal_basis: bool,
    ) -> list[EvidenceGap]:
        gaps: list[EvidenceGap] = []
        if all(item.status is FactorStatus.UNKNOWN for item in registration):
            gaps.append(
                _vehicle_gap(
                    MaterialCategory.VEHICLE_REGISTRATION_PLATE,
                    "缺少号牌、登记类型或行驶证记录。",
                    ["车辆法律属性", "赔偿路径"],
                    "核验号牌、登记证或属地车辆登记查询结果",
                )
            )
        if all(item.status is FactorStatus.UNKNOWN for item in appraisals):
            gaps.append(
                _vehicle_gap(
                    MaterialCategory.VEHICLE_NATURE_APPRAISAL,
                    "缺少完整车辆属性鉴定及其依据。",
                    ["确定性机动车结论", "赔偿路径"],
                    "取得鉴定意见、委托事项、检材和鉴定标准",
                )
            )
        unknown_parameters = [
            item.display_name
            for item in parameter_comparison
            if item.status
            in {
                TechnicalComparisonStatus.UNKNOWN,
                TechnicalComparisonStatus.CONFLICTING,
            }
        ]
        if unknown_parameters:
            gaps.append(
                _vehicle_gap(
                    MaterialCategory.VEHICLE_TECHNICAL_PARAMETERS,
                    f"以下参数未知或冲突：{'、'.join(unknown_parameters)}。",
                    ["技术标准符合性"],
                    "补充合格证、铭牌或检测报告并核验实车改装",
                    priority=Priority.P1,
                )
            )
        if not has_legal_basis:
            gaps.append(
                _vehicle_gap(
                    "legal_citation",
                    "缺少可验证且在事故日期有效的车辆属性法律引用。",
                    ["确定性法律属性结论"],
                    "重新执行本地法律检索并核验版本、地域和有效期",
                )
            )
        return gaps

    @staticmethod
    def _hypotheses(
        *,
        classification: VehicleNatureClassification,
        supporting_ids: list[str],
        contradicting_ids: list[str],
        missing: list[str],
    ) -> list[VehicleNatureHypothesis]:
        if classification is VehicleNatureClassification.MOTOR_VEHICLE:
            pairs = [
                (VehicleNatureClassification.MOTOR_VEHICLE, 0.75),
                (VehicleNatureClassification.SUSPECTED_MOTOR_VEHICLE, 0.25),
            ]
        elif classification is VehicleNatureClassification.NON_MOTOR_VEHICLE:
            pairs = [
                (VehicleNatureClassification.NON_MOTOR_VEHICLE, 0.72),
                (VehicleNatureClassification.SUSPECTED_MOTOR_VEHICLE, 0.28),
            ]
        elif classification is VehicleNatureClassification.SUSPECTED_MOTOR_VEHICLE:
            pairs = [
                (VehicleNatureClassification.NON_MOTOR_VEHICLE, 0.45),
                (VehicleNatureClassification.MOTOR_VEHICLE, 0.55),
            ]
        else:
            pairs = [
                (VehicleNatureClassification.NON_MOTOR_VEHICLE, 0.50),
                (VehicleNatureClassification.SUSPECTED_MOTOR_VEHICLE, 0.50),
            ]
        result = []
        for index, (item, probability) in enumerate(pairs, start=1):
            regime = (
                "motor_vs_motor"
                if item is VehicleNatureClassification.MOTOR_VEHICLE
                else (
                    "motor_vs_non_motor_or_pedestrian"
                    if item is VehicleNatureClassification.NON_MOTOR_VEHICLE
                    else "pending_vehicle_classification"
                )
            )
            result.append(
                VehicleNatureHypothesis(
                    hypothesis_id=f"VH-{index}",
                    classification=item,
                    probability=probability,
                    supporting_fact_ids=supporting_ids,
                    contradicting_fact_ids=contradicting_ids,
                    missing_evidence=missing,
                    compensation_regime_impact=regime,
                    explanation=(
                        "该假设用于比较证据变化对赔偿路径的影响，"
                        "不是司法或行政机关的最终定性。"
                    ),
                )
            )
        return result


def _factor_fact_ids(factors: list[VehicleFactor], status: FactorStatus) -> set[str]:
    return {
        fact_id
        for item in factors
        if item.status is status
        for fact_id in item.fact_ids
    }


def _fact_text(fact: dict[str, Any]) -> str:
    return " ".join(
        str(fact.get(key, "")) for key in ("statement", "subject", "predicate", "value")
    )


def _references(
    facts: list[dict[str, Any]], fact_ids: set[str]
) -> list[EvidenceReference]:
    result = []
    for fact in facts:
        if fact.get("fact_id") not in fact_ids or not fact.get("source_node_ids"):
            continue
        status = {
            "verified": "confirmed",
            "confirmed": "confirmed",
            "disputed": "disputed",
            "rejected": "rejected",
        }.get(str(fact.get("status")), "unverified")
        result.append(
            EvidenceReference(
                fact_id=str(fact["fact_id"]),
                statement=str(fact.get("statement", "")),
                evidence_ids=list(fact["source_node_ids"]),
                status=status,
                confidence=float(fact.get("confidence", 0.0)),
            )
        )
    return result


def _vehicle_gap(
    category: MaterialCategory | str,
    reason: str,
    required_for: list[str],
    method: str,
    *,
    priority: Priority = Priority.P0,
) -> EvidenceGap:
    return EvidenceGap(
        category=category,
        reason=reason,
        required_for=required_for,
        priority=priority,
        collection_method=method,
        related_agent="vehicle_nature",
        blocks_conclusions=required_for if priority is Priority.P0 else [],
    )
