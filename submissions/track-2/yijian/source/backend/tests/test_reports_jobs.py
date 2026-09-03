# -*- coding: utf-8 -*-
"""整盘报告、九档棋力与本地任务队列回归测试。"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

import importers
import jobs
import library
import reports
import sgf
from engine import MockKataGoEngine
from goboard import replay


SGF_FIXTURE = (
    "(;GM[1]FF[4]SZ[19]KM[7.5]PB[脱敏黑方]PW[脱敏白方]RE[B+R]"
    ";B[pd];W[dd];B[qp];W[dq];B[cf];W[fc];B[pp];W[dp]"
    ";B[cn];W[fq];B[qf];W[oc];B[nc];W[qc];B[qd];W[pc]"
    ";B[od];W[nb];B[mc];W[ne];B[pf];W[oe];B[pe];W[of]"
    ";B[pg];W[ng];B[qh];W[oh];B[oi];W[ni];B[pj];W[nk]"
    ";B[ql];W[om];B[pm];W[nm];B[qn];W[no];B[oo];W[np]"
    ";B[op];W[nq];B[oq];W[nr];B[or];W[ns];B[ps];W[os])"
)


def fixture_game():
    return importers.import_bytes(SGF_FIXTURE.encode("utf-8"), "fixture.sgf")


@pytest.mark.parametrize(
    "rank,factor",
    [
        ("kyu_25_13", 2.5), ("kyu_12_1", 2.0), ("amateur_1d", 1.8),
        ("amateur_2d", 1.6), ("amateur_3d", 1.4), ("amateur_4d", 1.2),
        ("amateur_5d", 1.0), ("amateur_6d", .8), ("professional", .6),
    ],
)
def test_rank_thresholds(rank, factor):
    values = reports.thresholds(rank)
    assert values["major"]["winrate"] == pytest.approx(10 * factor)
    assert values["mistake"]["score"] == pytest.approx(2.5 * factor)
    assert values["question"]["winrate"] == pytest.approx(2 * factor)


def test_same_loss_changes_level_by_rank():
    assert reports.classify_loss(4.9, 0, "kyu_25_13") is None
    assert reports.classify_loss(4.9, 0, "amateur_5d") == "question"
    assert reports.classify_loss(4.9, 0, "professional") == "mistake"


@pytest.mark.parametrize(
    "legacy,expected",
    [
        ("1段以下", "kyu_12_1"), ("1段", "amateur_1d"),
        ("6段", "amateur_6d"), ("7段", "amateur_6d"),
        ("9段", "amateur_6d"), ("职业", "professional"),
        ("bad", "amateur_5d"), (None, "amateur_5d"),
    ],
)
def test_legacy_rank_migration(legacy, expected):
    assert reports.normalize_rank(legacy) == expected


def test_four_channel_report_and_dynamic_rank():
    imported = fixture_game()
    analysis = MockKataGoEngine().analyze_game(imported.game)
    raw = reports.build_raw_report(imported.game, analysis, "B")
    five_dan = reports.render_report(raw, "amateur_5d")
    beginner = reports.render_report(raw, "kyu_25_13")
    assert set(five_dan["stageCards"]) == {"joseki", "opening", "middle", "endgame"}
    assert five_dan["perspective"] == "B"
    assert five_dan["positions"] == beginner["positions"]
    assert all(
        beginner["stageCards"][name]["score"] >= five_dan["stageCards"][name]["score"]
        for name in five_dan["stageCards"]
    )
    assert all(segment["end"] <= 80 for segment in raw["phases"]["joseki"])
    evidence = raw["losses"][0]["purposeEvidence"]
    assert {
        "move", "player", "connectedGroups", "adjacentOpponentGroups",
        "captures", "libertiesBeforeAfter", "connection", "cut",
        "defense", "attack", "territoryDelta", "ownershipDelta",
        "winrateLoss", "scoreLoss", "bestMove", "pv", "confidence",
        "evidenceSource",
    } <= evidence.keys()
    assert evidence["evidenceSource"][0] == "board_rules"


def test_isolated_move_is_not_mislabeled_as_defense_or_attack():
    game = sgf.parse("(;GM[1]FF[4]SZ[19]KM[7.5];B[pd])")
    _, states = replay(game)
    evidence = reports.build_move_purpose_evidence(
        game,
        states,
        [{}, {}],
        1,
        analysis_source="katago",
        demo=False,
    )
    assert evidence["connectedGroups"] == 0
    assert evidence["adjacentOpponentGroups"] == 0
    assert evidence["defense"] is False
    assert evidence["attack"] is False


def test_direct_contact_can_be_labeled_as_reinforcement():
    game = sgf.parse(
        "(;GM[1]FF[4]SZ[19]KM[7.5];B[pd];W[dd];B[pe])"
    )
    _, states = replay(game)
    evidence = reports.build_move_purpose_evidence(
        game,
        states,
        [{}, {}, {}, {}],
        3,
        analysis_source="katago",
        demo=False,
    )
    assert evidence["connectedGroups"] == 1
    assert evidence["defense"] is True


def test_analysis_job_persists_report(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "DB_PATH", tmp_path / "jobs.db")
    imported = fixture_game()
    game, _ = library.add_import(imported)
    manager = jobs.AnalysisManager(MockKataGoEngine())
    job = manager.create(game["id"], "B")
    deadline = time.time() + 5
    while time.time() < deadline:
        job = manager.get(job["id"])
        if job["status"] in ("completed", "failed"):
            break
        time.sleep(.02)
    manager.close()
    assert job["status"] == "completed", job
    assert job["progress"] == 100
    assert job["elapsedSeconds"] >= 0
    assert job["etaSeconds"] == 0
    assert job["targetSeconds"] == pytest.approx(jobs.FAST_TARGET_SECONDS)
    assert job["rate"] >= 0
    cached = library.latest_report(game["id"], "B")
    assert cached and cached["raw"]["perspective"] == "B"
    assert cached["raw"]["engine"]["visits"] == jobs.FAST_SCAN_VISITS
    assert cached["raw"]["engine"]["criticalVisits"] == jobs.FAST_REVIEW_VISITS
    assert cached["raw"]["engine"]["targetSeconds"] == pytest.approx(
        jobs.FAST_TARGET_SECONDS
    )


def test_analysis_modes_have_distinct_signatures_and_metadata(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "DB_PATH", tmp_path / "modes.db")
    imported = fixture_game()
    game, _ = library.add_import(imported)
    manager = jobs.AnalysisManager(MockKataGoEngine())
    assert manager.signature(game, "fast") != manager.signature(game, "deep")
    fast = manager.create(game["id"], "B", mode="fast")
    deep = manager.create(game["id"], "W", mode="deep")
    assert fast["mode"] == "fast"
    assert deep["mode"] == "deep"
    deadline = time.time() + 5
    while time.time() < deadline:
        fast = manager.get(fast["id"])
        deep = manager.get(deep["id"])
        if fast["status"] == deep["status"] == "completed":
            break
        time.sleep(.02)
    manager.close()
    assert fast["status"] == deep["status"] == "completed"
    assert library.latest_report(game["id"], "B")["raw"]["engine"]["analysisMode"] == "fast"
    assert library.latest_report(game["id"], "W")["raw"]["engine"]["analysisMode"] == "deep"


def test_deep_result_keeps_fast_evidence_and_quality_marker():
    raw = {
        "losses": [{
            "turn": 3, "color": "B", "winrateLoss": 4.0, "scoreLoss": 1.2,
        }]
    }
    pre = {
        "winrateBlack": .60, "scoreLeadBlack": 3.0,
        "recommendations": [{"move": "D4", "pv": ["D4", "Q16"]}],
    }
    post = {"winrateBlack": .51, "scoreLeadBlack": .5}
    reports.apply_deep_result(
        raw, 3, pre, post, visits=256, confidence="high"
    )
    node = raw["losses"][0]
    assert node["fastWinrateLoss"] == 4.0
    assert node["winrateLoss"] == 9.0
    assert node["deepVisits"] == 256
    assert node["confidence"] == "high"
    assert node["stability"] == "confirmed"
