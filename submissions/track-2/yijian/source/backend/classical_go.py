# -*- coding: utf-8 -*-
"""可追溯的公版古典棋理短句；只作教学表达参考，不构成局面事实。"""

from __future__ import annotations

from copy import deepcopy


PRINCIPLES = (
    {
        "id": "qijing-plan-before-shape",
        "maxim": "计定于内而势成于外",
        "work": "棋经十三篇·得算篇",
        "author": "张拟",
        "era": "北宋",
        "sourceUrl": "https://zh.wikisource.org/wiki/棋經十三篇",
        "license": "public-domain",
        "tags": ("全局", "方向", "计划", "布局", "势"),
        "gloss": "先明确全局目标，再判断局部着法是否真的服务于这个目标。",
    },
    {
        "id": "qijing-adapt-to-opponent",
        "maxim": "以正合其势，以权制其敌",
        "work": "棋经十三篇·得算篇",
        "author": "张拟",
        "era": "北宋",
        "sourceUrl": "https://zh.wikisource.org/wiki/棋經十三篇",
        "license": "public-domain",
        "tags": ("应对", "灵活", "变化", "攻防", "比较"),
        "gloss": "先守住棋形的正理，再依据对方强弱灵活选择手段。",
    },
    {
        "id": "qijing-finish-before-moving",
        "maxim": "施行未成，不可先动",
        "work": "棋经十三篇·杂说篇",
        "author": "张拟",
        "era": "北宋",
        "sourceUrl": "https://zh.wikisource.org/wiki/棋經十三篇",
        "license": "public-domain",
        "tags": ("未活", "薄", "补强", "安定", "联络", "弱棋"),
        "gloss": "己方棋形尚未安定时，先检查弱点，再决定是否转向别处。",
    },
    {
        "id": "qijing-compare-strength",
        "maxim": "强弱相形，利害相倾，不可不察",
        "work": "棋经十三篇·杂说篇",
        "author": "张拟",
        "era": "北宋",
        "sourceUrl": "https://zh.wikisource.org/wiki/棋經十三篇",
        "license": "public-domain",
        "tags": ("强弱", "得失", "比较", "棋块", "攻防", "外势"),
        "gloss": "判断得失不能只看落点，要同时比较双方棋块的强弱变化。",
    },
    {
        "id": "dunhuang-invade-with-sente",
        "maxim": "入境侵疆，常存先手",
        "work": "敦煌棋经",
        "author": "佚名",
        "era": "北周",
        "sourceUrl": "https://zh.wikisource.org/wiki/敦煌棋經",
        "license": "public-domain",
        "tags": ("侵", "入", "外搬", "角部", "边上", "先手", "腾挪"),
        "gloss": "进入对方势力范围时，要同时检查后续先手、退路和腾挪余地。",
    },
)


def _candidate_text(candidate: dict | None) -> str:
    if not isinstance(candidate, dict):
        return ""
    region = candidate.get("region")
    heuristics = candidate.get("heuristics")
    rules = candidate.get("rules")
    values = [
        region.get("label") if isinstance(region, dict) else region,
        heuristics.get("role") if isinstance(heuristics, dict) else "",
        rules.get("connection") if isinstance(rules, dict) else "",
    ]
    return " ".join(str(value or "") for value in values)


def match_principle(
    question: str,
    target_kind: str,
    candidates: dict | None,
) -> dict:
    """按问题与服务端候选证据匹配一条古训；匹配本身是教学启发式。"""
    candidates = candidates if isinstance(candidates, dict) else {}
    if target_kind == "comparison":
        text = "比较 " + _candidate_text(candidates.get("actual"))
        text += " " + _candidate_text(candidates.get("best"))
    else:
        text = _candidate_text(candidates.get(target_kind))
    haystack = f"{question} {text}"
    scored = []
    for principle in PRINCIPLES:
        score = sum(1 for tag in principle["tags"] if tag in haystack)
        if score:
            scored.append((score, principle))
    if not scored:
        return {}
    scored.sort(key=lambda item: item[0], reverse=True)
    result = deepcopy(scored[0][1])
    result["confidence"] = "heuristic"
    result["source"] = "classical_go.match_principle"
    return result

