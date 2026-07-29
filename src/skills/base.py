"""Skill base types — selectable capabilities that write real files/projects."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class SkillResult:
    skill_id: str
    title: str
    project_dir: str
    files_written: list[str] = field(default_factory=list)
    message: str = ""

    def as_text(self) -> str:
        lines = [
            f"【技能】{self.title} ({self.skill_id})",
            f"【项目目录】{self.project_dir}",
            f"【生成文件】{len(self.files_written)} 个：",
        ]
        for p in self.files_written:
            lines.append(f"  - {p}")
        if self.message:
            lines.append(self.message)
        return "\n".join(lines)


class Skill:
    id: str = "base"
    title: str = "Base"
    description: str = ""
    category: str = "general"

    def run(self, root: Path, params: dict[str, Any] | None = None) -> SkillResult:
        raise NotImplementedError


def write_tree(base: Path, tree: dict[str, str]) -> list[str]:
    """Write relative path -> content mapping under base. Returns written paths."""
    from src.security.paths import is_under

    written: list[str] = []
    base = base.resolve()
    base.mkdir(parents=True, exist_ok=True)
    for rel, content in tree.items():
        rel_norm = str(rel).replace("\\", "/").lstrip("/")
        if ".." in Path(rel_norm).parts:
            continue
        path = (base / rel_norm).resolve()
        if not is_under(path, base):
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        written.append(str(path))
    return written
