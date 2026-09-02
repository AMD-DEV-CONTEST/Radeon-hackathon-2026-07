"""A repair prompt must fit in the model's context, or the repair never happens.

Measured 2026-08-01 on SWE-bench mwaskom__seaborn-2848: fix-target inference selected
`seaborn/cm.py` -- ~60 KB, overwhelmingly literal colormap tables -- and the prompt reached
67,530 characters against an 8,192-token server. All six samples died. The defect being
hunted was a few lines; the prompt was 1,500 lines of RGB tuples.

Project Cloak already paid for this lesson once and ended at `_REGION_THRESHOLD = 0`,
always region mode. Same rule, applied to repair.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from determinex_repair import _source_for_prompt  # noqa: E402


def _big(tmp_path: Path, n_lines: int = 1500) -> Path:
    p = tmp_path / "cm.py"
    # Zero-padded so `_cmap_0200` is an exact, unambiguous token. An unpadded `_cmap_200`
    # made the "absent" assertions below pass VACUOUSLY -- they searched for a string the
    # fixture never wrote, which is a green tick for a check that established nothing.
    body = "\n".join(f"_cmap_{i:04d} = (0.{i:04d}, 0.{i:04d}, 0.{i:04d})" for i in range(n_lines))
    p.write_text(body + "\ndef lookup(name):\n    return _cmap_0\n", encoding="utf-8")
    return p


def test_a_small_file_is_still_sent_whole(tmp_path: Path):
    """Windowing a file that already fits would only make SEARCH anchoring harder."""
    p = tmp_path / "small.py"
    p.write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    out = _source_for_prompt(p, "small.py", 'File "small.py", line 2, in add')
    assert out == "def add(a, b):\n    return a - b\n"
    assert "omitted" not in out


def test_a_large_file_is_windowed_around_the_lines_the_failure_names(tmp_path: Path):
    p = _big(tmp_path)
    oracle = 'File "cm.py", line 1200, in lookup\n    return _cmap_0\nNameError'
    out = _source_for_prompt(p, "seaborn/cm.py", oracle, budget=24_000)

    assert len(out) < 24_000, "the whole point is that it fits"
    assert "_cmap_1200" in out, "the implicated region must be present"
    assert "_cmap_0001 " not in out, "a distant region should have been dropped"
    assert "omitted" in out, "elision must be visible to the model"


def test_the_window_carries_real_line_numbers(tmp_path: Path):
    """Without them the model cannot correlate the traceback with what it is reading."""
    p = _big(tmp_path)
    out = _source_for_prompt(
        p, "seaborn/cm.py", 'File "cm.py", line 1200, in lookup', budget=24_000
    )
    assert "  1200| " in out


def test_the_model_is_told_not_to_anchor_across_an_omission(tmp_path: Path):
    """A SEARCH block spanning elided text matches nothing, and the failure reads as the
    model being unable to produce a valid edit."""
    p = _big(tmp_path)
    out = _source_for_prompt(
        p, "seaborn/cm.py", 'File "cm.py", line 1200, in lookup', budget=24_000
    )
    assert "never write a SEARCH anchor that spans an omission" in out


def test_a_large_file_with_no_named_line_still_fits_and_says_so(tmp_path: Path):
    """Degrading to the head is a guess, and it must be labelled as one rather than
    presented as the file."""
    p = _big(tmp_path)
    out = _source_for_prompt(p, "seaborn/cm.py", "no traceback here", budget=24_000)
    assert len(out) < 24_000
    assert "did not name a line in this file" in out
    assert "omitted" in out


def test_an_unreadable_target_yields_empty_rather_than_raising(tmp_path: Path):
    out = _source_for_prompt(tmp_path / "gone.py", "gone.py", "")
    assert out == ""


def test_multiple_implicated_lines_are_all_included(tmp_path: Path):
    p = _big(tmp_path)
    oracle = 'File "cm.py", line 200, in a\nFile "cm.py", line 1400, in b\n'
    out = _source_for_prompt(p, "seaborn/cm.py", oracle, budget=24_000)
    assert "_cmap_0200" in out and "_cmap_1400" in out
    assert len(out) < 24_000


def test_frames_from_other_files_do_not_steer_this_files_window(tmp_path: Path):
    """A traceback names several files. Only lines attributed to THIS one are regions."""
    p = _big(tmp_path)
    oracle = 'File "other.py", line 200, in a\nFile "cm.py", line 1400, in b\n'
    out = _source_for_prompt(p, "seaborn/cm.py", oracle, budget=24_000)
    assert "_cmap_1400" in out
    assert "_cmap_0200 " not in out
