import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PACKET = ROOT / "assurance" / "evidence" / "programbench_200_lock_campaign"
BOARD = ROOT / "logs" / "programbench_lock_board.json"

REQUIRED_FILES = {
    "baseline_board.json",
    "baseline_summary.md",
    "remaining_tools.json",
    "remaining_tools.md",
    "campaign_plan.md",
    "remaining_tool_classification.md",
}

ALLOWED_CATEGORIES = {
    "LOCK_NOW",
    "PUSH_TO_LOCK",
    "FACTORY_ACCEPTED_NEEDS_HARDENING",
    "HAND_TEST_ITERATE",
    "BROKEN_HARNESS",
    "MISSING_DEPENDENCY",
    "UPSTREAM_COMPLEXITY_HIGH",
    "BLOCKED_EXACT",
}


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _rename_agnostic(value):
    """Normalize the Citadel<->Determinex mechanical-rename token in machine paths so the frozen
    baseline (captured under one checkout/drive naming) still locks CONTENT equality against a
    board regenerated under the other. Scores, statuses, counts stay strictly compared -- only the
    rename token differs across eras, and no tool slug contains it."""
    if isinstance(value, str):
        return value.replace("Determinex", "Citadel").replace("determinex", "citadel")
    if isinstance(value, list):
        return [_rename_agnostic(v) for v in value]
    if isinstance(value, dict):
        return {k: _rename_agnostic(v) for k, v in value.items()}
    return value


def _remaining_board_rows():
    board = _read_json(BOARD)
    return [row for row in board if not row.get("locked_archive")]


def _classification_rows():
    lines = (PACKET / "remaining_tool_classification.md").read_text(encoding="utf-8").splitlines()
    rows = []
    in_tool_table = False
    for line in lines:
        if line.startswith("| Tool | Current score | Status | Category |"):
            in_tool_table = True
            continue
        if in_tool_table and not line.startswith("|"):
            break
        if not in_tool_table:
            continue
        if not line.startswith("| "):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if not cells or cells[0] == "---":
            continue
        rows.append(cells)
    return rows


def test_pb_200_campaign_packet_has_required_files():
    missing = [name for name in sorted(REQUIRED_FILES) if not (PACKET / name).exists()]
    assert missing == []


def test_pb_200_campaign_baseline_matches_current_board_counts():
    remaining = _remaining_board_rows()
    locked = [row for row in _read_json(BOARD) if row.get("locked_archive")]
    baseline = _read_json(PACKET / "baseline_board.json")
    remaining_tools = _read_json(PACKET / "remaining_tools.json")

    assert _rename_agnostic(baseline) == _rename_agnostic(_read_json(BOARD))
    assert len(baseline) == 210
    assert len(locked) == 100
    assert len(remaining) == 110
    assert len(remaining_tools) == 110
    assert sum(int(row.get("best_passed") or 0) for row in baseline) == 205783
    assert sum(int(row.get("best_runnable_total") or 0) for row in baseline) == 259965


def test_pb_200_campaign_classifies_every_remaining_tool_once():
    remaining_slugs = {row["base_slug"] for row in _remaining_board_rows()}
    rows = _classification_rows()

    assert len(rows) == 110
    classified_slugs = [row[0] for row in rows]
    assert set(classified_slugs) == remaining_slugs
    assert len(classified_slugs) == len(set(classified_slugs))

    for row in rows:
        assert len(row) == 8
        assert row[3] in ALLOWED_CATEGORIES
        assert row[4]
        assert row[5]
        assert row[6] == "Codex"
        assert row[7]
