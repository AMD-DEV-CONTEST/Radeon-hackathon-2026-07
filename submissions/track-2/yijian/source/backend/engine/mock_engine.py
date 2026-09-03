# -*- coding: utf-8 -*-
"""Mock KataGo 引擎 —— W1 开发/演示用。

- 输出结构与真实 KataGoEngine 完全一致（见 base.py），前端与测试可无缝切换
- 完全确定性：同一棋谱两次分析结果逐字节相同（无真实时间/随机源）
- 所有结果 demo=True，前端必须展示「演示」标注 —— 不冒充真实引擎数据

对 AlphaGo–李世石 G4 内置了一条按公开赛评走势手工设定的演示锚点曲线
（第 78 手白 L11 后黑胜率崩落），其余棋谱用哈希种子生成中性演示曲线。
"""

import hashlib
import math

from .base import AnalysisEngine

# AlphaGo G4 演示锚点：[手数, 黑胜率%]。依据公开赛评的走势手工设定，仅供演示。
_G4_ANCHORS = [
    (0, 50), (10, 49), (20, 52), (30, 54), (40, 53), (50, 58), (60, 64),
    (70, 68), (77, 70), (78, 58), (80, 52), (83, 44), (85, 34), (87, 23),
    (90, 18), (95, 15), (100, 13), (110, 10), (120, 9), (135, 7.5),
    (150, 6), (165, 4.5), (180, 3),
]


def _seeded_noise(seed: int, i: int) -> float:
    x = math.sin((i + 1) * 127.1 + seed * 311.7) * 43758.5453
    return (x - math.floor(x) - 0.5) * 1.6  # ±0.8 个百分点


def _interp(anchors, m):
    for j in range(len(anchors) - 1):
        x0, y0 = anchors[j]
        x1, y1 = anchors[j + 1]
        if x0 <= m <= x1:
            t = 0 if x1 == x0 else (m - x0) / (x1 - x0)
            return y0 + (y1 - y0) * t
    return anchors[-1][1]


def _is_alphago_g4(game) -> bool:
    return (len(game.moves) == 180 and game.moves[77].coord == "ki"
            and game.info.get("RE") == "W+Resign")


class MockKataGoEngine(AnalysisEngine):

    name = "mock"
    version = "public-fixture-v1"
    model_name = "deterministic-mock"

    def analyze_game(self, game) -> dict:
        n = len(game.moves)
        seed = int(hashlib.sha256(
            " ".join(m.coord for m in game.moves).encode()
        ).hexdigest()[:8], 16)

        winrates = []
        if _is_alphago_g4(game):
            label = "演示数据（Mock 引擎 · AlphaGo G4 手工锚点，非真实 KataGo 分析）"
            for m in range(n + 1):
                w = _interp(_G4_ANCHORS, m) + _seeded_noise(seed, m)
                winrates.append(min(0.99, max(0.01, w / 100)))
        else:
            label = "演示数据（Mock 引擎 · 哈希种子生成，非真实 KataGo 分析）"
            for m in range(n + 1):
                drift = 8 * math.sin(m / 23 + seed % 7)  # 缓慢摆动的中性曲线
                w = 50 + drift + _seeded_noise(seed, m)
                winrates.append(min(0.99, max(0.01, w / 100)))

        positions = [
            {"turn": m, "winrateBlack": round(winrates[m], 4),
             "scoreLeadBlack": round((winrates[m] - 0.5) * 20, 2)}
            for m in range(n + 1)
        ]
        return {
            "source": self.name,
            "demo": True,
            "label": label,
            "positions": positions,
            "keyMoves": self.extract_key_moves(game, winrates),
        }

    def analyze_position(
        self, game, turn, variation=None, visits=None,
        include_ownership=False, cancelled=None,
    ) -> dict:
        """Return deterministic demo-only candidate data for offline reproduction.

        This deliberately does not pretend to be KataGo. It exists so the public
        no-model fallback can exercise the same Agent and validator contracts in
        a clean environment.
        """
        del cancelled
        variation = [str(move).upper() for move in (variation or [])]
        visits = int(visits or 16)
        clamped_turn = max(0, min(int(turn), len(game.moves)))
        seed_text = "|".join((
            str(game.size),
            str(clamped_turn),
            ",".join(variation),
            " ".join(move.coord for move in game.moves),
        ))
        seed = int(hashlib.sha256(seed_text.encode("utf-8")).hexdigest()[:8], 16)
        occupied = {
            move.coord for move in game.moves[:clamped_turn]
            if not move.is_pass
        }
        candidates = [
            coord for coord in (
                "D4", "Q16", "D16", "Q4", "K10", "C3", "R17",
            )
            if coord.lower() not in occupied and coord not in variation
        ]
        if len(candidates) < 3:
            candidates.extend(["PASS"] * (3 - len(candidates)))
        offset = seed % len(candidates)
        ordered = candidates[offset:] + candidates[:offset]
        base = 0.46 + (seed % 900) / 10000
        recommendations = []
        for rank, move in enumerate(ordered[:3]):
            reply = ordered[(rank + 1) % len(ordered)]
            recommendations.append({
                "move": move,
                "winrateBlack": round(min(0.60, base - rank * 0.01), 4),
                "scoreLeadBlack": round(
                    (base - 0.5) * 20 - rank * 0.2, 2
                ),
                "visits": max(1, visits // (rank + 1)),
                "pv": [move, reply],
            })
        result = {
            "source": self.name,
            "demo": True,
            "recommendations": recommendations,
            "winrateBlack": round(base, 4),
            "scoreLeadBlack": round((base - 0.5) * 20, 2),
            "visits": visits,
            "komi": 7.5,
        }
        if include_ownership:
            result["ownership"] = [0.0] * (game.size * game.size)
        return result
