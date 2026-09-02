"""
Gradle project indexer — discovers and indexes Gradle projects for corpus ingest.

Parses build.gradle / build.gradle.kts files to extract project metadata
(name, group, version, license, dependencies) for license-gated processing.

Note: Gradle's Groovy DSL is not formally parseable without executing it.
This indexer uses regex extraction on common patterns and is best-effort.
For authoritative metadata, use `gradle properties` at runtime.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass
class GradleProject:
    path: Path
    name: str
    group: str
    version: str
    license_expression: str  # raw text found near "license" keyword
    plugins: list[str] = field(default_factory=list)
    dependencies: list[dict[str, str]] = field(default_factory=list)
    is_kotlin_dsl: bool = False

    @property
    def coordinates(self) -> str:
        return f"{self.group}:{self.name}:{self.version}"

    def to_dict(self) -> dict:
        return {
            "path": str(self.path),
            "coordinates": self.coordinates,
            "license_expression": self.license_expression,
            "plugin_count": len(self.plugins),
            "dependency_count": len(self.dependencies),
            "is_kotlin_dsl": self.is_kotlin_dsl,
        }


_PATTERNS = {
    "group": re.compile(r"""^group\s*[=:]\s*['"]([^'"]+)['"]""", re.M),
    "version": re.compile(r"""^version\s*[=:]\s*['"]([^'"]+)['"]""", re.M),
    "name": re.compile(r"""^rootProject\.name\s*[=:]\s*['"]([^'"]+)['"]""", re.M),
    "license": re.compile(r"""(?:license|licensing).{0,80}['"]([A-Za-z0-9.\-\s]+)['"]""", re.I),
    "plugin": re.compile(r"""(?:id|plugin)\s*\(?['"]([^'"]+)['"]"""),
    "dep": re.compile(
        r"""(?:implementation|api|compile|testImplementation|runtimeOnly)\s*\(?['"]([^'"]+)['"]""",
        re.M,
    ),
}


def _extract(pattern: re.Pattern, text: str) -> str:
    m = pattern.search(text)
    return m.group(1).strip() if m else ""


def parse_build_file(build_path: Path) -> GradleProject | None:
    try:
        text = build_path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        log.warning("[gradle_indexer] read error %s: %s", build_path, e)
        return None

    is_kts = build_path.suffix == ".kts"

    # Try to get name from settings.gradle(kts) in same dir
    settings_path = build_path.parent / ("settings.gradle.kts" if is_kts else "settings.gradle")
    name = ""
    if settings_path.is_file():
        try:
            settings_text = settings_path.read_text(encoding="utf-8", errors="replace")
            name = _extract(_PATTERNS["name"], settings_text)
        except Exception:
            pass
    if not name:
        name = build_path.parent.name

    group = _extract(_PATTERNS["group"], text)
    version = _extract(_PATTERNS["version"], text)
    license_expression = _extract(_PATTERNS["license"], text)

    plugins = _PATTERNS["plugin"].findall(text)
    raw_deps = _PATTERNS["dep"].findall(text)
    dependencies = []
    for dep in raw_deps:
        parts = dep.split(":")
        if len(parts) >= 2:
            dependencies.append(
                {
                    "groupId": parts[0],
                    "artifactId": parts[1],
                    "version": parts[2] if len(parts) > 2 else "",
                }
            )

    return GradleProject(
        path=build_path,
        name=name,
        group=group,
        version=version,
        license_expression=license_expression,
        plugins=plugins,
        dependencies=dependencies,
        is_kotlin_dsl=is_kts,
    )


def index_directory(root: Path, max_projects: int = 500) -> list[GradleProject]:
    """Scan root for build.gradle / build.gradle.kts files."""
    projects = []
    for build_file in list(root.rglob("build.gradle")) + list(root.rglob("build.gradle.kts")):
        if len(projects) >= max_projects:
            break
        if any(part in ("build", ".gradle", "node_modules") for part in build_file.parts):
            continue
        project = parse_build_file(build_file)
        if project:
            projects.append(project)
    log.info("[gradle_indexer] indexed %d Gradle projects under %s", len(projects), root)
    return projects
