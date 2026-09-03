# -*- coding: utf-8 -*-
"""分析引擎抽象层 —— 弈鉴 GoMentor

统一接口，两个实现：
- MockKataGoEngine：W1 开发用，确定性演示数据（所有输出标注 demo）
- KataGoEngine：包装真实 KataGo analysis 模式，
  走 JSON 协议（query: id/moves/rules/komi/analyzeTurns → response: turnNumber/
  rootInfo.winrate/scoreLead/moveInfos），输出结构与 Mock 完全一致，前端无感切换。

分析结果结构（dict，可直接 JSON 序列化）：
{
  "source":  "mock" | "katago",
  "demo":    bool,                 # True = 演示数据，前端必须显示「演示」标注
  "label":   str,                  # 数据来源说明
  "positions": [                   # 每个局面一条，下标 = 手数（0 = 空盘）
    {"turn": int, "winrateBlack": float(0~1), "scoreLeadBlack": float}
  ],
  "keyMoves": [                    # 按胜率摆动绝对值降序
    {"number": int, "coord": str, "gtp": str, "color": "B"|"W",
     "deltaWinrate": float, "note": str}
  ]
}
"""

from abc import ABC, abstractmethod


class AnalysisEngine(ABC):

    @abstractmethod
    def analyze_game(self, game) -> dict:
        """全局分析 sgf.Game，返回上述结构。"""

    @staticmethod
    def extract_key_moves(game, winrates, top_n: int = 5) -> list:
        """从胜率曲线提取关键手：单手黑胜率摆动绝对值最大的 top_n 手。

        winrates: 长度 = len(moves)+1 的黑胜率序列（0~1）。
        """
        from goboard import gtp_name

        deltas = []
        for i, mv in enumerate(game.moves, start=1):
            d = winrates[i] - winrates[i - 1]
            deltas.append((abs(d), d, mv))
        deltas.sort(key=lambda t: -t[0])
        out = []
        for _, d, mv in deltas[:top_n]:
            side = "黑" if mv.color == "B" else "白"
            gained = (d > 0) == (mv.color == "B")
            out.append({
                "number": mv.number,
                "coord": mv.coord,
                "gtp": gtp_name(mv.coord, game.size) if not mv.is_pass else "pass",
                "color": mv.color,
                "deltaWinrate": round(d, 4),
                "note": f"{side}方第 {mv.number} 手，黑胜率{'上升' if d > 0 else '下降'} "
                        f"{abs(d) * 100:.1f} 个百分点"
                        + ("" if gained else "，本方局势受损"),
            })
        return out
