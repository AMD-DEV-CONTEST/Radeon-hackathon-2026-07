# -*- coding: utf-8 -*-
"""SGF 解析模块 —— 弈鉴 GoMentor

只做两件事：
1. 解析对局元信息（对局者、结果、规则、贴目等）
2. 抽取主变化着手序列（黑白交替，含 pass）

设计约定：
- 坐标使用 SGF 字母格式原样传出（如 "pd"），由 goboard 负责转数字坐标
- 分支变化只取主线（第一分支）；复盘工作台 W2 再考虑变化树
"""

from dataclasses import dataclass, field


@dataclass
class Move:
    color: str          # "B" / "W"
    coord: str          # SGF 坐标，如 "pd"；pass 为 ""
    number: int         # 手数，从 1 开始

    @property
    def is_pass(self) -> bool:
        # SZ<=19 时 "tt" 与空串都是 pass（FF[3] 约定）
        return self.coord in ("", "tt")


@dataclass
class Game:
    info: dict = field(default_factory=dict)   # 根节点属性，如 PB/PW/RE/KM/SZ
    moves: list = field(default_factory=list)  # list[Move]

    @property
    def size(self) -> int:
        try:
            return int(self.info.get("SZ", "19"))
        except ValueError:
            return 19


class SGFError(ValueError):
    pass


def _tokenize(text: str):
    """把 SGF 文本切成 token 流：'(' ')' ';' 或 (key, value) 属性对。"""
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch in "();":
            yield ch
            i += 1
        elif ch.isspace():
            i += 1
        elif ch.isalpha():
            # 属性名：连续大写字母（兼容小写扩展写法）
            j = i
            while j < n and text[j].isalpha():
                j += 1
            key = "".join(c for c in text[i:j] if c.isupper()) or text[i:j].upper()
            i = j
            # 一个属性可带多个 [] 值
            values = []
            while i < n:
                while i < n and text[i].isspace():
                    i += 1
                if i >= n or text[i] != "[":
                    break
                i += 1
                buf = []
                while i < n and text[i] != "]":
                    if text[i] == "\\" and i + 1 < n:
                        buf.append(text[i + 1])
                        i += 2
                    else:
                        buf.append(text[i])
                        i += 1
                if i >= n:
                    raise SGFError("属性值未闭合：缺少 ']'")
                i += 1  # 跳过 ']'
                values.append("".join(buf))
            if not values:
                raise SGFError(f"属性 {key} 缺少值")
            yield (key, values)
        else:
            raise SGFError(f"无法识别的字符：{ch!r}（位置 {i}）")


def parse(text: str) -> Game:
    """解析 SGF 文本，返回 Game。只跟随主线（每个分叉取第一分支）。"""
    text = text.strip()
    if not text.startswith("("):
        raise SGFError("不是合法的 SGF：应以 '(' 开头")

    game = Game()
    depth = 0
    in_main = True          # 是否仍在主线上
    skip_until_depth = None  # 进入旁支后跳过，直到深度回落
    seen_first_branch = {}   # depth -> 是否已走过该层第一分支
    node_count = 0

    for tok in _tokenize(text):
        if tok == "(":
            depth += 1
            if skip_until_depth is None:
                if seen_first_branch.get(depth):
                    # 同层第二个分支 → 旁支，整段跳过
                    skip_until_depth = depth - 1
                else:
                    seen_first_branch[depth] = True
            continue
        if tok == ")":
            depth -= 1
            # 清理更深层的分支记账，使兄弟分支判定正确
            for d in list(seen_first_branch):
                if d > depth + 1:
                    del seen_first_branch[d]
            if skip_until_depth is not None and depth <= skip_until_depth:
                skip_until_depth = None
            continue
        if skip_until_depth is not None:
            continue
        if tok == ";":
            node_count += 1
            continue
        key, values = tok
        if key in ("B", "W"):
            game.moves.append(Move(color=key, coord=values[0], number=len(game.moves) + 1))
        elif node_count <= 1 and key not in game.info:
            game.info[key] = values[0] if len(values) == 1 else values

    if depth != 0:
        raise SGFError("括号不匹配")
    if node_count == 0:
        raise SGFError("SGF 中没有节点")
    return game


def parse_file(path: str) -> Game:
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return parse(f.read())
