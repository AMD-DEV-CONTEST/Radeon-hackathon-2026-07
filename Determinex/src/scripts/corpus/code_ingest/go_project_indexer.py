"""
Go project indexer.

Detects module-based Go projects and records the structure needed by the
repair factory. This is intentionally static: it does not require Go on PATH.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class GoProject:
    root: Path
    module_path: str
    go_version: str
    has_go_mod: bool
    has_go_sum: bool
    cmd_dirs: list[str] = field(default_factory=list)
    internal_dirs: list[str] = field(default_factory=list)
    pkg_dirs: list[str] = field(default_factory=list)
    packages: list[str] = field(default_factory=list)
    test_files: list[str] = field(default_factory=list)
    build_tags: list[str] = field(default_factory=list)
    generated_files: list[str] = field(default_factory=list)
    license_expression: str = ""


def _safe_read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _module_path(go_mod: str) -> str:
    m = re.search(r"^module\s+(\S+)", go_mod, re.M)
    return m.group(1) if m else ""


def _go_version(go_mod: str) -> str:
    m = re.search(r"^go\s+([0-9.]+)", go_mod, re.M)
    return m.group(1) if m else ""


def _rel_dirs(root: Path, name: str) -> list[str]:
    base = root / name
    if not base.is_dir():
        return []
    return [
        str(p.relative_to(root)).replace("\\", "/") + "/" for p in base.rglob("*") if p.is_dir()
    ] or [name + "/"]


def _license_hint(root: Path) -> str:
    for name in ("LICENSE", "LICENSE.txt", "LICENSE.md", "LICENCE", "COPYING"):
        p = root / name
        if not p.is_file():
            continue
        text = _safe_read(p)[:300]
        if re.search(r"\bMIT\b", text, re.I):
            return "MIT"
        if re.search(r"Apache", text, re.I):
            return "Apache-2.0"
        if re.search(r"\bBSD\b", text, re.I):
            return "BSD"
        if re.search(r"\bGPL\b", text, re.I):
            return "GPL"
    return ""


def index_go_project(path: Path) -> GoProject | None:
    go_mod_path = path / "go.mod"
    if not go_mod_path.is_file():
        return None

    go_mod = _safe_read(go_mod_path)
    module = _module_path(go_mod)
    if not module:
        return None

    test_files: list[str] = []
    build_tags: set[str] = set()
    generated_files: list[str] = []
    packages: set[str] = set()

    for go_file in path.rglob("*.go"):
        rel = str(go_file.relative_to(path)).replace("\\", "/")
        if rel.startswith(("vendor/", ".git/")):
            continue
        text = _safe_read(go_file)
        pkg = re.search(r"^package\s+([A-Za-z_]\w*)", text, re.M)
        if pkg:
            packages.add(pkg.group(1))
        if rel.endswith("_test.go"):
            test_files.append(rel)
        for m in re.finditer(r"^//go:build\s+(.+)$", text, re.M):
            build_tags.add(m.group(1).strip())
        if "Code generated" in text or "DO NOT EDIT" in text:
            generated_files.append(rel)

    return GoProject(
        root=path,
        module_path=module,
        go_version=_go_version(go_mod),
        has_go_mod=True,
        has_go_sum=(path / "go.sum").is_file(),
        cmd_dirs=_rel_dirs(path, "cmd"),
        internal_dirs=_rel_dirs(path, "internal"),
        pkg_dirs=_rel_dirs(path, "pkg"),
        packages=sorted(packages),
        test_files=sorted(test_files),
        build_tags=sorted(build_tags),
        generated_files=sorted(generated_files),
        license_expression=_license_hint(path),
    )
