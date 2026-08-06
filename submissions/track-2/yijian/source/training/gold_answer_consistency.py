# -*- coding: utf-8 -*-
"""Deterministic safety checks for human-reviewed training answers.

The checker is deliberately narrower than a Go-language judge.  It does not
decide whether prose is elegant or strategically insightful.  It only blocks
structured claims that can be proven inconsistent with the verified evidence
attached to a teaching unit.
"""

from __future__ import annotations

import math
import re
from typing import Any


COORD_RE = re.compile(
    r"(?<![A-Za-z0-9])([A-HJ-T](?:1[0-9]|[1-9]))(?![A-Za-z0-9])",
    re.IGNORECASE,
)
PERCENT_RE = re.compile(r"([+-]?\d+(?:\.\d+)?)\s*(?:%|％|个百分点)")
SCORE_RE = re.compile(r"([+-]?\d+(?:\.\d+)?)\s*目")
VISITS_RE = re.compile(r"(\d+)\s*(?:visits?|访问量|次访问|访问)", re.IGNORECASE)
MOVE_NUMBER_RE = re.compile(r"第\s*(\d+)\s*手")
NUMBER_RE = re.compile(r"[+-]?\d+(?:\.\d+)?")
CN_NUMBER = r"[零〇一二两三四五六七八九十百千点]+"
CN_PERCENT_RE = re.compile(rf"(?:百分之({CN_NUMBER})|({CN_NUMBER})个百分点)")
CN_CHENG_RE = re.compile(rf"({CN_NUMBER})成(?:({CN_NUMBER}))?")
CN_SCORE_RE = re.compile(rf"({CN_NUMBER})目(半)?|半目")
CN_VISITS_RE = re.compile(rf"({CN_NUMBER})\s*(?:次访问|访问量|次搜索)")
CN_MOVE_NUMBER_RE = re.compile(rf"第\s*({CN_NUMBER})\s*手")

BEST_LABELS = ("AI首选", "引擎首选", "KataGo首选", "首选", "推荐手", "最佳着法", "最佳手")
ACTUAL_LABELS = ("实战手", "实战这手", "实战", "本手", "这手", "此手")
POSITION_LABELS = ("当前局面", "这个局面", "此局面", "局面", "形势")
COMPARISON_LABELS = ("相比", "比较", "两手", "前者", "后者", "取舍", "而实战", "而首选")
DECISIVE_LIFE_DEATH = (
    "已经死",
    "已死",
    "死棋",
    "必死",
    "一定死",
    "已经活",
    "活棋",
    "必活",
    "一定活",
    "必胜",
    "胜定",
)
NEGATING_CONTEXT = ("不", "未", "并非", "不能", "不可", "尚未", "不等于", "不能说")


class AnswerConsistencyError(ValueError):
    pass


def _chinese_number(value: str) -> float:
    digits = {
        "零": 0,
        "〇": 0,
        "一": 1,
        "二": 2,
        "两": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
    }
    if "点" in value:
        integer, fractional = value.split("点", 1)
        if not fractional or any(character not in digits for character in fractional):
            raise AnswerConsistencyError("回答包含无法核验的中文数字")
        fraction = float("0." + "".join(str(digits[character]) for character in fractional))
        return _chinese_number(integer or "零") + fraction
    total = 0
    current = 0
    units = {"十": 10, "百": 100, "千": 1000}
    for character in value:
        if character in digits:
            current = digits[character]
        elif character in units:
            total += (current or 1) * units[character]
            current = 0
        else:
            raise AnswerConsistencyError("回答包含无法核验的中文数字")
    return float(total + current)


def _coords(text: str) -> set[str]:
    return {match.group(1).upper() for match in COORD_RE.finditer(text)}


def _close_to_any(value: float, allowed: set[float], tolerance: float = 0.051) -> bool:
    return any(math.isclose(value, candidate, abs_tol=tolerance) for candidate in allowed)


def _pairwise_values(values: list[float], *, scale: float = 1.0) -> set[float]:
    result = {value * scale for value in values}
    for left_index, left in enumerate(values):
        for right in values[left_index + 1 :]:
            difference = abs(left - right) * scale
            result.add(difference)
            result.add(-difference)
    return result


def _mask_spans(text: str, spans: list[tuple[int, int]]) -> str:
    characters = list(text)
    for start, end in spans:
        characters[start:end] = " " * (end - start)
    return "".join(characters)


def _assert_role_bindings(answer: str, actual_move: str, best_move: str) -> None:
    label_group = "|".join(re.escape(label) for label in BEST_LABELS)
    coord = r"([A-HJ-T](?:1[0-9]|[1-9]))"
    best_patterns = (
        re.compile(rf"(?:{label_group})\s*(?:是|为|在|：|:)?\s*{coord}", re.IGNORECASE),
        re.compile(rf"{coord}\s*(?:是|为)?\s*(?:{label_group})", re.IGNORECASE),
    )
    for pattern in best_patterns:
        for match in pattern.finditer(answer):
            if match.group(1).upper() != best_move:
                raise AnswerConsistencyError("回答把非首选坐标描述成了 AI/KataGo 首选")

    actual_group = "|".join(re.escape(label) for label in ("实战手", "实战", "实际下的"))
    actual_patterns = (
        re.compile(rf"(?:{actual_group})\s*(?:是|为|下在|走了|：|:)?\s*{coord}", re.IGNORECASE),
        re.compile(rf"{coord}\s*(?:是|为)?\s*(?:{actual_group})", re.IGNORECASE),
    )
    for pattern in actual_patterns:
        for match in pattern.finditer(answer):
            if match.group(1).upper() != actual_move:
                raise AnswerConsistencyError("回答把非实战坐标描述成了实战手")

    if actual_move != best_move:
        actual_as_best = re.compile(
            rf"{re.escape(actual_move)}\s*(?:就是|是|为)\s*(?:{label_group})",
            re.IGNORECASE,
        )
        if actual_as_best.search(answer):
            raise AnswerConsistencyError("回答把实战手误写成了 AI/KataGo 首选")


def _assert_target_anchor(
    question: str,
    answer: str,
    *,
    target_kind: str,
    target_move: str,
    actual_move: str,
    best_move: str,
) -> None:
    question_coords = _coords(question)
    if question_coords and target_move not in question_coords:
        raise AnswerConsistencyError("问题文字中的坐标没有锚定 questionTargetMove")

    answer_coords = _coords(answer)
    if target_kind == "actual":
        anchored = target_move in answer_coords or any(label in answer for label in ACTUAL_LABELS)
    elif target_kind == "best":
        anchored = target_move in answer_coords or any(label in answer for label in BEST_LABELS)
    elif target_kind == "position":
        anchored = any(label in answer for label in POSITION_LABELS)
    else:
        both_moves = {actual_move, best_move} <= answer_coords
        anchored = both_moves or any(label in answer for label in COMPARISON_LABELS)
    if not anchored:
        raise AnswerConsistencyError("回答没有锚定用户所问的实战手、首选或比较对象")


def _assert_no_unsupported_numbers(answer: str, katago: dict[str, Any], rebuilt: dict[str, Any]) -> None:
    candidates = katago["analysisArtifact"]["candidates"]
    winrates = [float(candidate["winrate"]) for candidate in candidates]
    scores = [float(candidate["scoreLead"]) for candidate in candidates]
    allowed_percentages = _pairwise_values(winrates, scale=100.0)
    allowed_scores = _pairwise_values(scores)
    allowed_visits = {int(katago["visits"])} | {
        int(candidate["visits"]) for candidate in candidates
    }
    allowed_move_numbers = {int(rebuilt["actualMoveNumber"])}

    consumed: list[tuple[int, int]] = []
    for match in COORD_RE.finditer(answer):
        consumed.append(match.span())
    for match in PERCENT_RE.finditer(answer):
        value = float(match.group(1))
        if not _close_to_any(value, allowed_percentages):
            raise AnswerConsistencyError("回答包含证据中不存在的胜率或胜率变化")
        consumed.append(match.span())
    for match in SCORE_RE.finditer(answer):
        value = float(match.group(1))
        if not _close_to_any(value, allowed_scores):
            raise AnswerConsistencyError("回答包含证据中不存在的目差或目差变化")
        consumed.append(match.span())
    for match in VISITS_RE.finditer(answer):
        if int(match.group(1)) not in allowed_visits:
            raise AnswerConsistencyError("回答包含证据中不存在的访问量")
        consumed.append(match.span())
    for match in MOVE_NUMBER_RE.finditer(answer):
        if int(match.group(1)) not in allowed_move_numbers:
            raise AnswerConsistencyError("回答包含与当前教学单元不一致的手数")
        consumed.append(match.span())

    for match in CN_PERCENT_RE.finditer(answer):
        value = _chinese_number(match.group(1) or match.group(2))
        if not _close_to_any(value, allowed_percentages):
            raise AnswerConsistencyError("回答包含证据中不存在的中文胜率或胜率变化")
    for match in CN_CHENG_RE.finditer(answer):
        value = _chinese_number(match.group(1)) * 10
        if match.group(2):
            value += _chinese_number(match.group(2))
        if not _close_to_any(value, allowed_percentages):
            raise AnswerConsistencyError("回答包含证据中不存在的成数胜率")
    for match in CN_SCORE_RE.finditer(answer):
        value = 0.5 if match.group(0) == "半目" else _chinese_number(match.group(1))
        if match.group(2):
            value += 0.5
        if not _close_to_any(value, allowed_scores):
            raise AnswerConsistencyError("回答包含证据中不存在的中文目差或目差变化")
    for match in CN_VISITS_RE.finditer(answer):
        if not _close_to_any(_chinese_number(match.group(1)), {float(v) for v in allowed_visits}, 0.0):
            raise AnswerConsistencyError("回答包含证据中不存在的中文访问量")
    for match in CN_MOVE_NUMBER_RE.finditer(answer):
        if not _close_to_any(
            _chinese_number(match.group(1)),
            {float(v) for v in allowed_move_numbers},
            0.0,
        ):
            raise AnswerConsistencyError("回答包含与当前教学单元不一致的中文手数")

    remaining = _mask_spans(answer, consumed)
    if NUMBER_RE.search(remaining):
        raise AnswerConsistencyError("回答包含未绑定权威证据的数字")


def _assert_no_unsupported_decisive_claim(answer: str) -> None:
    for phrase in DECISIVE_LIFE_DEATH:
        start = 0
        while True:
            index = answer.find(phrase, start)
            if index < 0:
                break
            prefix = answer[max(0, index - 7) : index]
            if not any(negation in prefix for negation in NEGATING_CONTEXT):
                raise AnswerConsistencyError("回答包含当前证据不能支持的确定性死活/胜负结论")
            start = index + len(phrase)


def validate_gold_answer(
    unit: dict[str, Any],
    rebuilt: dict[str, Any],
    katago: dict[str, Any],
) -> None:
    board = unit["board"]
    expression = unit["evidence"]["teacherExpression"]
    question = str(expression["question"]).strip()
    answer = str(expression["answer"]).strip()
    follow_ups = expression.get("followUps") or []
    if not isinstance(follow_ups, list) or not all(
        isinstance(item, str) and bool(item.strip()) for item in follow_ups
    ):
        raise AnswerConsistencyError("followUps 必须是非空字符串数组或空数组")
    assistant_text = "\n".join([answer, *(item.strip() for item in follow_ups)])
    all_text = "\n".join([question, assistant_text])
    actual_move = str(rebuilt["actualMove"]).upper()
    best_move = str(katago["bestMove"]).upper()
    target_move = str(rebuilt["questionTargetMove"]).upper()

    allowed_coords = {actual_move, best_move}
    for candidate in katago["analysisArtifact"]["candidates"]:
        allowed_coords.add(str(candidate["move"]).upper())
        allowed_coords.update(str(move).upper() for move in candidate["pv"])
    coordinate_evidence = (unit.get("evidence") or {}).get(
        "teacherCoordinateEvidence"
    ) or []
    if not isinstance(coordinate_evidence, list):
        raise AnswerConsistencyError("teacherCoordinateEvidence 必须是数组")
    analysis_board = rebuilt.get("_analysisBoardBefore")
    board_size = int(rebuilt["boardSize"])
    letters = "ABCDEFGHJKLMNOPQRST"[:board_size]
    state_names = {0: "empty", 1: "B", 2: "W"}
    for item in coordinate_evidence:
        if not isinstance(item, dict) or item.get("status") != "verified_board_state":
            raise AnswerConsistencyError("教师坐标证据未通过棋盘状态核验")
        coord = str(item.get("coord") or "").upper()
        if not COORD_RE.fullmatch(coord) or coord[0] not in letters:
            raise AnswerConsistencyError("教师坐标证据包含非法坐标")
        column = letters.index(coord[0])
        row = board_size - int(coord[1:])
        if not (0 <= row < board_size):
            raise AnswerConsistencyError("教师坐标证据超出棋盘")
        actual_before = state_names[analysis_board.get(column, row)]
        if item.get("before") != actual_before:
            raise AnswerConsistencyError(f"教师坐标证据与落子前棋盘不一致：{coord}")
        allowed_coords.add(coord)
    unsupported = _coords(all_text) - allowed_coords
    if unsupported:
        raise AnswerConsistencyError(
            "问题或回答包含权威候选/PV中不存在的坐标: "
            + ", ".join(sorted(unsupported))
        )

    _assert_role_bindings(all_text, actual_move, best_move)
    _assert_no_unsupported_numbers(all_text, katago, rebuilt)
    _assert_no_unsupported_decisive_claim(assistant_text)
    _assert_target_anchor(
        question,
        answer,
        target_kind=str(board["targetKind"]),
        target_move=target_move,
        actual_move=actual_move,
        best_move=best_move,
    )
