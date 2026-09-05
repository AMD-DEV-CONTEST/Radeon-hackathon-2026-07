"""T4 citation validator unit tests (blueprint ARCHITECT_BLUEPRINT.md §3.3).

The validator is the guard for the "evidence-based answers" selling point: a
27B Q4 model will happily invent `file#L42-L58` ranges. These tests pin down
the three validation layers (syntax / file / retrieved-source) and the three
modes (off / annotate / strip).
"""
from __future__ import annotations

import pytest

from screwshell.core.citations import (
    CitationValidator, merge_citations, normalize_source, validate_citations,
)


@pytest.fixture
def ws(tmp_path):
    (tmp_path / "notes.py").write_text("\n".join(f"line{i}" for i in range(1, 11)),
                                       encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "rag.md").write_text("a\nb\nc\n", encoding="utf-8")
    return tmp_path


# ----------------------------------------------------------------- extract
def test_extract_parses_ranges_and_plain_lines(ws):
    v = CitationValidator(str(ws))
    cites = v.extract("see notes.py#L1-L3 and notes.py#L7 and sub/rag.md#L2")
    assert [(c.source, c.start_line, c.end_line) for c in cites] == [
        ("notes.py", 1, 3), ("notes.py", 7, 7), ("sub/rag.md", 2, 2)]


def test_normalize_source_unifies_windows_backslashes(ws):
    assert normalize_source(r"a\b.py") == "a/b.py"
    assert normalize_source("./a.py") == "a.py"
    assert normalize_source(" a.py ") == "a.py"


# ----------------------------------------------------- layer 2: file checks
def test_file_missing(ws):
    v = CitationValidator(str(ws))
    c = v.extract("x ghost.py#L1")[0]
    issue = v.check(c)
    assert issue is not None and issue.kind == "file_missing"


def test_line_out_of_range(ws):
    v = CitationValidator(str(ws))
    c = v.extract("x notes.py#L99")[0]
    issue = v.check(c)
    assert issue is not None and issue.kind == "line_out_of_range"


def test_outside_workspace(ws):
    v = CitationValidator(str(ws))
    c = v.extract("x ../secrets.py#L1")[0]
    issue = v.check(c)
    assert issue is not None and issue.kind == "outside_workspace"


def test_valid_citation_passes(ws):
    v = CitationValidator(str(ws))
    c = v.extract("x notes.py#L2-L4")[0]
    assert v.check(c) is None


# --------------------------------------------------- layer 3: retrieved-only
def test_not_retrieved_when_index_supplied(ws):
    v = CitationValidator(str(ws), retrieved=[{"source": "notes.py",
                                               "start_line": 1,
                                               "end_line": 5}])
    hit = v.extract("x notes.py#L2-L3")[0]      # inside the retrieved range
    miss = v.extract("x notes.py#L9")[0]        # outside it
    assert v.check(hit) is None
    assert v.check(miss).kind == "not_retrieved"


# ------------------------------------------- layer 3.5: quote round-trip
def test_quote_roundtrip_passes_when_literal_present(ws):
    # notes.py lines are "line1".."line10"
    v = CitationValidator(str(ws))
    c = v.extract("x notes.py#L2-L3")[0]
    assert v.check(c, context='如 "line2" 所示 ') is None


def test_quote_roundtrip_flags_missing_literal(ws):
    v = CitationValidator(str(ws))
    c = v.extract("x notes.py#L2-L3")[0]
    issue = v.check(c, context='如 "line9" 所示 ')
    assert issue is not None and issue.kind == "quote_not_found"


def test_quote_roundtrip_skips_when_no_quote(ws):
    v = CitationValidator(str(ws))
    c = v.extract("x notes.py#L2-L3")[0]
    assert v.check(c, context="根据实现 ") is None


# ------------------------------------------------------------------ modes
def test_annotate_marks_unverified_without_deleting(ws):
    text = "结论见 notes.py#L1-L2 与 ghost.py#L7。"
    out, report = validate_citations(text, workspace=str(ws), mode="annotate")
    assert report.total == 2 and report.valid == 1
    assert "ghost.py#L7 ⚠未证实" in out          # inline mark
    assert "notes.py#L1-L2" in out and "⚠未证实" not in out.split("ghost")[0]
    assert "引用校验：2 条引用中 1 条未证实" in out  # summary line
    assert "file_missing" in out


def test_strip_removes_only_the_bad_mark(ws):
    text = "结论见 notes.py#L1-L2 与 ghost.py#L7，其余正常。"
    out, report = validate_citations(text, workspace=str(ws), mode="strip")
    assert report.total == 2 and report.valid == 1
    assert "ghost.py#L7" not in out              # mark gone
    assert "notes.py#L1-L2" in out               # good mark kept
    assert "其余正常" in out                      # sentence kept


def test_off_returns_text_untouched(ws):
    text = "结论见 ghost.py#L7。"
    out, report = validate_citations(text, workspace=str(ws), mode="off")
    assert out == text
    assert report.total == 0


def test_accuracy_zero_for_uncited_answer(ws):
    _, report = validate_citations("没有引用的答案。", workspace=str(ws))
    assert report.total == 0 and report.accuracy == 0.0


# --------------------------------------------------------------- merging
def test_merge_citations_merges_same_source(ws):
    out = merge_citations([
        {"source": "a.py", "start_line": 1, "end_line": 3, "score": 0.5},
        {"source": "a.py", "start_line": 5, "end_line": 9, "score": 0.8},
        {"source": "b.md", "start_line": 2, "end_line": 2, "score": 0.2},
    ], max_n=8)
    assert len(out) == 2
    merged = next(d for d in out if d["source"] == "a.py")
    assert merged["start_line"] == 1 and merged["end_line"] == 9
    assert merged["score"] == 0.8
