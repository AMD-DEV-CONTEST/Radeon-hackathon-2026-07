"""Evidence-constrained liability, causation, and counterfactual analysis."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from app.agents.model_adapter import (
    AgentModelAdapter,
    DeterministicAgentModelAdapter,
)
from app.schemas.business import (
    AccidentResponsibility,
    CausalRole,
    CausationFinding,
    CivilCompensationAllocation,
    CompensationRegime,
    CounterfactualBranch,
    CounterfactualFinding,
    EvidenceGap,
    EvidenceReference,
    InsurancePaymentEstimate,
    LiabilityHypothesis,
    LiabilityResult,
    MaterialCategory,
    Party,
    Priority,
    ResponsibilityLevel,
    ShareRange,
    UncertaintyAssessment,
    VehicleNatureClassification,
    VehicleNatureResult,
    ViolationFinding,
    ViolationStatus,
)
from app.schemas.legal import LegalCitation


@dataclass(frozen=True)
class BehaviorRule:
    category: str
    display_name: str
    fact_keywords: tuple[str, ...]
    violation_markers: tuple[str, ...]
    compliance_markers: tuple[str, ...]
    excluded_markers: tuple[str, ...]
    motor_law_refs: tuple[tuple[str, str], ...]
    two_wheeler_law_refs: tuple[tuple[str, str], ...]
    causal_role: CausalRole
    base_strength: float


BEHAVIOR_RULES = (
    BehaviorRule(
        "travel_direction",
        "通行方向",
        ("行驶方向", "驶入方向", "由支路进入", "由主路进入"),
        ("违反通行方向", "错误方向"),
        ("按通行方向",),
        (),
        (),
        (),
        CausalRole.CONDITIONAL,
        0.35,
    ),
    BehaviorRule(
        "lane_usage",
        "车道使用",
        ("机动车道", "非机动车道", "占道", "车道"),
        ("违法占道", "占用对向车道", "驶入对向车道"),
        ("在本车道", "按车道行驶"),
        (),
        (),
        (),
        CausalRole.SECONDARY,
        0.45,
    ),
    BehaviorRule(
        "traffic_control",
        "信号灯/标志",
        ("闯红灯", "信号灯", "交通标志", "标线", "停止信号"),
        ("闯红灯", "违反停止信号", "违反信号", "未按信号"),
        ("遵守信号", "绿灯通行"),
        (),
        (),
        (("CN-REG-RTSA-IMPLEMENTATION-2017", "第六十八条"),),
        CausalRole.TRIGGERING,
        0.85,
    ),
    BehaviorRule(
        "right_of_way",
        "让行义务",
        ("未让行", "让行", "优先通行", "转弯", "直行", "右方来车"),
        ("未让行", "未让", "未停车瞭望"),
        ("已让行", "停车瞭望"),
        (),
        (("CN-REG-RTSA-IMPLEMENTATION-2017", "第五十二条"),),
        (
            ("CN-REG-RTSA-IMPLEMENTATION-2017", "第六十八条"),
            ("CN-REG-RTSA-IMPLEMENTATION-2017", "第六十九条"),
        ),
        CausalRole.PRIMARY,
        0.75,
    ),
    BehaviorRule(
        "speed",
        "速度",
        ("超速", "车速", "速度", "时速"),
        ("超速", "超过限速", "速度过快"),
        ("未超速", "速度正常"),
        ("设计车速", "额定"),
        (),
        (),
        CausalRole.PRIMARY,
        0.65,
    ),
    BehaviorRule(
        "observation",
        "观察注意",
        ("未充分观察", "疏于观察", "未注意", "瞭望", "观察"),
        ("未充分观察", "疏于观察", "未注意", "未瞭望"),
        ("充分观察", "已观察", "停车瞭望"),
        (),
        (("CN-REG-RTSA-IMPLEMENTATION-2017", "第五十二条"),),
        (("CN-REG-RTSA-IMPLEMENTATION-2017", "第六十九条"),),
        CausalRole.SECONDARY,
        0.55,
    ),
    BehaviorRule(
        "braking_avoidance",
        "制动避让",
        ("未制动", "制动", "刹车", "避让", "转向避让"),
        ("未制动", "未刹车", "未避让", "未采取制动", "未采取避让"),
        ("已制动", "采取制动", "及时制动", "已避让"),
        (),
        (),
        (),
        CausalRole.SECONDARY,
        0.55,
    ),
    BehaviorRule(
        "wrong_way",
        "逆行",
        ("逆行", "反向行驶"),
        ("逆行", "反向行驶"),
        ("顺向行驶",),
        (),
        (),
        (),
        CausalRole.TRIGGERING,
        0.80,
    ),
    BehaviorRule(
        "crossing",
        "横穿",
        ("横穿", "突然驶入", "穿越道路"),
        ("横穿", "突然驶入", "穿越道路"),
        (),
        (),
        (),
        (),
        CausalRole.TRIGGERING,
        0.78,
    ),
    BehaviorRule(
        "illegal_passenger",
        "违法载人",
        ("违法载人", "搭载", "乘坐人数", "载人"),
        ("违法载人", "超员"),
        ("未载人", "核载范围内"),
        (),
        (),
        (),
        CausalRole.CONDITIONAL,
        0.20,
    ),
    BehaviorRule(
        "night_lighting",
        "夜间照明",
        ("夜间", "未开灯", "照明", "车灯"),
        ("夜间未开灯", "未开灯", "灯光不合格"),
        ("已开灯", "照明正常"),
        (),
        (),
        (),
        CausalRole.CONDITIONAL,
        0.35,
    ),
    BehaviorRule(
        "modification",
        "改装",
        ("改装", "解除限速", "剪线提速", "更换控制器", "加装电池"),
        ("改装", "解除限速", "剪线提速", "更换控制器", "加装电池"),
        ("未改装", "原厂状态"),
        (),
        (),
        (),
        CausalRole.CONDITIONAL,
        0.25,
    ),
)


LIABILITY_LEGAL_DOCUMENTS = {
    "CN-LAW-RTSA-2021",
    "CN-REG-RTSA-IMPLEMENTATION-2017",
    "CN-RULE-ACCIDENT-PROCEDURE-2017",
    "CN-LAW-CIVIL-CODE-2020",
    "CN-JI-TRAFFIC-DAMAGE-I-2020",
    "CN-JI-TRAFFIC-DAMAGE-II-2026",
    "CN-CASE-TRAFFIC-2024",
    "CN-REG-CALI-2019",
}


class LiabilityAgent:
    def __init__(self, *, model_adapter: AgentModelAdapter | None = None):
        self.model_adapter = model_adapter or DeterministicAgentModelAdapter()

    def run(
        self,
        *,
        facts: list[dict[str, Any]],
        legal_citations: list[LegalCitation],
        vehicle_nature: VehicleNatureResult,
        conflicts: list[dict[str, Any]] | None = None,
    ) -> LiabilityResult:
        conflicts = conflicts or []
        disputed_ids = {
            str(fact_id)
            for conflict in conflicts
            for fact_id in conflict.get("fact_ids", [])
        }
        violation_matrix = self._violation_matrix(facts, legal_citations, disputed_ids)
        causation_matrix = self._causation_matrix(violation_matrix)
        scores = self._party_scores(violation_matrix, causation_matrix)
        missing = self._critical_missing(facts, vehicle_nature.classification)
        blocked = bool(missing or disputed_ids)
        hypotheses = self._liability_hypotheses(
            scores=scores,
            findings=violation_matrix,
            missing=missing,
            blocked=blocked,
        )
        probabilities = {item.label: item.probability for item in hypotheses}
        regime = self._compensation_regime(vehicle_nature.classification, bool(facts))
        legal_basis = [
            citation
            for citation in legal_citations
            if citation.document_id in LIABILITY_LEGAL_DOCUMENTS
        ]
        selected = max(hypotheses, key=lambda item: item.probability)
        accident = AccidentResponsibility(
            status=(
                "multiple_hypotheses_only" if blocked else "qualified_distribution"
            ),
            selected_hypothesis_id=None if blocked else selected.hypothesis_id,
            levels_allowed=list(ResponsibilityLevel),
            explanation=(
                "概率表示当前证据下的可比较置信分布，不是交警、法院或保险理赔的最终结论。"
            ),
        )
        civil = self._civil_allocation(
            regime=regime,
            selected=selected,
            legal_basis=legal_basis,
        )
        insurance = self._insurance_estimate(facts)
        counterfactual = self._counterfactual_analysis(facts, hypotheses)
        key_evidence = _key_evidence(facts, violation_matrix)
        trace = {
            "method": "configurable_rule_score_softmax_v1",
            "party_scores": {
                party.value: round(score, 6) for party, score in scores.items()
            },
            "temperature": 1.25 if blocked else 0.80,
            "unique_conclusion_blocked": blocked,
            "model_adapter": self.model_adapter.name,
        }
        explanation = self.model_adapter.explain(
            "liability",
            {
                "scoring_trace": trace,
                "hypotheses": [
                    {
                        "id": item.hypothesis_id,
                        "label": item.label,
                        "probability": item.probability,
                    }
                    for item in hypotheses
                ],
            },
        )
        return LiabilityResult(
            violation_matrix=violation_matrix,
            causation_matrix=causation_matrix,
            liability_hypotheses=hypotheses,
            responsibility_probabilities=probabilities,
            accident_responsibility=accident,
            civil_compensation_allocation=civil,
            insurance_payment_estimate=insurance,
            compensation_regime=regime,
            key_evidence=key_evidence,
            missing_evidence=missing,
            counterfactual_analysis=counterfactual,
            uncertainty=UncertaintyAssessment(
                unique_conclusion_blocked=blocked,
                critical_missing_evidence=[str(item.category) for item in missing],
                disputed_fact_ids=sorted(disputed_ids),
                confidence_note=(
                    "存在关键缺证或争议事实，仅保留多假设。"
                    if blocked
                    else "证据足以形成受限定的排序，但仍需人工复核。"
                ),
            ),
            legal_basis=legal_basis,
            explanation=explanation,
            scoring_trace=trace,
        )

    @staticmethod
    def _violation_matrix(
        facts: list[dict[str, Any]],
        citations: list[LegalCitation],
        disputed_ids: set[str],
    ) -> list[ViolationFinding]:
        findings: list[ViolationFinding] = []
        for party in (Party.MOTOR_VEHICLE, Party.TWO_WHEELER):
            party_facts = [item for item in facts if _infer_party(item) is party]
            for rule in BEHAVIOR_RULES:
                matching = [
                    item
                    for item in party_facts
                    if any(
                        keyword in _fact_text(item) for keyword in rule.fact_keywords
                    )
                ]
                violating = [
                    item
                    for item in matching
                    if _behavior_fact_status(rule, item) == "violation"
                ]
                compliant = [
                    item
                    for item in matching
                    if _behavior_fact_status(rule, item) == "compliant"
                ]
                active_facts = violating or compliant
                relevant_citations = _citations_for_rule(rule, citations, party)
                fact_ids = sorted(
                    {
                        str(item["fact_id"])
                        for item in active_facts
                        if item.get("fact_id")
                    }
                )
                evidence_ids = sorted(
                    {
                        str(node_id)
                        for item in active_facts
                        for node_id in item.get("source_node_ids", [])
                    }
                )
                if violating:
                    all_confirmed = all(
                        str(item.get("status")) in {"verified", "confirmed"}
                        and str(item.get("fact_id")) not in disputed_ids
                        for item in violating
                    )
                    status = (
                        ViolationStatus.CONFIRMED
                        if all_confirmed and evidence_ids and relevant_citations
                        else ViolationStatus.POSSIBLE
                    )
                    base_confidence = sum(
                        float(item.get("confidence", 0.0)) for item in violating
                    ) / len(violating)
                    confidence = (
                        min(base_confidence, 0.95)
                        if status is ViolationStatus.CONFIRMED
                        else min(base_confidence, 0.69)
                    )
                    behavior = "；".join(
                        str(item.get("statement", "")) for item in violating[:3]
                    )
                elif compliant:
                    status = ViolationStatus.REFUTED
                    confidence = min(
                        sum(
                            float(item.get("confidence", 0.0))
                            for item in compliant
                        )
                        / len(compliant),
                        0.95,
                    )
                    behavior = "；".join(
                        str(item.get("statement", "")) for item in compliant[:3]
                    )
                    relevant_citations = []
                else:
                    status = ViolationStatus.UNKNOWN
                    confidence = 0.0
                    behavior = f"未发现可核验的{rule.display_name}事实"
                findings.append(
                    ViolationFinding(
                        behavior_id=f"VIO-{party.value.upper()}-{rule.category.upper()}",
                        party=party,
                        category=rule.category,
                        behavior=behavior,
                        fact_ids=fact_ids,
                        evidence_ids=evidence_ids,
                        law_citations=relevant_citations,
                        status=status,
                        confidence=round(confidence, 4),
                        explanation=(
                            "confirmed 仅在事实、Evidence ID和有效法律引用同时存在时使用；"
                            "否则保持 possible 或 unknown。"
                        ),
                    )
                )
        return findings

    @staticmethod
    def _causation_matrix(
        findings: list[ViolationFinding],
    ) -> list[CausationFinding]:
        by_category = {rule.category: rule for rule in BEHAVIOR_RULES}
        results: list[CausationFinding] = []
        for finding in findings:
            if finding.status not in {
                ViolationStatus.CONFIRMED,
                ViolationStatus.POSSIBLE,
            }:
                continue
            rule = by_category[finding.category]
            status_weight = 1.0 if finding.status is ViolationStatus.CONFIRMED else 0.55
            strength = round(rule.base_strength * finding.confidence * status_weight, 4)
            role = rule.causal_role
            if finding.category in {"illegal_passenger", "modification"}:
                role = CausalRole.CONDITIONAL
            results.append(
                CausationFinding(
                    behavior_id=finding.behavior_id,
                    causal_role=role,
                    causal_strength=strength,
                    reasoning=(
                        f"{rule.display_name}按其对碰撞发生的直接性、可避免性和"
                        "当前事实置信度评估；违法数量不直接换算责任。"
                    ),
                    counterfactual_effect=(
                        "若可靠证据证明该行为不存在或与碰撞无联系，"
                        "其对应当事人的原因力分值将下降。"
                    ),
                )
            )
        return results

    @staticmethod
    def _party_scores(
        findings: list[ViolationFinding],
        causation: list[CausationFinding],
    ) -> dict[Party, float]:
        finding_by_id = {item.behavior_id: item for item in findings}
        scores = {Party.MOTOR_VEHICLE: 0.0, Party.TWO_WHEELER: 0.0}
        for item in causation:
            finding = finding_by_id[item.behavior_id]
            scores[finding.party] += item.causal_strength
        return scores

    @staticmethod
    def _liability_hypotheses(
        *,
        scores: dict[Party, float],
        findings: list[ViolationFinding],
        missing: list[EvidenceGap],
        blocked: bool,
    ) -> list[LiabilityHypothesis]:
        difference = scores[Party.TWO_WHEELER] - scores[Party.MOTOR_VEHICLE]
        utilities = [difference, -abs(difference) * 0.5, -difference]
        probabilities = _softmax(utilities, temperature=1.25 if blocked else 0.80)
        active_motor = [
            item.behavior_id
            for item in findings
            if item.party is Party.MOTOR_VEHICLE
            and item.status
            in {
                ViolationStatus.CONFIRMED,
                ViolationStatus.POSSIBLE,
            }
        ]
        active_two = [
            item.behavior_id
            for item in findings
            if item.party is Party.TWO_WHEELER
            and item.status
            in {
                ViolationStatus.CONFIRMED,
                ViolationStatus.POSSIBLE,
            }
        ]
        missing_names = [str(item.category) for item in missing]
        templates: tuple[
            tuple[
                str,
                str,
                dict[Party, ResponsibilityLevel],
                list[str],
                list[str],
            ],
            ...,
        ] = (
            (
                "LH-TWO-MAJOR",
                "两轮车辆主要责任、机动车次要责任",
                {
                    Party.MOTOR_VEHICLE: ResponsibilityLevel.MINOR,
                    Party.TWO_WHEELER: ResponsibilityLevel.MAJOR,
                },
                active_two,
                active_motor,
            ),
            (
                "LH-EQUAL",
                "双方同等责任",
                {
                    Party.MOTOR_VEHICLE: ResponsibilityLevel.EQUAL,
                    Party.TWO_WHEELER: ResponsibilityLevel.EQUAL,
                },
                [*active_motor, *active_two],
                [],
            ),
            (
                "LH-MOTOR-MAJOR",
                "机动车主要责任、两轮车辆次要责任",
                {
                    Party.MOTOR_VEHICLE: ResponsibilityLevel.MAJOR,
                    Party.TWO_WHEELER: ResponsibilityLevel.MINOR,
                },
                active_motor,
                active_two,
            ),
        )
        return [
            LiabilityHypothesis(
                hypothesis_id=hypothesis_id,
                label=label,
                probability=probabilities[index],
                party_responsibility=party_responsibility,
                supporting_findings=supporting,
                contradicting_findings=contradicting,
                assumptions=[
                    "仅使用当前 Evidence Graph 中可引用事实",
                    "原因力按直接性而非违法数量排序",
                ],
                missing_evidence=missing_names,
                explanation=(
                    "该方案用于比较当前证据下的责任结构，概率需在专家反馈集上校准。"
                ),
            )
            for index, (
                hypothesis_id,
                label,
                party_responsibility,
                supporting,
                contradicting,
            ) in enumerate(templates)
        ]

    @staticmethod
    def _critical_missing(
        facts: list[dict[str, Any]],
        classification: VehicleNatureClassification,
    ) -> list[EvidenceGap]:
        text = " ".join(_fact_text(item) for item in facts)
        gaps: list[EvidenceGap] = []
        if not any(
            keyword in text
            for keyword in (
                "轨迹",
                "逆行",
                "横穿",
                "驶入",
                "行驶方向",
                "碰撞前",
            )
        ):
            gaps.append(
                _liability_gap(
                    MaterialCategory.DASHCAM_VIDEO,
                    "缺少碰撞前连续轨迹。",
                    ["唯一事故责任结论", "原因力排序"],
                    "固定原始行车记录仪或调取连续路口监控",
                )
            )
        if not any(
            keyword in text for keyword in ("信号灯", "信号相位", "交通标志", "标线")
        ):
            gaps.append(
                _liability_gap(
                    MaterialCategory.ROAD_SIGNAL_EVIDENCE,
                    "信号灯状态、相位或标志标线未知。",
                    ["信号控制义务", "路权"],
                    "调取信号配时、路口监控或补拍标志标线",
                )
            )
        if not any(
            keyword in text
            for keyword in ("让行", "优先通行", "直行", "转弯", "右方来车")
        ):
            gaps.append(
                _liability_gap(
                    "right_of_way",
                    "缺少可确定路权与让行义务的事实。",
                    ["让行义务", "责任等级"],
                    "补充道路结构、行驶方向和标志标线证据",
                )
            )
        if classification in {
            VehicleNatureClassification.SUSPECTED_MOTOR_VEHICLE,
            VehicleNatureClassification.INSUFFICIENT_EVIDENCE,
        }:
            gaps.append(
                _liability_gap(
                    MaterialCategory.VEHICLE_NATURE_APPRAISAL,
                    "车辆属性尚未确定，民事赔偿路径保持 pending。",
                    ["民事赔偿责任路径"],
                    "补充登记、合格证、实车检测与车辆属性鉴定",
                )
            )
        if not any(
            keyword in text for keyword in ("碰撞点", "接触位置", "刹车痕迹", "制动")
        ):
            gaps.append(
                _liability_gap(
                    "collision_point_and_braking",
                    "缺少碰撞点、接触位置或制动痕迹证据。",
                    ["轨迹校验", "可避免性"],
                    "取得现场勘查图、痕迹照片和车辆损伤对应关系",
                )
            )
        return gaps

    @staticmethod
    def _compensation_regime(
        classification: VehicleNatureClassification, has_facts: bool
    ) -> CompensationRegime:
        if not has_facts:
            return CompensationRegime.INSUFFICIENT_EVIDENCE
        if classification is VehicleNatureClassification.MOTOR_VEHICLE:
            return CompensationRegime.MOTOR_VS_MOTOR
        if classification is VehicleNatureClassification.NON_MOTOR_VEHICLE:
            return CompensationRegime.MOTOR_VS_NON_MOTOR_OR_PEDESTRIAN
        return CompensationRegime.PENDING_VEHICLE_CLASSIFICATION

    @staticmethod
    def _civil_allocation(
        *,
        regime: CompensationRegime,
        selected: LiabilityHypothesis,
        legal_basis: list[LegalCitation],
    ) -> CivilCompensationAllocation:
        civil_basis = [
            item
            for item in legal_basis
            if (
                item.document_id == "CN-LAW-RTSA-2021"
                and item.article_no == "第七十六条"
            )
            or (
                item.document_id == "CN-LAW-CIVIL-CODE-2020"
                and item.article_no in {"第一千二百零八条", "第一千二百一十三条"}
            )
        ]
        if regime in {
            CompensationRegime.PENDING_VEHICLE_CLASSIFICATION,
            CompensationRegime.INSUFFICIENT_EVIDENCE,
        }:
            return CivilCompensationAllocation(
                status="insufficient_evidence",
                regime=regime,
                share_ranges=[],
                assumptions=[
                    "车辆法律属性未确定或基础事实不足",
                    "交强险责任限额内外需分层处理",
                ],
                legal_basis=civil_basis,
                explanation=(
                    "车辆属性改变适用路径；在该前置问题解决前不输出赔偿比例。"
                ),
            )
        label = selected.label
        if regime is CompensationRegime.MOTOR_VS_MOTOR:
            motor_range = (
                (0.20, 0.40)
                if label.startswith("两轮车辆主要")
                else ((0.45, 0.55) if label.startswith("双方同等") else (0.60, 0.80))
            )
        else:
            motor_range = (
                (0.30, 0.50)
                if label.startswith("两轮车辆主要")
                else ((0.50, 0.70) if label.startswith("双方同等") else (0.70, 1.00))
            )
        return CivilCompensationAllocation(
            status="range_only",
            regime=regime,
            share_ranges=[
                ShareRange(
                    party=Party.MOTOR_VEHICLE,
                    minimum=motor_range[0],
                    maximum=motor_range[1],
                ),
                ShareRange(
                    party=Party.TWO_WHEELER,
                    minimum=round(1 - motor_range[1], 4),
                    maximum=round(1 - motor_range[0], 4),
                ),
            ],
            assumptions=[
                "区间仅针对交强险责任限额外的过错分担示意",
                "具体比例需结合地区裁判规则、损失项目和人工复核",
            ],
            legal_basis=civil_basis,
            explanation=(
                "民事赔偿责任区间与事故责任概率分开生成，"
                "不等同于保险公司的最终赔付金额。"
            ),
        )

    @staticmethod
    def _insurance_estimate(
        facts: list[dict[str, Any]],
    ) -> InsurancePaymentEstimate:
        text = " ".join(_fact_text(item) for item in facts)
        required = []
        if not any(keyword in text for keyword in ("保险单", "交强险", "商业险")):
            required.append("保险单与适用保险条款")
        if not any(keyword in text for keyword in ("责任限额", "保险限额")):
            required.append("交强险及商业险责任限额")
        if not any(
            keyword in text for keyword in ("医疗费", "维修费", "定损金额", "损失金额")
        ):
            required.append("经核验的损失项目与金额")
        required.extend(["免赔/免责条款适用性", "既往赔付或垫付金额"])
        return InsurancePaymentEstimate(
            status="insufficient_data",
            estimated_amount=None,
            required_inputs=sorted(set(required)),
            explanation=(
                "保险支付取决于交强险、商业险、责任限额、合同条款和损失数据；"
                "当前不估算具体金额。"
            ),
        )

    @staticmethod
    def _counterfactual_analysis(
        facts: list[dict[str, Any]],
        hypotheses: list[LiabilityHypothesis],
    ) -> list[CounterfactualFinding]:
        text = " ".join(_fact_text(item) for item in facts)
        ids = {item.hypothesis_id: item.label for item in hypotheses}
        two_major = next(
            key for key, label in ids.items() if label.startswith("两轮车辆主要")
        )
        equal = next(key for key, label in ids.items() if label.startswith("双方同等"))
        motor_major = next(
            key for key, label in ids.items() if label.startswith("机动车主要")
        )
        definitions = (
            (
                "intersection_surveillance",
                any(keyword in text for keyword in ("路口监控", "连续监控")),
                "调取覆盖碰撞前后时段的路口监控原文件",
                CounterfactualBranch(
                    condition="若监控显示两轮车辆逆行或突然横穿",
                    increases_hypotheses=[two_major],
                    decreases_hypotheses=[motor_major],
                    explanation="直接触发行为和可避免性证据将偏向两轮车辆原因力上升。",
                ),
                CounterfactualBranch(
                    condition="若监控显示机动车违反信号或未让优先车辆",
                    increases_hypotheses=[motor_major],
                    decreases_hypotheses=[two_major],
                    explanation="机动车的触发性通行行为得到支持时，其原因力上升。",
                ),
            ),
            (
                "original_dashcam",
                any(keyword in text for keyword in ("原始行车记录仪", "连续轨迹")),
                "固定含时间戳和完整前后片段的原始行车记录仪",
                CounterfactualBranch(
                    condition="若原视频显示机动车及时制动且两轮车辆突然进入",
                    increases_hypotheses=[two_major],
                    decreases_hypotheses=[motor_major],
                    explanation="机动车可避免性下降，两轮车辆触发性上升。",
                ),
                CounterfactualBranch(
                    condition="若原视频显示机动车有充分反应时间但未观察或未制动",
                    increases_hypotheses=[motor_major, equal],
                    decreases_hypotheses=[two_major],
                    explanation="机动车注意与避让原因力上升。",
                ),
            ),
            (
                "vehicle_nature_appraisal",
                "车辆属性鉴定" in text,
                "取得完整鉴定意见并核验检材、方法和标准版本",
                CounterfactualBranch(
                    condition="若有效鉴定和管理证据支持机动车属性",
                    increases_hypotheses=[],
                    decreases_hypotheses=[],
                    explanation="该结果主要改变民事赔偿路径，不单独改变事故原因力。",
                ),
                CounterfactualBranch(
                    condition="若有效证据支持非机动车属性",
                    increases_hypotheses=[],
                    decreases_hypotheses=[],
                    explanation="该结果主要改变民事赔偿路径，不单独改变事故原因力。",
                ),
            ),
            (
                "signal_phase",
                any(keyword in text for keyword in ("信号相位", "信号灯状态")),
                "调取信号控制系统相位记录并与视频时间校准",
                CounterfactualBranch(
                    condition="若相位记录显示两轮车辆违反停止信号",
                    increases_hypotheses=[two_major],
                    decreases_hypotheses=[motor_major],
                    explanation="违反信号的触发性原因得到支持。",
                ),
                CounterfactualBranch(
                    condition="若相位记录显示机动车违反停止信号",
                    increases_hypotheses=[motor_major],
                    decreases_hypotheses=[two_major],
                    explanation="机动车触发性原因得到支持。",
                ),
            ),
            (
                "collision_point_and_brake_marks",
                any(keyword in text for keyword in ("碰撞点", "接触位置", "刹车痕迹")),
                "取得现场勘查图、刹车痕迹和两车损伤对应照片",
                CounterfactualBranch(
                    condition="若痕迹支持两轮车辆侵入机动车既有行驶路径",
                    increases_hypotheses=[two_major],
                    decreases_hypotheses=[motor_major],
                    explanation="侵入路径与碰撞触发关系得到支持。",
                ),
                CounterfactualBranch(
                    condition="若痕迹支持机动车偏离车道或无有效制动",
                    increases_hypotheses=[motor_major, equal],
                    decreases_hypotheses=[two_major],
                    explanation="机动车车道使用或可避免性原因力上升。",
                ),
            ),
        )
        return [
            CounterfactualFinding(
                evidence_type=evidence_type,
                current_status="available" if available else "missing",
                branches=[branch_a, branch_b],
                collection_action=action,
            )
            for evidence_type, available, action, branch_a, branch_b in definitions
        ]


def _fact_text(fact: dict[str, Any]) -> str:
    return " ".join(
        str(fact.get(key, "")) for key in ("statement", "subject", "predicate", "value")
    )


def _infer_party(fact: dict[str, Any]) -> Party:
    text = _fact_text(fact)
    if any(
        keyword in text for keyword in ("两轮车辆", "电动车", "电动自行车", "骑行人")
    ):
        return Party.TWO_WHEELER
    if any(
        keyword in text
        for keyword in ("机动车驾驶人", "机动车", "汽车", "轿车", "小客车")
    ):
        return Party.MOTOR_VEHICLE
    return Party.UNKNOWN


def _behavior_fact_status(rule: BehaviorRule, fact: dict[str, Any]) -> str:
    text = _fact_text(fact)
    if any(marker in text for marker in rule.excluded_markers):
        return "neutral"
    if any(marker in text for marker in rule.compliance_markers):
        return "compliant"
    if any(marker in text for marker in rule.violation_markers):
        return "violation"
    return "neutral"


def _citations_for_rule(
    rule: BehaviorRule,
    citations: list[LegalCitation],
    party: Party,
) -> list[LegalCitation]:
    refs = (
        rule.motor_law_refs
        if party is Party.MOTOR_VEHICLE
        else rule.two_wheeler_law_refs
    )
    return [
        citation
        for citation in citations
        if (citation.document_id, citation.article_no or "") in refs
    ][:3]


def _softmax(values: list[float], *, temperature: float) -> list[float]:
    scaled = [value / temperature for value in values]
    maximum = max(scaled)
    exponentials = [math.exp(value - maximum) for value in scaled]
    total = sum(exponentials)
    raw = [value / total for value in exponentials]
    rounded = [round(value, 6) for value in raw[:-1]]
    rounded.append(round(1.0 - sum(rounded), 6))
    return rounded


def _key_evidence(
    facts: list[dict[str, Any]], findings: list[ViolationFinding]
) -> list[EvidenceReference]:
    ids = []
    for finding in sorted(findings, key=lambda item: item.confidence, reverse=True):
        if finding.status in {
            ViolationStatus.CONFIRMED,
            ViolationStatus.POSSIBLE,
        }:
            ids.extend(finding.fact_ids)
    selected = set(ids[:10])
    result = []
    for fact in facts:
        if fact.get("fact_id") not in selected or not fact.get("source_node_ids"):
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


def _liability_gap(
    category: MaterialCategory | str,
    reason: str,
    required_for: list[str],
    method: str,
) -> EvidenceGap:
    return EvidenceGap(
        category=category,
        reason=reason,
        required_for=required_for,
        priority=Priority.P0,
        collection_method=method,
        related_agent="liability",
        blocks_conclusions=required_for,
    )
