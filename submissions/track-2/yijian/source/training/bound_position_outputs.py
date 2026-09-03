#!/usr/bin/env python3
"""Apply the same deterministic evidence fallback to raw position-model outputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import validate_award_runtime as validator


SCHEMA = "yijian-bounded-position-output-v1"


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def metric(candidate: dict[str, Any], key: str) -> str:
    value = candidate.get(key)
    if value is None:
        return "未登记"
    if key.endswith("Winrate"):
        return f"{float(value) * 100:.2f}%"
    return f"{float(value):.2f}目"


def deterministic_fallback(case: dict[str, Any]) -> str:
    evidence = case.get("evidence") or {}
    actual = str(evidence.get("actualMove") or "")
    best = str(evidence.get("bestMove") or "")
    color = "黑棋" if evidence.get("toPlay") == "B" else "白棋" if evidence.get("toPlay") == "W" else "当前一方"
    katago = evidence.get("katago") or {}
    candidates = katago.get("candidates") or []
    best_info = next((row for row in candidates if str(row.get("move") or "") == best), candidates[0] if candidates else {})
    actual_info = katago.get("actualMoveAnalysis") or next(
        (row for row in candidates if str(row.get("move") or "") == actual), {}
    )
    target = case.get("target") or evidence.get("questionTarget")
    if target == "actual":
        answer = (
            f"轮到{color}，实战候选是 {actual}。规则重放确认该手合法；"
            f"KataGo 对该手的本方胜率为 {metric(actual_info, 'subjectWinrate')}，"
            f"本方目差为 {metric(actual_info, 'subjectScoreLead')}。"
            "现有证据只支持当前局面的合法性与引擎评估，不额外断言未登记的局部机制。"
        )
    elif target == "comparison":
        answer = (
            f"轮到{color}，同一回合应比较实战 {actual} 与首选 {best}。"
            f"实战手的本方胜率/目差为 {metric(actual_info, 'subjectWinrate')} / {metric(actual_info, 'subjectScoreLead')}；"
            f"首选为 {metric(best_info, 'subjectWinrate')} / {metric(best_info, 'subjectScoreLead')}。"
            "取舍仅限这次 128 visits 登记结果，不外推整盘胜负。"
        )
    else:
        answer = (
            f"轮到{color}，KataGo 首选 {best}。其本方胜率为 {metric(best_info, 'subjectWinrate')}，"
            f"本方目差为 {metric(best_info, 'subjectScoreLead')}。"
            "现有证据没有提供足够的局部机制说明，因此不补写其他坐标或死活结论。"
        )
    return json.dumps({"answer": answer, "followUps": ["是否继续查看登记的 KataGo 主变化？"]}, ensure_ascii=False)


def build(cases_path: Path, raw_path: Path, output_path: Path) -> dict[str, Any]:
    cases = validator.read_jsonl(cases_path)
    raw_map, raw_report = validator.output_map(raw_path)
    raw_validation = validator.validate_positions(cases, raw_map)
    invalid = {
        row["caseId"]: row
        for row in raw_validation["details"]
        if not row["faithful"]
    }
    results = []
    for case in cases:
        case_id = str(case["caseId"])
        source = dict(raw_map.get(case_id) or {"caseId": case_id})
        if case_id in invalid:
            source["rawAnswerSha256"] = hashlib.sha256(str(source.get("answer") or "").encode("utf-8")).hexdigest()
            source["answer"] = deterministic_fallback(case)
            source["succeeded"] = True
            source["fallbackApplied"] = True
            source["fallbackReason"] = {
                "jsonValid": invalid[case_id]["jsonValid"],
                "illegalCoordinates": invalid[case_id]["illegalCoordinates"],
                "wrongBestClaim": invalid[case_id]["wrongBestClaim"],
                "perspectiveValid": invalid[case_id]["perspectiveValid"],
            }
        else:
            source["fallbackApplied"] = False
        results.append(source)
    final_map = {row["caseId"]: row for row in results}
    final_validation = validator.validate_positions(cases, final_map)
    if final_validation["severeContradictions"] or final_validation["structuredOutputSuccess"] != 1:
        raise ValueError("deterministic fallback did not produce fully bounded outputs")
    report = {
        "schemaVersion": SCHEMA, "model": raw_report.get("model"),
        "inputSha256": file_hash(cases_path), "rawOutputSha256": file_hash(raw_path),
        "cases": len(results), "succeeded": len(results), "successRate": 1.0,
        "rawValidation": {
            "structuredOutputSuccess": raw_validation["structuredOutputSuccess"],
            "evidenceFaithfulness": raw_validation["evidenceFaithfulness"],
            "severeContradictions": raw_validation["severeContradictions"],
        },
        "fallbackCount": len(invalid),
        "finalValidation": {
            "structuredOutputSuccess": final_validation["structuredOutputSuccess"],
            "evidenceFaithfulness": final_validation["evidenceFaithfulness"],
            "severeContradictions": final_validation["severeContradictions"],
        },
        "results": results,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(output_path.name + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, output_path)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = build(args.cases, args.raw, args.output)
    print(json.dumps({
        "model": report["model"], "cases": report["cases"],
        "fallbackCount": report["fallbackCount"],
        "rawValidation": report["rawValidation"],
        "finalValidation": report["finalValidation"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
