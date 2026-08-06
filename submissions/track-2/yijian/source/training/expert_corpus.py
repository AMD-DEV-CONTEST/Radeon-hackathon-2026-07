# -*- coding: utf-8 -*-
"""校验并编译创作者授权的专家教学单元。"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import random
import re
import sys
from pathlib import Path
from typing import Any


TRAINING_ROOT = Path(__file__).resolve().parent
BACKEND_ROOT = TRAINING_ROOT.parent / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

import goboard  # noqa: E402
import sgf  # noqa: E402
import trusted_katago_artifacts as trusted_katago  # noqa: E402
from engine.katago_engine import normalize_komi  # noqa: E402
import trusted_source_chain  # noqa: E402
from gold_answer_consistency import (  # noqa: E402
    AnswerConsistencyError,
    validate_gold_answer,
)


SOURCE_REGISTRY = TRAINING_ROOT / "sources.json"
LEGACY_UNIT_SCHEMAS = {
    "authorized-video-teaching-unit-v1",
    "authorized-video-teaching-unit-v2",
}
LEGACY_UNIT_SCHEMA = "authorized-video-teaching-unit-v1"
UNIT_SCHEMA = "authorized-video-teaching-unit-v3"
SPLIT_MANIFEST_SCHEMA = "creator-split-manifest-v1"
COVERAGE_MANIFEST_SCHEMA = "creator-coverage-manifest-v1"
EXPLICIT_SPLIT_COUNTS = {"train": 48, "dev": 8, "test": 8}
REQUIRED_CREATOR_THEMES = {
    "opening_value", "vital_point", "thickness", "sente",
    "attack_target", "sacrifice_tradeoff", "territory_influence", "ko",
    "joseki", "life_death", "liberty_race", "endgame",
}
CREATOR_THEME_ALIASES = {
    "opening": "opening_value",
    "ko_shape": "ko",
    "sacrifice": "sacrifice_tradeoff",
}
OUTPUT_SCHEMA = "authorized-video-sft-v3"
TARGET_KINDS = {"actual", "best", "comparison", "position"}
SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
TRANSCRIPT_ARTIFACT_SCHEMA = "human-verified-transcript-v1"
KATAGO_ARTIFACT_SCHEMA = trusted_katago.ARTIFACT_SCHEMA
RULE_ARTIFACT_SCHEMA = "goboard-rule-artifact-v1"
GTP_COORD_RE = re.compile(r"^(?:PASS|[A-HJ-T](?:[1-9]|1[0-9]))$", re.IGNORECASE)
MAX_CREATOR_SFT_ANSWER_CHARS = 180
SYSTEM = (
    "你是弈鉴围棋教练。KataGo负责胜率、目差、候选手与变化，规则引擎负责"
    "落子、提子、气与棋块事实；专家材料提供可追溯的棋理判断和教学方法。"
    "回答必须绑定用户所问目标，解释具体围棋机制与取舍，不得把专家判断或"
    "语言风格冒充KataGo事实，也不得新增证据中没有的数值、坐标或死活结论。"
    "默认先给结论，再说明机制和取舍或边界，避免重复展开。"
    "只返回JSON，字段为answer与followUps。"
)


class CorpusError(ValueError):
    pass


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise CorpusError(f"JSON根节点必须为对象：{path}")
    return value


def load_sources() -> dict[str, dict[str, Any]]:
    registry = read_json(SOURCE_REGISTRY)
    return {
        source["id"]: source
        for source in registry.get("allowlist") or []
        if isinstance(source, dict) and source.get("id")
    }


def require(condition: bool, unit_id: str, message: str) -> None:
    if not condition:
        raise CorpusError(f"{unit_id}: {message}")


def validated_sft_answer(expression: dict[str, Any], unit_id: str) -> str:
    """Return the human-approved concise target and reject verbose drift."""
    answer = str(expression.get("answer") or "").strip()
    require(bool(answer), unit_id, "缺少专家回答")
    require(
        len(answer) <= MAX_CREATOR_SFT_ANSWER_CHARS,
        unit_id,
        f"SFT回答超过{MAX_CREATOR_SFT_ANSWER_CHARS}字，详细解释应移入referenceAnswerDetailed",
    )
    return answer


def canonical_json(value: Any) -> str:
    """训练制品统一使用无空白、键排序、禁止 NaN 的 UTF-8 JSON。"""
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise CorpusError(f"制品无法规范化为JSON：{exc}") from exc


def canonical_json_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _require_gtp_coord(value: Any, board_size: int, unit_id: str, label: str) -> str:
    coord = str(value or "").strip().upper()
    require(bool(GTP_COORD_RE.fullmatch(coord)), unit_id, f"{label}不是有效GTP坐标")
    if coord != "PASS":
        column = "ABCDEFGHJKLMNOPQRST".index(coord[0]) + 1
        row = int(coord[1:])
        require(column <= board_size and row <= board_size, unit_id, f"{label}超出棋盘")
    return coord


def _finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def position_hash(board: goboard.Board, to_play: str, komi: object) -> str:
    """按 teaching-context-v6 的局面身份规范计算哈希。"""
    payload = json.dumps(
        {
            "size": board.size,
            "stones": bytes(board.grid).hex(),
            "toPlay": to_play,
            "ko": list(board.ko) if board.ko else None,
            "capturedBlack": int(board.captured.get(goboard.BLACK, 0)),
            "capturedWhite": int(board.captured.get(goboard.WHITE, 0)),
            "komi": str(komi or ""),
            "rules": "simple-ko-no-suicide",
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def board_similarity_fingerprint(board: goboard.Board, to_play: str) -> str:
    """对八种棋盘对称变换取规范形，拦截旋转/镜像后的同局面跨集合泄漏。"""
    size = board.size

    def transform(c: int, r: int, variant: int) -> tuple[int, int]:
        if variant >= 4:
            c = size - 1 - c
            variant -= 4
        for _ in range(variant):
            c, r = size - 1 - r, c
        return c, r

    variants = []
    for variant in range(8):
        stones = [goboard.EMPTY] * (size * size)
        for row in range(size):
            for column in range(size):
                x, y = transform(column, row, variant)
                stones[y * size + x] = board.get(column, row)
        ko = transform(*board.ko, variant) if board.ko else None
        variants.append(json.dumps({
            "size": size,
            "stones": bytes(stones).hex(),
            "toPlay": to_play,
            "ko": list(ko) if ko else None,
        }, sort_keys=True, separators=(",", ":")))
    return hashlib.sha256(min(variants).encode("utf-8")).hexdigest()


def game_identity(game: sgf.Game) -> str:
    """按完整主线而非视频身份生成对局指纹，识别同一盘棋的重复讲解。"""
    return canonical_json_sha256({
        "size": game.size,
        "komi": str(game.info.get("KM") or ""),
        "rules": str(game.info.get("RU") or ""),
        "moves": [
            [move.color, "" if move.is_pass else move.coord]
            for move in game.moves
        ],
    })


def verified_transcript_artifact(unit: dict[str, Any]) -> dict[str, Any]:
    """校验人工分段并返回参与哈希的唯一规范投影。"""
    unit_id = str(unit.get("id") or "<missing-id>")
    source = unit.get("source") or {}
    transcript = unit.get("transcript") or {}
    segments = transcript.get("segments")
    require(isinstance(segments, list) and bool(segments), unit_id, "转写缺少人工核验segments")

    normalized = []
    cursor = source.get("startMs")
    for index, segment in enumerate(segments, 1):
        require(isinstance(segment, dict), unit_id, f"转写第{index}段必须是对象")
        require(
            segment.get("status") == "human_verified",
            unit_id,
            f"转写第{index}段未人工核验",
        )
        start_ms = segment.get("startMs")
        end_ms = segment.get("endMs")
        require(
            isinstance(start_ms, int)
            and not isinstance(start_ms, bool)
            and isinstance(end_ms, int)
            and not isinstance(end_ms, bool)
            and start_ms < end_ms,
            unit_id,
            f"转写第{index}段时间无效",
        )
        require(start_ms == cursor, unit_id, "转写segments未连续覆盖来源时间段")
        require(end_ms <= source.get("endMs"), unit_id, "转写segment超出来源时间段")
        text = segment.get("text")
        require(
            isinstance(text, str) and bool(text.strip()) and text == text.strip(),
            unit_id,
            f"转写第{index}段正文为空或含首尾空白",
        )
        normalized.append(
            {
                "startMs": start_ms,
                "endMs": end_ms,
                "text": text,
                "status": "human_verified",
            }
        )
        cursor = end_ms

    require(cursor == source.get("endMs"), unit_id, "转写segments未完整覆盖来源时间段")
    rebuilt_text = "\n".join(segment["text"] for segment in normalized)
    require(
        transcript.get("text") == rebuilt_text,
        unit_id,
        "transcript.text必须由人工核验segments逐段重建",
    )
    artifact = {
        "schemaVersion": TRANSCRIPT_ARTIFACT_SCHEMA,
        "videoId": source.get("videoId"),
        "startMs": source.get("startMs"),
        "endMs": source.get("endMs"),
        "segments": normalized,
    }
    require(
        source.get("transcriptSha256") == canonical_json_sha256(artifact),
        unit_id,
        "transcriptSha256与人工核验分段规范JSON不一致",
    )
    return artifact


def _next_color(game: sgf.Game, turn: int) -> str:
    if turn < len(game.moves):
        return game.moves[turn].color
    if turn:
        return "W" if game.moves[turn - 1].color == "B" else "B"
    return game.moves[0].color if game.moves else "B"


def _game_from_reconstructed_moves(
    board_meta: dict[str, Any], unit_id: str
) -> sgf.Game:
    moves = board_meta.get("moves")
    require(isinstance(moves, list) and bool(moves), unit_id, "无原始SGF时缺少完整落子序列")
    require(
        board_meta.get("moveSequenceStatus") == "human_verified",
        unit_id,
        "重建落子序列未经人工核验",
    )
    size = board_meta.get("boardSize")
    require(
        isinstance(size, int) and not isinstance(size, bool) and 2 <= size <= 19,
        unit_id,
        "无原始SGF时必须提供2至19路boardSize",
    )
    frame = board_meta.get("frameEvidence") or {}
    require(frame.get("status") == "human_verified", unit_id, "棋盘帧证据未经人工核验")
    timestamp_ms = frame.get("timestampMs")
    require(
        isinstance(timestamp_ms, int) and not isinstance(timestamp_ms, bool),
        unit_id,
        "棋盘帧证据缺少毫秒时间码",
    )
    require(
        bool(SHA256_RE.fullmatch(str(frame.get("frameSha256") or ""))),
        unit_id,
        "棋盘帧证据缺少有效SHA-256",
    )
    parsed_moves = []
    for index, value in enumerate(moves, 1):
        require(isinstance(value, dict), unit_id, f"第{index}手落子记录必须是对象")
        color = str(value.get("color") or "").upper()
        coord = value.get("coord")
        require(color in ("B", "W"), unit_id, f"第{index}手颜色错误")
        require(isinstance(coord, str), unit_id, f"第{index}手缺少SGF坐标")
        parsed_moves.append(sgf.Move(color=color, coord=coord, number=index))
    return sgf.Game(
        info={"SZ": str(size), "KM": str(board_meta.get("komi") or "")},
        moves=parsed_moves,
    )


def reconstruct_board_facts(
    unit: dict[str, Any]
) -> dict[str, Any]:
    """从原始SGF或人工核验的完整落子序列重建当前局面。"""
    unit_id = str(unit.get("id") or "<missing-id>")
    board_meta = unit.get("board") or {}
    source_meta = unit.get("source") or {}
    sgf_text = str(board_meta.get("sgf") or "").strip()
    if sgf_text:
        require(not board_meta.get("moves"), unit_id, "SGF与重建落子序列不能同时提供")
        try:
            game = sgf.parse(sgf_text)
        except (sgf.SGFError, ValueError) as exc:
            raise CorpusError(f"{unit_id}: SGF无法解析：{exc}") from exc
    else:
        game = _game_from_reconstructed_moves(board_meta, unit_id)
        frame = board_meta.get("frameEvidence") or {}
        require(
            source_meta.get("startMs") <= frame.get("timestampMs") <= source_meta.get("endMs"),
            unit_id,
            "棋盘帧时间码不在授权视频片段内",
        )

    require(2 <= game.size <= 19, unit_id, "训练棋盘目前只支持2至19路")
    try:
        # 完整重放先验证所提供的整条主线；随后重放到目标手生成精确状态。
        goboard.replay(game)
    except (goboard.IllegalMove, ValueError, AssertionError) as exc:
        raise CorpusError(f"{unit_id}: SGF/落子无法合法重建：{exc}") from exc

    turn = board_meta.get("turn")
    require(
        isinstance(turn, int) and not isinstance(turn, bool) and 0 <= turn <= len(game.moves),
        unit_id,
        "手数与可重建落子序列不一致",
    )
    actual_move_number = board_meta.get("actualMoveNumber")
    require(
        isinstance(actual_move_number, int)
        and not isinstance(actual_move_number, bool)
        and 1 <= actual_move_number <= len(game.moves),
        unit_id,
        "actualMoveNumber必须指向可重建落子序列中的实战手",
    )
    require(
        turn == actual_move_number,
        unit_id,
        "turn必须与actualMoveNumber指向同一实战手",
    )
    try:
        before_actual, _ = goboard.replay(game, upto=actual_move_number - 1)
        after_actual, _ = goboard.replay(game, upto=actual_move_number)
    except (goboard.IllegalMove, ValueError, AssertionError) as exc:
        raise CorpusError(f"{unit_id}: 目标手数局面无法合法重建：{exc}") from exc
    actual_record = game.moves[actual_move_number - 1]
    subject_color = actual_record.color
    derived_to_play = _next_color(game, actual_move_number)
    require(board_meta.get("subjectColor") == subject_color, unit_id, "subjectColor与实战手行棋方不一致")
    require(board_meta.get("toPlay") == derived_to_play, unit_id, "toPlay与实战手后局面不一致")
    analysis_hash_before = position_hash(
        before_actual, subject_color, game.info.get("KM")
    )
    actual_hash_after = position_hash(
        after_actual, derived_to_play, game.info.get("KM")
    )
    require(
        board_meta.get("analysisPositionHashBefore") == analysis_hash_before,
        unit_id,
        "analysisPositionHashBefore与实战手前局面不一致",
    )
    require(
        board_meta.get("actualPositionHashAfter") == actual_hash_after,
        unit_id,
        "actualPositionHashAfter与实战手后局面不一致",
    )
    # positionHash/turn/toPlay 是 v1 样本的实战手后兼容字段，不再承担
    # KataGo 分析身份。保留严格等值检查，防止旧消费方读到歧义数据。
    require(
        board_meta.get("positionHash") == actual_hash_after,
        unit_id,
        "positionHash与实战手后局面不一致",
    )
    actual_move = (
        "pass"
        if actual_record.is_pass
        else goboard.gtp_name(actual_record.coord, game.size)
    )
    require(
        str(board_meta.get("actualMove") or "").upper() == actual_move.upper(),
        unit_id,
        "actualMove与actualMoveNumber的落子不一致",
    )
    best_move = str(board_meta.get("bestMove") or "").strip()
    require(bool(best_move), unit_id, "缺少与实战手同局面的AI首选")
    question_target = str(board_meta.get("questionTargetMove") or "").strip()
    require(bool(question_target), unit_id, "缺少questionTargetMove")
    target_kind = board_meta.get("targetKind")
    expected_targets = {
        "actual": {actual_move.upper()},
        "best": {best_move.upper()},
        "comparison": {actual_move.upper(), best_move.upper()},
        "position": {best_move.upper()},
    }.get(target_kind, set())
    require(
        question_target.upper() in expected_targets,
        unit_id,
        "questionTargetMove与targetKind指向的实战手/AI首选不一致",
    )
    captured_color = goboard.WHITE if subject_color == "B" else goboard.BLACK
    captured_stones = int(after_actual.captured[captured_color]) - int(
        before_actual.captured[captured_color]
    )
    ko_point_after = None
    if after_actual.ko:
        ko_x, ko_y = after_actual.ko
        ko_point_after = goboard.gtp_name(
            chr(97 + ko_x) + chr(97 + ko_y), game.size
        )
    return {
        "turn": turn,
        "toPlay": derived_to_play,
        "positionHash": actual_hash_after,
        "boardFingerprint": board_similarity_fingerprint(before_actual, subject_color),
        "gameIdentity": game_identity(game),
        "actualMoveNumber": actual_move_number,
        "subjectColor": subject_color,
        "analysisPositionHashBefore": analysis_hash_before,
        "actualPositionHashAfter": actual_hash_after,
        "questionTargetMove": question_target.upper(),
        "actualMove": actual_move,
        "boardSize": game.size,
        "capturedStones": captured_stones,
        "koPointAfter": ko_point_after,
        # 只供本进程复核候选 PV，compile_row 不会把 Board 对象投影进训练集。
        "_analysisBoardBefore": before_actual,
        "_komi": normalize_komi(game.info.get("KM"), _katago_rules(game)),
        "_katagoRules": _katago_rules(game),
    }


def _katago_rules(game: sgf.Game) -> str:
    raw = str(game.info.get("RU", "chinese")).lower()
    if "japan" in raw:
        return "japanese"
    if "korea" in raw:
        return "korean"
    if "aga" in raw:
        return "aga"
    return "chinese"


def _gtp_to_sgf(coord: str, board_size: int) -> str:
    if coord == "PASS":
        return ""
    column = "ABCDEFGHJKLMNOPQRST".index(coord[0])
    row_from_top = board_size - int(coord[1:])
    return chr(97 + column) + chr(97 + row_from_top)


def _verify_candidate_pvs(
    candidates: list[dict[str, Any]], rebuilt: dict[str, Any], unit_id: str
) -> None:
    """每条 PV 都从同一落子前局面、由 subjectColor 开始交替重放。"""
    subject = rebuilt["subjectColor"]
    first_color = goboard.BLACK if subject == "B" else goboard.WHITE
    for candidate in candidates:
        move = candidate["move"]
        board = copy.deepcopy(rebuilt["_analysisBoardBefore"])
        color = first_color
        for ply, coord in enumerate(candidate["pv"], 1):
            try:
                board.play(color, _gtp_to_sgf(coord, rebuilt["boardSize"]))
            except (goboard.IllegalMove, ValueError, AssertionError) as exc:
                side = "B" if color == goboard.BLACK else "W"
                raise CorpusError(
                    f"{unit_id}: KataGo候选{move} PV第{ply}手{side} {coord}非法：{exc}"
                ) from exc
            color = goboard.WHITE if color == goboard.BLACK else goboard.BLACK


def verified_katago_facts(
    unit: dict[str, Any],
    rebuilt: dict[str, Any],
    katago_registry: trusted_katago.TrustedKataGoRegistry | None = None,
    *,
    require_registry: bool = True,
) -> dict[str, Any]:
    """从外部受信 registry 解析 KataGo 制品，再复核局面与 PV。"""
    unit_id = str(unit.get("id") or "<missing-id>")
    board = unit.get("board") or {}
    katago = ((unit.get("evidence") or {}).get("katagoFacts") or {})
    require(katago.get("status") == "verified", unit_id, "KataGo证据未核验")
    require(katago.get("source") == "katago", unit_id, "KataGo来源错误")
    require(katago.get("demo") is False, unit_id, "Mock结果不能进入训练")
    require(
        isinstance(katago.get("visits"), int)
        and not isinstance(katago.get("visits"), bool)
        and katago["visits"] >= 128,
        unit_id,
        "训练金标至少需要128 visits",
    )
    require(
        katago.get("analysisPositionHashBefore")
        == rebuilt["analysisPositionHashBefore"],
        unit_id,
        "KataGo证据与实战手不属于同一落子前局面",
    )
    require(
        katago.get("subjectColor") == rebuilt["subjectColor"],
        unit_id,
        "KataGo证据与实战手不属于同一行棋方",
    )

    # 先对单元中的内联副本做完整显错，它仍然不是信任根。
    inline_artifact = katago.get("analysisArtifact")
    require(isinstance(inline_artifact, dict), unit_id, "KataGo缺少analysisArtifact审核副本")
    try:
        artifact = trusted_katago.canonicalize_artifact(inline_artifact)
    except trusted_katago.RegistryError as exc:
        raise CorpusError(f"{unit_id}: KataGo analysisArtifact审核副本无效：{exc}") from exc

    require(artifact.get("schemaVersion") == KATAGO_ARTIFACT_SCHEMA, unit_id, "KataGo artifact版本错误")
    visits = artifact["visits"]
    position = artifact["position"]
    rules = artifact["rules"]
    require(
        position["analysisPositionHashBefore"] == rebuilt["analysisPositionHashBefore"],
        unit_id,
        "KataGo受信制品与实战手不属于同一落子前局面",
    )
    require(
        position["moveNumber"] == rebuilt["actualMoveNumber"] - 1,
        unit_id,
        "KataGo受信制品的落子前手数不一致",
    )
    require(artifact["subjectColor"] == rebuilt["subjectColor"], unit_id, "KataGo受信制品行棋方不一致")
    require(rules["boardSize"] == rebuilt["boardSize"], unit_id, "KataGo受信制品棋盘尺寸不一致")
    require(rules["name"] == rebuilt["_katagoRules"], unit_id, "KataGo受信制品规则不一致")
    require(float(rules["komi"]) == float(rebuilt["_komi"]), unit_id, "KataGo受信制品贴目不一致")

    best_move = artifact["bestMove"]
    require(best_move == str(board.get("bestMove") or "").upper(), unit_id, "棋盘首选与KataGo受信制品首选不一致")
    normalized_candidates = artifact["candidates"]
    _verify_candidate_pvs(normalized_candidates, rebuilt, unit_id)
    seen_moves = {candidate["move"] for candidate in normalized_candidates}
    actual_move = rebuilt["actualMove"].upper()
    require(best_move in seen_moves, unit_id, "KataGo候选缺少首选")
    require(actual_move in seen_moves, unit_id, "KataGo候选缺少实战手，无法形成可验证比较")
    if actual_move != best_move:
        require(len(seen_moves) >= 2, unit_id, "KataGo比较至少需要实战手和首选两个候选")

    for field, value in (
        ("source", "katago"),
        ("demo", False),
        ("visits", visits),
        ("analysisPositionHashBefore", rebuilt["analysisPositionHashBefore"]),
        ("subjectColor", rebuilt["subjectColor"]),
        ("bestMove", best_move),
    ):
        require(katago.get(field) == value, unit_id, f"KataGo外层{field}与受信制品不一致")
    artifact_hash = canonical_json_sha256(artifact)
    variation_artifact = {
        "schemaVersion": "katago-variation-evidence-v1",
        "analysisPositionHashBefore": rebuilt["analysisPositionHashBefore"],
        "subjectColor": rebuilt["subjectColor"],
        "candidates": normalized_candidates,
    }
    variation_hash = canonical_json_sha256(variation_artifact)
    require(
        katago.get("analysisArtifactSha256") == artifact_hash,
        unit_id,
        "KataGo analysisArtifactSha256与内联制品不一致",
    )
    require(
        katago.get("variationEvidenceHash") == variation_hash,
        unit_id,
        "KataGo variationEvidenceHash与内联候选/PV不一致",
    )

    # 最后才跨越信任边界：即使调用者篡改数值并重算了上面所有哈希，
    # 只要服务端 registry 没有登记该制品，金标就必须 fail closed。
    trusted_artifact = artifact
    registry_verified = False
    if katago_registry is not None:
        try:
            trusted_artifact = katago_registry.resolve(katago.get("trustedArtifactRef"))
        except trusted_katago.RegistryError as exc:
            raise CorpusError(f"{unit_id}: 受信KataGo artifact引用无效：{exc}") from exc
        require(
            canonical_json(trusted_artifact) == canonical_json(artifact),
            unit_id,
            "KataGo内联analysisArtifact与受信registry制品不一致",
        )
        registry_verified = True
    elif require_registry:
        raise CorpusError(f"{unit_id}: 缺少受信KataGo artifact registry，金标默认关闭")
    return {
        "status": "verified",
        "source": "katago",
        "demo": False,
        "visits": visits,
        "analysisPositionHashBefore": rebuilt["analysisPositionHashBefore"],
        "subjectColor": rebuilt["subjectColor"],
        "bestMove": best_move,
        "registryVerified": registry_verified,
        "trustedArtifactRef": copy.deepcopy(katago.get("trustedArtifactRef")),
        "analysisArtifact": trusted_artifact,
        "analysisArtifactSha256": artifact_hash,
        "variationEvidenceHash": variation_hash,
    }


def verified_rule_facts(
    unit: dict[str, Any], rebuilt: dict[str, Any]
) -> dict[str, Any]:
    """把 goboard 可重建的局面身份、合法实战手与结果绑定起来。"""
    unit_id = str(unit.get("id") or "<missing-id>")
    rules = ((unit.get("evidence") or {}).get("ruleFacts") or {})
    require(
        rules.get("status") == "verified" and rules.get("source") == "goboard",
        unit_id,
        "规则事实必须由goboard核验",
    )
    artifact = rules.get("ruleArtifact")
    require(isinstance(artifact, dict), unit_id, "规则事实缺少可重建ruleArtifact")
    normalized_artifact = {
        "schemaVersion": RULE_ARTIFACT_SCHEMA,
        "source": "goboard",
        "rules": "simple-ko-no-suicide",
        "legal": True,
        "boardSize": rebuilt["boardSize"],
        "analysisPositionHashBefore": rebuilt["analysisPositionHashBefore"],
        "actualPositionHashAfter": rebuilt["actualPositionHashAfter"],
        "actualMoveNumber": rebuilt["actualMoveNumber"],
        "subjectColor": rebuilt["subjectColor"],
        "actualMove": rebuilt["actualMove"].upper(),
        "toPlayAfter": rebuilt["toPlay"],
        "capturedStones": rebuilt["capturedStones"],
        "koPointAfter": rebuilt["koPointAfter"],
    }
    for field, value in normalized_artifact.items():
        require(artifact.get(field) == value, unit_id, f"ruleArtifact.{field}与goboard重建结果不一致")
    artifact_hash = canonical_json_sha256(normalized_artifact)
    require(
        rules.get("ruleArtifactSha256") == artifact_hash,
        unit_id,
        "ruleArtifactSha256与goboard规范制品不一致",
    )
    return {
        "status": "verified",
        "source": "goboard",
        "ruleArtifact": normalized_artifact,
        "ruleArtifactSha256": artifact_hash,
    }


def _status_values(value: Any, parent_key: str = ""):
    """枚举显式状态字段，也覆盖 review 下的逐项审核状态。"""
    if isinstance(value, dict):
        for key, item in value.items():
            normalized_key = str(key).lower()
            is_status = normalized_key == "status" or normalized_key.endswith("status")
            is_review_status = parent_key == "review" and key in (
                "transcript", "board", "semantics"
            )
            if isinstance(item, str) and (is_status or is_review_status):
                yield item
            else:
                yield from _status_values(item, normalized_key)
    elif isinstance(value, list):
        for item in value:
            yield from _status_values(item, parent_key)


def validate_unit(
    unit: dict[str, Any],
    sources: dict[str, dict[str, Any]],
    *,
    source_chain: trusted_source_chain.SourceChainRegistry | None = None,
    review_registry: trusted_source_chain.HumanReviewRegistry | None = None,
    katago_registry: Any | None = None,
) -> None:
    unit_id = str(unit.get("id") or "<missing-id>")
    schema_version = unit.get("schemaVersion")
    require(
        schema_version in (*LEGACY_UNIT_SCHEMAS, UNIT_SCHEMA),
        unit_id,
        "schemaVersion错误",
    )
    source_meta = unit.get("source") or {}
    source_id = source_meta.get("sourceId")
    require(source_id in sources, unit_id, "sourceId不在许可台账")
    source = sources[source_id]
    required_uses = {"ai_training", "lora_finetuning"}
    require(required_uses <= set(source.get("use") or []), unit_id, "来源未授权模型训练")
    require(
        source_meta.get("authorizationId") == source.get("authorizationId"),
        unit_id,
        "authorizationId与许可台账不一致",
    )
    require(source_meta.get("creator") == source.get("author"), unit_id, "作者不一致")
    video_id = str(source_meta.get("videoId") or "")
    require(video_id.startswith("BV"), unit_id, "缺少有效BV号")
    require(
        source_meta.get("videoUrl") == f"https://www.bilibili.com/video/{video_id}",
        unit_id,
        "原视频URL与BV号不一致",
    )
    start_ms = source_meta.get("startMs")
    end_ms = source_meta.get("endMs")
    require(
        isinstance(start_ms, int)
        and not isinstance(start_ms, bool)
        and isinstance(end_ms, int)
        and not isinstance(end_ms, bool)
        and 0 <= start_ms < end_ms,
        unit_id,
        "时间段必须是递增的非负毫秒值",
    )
    transcript_sha = str(source_meta.get("transcriptSha256") or "")
    require(bool(SHA256_RE.fullmatch(transcript_sha)), unit_id, "缺少有效转写SHA-256")

    eligible = unit.get("trainingEligible") is True
    require(
        not eligible or schema_version == UNIT_SCHEMA,
        unit_id,
        "旧版教学单元只能保留为候选，不能进入训练",
    )
    transcript = unit.get("transcript") or {}
    board = unit.get("board") or {}
    evidence = unit.get("evidence") or {}
    has_machine_or_candidate = any(
        "machine" in value.lower() or "candidate" in value.lower()
        for value in _status_values(unit)
    )
    require(
        not (eligible and has_machine_or_candidate),
        unit_id,
        "包含machine/candidate状态时trainingEligible必须为false",
    )
    if not eligible:
        return

    require(transcript.get("status") == "human_verified", unit_id, "转写未经人工核验")
    verified_transcript_artifact(unit)
    require(board.get("status") == "human_verified", unit_id, "棋盘未经人工核验")
    require(board.get("targetKind") in TARGET_KINDS, unit_id, "targetKind错误")
    rebuilt = reconstruct_board_facts(unit)
    katago_facts = verified_katago_facts(
        unit, rebuilt, katago_registry, require_registry=False
    )
    verified_rule_facts(unit, rebuilt)
    claims = evidence.get("teacherHeuristics")
    require(isinstance(claims, list) and claims, unit_id, "缺少专家判断")
    for claim in claims:
        require(
            isinstance(claim, dict) and claim.get("confidence") == "expert_opinion",
            unit_id,
            "专家判断必须标为expert_opinion",
        )
        require(bool(str(claim.get("claim") or "").strip()), unit_id, "专家判断为空")
        require(bool(str(claim.get("basis") or "").strip()), unit_id, "专家判断缺少来源依据")
    expression = evidence.get("teacherExpression") or {}
    require(bool(str(expression.get("question") or "").strip()), unit_id, "缺少问题")
    require(bool(str(expression.get("answer") or "").strip()), unit_id, "缺少专家回答")
    try:
        validate_gold_answer(unit, rebuilt, katago_facts)
    except AnswerConsistencyError as exc:
        raise CorpusError(f"{unit_id}: 教学回答与权威证据不一致：{exc}") from exc
    require(
        (evidence.get("llmExpression") or {}).get("status") == "not_ground_truth",
        unit_id,
        "LLM表达必须明确不是金标事实",
    )
    require(unit.get("splitGroup") == f"video:{video_id}", unit_id, "必须按整条视频隔离")
    pedagogy = unit.get("pedagogy") or {}
    require(bool(pedagogy.get("competencies")), unit_id, "缺少教学能力标签")
    require(bool(pedagogy.get("mechanism")), unit_id, "缺少围棋机制")
    require(bool(str(pedagogy.get("boundary") or "").strip()), unit_id, "缺少结论边界")
    require(source_chain is not None, unit_id, "受信来源链registry缺失")
    try:
        source_binding = source_chain.binding_for_unit(source_meta)
    except trusted_source_chain.TrustError as exc:
        raise CorpusError(f"{unit_id}: 来源链校验失败：{exc}") from exc
    require(
        source_binding.get("creator") == source.get("author"),
        unit_id,
        "来源链作者与许可台账不一致",
    )
    require(
        source_binding.get("creatorPlatformId") == source.get("platformUserId"),
        unit_id,
        "来源链作者UID与许可台账不一致",
    )
    board_frame = board.get("frameEvidence")
    if isinstance(board_frame, dict):
        source_frame = source_meta.get("sourceChain") or {}
        require(
            board_frame.get("timestampMs") == source_frame.get("frameTimestampMs"),
            unit_id,
            "棋盘帧时间与受信来源链不一致",
        )
        require(
            str(board_frame.get("frameSha256") or "").lower()
            == str(source_frame.get("frameSha256") or "").lower(),
            unit_id,
            "棋盘帧SHA-256与受信来源链不一致",
        )
    require(review_registry is not None, unit_id, "独立人工审核registry/JSONL缺失")
    try:
        review_registry.verify(unit, source_binding)
    except trusted_source_chain.TrustError as exc:
        raise CorpusError(f"{unit_id}: 独立人工审核失败：{exc}") from exc
    require(
        katago_facts.get("registryVerified") is True,
        unit_id,
        "缺少受信KataGo artifact registry，金标默认关闭",
    )


def read_units(path: Path) -> list[dict[str, Any]]:
    units = []
    seen_ids: set[str] = set()
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise CorpusError(f"{path}:{line_number}: JSON错误: {exc}") from exc
            if not isinstance(value, dict):
                raise CorpusError(f"{path}:{line_number}: 每行必须是对象")
            unit_id = str(value.get("id") or "").strip()
            if unit_id in seen_ids:
                raise CorpusError(f"{path}:{line_number}: 重复的unit id：{unit_id}")
            seen_ids.add(unit_id)
            units.append(value)
    return units


def stable_split(groups: set[str], eval_ratio: float, seed: int) -> set[str]:
    ordered = sorted(groups)
    random.Random(seed).shuffle(ordered)
    if len(ordered) <= 1:
        return set()
    count = max(1, round(len(ordered) * eval_ratio))
    return set(ordered[:count])


def load_creator_coverage_manifest(
    path: Path,
    expected_sha256: str,
    units_path: Path,
    units: list[dict[str, Any]],
) -> tuple[dict[str, set[str]], dict[str, Any]]:
    """Load evidence-bound additive taxonomy without changing signed unit content."""
    expected = str(expected_sha256 or "").lower()
    require(bool(SHA256_RE.fullmatch(expected)), "<coverage-manifest>", "coverage manifest SHA-256 invalid")
    require(sha256_file(path) == expected, "<coverage-manifest>", "coverage manifest SHA-256 mismatch")
    document = read_json(path)
    require(
        document.get("schemaVersion") == COVERAGE_MANIFEST_SCHEMA,
        "<coverage-manifest>",
        "coverage manifest schema mismatch",
    )
    require(
        document.get("releaseSha256") == sha256_file(units_path),
        "<coverage-manifest>",
        "coverage manifest is not bound to the current signed release",
    )
    require(
        document.get("trainingContentChanged") is False
        and document.get("approvalContentHashesChanged") is False,
        "<coverage-manifest>",
        "coverage mapping must not change signed content or approval hashes",
    )
    unit_by_id = {str(unit.get("id") or ""): unit for unit in units}
    mappings = document.get("mappings")
    require(isinstance(mappings, list), "<coverage-manifest>", "mappings must be an array")
    additions: dict[str, set[str]] = {}
    for index, row in enumerate(mappings, 1):
        require(isinstance(row, dict), "<coverage-manifest>", f"mapping {index} must be an object")
        unit_id = str(row.get("unitId") or "").strip()
        require(unit_id in unit_by_id, "<coverage-manifest>", f"unknown unitId: {unit_id}")
        require(unit_by_id[unit_id].get("trainingEligible") is True, unit_id, "coverage mapping requires signed training-eligible unit")
        require(unit_id not in additions, unit_id, "duplicate coverage mapping")
        themes = row.get("addThemes")
        require(isinstance(themes, list) and themes, unit_id, "addThemes must be a non-empty array")
        normalized = {str(theme) for theme in themes}
        require(normalized <= REQUIRED_CREATOR_THEMES, unit_id, "coverage mapping contains an unknown formal theme")
        conclusion = str((unit_by_id[unit_id].get("pedagogy") or {}).get("conclusion") or "")
        require(bool(conclusion), unit_id, "signed teaching conclusion is missing")
        require(
            row.get("teacherConclusionSha256") == hashlib.sha256(conclusion.encode("utf-8")).hexdigest(),
            unit_id,
            "coverage evidence no longer matches the signed teaching conclusion",
        )
        require(bool(str(row.get("evidenceBasis") or "").strip()), unit_id, "coverage evidenceBasis is required")
        additions[unit_id] = normalized
    return additions, {
        "schemaVersion": COVERAGE_MANIFEST_SCHEMA,
        "sha256": expected,
        "releaseSha256": document.get("releaseSha256"),
        "mappingCount": len(additions),
    }


def explicit_split_assignments(
    path: Path,
    expected_sha256: str,
    units: list[dict[str, Any]],
    coverage_additions: dict[str, set[str]] | None = None,
) -> tuple[dict[str, str], dict[str, Any]]:
    """Load the award split contract and enforce exact 48/8/8 isolation."""
    expected = str(expected_sha256 or "").lower()
    require(bool(SHA256_RE.fullmatch(expected)), "<split-manifest>", "切分manifest SHA-256无效")
    require(sha256_file(path) == expected, "<split-manifest>", "切分manifest SHA-256不一致")
    document = read_json(path)
    require(
        document.get("schemaVersion") == SPLIT_MANIFEST_SCHEMA,
        "<split-manifest>",
        "切分manifest schema错误",
    )
    rows = document.get("assignments")
    require(isinstance(rows, list), "<split-manifest>", "切分assignments必须是数组")
    assignments: dict[str, str] = {}
    for index, row in enumerate(rows, 1):
        require(isinstance(row, dict), "<split-manifest>", f"第{index}条assignment无效")
        unit_id = str(row.get("unitId") or "").strip()
        split = str(row.get("split") or "").strip()
        require(bool(unit_id), "<split-manifest>", f"第{index}条缺少unitId")
        require(split in EXPLICIT_SPLIT_COUNTS, unit_id, "split必须是train/dev/test")
        require(unit_id not in assignments, unit_id, "切分manifest重复unitId")
        assignments[unit_id] = split
    eligible = {str(unit.get("id") or "") for unit in units if unit.get("trainingEligible") is True}
    require(set(assignments) == eligible, "<split-manifest>", "切分manifest必须精确覆盖全部可训练单元")
    counts = {name: sum(split == name for split in assignments.values()) for name in EXPLICIT_SPLIT_COUNTS}
    require(counts == EXPLICIT_SPLIT_COUNTS, "<split-manifest>", f"金标必须精确48/8/8，实际为{counts}")

    unit_by_id = {str(unit.get("id") or ""): unit for unit in units}
    video_splits: dict[str, set[str]] = {}
    video_unit_counts: dict[str, int] = {}
    target_counts: dict[str, int] = {name: 0 for name in TARGET_KINDS}
    theme_counts: dict[str, int] = {name: 0 for name in REQUIRED_CREATOR_THEMES}
    split_target_counts: dict[str, dict[str, int]] = {
        split: {name: 0 for name in TARGET_KINDS} for split in EXPLICIT_SPLIT_COUNTS
    }
    split_theme_counts: dict[str, dict[str, int]] = {
        split: {name: 0 for name in REQUIRED_CREATOR_THEMES}
        for split in EXPLICIT_SPLIT_COUNTS
    }
    for unit_id, split in assignments.items():
        unit = unit_by_id[unit_id]
        video_id = str((unit.get("source") or {}).get("videoId") or "")
        video_splits.setdefault(video_id, set()).add(split)
        video_unit_counts[video_id] = video_unit_counts.get(video_id, 0) + 1
        target = str((unit.get("board") or {}).get("targetKind") or "")
        if target in target_counts:
            target_counts[target] += 1
            split_target_counts[split][target] += 1
        competencies = {
            CREATOR_THEME_ALIASES.get(str(value), str(value))
            for value in ((unit.get("pedagogy") or {}).get("competencies") or [])
        }
        competencies |= (coverage_additions or {}).get(unit_id, set())
        for theme in REQUIRED_CREATOR_THEMES & competencies:
            theme_counts[theme] += 1
            split_theme_counts[split][theme] += 1
    leaking_videos = sorted(video for video, splits in video_splits.items() if len(splits) != 1)
    require(not leaking_videos, "<split-manifest>", f"视频跨集合泄漏：{leaking_videos[:3]}")
    require(
        len(video_unit_counts) == 16 and all(count == 4 for count in video_unit_counts.values()),
        "<split-manifest>",
        f"金标必须来自16个视频且每个视频4条：videos={len(video_unit_counts)}",
    )
    video_counts = {
        split: len({video for video, splits in video_splits.items() if split in splits})
        for split in EXPLICIT_SPLIT_COUNTS
    }
    require(
        video_counts == {"train": 12, "dev": 2, "test": 2},
        "<split-manifest>",
        f"视频切分必须精确12/2/2：{video_counts}",
    )
    require(
        all(target_counts.get(name, 0) >= 16 for name in ("actual", "best", "comparison")),
        "<split-manifest>",
        f"actual/best/comparison必须各至少16条：{target_counts}",
    )
    require(
        all(theme_counts[name] >= 4 for name in REQUIRED_CREATOR_THEMES),
        "<split-manifest>",
        f"12类棋理主题必须各至少4条：{theme_counts}",
    )
    require(
        all(split_target_counts["train"].get(name, 0) >= 8 for name in ("actual", "best", "comparison")),
        "<split-manifest>",
        f"train的actual/best/comparison必须各至少8条：{split_target_counts['train']}",
    )
    for split in ("dev", "test"):
        require(
            sum(count > 0 for count in split_target_counts[split].values()) >= 2,
            "<split-manifest>",
            f"{split}至少覆盖两种问题目标：{split_target_counts[split]}",
        )
    require(
        all(split_theme_counts["train"][name] >= 2 for name in REQUIRED_CREATOR_THEMES),
        "<split-manifest>",
        f"train十二类主题必须各至少2条：{split_theme_counts['train']}",
    )
    return assignments, {
        "sha256": expected,
        "counts": counts,
        "videoCounts": video_counts,
        "targetCounts": target_counts,
        "themeCounts": theme_counts,
        "splitTargetCounts": split_target_counts,
        "splitThemeCounts": split_theme_counts,
    }


def assert_compiled_split_isolation(rows_by_split: dict[str, list[dict[str, Any]]]) -> None:
    keys: dict[str, set[str]] = {name: set() for name in EXPLICIT_SPLIT_COUNTS}
    for split, rows in rows_by_split.items():
        for row in rows:
            metadata = row.get("metadata") or {}
            for name in (
                "videoId", "gameIdentity", "positionHash", "boardFingerprint",
            ):
                value = str(metadata.get(name) or "").strip()
                if value:
                    keys[split].add(f"{name}:{value}")
    for left, right in (("train", "dev"), ("train", "test"), ("dev", "test")):
        overlap = keys[left] & keys[right]
        require(not overlap, "<split-manifest>", f"{left}/{right}存在来源或对称局面泄漏：{sorted(overlap)[:3]}")


def compile_row(
    unit: dict[str, Any],
    *,
    source_chain: trusted_source_chain.SourceChainRegistry | None = None,
    review_registry: trusted_source_chain.HumanReviewRegistry | None = None,
    katago_registry: Any | None = None,
    coverage_themes: set[str] | None = None,
) -> dict[str, Any]:
    sources = load_sources()
    validate_unit(
        unit,
        sources,
        source_chain=source_chain,
        review_registry=review_registry,
        katago_registry=katago_registry,
    )
    unit_id = str(unit.get("id") or "<missing-id>")
    require(unit.get("trainingEligible") is True, unit_id, "候选单元不能编译进训练集")
    source = unit["source"]
    source_policy = sources.get(source["sourceId"]) or {}
    board = unit["board"]
    evidence = unit["evidence"]
    expression = evidence["teacherExpression"]
    rebuilt = reconstruct_board_facts(unit)
    transcript_artifact = verified_transcript_artifact(unit)
    katago_facts = verified_katago_facts(unit, rebuilt, katago_registry)
    rule_facts = verified_rule_facts(unit, rebuilt)
    source_binding = source_chain.binding_for_unit(source)
    approval = review_registry.verify(unit, source_binding)
    expert_heuristics = [
        {
            "claim": claim["claim"],
            "confidence": "expert_opinion",
            "basis": claim.get("basis"),
        }
        for claim in evidence["teacherHeuristics"]
    ]
    pedagogy = unit["pedagogy"]
    normalized_competencies = sorted({
        CREATOR_THEME_ALIASES.get(str(value), str(value))
        for value in (pedagogy.get("competencies") or [])
    } | set(coverage_themes or ()))
    projected_evidence = {
        "questionTarget": board["targetKind"],
        "questionTargetMove": rebuilt["questionTargetMove"],
        "turn": rebuilt["turn"],
        "toPlay": rebuilt["toPlay"],
        "positionHash": rebuilt["positionHash"],
        "boardFingerprint": rebuilt["boardFingerprint"],
        "gameIdentity": rebuilt["gameIdentity"],
        "actualMoveNumber": rebuilt["actualMoveNumber"],
        "subjectColor": rebuilt["subjectColor"],
        "analysisPositionHashBefore": rebuilt["analysisPositionHashBefore"],
        "actualPositionHashAfter": rebuilt["actualPositionHashAfter"],
        "actualMove": rebuilt["actualMove"],
        "bestMove": katago_facts["bestMove"],
        "transcriptArtifactSha256": canonical_json_sha256(transcript_artifact),
        "katagoFacts": katago_facts,
        "ruleFacts": rule_facts,
        "expertHeuristics": expert_heuristics,
        "pedagogy": {
            "competencies": normalized_competencies,
            "mechanism": pedagogy["mechanism"],
            "boundary": pedagogy["boundary"],
        },
        "claimBoundary": pedagogy["boundary"],
    }
    answer = validated_sft_answer(expression, unit_id)
    assistant = {
        "answer": answer,
        "followUps": expression.get("followUps") or [],
    }
    return {
        "messages": [
            {"role": "system", "content": SYSTEM},
            {
                "role": "user",
                "content": "证据：" + json.dumps(projected_evidence, ensure_ascii=False)
                + "\n问题：" + expression["question"],
            },
            {"role": "assistant", "content": json.dumps(assistant, ensure_ascii=False)},
        ],
        "metadata": {
            "id": unit["id"],
            "scenarioId": unit["splitGroup"],
            "competency": normalized_competencies,
            "target": board["targetKind"],
            "sourceIds": [source["sourceId"], "katago"],
            "authorizationId": source["authorizationId"],
            "license": "creator-authorized",
            "projectUseMode": source_policy.get("projectUseMode"),
            "commercialDeployment": False,
            "creator": source["creator"],
            "videoId": source["videoId"],
            "videoUrl": source["videoUrl"],
            "gameIdentity": rebuilt["gameIdentity"],
            "boardFingerprint": rebuilt["boardFingerprint"],
            "positionHash": rebuilt["positionHash"],
            "timeRangeMs": [source["startMs"], source["endMs"]],
            "transcriptSha256": canonical_json_sha256(transcript_artifact),
            "sourceChainId": source_binding["chainId"],
            "sourceChainBindingSha256": canonical_json_sha256(source_binding),
            "sourceManifestSha256": source_binding["manifestSha256"],
            "reviewApprovalId": approval["approvalId"],
            "reviewerId": approval["reviewerId"],
            "reviewedAt": approval["reviewedAt"],
            "reviewInputHashes": approval["hashes"],
            "reviewerRegistrySha256": approval["reviewerRegistrySha256"],
            "reviewApprovalsSha256": approval["reviewApprovalsSha256"],
            "splitGroup": unit["splitGroup"],
            "generator": OUTPUT_SCHEMA,
        },
    }


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--eval-ratio", type=float, default=0.2)
    parser.add_argument(
        "--test-ratio", type=float, default=0.0,
        help="可选封存测试集比例；启用后eval作为开发集，test仅供最终一次验收",
    )
    parser.add_argument("--seed", type=int, default=20260801)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--source-chain-registry", type=Path)
    parser.add_argument("--source-chain-registry-sha256")
    parser.add_argument("--reviewer-registry", type=Path)
    parser.add_argument("--reviewer-registry-sha256")
    parser.add_argument("--review-approvals", type=Path)
    parser.add_argument("--review-approvals-sha256")
    parser.add_argument("--katago-registry", type=Path)
    parser.add_argument("--katago-registry-sha256")
    parser.add_argument(
        "--split-manifest", type=Path,
        help="可选显式 creator-split-manifest-v1；启用后强制精确48/8/8与主题门禁",
    )
    parser.add_argument("--split-manifest-sha256")
    parser.add_argument(
        "--coverage-manifest", type=Path,
        help="optional evidence-bound creator-coverage-manifest-v1 taxonomy mapping",
    )
    parser.add_argument("--coverage-manifest-sha256")
    args = parser.parse_args()
    if not 0 <= args.eval_ratio < 1:
        raise SystemExit("--eval-ratio 必须位于 [0, 1)。")
    if not 0 <= args.test_ratio < 1:
        raise SystemExit("--test-ratio 必须位于 [0, 1)。")
    if args.eval_ratio + args.test_ratio >= 1:
        raise SystemExit("开发集与封存测试集比例之和必须小于1。")

    sources = load_sources()
    units = read_units(args.input)
    source_chain = None
    review_registry = None
    katago_registry = None
    source_chain_args = (
        args.source_chain_registry,
        args.source_chain_registry_sha256,
    )
    review_args = (
        args.reviewer_registry,
        args.review_approvals,
        args.reviewer_registry_sha256,
        args.review_approvals_sha256,
    )
    katago_registry_args = (
        args.katago_registry,
        args.katago_registry_sha256,
    )
    if any(source_chain_args):
        if not all(source_chain_args):
            raise SystemExit("来源链registry路径与SHA-256必须同时提供。")
        try:
            source_chain = trusted_source_chain.SourceChainRegistry.load(
                args.source_chain_registry,
                args.source_chain_registry_sha256,
            )
        except trusted_source_chain.TrustError as exc:
            raise SystemExit(f"来源链registry不受信：{exc}") from exc
    if any(review_args):
        if not all(review_args):
            raise SystemExit("审核人registry、审批JSONL及两者SHA-256必须全部提供。")
        try:
            review_registry = trusted_source_chain.HumanReviewRegistry.load(
                args.reviewer_registry,
                args.review_approvals,
                args.reviewer_registry_sha256,
                args.review_approvals_sha256,
            )
        except trusted_source_chain.TrustError as exc:
            raise SystemExit(f"人工审核registry/JSONL不受信：{exc}") from exc
    if any(katago_registry_args):
        if not all(katago_registry_args):
            raise SystemExit("KataGo registry路径与快照SHA-256必须同时提供。")
        try:
            katago_registry = trusted_katago.load_registry_snapshot(
                args.katago_registry,
                expected_sha256=args.katago_registry_sha256,
            )
        except trusted_katago.RegistryError as exc:
            raise SystemExit(f"KataGo artifact registry不受信：{exc}") from exc
    errors = []
    for unit in units:
        try:
            validate_unit(
                unit,
                sources,
                source_chain=source_chain,
                review_registry=review_registry,
                katago_registry=katago_registry,
            )
        except CorpusError as exc:
            errors.append(str(exc))
    eligible = [unit for unit in units if unit.get("trainingEligible") is True]
    report = {
        "schemaVersion": "authorized-video-corpus-validation-v1",
        "input": str(args.input),
        "total": len(units),
        "trainingEligible": len(eligible),
        "errors": errors,
        "passed": not errors,
    }
    if errors or args.validate_only:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        raise SystemExit(0 if not errors else 1)

    split_contract = None
    coverage_additions: dict[str, set[str]] = {}
    coverage_contract = None
    coverage_args = (args.coverage_manifest, args.coverage_manifest_sha256)
    if any(coverage_args):
        if not all(coverage_args):
            raise SystemExit("coverage manifest path and SHA-256 must be provided together")
        coverage_additions, coverage_contract = load_creator_coverage_manifest(
            args.coverage_manifest.resolve(),
            args.coverage_manifest_sha256,
            args.input.resolve(),
            units,
        )
    explicit_args = (args.split_manifest, args.split_manifest_sha256)
    if any(explicit_args):
        if not all(explicit_args):
            raise SystemExit("显式切分manifest路径与SHA-256必须同时提供。")
        assignments, split_contract = explicit_split_assignments(
            args.split_manifest.resolve(), args.split_manifest_sha256, units,
            coverage_additions,
        )
        train_ids = {unit_id for unit_id, split in assignments.items() if split == "train"}
        eval_ids = {unit_id for unit_id, split in assignments.items() if split == "dev"}
        test_ids = {unit_id for unit_id, split in assignments.items() if split == "test"}
        eval_groups = {unit["splitGroup"] for unit in eligible if unit["id"] in eval_ids}
        test_groups = {unit["splitGroup"] for unit in eligible if unit["id"] in test_ids}
    else:
        groups = {unit["splitGroup"] for unit in eligible}
        holdout_ratio = args.eval_ratio + args.test_ratio
        holdout_groups = stable_split(groups, holdout_ratio, args.seed)
        test_groups = (
            stable_split(
                holdout_groups,
                args.test_ratio / holdout_ratio,
                args.seed + 1,
            )
            if holdout_ratio and args.test_ratio
            else set()
        )
        eval_groups = holdout_groups - test_groups
        train_ids = {
            unit["id"] for unit in eligible if unit["splitGroup"] not in holdout_groups
        }
        eval_ids = {
            unit["id"] for unit in eligible if unit["splitGroup"] in eval_groups
        }
        test_ids = {
            unit["id"] for unit in eligible if unit["splitGroup"] in test_groups
        }
    train_rows = [
        compile_row(
            unit,
            source_chain=source_chain,
            review_registry=review_registry,
            katago_registry=katago_registry,
            coverage_themes=coverage_additions.get(str(unit.get("id") or ""), set()),
        )
        for unit in eligible
        if unit["id"] in train_ids
    ]
    eval_rows = [
        compile_row(
            unit,
            source_chain=source_chain,
            review_registry=review_registry,
            katago_registry=katago_registry,
            coverage_themes=coverage_additions.get(str(unit.get("id") or ""), set()),
        )
        for unit in eligible
        if unit["id"] in eval_ids
    ]
    test_rows = [
        compile_row(
            unit,
            source_chain=source_chain,
            review_registry=review_registry,
            katago_registry=katago_registry,
            coverage_themes=coverage_additions.get(str(unit.get("id") or ""), set()),
        )
        for unit in eligible
        if unit["id"] in test_ids
    ]
    if split_contract is not None:
        assert_compiled_split_isolation({
            "train": train_rows, "dev": eval_rows, "test": test_rows,
        })
    output_dir = args.output_dir or (TRAINING_ROOT / "data" / "authorized-video-v3")
    write_jsonl(output_dir / "expert_sft_train.jsonl", train_rows)
    write_jsonl(output_dir / "expert_sft_eval.jsonl", eval_rows)
    if args.test_ratio:
        write_jsonl(output_dir / "expert_sft_test.jsonl", test_rows)
    manifest = {
        **report,
        "schemaVersion": OUTPUT_SCHEMA,
        "train": len(train_rows),
        "eval": len(eval_rows),
        "dev": len(eval_rows),
        "test": len(test_rows),
        "split": (
            "video-isolated-three-way"
            if split_contract is not None or args.test_ratio
            else "video-isolated"
        ),
        "evalGroups": sorted(eval_groups),
        "devGroups": sorted(eval_groups),
        "testGroups": sorted(test_groups),
        "sourcePolicy": read_json(SOURCE_REGISTRY).get("policyVersion"),
        "seed": args.seed,
        "splitContract": split_contract,
        "coverageContract": coverage_contract,
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
