"""tests/test_lock_queue.py — programbench_lock_queue ranking logic.

Verifies the ranking heuristic produces the right ordering on synthetic data
and that each contributing signal moves p_lock in the expected direction.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import programbench_lock_queue as lq  # noqa: E402
import run_ledger as rl  # noqa: E402


@pytest.fixture
def seeded_ledger(tmp_path, monkeypatch):
    tmp_db = tmp_path / "ledger.db"
    tmp_jsonl = tmp_path / "ledger_jsonl"
    tmp_jsonl.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(rl, "LEDGER_DIR", tmp_jsonl)
    monkeypatch.setattr(rl, "SQLITE_PATH", tmp_db)
    return tmp_db


def _seed(
    run_id: str, task_id: str, score: float, passed: int, total: int, families: dict[str, int]
) -> None:
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
    rl.append_event(evt)


def _make_audit(language_by_task: dict[str, str]) -> dict:
    return {
        "residual": [{"instance_id": tid, "lang": lang} for tid, lang in language_by_task.items()]
    }


# ---------------------------------------------------------------------------
# Signal-level tests
# ---------------------------------------------------------------------------


def test_score_band_thresholds():
    assert lq._score_band(99.5) == 1.00
    assert lq._score_band(85.0) == 0.80
    assert lq._score_band(70.0) == 0.55
    assert lq._score_band(45.0) == 0.30
    assert lq._score_band(25.0) == 0.15
    assert lq._score_band(5.0) == 0.05


def test_concentration_picks_top_family():
    fams = {"rc_2_unknown_option": 800, "help_text_mismatch": 100, "other": 100}
    share, top = lq._concentration(fams)
    assert top == "rc_2_unknown_option"
    assert 0.79 < share < 0.81  # 800/1000


def test_concentration_empty_families():
    share, top = lq._concentration({})
    assert share == 0.0
    assert top == ""


def test_test_count_inv_monotone():
    # Fewer tests should produce a higher inverse score
    assert lq._test_count_inv(100) > lq._test_count_inv(1000)
    assert lq._test_count_inv(1000) > lq._test_count_inv(6000)
    assert lq._test_count_inv(0) == 0.5  # safety fallback


def test_language_transfer_bonus():
    assert lq._language_transfer("rs") == 1.0
    assert lq._language_transfer("rust") == 1.0
    assert lq._language_transfer("go") == 1.0
    assert lq._language_transfer("cpp") == 0.0
    assert lq._language_transfer("") == 0.0


def test_fixable_family_tiers():
    # Tier 1 dominant families get full credit
    assert lq._fixable_family("rc_2_unknown_option") == 1.0
    assert lq._fixable_family("help_text_mismatch") == 1.0
    # Tier 2 partial credit
    assert lq._fixable_family("json_io") == 0.6
    assert lq._fixable_family("filter_flag") == 0.6
    # "other" / infra / unknown -> no credit
    assert lq._fixable_family("other") == 0.0
    assert lq._fixable_family("hash_executable_fail") == 0.0
    assert lq._fixable_family("") == 0.0


# ---------------------------------------------------------------------------
# End-to-end ranking
# ---------------------------------------------------------------------------


def test_rank_orders_by_p_lock(seeded_ledger, monkeypatch):
    # high-concentration patch-fixable Rust tool at mid-score = top candidate
    _seed("r", "tool_high", 50.0, 500, 1000, {"rc_2_unknown_option": 480, "other": 20})
    # diffuse failure across many families, no patch fits — should rank low
    _seed(
        "r",
        "tool_diffuse",
        50.0,
        500,
        1000,
        {"other": 200, "filter_flag": 150, "stdin_handling": 100, "json_io": 50},
    )
    # high tests + low concentration = low rank
    _seed("r", "tool_huge", 30.0, 1500, 5000, {"other": 3500})
    # already locked = highest
    _seed("r", "tool_locked", 100.0, 1000, 1000, {})

    audit = _make_audit(
        {
            "tool_high": "rs",
            "tool_diffuse": "rs",
            "tool_huge": "rs",
            "tool_locked": "rs",
        }
    )
    monkeypatch.setattr(lq, "_DEFAULT_AUDIT", Path("/nonexistent"))
    # Inline-pass audit dict via temp file
    import json as _json

    tmp_audit = Path(seeded_ledger).parent / "audit.json"
    tmp_audit.write_text(_json.dumps(audit), encoding="utf-8")

    report = lq.rank("r", audit_path=tmp_audit, top=10)

    ids = [t["task_id"] for t in report["queue"]]
    # The lock QUEUE prioritizes tools likely to BECOME locks with bounded work.
    # An already-locked tool has score_band=1.0 (0.35 weight contribution) but
    # zero concentration and zero fixable_family — so a high-leverage actionable
    # tool (mid-band + concentrated + tier-1 patch fits) correctly outranks it.
    assert ids.index("tool_high") < ids.index("tool_locked"), (
        "high-leverage actionable tool must outrank an already-locked tool in the work queue"
    )
    # tool_high should beat tool_diffuse (same score, concentration + fixable_family edge)
    assert ids.index("tool_high") < ids.index("tool_diffuse")
    # tool_huge: low score + diffuse + huge tests => should be at/near the bottom
    assert ids.index("tool_huge") > ids.index("tool_high")


@pytest.mark.usefixtures("seeded_ledger")
def test_rank_emits_signal_breakdown():
    _seed("r", "tool_x", 50.0, 500, 1000, {"rc_2_unknown_option": 500})
    report = lq.rank("r", audit_path=Path("/nonexistent"), top=10)
    t = report["queue"][0]
    sig = t["signals"]
    # All 5 signals present
    assert set(sig.keys()) == {
        "score_band",
        "concentration",
        "test_count_inv",
        "language_transfer",
        "fixable_family",
    }
    # Reasons humanize the same fields
    reasons_str = "; ".join(t["reasons"])
    assert "fixable" in reasons_str.lower()
    assert "rc_2_unknown_option" in reasons_str


@pytest.mark.usefixtures("seeded_ledger")
def test_rank_empty_ledger_returns_empty_queue():
    report = lq.rank("nonexistent_run", audit_path=Path("/nonexistent"), top=10)
    assert report["tools_total"] == 0
    assert report["queue"] == []


@pytest.mark.usefixtures("seeded_ledger")
def test_rank_weights_published_in_report():
    _seed("r", "tool_x", 50.0, 500, 1000, {})
    report = lq.rank("r", audit_path=Path("/nonexistent"), top=5)
    w = report["weights"]
    # Weights should sum to ~1.0 so p_lock is bounded in [0, 1]
    assert abs(sum(w.values()) - 1.0) < 1e-9
