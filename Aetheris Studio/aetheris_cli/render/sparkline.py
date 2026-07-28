"""
Braille sparkline rendering module ported from ROCm CLI.
Maps numeric time series data into high-resolution braille graph characters (2 columns x 4 rows per character cell).
"""

from typing import List, Optional


def braille_char(left: int, right: int) -> str:
    code = 0
    if left & 0b0001:
        code |= 0x01
    if left & 0b0010:
        code |= 0x02
    if left & 0b0100:
        code |= 0x04
    if left & 0b1000:
        code |= 0x40

    if right & 0b0001:
        code |= 0x08
    if right & 0b0010:
        code |= 0x10
    if right & 0b0100:
        code |= 0x20
    if right & 0b1000:
        code |= 0x80

    return chr(0x2800 + code)


def lit_dots(value: Optional[int], max_val: int, total_dot_rows: int, row_top: int) -> int:
    if value is None:
        return 0

    max_v = max(max_val, 1)
    v = min(value, max_v)
    lit = round((v / max_v) * total_dot_rows)
    first_lit_row = max(0, total_dot_rows - lit)

    mask = 0
    for i in range(4):
        dot_row = row_top + i
        if first_lit_row <= dot_row < total_dot_rows:
            mask |= 1 << i

    return mask


def render_braille_sparkline(data: List[int], width: int = 20, max_val: Optional[int] = None) -> str:
    if not data or width <= 0:
        return " " * width

    actual_max = max_val if (max_val is not None and max_val > 0) else max(max(data, default=1), 1)
    total_dot_rows = 4

    bins = width * 2
    if len(data) > bins:
        slice_data = data[-bins:]
    else:
        slice_data = data

    result_chars = []
    for cx in range(width):
        left_val = slice_data[cx * 2] if (cx * 2) < len(slice_data) else None
        right_val = slice_data[cx * 2 + 1] if (cx * 2 + 1) < len(slice_data) else None

        l_mask = lit_dots(left_val, actual_max, total_dot_rows, 0)
        r_mask = lit_dots(right_val, actual_max, total_dot_rows, 0)

        result_chars.append(braille_char(l_mask, r_mask))

    return "".join(result_chars)
