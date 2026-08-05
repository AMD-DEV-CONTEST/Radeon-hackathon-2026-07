"""Convert business-agent evidence gaps into lawful collection checklists."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.schemas.rights import (
    CounterfactualImpact,
    DeadlineResult,
    EvidenceCollectionItem,
    TaskPriority,
)


class EvidenceGapPlanner:
    def plan(
        self,
        *,
        gaps: list[dict[str, Any]],
        deadlines: list[DeadlineResult],
        counterfactuals: list[dict[str, Any]] | None = None,
    ) -> list[EvidenceCollectionItem]:
        nearest_due = min(
            (item.due_at for item in deadlines if item.due_at is not None),
            default=None,
        )
        results: list[EvidenceCollectionItem] = []
        seen_gap_ids: set[str] = set()
        for gap in gaps:
            missing = str(gap.get("reason") or gap.get("category") or "未明确证据")
            affected = [
                str(value)
                for value in (
                    gap.get("required_for")
                    or gap.get("blocks_conclusions")
                    or ["车辆属性或责任假设"]
                )
            ]
            priority = _priority(str(gap.get("priority", "P1")))
            methods, alternatives, fallback = _collection_guidance(missing)
            fact_ids = sorted(
                {
                    str(value)
                    for value in gap.get("related_fact_ids", [])
                    if str(value).startswith("FACT-")
                }
            )
            evidence_ids = sorted(
                {
                    str(value)
                    for value in gap.get("related_evidence_ids", [])
                    if str(value).startswith(("NODE-", "EVID-", "SRC-"))
                }
            )
            impacts = _counterfactual_impacts(missing, affected, counterfactuals or [])
            digest = hashlib.sha256(
                json.dumps([missing, affected], ensure_ascii=False).encode("utf-8")
            ).hexdigest()[:16].upper()
            gap_id = f"GAP-{digest}"
            if gap_id in seen_gap_ids:
                continue
            seen_gap_ids.add(gap_id)
            results.append(
                EvidenceCollectionItem(
                    gap_id=gap_id,
                    missing_evidence=missing,
                    why_important=(
                        f"该材料影响：{'、'.join(affected)}。系统只说明可能影响，"
                        "不预设尚未取得证据的内容。"
                    ),
                    affected_conclusions=affected,
                    priority=priority,
                    due_at=nearest_due,
                    lawful_collection_methods=methods,
                    alternative_evidence=alternatives,
                    fallback_if_unavailable=fallback,
                    counterfactual_impacts=impacts,
                    related_fact_ids=fact_ids,
                    related_evidence_ids=evidence_ids,
                )
            )
        return results


def _priority(value: str) -> TaskPriority:
    return {
        "P0": TaskPriority.HIGH,
        "P1": TaskPriority.MEDIUM,
        "P2": TaskPriority.LOW,
    }.get(value.upper(), TaskPriority.MEDIUM)


def _collection_guidance(missing: str) -> tuple[list[str], list[str], str]:
    if any(value in missing for value in ("监控", "视频", "轨迹", "信号")):
        return (
            ["向有权管理单位依法提出保存/调取申请", "保存申请回执和原始文件哈希"],
            ["连续行车记录仪原文件", "现场图、信号配时记录、目击者依法形成的陈述"],
            "无法取得时，保持相关轨迹和信号事实为未核实，并扩大责任假设区间。",
        )
    if any(value in missing for value in ("登记", "号牌", "合格证", "CCC", "车辆")):
        return (
            ["向登记管理部门或车辆所有人依法核验", "核对实车、合格证和CCC一致性"],
            ["销售凭证、车辆铭牌照片、官方登记查询记录", "车辆属性鉴定意见"],
            "无法取得时，不把技术参数超标自动等同为机动车，赔偿路径保持待定。",
        )
    if "鉴定" in missing:
        return (
            ["依法申请复制完整鉴定意见及资质材料", "在适用期限内提出书面异议"],
            ["检验报告、检材清单、技术标准版本、鉴定人资质"],
            "无法取得时，鉴定相关结论仅作争议事实，不支撑确定性结论。",
        )
    return (
        ["通过合法、自愿、可审计的方式收集并保留来源记录"],
        ["同一事实的其他独立书证、视听资料或官方记录"],
        "无法取得时，将受影响结论降级为不确定并提交人工复核。",
    )


def _counterfactual_impacts(
    missing: str,
    affected: list[str],
    counterfactuals: list[dict[str, Any]],
) -> list[CounterfactualImpact]:
    matches = [
        item
        for item in counterfactuals
        if str(item.get("evidence_type", "")) in missing
        or missing in str(item.get("evidence_type", ""))
    ]
    impacts: list[CounterfactualImpact] = []
    for item in matches:
        for branch in item.get("branches", []):
            impacts.append(
                CounterfactualImpact(
                    condition=str(branch.get("condition", "若取得的证据支持该条件")),
                    affected_conclusions=affected,
                    likely_direction=(
                        "提高："
                        + "、".join(branch.get("increases_hypotheses", []))
                        + "；降低："
                        + "、".join(branch.get("decreases_hypotheses", []))
                    ),
                    caveat="这是条件影响说明，不代表证据内容已经存在或被证实。",
                )
            )
    if not impacts:
        impacts = [
            CounterfactualImpact(
                condition="若补充证据支持现有假设A",
                affected_conclusions=affected,
                likely_direction="假设A的相对权重可能上升，竞争假设相对下降。",
                caveat="不得据此预设或捏造证据内容。",
            ),
            CounterfactualImpact(
                condition="若补充证据支持竞争假设B或与现有材料冲突",
                affected_conclusions=affected,
                likely_direction="假设B或争议状态的权重可能上升。",
                caveat="必须先验证证据真实性、来源和与案件的关联性。",
            ),
        ]
    return impacts
