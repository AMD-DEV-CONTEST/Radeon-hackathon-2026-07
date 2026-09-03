# -*- coding: utf-8 -*-
"""整盘复盘报告：阶段识别、段位容错、节点和四阶段评分。"""

from __future__ import annotations

import statistics
from copy import deepcopy

import sgf
from goboard import gtp_name, replay


RANKS = {
    "kyu_25_13": {"name": "25级–13级", "tolerance": 2.5},
    "kyu_12_1": {"name": "12级–1级", "tolerance": 2.0},
    "amateur_1d": {"name": "业余1段", "tolerance": 1.8},
    "amateur_2d": {"name": "业余2段", "tolerance": 1.6},
    "amateur_3d": {"name": "业余3段", "tolerance": 1.4},
    "amateur_4d": {"name": "业余4段", "tolerance": 1.2},
    "amateur_5d": {"name": "业余5段", "tolerance": 1.0},
    "amateur_6d": {"name": "业余6段", "tolerance": 0.8},
    "professional": {"name": "职业", "tolerance": 0.6},
}

LEGACY_RANKS = {
    "1段以下": "kyu_12_1", "1段": "amateur_1d", "2段": "amateur_2d",
    "3段": "amateur_3d", "4段": "amateur_4d", "5段": "amateur_5d",
    "6段": "amateur_6d", "7段": "amateur_6d", "8段": "amateur_6d",
    "9段": "amateur_6d", "职业": "professional",
}

PHASE_NAMES = {
    "joseki": "定式", "opening": "布局", "middle": "中盘", "endgame": "官子",
}


def normalize_rank(value: str | None) -> str:
    if value in RANKS:
        return value
    return LEGACY_RANKS.get(str(value or ""), "amateur_5d")


def thresholds(rank: str) -> dict:
    rank = normalize_rank(rank)
    factor = RANKS[rank]["tolerance"]
    return {
        "major": {"winrate": 10.0 * factor, "score": 5.0 * factor},
        "mistake": {"winrate": 5.0 * factor, "score": 2.5 * factor},
        "question": {"winrate": 2.0 * factor, "score": 1.5 * factor},
    }


def classify_loss(winrate_loss: float, score_loss: float, rank: str) -> str | None:
    values = thresholds(rank)
    for severity in ("major", "mistake", "question"):
        limit = values[severity]
        if winrate_loss >= limit["winrate"] or score_loss >= limit["score"]:
            return severity
    return None


def _xy(coord: str) -> tuple[int, int]:
    return ord(coord[0]) - 97, ord(coord[1]) - 97


def _is_local(state: bytes, coord: str, radius: int = 2) -> bool:
    x, y = _xy(coord)
    for yy in range(max(0, y - radius), min(19, y + radius + 1)):
        for xx in range(max(0, x - radius), min(19, x + radius + 1)):
            if (xx != x or yy != y) and state[yy * 19 + xx]:
                return True
    return False


def _quadrants_occupied(state: bytes) -> bool:
    quadrants = [False, False, False, False]
    for y in range(19):
        for x in range(19):
            if not state[y * 19 + x]:
                continue
            quadrants[(y >= 9) * 2 + (x >= 9)] = True
    return all(quadrants)


def _corner(coord: str) -> str | None:
    x, y = _xy(coord)
    if x < 7 and y < 7:
        return "upper-left"
    if x >= 12 and y < 7:
        return "upper-right"
    if x < 7 and y >= 12:
        return "lower-left"
    if x >= 12 and y >= 12:
        return "lower-right"
    return None


def detect_joseki(game: sgf.Game, states: list[bytes], layout_end: int) -> list[dict]:
    limit = min(80, layout_end)
    segments: list[dict] = []
    for corner in ("upper-left", "upper-right", "lower-left", "lower-right"):
        active: list[int] = []
        outside = 0
        for turn in range(1, limit + 1):
            move = game.moves[turn - 1]
            inside = (
                not move.is_pass
                and _corner(move.coord) == corner
                and _is_local(states[turn - 1], move.coord, 2)
            )
            if inside:
                active.append(turn)
                outside = 0
            elif active:
                outside += 1
                if outside >= 2:
                    if len(active) >= 4:
                        segments.append({
                            "corner": corner, "start": active[0], "end": active[-1],
                            "moves": active.copy(),
                        })
                    active, outside = [], 0
        if len(active) >= 4:
            segments.append({
                "corner": corner, "start": active[0], "end": active[-1],
                "moves": active.copy(),
            })
    return sorted(segments, key=lambda item: item["start"])


def preprocess_game(game: sgf.Game, states: list[bytes] | None = None) -> dict:
    """只用 CPU 和规则重放预计算布局边界与定式候选，可与 KataGo 扫描并行。"""
    if states is None:
        _, states = replay(game)
    total = len(game.moves)
    layout_end = None
    for turn in range(30, min(80, total - 6) + 1):
        if not _quadrants_occupied(states[turn]):
            continue
        local_count = sum(
            _is_local(states[index - 1], game.moves[index - 1].coord)
            for index in range(max(1, turn - 11), turn + 1)
        )
        if local_count < 8:
            continue
        persisted = sum(
            _is_local(states[index - 1], game.moves[index - 1].coord)
            for index in range(turn + 1, min(total, turn + 6) + 1)
        )
        if persisted >= min(4, max(0, total - turn)):
            layout_end = turn
            break
    if layout_end is None:
        layout_end = max(40, min(70, round(total * 0.25)))
        layout_end = min(layout_end, total)
    return {
        "states": states,
        "layoutEnd": layout_end,
        "joseki": detect_joseki(game, states, layout_end),
    }


def detect_phases(
    game: sgf.Game,
    analysis: dict,
    ownership_samples: dict[int, list[float]] | None = None,
    preprocessed: dict | None = None,
) -> dict:
    preprocessed = preprocessed or preprocess_game(game)
    states = preprocessed["states"]
    layout_end = int(preprocessed["layoutEnd"])
    total = len(game.moves)

    positions = analysis.get("positions") or []
    ownership_samples = ownership_samples or {}
    sample_turns = sorted(turn for turn in ownership_samples if 80 <= turn < total)
    endgame_start = None
    stable: dict[int, bool] = {}
    for turn in sample_turns:
        ownership = ownership_samples[turn]
        state = states[turn]
        empty_values = [
            abs(value) for index, value in enumerate(ownership[:361])
            if not state[index]
        ]
        settled = (
            sum(value >= 0.75 for value in empty_values) / max(1, len(empty_values))
            if empty_values else 1.0
        )
        start, stop = max(1, turn - 9), min(turn, len(positions) - 1)
        changes = [
            abs(float(positions[index].get("scoreLeadBlack", 0)) -
                float(positions[index - 1].get("scoreLeadBlack", 0)))
            for index in range(start, stop + 1)
        ]
        stable[turn] = settled >= 0.72 and (statistics.median(changes) if changes else 0) <= 1.5
    for index, turn in enumerate(sample_turns[:-1]):
        if stable.get(turn) and stable.get(sample_turns[index + 1]):
            endgame_start = turn
            break
    if endgame_start is None:
        endgame_start = max(100, round(total * 0.68))
    endgame_start = max(layout_end + 1, min(endgame_start, total))

    return {
        "opening": {"start": 1, "end": layout_end},
        "middle": {"start": min(total, layout_end + 1), "end": max(layout_end, endgame_start - 1)},
        "endgame": {"start": endgame_start, "end": total},
        "joseki": preprocessed["joseki"],
    }


def _loss_for_move(game: sgf.Game, positions: list[dict], turn: int) -> dict:
    move = game.moves[turn - 1]
    pre, post = positions[turn - 1], positions[turn]
    pre_wr, post_wr = float(pre["winrateBlack"]), float(post["winrateBlack"])
    pre_score = float(pre.get("scoreLeadBlack", 0))
    post_score = float(post.get("scoreLeadBlack", 0))
    if move.color == "B":
        wr_loss = max(0.0, (pre_wr - post_wr) * 100)
        score_loss = max(0.0, pre_score - post_score)
    else:
        wr_loss = max(0.0, (post_wr - pre_wr) * 100)
        score_loss = max(0.0, post_score - pre_score)
    recommendation = (pre.get("recommendations") or [{}])[0]
    return {
        "turn": turn, "color": move.color, "coord": move.coord,
        "winrateLoss": round(wr_loss, 2), "scoreLoss": round(score_loss, 2),
        "actualMove": gtp_name(move.coord, game.size) if not move.is_pass else "pass",
        "recommendedMove": recommendation.get("move") or pre.get("bestMove"),
        "pv": list(recommendation.get("pv") or [])[:10],
        "deepened": False,
    }


def _phase_turns(phases: dict, channel: str) -> set[int]:
    if channel == "joseki":
        return {turn for segment in phases["joseki"] for turn in segment["moves"]}
    phase = phases[channel]
    return set(range(phase["start"], phase["end"] + 1))


def _group_at(state: bytes, size: int, start: tuple[int, int]) -> tuple[set[tuple[int, int]], set[tuple[int, int]]]:
    """从快照中提取棋群和气，供教学归因使用（不改动引擎证据）。"""
    x, y = start
    color = state[y * size + x]
    if not color:
        return set(), set()
    stack, seen, group, liberties = [start], {start}, set(), set()
    while stack:
        cx, cy = stack.pop()
        group.add((cx, cy))
        for nx, ny in ((cx - 1, cy), (cx + 1, cy), (cx, cy - 1), (cx, cy + 1)):
            if not (0 <= nx < size and 0 <= ny < size):
                continue
            value = state[ny * size + nx]
            if value == 0:
                liberties.add((nx, ny))
            elif value == color and (nx, ny) not in seen:
                seen.add((nx, ny))
                stack.append((nx, ny))
    return group, liberties


def _attach_analysis_evidence(
    evidence: dict,
    positions: list[dict],
    turn: int,
    player: str,
    analysis_source: str,
    demo: bool,
) -> dict:
    if turn < len(positions):
        pre, post = positions[turn - 1], positions[turn]
        if (
            isinstance(pre.get("winrateBlack"), (int, float))
            and isinstance(post.get("winrateBlack"), (int, float))
        ):
            black_delta = float(post["winrateBlack"]) - float(pre["winrateBlack"])
            score_delta = (
                float(post.get("scoreLeadBlack", 0))
                - float(pre.get("scoreLeadBlack", 0))
            )
            player_sign = 1 if player == "B" else -1
            evidence["winrateLoss"] = round(
                max(0, -black_delta * player_sign * 100),
                2,
            )
            evidence["scoreLoss"] = round(
                max(0, -score_delta * player_sign),
                2,
            )
        recommendation = (pre.get("recommendations") or [{}])[0]
        evidence["bestMove"] = recommendation.get("move") or pre.get("bestMove")
        evidence["pv"] = list(recommendation.get("pv") or [])[:10]
    if analysis_source == "katago" and not demo:
        evidence["evidenceSource"].append("katago")
    elif analysis_source == "mock":
        evidence["evidenceSource"].append("mock")
    else:
        evidence["evidenceSource"].append("analysis_unknown")
    evidence["confidence"] = (
        "high"
        if evidence["bestMove"] and analysis_source == "katago" and not demo
        else "medium"
    )
    return evidence


def build_move_purpose_evidence(
    game: sgf.Game,
    states: list[bytes],
    positions: list[dict],
    turn: int,
    *,
    analysis_source: str = "unknown",
    demo: bool = True,
) -> dict:
    """构造可审计的 MovePurposeEvidence。

    规则字段来自服务端合法重放；数值字段只有在明确标记为真实 KataGo 时
    才声明 ``katago`` 来源。启发式字段不冒充引擎直接输出。
    """
    if turn < 1 or turn > len(game.moves) or turn >= len(states):
        raise ValueError("turn out of range")
    move = game.moves[turn - 1]
    player = move.color
    color = 1 if player == "B" else 2
    enemy = 2 if color == 1 else 1
    before, after = states[turn - 1], states[turn]
    evidence = {
        "move": gtp_name(move.coord, game.size) if not move.is_pass else "pass",
        "player": player,
        "connectedGroups": 0,
        "adjacentOpponentGroups": 0,
        "captures": 0,
        "libertiesBeforeAfter": {"own": [0, 0], "opponent": [0, 0]},
        "connection": False,
        "cut": False,
        "defense": False,
        "attack": False,
        "territoryDelta": None,
        "ownershipDelta": None,
        "winrateLoss": None,
        "scoreLoss": None,
        "bestMove": None,
        "pv": [],
        "confidence": "low",
        "evidenceSource": ["board_rules"],
    }
    if move.is_pass:
        return _attach_analysis_evidence(
            evidence, positions, turn, player, analysis_source, demo
        )
    x, y = _xy(move.coord)
    neighbors = [(nx, ny) for nx, ny in
                 ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1))
                 if 0 <= nx < game.size and 0 <= ny < game.size]
    own_before, opp_before = set(), set()
    own_after, opp_after = set(), set()
    for nx, ny in neighbors:
        value_before = before[ny * game.size + nx]
        value_after = after[ny * game.size + nx]
        if value_before == color:
            own_before.add(tuple(sorted(_group_at(before, game.size, (nx, ny))[0])))
        elif value_before == enemy:
            opp_before.add(tuple(sorted(_group_at(before, game.size, (nx, ny))[0])))
        if value_after == color:
            own_after.add(tuple(sorted(_group_at(after, game.size, (nx, ny))[0])))
        elif value_after == enemy:
            opp_after.add(tuple(sorted(_group_at(after, game.size, (nx, ny))[0])))
    own_group_after, own_lib_after = _group_at(after, game.size, (x, y))
    own_lib_before = set()
    for nx, ny in neighbors:
        if before[ny * game.size + nx] == color:
            own_lib_before |= _group_at(before, game.size, (nx, ny))[1]
    opp_lib_before = set()
    for group in opp_before:
        if group:
            opp_lib_before |= set(
                (gx, gy) for gx, gy in _group_at(before, game.size, group[0])[1]
            )
    opp_lib_after = set()
    for group in opp_after:
        if group:
            opp_lib_after |= set(
                (gx, gy) for gx, gy in _group_at(after, game.size, group[0])[1]
            )
    captures_before = sum(1 for value in before if value == enemy)
    captures_after = sum(1 for value in after if value == enemy)
    evidence.update({
        "connectedGroups": len(own_before),
        "adjacentOpponentGroups": len(opp_before),
        "captures": max(0, captures_before - captures_after),
        "libertiesBeforeAfter": {
            "own": [len(own_lib_before), len(own_lib_after)],
            "opponent": [len(opp_lib_before), len(opp_lib_after)],
        },
        "connection": len(own_before) >= 2,
        "cut": len(opp_before) >= 2,
        # A newly played isolated stone naturally has liberties; that alone is
        # not evidence that it reinforced an existing friendly group.  Keep
        # these two labels conservative and require direct board contact.
        "defense": len(own_before) >= 1,
        "attack": len(opp_before) >= 1,
    })
    return _attach_analysis_evidence(
        evidence, positions, turn, player, analysis_source, demo
    )


# 保留模块内旧名称，避免尚未迁移的调用方绕过新的来源参数。
_purpose_evidence = build_move_purpose_evidence


def build_raw_report(
    game: sgf.Game,
    analysis: dict,
    perspective: str,
    ownership_samples: dict[int, list[float]] | None = None,
    preprocessed: dict | None = None,
) -> dict:
    perspective = "W" if perspective == "W" else "B"
    preprocessed = preprocessed or preprocess_game(game)
    phases = detect_phases(
        game, analysis, ownership_samples, preprocessed=preprocessed
    )
    states = preprocessed["states"]
    positions = analysis["positions"]
    losses = [
        _loss_for_move(game, positions, turn)
        for turn in range(1, len(game.moves) + 1)
        if game.moves[turn - 1].color == perspective
    ]
    for node in losses:
        node["purposeEvidence"] = build_move_purpose_evidence(
            game,
            states,
            positions,
            node["turn"],
            analysis_source=str(analysis.get("source") or "unknown"),
            demo=bool(analysis.get("demo", True)),
        )
    channels = {}
    candidate_turns: set[int] = set()
    for channel in ("joseki", "opening", "middle", "endgame"):
        turns = _phase_turns(phases, channel)
        values = [item for item in losses if item["turn"] in turns]
        values.sort(key=lambda item: (max(item["winrateLoss"] / 10, item["scoreLoss"] / 5), item["turn"]), reverse=True)
        channels[channel] = [item["turn"] for item in values]
        candidate_turns.update(item["turn"] for item in values[:3])

    final_winner = "B" if str(game.info.get("RE", "")).upper().startswith("B+") else "W"
    decisive = None
    for turn, position in enumerate(positions):
        winner_wr = position["winrateBlack"] if final_winner == "B" else 1 - position["winrateBlack"]
        future = positions[turn:min(len(positions), turn + 11)]
        if winner_wr >= 0.8 and len(future) >= min(10, len(positions) - turn):
            if all((item["winrateBlack"] if final_winner == "B" else 1 - item["winrateBlack"]) >= 0.7 for item in future):
                decisive = turn
                break
    turning = []
    for turn in range(1, len(positions) - 2):
        before = positions[turn - 1]["winrateBlack"] - 0.5
        after = positions[turn]["winrateBlack"] - 0.5
        if before * after < 0:
            side = 1 if after > 0 else -1
            if all((positions[index]["winrateBlack"] - 0.5) * side > 0 for index in range(turn, min(turn + 3, len(positions)))):
                turning.append(turn)

    return {
        "perspective": perspective,
        "game": {
            "black": game.info.get("PB", "？"), "white": game.info.get("PW", "？"),
            "result": game.info.get("RE", "？"), "date": game.info.get("DT", ""),
            "moveCount": len(game.moves), "boardSize": game.size,
        },
        "phases": phases,
        "positions": positions,
        "losses": losses,
        "channels": channels,
        "candidateTurns": sorted(candidate_turns),
        "turningPoints": turning,
        "decisiveTurn": decisive,
        "engine": {
            "source": analysis.get("source") or "unknown",
            "demo": bool(analysis.get("demo", True)),
            "label": analysis.get("label"),
            "version": analysis.get("engineVersion"),
            "model": analysis.get("model"),
            "modelSha256": analysis.get("modelSha256"),
            "backend": analysis.get("backend"),
            "transport": analysis.get("transport", "local-process"),
            "visits": analysis.get("scanVisits", analysis.get("visits", 32)),
            "criticalVisits": analysis.get("criticalVisits", 128),
            "deepNodeVisits": analysis.get("deepNodeVisits", 128),
            "analysisMode": analysis.get("analysisMode", "fast"),
        },
    }


def apply_deep_result(
    raw: dict, turn: int, pre: dict, post: dict, *,
    visits: int = 128,
    confidence: str = "medium",
    analysis_source: str | None = None,
    demo: bool | None = None,
    engine_version: str | None = None,
    engine_model: str | None = None,
) -> None:
    node = next((item for item in raw["losses"] if item["turn"] == turn), None)
    if not node:
        return
    node.setdefault("fastWinrateLoss", node["winrateLoss"])
    node.setdefault("fastScoreLoss", node["scoreLoss"])
    if node["color"] == "B":
        node["winrateLoss"] = round(max(0, (pre["winrateBlack"] - post["winrateBlack"]) * 100), 2)
        node["scoreLoss"] = round(max(0, pre["scoreLeadBlack"] - post["scoreLeadBlack"]), 2)
    else:
        node["winrateLoss"] = round(max(0, (post["winrateBlack"] - pre["winrateBlack"]) * 100), 2)
        node["scoreLoss"] = round(max(0, post["scoreLeadBlack"] - pre["scoreLeadBlack"]), 2)
    recommendation = (pre.get("recommendations") or [{}])[0]
    node["recommendedMove"] = recommendation.get("move")
    node["pv"] = list(recommendation.get("pv") or [])[:10]
    node["deepVisits"] = visits
    node["confidence"] = confidence
    node["stability"] = "confirmed" if confidence == "high" else "review"
    node["deepened"] = True
    engine = raw.get("engine", {})
    source = analysis_source or engine.get("source") or "unknown"
    is_demo = (
        (bool(demo) if demo is not None else bool(engine.get("demo", False)))
        or source != "katago"
    )
    node["deepAnalysis"] = {
        "source": source,
        "demo": is_demo,
        "visits": visits,
        "version": engine_version or engine.get("version"),
        "model": engine_model or engine.get("model"),
    }
    positions = raw.get("positions") or []
    if turn < len(positions):
        positions[turn - 1] = {**positions[turn - 1], **pre}
        positions[turn] = {**positions[turn], **post}
    purpose = node.get("purposeEvidence")
    if isinstance(purpose, dict):
        purpose["winrateLoss"] = node["winrateLoss"]
        purpose["scoreLoss"] = node["scoreLoss"]
        purpose["bestMove"] = node["recommendedMove"]
        purpose["pv"] = node["pv"]
        sources = [
            item
            for item in purpose.get("evidenceSource", [])
            if item not in ("katago", "mock", "analysis_unknown")
        ]
        sources.append(
            "katago"
            if source == "katago" and not is_demo
            else ("mock" if source == "mock" else "analysis_unknown")
        )
        purpose["evidenceSource"] = sources
        purpose["confidence"] = confidence
        purpose["deepVisits"] = visits


def _grade(score: int) -> str:
    if score >= 90:
        return "优秀"
    if score >= 80:
        return "稳健"
    if score >= 70:
        return "有波动"
    if score >= 60:
        return "明显失分"
    return "重点复盘"


def _score(items: list[dict], rank: str) -> dict:
    factor = RANKS[normalize_rank(rank)]["tolerance"]
    units = [
        min(2.0, max(item["winrateLoss"] / (10 * factor), item["scoreLoss"] / (5 * factor)))
        for item in items
    ]
    worst = sorted(units, reverse=True)[:3] + [0, 0, 0]
    average = sum(units) / len(units) if units else 0
    value = round(max(0, 100 - 20 * worst[0] - 12 * worst[1] - 8 * worst[2] - 10 * average))
    return {"score": value, "grade": _grade(value), "moveCount": len(items)}


def render_report(raw_report: dict, rank: str) -> dict:
    rank = normalize_rank(rank)
    report = deepcopy(raw_report)
    engine = report.setdefault("engine", {})
    if not engine.get("source"):
        engine["source"] = (
            "katago"
            if engine.get("version") and engine.get("model") and engine.get("backend")
            else "unknown"
        )
        engine["provenanceStatus"] = "legacy_inferred"
    if "demo" not in engine:
        engine["demo"] = engine["source"] != "katago"
    else:
        engine["demo"] = bool(engine["demo"]) or engine["source"] != "katago"
    normalized_analysis_source = (
        "katago"
        if engine["source"] == "katago" and not engine["demo"]
        else ("mock" if engine["source"] == "mock" else "analysis_unknown")
    )
    for node in report["losses"]:
        purpose = node.get("purposeEvidence")
        if isinstance(purpose, dict):
            sources = [
                item
                for item in purpose.get("evidenceSource", [])
                if item not in ("katago", "mock", "analysis_unknown")
            ]
            sources.append(normalized_analysis_source)
            purpose["evidenceSource"] = list(dict.fromkeys(sources))
        node["severity"] = classify_loss(node["winrateLoss"], node["scoreLoss"], rank)
        node["phaseTags"] = [
            PHASE_NAMES[channel] for channel in ("joseki", "opening", "middle", "endgame")
            if node["turn"] in set(report["channels"].get(channel, []))
        ]
    stage_cards = {}
    for channel in ("joseki", "opening", "middle", "endgame"):
        turns = set(report["channels"].get(channel, []))
        values = [item for item in report["losses"] if item["turn"] in turns]
        scored = _score(values, rank)
        visible = [item for item in values if item.get("severity")]
        visible.sort(key=lambda item: max(item["winrateLoss"] / 10, item["scoreLoss"] / 5), reverse=True)
        stage_cards[channel] = {
            "id": channel, "name": PHASE_NAMES[channel], **scored,
            "keyNodes": visible[:3],
            "maxError": visible[0] if visible else None,
            "bestTreatment": (
                f"第{visible[0]['turn']}手优先比较 {visible[0].get('recommendedMove') or '首选变化'}"
                if visible else "本阶段没有达到当前棋力标准的错误节点"
            ),
            "trainingTheme": {
                "joseki": "理解局部交换与脱先时机",
                "opening": "建立全局方向与大场顺序",
                "middle": "加强弱棋、攻防与转换判断",
                "endgame": "训练先后手和官子价值计算",
            }[channel],
        }
    report["rank"] = {"id": rank, **RANKS[rank], "thresholds": thresholds(rank)}
    report["stageCards"] = stage_cards
    report["visibleNodes"] = [
        item for item in report["losses"] if item.get("severity")
    ]
    report["visibleNodes"].sort(
        key=lambda item: max(item["winrateLoss"] / 10, item["scoreLoss"] / 5),
        reverse=True,
    )
    report["summary"] = {
        "result": report.get("game", {}).get("result", "？"),
        "decisiveTurn": report.get("decisiveTurn"),
        "mainProblems": [
            {
                "turn": item["turn"], "severity": item["severity"],
                "phaseTags": item["phaseTags"], "recommendedMove": item.get("recommendedMove"),
            }
            for item in report["visibleNodes"][:3]
        ],
        "trainingSuggestions": list(dict.fromkeys(
            card["trainingTheme"] for card in stage_cards.values()
            if card["keyNodes"]
        ))[:3],
    }
    return report
