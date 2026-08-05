from __future__ import annotations

import re
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

from privateops.models import ToolResult
from privateops.windows_inspector import SYSTEM_TOOLS, WindowsInspector


TEXT_EXTENSIONS = {".md", ".txt", ".json", ".yaml", ".yml", ".py", ".js", ".ts", ".html", ".css", ".log"}
ALLOWED_TEST_COMMANDS = {
    "python -m unittest discover -s tests",
    "python -m unittest discover -s tests -v",
}
SHELL_META = re.compile(r"[;&|><`\r\n]")
EXCLUDED_DIRECTORY_NAMES = {
    ".git",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "venv",
}


class ToolRegistry:
    def __init__(self, workspace: str | Path, system_inspector: WindowsInspector | None = None):
        self.workspace = Path(workspace).resolve()
        self.system_inspector = system_inspector or WindowsInspector()

    def execute(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        if name in SYSTEM_TOOLS:
            return self.system_inspector.collect(name)
        handlers = {
            "workspace_inventory": self._inventory,
            "search_text": self._search_text,
            "submission_readiness": self._submission_readiness,
            "run_tests": self._run_tests,
        }
        handler = handlers.get(name)
        if handler is None:
            return ToolResult(name, "blocked", "Unknown tools are blocked.")
        try:
            return handler(arguments)
        except (OSError, ValueError) as exc:
            return ToolResult(name, "failed", str(exc))

    def _files(self) -> list[Path]:
        if not self.workspace.exists():
            return []
        files = []
        for path in self.workspace.rglob("*"):
            if not path.is_file():
                continue
            resolved = path.resolve()
            if not resolved.is_relative_to(self.workspace):
                continue
            relative = resolved.relative_to(self.workspace)
            if any(part in EXCLUDED_DIRECTORY_NAMES for part in relative.parts):
                continue
            if len(relative.parts) >= 2 and relative.parts[:2] == ("data", "state"):
                continue
            files.append(resolved)
        return sorted(files)

    def _excluded_directories_present(self) -> list[str]:
        present = {
            path.name
            for path in self.workspace.rglob("*")
            if path.is_dir() and path.name in EXCLUDED_DIRECTORY_NAMES
        }
        if (self.workspace / "data" / "state").is_dir():
            present.add("data/state")
        return sorted(present)

    def _inventory(self, _: dict[str, Any]) -> ToolResult:
        files = [path.relative_to(self.workspace).as_posix() for path in self._files()]
        extensions = Counter(Path(path).suffix.lower() or "<none>" for path in files)
        excluded = self._excluded_directories_present()
        return ToolResult(
            "workspace_inventory",
            "completed",
            f"Indexed {len(files)} project files; excluded {len(excluded)} environment categories.",
            {
                "total_files": len(files),
                "sample": files[:250],
                "sample_truncated": len(files) > 250,
                "extensions": dict(sorted(extensions.items())),
                "excluded_directories": excluded,
            },
        )

    def _search_text(self, arguments: dict[str, Any]) -> ToolResult:
        query = str(arguments.get("query", "")).strip()
        if not query:
            return ToolResult("search_text", "failed", "A non-empty query is required.")
        matches = []
        for path in self._files():
            if path.suffix.lower() not in TEXT_EXTENSIONS or path.stat().st_size > 1_000_000:
                continue
            for number, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                if query.lower() in line.lower():
                    matches.append({"path": path.relative_to(self.workspace).as_posix(), "line": number, "text": line[:240]})
                    if len(matches) >= 50:
                        break
            if len(matches) >= 50:
                break
        return ToolResult("search_text", "completed", f"Found {len(matches)} matching lines.", {"matches": matches})

    def _submission_readiness(self, _: dict[str, Any]) -> ToolResult:
        required = ["README.md", "requirements.txt", "submission", "tests"]
        present = {item: (self.workspace / item).exists() for item in required}
        missing = [item for item, exists in present.items() if not exists]
        status = "completed" if not missing else "attention"
        summary = "Submission structure is complete." if not missing else "Missing: " + ", ".join(missing)
        return ToolResult("submission_readiness", status, summary, {"present": present, "missing": missing})

    def _run_tests(self, arguments: dict[str, Any]) -> ToolResult:
        command = str(arguments.get("command", "")).strip()
        if SHELL_META.search(command) or command not in ALLOWED_TEST_COMMANDS:
            return ToolResult("run_tests", "blocked", "Only exact allow-listed test commands may run.")
        completed = subprocess.run(
            command.split(),
            cwd=self.workspace,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        output = (completed.stdout + completed.stderr)[-8000:]
        status = "completed" if completed.returncode == 0 else "failed"
        return ToolResult("run_tests", status, f"Tests exited with code {completed.returncode}.", {"exit_code": completed.returncode, "output": output})
