"""
Centered popup geometry helpers, modal frame layout, theme picker, and keyboard help overlay ported from ROCm CLI.
Calculates centered rect dimensions and formats help, options, and theme selection overlays.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from aetheris_cli.render.theme import Theme, get_theme, list_theme_names


@dataclass
class RectBounds:
    x: int
    y: int
    width: int
    height: int


def calculate_centered_rect(
    pct_x: int,
    pct_y: int,
    max_w: int,
    max_h: int,
    terminal_width: int = 100,
    terminal_height: int = 30,
) -> RectBounds:
    h_pct = max(5, min(max_h, (terminal_height * pct_y) // 100))
    v_pad = max(0, (terminal_height - h_pct) // 2)

    w_pct = max(20, min(max_w, (terminal_width * pct_x) // 100))
    h_pad = max(0, (terminal_width - w_pct) // 2)

    return RectBounds(x=h_pad, y=v_pad, width=w_pct, height=h_pct)


def format_key_help_line(key: str, description: str, theme: Theme) -> str:
    return f"  [{theme.accent}]{key:<18}[/{theme.accent}] [{theme.fg}]{description}[/{theme.fg}]"


def get_global_keyboard_help_lines(theme_name: str = "tokyo-night") -> List[str]:
    t = get_theme(theme_name)
    lines = [
        f"[{t.accent}]=== Aetheris CLI Keyboard Shortcuts ===[/{t.accent}]",
        format_key_help_line("q / Ctrl+C", "Quit session", t),
        format_key_help_line("?", "Toggle help overlay", t),
        format_key_help_line("t", "Theme picker", t),
        format_key_help_line("Tab / Shift-Tab", "Navigate options / focus", t),
        format_key_help_line("y / n", "Approve / Deny confirmation gate", t),
        format_key_help_line("Enter", "Confirm highlighted action", t),
    ]
    return lines


def get_theme_picker_lines(current_theme_name: str, selected_index: int = 0) -> List[str]:
    names = list_theme_names()
    lines = []
    for idx, name in enumerate(names):
        marker = "●" if name == current_theme_name else " "
        pointer = "▸" if idx == selected_index else " "
        theme = get_theme(name)
        swatch = f"[on {theme.bg}]  [/on {theme.bg}][on {theme.accent}]  [/on {theme.accent}][on {theme.ok}]  [/on {theme.ok}][on {theme.warn}]  [/on {theme.warn}][on {theme.err}]  [/on {theme.err}]"
        lines.append(f"{pointer} {marker} {swatch} {name}")
    return lines
