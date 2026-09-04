"""Evidence intake plus business-layer material completeness assessment.

The legacy :func:`assess_intake` remains the reconstruction gate. The business
agent consumes its already-parsed sources and facts and never repeats OCR,
video parsing, or visual extraction.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.schemas.business import (
    BlockingIssue,
    CaseIntakeResult,
    EvidenceGap,
    IssueSeverity,
    MaterialCategory,
    Priority,
    QualityIssue,
    UploadedMaterial,
)
from app.schemas.evidence import SourceFile, SourceKind, SourceRole


@dataclass(frozen=True)
class IntakeAssessment:
    uploaded_materials: tuple[str, ...]
    missing_materials: tuple[str, ...]
    ready_for_reconstruction: bool
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "uploaded_materials": list(self.uploaded_materials),
            "missing_materials": list(self.missing_materials),
            "ready_for_reconstruction": self.ready_for_reconstruction,
            "warnings": list(self.warnings),
        }


def assess_intake(sources: list[SourceFile]) -> IntakeAssessment:
    roles = {source.role for source in sources}
    kinds = {source.kind for source in sources}
    uploaded = tuple(
        f"{source.source_id}: {source.original_name} ({source.role.value})"
        for source in sources
    )
    missing: list[str] = []
    warnings: list[str] = []

    if not ({SourceKind.IMAGE, SourceKind.VIDEO} & kinds):
        missing.append("至少一份现场照片或行车记录仪视频")
    if SourceRole.ACCIDENT_DETERMINATION not in roles:
        missing.append("道路交通事故认定书（如已出具）")
    if not ({SourceRole.VEHICLE_DOCUMENT, SourceRole.APPRAISAL_REPORT} & roles):
        missing.append("两轮车辆合格证/登记资料或车辆属性鉴定材料")
    if all(source.role is SourceRole.OTHER for source in sources):
        warnings.append("所有材料均未声明用途，后续缺件判断可能不完整。")

    return IntakeAssessment(
        uploaded_materials=uploaded,
        missing_materials=tuple(missing),
        ready_for_reconstruction=bool(sources)
        and bool({SourceKind.IMAGE, SourceKind.VIDEO, SourceKind.PDF} & kinds),
        warnings=tuple(warnings),
    )


ROLE_CATEGORIES: dict[SourceRole, set[MaterialCategory]] = {
    SourceRole.ACCIDENT_DETERMINATION: {MaterialCategory.ACCIDENT_DETERMINATION},
    SourceRole.DELIVERY_INFORMATION: {MaterialCategory.DELIVERY_INFORMATION},
    SourceRole.DASHCAM_VIDEO: {MaterialCategory.DASHCAM_VIDEO},
    SourceRole.SCENE_PHOTO: {MaterialCategory.SCENE_PHOTOS},
    SourceRole.ROAD_SIGNAL_EVIDENCE: {MaterialCategory.ROAD_SIGNAL_EVIDENCE},
    SourceRole.VEHICLE_REGISTRATION: {MaterialCategory.VEHICLE_REGISTRATION_PLATE},
    SourceRole.VEHICLE_CERTIFICATE_CCC: {MaterialCategory.VEHICLE_CERTIFICATE_CCC},
    SourceRole.VEHICLE_TECHNICAL_PARAMETERS: {
        MaterialCategory.VEHICLE_TECHNICAL_PARAMETERS
    },
    SourceRole.APPRAISAL_REPORT: {MaterialCategory.VEHICLE_NATURE_APPRAISAL},
    SourceRole.INQUIRY_RECORD: {MaterialCategory.INQUIRY_RECORD},
    SourceRole.MEDICAL_RECORD: {MaterialCategory.MEDICAL_REPAIR_MATERIALS},
    SourceRole.REPAIR_RECORD: {MaterialCategory.MEDICAL_REPAIR_MATERIALS},
    SourceRole.INSURANCE_POLICY: {MaterialCategory.INSURANCE_POLICY_TERMS},
}


CATEGORY_DETAILS: dict[MaterialCategory, tuple[str, list[str], Priority, str, str]] = {
    MaterialCategory.ACCIDENT_DETERMINATION: (
        "核对交警记录的事实、成因、责任与送达程序",
        ["事故责任分析", "复核权利识别"],
        Priority.P0,
        "取得道路交通事故认定书原件或清晰扫描件",
        "case_intake",
    ),
    MaterialCategory.DELIVERY_INFORMATION: (
        "期限起算必须有可核验的送达时间",
        ["复核期限计算"],
        Priority.P0,
        "补充送达回证、短信/平台记录或人工确认的送达日期",
        "rights_workflow",
    ),
    MaterialCategory.DASHCAM_VIDEO: (
        "碰撞前连续轨迹比单张照片更能支持原因力判断",
        ["碰撞前轨迹", "制动避让", "原因力分析"],
        Priority.P0,
        "固定并上传带原始时间信息的行车记录仪文件",
        "liability",
    ),
    MaterialCategory.SCENE_PHOTOS: (
        "现场位置、车道、碰撞点和损伤形态需要图像支持",
        ["事故现场还原", "碰撞点核验"],
        Priority.P0,
        "上传未经裁剪的现场照片并保留原始元数据",
        "evidence",
    ),
    MaterialCategory.ROAD_SIGNAL_EVIDENCE: (
        "路权、信号灯相位和标志标线会改变责任假设",
        ["信号灯状态", "让行义务", "路权"],
        Priority.P0,
        "申请调取路口监控、信号配时或补拍标志标线",
        "liability",
    ),
    MaterialCategory.VEHICLE_REGISTRATION_PLATE: (
        "登记及管理方式是车辆法律属性的重要独立因素",
        ["车辆法律属性", "赔偿路径"],
        Priority.P0,
        "核验号牌、登记证或属地登记查询结果",
        "vehicle_nature",
    ),
    MaterialCategory.VEHICLE_CERTIFICATE_CCC: (
        "车型、产品属性与CCC一致性不能只靠外观推断",
        ["车辆产品属性", "是否改装"],
        Priority.P0,
        "取得车辆合格证、CCC证书和车型信息",
        "vehicle_nature",
    ),
    MaterialCategory.VEHICLE_TECHNICAL_PARAMETERS: (
        "技术标准只能在参数可追溯时逐项比较",
        ["技术标准符合性"],
        Priority.P1,
        "取得铭牌、说明书或检测报告中的车速、质量、功率等参数",
        "vehicle_nature",
    ),
    MaterialCategory.VEHICLE_NATURE_APPRAISAL: (
        "车辆属性鉴定可显著影响法律属性判断，但仍需审查依据和程序",
        ["车辆法律属性", "赔偿路径"],
        Priority.P0,
        "取得完整鉴定意见、委托事项、检材和鉴定依据",
        "vehicle_nature",
    ),
    MaterialCategory.INQUIRY_RECORD: (
        "各方陈述可用于发现争点但不能替代客观证据",
        ["事实冲突核验"],
        Priority.P1,
        "申请复制询问笔录或提交当事人陈述",
        "case_intake",
    ),
    MaterialCategory.MEDICAL_REPAIR_MATERIALS: (
        "损失项目和金额需要票据、诊断及维修清单支持",
        ["损失核定", "赔偿与保险支付"],
        Priority.P1,
        "补充医疗票据、诊断证明、维修清单或定损单",
        "compensation",
    ),
    MaterialCategory.INSURANCE_POLICY_TERMS: (
        "保险限额、免赔和责任范围取决于具体保单及条款",
        ["保险赔付估算"],
        Priority.P1,
        "上传交强险、商业险保单及适用条款",
        "insurance",
    ),
}


FACT_CATEGORY_KEYWORDS: dict[MaterialCategory, tuple[str, ...]] = {
    MaterialCategory.DELIVERY_INFORMATION: ("送达日期", "送达时间", "送达回证"),
    MaterialCategory.ROAD_SIGNAL_EVIDENCE: (
        "信号灯",
        "交通标志",
        "标线",
        "路口监控",
        "信号相位",
    ),
    MaterialCategory.VEHICLE_REGISTRATION_PLATE: (
        "登记类型",
        "号牌类型",
        "车辆登记",
        "行驶证",
    ),
    MaterialCategory.VEHICLE_CERTIFICATE_CCC: (
        "合格证",
        "CCC",
        "3C认证",
        "产品型号",
    ),
    MaterialCategory.VEHICLE_TECHNICAL_PARAMETERS: (
        "最高设计",
        "整车质量",
        "电机功率",
        "额定功率",
        "标称电压",
        "车体宽度",
        "脚踏",
    ),
    MaterialCategory.VEHICLE_NATURE_APPRAISAL: (
        "车辆属性鉴定",
        "鉴定为机动车",
        "鉴定为非机动车",
    ),
    MaterialCategory.INQUIRY_RECORD: ("询问笔录", "当事人陈述"),
    MaterialCategory.MEDICAL_REPAIR_MATERIALS: (
        "医疗费",
        "诊断",
        "维修",
        "定损",
    ),
    MaterialCategory.INSURANCE_POLICY_TERMS: (
        "保险单",
        "交强险",
        "商业险",
        "保险条款",
    ),
}


def _fact_text(fact: dict[str, Any]) -> str:
    return " ".join(
        str(fact.get(key, "")) for key in ("statement", "subject", "predicate", "value")
    )


def _gap(category: MaterialCategory) -> EvidenceGap:
    reason, required_for, priority, method, agent = CATEGORY_DETAILS[category]
    blocked = (
        required_for
        if category
        in {
            MaterialCategory.DASHCAM_VIDEO,
            MaterialCategory.SCENE_PHOTOS,
            MaterialCategory.ROAD_SIGNAL_EVIDENCE,
            MaterialCategory.VEHICLE_REGISTRATION_PLATE,
            MaterialCategory.VEHICLE_NATURE_APPRAISAL,
        }
        else []
    )
    return EvidenceGap(
        category=category,
        reason=reason,
        required_for=required_for,
        priority=priority,
        collection_method=method,
        related_agent=agent,
        blocks_conclusions=blocked,
    )


def assess_business_intake(
    sources: list[SourceFile],
    facts: list[dict[str, Any]],
    *,
    evidence_nodes: list[dict[str, Any]] | None = None,
    conflicts: list[dict[str, Any]] | None = None,
    case_type: str = "motor_vehicle_vs_two_wheeler",
) -> CaseIntakeResult:
    """Assess business material completeness using existing evidence outputs."""

    evidence_nodes = evidence_nodes or []
    conflicts = conflicts or []
    categories: dict[MaterialCategory, dict[str, set[str]]] = {}
    for source in sources:
        mapped = set(ROLE_CATEGORIES.get(source.role, set()))
        if source.role is SourceRole.VEHICLE_DOCUMENT:
            mapped.update(
                {
                    MaterialCategory.VEHICLE_REGISTRATION_PLATE,
                    MaterialCategory.VEHICLE_CERTIFICATE_CCC,
                }
            )
        for category in mapped:
            entry = categories.setdefault(
                category, {"source_ids": set(), "evidence_ids": set()}
            )
            entry["source_ids"].add(source.source_id)

    for fact in facts:
        text = _fact_text(fact)
        for category, keywords in FACT_CATEGORY_KEYWORDS.items():
            if any(keyword.lower() in text.lower() for keyword in keywords):
                entry = categories.setdefault(
                    category, {"source_ids": set(), "evidence_ids": set()}
                )
                entry["evidence_ids"].update(fact.get("source_node_ids", []))

    node_source = {
        item.get("node_id"): item.get("source_id") for item in evidence_nodes
    }
    for entry in categories.values():
        for evidence_id in entry["evidence_ids"]:
            source_id = node_source.get(evidence_id)
            if source_id:
                entry["source_ids"].add(str(source_id))

    uploaded = [
        UploadedMaterial(
            category=category,
            source_ids=sorted(values["source_ids"]),
            evidence_ids=sorted(values["evidence_ids"]),
            description=CATEGORY_DETAILS[category][0],
        )
        for category, values in sorted(
            categories.items(), key=lambda item: item[0].value
        )
    ]
    required_categories = {
        MaterialCategory.ACCIDENT_DETERMINATION,
        MaterialCategory.DASHCAM_VIDEO,
        MaterialCategory.SCENE_PHOTOS,
        MaterialCategory.ROAD_SIGNAL_EVIDENCE,
        MaterialCategory.VEHICLE_REGISTRATION_PLATE,
        MaterialCategory.VEHICLE_CERTIFICATE_CCC,
        MaterialCategory.VEHICLE_NATURE_APPRAISAL,
    }
    optional_categories = set(MaterialCategory) - required_categories
    missing_required = [
        _gap(category)
        for category in sorted(
            required_categories - set(categories), key=lambda x: x.value
        )
    ]
    missing_optional = [
        _gap(category)
        for category in sorted(
            optional_categories - set(categories), key=lambda x: x.value
        )
    ]

    has_visual = bool(
        {
            MaterialCategory.DASHCAM_VIDEO,
            MaterialCategory.SCENE_PHOTOS,
        }
        & set(categories)
    )
    has_any_evidence = bool(sources and evidence_nodes and facts)
    blocking: list[BlockingIssue] = []
    if not has_any_evidence:
        blocking.append(
            BlockingIssue(
                code="NO_RECONSTRUCTED_EVIDENCE",
                message="尚无可引用的证据节点与事实，业务 Agent 不得形成结论。",
                blocked_outputs=[
                    "vehicle_nature",
                    "accident_responsibility",
                    "civil_compensation",
                ],
                related_missing_categories=[
                    MaterialCategory.DASHCAM_VIDEO,
                    MaterialCategory.SCENE_PHOTOS,
                ],
            )
        )
    if not has_visual:
        blocking.append(
            BlockingIssue(
                code="NO_SCENE_OR_TRAJECTORY_EVIDENCE",
                message="缺少现场或连续轨迹证据，阻断唯一事故责任结论。",
                blocked_outputs=["unique_accident_responsibility"],
                related_missing_categories=[
                    MaterialCategory.DASHCAM_VIDEO,
                    MaterialCategory.SCENE_PHOTOS,
                ],
            )
        )
    if not (
        {
            MaterialCategory.VEHICLE_REGISTRATION_PLATE,
            MaterialCategory.VEHICLE_NATURE_APPRAISAL,
        }
        & set(categories)
    ):
        blocking.append(
            BlockingIssue(
                code="NO_CORE_VEHICLE_NATURE_EVIDENCE",
                message="缺少登记/号牌与车辆属性鉴定，阻断确定性机动车结论。",
                blocked_outputs=[
                    "definite_vehicle_classification",
                    "final_compensation_regime",
                ],
                related_missing_categories=[
                    MaterialCategory.VEHICLE_REGISTRATION_PLATE,
                    MaterialCategory.VEHICLE_NATURE_APPRAISAL,
                ],
            )
        )

    quality_issues = [
        QualityIssue(
            code="EVIDENCE_CONFLICT",
            message=item.get("description", "证据事实存在冲突，需人工核验。"),
            severity=IssueSeverity.BLOCKING,
            evidence_ids=[],
        )
        for item in conflicts
    ]
    low_quality_sources = [
        source.source_id for source in sources if source.status.value == "failed"
    ]
    if low_quality_sources:
        quality_issues.append(
            QualityIssue(
                code="SOURCE_PROCESSING_FAILED",
                message="部分材料解析失败，需重新上传清晰原件或人工录入。",
                severity=IssueSeverity.WARNING,
                source_ids=low_quality_sources,
            )
        )

    actions = sorted(
        [*missing_required, *missing_optional],
        key=lambda item: (item.priority.value, str(item.category)),
    )
    return CaseIntakeResult(
        case_type=case_type,
        uploaded_materials=uploaded,
        missing_required_materials=missing_required,
        missing_optional_materials=missing_optional,
        quality_issues=quality_issues,
        blocking_issues=blocking,
        next_collection_actions=actions,
        can_continue_analysis=has_any_evidence,
        route_hint=("evidence_ready" if has_any_evidence else "missing_evidence"),
    )
