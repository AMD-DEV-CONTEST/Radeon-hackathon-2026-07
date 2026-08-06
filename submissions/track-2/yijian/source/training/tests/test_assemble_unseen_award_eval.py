from __future__ import annotations

import sys
from pathlib import Path


TRAINING_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TRAINING_ROOT))

import assemble_unseen_award_eval as assemble  # noqa: E402
import validate_award_runtime as runtime  # noqa: E402


def test_official_allowed_coordinates_include_all_exposed_evidence() -> None:
    unit = {
        "id": "official-test",
        "question": "比较 A6 与 B7。",
        "teacherAnswer": "以证据为界。",
        "evidenceBoundary": "不新增坐标。",
        "board": {
            "questionTargetMove": "A6",
            "before": {"black": ["C8"], "white": ["B6"]},
            "after": {"black": ["C8", "A6"], "white": ["B6"]},
        },
        "ruleFacts": {"capturedByTarget": ["B6"]},
        "katago": {
            "bestMove": "D10",
            "candidates": [{"move": "D10", "pv": ["E11"]}],
            "localCandidateAudit": {"allowedMoves": ["B7"]},
        },
        "source": {"sourceLocator": "official diagram: F12"},
    }
    row = assemble.official_cases([unit])[0]
    assert set(row["expected"]["allowedCoordinates"]) >= {
        "A6", "B6", "B7", "C8", "D10", "E11", "F12",
    }


def test_best_claim_keeps_two_digit_coordinate() -> None:
    assert runtime.BEST_CLAIM.findall("KataGo 首选是 F13。") == ["F13"]
    assert runtime.BEST_CLAIM.findall("best move: J10") == ["J10"]
