"""Log Analyst agent — investigates application/infra logs for the incident window."""
from app.agents.base import BaseAgent
from app.tools.log_query import LogQueryTool

_SYSTEM_PROMPT = """You are the Log Analysis agent. Given a set of log lines, summarize
any errors, exceptions, or anomalous patterns relevant to the incident in 2-4 sentences.
Then state a confidence (0-1) that these logs are related to the root cause."""


class LogAnalystAgent(BaseAgent):
    name = "log_analyst"
    system_prompt = _SYSTEM_PROMPT

    def __init__(self, *args, log_tool: LogQueryTool | None = None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.log_tool = log_tool or LogQueryTool()

    async def act(self, state: dict) -> dict:
        service = state.get("service_hint") or "unknown-service"
        tool_result = await self.log_tool.run(service=service, minutes_back=30)

        result = await self.inference.complete(
            system_prompt=self.system_prompt,
            user_prompt=f"Service: {service}\nLog query result: {tool_result.output}",
            temperature=0.2,
            max_tokens=400,
        )

        evidence = state.get("evidence", [])
        evidence.append(
            {
                "evidence_type": "log",
                "source_agent": self.name,
                "summary": result.text,
                "raw_data": tool_result.output or {},
            }
        )
        return {
            "evidence": evidence,
            "_reasoning": result.text,
            "_tool_calls": [{"tool": self.log_tool.name, "success": tool_result.success}],
            "_tokens_generated": result.completion_tokens,
            "_tokens_per_second": result.tokens_per_second,
        }
