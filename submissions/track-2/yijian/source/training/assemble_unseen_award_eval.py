# -*- coding: utf-8 -*-
"""Assemble the frozen 12 official + 28 project-original award evaluation cases."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any


SYSTEM = (
    "你是弈鉴围棋教练。只能使用服务端给出的规则事实、KataGo 候选和来源边界。"
    "先给结论，再解释具体机制与取舍。不得新增坐标、胜率、目差、行棋方或死活结论。"
    "只返回 JSON，字段为 answer 与 followUps。"
)

COORD_TOKEN = re.compile(r"(?<![A-Za-z0-9])[A-HJ-T](?:1[0-9]|[1-9])(?![A-Za-z0-9])", re.I)


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def coordinates_in(value: Any) -> set[str]:
    """Collect every board coordinate actually exposed in an evidence object."""
    found: set[str] = set()
    if isinstance(value, dict):
        for item in value.values():
            found.update(coordinates_in(item))
    elif isinstance(value, (list, tuple)):
        for item in value:
            found.update(coordinates_in(item))
    elif isinstance(value, str):
        found.update(match.upper() for match in COORD_TOKEN.findall(value))
        if value.strip().upper() == "PASS":
            found.add("PASS")
    return found


def project_cases(cases: list[dict[str, Any]], result: dict[str, Any]) -> list[dict[str, Any]]:
    analyses = {str(row["id"]): row for row in result.get("results") or []}
    rows = []
    for row in cases:
        analysis = analyses.get(str(row["caseId"]))
        if not analysis:
            raise ValueError(f"missing KataGo result for {row['caseId']}")
        move_infos = analysis.get("moveInfos") or []
        root = analysis.get("rootInfo") or {}
        if not move_infos or int(root.get("visits") or 0) < 128:
            raise ValueError(f"incomplete 128-visit analysis for {row['caseId']}")
        best = str(move_infos[0]["move"]).upper()
        actual = str(row["position"]["moves"][-1][1]).upper()
        candidates = [{
            "move": str(item.get("move") or "").upper(),
            "visits": int(item.get("visits") or 0),
            "winrate": item.get("winrate"),
            "scoreLead": item.get("scoreLead"),
            "pv": [str(move).upper() for move in (item.get("pv") or [])[:12]],
        } for item in move_infos[:8]]
        evidence = {
            "questionTarget": row["target"], "actualMove": actual, "bestMove": best,
            "toPlay": row["position"]["toPlay"], "boardSize": 19,
            "positionHash": row["positionHash"], "boardFingerprint": row["boardFingerprint"],
            "katago": {"visits": 128, "bestMove": best, "candidates": candidates,
                        "rootWinrate": root.get("winrate"), "rootScoreLead": root.get("scoreLead")},
            "claimBoundary": "仅支持当前公开棋谱重建局面、goboard 规则事实与本次 KataGo 128 visits；不外推整盘胜负或绝对死活。",
        }
        rows.append({
            "schemaVersion": "yijian-award-position-case-v1", "caseId": row["caseId"],
            "suite": "unseen_project_position", "target": row["target"], "question": row["question"],
            "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": f"证据：{canonical(evidence)}\n问题：{row['question']}"}],
            "expected": {"actualMove": actual, "bestMove": best, "allowedCoordinates": sorted({actual, best, *[item["move"] for item in candidates], *[move for item in candidates for move in item["pv"]]}), "specialty": False},
            "evidence": evidence, "sealed": False, "trainingEligible": False,
        })
    return rows


def official_cases(units: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for index, unit in enumerate(units):
        target = ("actual", "best", "comparison")[index % 3]
        katago = unit.get("katago") or {}
        board = unit.get("board") or {}
        actual = str(board.get("questionTargetMove") or katago.get("bestMove") or "").upper()
        best = str(katago.get("bestMove") or actual).upper()
        candidates = katago.get("candidates") or []
        evidence = {
            "questionTarget": target, "actualMove": actual, "bestMove": best,
            "board": board, "ruleFacts": unit.get("ruleFacts"), "katago": katago,
            "source": unit.get("source"), "claimBoundary": unit.get("evidenceBoundary"),
        }
        allowed = coordinates_in(evidence) | {actual, best}
        rows.append({
            "schemaVersion": "yijian-award-position-case-v1", "caseId": str(unit["id"]),
            "suite": "official_specialty", "target": target, "question": str(unit.get("question") or "请解释当前目标手的机制与取舍。"),
            "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": f"证据：{canonical(evidence)}\n问题：{unit.get('question') or ''}"}],
            "expected": {"actualMove": actual, "bestMove": best, "allowedCoordinates": sorted(value for value in allowed if value), "specialty": True, "referenceAnswer": unit.get("teacherAnswer")},
            "evidence": evidence, "sealed": False, "trainingEligible": False,
        })
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-cases", type=Path, required=True)
    parser.add_argument("--katago-results", type=Path, required=True)
    parser.add_argument("--official-units", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    projects = project_cases(read_jsonl(args.project_cases), json.loads(args.katago_results.read_text(encoding="utf-8")))
    officials = official_cases(read_jsonl(args.official_units))
    rows = officials + projects
    if len(officials) != 12 or len(projects) != 28 or len(rows) != 40:
        raise SystemExit(f"expected 12+28=40, got {len(officials)}+{len(projects)}")
    targets = {target: sum(row["target"] == target for row in rows) for target in ("actual", "best", "comparison")}
    if min(targets.values()) < 10:
        raise SystemExit(f"blind target quota failed: {targets}")
    atomic(args.output, "".join(canonical(row) + "\n" for row in rows))
    manifest = {
        "schemaVersion": "yijian-award-position-manifest-v1", "passed": True,
        "cases": 40, "officialSpecialty": 12, "projectOriginal": 28,
        "targets": targets, "trainingEligible": False,
        "outputSha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
    }
    atomic(args.output.with_name("manifest.json"), json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(manifest, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
