"""
tests/test_swebench_patch_smoke.py — Smoke tests for swe_agent.patch.

The SEARCH/REPLACE patch engine is the load-bearing piece of the SWE-bench
solve loop — every Builder output goes through this parser + applicator
cascade. The 2026-05-05 hardening sprint fixed 8 bugs here (CRLF normalization,
paren-stripped anchors, line-number prefix stripping, etc.). These tests
keep those fixes wedged in place.
"""

from __future__ import annotations

import pytest
from swe_agent.patch import (
    _apply_search_replace_blocks,
    _normalize_for_match,
    _parse_search_replace_blocks,
)


def test_normalize_for_match_strips_crlf_and_trailing_ws():
    s = "line one  \r\nline two\t\r\nline three\r"
    out = _normalize_for_match(s)
    assert "\r" not in out
    assert out == "line one\nline two\nline three\n"


def test_parse_strict_block():
    raw = (
        "Some preamble from the model.\n"
        "<<<SEARCH\n"
        "old line\n"
        "===\n"
        "new line\n"
        ">>>REPLACE\n"
        "Trailing chatter.\n"
    )
    blocks = _parse_search_replace_blocks(raw)
    assert blocks == [("old line", "new line")]


def test_parse_lenient_handles_marker_decoration():
    """DeepSeek and Anthropic sometimes append a filename or extra separators."""
    raw = "<<<SEARCH: app.py\nx = 1\n====\nx = 2\n>>>REPLACE done\n"
    blocks = _parse_search_replace_blocks(raw)
    assert blocks == [("x = 1", "x = 2")]


def test_parse_rejects_no_op_blocks():
    raw = "<<<SEARCH\nsame line\n===\nsame line\n>>>REPLACE\n"
    assert _parse_search_replace_blocks(raw) == []


def test_apply_exact_match():
    source = "def foo():\n    return 1\n"
    blocks = [("    return 1", "    return 2")]
    result, failed = _apply_search_replace_blocks(source, blocks)
    assert failed == []
    assert result == "def foo():\n    return 2\n"


def test_apply_crlf_tolerant_match():
    """Source uses LF, model output uses CRLF — pass 2 should still match."""
    source = "def foo():\n    return 1\n"
    blocks = [("    return 1\r", "    return 2")]
    result, failed = _apply_search_replace_blocks(source, blocks)
    assert failed == [] or result != source, "CRLF-tolerant match should succeed"


def test_apply_strips_line_number_prefixes():
    """Models sometimes copy `42 | ` prefixes from numbered edit windows."""
    source = "def foo():\n    return 1\n"
    raw = (
        "<<<SEARCH\n"
        "  10 | def foo():\n"
        "  11 |     return 1\n"
        "===\n"
        "  10 | def foo():\n"
        "  11 |     return 2\n"
        ">>>REPLACE\n"
    )
    blocks = _parse_search_replace_blocks(raw)
    assert blocks, "blocks should parse after prefix strip"
    result, failed = _apply_search_replace_blocks(source, blocks)
    assert failed == [], f"expected match after prefix strip, got failed={failed}"
    assert "return 2" in result


def test_apply_reports_failed_search():
    source = "def foo():\n    return 1\n"
    blocks = [("def NEVER():", "def foo():")]
    result, failed = _apply_search_replace_blocks(source, blocks)
    assert len(failed) == 1
    assert result == source  # source unchanged when search misses


def test_make_targeted_patch_creates_unified_diff(monkeypatch):
    """The diff builder must produce a clean git-style unified diff."""
    # Import lazily — determinex_swebench_agent has heavy top-level imports
    # we can mock around. Skip if not importable.
    try:
        from determinex_swebench_agent import make_targeted_patch
    except Exception as e:
        pytest.skip(f"determinex_swebench_agent not importable in this env: {e}")

    original = "x = 1\ny = 2\n"
    fixed = "x = 1\ny = 99\n"
    patch = make_targeted_patch("src/app.py", original, fixed)
    assert patch.startswith("diff --git a/src/app.py b/src/app.py")
    assert "--- a/src/app.py" in patch
    assert "+++ b/src/app.py" in patch
    assert "-y = 2" in patch
    assert "+y = 99" in patch


def test_make_targeted_patch_empty_on_no_change():
    try:
        from determinex_swebench_agent import make_targeted_patch
    except Exception as e:
        pytest.skip(f"determinex_swebench_agent not importable in this env: {e}")
    same = "x = 1\ny = 2\n"
    assert make_targeted_patch("src/app.py", same, same) == ""


def test_empty_search_block_never_corrupts_an_existing_file():
    """An empty SEARCH block must not splice text into a non-empty file.

    `"" in anything` is always True, so an empty SEARCH used to fall through
    to the exact-match pass and do result.replace("", replace, 1) -- inserting
    at offset 0 with no separator. Observed live: a local-agent turn wrote
    `return a - bdef add(a,b):` (a syntax error) straight to disk. Per the
    prompt contract an empty SEARCH means "create this new file", so it is
    only legal against empty content; otherwise it must fail closed.
    """
    from swe_agent.patch import _apply_search_replace_blocks

    src = "def add(a,b):\n    return a+b\n"
    out, failed = _apply_search_replace_blocks(src, [("", "def sub(a,b):\n    return a-b\n")])
    assert out == src, "empty SEARCH must not modify an existing file"
    assert failed, "empty SEARCH against a non-empty file must be reported as failed"


def test_empty_search_block_still_creates_a_new_file():
    from swe_agent.patch import _apply_search_replace_blocks

    out, failed = _apply_search_replace_blocks("", [("", "hello\n")])
    assert out == "hello\n"
    assert not failed
