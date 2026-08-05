"""Conservative conflict detection for single-valued observations."""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict

from app.schemas.evidence import EvidenceConflict, Fact


SINGLE_VALUED_PREDICATES = {
    "信号灯状态",
    "行驶方向",
    "驶入方向",
    "车道",
    "所在车道",
    "是否逆行",
    "车辆类型",
    "号牌类型",
    "登记类型",
    "碰撞位置",
    "接触位置",
    "颜色",
    "送达日期",
    "事故时间",
    "事故地点",
}


def detect_conflicts(facts: list[Fact], *, min_confidence: float = 0.45) -> list[EvidenceConflict]:
    groups: dict[tuple[str, str], list[Fact]] = defaultdict(list)
    for fact in facts:
        if fact.confidence < min_confidence:
            continue
        predicate = _normalize(fact.predicate)
        if predicate not in {_normalize(value) for value in SINGLE_VALUED_PREDICATES}:
            continue
        groups[(_normalize(fact.subject), predicate)].append(fact)

    conflicts: list[EvidenceConflict] = []
    for (subject, predicate), candidates in groups.items():
        values: dict[str, list[Fact]] = defaultdict(list)
        for fact in candidates:
            values[_normalize(fact.value)].append(fact)
        if len(values) <= 1:
            continue
        involved = tuple(sorted(fact.fact_id for fact in candidates))
        raw_values = sorted({fact.value for fact in candidates})
        digest = hashlib.sha256("\x1f".join(involved).encode("utf-8")).hexdigest()
        conflicts.append(
            EvidenceConflict(
                conflict_id=f"CONFLICT-{digest[:16].upper()}",
                case_id=candidates[0].case_id,
                subject=subject,
                predicate=predicate,
                fact_ids=involved,
                description=(
                    f"同一主体的单值字段出现不一致观测：{', '.join(raw_values)}。"
                    "需回看原始证据或人工核验。"
                ),
            )
        )
    return conflicts


def _normalize(value: str) -> str:
    return re.sub(r"[\s，。；：、,.!?！？:;\"'“”‘’（）()_-]+", "", value).lower()
