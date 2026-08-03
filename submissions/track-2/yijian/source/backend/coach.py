# -*- coding: utf-8 -*-
"""确定性教学人格引擎：不改动 KataGo 证据，只改变讲解方式。"""

from __future__ import annotations

from copy import deepcopy

from reports import RANKS, normalize_rank
from terminology import select_terms


PERSONAS = {
    "enlightenment": {
        "name": "启蒙导师",
        "description": "耐心拆成小步骤，尽量不用生硬术语。",
    },
    "principles": {
        "name": "棋理导师",
        "description": "兼顾棋理与变化，适合大多数棋友。",
    },
    "practical": {
        "name": "实战教练",
        "description": "直指损失与改进动作，强调训练可执行性。",
    },
    "professional": {
        "name": "职业研究员",
        "description": "高密度讨论全局、目数效率与复杂变化。",
    },
    "sparring": {
        "name": "对弈陪练",
        "description": "先提问引导判断，再揭示证据和推荐变化。",
    },
}

DEFAULT_SETTINGS = {
    "persona": "principles",
    "terminologyDensity": "medium",
    "explanationLength": "standard",
    "variationDepth": 6,
    "studentRank": "amateur_5d",
    "studentAge": None,
    "playerName": "",
    "playerAliases": [],
    "lastPerspective": None,
    "mentorMode": "baseline",
}


def normalize_settings(value: dict | None) -> dict:
    settings = {**DEFAULT_SETTINGS, **(value or {})}
    if settings["persona"] not in PERSONAS:
        settings["persona"] = DEFAULT_SETTINGS["persona"]
    if settings["terminologyDensity"] not in ("low", "medium", "high"):
        settings["terminologyDensity"] = "medium"
    if settings["explanationLength"] not in ("brief", "standard", "detailed"):
        settings["explanationLength"] = "standard"
    try:
        settings["variationDepth"] = min(20, max(1, int(settings["variationDepth"])))
    except (TypeError, ValueError):
        settings["variationDepth"] = 6
    age = settings.get("studentAge")
    settings["studentAge"] = min(100, max(4, int(age))) if str(age or "").isdigit() else None
    settings["studentRank"] = normalize_rank(settings.get("studentRank"))
    settings["playerName"] = str(settings.get("playerName") or "")[:80]
    aliases = settings.get("playerAliases")
    settings["playerAliases"] = list(dict.fromkeys(
        str(item).strip()[:80] for item in aliases if str(item).strip()
    ))[:30] if isinstance(aliases, list) else []
    settings["lastPerspective"] = (
        settings.get("lastPerspective")
        if settings.get("lastPerspective") in ("B", "W") else None
    )
    if settings.get("mentorMode") not in ("baseline", "local", "cloud", "compare"):
        settings["mentorMode"] = "baseline"
    return settings


def preview(settings: dict, position: dict | None = None, evidence: dict | None = None,
            purpose: dict | None = None) -> dict:
    settings = normalize_settings(settings)
    evidence_copy = deepcopy(evidence or {})
    purpose_copy = deepcopy(purpose or {})
    turn = int((position or {}).get("turn", 0))
    player = (position or {}).get("toPlay", "黑")
    winrate = evidence_copy.get("winrate")
    score = evidence_copy.get("scoreLead")
    best = evidence_copy.get("bestMove") or "候选点"
    source = evidence_copy.get("source")
    demo = bool(evidence_copy.get("demo", source != "katago"))
    evidence_label = (
        "KataGo"
        if source == "katago" and not demo
        else ("演示分析" if demo else "分析")
    )
    evidence_separator = " " if evidence_label == "KataGo" else ""
    evidence_line = f"第 {turn} 手，轮到{player}。"
    if isinstance(winrate, (int, float)):
        evidence_line += f" {evidence_label}{evidence_separator}黑方胜率 {winrate:.1f}%"
    if isinstance(score, (int, float)):
        evidence_line += f"，黑方目差 {score:+.1f}"
    evidence_line += f"，首选 {best}。"

    name = PERSONAS[settings["persona"]]["name"]
    rank_name = RANKS[settings["studentRank"]]["name"]
    if settings["persona"] == "enlightenment":
        paragraphs = [
            evidence_line,
            f"先别急着找最难的变化。第一步看自己的弱棋，第二步看对方哪里最薄，第三步再比较 {best} 是否能一手兼顾。",
            "你可以先说出这手棋想保护什么；判断方向正确，比记住答案更重要。",
        ]
    elif settings["persona"] == "principles":
        paragraphs = [
            evidence_line,
            f"{best} 的价值不只在局部得分，还在于保持先手并照顾全局厚薄。复盘时应把实战手与这一候选点的后续方向并列比较。",
            "建议先判断双方弱棋，再核对局部变化是否成立。",
        ]
    elif settings["persona"] == "practical":
        paragraphs = [
            evidence_line,
            f"训练结论：把 {best} 列为第一候选。落子前固定执行“弱棋—大场—强制手”三项检查。",
            "如果实战手导致胜率或目差明显下降，就把错误归因到具体漏看，而不是笼统记成‘下得不好’。",
        ]
    elif settings["persona"] == "professional":
        paragraphs = [
            evidence_line,
            f"需要比较 {best} 与次选点在先手权、外势效率和转换后的目差分布。主变化深度按 {settings['variationDepth']} 手展开，同时保留对方最强抵抗。",
            "结论必须区分策略概率、访问次数和局面不确定性，不能把单一路径当成强制变化。",
        ]
    else:
        paragraphs = [
            f"第 {turn} 手先不看答案：如果只能选一个方向，你会优先补强、攻击，还是抢大场？为什么？",
            evidence_line,
            f"现在用 {best} 验证你的判断。再想一步：对方最强的反击在哪里？",
        ]

    length = settings["explanationLength"]
    if length == "brief":
        paragraphs = paragraphs[:2]
    elif length == "detailed":
        paragraphs.append(
            f"建议把推荐变化演算 {settings['variationDepth']} 手，并记录实战与推荐图在先后手、厚薄和目数上的三项差别。"
        )
    terms = select_terms(settings["terminologyDensity"], ["形势判断", "厚薄"])
    title = purpose_copy.get("title") or f"第 {turn} 手的作用"
    region = purpose_copy.get("region") or "当前区域"
    role = purpose_copy.get("role") or "改善局部效率并兼顾全局方向"
    own = int(purpose_copy.get("ownNearby") or 0)
    enemy = int(purpose_copy.get("enemyNearby") or 0)
    captured = int(purpose_copy.get("captured") or 0)
    purpose_line = (
        f"落在{region}，{role}。局部范围内检测到己方关联子 {own} 处、"
        f"对方关联子 {enemy} 处。"
    )
    if captured:
        purpose_line += f"棋盘规则可确认，本手实际提取对方 {captured} 子。"
    confidence = purpose_copy.get("confidence")
    if confidence == "heuristic":
        purpose_line += "关联与作用属于基于棋群位置的启发式判断，可结合推荐变化继续核对。"
    delta = purpose_copy.get("evidenceSummary")
    tradeoff_line = str(delta or "结合 KataGo 证据比较实战与首选在先手、厚薄和地盘转换上的差异。")
    next_line = str(purpose_copy.get("nextFocus") or "下一步先检查双方弱棋，再判断局部交换是否值得。")
    return {
        "persona": {"id": settings["persona"], **PERSONAS[settings["persona"]]},
        "settings": settings,
        "text": "\n\n".join(paragraphs),
        "paragraphs": paragraphs,
        "evidenceLine": evidence_line,
        "title": title,
        "analysisParagraphs": [purpose_line, tradeoff_line, next_line],
        "terms": terms,
        "rank": {"id": settings["studentRank"], "name": rank_name},
        # 原样返回，便于测试确认人格层没有篡改引擎证据。
        "evidence": evidence_copy,
        "purpose": purpose_copy,
    }
