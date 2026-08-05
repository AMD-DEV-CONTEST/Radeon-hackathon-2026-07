"""Tests for determinex_reimpl_corpus.py's technique-recipe library (2026-07-16 expansion).

Covers: (1) the json/io recipe rewrite removing stale Python-only code samples, (2) the 7 new
recipes (diff/csv/regex_glob/ansi/checksum/http/git_plumbing), (3) recipes_for()'s content-based
domain detection (name + observed-output signals, not family-name classification -- audited to
only cover 52/200 real tasks), and (4) the explicit _RECIPE_PRIORITY ordering that replaced the
original accidental insert(0)-order-determines-priority behavior.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import determinex_reimpl_corpus as CORPUS  # noqa: E402


class _FakeProbe:
    def __init__(self, name: str = ""):
        self.name = name


class _FakeObs:
    def __init__(self, stdout: str = "", probe_name: str = ""):
        self.stdout = stdout
        self.probe = _FakeProbe(probe_name)


# ---------- json/io recipe content: no stale Python-only code ----------


def test_json_recipe_has_no_bare_python_code_fence():
    assert "```python" not in CORPUS._RECIPES["json"]
    assert "class Raw(str)" not in CORPUS._RECIPES["json"]


def test_json_recipe_covers_all_four_native_languages():
    text = CORPUS._RECIPES["json"]
    assert "Go" in text and "UseNumber" in text
    assert "Rust/C/C++" in text or ("Rust" in text and "C/C++" in text)


def test_io_recipe_has_no_bare_python_code_fence():
    assert "```python" not in CORPUS._RECIPES["io"]


def test_io_recipe_covers_all_native_languages():
    text = CORPUS._RECIPES["io"]
    for lang in ("Rust", "Go", "C/C++"):
        assert lang in text


def test_table_and_tui_recipes_unchanged_still_present():
    assert "COLUMN WIDTH" in CORPUS._RECIPES["table"]
    assert "ncurses" in CORPUS._RECIPES["tui"]


# ---------- new recipes exist and carry real content ----------


def test_all_new_recipes_present():
    for domain in ("diff", "csv", "regex_glob", "ansi", "checksum", "http", "git_plumbing"):
        assert domain in CORPUS._RECIPES
        assert len(CORPUS._RECIPES[domain]) > 200  # not a stub


def test_diff_recipe_mentions_hunk_format():
    assert "@@" in CORPUS._RECIPES["diff"]
    assert (
        "LCS" in CORPUS._RECIPES["diff"] or "longest-common-subsequence" in CORPUS._RECIPES["diff"]
    )


def test_csv_recipe_mentions_rfc4180_quoting_rule():
    text = CORPUS._RECIPES["csv"]
    assert "doubling" in text.lower() or "doubled" in text.lower()


def test_regex_glob_recipe_distinguishes_glob_from_regex():
    text = CORPUS._RECIPES["regex_glob"]
    assert "glob" in text.lower() and "regex" in text.lower()


def test_ansi_recipe_mentions_no_color_env_convention():
    assert "NO_COLOR" in CORPUS._RECIPES["ansi"]


def test_checksum_recipe_warns_algorithms_are_not_interchangeable():
    assert "NOT interchangeable" in CORPUS._RECIPES["checksum"]


def test_http_recipe_covers_go_stdlib_vs_raw_socket_asymmetry():
    text = CORPUS._RECIPES["http"]
    assert "net/http" in text
    assert "TCP socket" in text


def test_git_plumbing_recipe_recommends_shelling_out_not_reimplementing():
    text = CORPUS._RECIPES["git_plumbing"]
    assert "shell out" in text.lower() or "subprocess" in text.lower()


# ---------- recipes_for(): baseline ----------


def test_recipes_for_baseline_no_match_returns_only_io():
    result = CORPUS.recipes_for("totally_unclassifiable_tool", [])
    assert result == CORPUS._RECIPES["io"]


# ---------- recipes_for(): name-based detection ----------


def test_recipes_for_detects_diff_by_name():
    result = CORPUS.recipes_for("diffr", [])
    assert "hunk grouping" in result


def test_recipes_for_detects_csv_by_name():
    result = CORPUS.recipes_for("csview", [])
    assert "CSV/TSV" in result


def test_recipes_for_detects_regex_glob_by_name():
    result = CORPUS.recipes_for("igrep", [])
    assert "glob/pattern matching" in result


def test_recipes_for_detects_http_by_name():
    result = CORPUS.recipes_for("curlie", [])
    assert "HTTP request" in result


def test_recipes_for_detects_git_plumbing_by_name():
    result = CORPUS.recipes_for("git-trim", [])
    assert "git-wrapper" in result


def test_recipes_for_detects_checksum_by_name():
    result = CORPUS.recipes_for("md5sum-clone", [])
    assert "hash/checksum" in result


# ---------- recipes_for(): content-based detection ----------


def test_recipes_for_detects_json_from_observed_content():
    obs = [_FakeObs(stdout='{"a": 1, "b": 2}')]
    result = CORPUS.recipes_for("someunrelatedname", obs)
    assert "preserve EXACT number text" in result


def test_recipes_for_detects_table_from_box_drawing_glyphs():
    obs = [_FakeObs(stdout="┌──┬──┐\n│ a│ b│\n└──┴──┘")]
    result = CORPUS.recipes_for("someunrelatedname", obs)
    assert "box-drawing table layout" in result


def test_recipes_for_detects_tui_from_tui_snapshot_probe():
    obs = [_FakeObs(stdout="\x1b[42mX\x1b[0m", probe_name="tui-snapshot-1")]
    result = CORPUS.recipes_for("someunrelatedname", obs)
    assert "ncurses/curses TUI tools" in result


def test_recipes_for_detects_diff_from_hunk_header_in_output():
    obs = [_FakeObs(stdout="@@ -1,3 +1,4 @@\n-old\n+new\n")]
    result = CORPUS.recipes_for("someunrelatedname", obs)
    assert "hunk grouping" in result


def test_recipes_for_detects_csv_from_quoted_comma_dense_output():
    obs = [_FakeObs(stdout='a,b,"c,d",e\n1,2,"3,4",5\n')]
    result = CORPUS.recipes_for("someunrelatedname", obs)
    assert "CSV/TSV" in result


def test_recipes_for_detects_ansi_from_raw_escape_without_tui_snapshot_probe():
    """A plain colored-output tool (not a TUI) should still get the ansi recipe from a bare
    \\x1b[ signal in regular stdout, distinct from the tui-snapshot-specific detection."""
    obs = [_FakeObs(stdout="\x1b[32mgreen text\x1b[0m", probe_name="regular-probe")]
    result = CORPUS.recipes_for("someunrelatedname", obs)
    assert "ANSI color/style codes" in result


def test_recipes_for_detects_http_from_status_line_in_output():
    obs = [_FakeObs(stdout="HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n")]
    result = CORPUS.recipes_for("someunrelatedname", obs)
    assert "HTTP request" in result


# ---------- recipes_for(): priority ordering under multiple matches ----------


def test_recipes_for_tui_outranks_table_and_json_when_all_match():
    """Matches the pre-existing behavior (tui was always inserted last = highest priority)."""
    obs = [_FakeObs(stdout='{"a": 1} ┌──┐ \x1b[42mX\x1b[0m', probe_name="tui-snapshot-1")]
    result = CORPUS.recipes_for("someunrelatedname", obs)
    tui_idx = result.find("ncurses/curses TUI tools")
    table_idx = result.find("box-drawing table layout")
    json_idx = result.find("preserve EXACT number text")
    assert tui_idx != -1 and table_idx != -1 and json_idx != -1
    assert tui_idx < table_idx < json_idx  # tui first (highest priority), json last


def test_recipes_for_git_plumbing_outranks_regex_glob_when_both_match():
    """git_plumbing is a narrow/high-confidence name signal -- should outrank the broader
    regex_glob name signal per _RECIPE_PRIORITY."""
    result = CORPUS.recipes_for("git-grep-wrapper", [])
    git_idx = result.find("git-wrapper")
    regex_idx = result.find("glob/pattern matching")
    assert git_idx != -1 and regex_idx != -1
    assert git_idx < regex_idx


def test_recipe_priority_list_matches_actual_recipes_dict_keys():
    """Every _RECIPES key must appear in _RECIPE_PRIORITY exactly once -- an unlisted recipe
    would silently never be selected by recipes_for()'s `ordered` filter."""
    assert set(CORPUS._RECIPE_PRIORITY) == set(CORPUS._RECIPES.keys())
    assert len(CORPUS._RECIPE_PRIORITY) == len(set(CORPUS._RECIPE_PRIORITY))


# ---------- render_prompt_block(): full coach block still composes correctly ----------


def test_render_prompt_block_still_includes_recipe_and_pitfalls():
    block = CORPUS.render_prompt_block("diffr", observations=[])
    assert "hunk grouping" in block
    assert "Reimplementation pitfalls" in block
