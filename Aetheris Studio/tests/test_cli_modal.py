"""
Unit tests for Aetheris CLI modal helpers.
Verifies centered rect calculation, keyboard help formatting, and theme picker list generation.
"""

from aetheris_cli.render.modal import calculate_centered_rect, format_key_help_line, get_theme_picker_lines
from aetheris_cli.render.theme import get_theme


def test_calculate_centered_rect_bounds():
    bounds = calculate_centered_rect(70, 70, 80, 20, 100, 30)
    assert bounds.width <= 80
    assert bounds.height <= 20
    assert bounds.x >= 0
    assert bounds.y >= 0


def test_format_key_help_line():
    t = get_theme("tokyo-night")
    line = format_key_help_line("q", "quit", t)
    assert "q" in line
    assert "quit" in line


def test_get_theme_picker_lines():
    lines = get_theme_picker_lines("tokyo-night", selected_index=0)
    assert len(lines) >= 12
    assert "tokyo-night" in lines[3] or any("tokyo-night" in l for l in lines)
