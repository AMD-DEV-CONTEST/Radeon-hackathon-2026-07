"""What the Compiler Oracle actually verifies, per language.

WHY THIS EXISTS
---------------
The oracle is this system's entire reward signal -- CLAUDE.md: "Every training sample
in the corpus has passed a real compiler. This is the entire reward model." Measured
2026-07-28, `validate_project` had four branches and two of them verified almost
nothing:

  rust    -> cargo build        real type check
  go      -> go build ./...     real type check
  python  -> compileall         SYNTAX ONLY. Never executes a line, so a module-level
                                NameError, a bad import, or a reference to a function
                                that does not exist all produced "Compiler Oracle: PASS".
  else    -> return (True, "")  LENIENT PASS. TypeScript, Java, C, C++ all landed here,
                                so every step of such a session was recorded as verified
                                by nothing at all -- while CLAUDE.md listed `tsc` as
                                part of the oracle.

The lenient pass also contradicted the doctrine determinex_oracle.py was built to
enforce: "a stub raises OracleUnavailable with an install hint -- an oracle never
silently passes."

These tests pin the fix. They run the REAL oracle against real Docker, so they are
marked slow and skip when the sandbox backend is unavailable rather than passing
vacuously -- a skipped test says "not checked", a passing stub would say "verified",
which is the exact failure this file exists to prevent.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
for p in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

from hive.compiler import (  # noqa: E402
    _ORACLE_IMAGES,
    _oracle_install_hint,
    validate_project,
)

pytestmark = pytest.mark.slow


def _ws(tmp_path: Path, files: dict[str, str]) -> Path:
    for name, content in files.items():
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return tmp_path


ADD_OK = "def add(a, b):\n    return a + b\n"
ADD_WRONG = "def add(a, b):\n    return a - b\n"
TEST_ADD = (
    "import unittest\n"
    "from ok import add\n"
    "class T(unittest.TestCase):\n"
    "    def test_a(self):\n"
    "        self.assertEqual(add(2, 3), 5)\n"
)


# ── the language matrix, which is the actual claim ───────────────────────────


def test_the_configured_language_set_is_pinned():
    """Pins the honest scope. If someone adds an image, this fails and forces the
    per-language strength claim in CLAUDE.md to be updated with it.

    It has already worked once: adding the typescript image on 2026-07-29 failed this
    test plus the three below that used `typescript` AS their example of an unconfigured
    language, which is what made repointing them unavoidable rather than optional."""
    assert sorted(_ORACLE_IMAGES) == ["go", "python", "rust", "typescript"]


def test_an_unconfigured_language_fails_closed(tmp_path):
    """Was `return (True, "")`. A PASS that means nothing is worse than an honest
    failure: in the WAL and in the training corpus it is indistinguishable from a
    real one."""
    ws = _ws(tmp_path, {"A.java": 'class A { int x = "nope"; }\n'})
    passed, msg = validate_project(ws, "java")
    assert passed is False, "java was silently passed as verified"
    assert "No sandboxed Compiler Oracle" in msg
    assert "java" in msg


def test_the_failure_message_is_actionable(tmp_path):
    """It must say which languages ARE configured and how to get the missing
    toolchain, or the operator is left guessing."""
    ws = _ws(tmp_path, {"A.java": "class A {}\n"})
    _passed, msg = validate_project(ws, "java")
    for expected in ("python", "rust", "go", "typescript", "DETERMINEX_ORACLE_LENIENT"):
        assert expected in msg


def test_the_lenient_escape_hatch_marks_the_result_unverified(tmp_path, monkeypatch):
    """An opt-out has to exist so this change does not silently break in-flight work
    in another language -- but it must never look like a real pass. The returned
    output is tagged UNVERIFIED so the WAL carries the distinction."""
    monkeypatch.setenv("DETERMINEX_ORACLE_LENIENT", "1")
    ws = _ws(tmp_path, {"A.java": "class A {}\n"})
    passed, msg = validate_project(ws, "java")
    assert passed is True
    assert msg.startswith("UNVERIFIED:")


def test_install_hint_reads_the_registry_without_executing_anything():
    """The hint comes from determinex_oracle's dataclass, not from running its
    verify_fn. That distinction is why validate_project cannot just delegate: the
    registry's verify_fns use a direct host subprocess, and gaining verification by
    running model output outside the sandbox would trade a correctness gap for a
    security one."""
    hint = _oracle_install_hint("typescript")
    assert "typescript" in hint.lower()
    assert _oracle_install_hint("no-such-language-xyz") == ""


# ── python: the three stages, each strictly stronger than compileall ─────────


def _docker_ok() -> bool:
    """Is there a backend the ORACLE WILL ACTUALLY USE -- not merely one that exists.

    The first version of this asked only whether a backend resolved, and accepted
    ("docker", "wsl2", "direct"). But `validate_project` honours
    DETERMINEX_REQUIRE_DOCKER, which defaults to 1 and REFUSES wsl2 and direct:

        RuntimeError: DETERMINEX_REQUIRE_DOCKER=1 but backend resolved to WSL2.

    So on a WSL2-only box -- which is exactly what this project's own dev machine is, per
    CLAUDE.md -- the guard said "a backend is available", the runtime said "not that one",
    and the tests FAILED where they should have skipped. A skip condition that does not ask
    the same question the code asks is a check reporting an outcome it never established.
    """
    try:
        from hive.compiler import _oracle_backend

        backend = _oracle_backend()
    except Exception:
        return False
    if backend not in ("docker", "wsl2", "direct"):
        return False
    # Mirror the runtime's own gate rather than restating it: if Docker is required, only
    # Docker will do.
    if os.environ.get("DETERMINEX_REQUIRE_DOCKER", "1") == "1":
        return backend == "docker"
    return True


needs_sandbox = pytest.mark.skipif(
    not _docker_ok(),
    reason="no oracle execution backend the runtime would accept "
           "(DETERMINEX_REQUIRE_DOCKER=1 permits only docker)",
)


@needs_sandbox
def test_python_syntax_error_fails(tmp_path):
    passed, _ = validate_project(_ws(tmp_path, {"bad.py": "def f(:\n"}), "python")
    assert passed is False


@needs_sandbox
def test_python_module_level_error_fails_where_compileall_passed(tmp_path):
    """THE regression this fix is for. `x = undefined_name + 1` parses perfectly, so
    compileall reported PASS. Only importing the module reveals it."""
    ws = _ws(tmp_path, {"bad.py": "x = undefined_name + 1\n"})
    passed, msg = validate_project(ws, "python")
    assert passed is False, "a module-level NameError was reported as verified"
    assert "IMPORT FAILURES" in msg or "NameError" in msg


@needs_sandbox
def test_python_valid_code_with_no_tests_passes(tmp_path):
    """ "No tests" is NOT a failure. A greenfield step legitimately ships none, and
    failing it would be the un-actionable "fails for no reason" this project forbids."""
    passed, _ = validate_project(_ws(tmp_path, {"ok.py": ADD_OK}), "python")
    assert passed is True


@needs_sandbox
def test_python_runs_shipped_tests_and_a_failing_one_fails(tmp_path):
    """The strongest stage: real behaviour. add() returns a - b, the test wants 5."""
    ws = _ws(tmp_path, {"ok.py": ADD_WRONG, "test_ok.py": TEST_ADD})
    passed, _ = validate_project(ws, "python")
    assert passed is False, "a failing unittest was reported as verified"


@needs_sandbox
def test_python_passing_tests_pass(tmp_path):
    ws = _ws(tmp_path, {"ok.py": ADD_OK, "test_ok.py": TEST_ADD})
    passed, _ = validate_project(ws, "python")
    assert passed is True


# ── typescript, once it stopped being the lenient-pass example ────────────────


def test_typescript_catches_a_type_error(tmp_path):
    """The point of the image. Before it existed this exact file returned PASS."""
    ws = _ws(tmp_path, {"bad.ts": 'const x: number = "not a number";\n'})
    passed, out = validate_project(ws, "typescript")
    assert passed is False
    assert "TS2322" in out, out[:200]


def test_typescript_accepts_clean_source(tmp_path):
    """The other half: a fail-closed oracle that fails on everything is no oracle."""
    ws = _ws(tmp_path, {"ok.ts": "export const add = (a: number, b: number): number => a + b;\n"})
    passed, out = validate_project(ws, "typescript")
    assert passed is True, out[:300]


def test_typescript_error_paths_are_relative_to_the_workspace(tmp_path):
    """Regression. The first working version of this oracle passed
    `--project /determinex-tsconfig.json`, and tsconfig include-globs resolve against the
    CONFIG's directory -- so tsc walked the container root and reached the mounted sources
    sideways through /proc, reporting real type errors at `../proc/1/cwd/bad.ts`.

    The errors were correct and the paths were useless, which is a bad failure mode
    precisely because the tests still passed: the retry loop's feedback injection has to
    map an error back to a file it can open, and it silently could not."""
    ws = _ws(tmp_path, {"bad.ts": "const n: number = notDefinedAnywhere;\n"})
    _passed, out = validate_project(ws, "typescript")
    assert "bad.ts(" in out, out[:200]
    assert "/proc/" not in out, f"path escaped the workspace: {out[:200]}"


def test_a_language_alias_resolves_to_the_same_image(tmp_path):
    """lang="ts" missed the _ORACLE_IMAGES lookup and fell through to the generic default
    image, where `tsc` does not exist -- so a MISSING ORACLE reported itself as a compile
    failure. That is the one error an oracle must never make, because it is
    indistinguishable from the code under test being wrong."""
    ws = _ws(tmp_path, {"ok.ts": "export const n: number = 1;\n"})
    assert validate_project(ws, "ts")[0] is True


# ── the empty workspace, which every oracle must refuse ──────────────────────


@pytest.mark.parametrize(
    "lang,name,src",
    [
        ("python", "m.py", "x = 1\n"),
        ("typescript", "m.ts", "export const n: number = 1;\n"),
    ],
)
def test_an_empty_workspace_is_not_verified(tmp_path, lang, name, src):
    """`compileall` over zero files exits 0. So did the importer, and so did unittest
    discovery -- so a Python workspace containing no Python returned PASS and the WAL
    recorded that step as verified. A builder step whose patch was malformed, or that
    wrote outside the path the step declared, lands here directly.

    Both halves matter: refusing empty is only correct if the same oracle still accepts
    the same tree the moment one real source file appears in it."""
    empty = tmp_path / "empty"
    empty.mkdir()
    passed, msg = validate_project(empty, lang)
    assert passed is False, f"{lang} verified an empty workspace"
    assert "nothing to verify" in msg

    (empty / name).write_text(src, encoding="utf-8")
    assert validate_project(empty, lang)[0] is True, f"{lang} now rejects real source"


def test_vendored_sources_do_not_satisfy_the_python_source_check(tmp_path):
    """The has-sources check has to look for the STEP's output. A .venv full of
    site-packages .py files would otherwise satisfy it and hand back the very
    empty-workspace pass it exists to prevent."""
    ws = tmp_path / "vendored"
    (ws / ".venv" / "lib" / "site-packages").mkdir(parents=True)
    (ws / ".venv" / "lib" / "site-packages" / "dep.py").write_text("x = 1\n", encoding="utf-8")
    passed, msg = validate_project(ws, "python")
    assert passed is False
    assert "nothing to verify" in msg
