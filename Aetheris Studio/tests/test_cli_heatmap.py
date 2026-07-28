"""
Unit tests for Aetheris CLI 2-D heatmap renderer.
Verifies color interpolation and heatmap row rendering.
"""

from aetheris_cli.render.heatmap import Heatmap, HeatmapRow, lerp3_t


def test_lerp3_t_bounds():
    stops = ("#000000", "#808080", "#ffffff")
    assert lerp3_t(stops, 0.0) == "#000000"
    assert lerp3_t(stops, 1.0) == "#ffffff"


def test_heatmap_row_rendering():
    row = HeatmapRow(label="temp", data=[25.0, 50.0, 75.0, 100.0], max_val=100.0)
    hm = Heatmap(rows=[row], label_width=5)
    out = hm.render_row_string(row, width=20)
    assert "temp" in out
