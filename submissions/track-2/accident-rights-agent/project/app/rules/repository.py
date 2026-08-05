"""Load, integrity-check, and select date/jurisdiction-aware rule definitions."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from app.schemas.rules import (
    RuleDefinition,
    RuleSelectionResult,
    RuleSelectionStatus,
    rule_content_hash,
)


class RuleIntegrityError(ValueError):
    pass


class RuleRepository:
    def __init__(
        self,
        path: Path | str = Path("config/rules/national_rules.json"),
    ):
        self.path = Path(path)
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        if raw.get("schema_version") != 1:
            raise ValueError("Unsupported rule-pack schema version.")
        self.rules = [RuleDefinition.model_validate(item) for item in raw["rules"]]
        for item, rule in zip(raw["rules"], self.rules, strict=True):
            actual = rule_content_hash(item)
            if actual != rule.content_hash:
                raise RuleIntegrityError(
                    f"Rule content hash mismatch: {rule.rule_id} "
                    f"expected={rule.content_hash} actual={actual}"
                )
        identifiers = [item.rule_id for item in self.rules]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("Rule IDs must be unique.")

    def get(
        self,
        rule_id: str,
        *,
        as_of_date: date,
        jurisdiction: str = "CN",
    ) -> RuleDefinition:
        matches = [item for item in self.rules if item.rule_id == rule_id]
        if not matches:
            raise KeyError(rule_id)
        rule = matches[0]
        if not rule.applies(as_of_date=as_of_date, jurisdiction=jurisdiction):
            raise ValueError(
                f"Rule {rule_id} is not applicable in {jurisdiction} "
                f"as of {as_of_date.isoformat()}."
            )
        return rule

    def select(
        self,
        *,
        rule_type: str,
        as_of_date: date,
        jurisdiction: str = "CN",
    ) -> RuleSelectionResult:
        applicable = [
            item
            for item in self.rules
            if item.rule_type == rule_type
            and item.applies(as_of_date=as_of_date, jurisdiction=jurisdiction)
        ]
        if not applicable:
            return RuleSelectionResult(
                status=RuleSelectionStatus.NOT_FOUND,
                reason=(
                    f"No effective {rule_type} rule for {jurisdiction} "
                    f"on {as_of_date.isoformat()}."
                ),
            )
        if len(applicable) > 1:
            return RuleSelectionResult(
                status=RuleSelectionStatus.CONFLICT,
                conflicting_rule_ids=sorted(item.rule_id for item in applicable),
                reason="Multiple effective rules matched; no rule was silently selected.",
            )
        return RuleSelectionResult(
            status=RuleSelectionStatus.SELECTED,
            selected_rule=applicable[0],
            reason="One effective date- and jurisdiction-matched rule selected.",
        )

    def conflicts(
        self,
        *,
        as_of_date: date,
        jurisdiction: str = "CN",
    ) -> dict[str, list[str]]:
        grouped: dict[str, list[str]] = {}
        for rule in self.rules:
            if rule.applies(as_of_date=as_of_date, jurisdiction=jurisdiction):
                grouped.setdefault(rule.rule_type, []).append(rule.rule_id)
        return {
            rule_type: sorted(rule_ids)
            for rule_type, rule_ids in grouped.items()
            if len(rule_ids) > 1
        }
