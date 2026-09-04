from __future__ import annotations

import json
from datetime import date

from app.rules.repository import RuleRepository
from app.schemas.rules import rule_content_hash


def test_rule_pack_selects_effective_case_date_and_has_no_conflicts():
    rules = RuleRepository()
    selected = rules.select(
        rule_type="deadline.accident_determination_review",
        as_of_date=date(2026, 7, 20),
        jurisdiction="CN/Shanghai",
    )
    assert selected.status.value == "selected"
    assert selected.selected_rule.rule_id == (
        "RULE-CN-DEADLINE-ACCIDENT-REVIEW-2017"
    )
    assert rules.conflicts(as_of_date=date(2026, 7, 20)) == {}


def test_rule_conflict_is_reported_not_silently_overwritten(tmp_path):
    raw = json.loads(
        open("config/rules/national_rules.json", encoding="utf-8").read()
    )
    duplicate = dict(raw["rules"][0])
    duplicate["rule_id"] = "RULE-CN-DEADLINE-ACCIDENT-REVIEW-CONFLICT"
    duplicate["content_hash"] = rule_content_hash(duplicate)
    raw["rules"].append(duplicate)
    path = tmp_path / "conflict.json"
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    result = RuleRepository(path).select(
        rule_type="deadline.accident_determination_review",
        as_of_date=date(2026, 7, 20),
    )
    assert result.status.value == "conflict"
    assert len(result.conflicting_rule_ids) == 2
