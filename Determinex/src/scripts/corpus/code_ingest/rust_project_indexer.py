"""
Rust project indexer.

Parses Cargo.toml (single-crate or workspace) and produces a RustProject
describing the project's structure, build targets, and metadata.

No external dependencies — uses stdlib re + string parsing only.
Requires no Cargo on PATH; purely static analysis of the manifest.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class RustTarget:
    kind: str  # "bin" | "lib" | "test" | "bench" | "example"
    name: str
    path: str = ""


@dataclass
class RustProject:
    root: Path
    manifest_path: Path
    package_name: str
    edition: str  # "2015" | "2018" | "2021" | "2024"
    is_workspace: bool
    workspace_members: list[str] = field(default_factory=list)
    targets: list[RustTarget] = field(default_factory=list)
    has_build_script: bool = False  # build.rs present
    features: list[str] = field(default_factory=list)
    test_dirs: list[str] = field(default_factory=list)
    license_expression: str = ""  # from Cargo.toml [package].license


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_MEMBER_RE = re.compile(r'"([^"]+)"', re.M)
_FEATURE_RE = re.compile(r"^(\w[\w-]*)\s*=", re.M)


def _find_toml_key(content: str, key: str) -> str:
    """Return value of a top-level 'key = "value"' in TOML. Empty if not found."""
    m = re.search(rf'^{re.escape(key)}\s*=\s*"([^"]*)"', content, re.M)
    return m.group(1) if m else ""


def _extract_section(content: str, header: str) -> str:
    """Return the text of a TOML section, stopping at the next section header."""
    m = re.search(rf"^\[{re.escape(header)}\](.*)$", content, re.M | re.S)
    if not m:
        return ""
    after = m.group(1)
    # Stop at next [section]
    stop = re.search(r"^\[", after, re.M)
    return after[: stop.start()] if stop else after


def _parse_workspace_members(content: str) -> list[str]:
    ws_section = _extract_section(content, "workspace")
    members_block = re.search(r"members\s*=\s*\[([^\]]*)\]", ws_section, re.S)
    if not members_block:
        return []
    return [
        m.strip().strip("\"'") for m in members_block.group(1).split(",") if m.strip().strip("\"'")
    ]


def _parse_targets(root: Path, package_name: str, content: str) -> list[RustTarget]:
    targets: list[RustTarget] = []

    if (root / "src" / "main.rs").exists():
        targets.append(RustTarget(kind="bin", name=package_name, path="src/main.rs"))
    if (root / "src" / "lib.rs").exists():
        targets.append(RustTarget(kind="lib", name=package_name, path="src/lib.rs"))

    # Explicit [[bin]] sections
    for m in re.finditer(r'\[\[bin\]\]\s+name\s*=\s*"([^"]+)"', content, re.S):
        targets.append(RustTarget(kind="bin", name=m.group(1)))

    # Explicit [[example]] sections
    for m in re.finditer(r'\[\[example\]\]\s+name\s*=\s*"([^"]+)"', content, re.S):
        targets.append(RustTarget(kind="example", name=m.group(1)))

    return targets


def _parse_features(content: str) -> list[str]:
    feat_section = _extract_section(content, "features")
    return _FEATURE_RE.findall(feat_section) if feat_section else []


def _parse_test_dirs(root: Path) -> list[str]:
    dirs = []
    for candidate in ("tests", "benches", "examples"):
        if (root / candidate).is_dir():
            dirs.append(f"{candidate}/")
    return dirs


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def index_rust_project(path: Path) -> RustProject | None:
    """
    Locate and parse the Cargo.toml at *path*.
    Returns RustProject or None if this is not a Rust project.
    """
    manifest = path / "Cargo.toml"
    if not manifest.exists():
        return None

    try:
        content = manifest.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    is_workspace = bool(re.search(r"^\[workspace\]", content, re.M))
    workspace_members = _parse_workspace_members(content) if is_workspace else []

    # For workspaces, package_name comes from [workspace] or stays empty
    package_name = _find_toml_key(content, "name") or path.name
    edition = _find_toml_key(content, "edition") or "2021"
    license_expr = _find_toml_key(content, "license")

    has_build_script = (path / "build.rs").exists()
    features = _parse_features(content)
    targets = _parse_targets(path, package_name, content)
    test_dirs = _parse_test_dirs(path)

    return RustProject(
        root=path,
        manifest_path=manifest,
        package_name=package_name,
        edition=edition,
        is_workspace=is_workspace,
        workspace_members=workspace_members,
        targets=targets,
        has_build_script=has_build_script,
        features=features,
        test_dirs=test_dirs,
        license_expression=license_expr,
    )
