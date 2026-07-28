"""
Unit tests for Aetheris CLI braille spinner and progress parsing module.
Verifies frame cycling sequence and percentage extraction from progress lines.
"""

from aetheris_cli.render.spinner import parse_progress_pct, spinner_frame


def test_spinner_frame_cycling():
    assert spinner_frame(0) == "⠋"
    assert spinner_frame(1) == "⠙"
    assert spinner_frame(10) == spinner_frame(0)
    assert spinner_frame(21) == spinner_frame(1)


def test_parse_progress_pct_valid():
    assert parse_progress_pct("Downloading model.safetensors:  45%|████▌     | 2.3G/5.2G") == 45
    assert parse_progress_pct("100%|██████████| done") == 100
    assert parse_progress_pct("progress: 0%") == 0
    assert parse_progress_pct("45.6% complete") == 46


def test_parse_progress_pct_invalid():
    assert parse_progress_pct("no percent here") is None
    assert parse_progress_pct("just a % sign") is None
    assert parse_progress_pct("cpu at 250% load") is None
