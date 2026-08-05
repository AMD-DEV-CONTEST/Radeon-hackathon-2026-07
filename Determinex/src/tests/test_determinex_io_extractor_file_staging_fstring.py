"""Tests for determinex_io_extractor.py's f-string file-staging support (2026-07-17),
the twelfth fix in the skip-rate chain.

Continuing the tool-by-tool audit onto xh's remaining skips, sampled a broad, non-network
spread and found test_data_binary_from_file entirely unresolved:

    test_file = RESOURCES / 'binary_test.txt'
    RESOURCES.mkdir(parents=True, exist_ok=True)
    test_file.write_text('binary content\\n')
    result = run(['--curl', 'http://httpbin.org/post', f'@{test_file}'])
    assert result.returncode == 0
    assert "--data-binary" in stdout
    assert f"@{test_file}" in stdout

_track_files already resolves `test_file = RESOURCES / 'x'; test_file.write_text(...)`
into files_map (this pattern was already supported, confirmed by reading the existing
code before assuming anything was missing -- audit-before-build). The gap was purely on
the CONSUMPTION side: _file_arg (the function that recognizes a tracked file variable
used as an argv element and stages it) only matched `str(v)` or a bare `v` -- an f-string
reference (`f'@{test_file}'`) was invisible to it, so the file variable's resolved content
never got staged even though it was already known.

The generic _resolve() f-string branch (added in fix 11) COULD have resolved the text
`'@binary_test.txt'` on its own, but that path only produces a string -- it does not know
to also stage the underlying file for the oracle. Extracting the argv text alone without
staging the file would produce a CONFIDENTLY WRONG example: the oracle would run the real
CLI against a file that doesn't exist. That is worse than not extracting the test at all,
so this was deliberately NOT built via the cheaper _resolve() path (flagged, sized, and
correctly deferred as `io_extractor_write_text_staged_file_lead_20260717` in
build_knowledge.json rather than rushed).

Fix: extended _file_arg itself to also recognize a JoinedStr (f-string) argv element that
wraps EXACTLY ONE tracked file variable (plus arbitrary literal text around it, like the
leading `@`), and changed its return shape from a 2-tuple (basename doubling as both the
staged filename AND the argv text) to a 3-tuple `(arg_text, basename, content)`, since for
the f-string case those first two now differ (arg_text='@binary_test.txt', basename=
'binary_test.txt'). Both existing call sites (_resolve_list, _find_run_call's positional
arg loop) updated to unpack the 3-tuple and stage under `basename` while emitting
`arg_text` into argv -- this keeps the plain `str(v)`/bare-`v` cases byte-identical (there
arg_text == basename already). Also merged files_map's basenames into vars_map (as plain
strings) so the SAME variable resolves for an f-string reference on the ASSERTION side
too (`assert f"@{test_file}" in stdout`), via the existing fix-11 vars_map lookup in
_resolve_in_snippet -- no new logic needed there, just wider data flow.

Real A/B counterfactual: xh's test_curl_conversion.py went from partially-resolved to
163/163 (0 skipped) on this measure. Across xh's whole directory (one branch): 529->536
examples (+7 -- most of xh's remaining skips are still the separate, genuinely unfixable
http_server network-mock-server category, and the tempfile.NamedTemporaryFile-random-path
category, neither touched by this fix). Full 6-tool re-scan: xh 541->549 examples,
skip rate 46.5%->45.8%. Other 5 tools unchanged (pattern not present in their sampled
branches).
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import determinex_io_extractor as iox  # noqa: E402

# ---------- _file_arg(): f-string branch ----------


def test_file_arg_resolves_fstring_wrapping_one_file_var():
    node = ast.parse("f'@{test_file}'", mode="eval").body
    files_map = {"test_file": ("binary_test.txt", "binary content\n")}
    fa = iox._file_arg(node, files_map)
    assert fa == ("@binary_test.txt", "binary_test.txt", "binary content\n")


def test_file_arg_plain_bare_name_still_returns_matching_arg_text_and_basename():
    """Regression guard: the pre-fix 2-tuple shape's callers now unpack a 3-tuple --
    confirm the plain (non-f-string) case keeps arg_text == basename exactly as before."""
    node = ast.parse("test_file", mode="eval").body
    files_map = {"test_file": ("binary_test.txt", "binary content\n")}
    fa = iox._file_arg(node, files_map)
    assert fa == ("binary_test.txt", "binary_test.txt", "binary content\n")


def test_file_arg_plain_str_call_still_works():
    node = ast.parse("str(test_file)", mode="eval").body
    files_map = {"test_file": ("binary_test.txt", "binary content\n")}
    fa = iox._file_arg(node, files_map)
    assert fa == ("binary_test.txt", "binary_test.txt", "binary content\n")


def test_file_arg_fstring_with_two_file_vars_bails():
    """Two tracked-file references in one f-string is an ambiguous/unusual shape --
    never guess which one 'the' staged file is."""
    node = ast.parse("f'{a}-{b}'", mode="eval").body
    files_map = {
        "a": ("a.txt", "A"),
        "b": ("b.txt", "B"),
    }
    assert iox._file_arg(node, files_map) is None


def test_file_arg_fstring_with_untracked_name_bails():
    node = ast.parse("f'@{unrelated}'", mode="eval").body
    files_map = {"test_file": ("binary_test.txt", "binary content\n")}
    assert iox._file_arg(node, files_map) is None


def test_file_arg_fstring_with_non_name_interpolation_bails():
    """`f'@{obj.attr}'` or any other non-bare-Name interpolation isn't resolvable here --
    never guess past what's a plain tracked variable reference."""
    node = ast.parse("f'@{test_file.name}'", mode="eval").body
    files_map = {"test_file": ("binary_test.txt", "binary content\n")}
    assert iox._file_arg(node, files_map) is None


def test_file_arg_non_file_arg_node_returns_none():
    node = ast.parse("42", mode="eval").body
    assert iox._file_arg(node, {}) is None


# ---------- extract_file() integration ----------

_PREFIX = """
import subprocess

RESOURCES = __import__("pathlib").Path(__file__).parent / "test_resources" / "test_x"

def run(args):
    return subprocess.run(["./executable"] + args, capture_output=True, text=True)
"""


def test_extract_file_stages_fstring_referenced_file_correctly(tmp_path):
    src = (
        _PREFIX
        + """
def test_data_binary_from_file():
    test_file = RESOURCES / "binary_test.txt"
    test_file.write_text("binary content\\n")
    result = run(["--curl", "http://httpbin.org/post", f"@{test_file}"])
    assert result.returncode == 0
    assert "--data-binary" in result.stdout
    assert f"@{test_file}" in result.stdout
"""
    )
    f = tmp_path / "test_x.py"
    f.write_text(src, encoding="utf-8")
    cov = iox.extract_file(f)
    assert cov.n_examples == 1
    e = cov.examples[0]
    # run's own base (["./executable"]) is now correctly included -- see the
    # chained-wrapper-name discovery fix note in test_determinex_io_extractor_chained_fixtures.py
    # "executable" placeholder now correctly resolved (fix 40, 2026-07-17):
    # _is_executable_path_expr now also recognizes a bare string literal with
    # slashes baked in ("./executable"), not just a BinOp/Div chain.
    assert e.argv == ["executable", "--curl", "http://httpbin.org/post", "@binary_test.txt"]
    assert e.files == {"binary_test.txt": "binary content\n"}
    assert "--data-binary" in e.expect_in
    assert "@binary_test.txt" in e.expect_in


def test_extract_file_does_not_stage_the_arg_text_as_the_filename(tmp_path):
    """Confirms the 3-tuple split: the staged dict key must be the real basename
    ('binary_test.txt'), never the CLI arg text with its '@' prefix -- staging under
    the wrong name would mean the oracle creates a file the CLI never actually looks
    for, silently defeating the whole point of staging it."""
    src = (
        _PREFIX
        + """
def test_x():
    test_file = RESOURCES / "binary_test.txt"
    test_file.write_text("binary content\\n")
    result = run(["--curl", "http://httpbin.org/post", f"@{test_file}"])
    assert result.returncode == 0
"""
    )
    f = tmp_path / "test_x.py"
    f.write_text(src, encoding="utf-8")
    cov = iox.extract_file(f)
    assert cov.n_examples == 1
    assert "@binary_test.txt" not in cov.examples[0].files
    assert "binary_test.txt" in cov.examples[0].files
