"""
WebArena adapter — converts WebArena tasks into Determinex VisualTaskSpecs.

WebArena tasks specify a web-based goal (shopping, CMS, social, maps, etc.)
with a set of evaluation functions that check the final browser state.
Determinex routes these through browser_controller + browser_verifier.

WebArena task schema (subset):
  {
    "task_id": int,
    "sites": ["shopping", "reddit"],
    "intent": "Find the cheapest laptop under $500 and add it to cart",
    "eval": {
      "eval_types": ["url_match", "program_html"],
      "reference_url": "...",
      "program_html": [{"url": "...", "locator": "...", "required_contents": "..."}]
    },
    "start_url": "http://...",
    "geolocation": null,
    "intent_template": "...",
    "instantiation_dict": {}
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
class WebArenaTask:
    task_id: int | str
    intent: str
    sites: list[str]
    start_url: str
    eval_config: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


class WebArenaAdapter:
    """Converts WebArena tasks to VisualTaskSpec and back."""

    def to_task_spec(self, task: WebArenaTask) -> VisualTaskSpec:
        constraints = [
            "Complete the task using only the browser",
            "Do not navigate to URLs outside the specified sites",
            "Respect the site's authentication state — do not log in or out unless required",
        ]
        if task.eval_config.get("reference_url"):
            constraints.append(f"Final URL should match: {task.eval_config['reference_url']}")

        return VisualTaskSpec(
            task_id=f"webarena_{task.task_id}",
            env_type=EnvType.BROWSER,
            goal=task.intent,
            constraints=constraints,
            source_benchmark="webarena",
            max_steps=30,
            timeout_seconds=300,
            metadata={
                "start_url": task.start_url,
                "sites": task.sites,
                "eval_types": task.eval_config.get("eval_types", []),
                "task_id": task.task_id,
                **task.metadata,
            },
        )

    def eval_verdict(self, task: WebArenaTask, final_url: str, page_html: str) -> dict:
        """
        Lightweight local evaluator — checks url_match and string_match eval types.
        Full WebArena eval requires the webarena harness; this is a fast pre-check.
        """
        results: dict[str, bool] = {}
        eval_types = task.eval_config.get("eval_types", [])

        if "url_match" in eval_types:
            ref = task.eval_config.get("reference_url", "")
            results["url_match"] = ref in final_url if ref else False

        if "string_match" in eval_types:
            for item in task.eval_config.get("string_match", []):
                key = item.get("string", "")
                results[f"string_match:{key[:30]}"] = key.lower() in page_html.lower()

        return {
            "eval_types": eval_types,
            "results": results,
            "passed": all(results.values()) if results else False,
        }

    @staticmethod
    def load_tasks(json_path: Path) -> list[WebArenaTask]:
        import json

        data = json.loads(json_path.read_text())
        tasks = []
        for item in data if isinstance(data, list) else [data]:
            tasks.append(
                WebArenaTask(
                    task_id=item.get("task_id", 0),
                    intent=item.get("intent", ""),
                    sites=item.get("sites", []),
                    start_url=item.get("start_url", ""),
                    eval_config=item.get("eval", {}),
                    metadata={
                        k: v
                        for k, v in item.items()
                        if k not in ("task_id", "intent", "sites", "start_url", "eval")
                    },
                )
            )
        return tasks
