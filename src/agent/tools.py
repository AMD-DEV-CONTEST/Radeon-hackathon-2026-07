from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from src.memory.memory import SessionMemory
from src.privacy.guard import redact_text
from src.rag.store import VectorStore
from src.security.paths import safe_join


@dataclass
class ToolResult:
    name: str
    output: str


class ToolRegistry:
    def __init__(
        self,
        store: VectorStore,
        memory: SessionMemory,
        upload_dir: Path,
        skill_registry: Any | None = None,
    ) -> None:
        self.store = store
        self.memory = memory
        self.upload_dir = upload_dir
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.skills = skill_registry
        self._tools: dict[str, Callable[..., str]] = {
            "kb_search": self.kb_search,
            "list_files": self.list_files,
            "read_file": self.read_file,
            "write_note": self.write_note,
            "save_fact": self.save_fact,
            "recall_memory": self.recall_memory,
            "kb_stats": self.kb_stats,
            "list_workflows": self.list_workflows,
            "run_workflow": self.run_workflow_tool,
            "build_workflow": self.build_workflow_tool,
            "export_workflow": self.export_workflow_tool,
            "build_app_config": self.build_app_config_tool,
            "parse_image": self.parse_image,
            "list_skills": self.list_skills,
            "run_skill": self.run_skill,
        }

    def names(self) -> list[str]:
        return sorted(self._tools.keys())

    def describe(self) -> str:
        return (
            "Available tools (call one per step using JSON):\n"
            '- {"tool":"kb_search","args":{"query":"..."}}\n'
            '- {"tool":"list_files","args":{}}\n'
            '- {"tool":"read_file","args":{"name":"file.md"}}\n'
            '- {"tool":"write_note","args":{"note":"..."}}\n'
            '- {"tool":"save_fact","args":{"fact":"..."}}\n'
            '- {"tool":"recall_memory","args":{}}\n'
            '- {"tool":"kb_stats","args":{}}\n'
            '- {"tool":"list_workflows","args":{}}\n'
            '- {"tool":"run_workflow","args":{"workflow_id":"leave_request|it_onboarding|..."}}\n'
            '- {"tool":"build_workflow","args":{"requirement":"自然语言需求"}}\n'
            '- {"tool":"export_workflow","args":{"workflow_id":"...","formats":"yaml,json,dify,langchain"}}\n'
            '- {"tool":"build_app_config","args":{"app":"productivity|enterprise|rag|developer|multi","requirement":"..."}}\n'
            '- {"tool":"parse_image","args":{"name":"photo.png"}}\n'
            '- {"tool":"list_skills","args":{}}\n'
            '- {"tool":"run_skill","args":{"skill_id":"...","name":"optional_project_name"}}\n'
            'When finished, answer with: {"final":"your answer"}'
        )

    def run(self, name: str, args: dict) -> ToolResult:
        if name not in self._tools:
            return ToolResult(name=name, output=f"Unknown tool: {name}")
        try:
            output = self._tools[name](**(args or {}))
        except TypeError as exc:
            output = f"Bad arguments for {name}: {exc}"
        except Exception as exc:  # noqa: BLE001
            output = f"Tool error ({name}): {exc}"
        safe, _ = redact_text(str(output))
        return ToolResult(name=name, output=safe)

    def kb_search(self, query: str) -> str:
        hits = self.store.search(query)
        if not hits:
            return "No documents in knowledge base. Please ingest sample docs or upload files."
        lines = []
        for i, h in enumerate(hits, 1):
            text, _ = redact_text(h.text)
            lines.append(f"[{i}] source={h.source} score={h.score:.3f}\n{text}")
        return "\n\n".join(lines)

    def list_files(self) -> str:
        files = sorted(p.name for p in self.upload_dir.glob("*") if p.is_file())
        return json.dumps(files, ensure_ascii=False)

    def read_file(self, name: str) -> str:
        path = safe_join(self.upload_dir, name)
        if path is None:
            return "Access denied."
        if not path.exists() or not path.is_file():
            return f"File not found: {Path(name).name}"
        text = path.read_text(encoding="utf-8", errors="ignore")
        return text[:4000]

    def write_note(self, note: str) -> str:
        safe, _ = redact_text(note)
        return self.memory.add_note(safe)

    def save_fact(self, fact: str) -> str:
        safe, _ = redact_text(fact)
        return self.memory.add_fact(safe)

    def recall_memory(self) -> str:
        return self.memory.recall()

    def kb_stats(self) -> str:
        return f"Knowledge base chunks: {self.store.count()}"

    def list_workflows(self) -> str:
        from src.agent.workflow import list_workflows

        return list_workflows()

    def run_workflow_tool(self, workflow_id: str) -> str:
        from src.agent.workflow import run_workflow

        return run_workflow(self, workflow_id).summary

    def build_workflow_tool(self, requirement: str) -> str:
        from src.agent.workflow_builder import build_and_summarize

        return build_and_summarize(requirement)

    def export_workflow_tool(self, workflow_id: str, formats: str = "yaml,json,dify,langchain") -> str:
        from src.agent.workflow_export import export_all_formats_text, export_workflow

        fmts = [x.strip() for x in (formats or "").split(",") if x.strip()]
        if fmts:
            paths = export_workflow(workflow_id, fmts)
            return "已导出：\n" + "\n".join(f"- {k}: {v}" for k, v in paths.items())
        return export_all_formats_text(workflow_id)

    def build_app_config_tool(self, app: str, requirement: str) -> str:
        from src.apps.app_builder import build_for_app

        return build_for_app(app, requirement).summary

    def parse_image(self, name: str = "", path: str = "") -> str:
        from src.vision.image_parse import is_image_path, parse_image_to_text

        target = (path or name or "").strip()
        if not target:
            imgs = sorted(
                (p for p in self.upload_dir.iterdir() if p.is_file() and is_image_path(p)),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            if not imgs:
                return "未找到图片。请先上传 png/jpg/webp 到上传目录，或指定 name。"
            target_path = imgs[0]
        else:
            # never honor absolute paths — basename under upload_dir only
            target_path = safe_join(self.upload_dir, Path(target).name)
            if target_path is None:
                return "Access denied."
            if not target_path.exists() or not target_path.is_file():
                return f"图片不存在: {Path(target).name}"
            if not is_image_path(target_path):
                return "仅支持图片文件。"
        return parse_image_to_text(target_path)

    def list_skills(self) -> str:
        if self.skills is None:
            return "Skill registry not configured."
        return self.skills.describe()

    def run_skill(self, skill_id: str, name: str = "") -> str:
        if self.skills is None:
            return "Skill registry not configured."
        params = {"name": name} if name else {}
        result = self.skills.run_by_title(skill_id, params)
        return result.as_text()


_JSON_RE = re.compile(r"\{.*?\}", re.DOTALL)


def extract_json_action(text: str) -> dict | None:
    # Prefer the last JSON-looking object (models often narrate then emit JSON).
    matches = list(_JSON_RE.finditer(text or ""))
    for match in reversed(matches):
        try:
            obj = json.loads(match.group(0))
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            continue
    return None
