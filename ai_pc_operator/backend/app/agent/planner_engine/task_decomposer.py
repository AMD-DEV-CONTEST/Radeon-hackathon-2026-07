"""Task Decomposer — breaks a goal into atomic tasks.

A task is a single, executable unit of work. Each task has:
  - id: unique identifier
  - name: human-readable name
  - tool: which tool to invoke
  - inputs: parameters for the tool
  - depends_on: list of task ids that must complete first
  - optional: whether failure is acceptable
  - timeout: max execution time in seconds
  - retries: number of retry attempts

The decomposer uses intent-specific templates to know how to break
each goal into the right sequence of tasks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .goal_planner import Goal


@dataclass
class Task:
    """A single atomic task."""
    id: str
    name: str
    tool: str
    inputs: Dict[str, Any] = field(default_factory=dict)
    depends_on: List[str] = field(default_factory=list)
    optional: bool = False
    timeout: float = 30.0
    retries: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "tool": self.tool,
            "inputs": self.inputs,
            "depends_on": self.depends_on,
            "optional": self.optional,
            "timeout": self.timeout,
            "retries": self.retries,
            "metadata": self.metadata,
        }


class TaskDecomposer:
    """Decomposes goals into atomic tasks."""

    # Intent → task template (list of task specs)
    TASK_TEMPLATES = {
        "open_website": [
            {"name": "Ensure browser is ready", "tool": "browser.warmup",
             "optional": True, "timeout": 10.0},
            {"name": "Navigate to URL", "tool": "browser.open",
             "inputs_from": ["url"]},
            {"name": "Verify page loaded", "tool": "browser.verify_loaded",
             "timeout": 15.0},
        ],
        "open_app": [
            {"name": "Open application", "tool": "system.open_app",
             "inputs_from": ["app"]},
        ],
        "search_web": [
            {"name": "Open search engine", "tool": "browser.open",
             "inputs": {"url": "https://www.google.com"}},
            {"name": "Submit search query", "tool": "browser.search",
             "inputs_from": ["query"], "depends_on": ["t1"]},
        ],
        "delete_files": [
            {"name": "Scan target directory", "tool": "file.scan",
             "inputs_from": ["path"]},
            {"name": "Request approval", "tool": "approval.request",
             "depends_on": ["t1"]},
            {"name": "Quarantine files", "tool": "file.quarantine",
             "depends_on": ["t2"]},
        ],
        "list_files": [
            {"name": "List directory", "tool": "file.list",
             "inputs_from": ["path"]},
        ],
        "screen_click": [
            {"name": "Scan screen", "tool": "screen.scan"},
            {"name": "Locate element", "tool": "screen.locate",
             "inputs_from": ["text"], "depends_on": ["t1"]},
            {"name": "Click element", "tool": "screen.click",
             "depends_on": ["t2"]},
        ],
        "login": [
            {"name": "Open login page", "tool": "browser.open",
             "inputs_from": ["url"]},
            {"name": "Request vault unlock", "tool": "vault.unlock",
             "depends_on": ["t1"]},
            {"name": "Fill credentials", "tool": "auth.fill_credentials",
             "depends_on": ["t2"]},
            {"name": "Submit login form", "tool": "browser.submit",
             "depends_on": ["t3"]},
        ],
        "download_file": [
            {"name": "Verify source domain", "tool": "download.verify_source",
             "inputs_from": ["url"]},
            {"name": "Request approval if executable", "tool": "approval.request",
             "depends_on": ["t1"]},
            {"name": "Download file", "tool": "download.file",
             "inputs_from": ["url"], "depends_on": ["t2"]},
            {"name": "Hash and record", "tool": "download.hash",
             "depends_on": ["t3"]},
        ],
        "system_status": [
            {"name": "Collect metrics", "tool": "system.status"},
        ],
        "browser_session": [
            {"name": "Open browser", "tool": "system.open_app",
             "inputs": {"app": "chrome"}},
            {"name": "Keep system awake", "tool": "system.keep_awake"},
            {"name": "Start mouse jiggle", "tool": "system.mouse_jiggle",
             "inputs_from": ["duration"]},
        ],
    }

    def decompose(self, goal: Goal) -> List[Task]:
        """Decompose a goal into a list of tasks."""
        intent = goal.metadata.get("intent", "")
        params = goal.metadata.get("params", {})
        template = self.TASK_TEMPLATES.get(intent, [])

        tasks: List[Task] = []
        prev_id: Optional[str] = None

        for i, spec in enumerate(template):
            task_id = f"t{i+1}"
            inputs = dict(spec.get("inputs", {}))

            # Resolve inputs_from params
            for key in spec.get("inputs_from", []):
                if key in params:
                    inputs[key] = params[key]

            # Auto-chain dependencies if not specified
            depends_on = list(spec.get("depends_on", []))
            if not depends_on and prev_id and spec.get("chain", True):
                depends_on = [prev_id]

            task = Task(
                id=task_id,
                name=spec["name"],
                tool=spec["tool"],
                inputs=inputs,
                depends_on=depends_on,
                optional=spec.get("optional", False),
                timeout=spec.get("timeout", 30.0),
                retries=spec.get("retries", 0),
                metadata={"goal_intent": intent},
            )
            tasks.append(task)
            prev_id = task_id

        return tasks
