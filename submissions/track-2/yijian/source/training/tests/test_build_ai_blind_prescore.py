from __future__ import annotations

import json
import sys
from pathlib import Path


TRAINING = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TRAINING))

import build_ai_blind_prescore as prescore  # noqa: E402


def test_read_pack_and_extract_judge_object(tmp_path: Path) -> None:
    payload = {"packSha256": "a" * 64, "cases": [{"caseId": str(i)} for i in range(30)]}
    page = tmp_path / "review.html"
    page.write_text(
        '<script id="payload" type="application/json">' + json.dumps(payload) + "</script>",
        encoding="utf-8",
    )
    assert prescore.read_pack(page)["packSha256"] == "a" * 64
    assert prescore.extract_object('text {"ratings": []} tail') == {"ratings": []}
