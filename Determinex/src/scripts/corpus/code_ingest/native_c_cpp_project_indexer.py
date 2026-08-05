"""
Native C/C++ project indexer.

Detects Make/CMake/Meson/autotools style projects and records enough structure
for the verified repair factory. This is static analysis only; it never runs
configure, make, cmake, or compiler commands.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class NativeProject:
    root: Path
    build_system: str
    languages: list[str] = field(default_factory=list)
    source_files: list[str] = field(default_factory=list)
    header_files: list[str] = field(default_factory=list)
    test_dirs: list[str] = field(default_factory=list)
    has_makefile: bool = False
    has_cmake: bool = False
    has_configure: bool = False
    has_meson: bool = False
    has_compile_commands: bool = False
    license_expression: str = ""


_C_EXTS = {".c", ".h"}
_CPP_EXTS = {".cc", ".cpp", ".cxx", ".hpp", ".hh", ".hxx"}


def _safe_read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


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


def _test_dirs(root: Path) -> list[str]:
    names = ("test", "tests", "unit", "unittest", "integration")
    return [name + "/" for name in names if (root / name).is_dir()]


def _build_system(root: Path) -> str:
    if (root / "CMakeLists.txt").is_file():
        return "cmake"
    if (root / "meson.build").is_file():
        return "meson"
    if (root / "configure").is_file() or (root / "configure.ac").is_file():
        return "autotools"
    if (root / "Makefile").is_file() or (root / "makefile").is_file():
        return "make"
    return "unknown"


def index_native_project(path: Path) -> NativeProject | None:
    sources: list[str] = []
    headers: list[str] = []
    languages: set[str] = set()

    for p in path.rglob("*"):
        if not p.is_file():
            continue
        rel = str(p.relative_to(path)).replace("\\", "/")
        if rel.startswith((".git/", "build/", "cmake-build-", "vendor/")):
            continue
        ext = p.suffix.lower()
        if ext in _C_EXTS:
            if ext == ".c":
                sources.append(rel)
            else:
                headers.append(rel)
            languages.add("c")
        elif ext in _CPP_EXTS:
            if ext in {".cc", ".cpp", ".cxx"}:
                sources.append(rel)
            else:
                headers.append(rel)
            languages.add("cpp")

    has_build_file = any(
        (
            (path / "Makefile").is_file(),
            (path / "makefile").is_file(),
            (path / "CMakeLists.txt").is_file(),
            (path / "meson.build").is_file(),
            (path / "configure").is_file(),
            (path / "configure.ac").is_file(),
        )
    )
    if not sources and not has_build_file:
        return None

    return NativeProject(
        root=path,
        build_system=_build_system(path),
        languages=sorted(languages),
        source_files=sorted(sources),
        header_files=sorted(headers),
        test_dirs=_test_dirs(path),
        has_makefile=(path / "Makefile").is_file() or (path / "makefile").is_file(),
        has_cmake=(path / "CMakeLists.txt").is_file(),
        has_configure=(path / "configure").is_file() or (path / "configure.ac").is_file(),
        has_meson=(path / "meson.build").is_file(),
        has_compile_commands=(path / "compile_commands.json").is_file(),
        license_expression=_license_hint(path),
    )
