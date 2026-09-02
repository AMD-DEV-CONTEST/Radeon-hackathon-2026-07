"""tests/test_compare_runs.py — programbench_compare_runs.compare_two/three.

Builds a synthetic ledger with two or three runs, calls the comparator, and
asserts the delta math + lock detection + regression detection are correct.
The ledger is a real SQLite + JSONL pair built in a temp dir, so the test
exercises the actual `query_run_meta` + `_scores_from_ledger` read path.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import programbench_compare_runs as cmp_module  # noqa: E402
import run_ledger as rl  # noqa: E402


def _seed_one_event(
    tmp_db: Path,
    tmp_jsonl_dir: Path,
    run_id: str,
    task_id: str,
    score: float,
    passed: int,
    total: int,
    families: dict[str, int] | None = None,
) -> None:
    """Append an `eval / completed` event to a transient ledger."""
    rl.LEDGER_DIR = tmp_jsonl_dir  # type: ignore[assignment]
    rl.SQLITE_PATH = tmp_db  # type: ignore[assignment]
    evt = rl.LedgerEvent(
        run_id=run_id,
        task_id=task_id,
        phase="eval",
        status="completed",
        score=score,
        failures=families,
        artifact=f"/tmp/{run_id}/{task_id}.eval.json",
        extra={"passed": passed, "total": total, "failed": total - passed},
    )
    rl.append_event(evt, sqlite_path=tmp_db)


def _seed_meta(
    tmp_db: Path,
    tmp_jsonl_dir: Path,
    run_id: str,
    scaffold_version: str,
    patch_family: str,
    base_run_id: str | None = None,
) -> None:
    rl.LEDGER_DIR = tmp_jsonl_dir  # type: ignore[assignment]
    rl.SQLITE_PATH = tmp_db  # type: ignore[assignment]
    rl.record_run_meta(
        run_id=run_id,
        base_run_id=base_run_id,
        scaffold_version=scaffold_version,
        patch_family=patch_family,
        output_root=f"/tmp/{run_id}",
    )


@pytest.fixture
def tmp_ledger(tmp_path, monkeypatch):
    """Spin up a fresh ledger in tmp_path; monkeypatch the module globals so
    every read goes through it."""
    tmp_db = tmp_path / "ledger.db"
    tmp_jsonl = tmp_path / "ledger_jsonl"
    tmp_jsonl.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(rl, "LEDGER_DIR", tmp_jsonl)
    monkeypatch.setattr(rl, "SQLITE_PATH", tmp_db)
    # compare_runs reads via run_ledger's module global (via lazy `import run_ledger as _rl`
    # inside _scores_from_ledger); patching rl.SQLITE_PATH is sufficient.
    return tmp_db, tmp_jsonl


def test_compare_two_basic_deltas(tmp_ledger):
    tmp_db, tmp_jsonl = tmp_ledger
    # base run: three tools with scores 20 / 50 / 70
    _seed_meta(tmp_db, tmp_jsonl, "base", "scaff_v0", "(baseline)")
    _seed_one_event(
        tmp_db, tmp_jsonl, "base", "tool_a", 20.0, 200, 1000, families={"rc_2_unknown_option": 800}
    )
    _seed_one_event(
        tmp_db, tmp_jsonl, "base", "tool_b", 50.0, 500, 1000, families={"rc_2_unknown_option": 500}
    )
    _seed_one_event(tmp_db, tmp_jsonl, "base", "tool_c", 70.0, 700, 1000)

    # iter1: tool_a lifts to 60 (+40), tool_b regresses to 40 (-10), tool_c locks at 100
    _seed_meta(
        tmp_db, tmp_jsonl, "iter1", "scaff_clap_v1", "rc_2_unknown_option", base_run_id="base"
    )
    _seed_one_event(
        tmp_db, tmp_jsonl, "iter1", "tool_a", 60.0, 600, 1000, families={"rc_2_unknown_option": 400}
    )
    _seed_one_event(
        tmp_db, tmp_jsonl, "iter1", "tool_b", 40.0, 400, 1000, families={"rc_2_unknown_option": 600}
    )
    _seed_one_event(tmp_db, tmp_jsonl, "iter1", "tool_c", 100.0, 1000, 1000)

    report = cmp_module.compare_two("base", "iter1")

    assert report["shared_tools"] == 3
    assert report["avg_score_base"] == 46.7  # (20+50+70)/3 rounded
    assert report["avg_score_iter"] == 66.7  # (60+40+100)/3
    assert report["avg_delta_pp"] == 20.0  # net positive

    assert report["new_locks"] == ["tool_c"]
    assert report["new_unlocks"] == []
    assert report["regression_count"] == 1
    assert report["unchanged_count"] == 0
    assert report["regressions"][0]["task_id"] == "tool_b"
    assert report["regressions"][0]["delta"] == -10.0

    # Tools sorted by delta descending: tool_c (+30), tool_a (+40), tool_b (-10)
    # Note: tool_c delta is +30, tool_a is +40 so tool_a should come first
    tools_by_id = {t["task_id"]: t for t in report["tools"]}
    assert tools_by_id["tool_a"]["delta"] == 40.0
    assert tools_by_id["tool_b"]["delta"] == -10.0
    assert tools_by_id["tool_c"]["delta"] == 30.0
    assert tools_by_id["tool_a"]["is_new_lock"] is False
    assert tools_by_id["tool_c"]["is_new_lock"] is True
    assert tools_by_id["tool_b"]["is_regression"] is True


def test_compare_two_family_histogram_delta(tmp_ledger):
    tmp_db, tmp_jsonl = tmp_ledger
    _seed_meta(tmp_db, tmp_jsonl, "b", "v0", "(baseline)")
    _seed_one_event(
        tmp_db,
        tmp_jsonl,
        "b",
        "tool_x",
        10.0,
        100,
        1000,
        families={"rc_2_unknown_option": 800, "help_text_mismatch": 100},
    )

    _seed_meta(tmp_db, tmp_jsonl, "i1", "v1_clap", "rc_2_unknown_option", base_run_id="b")
    _seed_one_event(
        tmp_db,
        tmp_jsonl,
        "i1",
        "tool_x",
        90.0,
        900,
        1000,
        families={"rc_2_unknown_option": 50, "help_text_mismatch": 50},
    )

    report = cmp_module.compare_two("b", "i1")
    fams = {f["family"]: f for f in report["family_delta"]}
    assert fams["rc_2_unknown_option"]["base"] == 800
    assert fams["rc_2_unknown_option"]["iter"] == 50
    assert fams["rc_2_unknown_option"]["delta"] == -750  # huge drop, as expected for a clap fix
    assert fams["help_text_mismatch"]["delta"] == -50


def test_compare_two_provenance_pulled_from_meta(tmp_ledger):
    tmp_db, tmp_jsonl = tmp_ledger
    _seed_meta(tmp_db, tmp_jsonl, "b", "scaff_pre_clap", "(baseline)")
    _seed_one_event(tmp_db, tmp_jsonl, "b", "tool_a", 10.0, 10, 100)
    _seed_meta(tmp_db, tmp_jsonl, "i1", "scaff_clap_v1", "rc_2_unknown_option", base_run_id="b")
    _seed_one_event(tmp_db, tmp_jsonl, "i1", "tool_a", 60.0, 60, 100)

    report = cmp_module.compare_two("b", "i1")
    assert report["base_meta"]["scaffold_version"] == "scaff_pre_clap"
    assert report["iter_meta"]["scaffold_version"] == "scaff_clap_v1"
    assert report["iter_meta"]["patch_family"] == "rc_2_unknown_option"
    assert report["iter_meta"]["base_run_id"] == "b"


def test_compare_two_handles_only_one_side(tmp_ledger):
    tmp_db, tmp_jsonl = tmp_ledger
    _seed_meta(tmp_db, tmp_jsonl, "b", "v0", "(baseline)")
    _seed_one_event(tmp_db, tmp_jsonl, "b", "shared_tool", 50.0, 50, 100)
    _seed_one_event(tmp_db, tmp_jsonl, "b", "base_only_tool", 30.0, 30, 100)

    _seed_meta(tmp_db, tmp_jsonl, "i1", "v1", "f", base_run_id="b")
    _seed_one_event(tmp_db, tmp_jsonl, "i1", "shared_tool", 70.0, 70, 100)
    _seed_one_event(tmp_db, tmp_jsonl, "i1", "iter_only_tool", 80.0, 80, 100)

    report = cmp_module.compare_two("b", "i1")
    assert report["shared_tools"] == 1
    assert report["only_in_base"] == ["base_only_tool"]
    assert report["only_in_iter"] == ["iter_only_tool"]


def test_compare_three_trajectory(tmp_ledger):
    tmp_db, tmp_jsonl = tmp_ledger
    for run_id, score in [("b", 20.0), ("i1", 60.0), ("i2", 90.0)]:
        _seed_meta(
            tmp_db,
            tmp_jsonl,
            run_id,
            f"v_{run_id}",
            "fam",
            base_run_id=("b" if run_id != "b" else None),
        )
        _seed_one_event(tmp_db, tmp_jsonl, run_id, "tool_t", score, int(score), 100)

    report = cmp_module.compare_three("b", "i1", "i2")
    assert report["shared_tools"] == 1
    assert report["trajectory"][0]["task_id"] == "tool_t"
    assert report["trajectory"][0]["net_delta"] == 70.0
    assert report["trajectory"][0]["base"] == 20.0
    assert report["trajectory"][0]["iter1"] == 60.0
    assert report["trajectory"][0]["iter2"] == 90.0
