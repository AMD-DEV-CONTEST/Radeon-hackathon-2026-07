"""
AndroidWorld adapter — converts AndroidWorld mobile tasks into Determinex VisualTaskSpecs.

AndroidWorld provides Android device automation tasks with:
  - A natural-language instruction for an Android app
  - App package name and starting activity
  - An evaluator that checks device state after completion
  - Optional screenshots of the target state

Determinex routes these through adb_controller (emulator only —
DETERMINEX_REQUIRE_EMULATOR=1, DETERMINEX_ALLOW_PHYSICAL_DEVICE=0).

AndroidWorld task schema (subset):
  {
    "task_id": "...",
    "task_name": "TurnWifiOn",
    "instruction": "Turn on WiFi",
    "app_name": "Settings",
    "package_name": "com.android.settings",
    "activity_name": ".Settings",
    "params": {},
    "evaluators": [{"type": "wifi_on"}]
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
class AndroidWorldTask:
    task_id: str
    task_name: str
    instruction: str
    app_name: str
    package_name: str
    activity_name: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    evaluators: list[dict[str, Any]] = field(default_factory=list)
    screenshot_path: Path | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class AndroidWorldAdapter:
    """Converts AndroidWorld tasks to VisualTaskSpec."""

    def to_task_spec(self, task: AndroidWorldTask) -> VisualTaskSpec:
        return VisualTaskSpec(
            task_id=f"androidworld_{task.task_id}",
            env_type=EnvType.MOBILE,
            goal=task.instruction,
            constraints=[
                "Use Android emulator only — physical device connection not allowed",
                "Interact only with the target app unless the task explicitly requires leaving it",
                "All screenshots must pass through visual_cloak before any cloud call",
                f"Target app: {task.app_name} ({task.package_name})",
            ],
            source_benchmark="androidworld",
            max_steps=25,
            timeout_seconds=300,
            metadata={
                "package_name": task.package_name,
                "activity_name": task.activity_name,
                "app_name": task.app_name,
                "task_name": task.task_name,
                "params": task.params,
                "evaluator_types": [e.get("type", "") for e in task.evaluators],
                "has_screenshot": task.screenshot_path is not None,
                **task.metadata,
            },
        )

    def get_launch_command(self, task: AndroidWorldTask) -> str:
        """Return the adb shell am start command to launch the target activity."""
        component = (
            f"{task.package_name}/{task.activity_name}" if task.activity_name else task.package_name
        )
        return f"am start -n {component}"

    def eval_verdict(self, task: AndroidWorldTask, device_state: dict) -> dict:
        """
        Run lightweight local evaluation.
        Full evaluation for complex evaluator types requires the AndroidWorld harness.
        """
        results = {}
        for evaluator in task.evaluators:
            eval_type = evaluator.get("type", "")
            if eval_type == "wifi_on":
                results["wifi_on"] = device_state.get("wifi_enabled", False)
            elif eval_type == "app_installed":
                pkg = evaluator.get("package", task.package_name)
                results["app_installed"] = pkg in device_state.get("installed_packages", [])
            elif eval_type == "file_exists":
                path = evaluator.get("path", "")
                results[f"file_exists:{path}"] = path in device_state.get("files", [])
            else:
                results[eval_type] = False  # unknown → requires full harness

        return {
            "evaluators": [e.get("type", "") for e in task.evaluators],
            "results": results,
            "passed": all(results.values()) if results else False,
            "note": "complex evaluators require AndroidWorld harness"
            if any(
                v is False
                for k, v in results.items()
                if not any(et in k for et in ("wifi_on", "app_installed", "file_exists"))
            )
            else "",
        }

    @staticmethod
    def load_tasks(json_path: Path) -> list[AndroidWorldTask]:
        import json

        data = json.loads(json_path.read_text())
        tasks = []
        for item in data if isinstance(data, list) else [data]:
            ss = item.get("screenshot")
            tasks.append(
                AndroidWorldTask(
                    task_id=str(item.get("task_id", "")),
                    task_name=item.get("task_name", ""),
                    instruction=item.get("instruction", ""),
                    app_name=item.get("app_name", ""),
                    package_name=item.get("package_name", ""),
                    activity_name=item.get("activity_name", ""),
                    params=item.get("params", {}),
                    evaluators=item.get("evaluators", []),
                    screenshot_path=Path(ss) if ss else None,
                    metadata={
                        k: v
                        for k, v in item.items()
                        if k
                        not in (
                            "task_id",
                            "task_name",
                            "instruction",
                            "app_name",
                            "package_name",
                            "activity_name",
                            "params",
                            "evaluators",
                            "screenshot",
                        )
                    },
                )
            )
        return tasks
