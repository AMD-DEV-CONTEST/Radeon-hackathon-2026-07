"""
TypeScript/JavaScript npm project indexer.

Detects package-manager layout, TypeScript config, test tools, frontend
framework hints, source directories, and package metadata without running npm.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class NpmProject:
    root: Path
    package_name: str
    package_manager: str
    has_package_json: bool
    has_tsconfig: bool
    has_typescript: bool
    scripts: dict[str, str] = field(default_factory=dict)
    dependencies: list[str] = field(default_factory=list)
    dev_dependencies: list[str] = field(default_factory=list)
    source_dirs: list[str] = field(default_factory=list)
    component_dirs: list[str] = field(default_factory=list)
    test_tools: list[str] = field(default_factory=list)
    framework_hints: list[str] = field(default_factory=list)
    license_expression: str = ""


def _safe_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}


def _package_manager(root: Path) -> str:
    if (root / "pnpm-lock.yaml").is_file():
        return "pnpm"
    if (root / "yarn.lock").is_file():
        return "yarn"
    if (root / "package-lock.json").is_file():
        return "npm"
    return "npm"


def _dirs(root: Path, names: tuple[str, ...]) -> list[str]:
    return [name + "/" for name in names if (root / name).is_dir()]


def _test_tools(pkg: dict[str, Any], root: Path) -> list[str]:
    deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
    tools: set[str] = set()
    for name in ("vitest", "jest", "playwright", "mocha", "cypress"):
        if name in deps:
            tools.add(name)
    if (root / "vitest.config.ts").is_file() or (root / "vitest.config.js").is_file():
        tools.add("vitest")
    if (root / "jest.config.js").is_file() or (root / "jest.config.ts").is_file():
        tools.add("jest")
    if (root / "playwright.config.ts").is_file() or (root / "playwright.config.js").is_file():
        tools.add("playwright")
    return sorted(tools)


def _framework_hints(pkg: dict[str, Any], root: Path) -> list[str]:
    deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
    hints: set[str] = set()
    for name in ("react", "vue", "svelte", "next", "vite", "express"):
        if name in deps:
            hints.add(name)
    for name, marker in (("next", "next.config.js"), ("vite", "vite.config.ts")):
        if (root / marker).is_file():
            hints.add(name)
    return sorted(hints)


def index_npm_project(path: Path) -> NpmProject | None:
    package_json = path / "package.json"
    if not package_json.is_file():
        return None
    pkg = _safe_json(package_json)
    if not pkg:
        return None
    deps = pkg.get("dependencies", {}) or {}
    dev_deps = pkg.get("devDependencies", {}) or {}
    has_tsconfig = (path / "tsconfig.json").is_file()
    has_typescript = has_tsconfig or "typescript" in deps or "typescript" in dev_deps
    return NpmProject(
        root=path,
        package_name=pkg.get("name") or path.name,
        package_manager=_package_manager(path),
        has_package_json=True,
        has_tsconfig=has_tsconfig,
        has_typescript=has_typescript,
        scripts=dict(pkg.get("scripts", {}) or {}),
        dependencies=sorted(deps.keys()),
        dev_dependencies=sorted(dev_deps.keys()),
        source_dirs=_dirs(path, ("src", "app", "pages", "lib")),
        component_dirs=_dirs(path, ("components", "src/components", "app/components")),
        test_tools=_test_tools(pkg, path),
        framework_hints=_framework_hints(pkg, path),
        license_expression=pkg.get("license") or "",
    )
