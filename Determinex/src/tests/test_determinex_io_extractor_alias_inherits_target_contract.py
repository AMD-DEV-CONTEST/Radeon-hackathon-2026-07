"""Test for fix 33 (2026-07-17): a fixture ALIAS (`def run_cmd(): return run_binary`,
no assignment, no Call) must inherit its TARGET's learned base/flags/suffix contract
under the alias's own name, not just be recognized as a "valid run-name."

Root-caused via dropbear's whole test suite: `run_binary(*args, **kwargs)` is a
plain module-level function that shells out via `cmd = ["../executable"] +
list(args); return subprocess.run(cmd, **kwargs)` -- a well-learnable base
(["../executable"]) via the existing `[prefix] + list(args)` mechanism. But every
test calls `run_cmd(...)`, a FIXTURE whose body is bare `return run_binary`.
_discover_fixture_wrapper_aliases already recognized "run_cmd" as a VALID run-name
(so _find_run_call doesn't skip its call nodes) -- but that alone doesn't help:
_find_run_call's is_learned_wrapper check does `kwarg_flags.get(name)` where `name`
is literally "run_cmd" (the call site's own func name), and kwarg_flags only ever
had an entry under "run_binary". So is_learned_wrapper stayed False for every
run_cmd(...) call, and the caller's own args became the WHOLE argv --
`run_cmd("-h")` resolved to argv=['-h'], missing "../executable" entirely: a
confidently WRONG example, not a skip.

Fixed by changing _discover_fixture_wrapper_aliases's return type from a bare
set[str] to dict[str, str] (alias name -> its real target name), then copying the
target's kwarg_flags entry to the alias's own name too, whenever the alias doesn't
already have its own entry.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import determinex_io_extractor as iox  # noqa: E402


def test_discover_fixture_wrapper_aliases_returns_target_mapping():
    tree = iox.ast.parse("""
import subprocess
import pytest

def run_binary(*args, **kwargs):
    cmd = ["../executable"] + list(args)
    return subprocess.run(cmd, **kwargs)

@pytest.fixture
def run_cmd():
    return run_binary
""")
    aliases = iox._discover_fixture_wrapper_aliases(tree, Path("conftest.py"), {"run_binary"})
    assert aliases == {"run_cmd": "run_binary"}


def test_extract_file_resolves_dropbear_shaped_bare_alias_end_to_end(tmp_path):
    conf = tmp_path / "conftest.py"
    conf.write_text(
        """
import subprocess
import pytest

def run_binary(*args, **kwargs):
    cmd = ["../executable"] + list(args)
    kwargs.setdefault("capture_output", True)
    return subprocess.run(cmd, **kwargs)

@pytest.fixture
def run_cmd():
    return run_binary
""",
        encoding="utf-8",
    )
    src = """
def test_help(run_cmd):
    result = run_cmd("-h")
    assert result.returncode == 0
"""
    f = tmp_path / "test_x.py"
    f.write_text(src, encoding="utf-8")
    cov = iox.extract_file(f)
    assert cov.n_examples == 1
    # "executable" placeholder now correctly resolved (fix 40, 2026-07-17):
    # _is_executable_path_expr now also recognizes a bare string literal with
    # slashes baked in ("../executable"), not just a BinOp/Div chain.
    assert cov.examples[0].argv == ["executable", "-h"]
