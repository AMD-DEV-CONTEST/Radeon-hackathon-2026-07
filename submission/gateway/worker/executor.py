from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.request
from pathlib import Path
from typing import Any

from orchestrator.acceptance import run_acceptance_check

DEEPSEEK_BASE = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-chat"
MAX_FILE_CHARS = 4000
MAX_TREE_LINES = 120
MAX_BUILD_FIX_ATTEMPTS = 2


class CodingExecutor:
    """DeepSeek-powered coding task executor with per-task state persistence."""

    def __init__(self, workspace: str, api_key: str) -> None:
        self.workspace = Path(workspace)
        self.api_key = api_key
        self.state_dir = self.workspace / ".union_state"
        self.state_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ public

    def execute(self, task: dict[str, Any]) -> tuple[str, str]:
        """Return (acceptance_result, summary). Resumes from saved state."""
        task_id = task["id"]
        state = self._load_state(task_id)
        if state is None:
            instruction = (
                (task.get("payload") or {}).get("instruction")
                or task.get("description")
                or task.get("title")
                or ""
            )
            state = {
                "task_id": task_id,
                "phase": "planning",
                "instruction": instruction,
                "plan": "",
                "files_changed": [],
                "fix_attempts": 0,
                "acceptance_check": task.get("acceptance_check") or {},
            }
        try:
            result = self._run(state)
            if result[0] in ("pass", "fail", "needs_review"):
                self._delete_state(task_id)
            return result
        except Exception as exc:
            self._save_state(state)
            return "fail", f"executor crashed: {exc}"

    # ----------------------------------------------------------------- phases

    def _run(self, state: dict) -> tuple[str, str]:
        if state["phase"] == "planning":
            state["plan"] = self._plan(state["instruction"])
            state["phase"] = "editing"
            self._save_state(state)

        if state["phase"] == "editing":
            changed = self._edit(state)
            state["files_changed"].extend(changed)
            state["phase"] = "building"
            self._save_state(state)

        if state["phase"] == "building":
            return self._acceptance_loop(state)

        return "needs_review", "unknown phase"

    def _plan(self, instruction: str) -> str:
        tree = self._tree()
        prompt = (
            f"You are a TypeScript/Next.js coding assistant.\n\n"
            f"Project tree:\n{tree}\n\n"
            f"Task: {instruction}\n\n"
            f'List files to read as JSON: {{"files_to_read": ["rel/path/file.ts", ...]}}\n'
            f"Be minimal — only files directly needed."
        )
        return self._deepseek([{"role": "user", "content": prompt}])

    def _edit(self, state: dict) -> list[str]:
        files_to_read: list[str] = self._extract_list(state["plan"], "files_to_read") or []
        file_contents: dict[str, str] = {}
        for rel in files_to_read[:12]:
            p = self.workspace / rel
            if p.exists() and p.is_file():
                try:
                    file_contents[rel] = p.read_text(encoding="utf-8", errors="replace")[:MAX_FILE_CHARS]
                except OSError:
                    pass

        files_block = "\n\n".join(
            f"=== {path} ===\n{content}" for path, content in file_contents.items()
        )
        prompt = (
            f"Task: {state['instruction']}\n\n"
            f"Current files:\n{files_block}\n\n"
            f"Output ONLY changed files in this format:\n"
            f"=== FILE: rel/path/file.ts ===\n<complete content>\n=== END FILE ===\n\n"
            f"Rules: complete content (no diffs), minimal changes, valid TypeScript."
        )
        response = self._deepseek([{"role": "user", "content": prompt}])
        return self._apply(response)

    def _acceptance_loop(self, state: dict) -> tuple[str, str]:
        check = state.get("acceptance_check") or {}
        check_type = (check.get("type") or "").strip().lower()
        if check_type:
            result = run_acceptance_check(check)
            summary = (
                f"Acceptance check {check_type} returned {result}. "
                f"Files changed: {', '.join(state['files_changed']) or 'none'}"
            )
            return result, summary

        ok, out = self._build()
        if ok:
            summary = f"Build passed. Files changed: {', '.join(state['files_changed']) or 'none'}"
            return "pass", summary

        while state["fix_attempts"] < MAX_BUILD_FIX_ATTEMPTS:
            state["fix_attempts"] += 1
            self._save_state(state)
            fixed = self._fix(out)
            state["files_changed"].extend(fixed)
            self._save_state(state)
            ok, out = self._build()
            if ok:
                summary = f"Build passed after {state['fix_attempts']} fix(es). Changed: {', '.join(state['files_changed'])}"
                return "pass", summary

        return "fail", f"Build failed after {state['fix_attempts']} fix attempts.\n{out[-800:]}"

    def _fix(self, build_output: str) -> list[str]:
        prompt = (
            f"Build errors:\n{build_output[-2000:]}\n\n"
            f"Fix the TypeScript errors. Output changed files:\n"
            f"=== FILE: path ===\n<content>\n=== END FILE ==="
        )
        response = self._deepseek([{"role": "user", "content": prompt}])
        return self._apply(response)

    # ----------------------------------------------------------------- helpers

    def _build(self) -> tuple[bool, str]:
        for cmd in ("pnpm build", "npm run build"):
            try:
                r = subprocess.run(
                    cmd, cwd=str(self.workspace),
                    capture_output=True, text=True, timeout=300,
                    shell=True,
                )
                if r.returncode == 0:
                    return True, r.stdout + r.stderr
                return False, r.stdout + r.stderr
            except subprocess.TimeoutExpired:
                return False, "build timed out after 300s"
        return False, "neither pnpm nor npm found"

    def _apply(self, response: str) -> list[str]:
        changed: list[str] = []
        for m in re.finditer(r"=== FILE: (.+?) ===\n([\s\S]+?)=== END FILE ===", response):
            rel = m.group(1).strip()
            content = m.group(2)
            # Strip markdown code fences DeepSeek sometimes wraps content in
            content = re.sub(r"^```[^\n]*\n", "", content)
            content = re.sub(r"\n```\s*$", "", content)
            target = self.workspace / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            changed.append(rel)
        return changed

    def _tree(self) -> str:
        skip = {"node_modules", ".git", ".next", "dist", ".venv", "__pycache__",
                ".union_state", ".turbo", "out", "build", ".cache"}
        lines: list[str] = []
        for root, dirs, files in os.walk(str(self.workspace)):
            dirs[:] = sorted(d for d in dirs if d not in skip)
            level = len(Path(root).relative_to(self.workspace).parts)
            indent = "  " * level
            lines.append(f"{indent}{Path(root).name}/")
            for f in sorted(files)[:15]:
                lines.append(f"{indent}  {f}")
            if len(lines) >= MAX_TREE_LINES:
                lines.append("  ...(truncated)")
                break
        return "\n".join(lines)

    def _deepseek(self, messages: list[dict]) -> str:
        payload = {"model": DEEPSEEK_MODEL, "messages": messages, "temperature": 0.1}
        req = urllib.request.Request(
            f"{DEEPSEEK_BASE}/chat/completions",
            data=json.dumps(payload).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
        )
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read())["choices"][0]["message"]["content"]

    def _extract_list(self, text: str, key: str) -> list[str] | None:
        try:
            m = re.search(r"\{[\s\S]+?\}", text)
            if m:
                return json.loads(m.group()).get(key)
        except Exception:
            pass
        return None

    def _load_state(self, task_id: str) -> dict | None:
        f = self.state_dir / f"{task_id}.json"
        if f.exists():
            try:
                return json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                pass
        return None

    def _save_state(self, state: dict) -> None:
        f = self.state_dir / f"{state['task_id']}.json"
        f.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    def _delete_state(self, task_id: str) -> None:
        f = self.state_dir / f"{task_id}.json"
        if f.exists():
            f.unlink()
