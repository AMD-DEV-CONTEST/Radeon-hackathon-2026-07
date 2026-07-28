"""
Braille spinner frames and progress percentage parsing logic ported from ROCm CLI.
Provides frame generation functions using braille glyphs and regex/string parsing for percentage tokens in long-running job output lines.
"""

import re
from typing import Optional

BRAILLE_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


def spinner_frame(tick: int) -> str:
    return BRAILLE_FRAMES[tick % len(BRAILLE_FRAMES)]


def parse_progress_pct(line: str) -> Optional[int]:
    if not line or "%" not in line:
        return None

    pct_idx = line.rfind("%")
    sub = line[:pct_idx]

    num_chars = []
    for c in reversed(sub):
        if c.isdigit() or c == ".":
            num_chars.append(c)
        else:
            break

    if not num_chars:
        return None

    num_str = "".join(reversed(num_chars))
    try:
        val = float(num_str)
        if 0.0 <= val <= 100.0:
            return round(val)
        return None
    except ValueError:
        return None
