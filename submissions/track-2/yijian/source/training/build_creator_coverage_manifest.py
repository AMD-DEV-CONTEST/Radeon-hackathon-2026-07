# -*- coding: utf-8 -*-
"""Build an evidence-bound taxonomy overlay for the signed 64-unit release."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

import expert_corpus
import gold_review_workflow as workflow


ENDGAME_EVIDENCE = {
    "gold-batch-04-bv1yc41177ux-000000585000": (
        "B14先长保留一路立的强制性，核心是官子阶段的先后次序与先手保留；"
        "该映射只补充主题分类，不改变已签发结论。"
    ),
    "gold-pilot-bv1qekr6qes7-000000686120": (
        "S17与R18比较的是先手是否真正兑现，以及应手后是否仍需补棋；"
        "这是官子先手判断，映射不新增坐标、数值或胜负结论。"
    ),
}


def normalized_themes(unit: dict[str, Any]) -> set[str]:
    return {
        expert_corpus.CREATOR_THEME_ALIASES.get(str(value), str(value))
        for value in ((unit.get("pedagogy") or {}).get("competencies") or [])
    } & expert_corpus.REQUIRED_CREATOR_THEMES


def counts(units: list[dict[str, Any]], additions: dict[str, set[str]] | None = None) -> dict[str, int]:
    result: Counter[str] = Counter()
    for unit in units:
        themes = normalized_themes(unit) | (additions or {}).get(str(unit.get("id") or ""), set())
        result.update(themes)
    return {name: result[name] for name in sorted(expert_corpus.REQUIRED_CREATOR_THEMES)}


def build(units_path: Path) -> dict[str, Any]:
    units = workflow.read_jsonl(units_path)
    workflow.require(len(units) == 64, f"coverage manifest requires exactly 64 units, got {len(units)}")
    unit_by_id = {str(unit.get("id") or ""): unit for unit in units}
    mappings = []
    additions: dict[str, set[str]] = {}
    for unit_id, basis in ENDGAME_EVIDENCE.items():
        workflow.require(unit_id in unit_by_id, f"coverage evidence unit missing: {unit_id}")
        unit = unit_by_id[unit_id]
        workflow.require(unit.get("trainingEligible") is True, f"coverage evidence is not training eligible: {unit_id}")
        conclusion = str((unit.get("pedagogy") or {}).get("conclusion") or "")
        workflow.require(conclusion, f"coverage evidence conclusion missing: {unit_id}")
        mappings.append({
            "unitId": unit_id,
            "addThemes": ["endgame"],
            "teacherConclusionSha256": hashlib.sha256(conclusion.encode("utf-8")).hexdigest(),
            "evidenceBasis": basis,
            "sourceFields": ["pedagogy.conclusion", "pedagogy.mechanism", "pedagogy.tradeoff"],
        })
        additions[unit_id] = {"endgame"}
    before = counts(units)
    after = counts(units, additions)
    workflow.require(before["endgame"] == 2, f"unexpected pre-mapping endgame count: {before['endgame']}")
    workflow.require(after["endgame"] == 4, f"endgame gate not satisfied: {after['endgame']}")
    workflow.require(all(after[name] >= 4 for name in expert_corpus.REQUIRED_CREATOR_THEMES), f"formal theme gate failed: {after}")
    return {
        "schemaVersion": expert_corpus.COVERAGE_MANIFEST_SCHEMA,
        "productName": "弈鉴LoRA",
        "releaseSha256": expert_corpus.sha256_file(units_path),
        "policy": "evidence-bound additive taxonomy; signed unit content remains immutable",
        "trainingContentChanged": False,
        "approvalContentHashesChanged": False,
        "mappings": mappings,
        "themeCountsBefore": before,
        "themeCountsAfter": after,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--units", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    value = build(args.units.resolve())
    workflow.write_json(args.output.resolve(), value)
    print(json.dumps({
        "output": str(args.output),
        "mappings": len(value["mappings"]),
        "themeCountsAfter": value["themeCountsAfter"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
