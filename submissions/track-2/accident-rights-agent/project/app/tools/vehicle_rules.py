"""Deterministic, versioned electric-bicycle parameter comparison.

This tool reports technical-standard compliance only. It never converts a
non-compliant parameter into a legal motor-vehicle classification.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any

from app.schemas.business import (
    ParameterComparison,
    TechnicalComparisonStatus,
)

DEFAULT_RULES_PATH = Path("config/vehicle_parameter_rules.json")


class VehicleParameterRuleEngine:
    def __init__(self, rules_path: Path | str = DEFAULT_RULES_PATH):
        self.rules_path = Path(rules_path)
        payload = json.loads(self.rules_path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != 1:
            raise ValueError("Unsupported vehicle-rule schema version.")
        required = {
            "ruleset_id",
            "jurisdiction",
            "effective_date",
            "source_law_id",
            "rules",
        }
        missing = required - set(payload)
        if missing:
            raise ValueError(f"Vehicle ruleset lacks fields: {sorted(missing)}")
        if not isinstance(payload["rules"], list) or not payload["rules"]:
            raise ValueError("Vehicle ruleset must contain at least one rule.")
        self.payload = payload

    @property
    def ruleset_id(self) -> str:
        return str(self.payload["ruleset_id"])

    def compare(
        self,
        facts: list[dict[str, Any]],
        *,
        accident_date: date | None = None,
        disputed_fact_ids: set[str] | None = None,
    ) -> list[ParameterComparison]:
        disputed_fact_ids = disputed_fact_ids or set()
        effective = date.fromisoformat(self.payload["effective_date"])
        expired = (
            date.fromisoformat(self.payload["expiry_date"])
            if self.payload.get("expiry_date")
            else None
        )
        applicable = accident_date is None or (
            accident_date >= effective and (expired is None or accident_date < expired)
        )
        all_text = " ".join(_fact_text(item) for item in facts)
        results: list[ParameterComparison] = []
        for rule in self.payload["rules"]:
            matching = [
                item
                for item in facts
                if any(
                    alias.lower() in _fact_text(item).lower()
                    for alias in rule["aliases"]
                )
            ]
            if not applicable:
                status = TechnicalComparisonStatus.NOT_APPLICABLE
                observed: str | float | int | bool | None = (
                    "；".join(str(item.get("value", "")) for item in matching) or None
                )
                explanation = (
                    f"事故日期不在规则集 {self.ruleset_id} 的有效期内；"
                    "必须选择事故发生时有效的标准版本。"
                )
            else:
                status, observed, explanation = self._evaluate(rule, matching, all_text)
                if disputed_fact_ids & {
                    str(item.get("fact_id", "")) for item in matching
                }:
                    status = TechnicalComparisonStatus.CONFLICTING
                    explanation = (
                        f"{explanation} 相关事实已标记 disputed，"
                        "不得据此形成确定性技术结论。"
                    )
                distinct = {
                    _normalized_observed(item.get("value"))
                    for item in matching
                    if item.get("value") not in (None, "")
                }
                if len(distinct) > 1 and rule["comparison"] not in {
                    "anti_tamper",
                    "modification",
                }:
                    status = TechnicalComparisonStatus.CONFLICTING
                    explanation = f"同一参数存在多个不一致观测：{sorted(distinct)}。"
            results.append(
                ParameterComparison(
                    parameter=rule["parameter"],
                    display_name=rule["display_name"],
                    observed_value=observed,
                    standard_requirement=rule["requirement"],
                    status=status,
                    explanation=explanation,
                    fact_ids=sorted(
                        {
                            str(item["fact_id"])
                            for item in matching
                            if item.get("fact_id")
                        }
                    ),
                    evidence_ids=sorted(
                        {
                            str(node_id)
                            for item in matching
                            for node_id in item.get("source_node_ids", [])
                        }
                    ),
                    jurisdiction=self.payload["jurisdiction"],
                    effective_date=self.payload["effective_date"],
                    expiry_date=self.payload.get("expiry_date"),
                    source_law_id=self.payload["source_law_id"],
                    source_article=rule.get("source_article"),
                )
            )
        return results

    def _evaluate(
        self,
        rule: dict[str, Any],
        matching: list[dict[str, Any]],
        all_text: str,
    ) -> tuple[TechnicalComparisonStatus, Any, str]:
        if not matching:
            return (
                TechnicalComparisonStatus.UNKNOWN,
                None,
                "材料中未找到可追溯的该参数观测。",
            )
        combined = "；".join(
            str(item.get("value") or item.get("statement") or "") for item in matching
        )
        comparison = rule["comparison"]
        if comparison == "max_numeric":
            values = [
                value
                for item in matching
                if (value := _numeric_value(item.get("value"), rule.get("unit")))
                is not None
            ]
            if not values:
                return (
                    TechnicalComparisonStatus.UNKNOWN,
                    combined,
                    "已识别材料，但未能解析为可比较的数值。",
                )
            observed = max(values)
            threshold = float(rule["threshold"])
            status = (
                TechnicalComparisonStatus.COMPLIANT
                if observed <= threshold
                else TechnicalComparisonStatus.NON_COMPLIANT
            )
            return (
                status,
                observed,
                f"观测值 {observed:g} {rule.get('unit') or ''} "
                f"{'不超过' if status is TechnicalComparisonStatus.COMPLIANT else '超过'}"
                f"阈值 {threshold:g} {rule.get('unit') or ''}。"
                "该结果仅表示技术标准符合性。",
            )
        if comparison == "battery_dependent_mass":
            values = [
                value
                for item in matching
                if (value := _numeric_value(item.get("value"), "kg")) is not None
            ]
            if not values:
                return (
                    TechnicalComparisonStatus.UNKNOWN,
                    combined,
                    "整车质量无法解析为数值。",
                )
            observed = max(values)
            lead_acid = "铅酸" in all_text
            battery_known = lead_acid or any(
                keyword in all_text for keyword in ("锂电", "锂离子", "钠离子")
            )
            if not battery_known and observed > float(rule["threshold"]):
                return (
                    TechnicalComparisonStatus.UNKNOWN,
                    observed,
                    "质量超过非铅酸阈值，但电池类型未知，无法选择55 kg或63 kg阈值。",
                )
            threshold = float(
                rule["lead_acid_threshold"] if lead_acid else rule["threshold"]
            )
            status = (
                TechnicalComparisonStatus.COMPLIANT
                if observed <= threshold
                else TechnicalComparisonStatus.NON_COMPLIANT
            )
            return (
                status,
                observed,
                f"按{'铅酸' if lead_acid else '非铅酸'}车型阈值 "
                f"{threshold:g} kg 比较；结果仅表示技术标准符合性。",
            )
        if comparison == "record_only":
            return (
                TechnicalComparisonStatus.UNKNOWN,
                combined,
                "该项已记录，但规则明确禁止仅凭该字段自动形成符合性或法律属性结论。",
            )
        if comparison == "presence_positive":
            negative = any(
                marker in combined
                for marker in ("无合格证", "未认证", "认证失效", "不一致", "伪造")
            )
            return (
                (
                    TechnicalComparisonStatus.NON_COMPLIANT
                    if negative
                    else TechnicalComparisonStatus.COMPLIANT
                ),
                combined,
                (
                    "材料显示证书缺失、失效或与实车不一致。"
                    if negative
                    else "材料中存在合格证/CCC记录，仍需核验真伪与车型一致性。"
                ),
            )
        if comparison == "conditional_boolean":
            has_pedal = any(
                marker in combined for marker in ("有脚踏", "具备脚踏", "保留脚踏")
            )
            no_pedal = any(
                marker in combined for marker in ("无脚踏", "拆除脚踏", "不具备脚踏")
            )
            pedal_assist = "电助力" in all_text
            electric_only = "仅电驱动" in all_text
            if has_pedal:
                return (
                    TechnicalComparisonStatus.COMPLIANT,
                    True,
                    "材料显示具备脚踏骑行装置。",
                )
            if no_pedal and pedal_assist:
                return (
                    TechnicalComparisonStatus.NON_COMPLIANT,
                    False,
                    "材料显示电助力车型缺少脚踏骑行装置。",
                )
            if no_pedal and electric_only:
                return (
                    TechnicalComparisonStatus.NOT_APPLICABLE,
                    False,
                    "仅电驱动车型可选择设置脚踏装置，缺少脚踏本身不构成不符合。",
                )
            return (
                TechnicalComparisonStatus.UNKNOWN,
                combined,
                "脚踏状态或驱动模式不足，无法进行条件比较。",
            )
        if comparison == "anti_tamper":
            altered = any(
                marker in combined
                for marker in ("解除限速", "剪线", "解码", "改装控制器", "提速")
            )
            protected = any(
                marker in combined
                for marker in ("防篡改合格", "不可解除限速", "限速器封装")
            )
            if altered:
                return (
                    TechnicalComparisonStatus.NON_COMPLIANT,
                    combined,
                    "材料显示存在解除限速或控制器/限速器篡改迹象。",
                )
            if protected:
                return (
                    TechnicalComparisonStatus.COMPLIANT,
                    combined,
                    "材料明确记载防篡改检查符合要求。",
                )
            return (
                TechnicalComparisonStatus.UNKNOWN,
                combined,
                "仅提及防篡改部件，缺少检测结论。",
            )
        if comparison == "modification":
            not_modified = any(
                marker in combined for marker in ("未改装", "无改装", "保持原厂")
            )
            modified = any(
                marker in combined
                for marker in (
                    "解除限速",
                    "剪线提速",
                    "更换控制器",
                    "加装电池",
                    "存在改装",
                )
            )
            if modified:
                return (
                    TechnicalComparisonStatus.NON_COMPLIANT,
                    True,
                    "材料显示存在改装，需核验改装部件与事故原因的具体联系。",
                )
            if not_modified:
                return (
                    TechnicalComparisonStatus.COMPLIANT,
                    False,
                    "材料明确记载未发现改装。",
                )
            return (
                TechnicalComparisonStatus.UNKNOWN,
                combined,
                "材料不足以确认是否改装。",
            )
        raise ValueError(f"Unsupported comparison type: {comparison}")


def _fact_text(fact: dict[str, Any]) -> str:
    return " ".join(
        str(fact.get(key, "")) for key in ("statement", "subject", "predicate", "value")
    )


def _numeric_value(value: Any, target_unit: str | None) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value or "")
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    parsed = float(match.group(0))
    lowered = text.lower().replace(" ", "")
    if target_unit == "m" and ("cm" in lowered or "厘米" in lowered):
        parsed /= 100
    if target_unit == "W" and ("kw" in lowered or "千瓦" in lowered):
        parsed *= 1000
    return round(parsed, 6)


def _normalized_observed(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).lower()
