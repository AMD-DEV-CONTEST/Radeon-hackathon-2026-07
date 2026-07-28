"""
Unit tests for Aetheris CLI braille sparkline renderer.
Verifies Unicode braille character composition and multi-sample graph rendering.
"""

from aetheris_cli.render.sparkline import braille_char, lit_dots, render_braille_sparkline


def test_empty_is_blank_braille():
    assert braille_char(0, 0) == "\u2800"


def test_all_dots_is_full_braille_block():
    assert braille_char(0b1111, 0b1111) == "⣿"


def test_lit_dots_max():
    mask = lit_dots(100, 100, 4, 0)
    assert mask == 0b1111


def test_lit_dots_zero():
    mask = lit_dots(0, 100, 4, 0)
    assert mask == 0


def test_render_braille_sparkline_output():
    data = [0, 50, 100, 100]
    out = render_braille_sparkline(data, width=2, max_val=100)
    assert len(out) == 2
    assert out[0] != " "
