"""The `determinex` console script must be reachable from an INSTALL, not just a checkout.

`[project.scripts]` declares `determinex = "scripts.determinex_cli:main"`, so a built wheel has to
contain a `scripts` package or the command fails at import — and every user-facing instruction in
the README is written as `determinex <cmd>`.

That works today, but it works by way of a DEFAULT nobody asserts. `scripts/` has no `__init__.py`,
so it is an implicit namespace package: `find_packages()` does not see it (measured — it returns
only `determinex_trainer`), and `find_namespace_packages()` does. setuptools' pyproject discovery
enables namespaces by default, which is the only reason `determinex.egg-info/top_level.txt` lists
`scripts` at all. Set `namespaces = false` under `[tool.setuptools.packages.find]`, or narrow
`include`, and the wheel silently ships without the module its own console script points at. The
checkout would keep working the whole time, because the repo root is on `sys.path` there.

Found 2026-07-31 while adding `determinex build` and checking whether the README's `determinex
build --idea ...` was a claim I could actually make. Same shape as the rest of tonight's defects:
a thing that holds for a reason nothing states.

Deliberately asserts on CONFIG rather than calling `find_namespace_packages()`: that call takes
~25 minutes on this ~10 GiB checkout, which is not a unit test.
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = REPO_ROOT / "pyproject.toml"


@pytest.fixture(scope="module")
def pyproject() -> dict:
    if not PYPROJECT.is_file():
        pytest.skip("pyproject.toml absent")
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))


def _console_scripts(pyproject: dict) -> dict[str, str]:
    scripts = (pyproject.get("project") or {}).get("scripts") or {}
    assert scripts, "pyproject declares no [project.scripts]"
    return scripts


def _find_config(pyproject: dict) -> dict:
    tool = (pyproject.get("tool") or {}).get("setuptools") or {}
    return (tool.get("packages") or {}).get("find") or {}


class TestTheEntryPointModuleIsShipped:
    def test_the_determinex_command_is_declared(self, pyproject: dict) -> None:
        assert "determinex" in _console_scripts(pyproject), (
            "the README instructs users to run `determinex`; it must be a console script"
        )

    def test_every_console_script_target_module_exists_on_disk(self, pyproject: dict) -> None:
        for name, target in _console_scripts(pyproject).items():
            module_path, _, attr = target.partition(":")
            assert attr, f"{name}: entry point {target!r} names no callable"
            candidate = REPO_ROOT / Path(*module_path.split("."))
            assert (
                candidate.with_suffix(".py").is_file() or (candidate / "__init__.py").is_file()
            ), f"{name}: entry point module {module_path!r} does not exist"

    def test_every_console_script_root_package_is_covered_by_the_include_patterns(
        self, pyproject: dict
    ) -> None:
        """A root package outside `include` is simply not in the wheel."""
        find = _find_config(pyproject)
        include = find.get("include")
        if include is None:
            pytest.skip("no explicit include list; setuptools discovers everything")
        for name, target in _console_scripts(pyproject).items():
            root = target.partition(":")[0].split(".")[0]
            covered = any(
                root == pattern or (pattern.endswith("*") and root.startswith(pattern[:-1]))
                for pattern in include
            )
            assert covered, (
                f"{name}: root package {root!r} matches none of include={include}, so a built "
                "wheel would not contain the module this console script points at"
            )

    def test_namespace_discovery_is_not_disabled(self, pyproject: dict) -> None:
        """The load-bearing default.

        Every console-script root package here is an implicit namespace package (no __init__.py),
        so `namespaces = false` would drop it from the wheel while the checkout kept working.
        """
        find = _find_config(pyproject)
        assert find.get("namespaces", True) is not False, (
            "namespaces discovery is disabled, but the console-script package(s) have no "
            "__init__.py — a built wheel would not contain them"
        )

    def test_the_namespace_assumption_is_the_one_actually_in_play(self, pyproject: dict) -> None:
        """Not a tautology: assert these packages really do lack __init__.py.

        If someone adds `scripts/__init__.py`, the test above stops being load-bearing and this
        one says so rather than silently guarding nothing.
        """
        roots = {t.partition(":")[0].split(".")[0] for t in _console_scripts(pyproject).values()}
        namespace_roots = [r for r in roots if not (REPO_ROOT / r / "__init__.py").is_file()]
        assert namespace_roots, (
            "every console-script root package now has __init__.py, so namespace discovery is no "
            "longer load-bearing — simplify or delete test_namespace_discovery_is_not_disabled"
        )


class TestTheEntryPointResolvesTheWayAConsoleScriptResolvesIt:
    def test_the_installed_entry_point_loads_and_is_callable(self) -> None:
        """`ep.load()` is exactly what a generated console script does.

        This is the check that would have caught a broken entry point regardless of packaging --
        it does not care how the module got onto sys.path, only that the declared target resolves.
        """
        import importlib.metadata as md

        try:
            dist = md.distribution("determinex")
        except md.PackageNotFoundError:
            pytest.skip("determinex is not installed in this environment")
        matches = [e for e in dist.entry_points if e.name == "determinex"]
        assert matches, "the installed distribution declares no `determinex` entry point"
        loaded = matches[0].load()
        assert callable(loaded)

    def test_the_declared_target_matches_what_is_installed(self, pyproject: dict) -> None:
        """Catches an install that has drifted from the source tree's declaration."""
        import importlib.metadata as md

        try:
            dist = md.distribution("determinex")
        except md.PackageNotFoundError:
            pytest.skip("determinex is not installed in this environment")
        installed = {e.name: e.value for e in dist.entry_points}
        if "determinex" not in installed:
            pytest.skip("installed distribution predates the console script")
        assert installed["determinex"] == _console_scripts(pyproject)["determinex"]


def test_python_is_new_enough_for_tomllib() -> None:
    """tomllib is stdlib from 3.11; pyproject pins 3.11 as the floor."""
    assert sys.version_info >= (3, 11)
