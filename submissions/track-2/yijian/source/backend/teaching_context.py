# -*- coding: utf-8 -*-
"""服务端权威教学上下文。

客户端只负责定位 ``gameId + turn + variation``。棋谱正文、合法盘面、KataGo
证据、规则事实和启发式判断均在服务端重新取得或重建，再交给 coach/mentor
表达层。该模块不接受客户端生成的棋力或棋理事实。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections import OrderedDict
from copy import deepcopy
from threading import RLock

import library
import reports
import sgf
from engine import KataGoEngine, KataGoError
from goboard import BLACK, WHITE, gtp_name, replay, sgf_to_xy


SCHEMA_VERSION = "teaching-context-v6"
EVIDENCE_PROJECTION_VERSION = "dual-move-candidates-v5-variation-adjudication"
VARIATION_EVIDENCE_VERSION = "variation-evidence-v3-group-role-semantics"
DEFAULT_BRANCH_VISITS = 32
MAX_BRANCH_REPLIES = 3
MAX_BRANCH_DEPTH = 8
MAX_VARIATION_MOVES = 40
_GTP_COLUMNS = "ABCDEFGHJKLMNOPQRSTUVWXYZ"
_GTP_RE = re.compile(r"^([A-HJ-Z])([1-9][0-9]?)$")
_CONTEXT_CACHE_LIMIT = 256
_CONTEXT_CACHE: OrderedDict[str, dict] = OrderedDict()
_CONTEXT_CACHE_LOCK = RLock()


class TeachingContextError(ValueError):
    """可映射为明确 HTTP 状态的上下文重建错误。"""

    def __init__(self, message: str, *, status_code: int = 400, code: str = "invalid_context"):
        super().__init__(message)
        self.status_code = status_code
        self.code = code


def _normalize_variation(value: list[str] | None, size: int) -> list[str]:
    if not value:
        return []
    if len(value) > MAX_VARIATION_MOVES:
        raise TeachingContextError(
            f"变化最多允许 {MAX_VARIATION_MOVES} 手",
            code="variation_too_long",
        )
    normalized: list[str] = []
    for raw in value:
        move = str(raw or "").strip().upper()
        if move in ("PASS", "TT"):
            normalized.append("pass")
            continue
        match = _GTP_RE.fullmatch(move)
        if not match:
            raise TeachingContextError(
                f"变化中包含无效坐标：{raw}",
                code="invalid_variation_coordinate",
            )
        column, row_text = match.groups()
        try:
            column_index = _GTP_COLUMNS.index(column)
        except ValueError as exc:
            raise TeachingContextError(
                f"变化中包含无效坐标：{raw}",
                code="invalid_variation_coordinate",
            ) from exc
        row = int(row_text)
        if column_index >= size or row < 1 or row > size:
            raise TeachingContextError(
                f"变化坐标超出 {size} 路棋盘：{raw}",
                code="variation_coordinate_out_of_range",
            )
        normalized.append(f"{column}{row}")
    return normalized


def _gtp_to_sgf(move: str, size: int) -> str:
    if move == "pass":
        return ""
    match = _GTP_RE.fullmatch(move)
    if not match:
        raise TeachingContextError(
            f"变化中包含无效坐标：{move}",
            code="invalid_variation_coordinate",
        )
    column, row_text = match.groups()
    x = _GTP_COLUMNS.index(column)
    y = size - int(row_text)
    return f"{chr(97 + x)}{chr(97 + y)}"


def _next_color(game: sgf.Game, turn: int) -> str:
    if turn < len(game.moves):
        return game.moves[turn].color
    if turn:
        return "W" if game.moves[turn - 1].color == "B" else "B"
    return "B"


def _xy_to_gtp(x: int, y: int, size: int) -> str:
    return f"{_GTP_COLUMNS[x]}{size - y}"


def _group_payload(board, x: int, y: int) -> dict:
    group, liberties = board.group_and_liberties(x, y)
    color = board.get(x, y)
    return {
        "color": "B" if color == BLACK else "W",
        "stones": len(group),
        "liberties": len(liberties),
        "stonePoints": sorted(
            _xy_to_gtp(px, py, board.size) for px, py in group
        )[:12],
        "libertyPoints": sorted(
            _xy_to_gtp(px, py, board.size) for px, py in liberties
        )[:12],
    }


def _adjacent_groups(board, x: int, y: int, color: int) -> list[dict]:
    groups: list[dict] = []
    seen: set[frozenset[tuple[int, int]]] = set()
    for nx, ny in board.neighbors(x, y):
        if board.get(nx, ny) != color:
            continue
        group, _ = board.group_and_liberties(nx, ny)
        key = frozenset(group)
        if key in seen:
            continue
        seen.add(key)
        groups.append(_group_payload(board, nx, ny))
    return groups


def _rule_replay_line(prefix_game: sgf.Game, line: list[str]) -> dict:
    """逐手重放一条 KataGo PV，只生成规则引擎能够确定的事实。"""
    board, _ = replay(prefix_game)
    color_code = BLACK if _next_color(prefix_game, len(prefix_game.moves)) == "B" else WHITE
    events: list[dict] = []
    for ply, raw_move in enumerate(line[: MAX_BRANCH_DEPTH + 1], start=1):
        move = str(raw_move or "").strip().upper()
        if move in ("PASS", "TT"):
            board.play(color_code, "")
            events.append({
                "ply": ply,
                "player": "B" if color_code == BLACK else "W",
                "move": "pass",
                "captures": 0,
                "source": "goboard",
            })
            color_code = WHITE if color_code == BLACK else BLACK
            continue
        coord = _gtp_to_sgf(move, board.size)
        x, y = sgf_to_xy(coord)
        own_before = _adjacent_groups(board, x, y, color_code)
        captured = board.play(color_code, coord)
        own_group = _group_payload(board, x, y)
        enemy_code = WHITE if color_code == BLACK else BLACK
        opponent_groups = _adjacent_groups(board, x, y, enemy_code)
        events.append({
            "ply": ply,
            "player": "B" if color_code == BLACK else "W",
            "move": move,
            "captures": len(captured),
            "capturedPoints": sorted(
                _xy_to_gtp(px, py, board.size) for px, py in captured
            ),
            "adjacentOwnGroupsBefore": own_before,
            "joinedOwnGroups": len(own_before),
            "newGroup": own_group,
            "adjacentOpponentGroups": opponent_groups,
            "opponentGroupsInAtari": sum(
                group["liberties"] == 1 for group in opponent_groups
            ),
            "selfAtari": own_group["liberties"] == 1,
            "koPoint": (
                _xy_to_gtp(board.ko[0], board.ko[1], board.size)
                if board.ko else None
            ),
            "source": "goboard",
        })
        color_code = enemy_code
    return {
        "status": "replayed",
        "events": events,
        "summary": {
            "captureEvents": sum(event.get("captures", 0) > 0 for event in events),
            "capturedStones": sum(event.get("captures", 0) for event in events),
            "atariEvents": sum(event.get("opponentGroupsInAtari", 0) > 0 for event in events),
            "selfAtariEvents": sum(bool(event.get("selfAtari")) for event in events),
            "koEvents": sum(bool(event.get("koPoint")) for event in events),
        },
        "source": "goboard",
        "confidence": "deterministic",
    }


def _variation_game(
    game: sgf.Game, base_turn: int, variation: list[str]
) -> tuple[sgf.Game, list[bytes]]:
    board, _ = replay(game, upto=base_turn)
    moves = list(game.moves[:base_turn])
    states = [bytes(board.grid)]
    color = _next_color(game, base_turn)
    for item in variation:
        coord = _gtp_to_sgf(item, game.size)
        try:
            board.play(BLACK if color == "B" else WHITE, coord)
        except ValueError as exc:
            raise TeachingContextError(
                f"变化无法合法重放：{exc}",
                code="illegal_variation",
            ) from exc
        moves.append(sgf.Move(color=color, coord=coord, number=len(moves) + 1))
        states.append(bytes(board.grid))
        color = "W" if color == "B" else "B"
    return sgf.Game(info=deepcopy(game.info), moves=moves), states


def _legacy_engine_metadata(raw: dict) -> dict:
    engine = deepcopy(raw.get("engine") or {})
    source_declared = bool(engine.get("source"))
    source = str(engine.get("source") or "")
    if not source:
        if engine.get("version") and engine.get("model") and engine.get("backend"):
            source = "katago"
        elif str(engine.get("model") or "").lower().startswith("mock"):
            source = "mock"
        else:
            source = "unknown"
    if "demo" in engine:
        demo = bool(engine["demo"]) or source != "katago"
    else:
        demo = source != "katago"
    return {
        **engine,
        "source": source,
        "demo": demo,
        "provenanceStatus": "declared" if source_declared else "legacy_inferred",
    }


def _phase_at(phases: dict, turn: int) -> str:
    if any(
        item.get("start", 0) <= turn <= item.get("end", -1)
        for item in phases.get("joseki", [])
    ):
        return "定式"
    opening = phases.get("opening") or {}
    endgame = phases.get("endgame") or {}
    if turn <= int(opening.get("end") or 0):
        return "布局"
    if turn >= int(endgame.get("start") or 10**9):
        return "官子"
    return "中盘"


def _region(move: str | None, size: int) -> str:
    if not move or move == "pass":
        return "全局"
    match = _GTP_RE.fullmatch(move.upper())
    if not match:
        return "当前区域"
    x = _GTP_COLUMNS.index(match.group(1))
    y = size - int(match.group(2))
    band = max(3, size // 3)
    side = "左边" if x < band else ("右边" if x >= size - band else "中央")
    vertical = "上方" if y < band else ("下方" if y >= size - band else "中腹")
    return f"{side}{vertical}"


def _move_xy(move: str | None, size: int) -> tuple[int, int] | None:
    if not move or move == "pass":
        return None
    match = _GTP_RE.fullmatch(move.upper())
    if not match:
        return None
    x = _GTP_COLUMNS.index(match.group(1))
    y = size - int(match.group(2))
    if not (0 <= x < size and 0 <= y < size):
        return None
    return x, y


def _opening_geometry(move: str | None, size: int) -> dict:
    """只由坐标确定角、边、中腹；战略价值留在启发式层。"""
    point = _move_xy(move, size)
    if point is None:
        return {
            "zone": "global",
            "zoneLabel": "全局",
            "sectorLabel": "全局",
            "source": "coordinate_projection",
            "confidence": "deterministic",
        }
    x, y = point
    edge_x = min(x, size - 1 - x)
    edge_y = min(y, size - 1 - y)
    corner_band = max(4, size // 4)
    edge_band = max(4, size // 4)
    near_vertical_edge = edge_x < corner_band
    near_horizontal_edge = edge_y < corner_band
    if near_vertical_edge and near_horizontal_edge:
        zone = "corner"
        zone_label = "角部"
        sector = (
            ("左" if x < size / 2 else "右")
            + ("上角" if y < size / 2 else "下角")
        )
    elif edge_x < edge_band or edge_y < edge_band:
        zone = "side"
        zone_label = "边上"
        if edge_y <= edge_x:
            sector = "上边" if y < size / 2 else "下边"
        else:
            sector = "左边" if x < size / 2 else "右边"
    else:
        zone = "center"
        zone_label = "中腹"
        sector = "中央"
    return {
        "zone": zone,
        "zoneLabel": zone_label,
        "sectorLabel": sector,
        "edgeDistance": min(edge_x, edge_y),
        "source": "coordinate_projection",
        "confidence": "deterministic",
    }


def _opening_strategy_profile(
    state: bytes,
    size: int,
    move: str | None,
    player: str,
) -> dict:
    """从坐标与盘面关系生成可审计的布局启发式，不冒充 KataGo 战略定论。"""
    geometry = _opening_geometry(move, size)
    point = _move_xy(move, size)
    own, enemy = (BLACK, WHITE) if player == "B" else (WHITE, BLACK)
    if point is None:
        return {
            "strategicType": "global",
            "development": "先比较全局大场的优先级",
            "priorityPrinciple": "布局通常先看角部争夺，再看边上扩张，最后才是无具体目标的中腹行棋",
            "confidence": "heuristic",
            "source": "opening_board_geometry",
        }

    x, y = point
    corner_band = max(5, size // 3)
    corner_x = range(0, corner_band) if x < size / 2 else range(size - corner_band, size)
    corner_y = range(0, corner_band) if y < size / 2 else range(size - corner_band, size)
    corner_own = sum(state[yy * size + xx] == own for yy in corner_y for xx in corner_x)
    corner_enemy = sum(state[yy * size + xx] == enemy for yy in corner_y for xx in corner_x)

    side_own: list[tuple[int, int]] = []
    if geometry["zone"] == "side":
        if geometry["sectorLabel"] in ("上边", "下边"):
            side_own = [
                (xx, yy)
                for yy in range(size)
                for xx in range(size)
                if state[yy * size + xx] == own
                and abs(yy - y) <= 1
                and (xx, yy) != (x, y)
            ]
        else:
            side_own = [
                (xx, yy)
                for yy in range(size)
                for xx in range(size)
                if state[yy * size + xx] == own
                and abs(xx - x) <= 1
                and (xx, yy) != (x, y)
            ]
    spans_both_flanks = bool(
        side_own
        and (
            (
                geometry["sectorLabel"] in ("上边", "下边")
                and any(xx < x for xx, _ in side_own)
                and any(xx > x for xx, _ in side_own)
            )
            or (
                geometry["sectorLabel"] in ("左边", "右边")
                and any(yy < y for _, yy in side_own)
                and any(yy > y for _, yy in side_own)
            )
        )
    )
    formation = None
    if geometry["zone"] == "side" and spans_both_flanks and size == 19:
        star_axis = {3, size // 2, size - 4}
        if geometry["sectorLabel"] in ("上边", "下边"):
            axis_points = {x, *(xx for xx, _ in side_own)}
            fourth_line = min(y, size - 1 - y) == 3
        else:
            axis_points = {y, *(yy for _, yy in side_own)}
            fourth_line = min(x, size - 1 - x) == 3
        if fourth_line and star_axis.issubset(axis_points):
            formation = "three_star_style"

    if geometry["zone"] == "corner" and corner_enemy:
        strategic_type = "corner_approach"
        development = "接近对方已有角部棋子，主动争夺角上的行棋次序"
    elif geometry["zone"] == "corner" and corner_own > 1:
        strategic_type = "corner_reinforcement"
        development = "围绕己方角部继续发展，具体效率需用变化核对"
    elif geometry["zone"] == "corner":
        strategic_type = "corner_occupation"
        development = "优先取得角部根据与发展空间"
    elif geometry["zone"] == "side" and spans_both_flanks:
        strategic_type = "side_framework_bridge"
        development = "位于同侧两翼己子之间，扩张并串联宽阔的边上框架"
    elif geometry["zone"] == "side" and side_own:
        strategic_type = "side_extension"
        development = "沿边扩张已有子力，增加边上框架潜力"
    elif geometry["zone"] == "side":
        strategic_type = "side_development"
        development = "抢占边上大场，价值取决于两侧角部与先后手"
    else:
        strategic_type = "center_development"
        development = "在中腹取势，必须结合攻防对象与先手价值判断"

    framework = None
    if geometry["zone"] == "side":
        framework = {
            "sameSideFriendlyStones": len(side_own),
            "spansBothFlanks": spans_both_flanks,
            "formation": formation,
            "description": (
                "落点与同侧两翼己子构成三连星式宽框架"
                if formation == "three_star_style"
                else "落点处于同侧两翼己子之间，形成宽框架关系"
                if spans_both_flanks
                else (
                    "落点沿同侧既有己子扩张"
                    if side_own
                    else "未检测到同侧既有己子"
                )
            ),
        }
    return {
        "strategicType": strategic_type,
        "development": development,
        "priorityPrinciple": "布局通常先看角部争夺，再看边上扩张，最后才是无具体目标的中腹行棋",
        "cornerContext": {
            "ownStones": corner_own,
            "opponentStones": corner_enemy,
            "description": (
                "对方已在该角落子，当前着法属于角部争夺而非抢占空角"
                if geometry["zone"] == "corner" and corner_enemy
                else (
                    "己方已在该角有子"
                    if geometry["zone"] == "corner" and corner_own > 1
                    else "该着法优先发展角部"
                )
            ),
        } if geometry["zone"] == "corner" else None,
        "framework": framework,
        "confidence": "heuristic",
        "source": "opening_board_geometry",
    }


def _local_situation_profile(
    rule_facts: dict,
    own_count: int,
    enemy_count: int,
    phase: str,
) -> dict:
    """用规则信号识别局部战斗范围；只约束讲解主题，不判断死活结果。"""
    liberties = rule_facts.get("libertiesBeforeAfter")
    liberties = liberties if isinstance(liberties, dict) else {}
    own_liberties = list(liberties.get("own") or [])
    opponent_liberties = list(liberties.get("opponent") or [])
    adjacent = int(rule_facts.get("adjacentOpponentGroups") or 0)
    dense_contact = (
        own_count >= 4
        and enemy_count >= 4
        and adjacent >= 1
    )
    low_liberty_contact = any(
        isinstance(value, int) and value <= 2
        for value in (
            own_liberties[-1:] + opponent_liberties[-1:]
        )
    )
    tactical = bool(
        dense_contact
        and (
            phase != "布局"
            or low_liberty_contact
            or rule_facts.get("cut")
            or rule_facts.get("attack")
            or rule_facts.get("defense")
        )
    )
    if tactical:
        return {
            "scope": "local_fight",
            "label": "局部对杀",
            "description": "落点处于双方棋子密集接触区，应按局部攻防与对杀次序判断",
            "focus": "优先检查双方棋块的气、连接、切断、先手和局部存亡",
            "scopeGuard": "不得用无关的角边中腹发展或全局大场替代局部战斗分析",
            "ownNearby": own_count,
            "enemyNearby": enemy_count,
            "adjacentOpponentGroups": adjacent,
            "ownLibertiesBeforeAfter": own_liberties,
            "opponentLibertiesBeforeAfter": opponent_liberties,
            "confidence": "heuristic",
            "source": "board_rules_local_density",
        }
    return {
        "scope": "global_or_positional",
        "label": "全局或局部未定",
        "description": "当前规则信号不足以确定为局部对杀",
        "focus": "结合阶段、候选变化和双方弱棋继续判断",
        "scopeGuard": None,
        "ownNearby": own_count,
        "enemyNearby": enemy_count,
        "adjacentOpponentGroups": adjacent,
        "ownLibertiesBeforeAfter": own_liberties,
        "opponentLibertiesBeforeAfter": opponent_liberties,
        "confidence": "heuristic",
        "source": "board_rules_local_density",
    }


def _nearby_counts(state: bytes, size: int, move: str | None, player: str) -> tuple[int, int]:
    if not move or move == "pass":
        return 0, 0
    match = _GTP_RE.fullmatch(move.upper())
    if not match:
        return 0, 0
    x = _GTP_COLUMNS.index(match.group(1))
    y = size - int(match.group(2))
    own, enemy = (BLACK, WHITE) if player == "B" else (WHITE, BLACK)
    own_count = enemy_count = 0
    for yy in range(max(0, y - 3), min(size - 1, y + 3) + 1):
        for xx in range(max(0, x - 3), min(size - 1, x + 3) + 1):
            if (xx == x and yy == y) or max(abs(xx - x), abs(yy - y)) > 3:
                continue
            value = state[yy * size + xx]
            if value == own:
                own_count += 1
            elif value == enemy:
                enemy_count += 1
    return own_count, enemy_count


def _role_from_rules(rule_facts: dict) -> tuple[str, str]:
    if rule_facts.get("captures"):
        return (
            f"提取对方 {rule_facts['captures']} 子，直接改变局部气与盘面",
            "rule",
        )
    if rule_facts.get("connection"):
        return "连接相邻己方棋块，并改善局部联络", "rule"
    if rule_facts.get("cut"):
        return "在相邻对方棋块之间制造切断可能", "heuristic"
    if rule_facts.get("attack") and rule_facts.get("defense"):
        return "在局部同时承担补强与施压作用", "heuristic"
    if rule_facts.get("attack"):
        return "靠近对方棋块施加压力，具体效果需用变化验证", "heuristic"
    if rule_facts.get("defense"):
        return "靠近己方棋块补强，具体效率需与首选比较", "heuristic"
    return "占据局部要点，战略作用仍需结合推荐变化核对", "heuristic"


def _purpose_payload(
    game: sgf.Game,
    turn: int,
    state: bytes,
    rule_facts: dict,
    pre: dict,
    post: dict,
    engine_meta: dict,
    phase: str,
) -> dict:
    if turn <= 0:
        return {
            "title": "开局前的判断",
            "region": "全局",
            "role": "尚未落子，先建立候选方向",
            "ownNearby": 0,
            "enemyNearby": 0,
            "captured": 0,
            "confidence": "rule",
            "evidenceSummary": "当前是开局前局面。",
            "nextFocus": "先比较角部、边上和全局大场的优先级。",
            "evidenceSource": ["board_rules"],
        }
    move = rule_facts.get("move")
    player = rule_facts.get("player") or game.moves[turn - 1].color
    if move == "pass":
        role, confidence = "暂不在棋盘落子", "rule"
    else:
        role, confidence = _role_from_rules(rule_facts)
    own_count, enemy_count = _nearby_counts(state, game.size, move, player)
    opening_geometry = _opening_geometry(move, game.size)
    local_situation = _local_situation_profile(
        rule_facts, own_count, enemy_count, phase
    )
    opening_strategy = (
        _opening_strategy_profile(state, game.size, move, player)
        if phase == "布局" and local_situation["scope"] != "local_fight"
        else None
    )
    winrate_delta = None
    score_delta = None
    if (
        isinstance(pre.get("winrateBlack"), (int, float))
        and isinstance(post.get("winrateBlack"), (int, float))
    ):
        winrate_delta = (post["winrateBlack"] - pre["winrateBlack"]) * 100
    if (
        isinstance(pre.get("scoreLeadBlack"), (int, float))
        and isinstance(post.get("scoreLeadBlack"), (int, float))
    ):
        score_delta = post["scoreLeadBlack"] - pre["scoreLeadBlack"]
    if winrate_delta is not None and score_delta is not None:
        prefix = (
            "KataGo 证据显示"
            if engine_meta.get("source") == "katago"
            and engine_meta.get("demo") is False
            else (
                "演示分析显示"
                if engine_meta.get("demo") or engine_meta.get("source") == "mock"
                else "服务端分析显示"
            )
        )
        summary = (
            f"{prefix}，本手后黑方胜率"
            f"{'上升' if winrate_delta >= 0 else '下降'} "
            f"{abs(winrate_delta):.1f} 个百分点，黑方目差"
            f"{'增加' if score_delta >= 0 else '减少'} "
            f"{abs(score_delta):.1f} 目。"
        )
    else:
        summary = "当前只有规则事实，没有可用的真实 KataGo 数值证据。"
    return {
        "title": f"第 {turn} 手 {player} {move or 'pass'} 的作用",
        "region": _region(move, game.size),
        "role": role,
        "ownNearby": own_count,
        "enemyNearby": enemy_count,
        "captured": int(rule_facts.get("captures") or 0),
        "confidence": confidence,
        "evidenceSummary": summary,
        "nextFocus": (
            "下一步先比较双方棋块的气、连接、切断与先手次序。"
            if local_situation["scope"] == "local_fight"
            else "下一步比较实战与首选在先手、地盘转换和双方弱棋上的差异。"
        ),
        "openingGeometry": opening_geometry,
        "openingStrategy": opening_strategy,
        "localSituation": local_situation,
        "evidenceSource": list(rule_facts.get("evidenceSource") or ["board_rules"]),
    }


def _rule_fact_payload(rule_facts: dict) -> dict:
    return {
        key: deepcopy(rule_facts.get(key))
        for key in (
            "move",
            "player",
            "captures",
            "connectedGroups",
            "adjacentOpponentGroups",
            "libertiesBeforeAfter",
            "connection",
        )
    } | {
        "confidence": "deterministic",
        "source": "goboard",
    }


def _heuristic_fact_payload(rule_facts: dict, purpose: dict) -> dict:
    return {
        "region": purpose.get("region"),
        "ownNearby": purpose.get("ownNearby"),
        "enemyNearby": purpose.get("enemyNearby"),
        "cutPossible": bool(rule_facts.get("cut")),
        "defensePossible": bool(rule_facts.get("defense")),
        "attackPossible": bool(rule_facts.get("attack")),
        "openingStrategy": deepcopy(purpose.get("openingStrategy")),
        "localSituation": deepcopy(purpose.get("localSituation")),
        "confidence": purpose.get("confidence"),
        "source": "MovePurposeEvidence",
    }


def _candidate_payload(
    kind: str,
    move: str | None,
    player: str | None,
    size: int,
    rule_facts: dict | None,
    purpose: dict | None,
    *,
    engine_meta: dict,
    recommendation: dict | None = None,
    legal: bool = True,
    unavailable_reason: str | None = None,
) -> dict | None:
    """把一手候选着投影为规则、坐标事实与启发式作用三层证据。"""
    if not move:
        return None
    purpose = deepcopy(purpose or {})
    rule_facts = deepcopy(rule_facts or {})
    rules = _rule_fact_payload(rule_facts) if rule_facts else {
        "move": move,
        "player": player,
        "captures": None,
        "connectedGroups": None,
        "adjacentOpponentGroups": None,
        "libertiesBeforeAfter": None,
        "connection": None,
        "confidence": "unavailable",
        "source": "goboard",
    }
    rules["legal"] = bool(legal)
    if unavailable_reason:
        rules["unavailableReason"] = unavailable_reason
    recommendation = deepcopy(recommendation or {})
    return {
        "kind": kind,
        "move": move,
        "player": player,
        "region": {
            "label": purpose.get("region") or _region(move, size),
            "source": "coordinate_projection",
            "confidence": "deterministic",
        },
        "geometry": deepcopy(
            purpose.get("openingGeometry") or _opening_geometry(move, size)
        ),
        "rules": rules,
        "heuristics": {
            "role": purpose.get("role") or "局部作用需要进入变化后继续验证",
            "ownNearby": purpose.get("ownNearby"),
            "enemyNearby": purpose.get("enemyNearby"),
            "openingStrategy": deepcopy(purpose.get("openingStrategy")),
            "localSituation": deepcopy(purpose.get("localSituation")),
            "confidence": purpose.get("confidence") or "unavailable",
            "source": "MovePurposeEvidence",
        },
        "analysis": {
            "source": engine_meta.get("source"),
            "demo": bool(engine_meta.get("demo")),
            "rank": 1 if kind == "best" else None,
            "visits": recommendation.get("visits") or engine_meta.get("visits"),
            "pv": list(recommendation.get("pv") or [])[:10],
        },
    }


def _best_move_candidate(
    game: sgf.Game,
    effective_turn: int,
    best_move: str | None,
    player: str | None,
    pre: dict,
    engine_meta: dict,
    phase: str,
) -> tuple[dict | None, dict | None]:
    """在实战落子前的服务端盘面上合法试下首选，重建它自己的关系与作用。"""
    if not best_move:
        return None, None
    recommendation = next(
        (
            deepcopy(item)
            for item in (pre.get("recommendations") or [])
            if str(item.get("move") or "").upper() == str(best_move).upper()
        ),
        {"move": best_move},
    )
    prefix_turn = max(0, effective_turn - 1)
    candidate_turn = prefix_turn + 1
    candidate_player = player or _next_color(game, prefix_turn)
    try:
        coord = _gtp_to_sgf(str(best_move), game.size)
        candidate_game = sgf.Game(
            info=deepcopy(game.info),
            moves=[
                *list(game.moves[:prefix_turn]),
                sgf.Move(
                    color=candidate_player,
                    coord=coord,
                    number=candidate_turn,
                ),
            ],
        )
        _, candidate_states = replay(candidate_game)
        candidate_post = {
            key: deepcopy(recommendation.get(key))
            for key in ("winrateBlack", "scoreLeadBlack", "visits")
            if recommendation.get(key) is not None
        }
        candidate_positions = [{} for _ in range(candidate_turn + 1)]
        candidate_positions[prefix_turn] = deepcopy(pre)
        candidate_positions[candidate_turn] = candidate_post
        candidate_rules = reports.build_move_purpose_evidence(
            candidate_game,
            candidate_states,
            candidate_positions,
            candidate_turn,
            analysis_source=engine_meta["source"],
            demo=engine_meta["demo"],
        )
        candidate_purpose = _purpose_payload(
            candidate_game,
            candidate_turn,
            candidate_states[candidate_turn],
            candidate_rules,
            pre,
            candidate_post,
            engine_meta,
            phase,
        )
        return (
            _candidate_payload(
                "best",
                str(best_move),
                candidate_player,
                game.size,
                candidate_rules,
                candidate_purpose,
                engine_meta=engine_meta,
                recommendation=recommendation,
            ),
            candidate_purpose,
        )
    except (TeachingContextError, ValueError) as exc:
        unavailable_purpose = {
            "region": _region(str(best_move), game.size),
            "role": "推荐点的局部作用需要进入变化后继续验证",
            "confidence": "unavailable",
        }
        return (
            _candidate_payload(
                "best",
                str(best_move),
                candidate_player,
                game.size,
                None,
                unavailable_purpose,
                engine_meta=engine_meta,
                recommendation=recommendation,
                legal=False,
                unavailable_reason=str(exc),
            ),
            unavailable_purpose,
        )


def _facts_hash(facts: dict) -> str:
    payload = json.dumps(
        facts,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _position_hash(
    state: bytes,
    to_play: str,
    size: int,
    *,
    ko: tuple[int, int] | None,
    captured: dict[int, int],
    komi: object,
) -> str:
    payload = json.dumps(
        {
            "size": size,
            "stones": state.hex(),
            "toPlay": to_play,
            "ko": list(ko) if ko else None,
            "capturedBlack": int(captured.get(BLACK, 0)),
            "capturedWhite": int(captured.get(WHITE, 0)),
            "komi": str(komi or ""),
            "rules": "simple-ko-no-suicide",
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _cache_get(key: str) -> dict | None:
    with _CONTEXT_CACHE_LOCK:
        value = _CONTEXT_CACHE.get(key)
        if value is None:
            return None
        _CONTEXT_CACHE.move_to_end(key)
        return deepcopy(value)


def _cache_put(key: str, value: dict) -> None:
    with _CONTEXT_CACHE_LOCK:
        _CONTEXT_CACHE[key] = deepcopy(value)
        _CONTEXT_CACHE.move_to_end(key)
        while len(_CONTEXT_CACHE) > _CONTEXT_CACHE_LIMIT:
            _CONTEXT_CACHE.popitem(last=False)


def _branch_cache_identity(context: dict, analysis_engine, visits: int) -> tuple[str, str]:
    engine_version = "|".join((
        VARIATION_EVIDENCE_VERSION,
        str(getattr(analysis_engine, "version", "unknown")),
        str(getattr(analysis_engine, "model_name", "unknown")),
        str(visits),
    ))
    payload = json.dumps(
        {
            "positionHash": context.get("positionHash"),
            "reportRevision": context.get("reportRevision"),
            "subject": context.get("subject"),
            "moves": context.get("facts", {}).get("moveCandidates"),
            "version": engine_version,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest(), engine_version


def _candidate_branch(
    analysis_engine,
    game: sgf.Game,
    root_turn: int,
    prefix_variation: list[str],
    prefix_game: sgf.Game,
    kind: str,
    move: str,
    visits: int,
) -> dict:
    result = analysis_engine.analyze_position(
        game,
        root_turn,
        [*prefix_variation, move],
        visits=visits,
    )
    recommendations = list(result.get("recommendations") or [])[:MAX_BRANCH_REPLIES]
    replies: list[dict] = []
    for rank, recommendation in enumerate(recommendations, start=1):
        reply = str(recommendation.get("move") or "").upper()
        pv = [str(item).upper() for item in (recommendation.get("pv") or []) if item]
        if reply and (not pv or pv[0] != reply):
            pv.insert(0, reply)
        continuation = pv[:MAX_BRANCH_DEPTH]
        full_line = [move, *continuation]
        try:
            rule_replay = _rule_replay_line(prefix_game, full_line)
        except (TeachingContextError, ValueError) as exc:
            rule_replay = {
                "status": "invalid_line",
                "reason": str(exc),
                "events": [],
                "summary": {},
                "source": "goboard",
                "confidence": "unavailable",
            }
        replies.append({
            "rank": rank,
            "reply": reply or None,
            "visits": recommendation.get("visits"),
            "winrateBlack": recommendation.get("winrateBlack"),
            "scoreLeadBlack": recommendation.get("scoreLeadBlack"),
            "line": full_line,
            "ruleReplay": rule_replay,
        })
    total_reply_visits = sum(
        int(item.get("visits") or 0) for item in recommendations
    )
    top_reply_visits = int(recommendations[0].get("visits") or 0) if recommendations else 0
    return {
        "kind": kind,
        "move": move,
        "analysisAfterMove": {
            "winrateBlack": result.get("winrateBlack"),
            "scoreLeadBlack": result.get("scoreLeadBlack"),
            "visits": result.get("visits"),
            "source": "katago",
        },
        "replySearch": {
            "count": len(replies),
            "topReply": replies[0].get("reply") if replies else None,
            "topReplyVisitShare": (
                round(top_reply_visits / total_reply_visits, 4)
                if total_reply_visits else None
            ),
            "interpretationBoundary": (
                "访问量分布只表示搜索关注度，不能单独证明对手必须应手"
            ),
            "source": "katago",
        },
        "replies": replies,
    }


def _first_branch_events(branch: dict) -> list[dict]:
    replies = branch.get("replies") if isinstance(branch.get("replies"), list) else []
    first = replies[0] if replies and isinstance(replies[0], dict) else {}
    replay_value = (
        first.get("ruleReplay") if isinstance(first.get("ruleReplay"), dict) else {}
    )
    events = replay_value.get("events")
    return events if isinstance(events, list) else []


def _atari_targets(event: dict) -> list[dict]:
    groups = (
        event.get("adjacentOpponentGroups")
        if isinstance(event.get("adjacentOpponentGroups"), list)
        else []
    )
    return [
        group for group in groups
        if isinstance(group, dict) and int(group.get("liberties") or 0) == 1
    ]


def _public_target_summary(event: dict) -> dict:
    targets = _atari_targets(event)
    return {
        "atariTargetGroups": len(targets),
        "atariTargetStones": sum(int(group.get("stones") or 0) for group in targets),
        "targetLibertiesAfter": sorted({
            int(group.get("liberties") or 0) for group in targets
        }),
        "newGroupStones": int((event.get("newGroup") or {}).get("stones") or 0),
        "newGroupLiberties": int((event.get("newGroup") or {}).get("liberties") or 0),
        "capturesNow": int(event.get("captures") or 0),
        "joinedOwnGroups": int(event.get("joinedOwnGroups") or 0),
        "source": "goboard",
        "confidence": "deterministic",
    }


def _move_far_from_points(
    move: object, points: set[str], size: int, *, radius: int = 5
) -> bool:
    move_xy = _move_xy(str(move or ""), size)
    anchors = [
        point_xy for point in points
        if (point_xy := _move_xy(point, size)) is not None
    ]
    if move_xy is None or not anchors:
        return False
    return min(
        abs(move_xy[0] - anchor[0]) + abs(move_xy[1] - anchor[1])
        for anchor in anchors
    ) > radius


def _tactical_semantics(
    branches: dict[str, dict], actual_move: str, best_move: str, size: int
) -> dict:
    """把规则事件关联成棋形语义；不把启发式冒充规则或 KataGo 事实。"""
    actual = branches.get("actual") if isinstance(branches.get("actual"), dict) else {}
    best = branches.get("best") if isinstance(branches.get("best"), dict) else {}
    actual_events = _first_branch_events(actual)
    best_events = _first_branch_events(best)
    if not actual_events or not best_events:
        return {"status": "unavailable", "reason": "主要变化缺少规则事件"}

    actual_first = actual_events[0]
    best_first = best_events[0]
    actual_reply = actual_events[1] if len(actual_events) > 1 else {}
    actual_targets = _atari_targets(actual_first)
    best_targets = _atari_targets(best_first)
    best_target_points = {
        str(point).upper()
        for group in best_targets
        for point in (group.get("stonePoints") or [])
    }
    actual_target_points = {
        str(point).upper()
        for group in actual_targets
        for point in (group.get("stonePoints") or [])
    }
    reply_group = (
        actual_reply.get("newGroup")
        if isinstance(actual_reply.get("newGroup"), dict)
        else {}
    )
    reply_group_points = {
        str(point).upper() for point in (reply_group.get("stonePoints") or [])
    }
    reply_own_before = (
        actual_reply.get("adjacentOwnGroupsBefore")
        if isinstance(actual_reply.get("adjacentOwnGroupsBefore"), list)
        else []
    )
    same_group_before = next(
        (
            group for group in reply_own_before
            if isinstance(group, dict)
            and best_target_points.issubset({
                str(point).upper() for point in (group.get("stonePoints") or [])
            })
        ),
        {},
    )
    reply_move = str(actual_reply.get("move") or "").upper()
    same_group_role_reversal = bool(
        best_target_points and best_target_points.issubset(reply_group_points)
    )
    actual_atari_ignored = bool(
        actual_target_points
        and not actual_target_points.intersection(reply_group_points)
        and reply_move != actual_move
    )

    best_anchor_points = {best_move, *best_target_points}
    best_replies = best.get("replies") if isinstance(best.get("replies"), list) else []
    checked_best_replies = [
        reply for reply in best_replies[:2] if isinstance(reply, dict) and reply.get("reply")
    ]
    elsewhere_replies = sum(
        _move_far_from_points(reply.get("reply"), best_anchor_points, size)
        for reply in checked_best_replies
    )
    shared_point = bool(reply_move and reply_move == best_move)
    mutual_vital_point = bool(shared_point and same_group_role_reversal)
    return {
        "status": "ready" if mutual_vital_point else "partial",
        "scope": "local_fight",
        "actualSImmediate": _public_target_summary(actual_first),
        "bestJImmediate": _public_target_summary(best_first),
        "opponentJAfterS": {
            "isEngineTopReply": shared_point,
            "extendsSameGroupAttackedByJ": same_group_role_reversal,
            "groupStonesBefore": int(same_group_before.get("stones") or 0),
            "groupLibertiesBefore": int(same_group_before.get("liberties") or 0),
            "groupStonesAfter": int(reply_group.get("stones") or 0),
            "groupLibertiesAfter": int(reply_group.get("liberties") or 0),
            "joinedOwnGroups": int(actual_reply.get("joinedOwnGroups") or 0),
            "source": "katago+goboard",
            "confidence": "deterministic_relation",
        },
        "replyPriority": {
            "opponentIgnoresSImmediateAtariToPlayJ": actual_atari_ignored and shared_point,
            "bestBranchRepliesChecked": len(checked_best_replies),
            "bestBranchRepliesElsewhere": elsewhere_replies,
            "bestBranchTopRepliesAllElsewhere": bool(
                checked_best_replies and elsewhere_replies == len(checked_best_replies)
            ),
            "interpretationBoundary": (
                "远处应对只证明引擎主变化选择脱先，不等于被打吃棋块已经死亡或必须弃掉"
            ),
            "source": "katago_pv+coordinate_distance",
        },
        "comparison": {
            "sharedUrgentPoint": shared_point,
            "sameGroupRoleReversal": same_group_role_reversal,
            "mutualVitalPoint": mutual_vital_point,
            "goMeaning": (
                "J 是同一块棋的攻守转换点：当前一方先占 J 会把该棋块压到一气；"
                "若先走 S，对手抢 J 会把同一棋块接长并扩气。"
                if mutual_vital_point else
                "已确认 S/J 的规则作用不同，但不足以自动断言同一棋块的攻守转换。"
            ),
            "confidence": "high" if mutual_vital_point else "limited",
            "source": "katago_priority+goboard_group_identity",
        },
        "claimBoundary": {
            "ruleFacts": [
                "target_group_size", "liberties_after_move", "group_identity",
                "connection_after_reply",
            ],
            "katagoFacts": ["top_reply", "pv_reply_location"],
            "heuristicInference": ["mutual_vital_point", "attack_defense_role_reversal"],
            "notProven": ["forced_reply", "group_dead", "group_must_be_sacrificed"],
        },
    }


def _attach_variation_adjudication(context: dict, value: dict) -> dict:
    """变化裁决拥有独立指纹，不改变讲解/问棋共用的基础 contextId。"""
    evidence_hash = _facts_hash(value)
    seed = json.dumps(
        {
            "contextId": context.get("contextId"),
            "variationEvidenceHash": evidence_hash,
            "schemaVersion": VARIATION_EVIDENCE_VERSION,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    context["adjudication"] = {
        "schemaVersion": VARIATION_EVIDENCE_VERSION,
        "variationEvidenceHash": evidence_hash,
        "adjudicationId": hashlib.sha256(seed.encode("utf-8")).hexdigest(),
        "variationEvidence": deepcopy(value),
    }
    return context


def enrich_with_variation_evidence(
    context: dict,
    analysis_engine,
    *,
    visits: int | None = None,
) -> dict:
    """仅在问棋阶段深查实战/首选分支，并把多PV规则重放写回证据包。"""
    enriched = deepcopy(context)
    analysis = enriched.setdefault("facts", {}).setdefault("analysis", {})
    if analysis.get("source") != "katago" or analysis.get("demo") is not False:
        return _attach_variation_adjudication(enriched, {
            "schemaVersion": VARIATION_EVIDENCE_VERSION,
            "status": "unavailable",
            "reason": "真实 KataGo 证据不可用",
            "source": analysis.get("source") or "analysis_unknown",
        })
    candidates = enriched.get("facts", {}).get("moveCandidates") or {}
    actual = candidates.get("actual") if isinstance(candidates.get("actual"), dict) else {}
    best = candidates.get("best") if isinstance(candidates.get("best"), dict) else {}
    actual_move = str(actual.get("move") or "").upper()
    best_move = str(best.get("move") or "").upper()
    if not actual_move or not best_move:
        return _attach_variation_adjudication(enriched, {
            "schemaVersion": VARIATION_EVIDENCE_VERSION,
            "status": "unavailable",
            "reason": "缺少实战手或首选手",
            "source": "server",
        })
    visits = max(16, min(512, int(
        visits or os.getenv("GOMENTOR_MENTOR_BRANCH_VISITS", DEFAULT_BRANCH_VISITS)
    )))
    cache_key, engine_version = _branch_cache_identity(
        enriched, analysis_engine, visits
    )
    cached = library.get_analysis_cache(cache_key, engine_version)
    if isinstance(cached, dict) and cached.get("schemaVersion") == VARIATION_EVIDENCE_VERSION:
        return _attach_variation_adjudication(enriched, cached)
    detail = library.get_game(str(enriched.get("gameId") or ""))
    if not detail:
        raise TeachingContextError(
            "棋谱不存在，无法复核候选变化",
            status_code=404,
            code="game_not_found",
        )
    try:
        game = sgf.parse(detail["sgf"])
    except sgf.SGFError as exc:
        raise TeachingContextError(
            f"棋谱无法解析：{exc}",
            status_code=409,
            code="stored_game_invalid",
        ) from exc
    subject = enriched.get("subject") or {}
    subject_variation = list(subject.get("variation") or [])
    if subject_variation:
        root_turn = int(subject.get("baseTurn") or 0)
        prefix_variation = subject_variation[:-1]
    else:
        root_turn = max(0, int(subject.get("effectiveTurn") or 0) - 1)
        prefix_variation = []
    prefix_game, _ = _variation_game(game, root_turn, prefix_variation)
    branch_moves = [("actual", actual_move)]
    if best_move != actual_move:
        branch_moves.append(("best", best_move))
    branches: dict[str, dict] = {}
    try:
        for kind, move in branch_moves:
            branches[kind] = _candidate_branch(
                analysis_engine,
                game,
                root_turn,
                prefix_variation,
                prefix_game,
                kind,
                move,
                visits,
            )
        if best_move == actual_move and "actual" in branches:
            branches["best"] = deepcopy(branches["actual"])
            branches["best"]["kind"] = "best"
    except (KataGoError, TeachingContextError, ValueError) as exc:
        variation_evidence = {
            "schemaVersion": VARIATION_EVIDENCE_VERSION,
            "status": "unavailable",
            "reason": str(exc),
            "source": "katago",
            "demo": False,
            "visitsPerBranch": visits,
        }
    else:
        actual_top_reply = (
            branches.get("actual", {}).get("replySearch", {}).get("topReply")
        )
        variation_evidence = {
            "schemaVersion": VARIATION_EVIDENCE_VERSION,
            "status": "ready",
            "source": "katago+goboard",
            "demo": False,
            "visitsPerBranch": visits,
            "decisionTurn": root_turn,
            "branches": branches,
            "comparison": {
                "actualMove": actual_move,
                "bestMove": best_move,
                "actualTopReply": actual_top_reply,
                "bestBecameTopReplyAfterActual": bool(
                    best_move and actual_top_reply == best_move
                ),
                "interpretationBoundary": (
                    "候选优先级来自 KataGo；提子、气、连接与劫点来自规则重放；"
                    "厚薄、轻重和先手价值仍属于基于分支结果的启发式判断"
                ),
            },
            "tacticalSemantics": _tactical_semantics(
                branches, actual_move, best_move, game.size
            ),
            "claimBoundary": {
                "katagoFacts": [
                    "candidate_order", "winrate", "score_lead", "pv", "visits"
                ],
                "ruleFacts": [
                    "captures", "groups", "liberties", "connections", "simple_ko"
                ],
                "notDirectlyProven": [
                    "forced_reply", "life_and_death", "thickness", "sacrifice_value"
                ],
            },
        }
        library.put_analysis_cache(cache_key, engine_version, variation_evidence)
    return _attach_variation_adjudication(enriched, variation_evidence)


def _current_and_previous(
    positions: list[dict], turn: int
) -> tuple[dict, dict]:
    if turn < 0 or turn >= len(positions):
        raise TeachingContextError(
            "整盘报告与请求手数不一致，请重新分析棋谱",
            status_code=409,
            code="stale_report",
        )
    post = deepcopy(positions[turn])
    pre = deepcopy(positions[max(0, turn - 1)])
    return pre, post


def _first_recommendation_move(position: dict) -> str | None:
    recommendations = position.get("recommendations")
    if isinstance(recommendations, list) and recommendations:
        move = recommendations[0].get("move")
        if move:
            return str(move).upper()
    move = position.get("bestMove")
    return str(move).upper() if move else None


def _decision_relation(
    actual_move: str | None,
    best_move_before: str | None,
    post: dict,
    engine_meta: dict,
) -> dict:
    """比较实战前后的引擎首选，识别是否把同一急点让给了对手。

    这里只陈述两个 KataGo 结果之间可复核的坐标关系，不把它直接解释成
    已经杀死、必然先手或某个具体手筋。
    """
    actual = str(actual_move or "").upper() or None
    before = str(best_move_before or "").upper() or None
    after = _first_recommendation_move(post)
    missed_point_became_reply = bool(
        actual
        and before
        and after
        and actual != before
        and before == after
    )
    source = str(engine_meta.get("source") or "analysis")
    is_katago = source == "katago" and engine_meta.get("demo") is False
    return {
        "actualMove": actual,
        "bestMoveBeforeActual": before,
        "bestMoveAfterActual": after,
        "missedBestBecameOpponentBestReply": missed_point_became_reply,
        "description": (
            "实战没有占据原首选点；落子后轮到对手时，同一坐标仍是引擎首选"
            if missed_point_became_reply
            else "实战前后的首选坐标没有形成同一急点关系"
        ),
        "interpretationBoundary": (
            "这能证明双方都重视同一落点及其行棋次序；具体紧气、切断、"
            "封锁或死活效果仍须沿推荐变化核对"
            if missed_point_became_reply
            else "当前坐标关系不足以单独判断局部手筋"
        ),
        "source": (
            "katago_pre_post_sequence"
            if is_katago
            else f"{source}_pre_post_sequence"
        ),
        "confidence": "high" if is_katago else (
            "demo" if engine_meta.get("demo") else "limited"
        ),
    }


def build_authoritative_context(
    game_id: str,
    turn: int,
    variation: list[str] | None,
    analysis_engine,
    report_id: str | None = None,
) -> dict:
    """仅凭定位信息重建一份可追踪的权威教学证据包。"""
    detail = library.get_game(str(game_id or ""))
    if not detail:
        raise TeachingContextError(
            "棋谱不存在，无法重建教学证据",
            status_code=404,
            code="game_not_found",
        )
    try:
        game = sgf.parse(detail["sgf"])
    except sgf.SGFError as exc:
        raise TeachingContextError(
            f"棋谱无法解析：{exc}",
            status_code=409,
            code="stored_game_invalid",
        ) from exc
    base_turn = int(turn)
    if base_turn < 0 or base_turn > len(game.moves):
        raise TeachingContextError(
            f"手数必须在 0 到 {len(game.moves)} 之间",
            code="turn_out_of_range",
        )
    normalized_variation = _normalize_variation(variation, game.size)
    report = (
        library.get_report(str(report_id), detail["id"])
        if report_id
        else library.latest_report(detail["id"])
    )
    if not report:
        raise TeachingContextError(
            (
                "指定报告不存在或不属于当前棋谱"
                if report_id
                else "该棋谱尚未完成整盘预分析，无法生成权威教学证据"
            ),
            status_code=409,
            code="report_mismatch" if report_id else "analysis_required",
        )
    raw = report["raw"]
    report_revision = report.get("revision") or library.report_revision(raw)
    engine_meta = _legacy_engine_metadata(raw)
    cache_seed = json.dumps(
        {
            "schemaVersion": SCHEMA_VERSION,
            "evidenceProjectionVersion": EVIDENCE_PROJECTION_VERSION,
            "gameId": detail["id"],
            "reportId": report["id"],
            "reportRevision": report_revision,
            "baseTurn": base_turn,
            "variation": normalized_variation,
            "runtimeEngine": {
                "type": type(analysis_engine).__name__,
                "version": getattr(analysis_engine, "version", None),
                "model": getattr(analysis_engine, "model_name", None),
                "maxVisits": getattr(analysis_engine, "max_visits", None),
            },
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    cache_key = hashlib.sha256(cache_seed.encode("utf-8")).hexdigest()
    cached_context = _cache_get(cache_key)
    if cached_context is not None:
        return cached_context

    cached_narrative = None
    if normalized_variation:
        variant_game, _ = _variation_game(game, base_turn, normalized_variation)
        effective_turn = len(variant_game.moves)
        _, full_states = replay(variant_game)
        final_state = full_states[-1]
        if isinstance(analysis_engine, KataGoEngine):
            try:
                pre = analysis_engine.analyze_position(
                    game, base_turn, normalized_variation[:-1]
                )
                post = analysis_engine.analyze_position(
                    game, base_turn, normalized_variation
                )
            except KataGoError as exc:
                raise TeachingContextError(
                    f"KataGo 暂时无法重建变化证据：{exc}",
                    status_code=503,
                    code="katago_unavailable",
                ) from exc
            engine_meta = {
                "source": "katago",
                "demo": False,
                "label": (
                    f"真实 KataGo v{analysis_engine.version} · "
                    f"{analysis_engine.model_name}"
                ),
                "version": analysis_engine.version,
                "model": analysis_engine.model_name,
                "backend": "OpenCL",
                "visits": post.get("visits"),
                "provenanceStatus": "live_position_analysis",
            }
        else:
            pre, post = {}, {}
            engine_meta = {
                "source": "mock",
                "demo": True,
                "label": "规则重放降级（无真实 KataGo 变化证据）",
                "version": None,
                "model": None,
                "backend": None,
                "visits": None,
                "provenanceStatus": "rules_only",
            }
        positions = [{} for _ in range(effective_turn + 1)]
        positions[max(0, effective_turn - 1)] = pre
        positions[effective_turn] = post
        rule_facts = reports.build_move_purpose_evidence(
            variant_game,
            full_states,
            positions,
            effective_turn,
            analysis_source=engine_meta["source"],
            demo=engine_meta["demo"],
        )
        subject_game = variant_game
        state = final_state
    else:
        effective_turn = base_turn
        positions = raw.get("positions") or []
        pre, post = _current_and_previous(positions, effective_turn)
        _, states = replay(game)
        state = states[effective_turn]
        subject_game = game
        if effective_turn:
            rule_facts = reports.build_move_purpose_evidence(
                game,
                states,
                positions,
                effective_turn,
                analysis_source=engine_meta["source"],
                demo=engine_meta["demo"],
            )
            node = next(
                (
                    item
                    for item in raw.get("losses", [])
                    if item.get("turn") == effective_turn
                ),
                None,
            )
            if node:
                cached_narrative = deepcopy(node.get("narrative"))
                for source_key, target_key in (
                    ("winrateLoss", "winrateLoss"),
                    ("scoreLoss", "scoreLoss"),
                    ("recommendedMove", "bestMove"),
                    ("pv", "pv"),
                    ("confidence", "confidence"),
                    ("deepVisits", "deepVisits"),
                ):
                    if node.get(source_key) is not None:
                        rule_facts[target_key] = deepcopy(node[source_key])
        else:
            rule_facts = {
                "move": None,
                "player": None,
                "captures": 0,
                "connectedGroups": 0,
                "adjacentOpponentGroups": 0,
                "connection": False,
                "cut": False,
                "defense": False,
                "attack": False,
                "libertiesBeforeAfter": {"own": [0, 0], "opponent": [0, 0]},
                "winrateLoss": None,
                "scoreLoss": None,
                "bestMove": None,
                "pv": [],
                "confidence": "high",
                "evidenceSource": ["board_rules"],
            }

    to_play = _next_color(subject_game, effective_turn)
    move = (
        "pass"
        if effective_turn and subject_game.moves[effective_turn - 1].is_pass
        else (
            gtp_name(
                subject_game.moves[effective_turn - 1].coord,
                subject_game.size,
            )
            if effective_turn
            else None
        )
    )
    player = subject_game.moves[effective_turn - 1].color if effective_turn else None
    recommendations = deepcopy(pre.get("recommendations") or [])
    best_move = (
        recommendations[0].get("move")
        if recommendations
        else pre.get("bestMove")
    )
    winrate_delta = None
    score_delta = None
    player_winrate_delta = None
    player_score_delta = None
    if (
        isinstance(pre.get("winrateBlack"), (int, float))
        and isinstance(post.get("winrateBlack"), (int, float))
    ):
        winrate_delta = (post["winrateBlack"] - pre["winrateBlack"]) * 100
    if (
        isinstance(pre.get("scoreLeadBlack"), (int, float))
        and isinstance(post.get("scoreLeadBlack"), (int, float))
    ):
        score_delta = post["scoreLeadBlack"] - pre["scoreLeadBlack"]
    if player == "B":
        player_winrate_delta = winrate_delta
        player_score_delta = score_delta
    elif player == "W":
        player_winrate_delta = -winrate_delta if winrate_delta is not None else None
        player_score_delta = -score_delta if score_delta is not None else None
    evidence = {
        "winrate": (
            post["winrateBlack"] * 100
            if isinstance(post.get("winrateBlack"), (int, float))
            else None
        ),
        "scoreLead": post.get("scoreLeadBlack"),
        "bestMove": best_move,
        "recommendations": recommendations,
        "winrateDelta": winrate_delta,
        "scoreDelta": score_delta,
        "playerWinrateDelta": player_winrate_delta,
        "playerScoreDelta": player_score_delta,
        "valuePerspective": "black",
        "deltaPerspective": "move_player",
        "winrateLoss": rule_facts.get("winrateLoss"),
        "scoreLoss": rule_facts.get("scoreLoss"),
        "pv": deepcopy(rule_facts.get("pv") or []),
        "source": engine_meta["source"],
        "demo": engine_meta["demo"],
        "reportId": report["id"],
        "reportSignature": report.get("signature"),
        "reportRevision": report_revision,
        "visits": rule_facts.get("deepVisits") or engine_meta.get("visits"),
    }
    evidence["decisionRelation"] = _decision_relation(
        move, best_move, post, engine_meta
    )
    phase_turn = base_turn if normalized_variation else effective_turn
    phase = _phase_at(raw.get("phases") or {}, phase_turn)
    purpose = _purpose_payload(
        subject_game,
        effective_turn,
        state,
        rule_facts,
        pre,
        post,
        engine_meta,
        phase,
    )
    actual_candidate = _candidate_payload(
        "actual",
        move,
        player,
        game.size,
        rule_facts if effective_turn else None,
        purpose if effective_turn else None,
        engine_meta=engine_meta,
    )
    best_candidate, best_purpose = _best_move_candidate(
        subject_game,
        effective_turn,
        best_move,
        player,
        pre,
        engine_meta,
        phase,
    )
    move_candidates = {
        "decisionTurn": max(0, effective_turn - 1),
        "actual": actual_candidate,
        "best": best_candidate,
        "sameMove": bool(
            move and best_move
            and str(move).upper() == str(best_move).upper()
        ),
    }
    position = {
        "turn": effective_turn,
        "baseTurn": base_turn,
        "variationDepth": len(normalized_variation),
        "toPlay": "黑" if to_play == "B" else "白",
        "player": "黑" if player == "B" else ("白" if player == "W" else None),
        "phase": phase,
        "move": move,
        "boardSize": game.size,
    }
    position_board, _ = replay(subject_game, upto=effective_turn)
    position_hash = _position_hash(
        state,
        to_play,
        game.size,
        ko=position_board.ko,
        captured=position_board.captured,
        komi=game.info.get("KM"),
    )
    facts = {
        "rules": _rule_fact_payload(rule_facts),
        "analysis": evidence,
        "heuristics": _heuristic_fact_payload(rule_facts, purpose),
        "moveCandidates": move_candidates,
    }
    evidence_hash = _facts_hash(facts)
    context_seed = json.dumps(
        {
            "gameId": detail["id"],
            "reportId": report["id"],
            "reportSignature": report.get("signature"),
            "reportRevision": report_revision,
            "baseTurn": base_turn,
            "variation": normalized_variation,
            "positionHash": position_hash,
            "evidenceHash": evidence_hash,
            "schemaVersion": SCHEMA_VERSION,
            "evidenceProjectionVersion": EVIDENCE_PROJECTION_VERSION,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    context_id = hashlib.sha256(context_seed.encode("utf-8")).hexdigest()
    rule_source = {
        "type": "rule",
        "source": "goboard.py",
        "confidence": "deterministic",
        "facts": [
            "legal_replay",
            "captures",
            "groups",
            "liberties",
            "simple_ko",
        ],
    }
    engine_source = {
        "type": "katago" if engine_meta["source"] == "katago" else "analysis",
        "source": engine_meta["source"],
        "confidence": (
            "high"
            if engine_meta["source"] == "katago" and not engine_meta["demo"]
            else "demo"
        ),
        "demo": engine_meta["demo"],
        "version": engine_meta.get("version"),
        "model": engine_meta.get("model"),
        "backend": engine_meta.get("backend"),
        "visits": evidence.get("visits"),
        "status": (
            "deep_position_analysis"
            if rule_facts.get("deepVisits")
            else engine_meta.get("provenanceStatus")
        ),
    }
    heuristic_source = {
        "type": "heuristic",
        "source": "reports.MovePurposeEvidence",
        "confidence": purpose["confidence"],
        "facts": [
            "region",
            "nearby_counts",
            "cut_possible",
            "defense_possible",
            "attack_possible",
        ],
    }
    result = {
        "schemaVersion": SCHEMA_VERSION,
        "evidenceProjectionVersion": EVIDENCE_PROJECTION_VERSION,
        "contextId": context_id,
        "gameId": detail["id"],
        "reportId": report["id"],
        "reportSignature": report.get("signature"),
        "reportRevision": report_revision,
        "positionHash": position_hash,
        "evidenceHash": evidence_hash,
        "subject": {
            "baseTurn": base_turn,
            "variation": normalized_variation,
            "effectiveTurn": effective_turn,
            "move": move,
            "player": player,
        },
        "authority": {
            "source": "server",
            "reconstructed": True,
            "clientEvidenceAccepted": False,
        },
        "position": position,
        "facts": facts,
        "expression": {
            "baselinePurpose": purpose,
            "cachedNarrative": cached_narrative,
            "candidatePurposes": {
                "actual": deepcopy(purpose) if actual_candidate else None,
                "best": deepcopy(best_purpose) if best_candidate else None,
            },
        },
        "provenance": [rule_source, engine_source, heuristic_source],
    }
    _cache_put(cache_key, result)
    return result


def mentor_inputs(context: dict) -> tuple[dict, dict, dict]:
    """把统一证据包投影为现有确定性/LLM表达层的只读输入。"""
    facts = context["facts"]
    position = deepcopy(context["position"])
    position["moveCandidates"] = deepcopy(facts.get("moveCandidates") or {})
    position["decisionRelation"] = deepcopy(
        facts.get("analysis", {}).get("decisionRelation") or {}
    )
    analysis = deepcopy(facts["analysis"])
    adjudication = context.get("adjudication")
    if isinstance(adjudication, dict):
        analysis["variationEvidence"] = deepcopy(
            adjudication.get("variationEvidence") or {}
        )
        analysis["variationEvidenceHash"] = adjudication.get(
            "variationEvidenceHash"
        )
        analysis["adjudicationId"] = adjudication.get("adjudicationId")
    return (
        position,
        analysis,
        deepcopy(context["expression"]["baselinePurpose"]),
    )
