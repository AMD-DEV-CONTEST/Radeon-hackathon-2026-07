import json
from typing import Any, Dict, List

from nexus.agent.tool_registry import (
    ToolRegistry,
    create_default_registry,
)


class ToolExecutor:
    """
    Executes validated NexusAI agent plans against
    the allowlisted ToolRegistry.
    """

    def __init__(
        self,
        registry: ToolRegistry | None = None
    ):
        self.registry = (
            registry
            if registry is not None
            else create_default_registry()
        )

    def execute_step(
        self,
        step: Dict[str, Any],
        context: Dict[str, Any]
    ):
        tool_name = step.get("tool")

        if not tool_name:
            return {
                "status": "error",
                "error": "missing_tool",
                "step": step,
            }

        if not self.registry.has_tool(
            tool_name
        ):
            return {
                "status": "blocked",
                "error": "unregistered_tool",
                "tool": tool_name,
            }

        tool = self.registry.get_tool(
            tool_name
        )

        try:
            result = tool(context)

            return {
                "status": "success",
                "step": step.get("step"),
                "tool": tool_name,
                "observation": result,
            }

        except Exception as exc:
            return {
                "status": "error",
                "step": step.get("step"),
                "tool": tool_name,
                "error": str(exc),
            }

    def execute_plan(
        self,
        plan: Dict[str, Any],
        user_request: str
    ) -> Dict[str, Any]:

        context = {
            "user_request": user_request,
            "goal": plan.get("goal"),
            "observations": [],
        }

        execution_trace: List[
            Dict[str, Any]
        ] = []

        for step in plan.get(
            "plan",
            []
        ):
            result = self.execute_step(
                step,
                context
            )

            execution_trace.append(
                result
            )

            context[
                "observations"
            ].append(
                result
            )

            if result["status"] in {
                "error",
                "blocked",
            }:
                break

        success = all(
            result["status"] == "success"
            for result in execution_trace
        )

        return {
            "goal": plan.get("goal"),
            "success": success,
            "steps_executed": len(
                execution_trace
            ),
            "execution_trace": (
                execution_trace
            ),
        }


if __name__ == "__main__":
    executor = ToolExecutor()

    test_plan = {
        "goal": (
            "Find Aria's relationships "
            "and visualize them"
        ),
        "plan": [
            {
                "step": 1,
                "action": (
                    "Search the NexusAI "
                    "knowledge base"
                ),
                "tool": (
                    "search_knowledge"
                ),
            },
            {
                "step": 2,
                "action": (
                    "Query entities and "
                    "relationships"
                ),
                "tool": (
                    "query_knowledge_graph"
                ),
            },
            {
                "step": 3,
                "action": (
                    "Visualize relevant "
                    "knowledge"
                ),
                "tool": (
                    "explore_world"
                ),
            },
        ],
    }

    request = (
        "Find everything we know about "
        "Aria and show her relationships "
        "in WorldForge."
    )

    result = executor.execute_plan(
        test_plan,
        request
    )

    print(
        json.dumps(
            result,
            indent=2
        )
    )
