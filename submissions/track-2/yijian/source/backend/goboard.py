# -*- coding: utf-8 -*-
"""棋盘与吃子引擎 —— 弈鉴 GoMentor

规则实现：提子、禁自杀、简单劫（simple ko）。
与宣传页 JS 引擎同一套算法（气的洪泛搜索），可互为交叉验证。
"""

EMPTY, BLACK, WHITE = 0, 1, 2
_COL_LETTERS = "ABCDEFGHJKLMNOPQRST"  # 围棋坐标无 I


class IllegalMove(ValueError):
    pass


def sgf_to_xy(coord: str):
    """SGF 字母坐标 → (col, row)，均为 0 起始，row 0 为顶行。"""
    if len(coord) != 2:
        raise ValueError(f"坏坐标：{coord!r}")
    return ord(coord[0]) - 97, ord(coord[1]) - 97


def gtp_name(coord: str, size: int = 19) -> str:
    """SGF 坐标 → 人类可读坐标（如 'ki' → 'L11'）。"""
    c, r = sgf_to_xy(coord)
    return f"{_COL_LETTERS[c]}{size - r}"


class Board:
    def __init__(self, size: int = 19):
        self.size = size
        self.grid = [EMPTY] * (size * size)
        self.captured = {BLACK: 0, WHITE: 0}  # 各方被提掉的子数
        self.ko = None                        # 简单劫禁着点 (c, r)
        self.move_count = 0

    def idx(self, c, r):
        return r * self.size + c

    def get(self, c, r):
        return self.grid[self.idx(c, r)]

    def neighbors(self, c, r):
        if c > 0:
            yield c - 1, r
        if c < self.size - 1:
            yield c + 1, r
        if r > 0:
            yield c, r - 1
        if r < self.size - 1:
            yield c, r + 1

    def group_and_liberties(self, c, r):
        """返回 (组内点列表, 气点集合)。"""
        color = self.get(c, r)
        assert color != EMPTY
        stack, seen, group, libs = [(c, r)], {(c, r)}, [], set()
        while stack:
            x, y = stack.pop()
            group.append((x, y))
            for nx, ny in self.neighbors(x, y):
                v = self.get(nx, ny)
                if v == EMPTY:
                    libs.add((nx, ny))
                elif v == color and (nx, ny) not in seen:
                    seen.add((nx, ny))
                    stack.append((nx, ny))
        return group, libs

    def play(self, color: int, coord: str):
        """落一手（SGF 坐标；空串/'tt' 为 pass）。非法手抛 IllegalMove。"""
        if coord in ("", "tt"):
            self.ko = None
            self.move_count += 1
            return []

        c, r = sgf_to_xy(coord)
        if not (0 <= c < self.size and 0 <= r < self.size):
            raise IllegalMove(f"出界：{coord}")
        if self.get(c, r) != EMPTY:
            raise IllegalMove(f"落点非空：{gtp_name(coord, self.size)}")
        if self.ko == (c, r):
            raise IllegalMove(f"违反劫争禁着：{gtp_name(coord, self.size)}")

        enemy = WHITE if color == BLACK else BLACK
        self.grid[self.idx(c, r)] = color

        # 先提对方无气之组
        captured_pts = []
        for nc, nr in self.neighbors(c, r):
            if self.get(nc, nr) == enemy:
                group, libs = self.group_and_liberties(nc, nr)
                if not libs:
                    for gx, gy in group:
                        self.grid[self.idx(gx, gy)] = EMPTY
                    captured_pts.extend(group)
        if captured_pts:
            self.captured[enemy] += len(captured_pts)

        # 再查自身：无气即自杀，非法
        _, own_libs = self.group_and_liberties(c, r)
        if not own_libs:
            self.grid[self.idx(c, r)] = EMPTY
            raise IllegalMove(f"自杀手：{gtp_name(coord, self.size)}")

        # 简单劫：恰提一子、己方新子恰为单子单气 → 对方不可立即回提
        self.ko = None
        if len(captured_pts) == 1:
            group, libs = self.group_and_liberties(c, r)
            if len(group) == 1 and len(libs) == 1:
                self.ko = captured_pts[0]

        self.move_count += 1
        return captured_pts

    def stones(self):
        """当前盘面子数 {BLACK: n, WHITE: n}。"""
        out = {BLACK: 0, WHITE: 0}
        for v in self.grid:
            if v:
                out[v] += 1
        return out


def replay(game, upto: int = None):
    """重放 sgf.Game 主线，返回 (Board, 每手快照列表)。

    快照列表 states[i] 为第 i 手后的盘面 bytes（i=0 是空盘），供前端/分析层索引。
    """
    board = Board(game.size)
    states = [bytes(board.grid)]
    moves = game.moves if upto is None else game.moves[:upto]
    for mv in moves:
        color = BLACK if mv.color == "B" else WHITE
        board.play(color, "" if mv.is_pass else mv.coord)
        states.append(bytes(board.grid))
    return board, states
