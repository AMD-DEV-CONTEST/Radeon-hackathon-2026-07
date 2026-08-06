from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


TRAINING = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TRAINING))

import build_ai_assisted_blind_review as assisted  # noqa: E402


def fixtures(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    cases = [{"caseId": f"case-{index:02d}", "question": f"问题 {index}", "answers": [{"alias": alias, "answer": f"回答 {alias}"} for alias in ("A", "B", "C")]} for index in range(30)]
    pack = {"schemaVersion": "yijian-blind-review-pack-v2", "packSha256": "a" * 64, "cases": cases}
    review = tmp_path / "review.html"
    review.write_text('<script id="payload" type="application/json">' + json.dumps(pack, ensure_ascii=False) + "</script>", encoding="utf-8")
    prescore = {"schemaVersion": "yijian-ai-blind-prescore-v1", "status": "machine_suggestions_only", "humanReviewRequired": True, "judge": "PRIVATE-JUDGE-MODEL", "packSha256": "a" * 64, "completed": 30, "suggestions": [{"caseId": case["caseId"], "ratings": [{"alias": alias, "evidence": 4, "depth": 3, "actionability": 4, "severe": False, "reason": "建议理由"} for alias in ("A", "B", "C")]} for case in cases]}
    prescore_path = tmp_path / "prescore.json"
    prescore_path.write_text(json.dumps(prescore, ensure_ascii=False), encoding="utf-8")
    evidence_rows = [
        {
            "caseId": case["caseId"],
            "evidence": {
                "actualMove": "D4", "bestMove": "E5", "boardSize": 9, "toPlay": "B",
                "board": {"boardSize": 9, "subjectColor": "B", "before": {"black": ["C3"], "white": ["F6"]}},
                "katago": {"visits": 128, "bestMove": "E5", "candidates": [{"move": "E5", "visits": 128, "winrate": .6, "scoreLead": 2.0, "pv": ["E5"]}]},
                "claimBoundary": "只限当前局面。",
            },
            "expected": {"referenceAnswer": "参考答案"},
        }
        for case in cases
    ]
    cases_path = tmp_path / "cases.jsonl"
    cases_path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in evidence_rows), encoding="utf-8")
    queries_path = tmp_path / "queries.jsonl"
    queries_path.write_text(json.dumps({"id": cases[-1]["caseId"], "moves": [["B", "D4"], ["W", "E5"]]}) + "\n", encoding="utf-8")
    return review, prescore_path, cases_path, queries_path


def test_builds_prefilled_human_confirmation_page(tmp_path: Path) -> None:
    review, prescore, cases, queries = fixtures(tmp_path)
    output = tmp_path / "assisted.html"
    result = assisted.build(review, prescore, cases, queries, output)
    html = output.read_text(encoding="utf-8")
    assert result["cases"] == 30
    assert result["answers"] == 90
    assert result["boards"] == 30
    assert "canvas class=\"board\"" in html
    assert "绿圈：同回合 KataGo 首选" in html
    assert "AI 证据预审建议，不是职业棋手评分" in html
    assert "确认本题三份评分" in html
    assert "humanConfirmedCases" in html
    assert "PRIVATE-JUDGE-MODEL" not in html


def test_rejects_prescore_for_another_pack(tmp_path: Path) -> None:
    review, prescore_path, cases, queries = fixtures(tmp_path)
    value = json.loads(prescore_path.read_text(encoding="utf-8"))
    value["packSha256"] = "b" * 64
    prescore_path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="does not match"):
        assisted.build(review, prescore_path, cases, queries, tmp_path / "assisted.html")


def test_rejects_post_move_or_missing_board(tmp_path: Path) -> None:
    review, prescore, cases, queries = fixtures(tmp_path)
    rows = [json.loads(line) for line in cases.read_text(encoding="utf-8").splitlines()]
    rows[0]["evidence"]["board"]["before"]["black"].append("D4")
    cases.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    with pytest.raises(ValueError, match="already on the pre-move board"):
        assisted.build(review, prescore, cases, queries, tmp_path / "post-move.html")

    rows[0]["evidence"].pop("board")
    cases.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    with pytest.raises(ValueError, match="requires a pre-move board"):
        assisted.build(review, prescore, cases, queries, tmp_path / "missing-board.html")
