from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class ReplayWorkspace:
    candidate: dict[str, Any]
    workspace_path: Path
    manifest_path: Path
    hydrated: bool
    reason: str = ""


class ReplayWorkspaceBuilder:
    """Resolve a selected legacy replay candidate to a local workspace.

    The builder is intentionally conservative. It only reports a hydrated
    workspace when an existing directory can be found under one of the supplied
    roots. It does not clone or download during replay promotion.
    """

    def __init__(self, roots: list[Path] | None = None) -> None:
        self.roots = [Path(root) for root in roots or []]

    def build(self, candidate: dict[str, Any], manifest_dir: Path) -> ReplayWorkspace:
        tool = str(candidate.get("tool") or "")
        manifest_path = manifest_dir / f"{_safe_name(tool or 'unknown')}_replay_manifest.json"
        if not tool:
            return ReplayWorkspace(candidate, Path(), manifest_path, False, "missing_tool")
        if not _candidate_hash_valid(candidate):
            return ReplayWorkspace(
                candidate, Path(), manifest_path, False, "missing_candidate_hash"
            )

        workspace = self._find_workspace(tool)
        if workspace is None:
            return ReplayWorkspace(candidate, Path(), manifest_path, False, "workspace_not_found")
        return ReplayWorkspace(candidate, workspace, manifest_path, True, "")

    def _find_workspace(self, tool: str) -> Path | None:
        names = [tool, tool.replace("__", "_"), tool.split("__", 1)[-1]]
        for root in self.roots:
            for name in names:
                direct = root / name
                if direct.is_dir():
                    return direct
            if root.is_dir():
                for child in root.iterdir():
                    if child.is_dir() and (child.name == tool or child.name.startswith(tool)):
                        return child
        return None


def _candidate_hash_valid(candidate: dict[str, Any]) -> bool:
    return bool(
        candidate.get("legacy_row_hash")
        or candidate.get("candidate_hash")
        or candidate.get("duplicate_cluster_id")
    )


def _safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-._" else "_" for ch in value)[:120] or "unknown"
