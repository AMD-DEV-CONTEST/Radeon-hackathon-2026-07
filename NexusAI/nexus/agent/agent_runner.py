import json

from nexus.agent.radeon_agent import RadeonNexusAgent
from nexus.agent.tool_executor import ToolExecutor


class NexusAgentRunner:
    """
    End-to-end NexusAI agent pipeline.

    User Request
        -> Radeon LLM Planner
        -> Validated Plan
        -> Tool Executor
        -> Execution Trace
    """

    def __init__(self):
        print("=" * 70)
        print("INITIALIZING NEXUSAI AGENT CORE")
        print("=" * 70)

        self.agent = RadeonNexusAgent()
        self.executor = ToolExecutor()

    def run(self, user_request):
        print("\n[1] USER REQUEST")
        print(user_request)

        print("\n[2] GENERATING PLAN ON AMD RADEON")
        plan = self.agent.plan(user_request)

        print(
            json.dumps(
                plan,
                indent=2
            )
        )

        if not plan.get("plan"):
            return {
                "success": False,
                "error": "empty_plan",
                "plan": plan,
            }

        print("\n[3] EXECUTING VALIDATED PLAN")

        execution = self.executor.execute_plan(
            plan,
            user_request
        )

        print(
            json.dumps(
                execution,
                indent=2
            )
        )

        return {
            "success": execution["success"],
            "user_request": user_request,
            "planner": {
                "model": plan.get("model"),
                "backend": plan.get("backend"),
                "device": plan.get("device"),
            },
            "plan": plan,
            "execution": execution,
        }


if __name__ == "__main__":
    runner = NexusAgentRunner()

    request = (
        "Find everything we know about Aria, "
        "determine who she is connected to, "
        "and show her relationships in WorldForge."
    )

    result = runner.run(request)

    print("\n" + "=" * 70)
    print("FINAL NEXUSAI AGENT RESULT")
    print("=" * 70)

    print(
        json.dumps(
            result,
            indent=2
        )
    )
