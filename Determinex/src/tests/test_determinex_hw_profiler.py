"""tests/test_determinex_hw_profiler.py

Regression coverage for detect_dialect_sources's own copy of the same bug
class fixed in determinex_ingest.py: a raw, unfiltered `root.rglob("*.c")`
walked (and read_text'd -- full file CONTENTS, not just a stat) every .c
file anywhere under root, including huge non-source directories. Found live
2026-07-22 as the real remaining hang in ingest() on this repo after the
walk-and-crash bugs in determinex_ingest.py itself were fixed: this repo's
own census reports "c" as its most common language (thousands of vendored
ProgramBench reference C archives outweigh the Python/TS source), which
triggers this exact function on every real oracle-verification call.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT, _ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import determinex_hw_profiler as hw  # noqa: E402


def test_detect_dialect_sources_finds_a_real_match(tmp_path):
    (tmp_path / "kernel.c").write_text(
        "void run(void) { CONV_3x3_P1_VPU(a, b, c); }\n", encoding="utf-8"
    )
    found = hw.detect_dialect_sources(tmp_path)
    assert found is not None
    name, sources = found
    assert name == "et_soc1_yolo"
    assert sources == [tmp_path / "kernel.c"]


def test_detect_dialect_sources_ignores_excluded_dirs(tmp_path):
    (tmp_path / "kernel.c").write_text("int x;\n", encoding="utf-8")
    nm = tmp_path / "node_modules"
    nm.mkdir()
    (nm / "vendored.c").write_text(
        "void run(void) { CONV_3x3_P1_VPU(a, b, c); }\n", encoding="utf-8"
    )
    # The only real signature match lives in an excluded dir -- must not be found.
    assert hw.detect_dialect_sources(tmp_path) is None


def test_detect_dialect_sources_skips_scan_past_file_count_cap(tmp_path, monkeypatch):
    """Regression: thousands of real (non-excluded) .c files -- e.g. this
    project's own vendored ProgramBench reference archives -- must not be
    read+regex-scanned one by one. A repo with more .c files than a
    hand-ported kernel could realistically be skips the scan outright."""
    monkeypatch.setattr(hw, "_MAX_DIALECT_SCAN_FILES", 2)
    for i in range(5):
        (tmp_path / f"file_{i}.c").write_text(
            "void run(void) { CONV_3x3_P1_VPU(a, b, c); }\n", encoding="utf-8"
        )
    assert hw.detect_dialect_sources(tmp_path) is None


def test_detect_dialect_returns_none_when_no_signature_matches(tmp_path):
    (tmp_path / "plain.c").write_text("int main(void) { return 0; }\n", encoding="utf-8")
    assert hw.detect_dialect_sources(tmp_path) is None
    assert hw.detect_dialect(tmp_path) is None
