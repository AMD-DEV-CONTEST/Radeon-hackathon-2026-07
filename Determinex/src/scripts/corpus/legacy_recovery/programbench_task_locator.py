from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class LocatedPath:
    path: Path | None
    matches: list[Path]
    ambiguous: bool = False


class ProgramBenchTaskLocator:
    """Locate ProgramBench task/source roots and candidate workspaces."""

    def __init__(self, roots: list[Path] | None = None) -> None:
        self.roots = [Path(root) for root in roots or []]

    def locate(self, tool: str) -> LocatedPath:
        exact_matches: list[Path] = []
        prefix_matches: list[Path] = []
        for root in self.roots:
            if not root.exists() or not root.is_dir():
                continue
            exact, prefix = _matches_under(root, tool)
            exact_matches.extend(exact)
            prefix_matches.extend(prefix)
        unique_exact = _unique_paths(exact_matches)
        if unique_exact:
            if len(unique_exact) > 1:
                return LocatedPath(None, unique_exact, True)
            return LocatedPath(unique_exact[0], unique_exact, False)
        unique = _unique_paths(prefix_matches)
        if len(unique) > 1:
            return LocatedPath(None, unique, True)
        return LocatedPath(unique[0] if unique else None, unique, False)


def _matches_under(root: Path, tool: str) -> tuple[list[Path], list[Path]]:
    names = _candidate_names(tool)
    exact: list[Path] = []
    prefix: list[Path] = []
    for name in names:
        direct = root / name
        if direct.is_dir():
            exact.append(direct)
    try:
        children = list(root.iterdir())
    except OSError:
        return exact, prefix
    for child in children:
        if not child.is_dir():
            continue
        if child.name.startswith(tool) and child.name != tool:
            prefix.append(child)
    return exact, prefix


def _candidate_names(tool: str) -> list[str]:
    tail = tool.split("__", 1)[-1]
    return [
        tool,
        tool.replace("__", "_"),
        tail,
        tail.split(".", 1)[0],
    ]


def _unique_paths(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    unique: list[Path] = []
    for path in paths:
        key = str(path.resolve())
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique
