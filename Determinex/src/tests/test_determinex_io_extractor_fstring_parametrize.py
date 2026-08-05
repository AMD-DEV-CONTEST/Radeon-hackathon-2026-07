"""Tests for determinex_io_extractor.py's f-string-with-parametrize resolution (2026-07-16),
the eleventh fix in the skip-rate chain -- two related gaps found and fixed together.

Continuing the tool-by-tool audit onto codesnap (34.3% skip after fixes 1-10):
test_argument_parsing.py had 26/106 skipped. Two distinct but closely related causes:

(1) An f-string assigned to a LOCAL VARIABLE, one indirection away from argv:

        def test_output_supported_formats(self, extension):
            filename = f"test.{extension}"
            returncode, stdout, stderr = run_command(["-o", filename, "-c", "test"])

    `extension` is a @pytest.mark.parametrize value (fix 8 already resolves that), but
    `_track_vars` only handles LITERAL assignments via `_const()` -- a JoinedStr referencing
    a variable was invisible to it, so `filename` never made it into vars_map at all, and
    `run_command([..., filename, ...])` failed to resolve. Fixed by
    _track_local_fstring_vars(func, vars_map): a second pass over local assignments that
    tries _resolve_fstring_with_vars (already used for f-strings written directly in an
    assertion) against the CALLER's vars_map -- which by the time this runs already
    includes the current parametrize case's substitution, so `extension` is available.

(2) An f-string used DIRECTLY INLINE as an argv list element, no local variable at all:

        def test_color_flags_accept_hex_values(self, flag):
            run_command([f"--{flag}", "#ff0000", "-o", "test.png", "-c", "test"])

    A different AST position for the same underlying gap -- `_resolve()` (the function
    _resolve_list/_find_run_call funnel every argv element through) only tried `_const()`
    then a bare-Name vars_map lookup; a JoinedStr node was never given to
    _resolve_fstring_with_vars at all. Fixed by extending _resolve() itself to try it as a
    third option, benefiting every call site that already goes through _resolve() (argv
    list elements, keyword args, etc.) with no separate wiring needed.

Both fixes reuse _resolve_fstring_with_vars -- no new resolution logic, just two more call
sites reaching the one already-correct function.

Real A/B counterfactual on codesnap's test_argument_parsing.py: fix (1) alone took the file
80->83 examples (test_output_supported_formats's 3 parametrize cases). Fix (2) alone (on top
of fix 1) took it to 96 examples (+13 more: test_color_flags_accept_hex_values's 9 cases +
test_font_family_flags's 4 cases). test_long_flags_with_equals (5 cases) stays correctly
unresolved -- its argv depends on an `if flag_value.startswith(...): args.extend(...)`
CONDITIONAL evaluated against the parametrize value, real control-flow simulation rather
than data resolution; flagged as a bigger, separate lift, not attempted here. Across the
full 6-tool re-scan (3 branches each): codesnap 90->106 examples (34.3%->22.6%), plus a
bonus +12 on xh (529->541, general mechanism reused elsewhere in that corpus too, not
specifically targeted). atlas/ov/hwatch/lazygit unchanged (pattern absent in their sampled
branches).
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import determinex_io_extractor as iox  # noqa: E402

# ---------- _track_local_fstring_vars() ----------


def test_resolves_local_fstring_var_using_parametrize_case():
    tree = ast.parse("""
def test_x(extension):
    filename = f"test.{extension}"
""")
    node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef))
    out = iox._track_local_fstring_vars(node, {"extension": "png"})
    assert out == {"filename": "test.png"}


def test_does_not_overwrite_an_existing_vars_map_entry():
    tree = ast.parse("""
def test_x(extension):
    filename = f"test.{extension}"
""")
    node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef))
    out = iox._track_local_fstring_vars(node, {"extension": "png", "filename": "already-set"})
    assert out == {}


def test_leaves_unresolvable_fstring_out(tmp_path=None):
    tree = ast.parse("""
def test_x():
    filename = f"test.{unknown_var}"
""")
    node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef))
    out = iox._track_local_fstring_vars(node, {})
    assert out == {}


def test_ignores_plain_literal_assignments():
    """A literal (non-f-string) assignment isn't this function's job -- _track_vars
    already handles it; must not duplicate or interfere."""
    tree = ast.parse("""
def test_x():
    filename = "plain.txt"
""")
    node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef))
    out = iox._track_local_fstring_vars(node, {})
    assert out == {}


# ---------- _resolve(): inline f-string resolution ----------


def test_resolve_handles_inline_fstring_via_vars_map():
    node = ast.parse('f"--{flag}"', mode="eval").body
    assert iox._resolve(node, {"flag": "color"}) == "--color"


def test_resolve_inline_fstring_unresolvable_falls_through():
    node = ast.parse('f"--{flag}"', mode="eval").body
    assert iox._resolve(node, {}) is iox._UNK


def test_resolve_still_handles_plain_name_and_constant():
    """Regression guard: adding the JoinedStr branch must not disturb the existing
    bare-Name and literal-constant resolution paths."""
    name_node = ast.parse("flag", mode="eval").body
    assert iox._resolve(name_node, {"flag": "value"}) == "value"
    const_node = ast.parse('"literal"', mode="eval").body
    assert iox._resolve(const_node, {}) == "literal"


# ---------- extract_file() integration ----------

_PREFIX = """
import subprocess

def run_command(args):
    return subprocess.run(["./executable"] + args, capture_output=True, text=True)
"""


def test_extract_file_resolves_argv_via_local_fstring_var(tmp_path):
    src = (
        _PREFIX
        + """
@pytest.mark.parametrize("extension", ["png", "svg"])
def test_output_supported_formats(extension):
    filename = f"test.{extension}"
    result = run_command(["-o", filename, "-c", "test"])
    assert result.returncode == 0
"""
    )
    f = tmp_path / "test_x.py"
    f.write_text(src, encoding="utf-8")
    cov = iox.extract_file(f)
    assert cov.n_examples == 2
    by_name = {e.test: e for e in cov.examples}
    # run_command's own base is now correctly included as the "executable"
    # placeholder (fix 40, 2026-07-17: _is_executable_path_expr now also
    # recognizes a bare string literal with slashes baked in).
    assert by_name["test_output_supported_formats[png]"].argv == [
        "executable",
        "-o",
        "test.png",
        "-c",
        "test",
    ]
    assert by_name["test_output_supported_formats[svg]"].argv == [
        "executable",
        "-o",
        "test.svg",
        "-c",
        "test",
    ]


def test_extract_file_resolves_argv_via_inline_fstring(tmp_path):
    src = (
        _PREFIX
        + """
@pytest.mark.parametrize("flag", ["color", "reverse"])
def test_color_flags(flag):
    result = run_command([f"--{flag}", "#ff0000", "-o", "test.png"])
    assert result.returncode == 0
"""
    )
    f = tmp_path / "test_x.py"
    f.write_text(src, encoding="utf-8")
    cov = iox.extract_file(f)
    assert cov.n_examples == 2
    by_name = {e.test: e for e in cov.examples}
    # run_command's own base is now correctly included as the "executable"
    # placeholder (fix 40, 2026-07-17).
    assert by_name["test_color_flags[color]"].argv == [
        "executable",
        "--color",
        "#ff0000",
        "-o",
        "test.png",
    ]
    assert by_name["test_color_flags[reverse]"].argv == [
        "executable",
        "--reverse",
        "#ff0000",
        "-o",
        "test.png",
    ]


def test_extract_file_conditional_argv_still_correctly_unresolved(tmp_path):
    """Confirms the known, deliberately-unbuilt boundary: argv built by branching on the
    parametrize value at runtime (control flow, not data resolution) stays skipped."""
    src = (
        _PREFIX
        + """
@pytest.mark.parametrize("flag_value", ["--output=test.png", "--language=python"])
def test_long_flags_with_equals(flag_value):
    args = [flag_value, "-c", "test"]
    if not flag_value.startswith("--output"):
        args.extend(["-o", "test.png"])
    result = run_command(args)
    assert result.returncode == 0
"""
    )
    f = tmp_path / "test_x.py"
    f.write_text(src, encoding="utf-8")
    cov = iox.extract_file(f)
    assert cov.n_examples == 0
    assert len(cov.skipped) == 2
