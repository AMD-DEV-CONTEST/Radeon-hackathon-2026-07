"""Skill registry — list and run selectable development skills."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.skills.base import Skill, SkillResult
from src.skills.catalog import ALL_SKILLS


class SkillRegistry:
    def __init__(self, output_root: Path) -> None:
        self.output_root = Path(output_root)
        self.output_root.mkdir(parents=True, exist_ok=True)
        self._skills: dict[str, Skill] = {s.id: s for s in ALL_SKILLS}

    def list_skills(self) -> list[dict[str, str]]:
        return [
            {
                "id": s.id,
                "title": s.title,
                "description": s.description,
                "category": s.category,
            }
            for s in self._skills.values()
        ]

    def describe(self) -> str:
        lines = ["可选开发技能（会在磁盘生成真实项目文件）："]
        for s in self._skills.values():
            lines.append(f"- {s.id}: {s.title} — {s.description}")
        lines.append(f"输出根目录: {self.output_root}")
        return "\n".join(lines)

    def run(self, skill_id: str, params: dict[str, Any] | None = None) -> SkillResult:
        if skill_id not in self._skills:
            return SkillResult(
                skill_id=skill_id,
                title="unknown",
                project_dir=str(self.output_root),
                message=f"未知技能: {skill_id}\n{self.describe()}",
            )
        return self._skills[skill_id].run(self.output_root, params or {})

    def run_by_title(self, title_or_id: str, params: dict[str, Any] | None = None) -> SkillResult:
        raw = title_or_id.strip()
        if raw in self._skills:
            return self.run(raw, params)
        for s in self._skills.values():
            if raw == s.title or raw in s.title:
                return self.run(s.id, params)
        return self.run(raw, params)
