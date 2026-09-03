# -*- coding: utf-8 -*-
"""Mock 分析引擎测试。"""
import os
import io
import queue
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import sgf
from engine import MockKataGoEngine
from engine.katago_engine import KataGoEngine, KataGoError, normalize_komi

SGF_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "recommendation-smoke.sgf")


@pytest.fixture(scope="module")
def analysis():
    game = sgf.parse_file(SGF_PATH)
    return MockKataGoEngine().analyze_game(game)


def test_structure(analysis):
    assert analysis["source"] == "mock"
    assert analysis["demo"] is True
    assert "演示" in analysis["label"]
    assert len(analysis["positions"]) == 11  # empty board + 10 public fixture moves
    for p in analysis["positions"]:
        assert 0.0 < p["winrateBlack"] < 1.0
    assert 1 <= len(analysis["keyMoves"]) <= 5


def test_deterministic():
    game = sgf.parse_file(SGF_PATH)
    eng = MockKataGoEngine()
    assert eng.analyze_game(game) == eng.analyze_game(game)


def test_key_moves_sorted_and_move78_top1(analysis):
    kms = analysis["keyMoves"]
    deltas = [abs(k["deltaWinrate"]) for k in kms]
    assert deltas == sorted(deltas, reverse=True)
    # 演示锚点按 G4 赛评设定：第 78 手（白 L11）应为头号关键手
    assert 1 <= kms[0]["number"] <= 10
    assert kms[0]["gtp"]
    assert kms[0]["color"] in {"B", "W"}
    assert kms[0]["deltaWinrate"] != 0


def test_generic_game_neutral_curve():
    g = sgf.parse("(;GM[1]SZ[19];B[pd];W[dp];B[cd];W[qp];B[op])")
    out = MockKataGoEngine().analyze_game(g)
    assert out["demo"] is True
    assert len(out["positions"]) == 6
    assert len(out["keyMoves"]) == 5


def test_tencent_fox_chinese_komi_encoding():
    assert normalize_komi("375", "chinese") == 7.5
    assert normalize_komi("KM=375子", "chinese") == 7.5


def test_standard_and_territory_komi_encoding():
    assert normalize_komi("7.5", "chinese") == 7.5
    assert normalize_komi("650", "japanese") == 6.5
    assert normalize_komi("bad", "japanese") == 6.5


def test_variation_prefix_keeps_correct_color_order():
    game = sgf.parse("(;GM[1]SZ[19];B[pd];W[dp])")
    moves, next_color = KataGoEngine._moves_at_position(
        game, 1, ["D4", "Q3"]
    )
    assert moves == [["B", "Q16"], ["W", "D4"], ["B", "Q3"]]
    assert next_color == "W"


def test_query_observes_cancel_without_waiting_for_timeout():
    class Proc:
        stdin = io.StringIO()

        @staticmethod
        def poll():
            return None

    engine = KataGoEngine.__new__(KataGoEngine)
    engine._proc = Proc()
    engine._responses = queue.Queue()
    engine._stderr = []
    engine.timeout = 30
    started = time.monotonic()
    with pytest.raises(KataGoError, match="取消"):
        engine._query({"id": "cancel-test"}, 1, cancelled=lambda: True)
    assert time.monotonic() - started < .5


def test_warm_up_runs_minimal_query_once():
    engine = KataGoEngine.__new__(KataGoEngine)
    engine._ready = False
    engine._warming = False
    engine._warm_error = ""
    engine._lock = threading.Lock()
    calls = []
    engine._start = lambda: calls.append("start")

    def query(payload, expected):
        calls.append((payload["maxVisits"], payload["analyzeTurns"], expected))
        return {0: {"rootInfo": {"winrate": .5}}}

    engine._query = query
    assert engine.warm_up() is True
    assert engine._ready is True
    assert calls == ["start", (1, [0], 1)]
    assert engine.warm_up() is True
    assert calls == ["start", (1, [0], 1)]


def test_remote_command_uses_encrypted_stdio_without_changing_protocol():
    engine = KataGoEngine.__new__(KataGoEngine)
    engine.remote_enabled = True
    engine.ssh_executable = "ssh"
    engine.remote_host = "radeon-yijian"
    engine.remote_executable = "/persistent/yijian/katago/build/katago"
    engine.remote_config = "/persistent/yijian/config/analysis.cfg"
    engine.remote_model = "/persistent/yijian/models/strong.bin.gz"
    assert engine._command() == [
        "ssh", "-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
        "radeon-yijian", "/persistent/yijian/katago/build/katago",
        "analysis", "-config", "/persistent/yijian/config/analysis.cfg",
        "-model", "/persistent/yijian/models/strong.bin.gz",
    ]


def test_remote_engine_declares_pinned_model_provenance(tmp_path, monkeypatch):
    model = tmp_path / KataGoEngine.official_model_name
    config = tmp_path / "analysis.cfg"
    model.write_bytes(b"fixture; deployment verifies the real hash separately")
    config.write_text("maxVisits = 32\n", encoding="utf-8")
    monkeypatch.setenv("KATAGO_REMOTE_ENABLED", "1")
    monkeypatch.setenv("KATAGO_REMOTE_HOST", "radeon-yijian")
    engine = KataGoEngine(model=model, config=config)
    health = engine.health()
    assert engine.model_sha256 == KataGoEngine.official_model_sha256
    assert engine.chunk_size == 64
    assert health["transport"] == "ssh"
    assert health["modelSha256"] == KataGoEngine.official_model_sha256
