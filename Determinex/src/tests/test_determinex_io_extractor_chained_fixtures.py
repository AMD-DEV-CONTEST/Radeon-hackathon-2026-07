"""Tests for determinex_io_extractor.py's chained run-fixture resolution (2026-07-17),
the thirteenth fix in the skip-rate chain.

Continuing the tool-by-tool audit onto xh's remaining skips, found test_help_usage.py at
82/87 skipped despite fix 9 (run-invoking-fixture fallback) already existing:

    @pytest.fixture(scope="session")
    def help_result():
        return run_cmd(["--help"])

    @pytest.fixture(scope="session")
    def help_text(help_result):
        return help_result.stdout

    @pytest.mark.parametrize("flag", ["--help", "--version", ...])
    def test_help_documents_flag(help_text, flag):
        assert flag in help_text

`help_result` is a proper run-invoking fixture that fix 9's _track_run_fixtures already
finds fine. But every test here takes `help_text`, a SECOND fixture that depends on
`help_result` and merely projects one field (`.stdout`) out of it -- `help_text`'s own
body has no run-call at all, so _find_run_call finds nothing and it never entered the
run_fixtures map, even though every test in the file depends on exactly this fixture.

Which field gets projected doesn't matter for argv resolution -- a test using `help_text`
ran the exact same command as one using `help_result` directly. The expectation side
already doesn't care how the test's local name was bound (_is_result_rc/_is_result_out
match on attribute name alone, and the In/NotIn machinery doesn't validate its haystack
side at all -- confirmed via prior fixes' own notes), so `assert flag in help_text` and
`assert flag in help_result.stdout` resolve to checking the identical real captured
output. Fixed by extending _track_run_fixtures with a second, fixed-point pass: after the
first pass resolves direct run-invoking fixtures, repeatedly scan for a fixture whose body
is exactly `return <own-param>.<attr>` where `<own-param>` names one of ITS OWN
parameters and that parameter is already a resolved fixture -- if so, register it with the
identical (argv, stdin, env, files) tuple. Bounded by fixture count, so a chain three (or
more) deep also resolves without an artificial depth limit, and it never guesses past the
exact `return <param>.<attr>` shape (a fixture with any real logic in its body stays
unresolved, matching the existing discipline from the sibling alias-resolution fixes).

Real A/B counterfactual: test_help_usage.py went from 5/87 to 83/87 examples -- skip rate
94.3%->4.6%. The 4 remaining skips are each a genuinely different shape (no run call at
all, a direct stdout/stderr split check, an arguments-and-options section-listing check,
and a trailing-newline check) -- none forced. Full 6-tool re-scan (3 branches each): xh
549->627 examples, skip rate 45.8%->38.0%. Other 5 tools unchanged (pattern absent in
their sampled branches).
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import determinex_io_extractor as iox  # noqa: E402


def _tree(src: str) -> ast.Module:
    return ast.parse(src)


# ---------- _track_run_fixtures(): chained resolution ----------


def test_resolves_a_two_level_fixture_chain():
    tree = _tree("""
import subprocess

def run_cmd(args):
    return subprocess.run(["./executable"] + args, capture_output=True, text=True)

@pytest.fixture(scope="session")
def help_result():
    return run_cmd(["--help"])

@pytest.fixture(scope="session")
def help_text(help_result):
    return help_result.stdout
""")
    fx = iox._track_run_fixtures(tree, set())
    assert "help_result" in fx
    assert "help_text" in fx
    assert fx["help_text"] == fx["help_result"]
    assert fx["help_text"][0] == ["--help"]


def test_resolves_a_three_level_fixture_chain():
    """A chain three deep: each link projects an attribute off the previous fixture --
    same shape as the two-level case, just applied twice, confirming the fixed-point
    loop isn't hardcoded to exactly one hop."""
    tree = _tree("""
import subprocess

def run_cmd(args):
    return subprocess.run(["./executable"] + args, capture_output=True, text=True)

@pytest.fixture
def help_result():
    return run_cmd(["--help"])

@pytest.fixture
def help_text(help_result):
    return help_result.stdout

@pytest.fixture
def help_text_length(help_text):
    return help_text.__len__
""")
    fx = iox._track_run_fixtures(tree, set())
    assert "help_text_length" in fx
    assert fx["help_text_length"] == fx["help_result"]


def test_fixture_with_real_logic_in_body_is_not_chained():
    """A fixture that does more than a bare `return <param>.<attr>` is not a transparent
    projection -- never guess past real logic in the body."""
    tree = _tree("""
import subprocess

def run_cmd(args):
    return subprocess.run(["./executable"] + args, capture_output=True, text=True)

@pytest.fixture
def help_result():
    return run_cmd(["--help"])

@pytest.fixture
def help_text_upper(help_result):
    text = help_result.stdout
    return text.upper()
""")
    fx = iox._track_run_fixtures(tree, set())
    assert "help_result" in fx
    assert "help_text_upper" not in fx


def test_fixture_projecting_an_unresolved_fixture_stays_unresolved():
    tree = _tree("""
@pytest.fixture
def sample_result():
    return make_something_not_a_run_call()

@pytest.fixture
def sample_text(sample_result):
    return sample_result.stdout
""")
    fx = iox._track_run_fixtures(tree, set())
    assert fx == {}


def test_fixture_attribute_of_unrelated_name_not_chained():
    """The Attribute base must be one of THIS fixture's own parameters -- an attribute
    access on some other name (e.g. a module-level constant) must not match."""
    tree = _tree("""
import subprocess

def run_cmd(args):
    return subprocess.run(["./executable"] + args, capture_output=True, text=True)

@pytest.fixture
def help_result():
    return run_cmd(["--help"])

SOME_OBJ = object()

@pytest.fixture
def odd_fixture(help_result):
    return SOME_OBJ.attr
""")
    fx = iox._track_run_fixtures(tree, set())
    assert "help_result" in fx
    assert "odd_fixture" not in fx


# ---------- extract_file() integration ----------

_PREFIX = """
import subprocess

def run_cmd(args):
    return subprocess.run(["./executable"] + args, capture_output=True, text=True)

@pytest.fixture(scope="session")
def help_result():
    return run_cmd(["--help"])

@pytest.fixture(scope="session")
def help_text(help_result):
    return help_result.stdout
"""


def test_extract_file_resolves_test_via_chained_fixture(tmp_path):
    src = (
        _PREFIX
        + """
@pytest.mark.parametrize("flag", ["--help", "--version"])
def test_help_documents_flag(help_text, flag):
    assert flag in help_text
"""
    )
    f = tmp_path / "test_x.py"
    f.write_text(src, encoding="utf-8")
    cov = iox.extract_file(f)
    assert cov.n_tests == 2
    assert cov.n_examples == 2
    by_name = {e.test: e for e in cov.examples}
    # run_cmd's own base (["./executable"]) is now correctly included -- 2026-07-17's
    # chained-wrapper-name discovery fix registers run_cmd's base+args contract
    # (it directly shells out via `subprocess.run(["./executable"] + args, ...)`), so
    # argv reflects the REAL, complete command instead of missing the executable
    # placeholder entirely.
    # "executable" placeholder now correctly resolved (fix 40, 2026-07-17):
    # _is_executable_path_expr now also recognizes a bare string literal with
    # slashes baked in ("./executable"), not just a BinOp/Div chain.
    assert by_name["test_help_documents_flag[--help]"].argv == ["executable", "--help"]
    assert by_name["test_help_documents_flag[--help]"].expect_in == ["--help"]
    assert by_name["test_help_documents_flag[--version]"].expect_in == ["--version"]
