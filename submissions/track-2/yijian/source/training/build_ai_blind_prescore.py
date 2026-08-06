#!/usr/bin/env python3
"""Build non-authoritative AI suggestions for a human-confirmed blind review."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import time
import urllib.request
from pathlib import Path
from typing import Any

import validate_award_runtime as validator


SCHEMA = "yijian-ai-blind-prescore-v1"


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def read_pack(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    match = re.search(r'<script id="payload" type="application/json">(.*?)</script>', text, re.S)
    if not match:
        raise ValueError("blind review payload is missing")
    value = json.loads(match.group(1))
    if not isinstance(value, dict) or len(value.get("cases") or []) != 30:
        raise ValueError("blind pack must contain exactly 30 cases")
    return value


def extract_object(text: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
        if isinstance(value, dict):
            return value
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    while start >= 0:
        depth = 0
        quoted = False
        escaped = False
        for index in range(start, len(text)):
            char = text[index]
            if quoted:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    quoted = False
                continue
            if char == '"':
                quoted = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    value = json.loads(text[start:index + 1])
                    if isinstance(value, dict):
                        return value
        start = text.find("{", start + 1)
    raise ValueError("judge response does not contain a JSON object")


def call_judge(endpoint: str, model: str, case: dict[str, Any], blind_case: dict[str, Any]) -> dict[str, Any]:
    evidence = case.get("evidence") or {}
    compact = {
        "question": blind_case["question"],
        "expected": case.get("expected"),
        "questionTarget": evidence.get("questionTarget"),
        "actualMove": evidence.get("actualMove"),
        "actualColor": evidence.get("actualColor"),
        "bestMove": evidence.get("bestMove"),
        "toPlay": evidence.get("toPlay"),
        "sameTurnAlternatives": evidence.get("sameTurnAlternatives"),
        "boardBefore": (evidence.get("board") or {}).get("before"),
        "claimBoundary": evidence.get("claimBoundary"),
        "ruleFacts": evidence.get("ruleFacts"),
        "katago": {
            "bestMove": (evidence.get("katago") or {}).get("bestMove"),
            "candidates": (evidence.get("katago") or {}).get("candidates"),
            "actualMoveAnalysis": (evidence.get("katago") or {}).get("actualMoveAnalysis"),
            "perspective": (evidence.get("katago") or {}).get("perspective"),
            "subjectColor": (evidence.get("katago") or {}).get("subjectColor"),
        },
        "answers": blind_case["answers"],
    }
    system = (
        "你是围棋教学答案的证据审计器，不代表职业棋手，也不知道回答来自哪个模型。"
        "只按给定规则事实、KataGo、参考答案和证据边界评分。"
        "先核对实战颜色、当前行棋方及sameTurnAlternatives；不同颜色或不同回合的着法绝不能直接比较。"
        "subjectWinrate和subjectScoreLead已经换算为当前行棋方视角，不得再次反转。"
        "证据正确性、教学深度、可执行性各1到5分；冗长、自相矛盾、空泛套话要降分。"
        "出现错误坐标、错误首选、错误数值视角、无证据死活结论时 severe=true。"
        "严格返回JSON：{\"ratings\":[{\"alias\":\"A\",\"evidence\":1,\"depth\":1,"
        "\"actionability\":1,\"severe\":false,\"reason\":\"不超过60字\"}]}，必须含A/B/C。"
    )
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(compact, ensure_ascii=False, separators=(",", ":"))},
        ],
        "temperature": 0,
        "max_tokens": 650,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=240) as response:
        result = json.loads(response.read().decode("utf-8"))
    content = result["choices"][0]["message"]["content"]
    value = extract_object(content)
    ratings = value.get("ratings")
    if not isinstance(ratings, list):
        raise ValueError("judge response has no ratings array")
    by_alias = {str(row.get("alias")): row for row in ratings if isinstance(row, dict)}
    if set(by_alias) != {"A", "B", "C"}:
        raise ValueError("judge response must score A, B, and C exactly once")
    normalized = []
    for alias in ("A", "B", "C"):
        row = by_alias[alias]
        scores = {key: int(row.get(key)) for key in ("evidence", "depth", "actionability")}
        if not all(1 <= score <= 5 for score in scores.values()):
            raise ValueError("judge scores must be between 1 and 5")
        normalized.append({
            "alias": alias,
            **scores,
            "severe": bool(row.get("severe")),
            "reason": str(row.get("reason") or "")[:120],
        })
    return {"caseId": blind_case["caseId"], "ratings": normalized}


def deterministic_guard(case: dict[str, Any], blind_case: dict[str, Any], suggestion: dict[str, Any]) -> dict[str, Any]:
    by_alias = {row["alias"]: row for row in suggestion["ratings"]}
    for answer in blind_case["answers"]:
        alias = answer["alias"]
        checked = validator.validate_positions(
            [case], {case["caseId"]: {"answer": answer["answer"]}}
        )["details"][0]
        row = by_alias[alias]
        if checked["severeContradiction"] or checked["fabricatedSource"]:
            row["severe"] = True
            row["evidence"] = min(row["evidence"], 2)
            flags = checked["illegalCoordinates"]
            suffix = f"；规则校验异常：{','.join(flags)}" if flags else "；规则校验发现严重矛盾"
            row["reason"] = (row["reason"] + suffix)[:120]
        if any(token in answer["answer"] for token in ("【具体机制", "让我们仔细", "更正：", "等等，")):
            row["depth"] = min(row["depth"], 2)
            row["actionability"] = min(row["actionability"], 2)
    return suggestion


def write_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--endpoint", default="http://127.0.0.1:18082/v1/chat/completions")
    parser.add_argument("--model", default="Yijian-Qwen3.6-27B-GoCoach")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    pack = read_pack(args.review)
    cases = {row["caseId"]: row for row in read_jsonl(args.cases)}
    if set(row["caseId"] for row in pack["cases"]) - set(cases):
        raise ValueError("blind pack contains unknown cases")
    existing: dict[str, Any] = {}
    if args.output.is_file():
        previous = json.loads(args.output.read_text(encoding="utf-8"))
        if previous.get("packSha256") == pack["packSha256"]:
            existing = {row["caseId"]: row for row in previous.get("suggestions") or []}

    def evaluate(blind_case: dict[str, Any]) -> dict[str, Any]:
        for attempt in range(3):
            try:
                suggestion = call_judge(args.endpoint, args.model, cases[blind_case["caseId"]], blind_case)
                return deterministic_guard(cases[blind_case["caseId"]], blind_case, suggestion)
            except Exception:
                if attempt == 2:
                    raise
                time.sleep(1 + attempt)
        raise AssertionError("unreachable")

    pending = [row for row in pack["cases"] if row["caseId"] not in existing]
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {pool.submit(evaluate, row): row["caseId"] for row in pending}
        for future in concurrent.futures.as_completed(futures):
            value = future.result()
            existing[value["caseId"]] = value
            ordered = [existing[row["caseId"]] for row in pack["cases"] if row["caseId"] in existing]
            write_atomic(args.output, {
                "schemaVersion": SCHEMA,
                "status": "machine_suggestions_only",
                "humanReviewRequired": True,
                "judge": args.model,
                "packSha256": pack["packSha256"],
                "completed": len(ordered),
                "suggestions": ordered,
            })
            print(json.dumps({"completed": len(ordered), "total": 30, "caseId": value["caseId"]}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
