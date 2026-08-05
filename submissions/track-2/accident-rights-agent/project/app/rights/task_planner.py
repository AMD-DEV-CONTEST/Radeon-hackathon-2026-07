"""Create lawful, evidence-linked rights tasks from deterministic case gaps."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.schemas.business import LiabilityResult, VehicleNatureResult
from app.schemas.rights import (
    DeadlineResult,
    DeadlineStatus,
    RightsTask,
    TaskPriority,
)


class RightsTaskPlanner:
    def plan(
        self,
        *,
        missing_evidence: list[dict[str, Any]],
        vehicle_result: VehicleNatureResult | None,
        liability_result: LiabilityResult | None,
        deadlines: list[DeadlineResult],
        conflicts: list[dict[str, Any]],
        legal_issues: list[str] | None = None,
    ) -> list[RightsTask]:
        gaps = " ".join(
            " ".join(
                str(item.get(key, ""))
                for key in ("category", "reason", "collection_method", "required_for")
            )
            for item in missing_evidence
        )
        valid_fact_ids, valid_evidence_ids, law_ids = _linked_ids(
            vehicle_result, liability_result
        )
        tasks: list[RightsTask] = []

        review_deadline = next(
            (
                item
                for item in deadlines
                if item.matter_type == "accident_determination_review"
            ),
            None,
        )
        appraisal_deadline = next(
            (item for item in deadlines if item.matter_type == "appraisal_objection"),
            None,
        )
        if review_deadline:
            review_actions = [
                "核对送达回执、签收记录或电子送达记录",
                "整理争议事实与相反证据",
                "生成复核申请草稿并交由人工审核",
            ]
            if review_deadline.status is DeadlineStatus.EXPIRED:
                review_actions = [
                    "保留逾期状态和计算依据，不再表述为仍可按期提交",
                    "请法律专业人员核验是否存在其他程序性或诉讼救济路径",
                    "其他补救建议仅作待核验占位，不保证受理或可行",
                ]
            tasks.append(
                self._task(
                    task_type="prepare_accident_review",
                    title="准备道路交通事故认定复核材料",
                    objective="在已核验期限内形成事实、证据和法律依据一致的书面复核申请草稿。",
                    priority=_deadline_priority(review_deadline),
                    due_at=review_deadline.due_at,
                    blocking=review_deadline.status
                    in {DeadlineStatus.DUE_SOON, DeadlineStatus.DISPUTED},
                    fact_ids=valid_fact_ids,
                    evidence_ids=valid_evidence_ids,
                    law_ids=[
                        *law_ids,
                        *[item.source_id for item in review_deadline.legal_citations],
                    ],
                    prerequisites=[
                        "人工确认送达日期",
                        "核对事故认定书编号和申请人信息",
                        "Verifier与Policy Gate通过",
                    ],
                    actions=review_actions,
                    responsible_role="case_handler",
                )
            )
        if appraisal_deadline:
            tasks.append(
                self._task(
                    task_type="appraisal_objection_or_reappraisal",
                    title="三日内提交《重新检验、鉴定申请书》",
                    objective="在法定期限内核验鉴定资质、依据、检材和分析过程。",
                    priority=_deadline_priority(appraisal_deadline),
                    due_at=appraisal_deadline.due_at,
                    blocking=appraisal_deadline.status
                    in {DeadlineStatus.DUE_SOON, DeadlineStatus.DISPUTED},
                    fact_ids=valid_fact_ids,
                    evidence_ids=valid_evidence_ids,
                    law_ids=[
                        *law_ids,
                        *[
                            item.source_id
                            for item in appraisal_deadline.legal_citations
                        ],
                    ],
                    prerequisites=["人工确认鉴定意见送达日期", "取得完整鉴定意见"],
                    actions=[
                        "核对鉴定机构与鉴定人资质",
                        "核对检材来源、技术依据和分析过程",
                        "向原办案交管部门提交书面申请并请求另行委托鉴定机构",
                    ],
                    responsible_role="legal_reviewer",
                )
            )

        tasks.extend(
            [
                self._task(
                    task_type="preserve_dashcam_original",
                    title="保存行车记录仪原文件",
                    objective="固定原始载体、哈希、时间信息和连续画面，避免证据灭失。",
                    priority=TaskPriority.HIGH,
                    due_at=review_deadline.due_at if review_deadline else None,
                    blocking="行车记录仪" in gaps or "视频" in gaps,
                    fact_ids=valid_fact_ids,
                    evidence_ids=valid_evidence_ids,
                    law_ids=law_ids,
                    prerequisites=[],
                    actions=[
                        "只读复制原始文件并计算哈希",
                        "保留存储卡或原设备",
                        "记录复制人、时间和介质",
                    ],
                    responsible_role="vehicle_owner",
                ),
                self._task(
                    task_type="request_case_file_copy",
                    title="依法申请查阅、复制事故案卷材料",
                    objective="取得现场图、勘验记录、询问笔录及已公开证据材料。",
                    priority=TaskPriority.HIGH,
                    due_at=review_deadline.due_at if review_deadline else None,
                    blocking=bool(review_deadline),
                    fact_ids=valid_fact_ids,
                    evidence_ids=valid_evidence_ids,
                    law_ids=law_ids,
                    prerequisites=["确认申请主体资格和承办单位"],
                    actions=["列明申请材料范围", "保留申请和接收记录"],
                    responsible_role="case_handler",
                ),
                self._task(
                    task_type="insurance_notification",
                    title="向保险公司报案并补充案件材料",
                    objective="如实报告事故并按要求补充保单、损失和责任材料。",
                    priority=TaskPriority.MEDIUM,
                    due_at=None,
                    blocking=False,
                    fact_ids=valid_fact_ids,
                    evidence_ids=valid_evidence_ids,
                    law_ids=law_ids,
                    prerequisites=["核对保单和报案渠道"],
                    actions=["保存报案号", "提交材料清单", "记录补件要求"],
                    responsible_role="insured_or_claim_handler",
                ),
                self._task(
                    task_type="claim_handler_communication",
                    title="与理赔员核对责任、损失和补件事项",
                    objective="保持事实、责任、赔偿路径与保险责任分层沟通。",
                    priority=TaskPriority.MEDIUM,
                    due_at=None,
                    blocking=False,
                    fact_ids=valid_fact_ids,
                    evidence_ids=valid_evidence_ids,
                    law_ids=law_ids,
                    prerequisites=["准备案件摘要和证据目录"],
                    actions=[
                        "记录沟通日期与要点",
                        "仅陈述已核验事实",
                        "确认下一步材料",
                    ],
                    responsible_role="claim_handler",
                ),
            ]
        )

        if (
            any(
                keyword in gaps
                for keyword in ("监控", "信号", "轨迹", "碰撞点", "刹车", "现场")
            )
            or conflicts
        ):
            tasks.append(
                self._task(
                    task_type="collect_scene_and_cctv",
                    title="依法调取路口监控并补充碰撞点、刹车痕迹证据",
                    objective="补强车辆轨迹、信号相位、碰撞位置和避让行为的客观证据。",
                    priority=TaskPriority.HIGH,
                    due_at=review_deadline.due_at if review_deadline else None,
                    blocking=True,
                    fact_ids=valid_fact_ids,
                    evidence_ids=valid_evidence_ids,
                    law_ids=law_ids,
                    prerequisites=["确认监控管理单位和合法申请渠道"],
                    actions=[
                        "尽快提出保存或调取申请",
                        "申请复制现场图和勘验记录",
                        "保留申请回执，不接触或修改原始数据",
                    ],
                    responsible_role="case_handler",
                )
            )

        if any(
            keyword in gaps
            for keyword in ("登记", "号牌", "合格证", "CCC", "车辆属性", "鉴定")
        ) or (
            vehicle_result
            and vehicle_result.classification.value
            in {"suspected_motor_vehicle", "insufficient_evidence"}
        ):
            has_appraisal = bool(
                vehicle_result
                and any(
                    factor.fact_ids or factor.evidence_ids
                    for factor in vehicle_result.appraisal_factors
                )
            )
            tasks.append(
                self._task(
                    task_type="verify_vehicle_nature",
                    title=(
                        "向办案交警提交《重新检验、鉴定申请书》"
                        if has_appraisal
                        else "向办案交警提交《车辆属性检验、鉴定申请书》"
                    ),
                    objective=(
                        "把车辆参数、实车改装、产品一致性与法律属性认定分开核验，"
                        "并由办案交管部门依法审查和委托。"
                    ),
                    priority=TaskPriority.HIGH,
                    due_at=appraisal_deadline.due_at if appraisal_deadline else None,
                    blocking=True,
                    fact_ids=valid_fact_ids,
                    evidence_ids=valid_evidence_ids,
                    law_ids=law_ids,
                    prerequisites=["取得车辆识别信息和实车照片"],
                    actions=[
                        (
                            "确认原鉴定意见送达日期并核对三日申请期限"
                            if has_appraisal
                            else "确认办案单位、事故编号和拟申请的鉴定事项"
                        ),
                        "列明最高设计车速、解除限速、整车质量、电机功率和电池电压",
                        "列明脚踏能力、实车与合格证/CCC一致性及改装情况",
                        (
                            "请求原办案单位另行委托鉴定机构"
                            if has_appraisal
                            else "请求办案交管部门依法审查并委托鉴定"
                        ),
                    ],
                    responsible_role="vehicle_nature_reviewer",
                )
            )

        if legal_issues:
            tasks.append(
                self._task(
                    task_type="legal_review",
                    title="对规则冲突或法律适用问题进行人工复核",
                    objective="确认案件日期、管辖范围和法律版本后再形成确定性结论。",
                    priority=TaskPriority.HIGH,
                    due_at=review_deadline.due_at if review_deadline else None,
                    blocking=True,
                    fact_ids=valid_fact_ids,
                    evidence_ids=valid_evidence_ids,
                    law_ids=law_ids,
                    prerequisites=list(legal_issues),
                    actions=["核对官方现行文本", "记录适用版本和处理意见"],
                    responsible_role="legal_reviewer",
                )
            )
        return _deduplicate_tasks(tasks)

    @staticmethod
    def _task(
        *,
        task_type: str,
        title: str,
        objective: str,
        priority: TaskPriority,
        due_at: Any,
        blocking: bool,
        fact_ids: list[str],
        evidence_ids: list[str],
        law_ids: list[str],
        prerequisites: list[str],
        actions: list[str],
        responsible_role: str,
    ) -> RightsTask:
        digest = (
            hashlib.sha256(
                json.dumps(
                    [task_type, title, sorted(fact_ids), sorted(evidence_ids)],
                    ensure_ascii=False,
                    sort_keys=True,
                ).encode("utf-8")
            )
            .hexdigest()[:16]
            .upper()
        )
        return RightsTask(
            task_id=f"TASK-{digest}",
            task_type=task_type,
            title=title,
            objective=objective,
            priority=priority,
            due_at=due_at,
            blocking=blocking,
            related_fact_ids=sorted(set(fact_ids)),
            related_evidence_ids=sorted(set(evidence_ids)),
            related_law_ids=sorted(set(law_ids)),
            prerequisites=prerequisites,
            recommended_actions=actions,
            responsible_role=responsible_role,
            human_approval_required=True,
        )


def _deadline_priority(deadline: DeadlineResult) -> TaskPriority:
    if deadline.status in {
        DeadlineStatus.DUE_SOON,
        DeadlineStatus.DISPUTED,
        DeadlineStatus.EXPIRED,
    }:
        return TaskPriority.CRITICAL
    return TaskPriority.HIGH


def _linked_ids(
    vehicle: VehicleNatureResult | None,
    liability: LiabilityResult | None,
) -> tuple[list[str], list[str], list[str]]:
    fact_ids: set[str] = set()
    evidence_ids: set[str] = set()
    law_ids: set[str] = set()
    if vehicle:
        for reference in [*vehicle.supporting_facts, *vehicle.contradicting_facts]:
            fact_ids.add(reference.fact_id)
            evidence_ids.update(reference.evidence_ids)
        law_ids.update(item.source_id for item in vehicle.legal_basis)
    if liability:
        for reference in liability.key_evidence:
            fact_ids.add(reference.fact_id)
            evidence_ids.update(reference.evidence_ids)
        for finding in liability.violation_matrix:
            fact_ids.update(finding.fact_ids)
            evidence_ids.update(finding.evidence_ids)
            law_ids.update(item.source_id for item in finding.law_citations)
        law_ids.update(item.source_id for item in liability.legal_basis)
    return sorted(fact_ids), sorted(evidence_ids), sorted(law_ids)


def _deduplicate_tasks(tasks: list[RightsTask]) -> list[RightsTask]:
    unique: dict[str, RightsTask] = {}
    for task in tasks:
        unique[task.task_type] = task
    return sorted(
        unique.values(),
        key=lambda item: (
            list(TaskPriority).index(item.priority),
            item.task_type,
        ),
    )
