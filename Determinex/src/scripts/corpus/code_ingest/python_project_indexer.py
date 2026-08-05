"""
Python project indexer.

Parses pyproject.toml / setup.py / setup.cfg / pytest.ini to produce a
PythonProject describing the project's structure, test layout, and metadata.

No external dependencies — stdlib re + string parsing only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class PythonProject:
    root: Path
    package_name: str
    build_backend: str  # "setuptools" | "poetry" | "hatch" | "flit" | "pdm" | "unknown"
    has_pyproject_toml: bool
    has_setup_py: bool
    has_setup_cfg: bool
    test_runner: str  # "pytest" | "unittest" | "tox" | "nox" | "unknown"
    src_layout: bool  # True if src/<pkg>/ layout detected
    test_dirs: list[str] = field(default_factory=list)
    python_files: list[str] = field(default_factory=list)
    license_expression: str = ""
    setup_files: list[str] = field(default_factory=list)  # files that run on install


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _toml_str(content: str, key: str) -> str:
    """Return value of 'key = "value"' in TOML. Empty if not found."""
    m = re.search(rf'^{re.escape(key)}\s*=\s*"([^"]*)"', content, re.M)
    return m.group(1) if m else ""


def _detect_test_runner(root: Path, content: str) -> str:
    if (root / "pytest.ini").exists() or (root / "conftest.py").exists():
        return "pytest"
    if "pytest" in content:
        return "pytest"
    if (root / "tox.ini").exists():
        return "tox"
    if (root / "noxfile.py").exists():
        return "nox"
    if (root / "tests").is_dir():
        return "pytest"
    return "unittest"


def _detect_build_backend(content: str) -> str:
    if "poetry-core" in content or "poetry.core" in content:
        return "poetry"
    if "hatchling" in content or "hatch" in content:
        return "hatch"
    if "flit" in content:
        return "flit"
    if "pdm" in content:
        return "pdm"
    if "setuptools" in content or "setup.py" in content:
        return "setuptools"
    return "unknown"


def _collect_test_dirs(root: Path) -> list[str]:
    candidates = ("tests", "test", "src/tests", "spec")
    return [d + "/" for d in candidates if (root / d).is_dir()]


def _detect_license(root: Path) -> str:
    for name in ("LICENSE", "LICENSE.txt", "LICENSE.md", "LICENCE"):
        p = root / name
        if p.exists():
            try:
                first = p.read_text(encoding="utf-8", errors="replace")[:200]
                if re.search(r"MIT", first, re.I):
                    return "MIT"
                if re.search(r"Apache", first, re.I):
                    return "Apache-2.0"
                if re.search(r"BSD", first, re.I):
                    return "BSD"
                if re.search(r"GPL", first, re.I):
                    return "GPL"
            except OSError:
                pass
    return ""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def index_python_project(path: Path) -> PythonProject | None:
    """
    Detect and describe a Python project at *path*.
    Returns None if this is not a recognisable Python project.
    """
    has_pyproject = (path / "pyproject.toml").exists()
    has_setup_py = (path / "setup.py").exists()
    has_setup_cfg = (path / "setup.cfg").exists()

    if not (has_pyproject or has_setup_py or has_setup_cfg):
        # Fall back: any .py files + tests/ qualifies
        if not list(path.glob("*.py")) and not (path / "tests").is_dir():
            return None

    content = ""
    if has_pyproject:
        try:
            content = (path / "pyproject.toml").read_text(encoding="utf-8", errors="replace")
        except OSError:
            pass

    if has_setup_cfg and not content:
        try:
            content = (path / "setup.cfg").read_text(encoding="utf-8", errors="replace")
        except OSError:
            pass

    package_name = _toml_str(content, "name") or path.name
    build_backend = _detect_build_backend(content)
    test_runner = _detect_test_runner(path, content)
    test_dirs = _collect_test_dirs(path)
    src_layout = (path / "src").is_dir() and any((path / "src").iterdir())
    license_expr = _detect_license(path)

    setup_files: list[str] = []
    if has_setup_py:
        setup_files.append("setup.py")
    if has_pyproject:
        setup_files.append("pyproject.toml")

    return PythonProject(
        root=path,
        package_name=package_name,
        build_backend=build_backend,
        has_pyproject_toml=has_pyproject,
        has_setup_py=has_setup_py,
        has_setup_cfg=has_setup_cfg,
        test_runner=test_runner,
        src_layout=src_layout,
        test_dirs=test_dirs,
        license_expression=license_expr,
        setup_files=setup_files,
    )
