"""
determinex_cloak/classifier.py — Component 2: IdentifierClassifier.

AST-based private identifier extraction for Python repos.
Walks all .py files, collects every non-safe identifier, resolves
star-import holes via the tree-sitter bridge when available.
"""

from __future__ import annotations

import ast
import logging
import re
from pathlib import Path

from ._treesitter_bridge import _TS_AVAILABLE, resolve_python_star_imports

log = logging.getLogger("determinex_cloak")

_SINGLE_CHAR = re.compile(r"^[a-zA-Z_]$")
_DUNDER = re.compile(r"^__[a-zA-Z_][a-zA-Z0-9_]*__$")


class _IdentifierCollector(ast.NodeVisitor):
    """Collect all project-private identifiers from a parsed AST."""

    def __init__(self, safe: frozenset[str]) -> None:
        self.safe = safe
        self.found: set[str] = set()

    def _add(self, name: str) -> None:
        if not name:
            return
        if _SINGLE_CHAR.match(name):
            return
        if _DUNDER.match(name):
            return
        if name in self.safe:
            return
        self.found.add(name)

    def visit_Name(self, node: ast.Name) -> None:
        self._add(node.id)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._add(node.name)
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._add(node.name)
        self.generic_visit(node)

    def visit_arg(self, node: ast.arg) -> None:
        self._add(node.arg)
        self.generic_visit(node)

    def visit_Global(self, node: ast.Global) -> None:
        for n in node.names:
            self._add(n)
        self.generic_visit(node)

    def visit_Nonlocal(self, node: ast.Nonlocal) -> None:
        for n in node.names:
            self._add(n)
        self.generic_visit(node)


def _collect_star_imports(source: str) -> list[str]:
    """Return module names that have star imports in this source."""
    stars: list[str] = []
    try:
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name == "*":
                        stars.append(node.module or "?")
    except Exception:
        pass
    return stars


def build_private_identifier_set(
    repo_path: Path,
    safe_names: frozenset[str],
) -> tuple[frozenset[str], list[str]]:
    """
    Walk all .py files in repo_path.
    Returns (private_ids, star_import_warnings).
    """
    collector = _IdentifierCollector(safe_names)
    star_warnings: list[str] = []

    _SKIP_DIRS = {
        "site-packages",
        "__pycache__",
        ".tox",
        ".eggs",
        ".pyinstaller",
        "resources",
        "fixtures",
        ".cargo",
        "_vendor",
        "vendor",
    }

    py_files = [
        f
        for f in repo_path.rglob("*.py")
        if not any(part in _SKIP_DIRS for part in f.parts)
        and "build" not in [p.lower() for p in f.relative_to(repo_path).parts[:1]]
    ]

    _MAX_FILES = 400
    if len(py_files) > _MAX_FILES:
        log.info("Cloak: capping scan to %d/%d files (large repo)", _MAX_FILES, len(py_files))
        py_files = py_files[:_MAX_FILES]

    log.info("Cloak: scanning %d Python files...", len(py_files))

    for py_file in py_files:
        try:
            if py_file.stat().st_size > 200_000:
                log.debug(
                    "Cloak: skip large file %s (%d bytes)", py_file.name, py_file.stat().st_size
                )
                continue
            source = py_file.read_text(encoding="utf-8", errors="ignore")
            for mod in _collect_star_imports(source):
                rel = str(py_file.relative_to(repo_path))
                star_warnings.append(f"{rel}: from {mod} import *")
            tree = ast.parse(source, filename=str(py_file))
            collector.visit(tree)
        except SyntaxError:
            pass
        except RecursionError:
            log.debug("Cloak: skip %s: recursion limit on deep AST", py_file.name)
        except Exception as e:
            log.debug("Cloak: skip %s: %s", py_file.name, e)

    if _TS_AVAILABLE and star_warnings:
        unresolved = resolve_python_star_imports(py_files, repo_path, safe_names, collector)
        resolved_count = len(star_warnings) - len(unresolved)
        if resolved_count:
            log.info(
                "Cloak: resolved %d/%d star-import holes via AST",
                resolved_count,
                len(star_warnings),
            )
        star_warnings = unresolved

    private = frozenset(collector.found)
    log.info(
        "Cloak: %d private identifiers, %d star-import warnings", len(private), len(star_warnings)
    )
    return private, star_warnings
