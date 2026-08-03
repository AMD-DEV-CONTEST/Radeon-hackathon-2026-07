# -*- coding: utf-8 -*-
"""KataGo 完成后的批量讲解与缓存边界测试。"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

import report_narratives
import jobs
from engine import MockKataGoEngine


def _raw(*, source: str = "katago", demo: bool = False) -> dict:
    return {
        "game": {"moveCount": 1, "boardSize": 19},
        "engine": {
            "source": source,
            "demo": demo,
            "criticalVisits": 128,
        },
        "positions": [
            {"winrateBlack": 0.50, "scoreLeadBlack": 0.0},
            {"winrateBlack": 0.46, "scoreLeadBlack": -1.2},
        ],
        "losses": [
            {
                "turn": 1,
                "color": "B",
                "actualMove": "K4",
                "recommendedMove": "C17",
                "winrateLoss": 4.0,
                "scoreLoss": 1.2,
                "deepVisits": 128,
                "pv": ["C17", "Q16"],
                "purposeEvidence": {
                    "connection": False,
                    "cut": False,
                    "defense": True,
                    "attack": False,
                    "connectedGroups": 1,
                    "adjacentOpponentGroups": 0,
                    "captures": 0,
                    "evidenceSource": ["board_rules", source],
                },
            }
        ],
    }


def test_batch_narrative_uses_frozen_true_katago_evidence(
    monkeypatch,
):
    calls = []

    def fake_call(provider, settings, position, evidence, purpose):
        calls.append((provider, position, evidence, purpose))
        return {
            "source": provider,
            "sourceLabel": "云端增强老师",
            "model": "fixture-model",
            "latencyMs": 25,
            "title": purpose["title"],
            "paragraphs": ["目的", "取舍", "下一步"],
        }

    monkeypatch.setenv("GOMENTOR_BATCH_MENTOR_PROVIDER", "cloud")
    monkeypatch.setenv("YIJIAN_CLOUD_LLM_URL", "http://fixture/v1")
    monkeypatch.setenv("YIJIAN_CLOUD_LLM_MODEL", "fixture-model")
    monkeypatch.setenv("YIJIAN_MENTOR_MODEL_REVISION", "fixture-rev")
    monkeypatch.setattr(report_narratives, "_settings", lambda: {})
    monkeypatch.setattr(report_narratives.mentor, "_call_provider", fake_call)

    raw = report_narratives.enrich(_raw())
    assert raw["narrativeBatch"]["generated"] == 1
    assert raw["narrativeBatch"]["failed"] == 0
    assert raw["losses"][0]["narrative"]["modelRevision"] == "fixture-rev"
    _, position, evidence, purpose = calls[0]
    assert position["moveCandidates"]["actual"]["region"]["label"] == "中央下方"
    assert position["moveCandidates"]["best"]["region"]["label"] == "左边上方"
    assert evidence["source"] == "katago"
    assert evidence["demo"] is False
    assert purpose["confidence"] == "heuristic"


def test_batch_narrative_refuses_mock_analysis(monkeypatch):
    def must_not_call(*_args, **_kwargs):
        raise AssertionError("mock analysis must never reach the LLM batch")

    monkeypatch.setattr(report_narratives.mentor, "_call_provider", must_not_call)
    raw = report_narratives.enrich(_raw(source="mock", demo=True))
    assert raw["narrativeBatch"]["generated"] == 0
    assert raw["narrativeBatch"]["skipped"] == "requires_true_katago"
    assert "narrative" not in raw["losses"][0]


def test_report_cache_signature_tracks_model_revision(monkeypatch):
    monkeypatch.setattr(report_narratives, "_settings", lambda: {})
    manager = jobs.AnalysisManager(MockKataGoEngine())
    try:
        monkeypatch.setenv("YIJIAN_MENTOR_MODEL_REVISION", "revision-a")
        first = manager.signature({"sgf": "(;GM[1]SZ[19])"})
        monkeypatch.setenv("YIJIAN_MENTOR_MODEL_REVISION", "revision-b")
        second = manager.signature({"sgf": "(;GM[1]SZ[19])"})
    finally:
        manager.close()
    assert first != second
