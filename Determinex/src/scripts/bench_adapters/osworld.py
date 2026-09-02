"""
OSWorld adapter — converts OSWorld desktop tasks into Determinex VisualTaskSpecs.

OSWorld provides computer-use tasks across macOS/Windows/Ubuntu with:
  - A screenshot of the initial desktop state
  - A natural-language instruction
  - A set of evaluators (file-based, accessibility-tree-based, execution-based)

Determinex routes these through screen_controller (VM only — DETERMINEX_REQUIRE_VM=1).
Physical host desktop control is refused by design.

OSWorld task schema (subset):
  {
    "id": "...",
    "instruction": "...",
    "config": [{"type": "launch", "parameters": {"command": "..."}}],
    "evaluator": {
      "func": "check_include_exclude",
      "result": {"type": "vm_command_line", "command": "..."},
      "expected": {"type": "rule", "rules": {"include": ["..."], "exclude": ["..."]}}
    },
    "snapshot": "snapshot_id"
  }
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from agents.base_agent import EnvType, VisualTaskSpec


@dataclass
class OSWorldTask:
    task_id: str
    instruction: str
    snapshot: str  # VM snapshot name to restore before task
    config: list[dict[str, Any]] = field(default_factory=list)
    evaluator: dict[str, Any] = field(default_factory=dict)
    screenshot_path: Path | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class OSWorldAdapter:
    """Converts OSWorld tasks to VisualTaskSpec and wraps VM setup."""

    def to_task_spec(self, task: OSWorldTask) -> VisualTaskSpec:
        return VisualTaskSpec(
            task_id=f"osworld_{task.task_id}",
            env_type=EnvType.DESKTOP,
            goal=task.instruction,
            constraints=[
                "Execute only within the VM — no host system access",
                "Restore VM snapshot before starting",
                "Use screen_controller (VNC only) for all interactions",
                "All screenshot captures must pass through visual_cloak before any cloud call",
            ],
            source_benchmark="osworld",
            max_steps=50,
            timeout_seconds=900,
            metadata={
                "snapshot": task.snapshot,
                "config_steps": len(task.config),
                "evaluator_func": task.evaluator.get("func", ""),
                "task_id": task.task_id,
                "has_screenshot": task.screenshot_path is not None,
                **task.metadata,
            },
        )

    def get_setup_commands(self, task: OSWorldTask) -> list[str]:
        """
        Extract shell commands to run in the VM before the agent starts.
        Returns a list of command strings derived from the task's config steps.
        """
        commands = []
        for step in task.config:
            step_type = step.get("type", "")
            params = step.get("parameters", {})
            if step_type == "launch":
                cmd = params.get("command")
                if cmd:
                    commands.append(cmd if isinstance(cmd, str) else " ".join(cmd))
            elif step_type == "execute":
                cmd = params.get("command")
                if cmd:
                    commands.append(cmd if isinstance(cmd, str) else " ".join(cmd))
        return commands

    def eval_verdict(self, task: OSWorldTask, vm_output: str) -> dict:
        """
        Run the evaluator logic locally for simple rule-based checks.
        Complex evaluators (execution_result, file_content) require the full OSWorld harness.
        """
        evaluator = task.evaluator
        func = evaluator.get("func", "")

        if func == "check_include_exclude":
            expected = evaluator.get("expected", {}).get("rules", {})
            includes = expected.get("include", [])
            excludes = expected.get("exclude", [])
            include_ok = all(kw.lower() in vm_output.lower() for kw in includes)
            exclude_ok = all(kw.lower() not in vm_output.lower() for kw in excludes)
            return {
                "func": func,
                "include_ok": include_ok,
                "exclude_ok": exclude_ok,
                "passed": include_ok and exclude_ok,
            }

        return {"func": func, "passed": False, "note": "requires full OSWorld harness"}

    @staticmethod
    def load_tasks(json_path: Path) -> list[OSWorldTask]:
        import json

        data = json.loads(json_path.read_text())
        tasks = []
        for item in data if isinstance(data, list) else [data]:
            ss = item.get("screenshot")
            tasks.append(
                OSWorldTask(
                    task_id=str(item.get("id", "")),
                    instruction=item.get("instruction", ""),
                    snapshot=item.get("snapshot", ""),
                    config=item.get("config", []),
                    evaluator=item.get("evaluator", {}),
                    screenshot_path=Path(ss) if ss else None,
                    metadata={
                        k: v
                        for k, v in item.items()
                        if k
                        not in (
                            "id",
                            "instruction",
                            "snapshot",
                            "config",
                            "evaluator",
                            "screenshot",
                        )
                    },
                )
            )
        return tasks
