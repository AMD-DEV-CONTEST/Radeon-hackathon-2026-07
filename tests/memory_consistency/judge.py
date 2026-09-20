"""Memory-consistency judgment engine (zero external dependencies).

Evaluates a scenario's per-round outputs against declarative rules:

- must_contain:        every keyword must appear in the output
- must_contain_any:    list of keywords -> at least one must appear;
                       list of lists -> every group must have >=1 hit
- must_not_contain:    any listed keyword appearing fails the check
- require_confirm:     when true, the output must hit any confirm_keywords
                       (prevents silent guessing on ambiguous references)

Outcome per scenario: PASS / FAIL / WARN.
"""

from __future__ import annotations

from typing import Any


def _hit_any(keywords: list[str], output: str) -> bool:
    return any(kw in output for kw in keywords)


def _match_contain_any(spec: Any, output: str) -> tuple[bool, list[str]]:
    """Support both flat keyword lists and groups of keyword lists."""
    if spec and isinstance(spec[0], (list, tuple)):
        missed_groups: list[str] = []
        for group in spec:
            if not _hit_any(list(group), output):
                missed_groups.append("|".join(group))
        return (not missed_groups), missed_groups
    flat = list(spec or [])
    return (_hit_any(flat, output)), (["ALL" ] if not _hit_any(flat, output) else [])


def evaluate_check(check: dict, output: str) -> dict:
    """Evaluate a single check block against one round's output."""
    reasons: list[str] = []
    passed = True

    must = check.get("must_contain", [])
    missing = [kw for kw in must if kw not in output]
    if missing:
        passed = False
        reasons.append(f"缺关键词: {missing}")

    mca = check.get("must_contain_any")
    if mca:
        ok, missed = _match_contain_any(mca, output)
        if not ok:
            passed = False
            reasons.append(f"any组未命中: {missed}")

    mnot = check.get("must_not_contain", [])
    hits = [kw for kw in mnot if kw in output]
    if hits:
        passed = False
        reasons.append(f"出现禁用词: {hits}")

    if check.get("require_confirm"):
        confirm_kws = check.get("confirm_keywords", [])
        if not _hit_any(confirm_kws, output):
            passed = False
            reasons.append("未检测到歧义确认/版本声明（静默猜测）")

    note = check.get("note", "")
    return {"passed": passed, "reasons": reasons, "note": note}


def evaluate_scenario(outputs: dict[int, str], scenario: dict) -> dict:
    """Evaluate all checks of a scenario.

    outputs: {round_number: agent_reply_text}
    Returns {status, details: [per-check], failed_rounds, missing_rounds}
    """
    details: list[dict] = []
    failed_rounds: list[int] = []
    missing_rounds: list[int] = []

    for check in scenario.get("checks", []):
        rnd = check.get("round")
        output = outputs.get(rnd)
        if output is None:
            missing_rounds.append(rnd)
            details.append({
                "round": rnd,
                "passed": False,
                "reasons": [f"第 {rnd} 轮无输出（Agent 未产生回复）"],
                "note": check.get("note", ""),
            })
            failed_rounds.append(rnd)
            continue
        if not str(output).strip():
            missing_rounds.append(rnd)
            details.append({
                "round": rnd,
                "passed": False,
                "reasons": ["输出为空"],
                "note": check.get("note", ""),
            })
            failed_rounds.append(rnd)
            continue

        result = evaluate_check(check, str(output))
        details.append({"round": rnd, **result})
        if not result["passed"]:
            failed_rounds.append(rnd)

    if not scenario.get("checks"):
        status = "WARN"
    elif failed_rounds:
        status = "FAIL"
    else:
        status = "PASS"

    return {
        "id": scenario.get("id"),
        "name": scenario.get("name"),
        "status": status,
        "details": details,
        "failed_rounds": sorted(set(failed_rounds)),
        "missing_rounds": sorted(set(missing_rounds)),
    }
