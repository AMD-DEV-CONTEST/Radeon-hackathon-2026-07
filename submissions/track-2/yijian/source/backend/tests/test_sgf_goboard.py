# -*- coding: utf-8 -*-
"""SGF 解析 + 棋盘引擎回归测试。

回归基准：素材/AlphaGo-李世石-第四局.sgf（2016 DeepMind 挑战赛 G4，白中盘胜）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import sgf
from goboard import Board, IllegalMove, BLACK, WHITE, replay, gtp_name

SGF_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "recommendation-smoke.sgf")


@pytest.fixture(scope="module")
def game():
    return sgf.parse_file(SGF_PATH)


# ---------- SGF 解析 ----------

def test_metadata(game):
    assert game.info["PB"] == "推荐手验证-黑"
    assert game.info["PW"] == "推荐手验证-白"
    assert game.info["EV"] == "弈鉴功能验证"
    assert game.info["KM"] == "7.5"
    assert game.size == 19


def test_move_count_public_fixture(game):
    assert len(game.moves) == 10


def test_moves_alternate_no_pass(game):
    for i, mv in enumerate(game.moves):
        assert mv.color == ("B" if i % 2 == 0 else "W")
        assert not mv.is_pass
        assert mv.number == i + 1


def test_first_public_fixture_move(game):
    """The first public fixture move is black Q16."""
    mv = game.moves[0]
    assert mv.color == "B"
    assert mv.coord == "pd"
    assert gtp_name(mv.coord) == "Q16"


def test_variation_takes_main_line():
    g = sgf.parse("(;GM[1]SZ[19];B[pd](;W[dp];B[cd])(;W[qq]))")
    assert [m.coord for m in g.moves] == ["pd", "dp", "cd"]


def test_escaped_bracket():
    g = sgf.parse("(;GM[1]C[a \\] b];B[pd])")
    assert g.info["C"] == "a ] b"
    assert g.moves[0].coord == "pd"


# ---------- 棋盘引擎：手工用例 ----------

def test_corner_capture():
    b = Board(19)
    b.play(WHITE, "aa")
    b.play(BLACK, "ba")
    caps = b.play(BLACK, "ab")
    assert caps == [(0, 0)]
    assert b.captured[WHITE] == 1
    assert b.get(0, 0) == 0


def test_suicide_illegal():
    b = Board(19)
    b.play(BLACK, "ba")
    b.play(BLACK, "ab")
    with pytest.raises(IllegalMove):
        b.play(WHITE, "aa")
    assert b.get(0, 0) == 0  # 盘面已回滚


def test_occupied_illegal():
    b = Board(19)
    b.play(BLACK, "pd")
    with pytest.raises(IllegalMove):
        b.play(WHITE, "pd")


def test_simple_ko():
    b = Board(19)
    # 经典劫形：白提黑一子成劫后，黑不能立即回提
    for color, coord in [(BLACK, "ba"), (BLACK, "ab"), (WHITE, "ca"),
                         (WHITE, "bb"), (BLACK, "cb")]:
        b.play(color, coord)
    caps = b.play(WHITE, "aa")  # 白提黑 ba 一子，成劫
    assert caps == [(1, 0)]
    with pytest.raises(IllegalMove):
        b.play(BLACK, "ba")     # 黑立即回提 → 非法
    b.play(BLACK, "pp")         # 找劫材（随便一手）
    b.play(WHITE, "pq")
    b.play(BLACK, "ba")         # 现在可以回提
    assert b.get(0, 0) == 0


def test_pass_clears_ko_and_counts():
    b = Board(19)
    b.play(BLACK, "")
    assert b.move_count == 1


# ---------- AlphaGo G4 全局重放回归 ----------

def test_replay_full_game_no_error(game):
    board, states = replay(game)
    assert board.move_count == 10
    assert len(states) == 11

    # 不变量：盘上子数 + 双方被提数 = 总着手数（本局无 pass）
    stones = board.stones()
    total = stones[BLACK] + stones[WHITE] + board.captured[BLACK] + board.captured[WHITE]
    assert total == 10

    # 重放全程无零气组（逐手校验）
    b2 = Board(game.size)
    for mv in game.moves:
        b2.play(BLACK if mv.color == "B" else WHITE, mv.coord)
        for r in range(19):
            for c in range(19):
                if b2.get(c, r):
                    _, libs = b2.group_and_liberties(c, r)
                    assert libs, f"第 {mv.number} 手后 ({c},{r}) 无气"


def test_public_fixture_has_no_captures(game):
    """The public ten-move fixture contains no captures."""
    board, _ = replay(game)
    assert board.captured[BLACK] + board.captured[WHITE] == 0


def test_final_board_snapshot_stable(game):
    """终局盘面指纹固定 —— 防未来改动引擎时悄悄破坏重放结果。"""
    board, states = replay(game)
    import hashlib
    fp = hashlib.sha256(states[-1]).hexdigest()[:16]
    # 基准值经全部不变量校验 + JS 引擎(crosscheck.mjs)逐点对照后固化
    assert fp == "83e398bc29bb9326"
    print(f"\n[终局盘面指纹] {fp}")
    stones = board.stones()
    print(f"[盘面] 黑 {stones[BLACK]} 子，白 {stones[WHITE]} 子；"
          f"黑被提 {board.captured[BLACK]}，白被提 {board.captured[WHITE]}")
