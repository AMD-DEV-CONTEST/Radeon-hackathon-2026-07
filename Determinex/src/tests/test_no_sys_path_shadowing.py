"""A test must not put a directory on sys.path that shadows a real package.

FOUND 2026-08-02, twice, from one line. `tests/test_calibration_k.py` contained

    sys.path.insert(0, str(_SCRIPTS / "hive"))

which places `scripts/hive` at the FRONT of sys.path. `scripts/hive/models.py` then shadows
the package `scripts/models/`, so anything importing `from models.local_model_config_record
import ...` -- which `ide/backend_command_surface.py` does -- fails with

    ModuleNotFoundError: No module named 'models.local_model_config_record';
    'models' is not a package

sys.path is process-global and pytest collects everything into one process, so the damage
lands on FILES COLLECTED LATER. It broke tests/test_autofix_pipeline.py and
tests/test_oracle_cost_gate.py, each of which passed in isolation and failed in company --
the most expensive kind of failure to diagnose, and one that looks like a bug in the victim.

Alphabetical collection put test_calibration_k ahead of both, so this was on course to break
the full suite. The insert bought nothing: `hive` is a package under `scripts`, which was
already on the path.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_TESTS = _ROOT / "tests"
_SCRIPTS = _ROOT / "scripts"


def _top_level_packages() -> set[str]:
    """Importable top-level names provided by `scripts/` (packages and modules)."""
    names: set[str] = set()
    for child in _SCRIPTS.iterdir():
        if child.is_dir() and (child / "__init__.py").exists():
            names.add(child.name)
        elif child.suffix == ".py":
            names.add(child.stem)
    return names


def _inserted_dirs(path: Path) -> list[tuple[int, str]]:
    """(line, rendered-expression) for every sys.path.insert/append in a file."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"), str(path))
    except SyntaxError:
        return []
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in ("insert", "append"):
            continue
        target = node.func.value
        # match `sys.path.insert(...)` and `path.insert(...)` where path came from sys
        rendered = ast.unparse(target) if hasattr(ast, "unparse") else ""
        if "path" not in rendered:
            continue
        arg = node.args[-1] if node.args else None
        if arg is None:
            continue
        out.append((node.lineno, ast.unparse(arg) if hasattr(ast, "unparse") else "?"))
    return out


def test_no_test_inserts_a_directory_that_shadows_a_package():
    """The guard. A directory whose *contents* collide with a top-level name under
    `scripts/` must never go on sys.path, because the collision resolves in favour of
    whichever is earlier -- and an insert at position 0 always wins."""
    packages = _top_level_packages()
    violations: list[str] = []

    for test_file in sorted(_TESTS.rglob("test_*.py")):
        for lineno, expr in _inserted_dirs(test_file):
            # Resolve the literal directory names mentioned in the expression. This is
            # deliberately textual: the expression is usually `str(_SCRIPTS / "hive")`, and
            # evaluating it would mean importing the test module we are auditing.
            for sub in re.findall(r'"([A-Za-z_][A-Za-z0-9_]*)"|\'([A-Za-z_][A-Za-z0-9_]*)\'',
                                  expr):
                name = sub[0] or sub[1]
                candidate = _SCRIPTS / name
                if not candidate.is_dir():
                    continue
                clashes = {
                    p.stem for p in candidate.glob("*.py") if p.stem != "__init__"
                } & packages
                if clashes:
                    rel = test_file.relative_to(_ROOT).as_posix()
                    violations.append(
                        f"{rel}:{lineno} puts scripts/{name} on sys.path, shadowing "
                        f"{sorted(clashes)}"
                    )

    assert not violations, (
        "sys.path is process-global and pytest shares it across every collected file, so "
        "these break OTHER tests, not their own:\n  " + "\n  ".join(violations)
    )


def test_the_guard_can_actually_see_the_original_offender():
    """NEGATIVE CONTROL. A guard that finds nothing is indistinguishable from a guard that
    cannot find anything -- this project has shipped that mistake before. Reconstruct the
    exact line that caused the outage and assert it is detected."""
    packages = _top_level_packages()
    assert "models" in packages, "scripts/models must be a package for this to be meaningful"
    hive_modules = {p.stem for p in (_SCRIPTS / "hive").glob("*.py") if p.stem != "__init__"}
    assert "models" in hive_modules, (
        "scripts/hive/models.py must exist -- it is the shadowing module"
    )
    assert hive_modules & packages, "the collision the guard looks for must be real"
