# -*- coding: utf-8 -*-
"""棋谱导入兼容层：按内容识别 SGF/GIB，并统一为 SGF 主线。"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

import sgf


class ImportError(ValueError):
    pass


@dataclass
class ImportedGame:
    game: sgf.Game
    sgf_text: str
    original_format: str
    encoding: str
    platform: str
    black_name: str
    white_name: str
    black_rank: str = ""
    white_rank: str = ""
    aliases: list[str] = field(default_factory=list)
    event: str = ""
    date: str = ""
    result: str = ""
    komi: float | None = None
    rules: str = ""
    source_filename: str = ""

    @property
    def content_hash(self) -> str:
        canonical = f"{self.game.size}|" + "|".join(
            f"{move.color}:{move.coord.lower()}" for move in self.game.moves
        )
        return hashlib.sha256(canonical.encode("ascii")).hexdigest()


def decode_bytes(data: bytes) -> tuple[str, str]:
    if not data:
        raise ImportError("棋谱文件为空")
    for encoding in ("utf-8-sig", "gb18030", "gbk"):
        try:
            return data.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    raise ImportError("无法识别棋谱编码，请转换为 UTF-8、GB18030 或 GBK")


def detect_format(text: str) -> str:
    probe = text.lstrip("\ufeff\r\n\t ")
    if probe.startswith("(") and ("GM[1]" in probe[:500] or ";" in probe[:50]):
        return "sgf"
    if re.search(r"(?m)^\s*(?:\\\[)?GAME[A-Z]+=", text) or re.search(
        r"(?m)^\s*STO\s+\d+\s+\d+\s+[12]\s+\d+\s+\d+", text
    ):
        return "gib"
    raise ImportError("无法按文件内容识别 SGF 或 GIB 格式")


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("]", "\\]")


def _serialize(game: sgf.Game, info: dict[str, str]) -> str:
    ordered = ("GM", "FF", "CA", "AP", "SZ", "PB", "PW", "BR", "WR", "RE", "KM", "DT", "EV", "RU")
    properties = []
    normalized = {"GM": "1", "FF": "4", "CA": "UTF-8", "SZ": str(game.size), **info}
    for key in ordered:
        value = normalized.get(key)
        if value not in (None, ""):
            properties.append(f"{key}[{_escape(str(value))}]")
    for key, value in normalized.items():
        if key not in ordered and isinstance(value, str) and value:
            properties.append(f"{key}[{_escape(value)}]")
    nodes = "".join(f";{move.color}[{move.coord}]" for move in game.moves)
    return "(;" + "".join(properties) + nodes + ")"


def _float_komi(raw: str | None) -> float | None:
    if raw in (None, ""):
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    # 腾讯/野狐导出曾使用 375 表示中国规则黑贴 3 又 3/4 子，即 7.5 目。
    if value == 375:
        return 7.5
    return value


def _platform_from(filename: str, info: dict[str, str]) -> str:
    joined = " ".join((filename, info.get("AP", ""), info.get("PC", ""))).lower()
    if "腾讯" in joined:
        return "腾讯围棋"
    if "野狐" in joined or "fox" in joined:
        return "野狐围棋"
    if "弈城" in joined or "tygem" in joined or "eweiqi" in joined:
        return "弈城围棋"
    return "本地棋谱"


def _filename_aliases(filename: str, names: tuple[str, str]) -> list[str]:
    stem = Path(filename).stem
    aliases: list[str] = []
    for token in re.findall(r"\[([^\]]+)\]|([^_()]+)\(\d+段\)", stem):
        candidate = next((part.strip() for part in token if part.strip()), "")
        candidate = re.sub(r"(?:黑|白|腾讯围棋|野狐围棋|弈城围棋)$", "", candidate)
        if candidate and candidate not in names:
            aliases.append(candidate)
    # 用户历史输入把 Almaz 的小写 l 写成了大写 I，作为兼容搜索别名。
    if any(name.casefold() == "almaz33" for name in names):
        aliases.append("AImaz33")
    for name in names:
        if re.fullmatch(r".+\d+", name):
            aliases.append(re.sub(r"\d+$", "", name))
    return list(dict.fromkeys(a for a in aliases if a))


def parse_sgf(text: str, filename: str, encoding: str) -> ImportedGame:
    try:
        game = sgf.parse(text)
    except sgf.SGFError as exc:
        raise ImportError(f"SGF 解析失败：{exc}") from exc
    if not game.moves:
        raise ImportError("SGF 中没有主线着手")
    info = {key: value for key, value in game.info.items() if isinstance(value, str)}
    # 弈城导出的 PW/PB 可能是账号别名；显示名以 WID/BID 为准。
    black_name = info.get("BID") or info.get("PB") or "黑方"
    white_name = info.get("WID") or info.get("PW") or "白方"
    aliases = [info.get("PB", ""), info.get("PW", "")]
    aliases.extend(_filename_aliases(filename, (black_name, white_name)))
    aliases = list(dict.fromkeys(a for a in aliases if a not in ("", black_name, white_name)))
    komi = _float_komi(info.get("KM"))
    if komi is not None:
        info["KM"] = f"{komi:g}"
    info["PB"], info["PW"] = black_name, white_name
    normalized = _serialize(game, info)
    normalized_game = sgf.parse(normalized)
    return ImportedGame(
        game=normalized_game,
        sgf_text=normalized,
        original_format="sgf",
        encoding=encoding,
        platform=_platform_from(filename, info),
        black_name=black_name,
        white_name=white_name,
        black_rank=info.get("BR", ""),
        white_rank=info.get("WR", ""),
        aliases=aliases,
        event=info.get("EV", ""),
        date=info.get("DT", ""),
        result=info.get("RE", ""),
        komi=komi,
        rules=info.get("RU", ""),
        source_filename=filename,
    )


def _gib_value(text: str, key: str) -> str:
    match = re.search(rf"(?m)^\s*(?:\\\[)?{re.escape(key)}=(.*?)(?:\\\])?\s*$", text)
    return match.group(1).strip() if match else ""


def _split_gib_user(value: str) -> tuple[str, str]:
    match = re.match(r"\s*(.*?)\s*(?:\(([^()]*)\))?\s*$", value)
    return (match.group(1).strip(), (match.group(2) or "").strip()) if match else (value, "")


def parse_gib(text: str, filename: str, encoding: str) -> ImportedGame:
    white_name, white_rank = _split_gib_user(_gib_value(text, "GAMEWHITENAME"))
    black_name, black_rank = _split_gib_user(_gib_value(text, "GAMEBLACKNAME"))
    moves: list[sgf.Move] = []
    letters = "abcdefghijklmnopqrstuvwxyz"
    for match in re.finditer(r"(?m)^\s*STO\s+\d+\s+\d+\s+([12])\s+(\d+)\s+(\d+)", text):
        color_code, x_raw, y_raw = match.groups()
        x, y = int(x_raw), int(y_raw)
        if not (0 <= x < 19 and 0 <= y < 19):
            raise ImportError(f"GIB 第 {len(moves) + 1} 手坐标越界：({x},{y})")
        moves.append(sgf.Move("B" if color_code == "1" else "W", letters[x] + letters[y], len(moves) + 1))
    if not moves:
        raise ImportError("GIB 中没有可识别的 STO 着手记录")
    raw_result = _gib_value(text, "GAMERESULT")
    winner = "W" if "白" in raw_result else "B" if "黑" in raw_result else ""
    if "中盘" in raw_result or "投子" in raw_result:
        result = f"{winner}+R" if winner else raw_result.strip()
    else:
        points = re.search(r"(\d+(?:\.\d+)?)\s*目(半)?胜", raw_result)
        if winner and points:
            amount = float(points.group(1)) + (0.5 if points.group(2) else 0.0)
            result = f"{winner}+{amount:g}"
        else:
            result = re.sub(r"\s+", "", raw_result)
    date = _gib_value(text, "GAMEDATE").split(" ")[0]
    event = _gib_value(text, "GAMETITLE")
    game = sgf.Game(
        info={
            "GM": "1", "FF": "4", "CA": "UTF-8", "SZ": "19",
            "PB": black_name or "黑方", "PW": white_name or "白方",
            "BR": black_rank, "WR": white_rank, "RE": result,
            "DT": date, "EV": event, "PC": _gib_value(text, "GAMEPLACE"),
            "AP": "弈鉴-GIB导入器",
        },
        moves=moves,
    )
    normalized = _serialize(game, game.info)
    return ImportedGame(
        game=sgf.parse(normalized),
        sgf_text=normalized,
        original_format="gib",
        encoding=encoding,
        platform="弈城围棋",
        black_name=game.info["PB"],
        white_name=game.info["PW"],
        black_rank=black_rank,
        white_rank=white_rank,
        aliases=_filename_aliases(filename, (game.info["PB"], game.info["PW"])),
        event=event,
        date=date,
        result=result,
        komi=None,
        source_filename=filename,
    )


def import_bytes(data: bytes, filename: str = "未命名棋谱") -> ImportedGame:
    if len(data) > 20 * 1024 * 1024:
        raise ImportError("棋谱文件超过 20 MB，请先确认文件是否损坏")
    text, encoding = decode_bytes(data)
    kind = detect_format(text)
    return parse_sgf(text, filename, encoding) if kind == "sgf" else parse_gib(text, filename, encoding)
