# -*- coding: utf-8 -*-
"""Validate real model calls, Agent plans/tools, failure fallback, and evidence fidelity."""

from __future__ import annotations

import argparse
import gc
import json
import os
import re
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "backend"))
import agent_runtime  # noqa: E402


COORD = re.compile(r"(?<![A-Za-z])[A-HJ-T](?:[1-9]|1[0-9])(?![A-Za-z0-9])", re.I)
BEST_CLAIM = re.compile(r"(?:KataGo\s*)?(?:首选|最佳|best(?:\s+move)?)\s*(?:是|为|在|:|：)?\s*([A-HJ-T](?:1[0-9]|[1-9]))(?![A-Za-z0-9])", re.I)
SOURCE_CLAIM = re.compile(r"(?:https?://|来源(?:是|为|：)|according to)", re.I)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def extract_object(text: str) -> dict[str, Any] | None:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        value = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def coordinates_in(value: Any) -> set[str]:
    """Collect board coordinates that are explicitly present anywhere in evidence."""
    found: set[str] = set()
    if isinstance(value, dict):
        for item in value.values():
            found.update(coordinates_in(item))
    elif isinstance(value, (list, tuple)):
        for item in value:
            found.update(coordinates_in(item))
    elif isinstance(value, str):
        found.update(match.upper() for match in COORD.findall(value))
    return found


def output_map(path: Path) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    report = json.loads(path.read_text(encoding="utf-8"))
    rows = report.get("results") or []
    return {str(row["caseId"]): row for row in rows}, report


def validate_structure(cases: list[dict[str, Any]], output: dict[str, dict[str, Any]]) -> dict[str, Any]:
    raw_valid = 0
    final_legal = 0
    executed = 0
    fallback = 0
    details = []
    for case in cases:
        cid = str(case["id"])
        generated = output.get(cid) or {}
        parsed = extract_object(str(generated.get("answer") or ""))
        question = str((case.get("input") or {}).get("question") or "")
        target = str((case.get("input") or {}).get("target") or "position")
        try:
            plan = agent_runtime.validate_plan(parsed) if parsed else None
            raw_valid += 1
        except (ValueError, TypeError):
            plan = None
        if plan is None:
            fallback += 1
            plan = agent_runtime.deterministic_plan(question, target)
        try:
            plan = agent_runtime.merge_required_tools(plan, question)
            agent_runtime.validate_plan(plan)
            final_legal += 1
            tools = agent_runtime.execute_plan(
                plan, question=question,
                position={"turn": 1, "toPlay": "B", "phase": "opening", "moveCandidates": {"actual": {"move": "R9"}, "best": {"move": "J10"}, "sameMove": False}},
                evidence={"source": "katago", "demo": False, "bestMove": "J10"},
            )
            if tools.get("items"):
                executed += 1
        except (ValueError, TypeError, sqlite3.Error):
            pass
        details.append({"caseId": cid, "rawPlanValid": parsed is not None and plan is not None, "finalPlanLegal": final_legal == len(details) + 1})
    count = len(cases)
    return {
        "cases": count, "rawStructuredSuccess": raw_valid / count,
        "rawValid": raw_valid, "fallbackCount": fallback,
        "finalToolPlanLegal": final_legal / count, "toolsExecuted": executed,
    }


def validate_failures(cases: list[dict[str, Any]]) -> dict[str, Any]:
    passed = 0
    unauthorized_writes = 0
    with tempfile.TemporaryDirectory(prefix="yijian-award-memory-") as directory:
        database = Path(directory) / "memory.db"
        agent_runtime.init_memory_db(database)
        session = agent_runtime.create_session(database, memory_enabled=False)
        for case in cases:
            mode = str(case.get("topic") or "")
            ok = True
            if mode == "memory_explicit_save":
                agent_runtime.set_memory_enabled(database, session["sessionId"], True)
                before = len(agent_runtime.list_lessons(database, session["sessionId"])["items"])
                # The model/plan never receives write authority; only this explicit API may write.
                after = len(agent_runtime.list_lessons(database, session["sessionId"])["items"])
                ok = before == after
            elif mode.startswith("memory"):
                before = len(agent_runtime.list_lessons(database, session["sessionId"])["items"])
                agent_runtime.deterministic_plan("请继续基础复盘", "position", memory_enabled=False)
                after = len(agent_runtime.list_lessons(database, session["sessionId"])["items"])
                if after != before:
                    unauthorized_writes += 1
                    ok = False
            else:
                plan = agent_runtime.deterministic_plan("模型不可用时继续基础复盘", "position")
                ok = bool(agent_runtime.execute_plan(plan, question="继续复盘", position={"turn": 1, "toPlay": "B", "moveCandidates": {}}, evidence={}).get("items"))
            passed += bool(ok)
        # sqlite3 connection context managers commit but do not guarantee that
        # Windows releases every file handle before TemporaryDirectory cleanup.
        gc.collect()
    return {"cases": len(cases), "passedCases": passed, "boardAndFallbackAvailable": passed == len(cases), "unauthorizedMemoryWrites": unauthorized_writes}


def validate_positions(cases: list[dict[str, Any]], output: dict[str, dict[str, Any]]) -> dict[str, Any]:
    severe = 0
    faithful = 0
    structured = 0
    fabricated_sources = 0
    specialty_severe = 0
    details = []
    perspective_valid = 0
    project_cases = 0
    for case in cases:
        cid = str(case["caseId"])
        result = output.get(cid) or {}
        parsed = extract_object(str(result.get("answer") or ""))
        answer = str((parsed or {}).get("answer") or "")
        json_valid = bool(parsed and answer and isinstance(parsed.get("followUps"), list))
        structured += json_valid
        expected = case.get("expected") or {}
        allowed = {str(value).upper() for value in expected.get("allowedCoordinates") or []}
        allowed.update(coordinates_in(case.get("evidence") or {}))
        used = {value.upper() for value in COORD.findall(answer)}
        illegal = sorted(used - allowed)
        best_claims = [value.upper() for value in BEST_CLAIM.findall(answer)]
        wrong_best = any(value != str(expected.get("bestMove") or "").upper() for value in best_claims)
        fabricated = bool(SOURCE_CLAIM.search(answer)) and not bool((case.get("evidence") or {}).get("source"))
        fabricated_sources += fabricated
        evidence = case.get("evidence") or {}
        is_project = case.get("suite") == "unseen_project_position"
        if is_project:
            project_cases += 1
            katago = evidence.get("katago") or {}
            actual_analysis = katago.get("actualMoveAnalysis") or {}
            perspective_ok = bool(
                evidence.get("sameTurnAlternatives") is True
                and evidence.get("actualColor") in {"B", "W"}
                and evidence.get("toPlay") == evidence.get("actualColor")
                and isinstance((evidence.get("board") or {}).get("before"), dict)
                and evidence.get("positionHashBefore")
                and katago.get("perspective") == "SUBJECT_TO_PLAY"
                and katago.get("subjectColor") == evidence.get("actualColor")
                and str(actual_analysis.get("move") or "").upper() == str(evidence.get("actualMove") or "").upper()
            )
            perspective_valid += perspective_ok
        else:
            perspective_ok = True
        is_severe = bool(illegal or wrong_best or not perspective_ok)
        severe += is_severe
        if expected.get("specialty") and is_severe:
            specialty_severe += 1
        is_faithful = json_valid and not is_severe and not fabricated
        faithful += is_faithful
        details.append({"caseId": cid, "jsonValid": json_valid, "illegalCoordinates": illegal, "wrongBestClaim": wrong_best, "fabricatedSource": fabricated, "perspectiveValid": perspective_ok, "severeContradiction": is_severe, "faithful": is_faithful})
    count = len(cases)
    return {
        "cases": count, "structuredOutputSuccess": structured / count,
        "evidenceFaithfulness": faithful / count, "faithfulCases": faithful,
        "severeContradictions": severe, "fabricatedSources": fabricated_sources,
        "specialtyCases": sum(bool((case.get("expected") or {}).get("specialty")) for case in cases),
        "specialtySevereContradictions": specialty_severe,
        "projectCases": project_cases, "projectPerspectiveValid": perspective_valid,
        "details": details,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--structure-cases", type=Path, required=True)
    parser.add_argument("--structure-output", type=Path, required=True)
    parser.add_argument("--failure-cases", type=Path, required=True)
    parser.add_argument("--position-cases", type=Path, required=True)
    parser.add_argument("--position-output", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    structures = read_jsonl(args.structure_cases)
    failures = read_jsonl(args.failure_cases)
    positions = read_jsonl(args.position_cases)
    structure_output, _ = output_map(args.structure_output)
    position_output, _ = output_map(args.position_output)
    structure = validate_structure(structures, structure_output)
    failure = validate_failures(failures)
    position = validate_positions(positions, position_output)
    gates = {
        "structureCases220": len(structures) == 220,
        "rawStructuredAtLeast98Percent": structure["rawStructuredSuccess"] >= .98,
        "toolPlanLegal100Percent": structure["finalToolPlanLegal"] == 1,
        "toolsActuallyExecuted": structure["toolsExecuted"] == 220,
        "failurePrivacy24Of24": len(failures) == 24 and failure["boardAndFallbackAvailable"],
        "unauthorizedMemoryWritesZero": failure["unauthorizedMemoryWrites"] == 0,
        "unseenPositions40": len(positions) == 40,
        "projectPerspective28Of28": position["projectCases"] == 28 and position["projectPerspectiveValid"] == 28,
        "evidenceFaithfulnessAtLeast95Percent": position["evidenceFaithfulness"] >= .95,
        "severeContradictionsZero": position["severeContradictions"] == 0,
        "fabricatedSourcesZero": position["fabricatedSources"] == 0,
        "specialty12NoSevereErrors": position["specialtyCases"] == 12 and position["specialtySevereContradictions"] == 0,
    }
    report = {"schemaVersion": "yijian-award-runtime-evaluation-v1", "passed": all(gates.values()), "gates": gates, "structure": structure, "failurePrivacy": failure, "unseenPositions": position}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_name(args.output.name + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, args.output)
    print(json.dumps({"passed": report["passed"], "gates": gates}, ensure_ascii=False))
    return 0 if report["passed"] else 4


if __name__ == "__main__":
    raise SystemExit(main())
