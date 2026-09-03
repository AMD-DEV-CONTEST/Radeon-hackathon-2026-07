# -*- coding: utf-8 -*-
"""内置内容包。

经典棋谱均来自明确声明 public domain 的 Andries Brouwer 棋谱库。
近期职业棋谱采用编辑审核制：只有来源与再分发依据齐备后才会进入 RECENT。
"""

from __future__ import annotations

from pathlib import Path

from importers import import_bytes
from library import add_import


CONTENT = Path(__file__).resolve().parent.parent / "content" / "classics"
SOURCE_ROOT = "https://homepages.cwi.nl/~aeb/go/games/games/AlphaGo/"
RIGHTS = (
    "Public domain. Andries Brouwer states: “I do not claim any rights on this "
    "collection. The games here are in the public domain.”"
)

CLASSICS = [
    ("FanHui/1.sgf", "AlphaGo 首次公开击败欧洲冠军系列赛之一"),
    ("FanHui/2.sgf", "AlphaGo 与职业棋手早期里程碑对局"),
    ("FanHui/3.sgf", "人机围棋进入职业水平的代表对局"),
    ("FanHui/4.sgf", "Fan Hui 五番棋代表局"),
    ("FanHui/5.sgf", "Fan Hui 五番棋收官局"),
    ("LeeSedol/1.sgf", "李世石—AlphaGo 五番棋首局"),
    ("LeeSedol/2.sgf", "AlphaGo 第37手引发广泛讨论的名局"),
    ("LeeSedol/3.sgf", "五番棋第三局，AlphaGo 提前锁定比赛"),
    ("LeeSedol/4.sgf", "李世石以“神之一手”取胜的人机名局"),
    ("LeeSedol/5.sgf", "李世石—AlphaGo 五番棋最终局"),
    ("May2017/1.sgf", "乌镇围棋峰会柯洁—AlphaGo 第一局"),
    ("May2017/2.sgf", "乌镇围棋峰会柯洁—AlphaGo 第二局"),
    ("May2017/3.sgf", "乌镇人机配对赛代表局"),
    ("May2017/4.sgf", "乌镇人机团队赛代表局"),
    ("May2017/5.sgf", "乌镇围棋峰会柯洁—AlphaGo 最终局"),
    ("NewYear2017/T15.sgf", "Master 对朴廷桓的网络快棋名局"),
    ("NewYear2017/T18.sgf", "Master 对柯洁的代表对局"),
    ("NewYear2017/T19.sgf", "柯洁执黑挑战 Master"),
    ("NewYear2017/T20.sgf", "Master 再战朴廷桓"),
    ("NewYear2017/F32.sgf", "Master 对古力的网络名局"),
    ("NewYear2017/F33.sgf", "Master 与古力换先再战"),
    ("NewYear2017/F39.sgf", "Master 对井山裕太的代表局"),
    ("NewYear2017/F50.sgf", "柯洁再度挑战 Master"),
    ("NewYear2017/F57.sgf", "Master 对申真谞的早期代表局"),
    ("NewYear2017/F60.sgf", "Master 六十连胜系列收官局"),
]

# 二十个编辑位已预留，但在授权与来源原链没有核验完成前绝不打包棋谱正文。
RECENT_EDITORIAL_SLOTS = [
    {
        "slot": index,
        "status": "rights-review-required",
        "required": ["比赛日期须在同步时过去12个月内", "原始棋谱链接", "再分发许可依据", "编辑入选理由"],
    }
    for index in range(1, 21)
]


def seed_classics() -> int:
    created = 0
    for index, (relative_url, reason) in enumerate(CLASSICS, start=1):
        path = CONTENT / f"classic-{index:02d}.sgf"
        if not path.exists():
            continue
        game = import_bytes(path.read_bytes(), path.name)
        _, was_created = add_import(
            game,
            category="classics",
            source_url=SOURCE_ROOT + relative_url,
            rights=RIGHTS,
            reason=reason,
            is_user=False,
        )
        created += int(was_created)
    return created
