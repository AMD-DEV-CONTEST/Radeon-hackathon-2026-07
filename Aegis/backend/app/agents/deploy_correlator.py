"""Deploy Correlator agent — checks if a recent deploy lines up with the incident window."""
from app.agents.base import BaseAgent
from app.tools.deploy_history import DeployHistoryTool

_SYSTEM_PROMPT = """You are the Deploy Correlation agent. Given a list of recent deployments,
determine whether any deployment's timing plausibly explains the incident. Summarize in
2-3 sentences and state a confidence (0-1)."""


class DeployCorrelatorAgent(BaseAgent):
    name = "deploy_correlator"
    system_prompt = _SYSTEM_PROMPT

    def __init__(self, *args, deploy_tool: DeployHistoryTool | None = None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.deploy_tool = deploy_tool or DeployHistoryTool()

    async def act(self, state: dict) -> dict:
        repo = state.get("service_hint") or "unknown/unknown"
        tool_result = await self.deploy_tool.run(repo=repo, hours_back=6)

        result = await self.inference.complete(
            system_prompt=self.system_prompt,
            user_prompt=f"Repo: {repo}\nRecent deploys: {tool_result.output}",
            temperature=0.2,
            max_tokens=300,
        )

        evidence = state.get("evidence", [])
        evidence.append(
            {
                "evidence_type": "deploy_event",
                "source_agent": self.name,
                "summary": result.text,
                "raw_data": tool_result.output or {},
            }
        )
        return {
            "evidence": evidence,
            "_reasoning": result.text,
            "_tool_calls": [{"tool": self.deploy_tool.name, "success": tool_result.success}],
            "_tokens_generated": result.completion_tokens,
            "_tokens_per_second": result.tokens_per_second,
        }
