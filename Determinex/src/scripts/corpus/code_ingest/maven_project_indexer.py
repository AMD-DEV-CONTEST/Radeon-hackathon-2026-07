"""
Maven project indexer — discovers and indexes Maven projects for corpus ingest.

Scans a root directory for pom.xml files, extracts project metadata
(groupId, artifactId, version, license, dependencies), and produces
an index suitable for license-gated corpus processing.
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

_MAVEN_NS = "http://maven.apache.org/POM/4.0.0"


@dataclass
class MavenProject:
    path: Path
    group_id: str
    artifact_id: str
    version: str
    packaging: str
    license_name: str
    license_url: str
    dependencies: list[dict[str, str]] = field(default_factory=list)
    modules: list[str] = field(default_factory=list)
    parent: dict[str, str] | None = None
    properties: dict[str, str] = field(default_factory=dict)

    @property
    def coordinates(self) -> str:
        return f"{self.group_id}:{self.artifact_id}:{self.version}"

    def to_dict(self) -> dict:
        return {
            "path": str(self.path),
            "coordinates": self.coordinates,
            "packaging": self.packaging,
            "license_name": self.license_name,
            "license_url": self.license_url,
            "dependency_count": len(self.dependencies),
            "has_modules": bool(self.modules),
        }


def _text(el: ET.Element | None) -> str:
    if el is None:
        return ""
    return (el.text or "").strip()


def _find(root: ET.Element, *tags: str) -> ET.Element | None:
    for tag in tags:
        # Must use 'is not None' — ET.Element with no children is falsy in boolean context
        el = root.find(f"{{{_MAVEN_NS}}}{tag}")
        if el is None:
            el = root.find(tag)
        if el is not None:
            return el
    return None


def parse_pom(pom_path: Path) -> MavenProject | None:
    try:
        tree = ET.parse(pom_path)
        root = tree.getroot()
    except (ET.ParseError, OSError) as e:
        log.warning("[maven_indexer] parse error %s: %s", pom_path, e)
        return None

    def find(*tags):
        return _find(root, *tags)

    group_id = _text(find("groupId"))
    artifact_id = _text(find("artifactId"))
    version = _text(find("version"))
    packaging = _text(find("packaging")) or "jar"

    # Parent coordinates
    parent_el = find("parent")
    parent = None
    if parent_el is not None:
        parent = {
            "groupId": _text(_find(parent_el, "groupId")),
            "artifactId": _text(_find(parent_el, "artifactId")),
            "version": _text(_find(parent_el, "version")),
        }
        if not group_id:
            group_id = parent["groupId"]
        if not version:
            version = parent["version"]

    # Licenses
    license_name = ""
    license_url = ""
    licenses_el = find("licenses")
    if licenses_el is not None:
        for lic_el in licenses_el.findall(f"{{{_MAVEN_NS}}}license") or licenses_el.findall(
            "license"
        ):
            license_name = _text(_find(lic_el, "name"))
            license_url = _text(_find(lic_el, "url"))
            break

    # Dependencies
    dependencies = []
    deps_el = find("dependencies")
    if deps_el is not None:
        for dep in deps_el.findall(f"{{{_MAVEN_NS}}}dependency") or deps_el.findall("dependency"):
            dependencies.append(
                {
                    "groupId": _text(_find(dep, "groupId")),
                    "artifactId": _text(_find(dep, "artifactId")),
                    "version": _text(_find(dep, "version")),
                    "scope": _text(_find(dep, "scope")) or "compile",
                }
            )

    # Modules (multi-module projects)
    modules = []
    modules_el = find("modules")
    if modules_el is not None:
        for mod_el in modules_el.findall(f"{{{_MAVEN_NS}}}module") or modules_el.findall("module"):
            if mod_el.text:
                modules.append(mod_el.text.strip())

    return MavenProject(
        path=pom_path,
        group_id=group_id,
        artifact_id=artifact_id,
        version=version,
        packaging=packaging,
        license_name=license_name,
        license_url=license_url,
        dependencies=dependencies,
        modules=modules,
        parent=parent,
    )


def index_directory(root: Path, max_projects: int = 500) -> list[MavenProject]:
    """Scan root recursively for pom.xml files and index all Maven projects."""
    projects = []
    for pom_path in root.rglob("pom.xml"):
        if len(projects) >= max_projects:
            break
        # Skip known build output dirs
        if any(part in ("target", "build", ".m2", "node_modules") for part in pom_path.parts):
            continue
        project = parse_pom(pom_path)
        if project:
            projects.append(project)
    log.info("[maven_indexer] indexed %d Maven projects under %s", len(projects), root)
    return projects
