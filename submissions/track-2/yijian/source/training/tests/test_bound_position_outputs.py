from __future__ import annotations

import json
import sys
from pathlib import Path


TRAINING = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TRAINING))
import bound_position_outputs as bounded  # noqa: E402


def test_invalid_coordinate_is_replaced_by_deterministic_fallback(tmp_path: Path) -> None:
    case = {
        "caseId": "case-1", "suite": "unseen_project_position", "target": "best",
        "expected": {"actualMove": "D4", "bestMove": "E5", "allowedCoordinates": ["D4", "E5"]},
        "evidence": {
            "actualMove": "D4", "actualColor": "B", "bestMove": "E5", "toPlay": "B",
            "sameTurnAlternatives": True, "positionHashBefore": "a" * 64,
            "board": {"before": {"black": [], "white": []}},
            "katago": {
                "perspective": "SUBJECT_TO_PLAY", "subjectColor": "B", "visits": 128,
                "actualMoveAnalysis": {"move": "D4", "subjectWinrate": .5, "subjectScoreLead": 0},
                "candidates": [{"move": "E5", "subjectWinrate": .6, "subjectScoreLead": 2, "visits": 128, "pv": ["E5"]}],
            },
        },
    }
    cases = tmp_path / "cases.jsonl"
    cases.write_text(json.dumps(case) + "\n", encoding="utf-8")
    raw = tmp_path / "raw.json"
    raw.write_text(json.dumps({
        "model": "model", "results": [{"caseId": "case-1", "answer": '{"answer":"首选 E5，随后 F13。","followUps":[]}', "succeeded": True}],
    }), encoding="utf-8")
    report = bounded.build(cases, raw, tmp_path / "bounded.json")
    assert report["fallbackCount"] == 1
    assert report["rawValidation"]["severeContradictions"] == 1
    assert report["finalValidation"]["severeContradictions"] == 0
    assert report["finalValidation"]["structuredOutputSuccess"] == 1
