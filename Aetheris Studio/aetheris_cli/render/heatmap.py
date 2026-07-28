"""
2-D Heatmap widget renderer ported from ROCm CLI.
Renders metric-by-time matrices (such as per-GPU VRAM%, temperature, or latency history) using 3-stop color interpolation.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Tuple


def hex_color_from_rgb(r: int, g: int, b: int) -> str:
    return f"#{r:02x}{g:02x}{b:02x}"


def parse_hex_color(c: str) -> Tuple[int, int, int]:
    cleaned = c.lstrip("#")
    if len(cleaned) == 6:
        return int(cleaned[0:2], 16), int(cleaned[2:4], 16), int(cleaned[4:6], 16)
    return 128, 128, 128


def lerp_color(c1: Tuple[int, int, int], c2: Tuple[int, int, int], t: float) -> Tuple[int, int, int]:
    t_clamped = max(0.0, min(1.0, t))
    r = round(c1[0] + (c2[0] - c1[0]) * t_clamped)
    g = round(c1[1] + (c2[1] - c1[1]) * t_clamped)
    b = round(c1[2] + (c2[2] - c1[2]) * t_clamped)
    return r, g, b


def lerp3_t(stops: Tuple[str, str, str], t: float) -> str:
    t_clamped = max(0.0, min(1.0, t))
    c0 = parse_hex_color(stops[0])
    c1 = parse_hex_color(stops[1])
    c2 = parse_hex_color(stops[2])

    if t_clamped <= 0.5:
        sub_t = t_clamped * 2.0
        r, g, b = lerp_color(c0, c1, sub_t)
    else:
        sub_t = (t_clamped - 0.5) * 2.0
        r, g, b = lerp_color(c1, c2, sub_t)

    return hex_color_from_rgb(r, g, b)


@dataclass
class HeatmapRow:
    label: str
    data: List[float]
    max_val: float = 100.0
    stops: Optional[Tuple[str, str, str]] = None


class Heatmap:
    def __init__(
        self,
        rows: List[HeatmapRow],
        stops: Tuple[str, str, str] = ("#1aa01a", "#f59e0b", "#ed1c24"),
        label_width: Optional[int] = None,
    ):
        self.rows = rows
        self.stops = stops
        if label_width is None:
            max_l = max((len(r.label) for r in rows), default=0) + 1
            self.label_width = min(max_l, 12)
        else:
            self.label_width = label_width

    def render_row_string(self, row: HeatmapRow, width: int = 40) -> str:
        label_w = min(self.label_width, width)
        data_w = max(0, width - label_w)

        label_fmt = f"{row.label:<{label_w}}"[:label_w]

        if data_w <= 0:
            return label_fmt

        visible = data_w
        if len(row.data) > visible:
            slice_data = row.data[-visible:]
        else:
            slice_data = row.data

        row_stops = row.stops or self.stops
        row_max = max(row.max_val, 1e-6)

        data_chars = []
        for v in slice_data:
            if v > 0.0:
                t = max(0.0, min(1.0, v / row_max))
                color_hex = lerp3_t(row_stops, t)
                data_chars.append(f"[on {color_hex}] [/on {color_hex}]")
            else:
                data_chars.append(" ")

        padding = " " * max(0, data_w - len(slice_data))
        return label_fmt + "".join(data_chars) + padding
