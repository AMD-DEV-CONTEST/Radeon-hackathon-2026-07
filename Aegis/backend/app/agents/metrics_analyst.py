"""Metrics Analyst agent — investigates Prometheus metrics for anomalies."""
from app.agents.base import BaseAgent
from app.tools.metrics_query import MetricsQueryTool

_SYSTEM_PROMPT = """You are the Metrics Analysis agent. Given a PromQL result set,
summarize any anomalies (spikes, drops, saturation) in 2-4 sentences and state a
confidence (0-1) that these metrics are related to the root cause."""


class MetricsAnalystAgent(BaseAgent):
    name = "metrics_analyst"
    system_prompt = _SYSTEM_PROMPT

    def __init__(self, *args, metrics_tool: MetricsQueryTool | None = None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.metrics_tool = metrics_tool or MetricsQueryTool()

    async def act(self, state: dict) -> dict:
        service = state.get("service_hint") or "unknown-service"
        promql = f'rate(http_requests_total{{service="{service}", status=~"5.."}}[5m])'
        tool_result = await self.metrics_tool.run(promql=promql, range_minutes=30)

        result = await self.inference.complete(
            system_prompt=self.system_prompt,
            user_prompt=f"Service: {service}\nMetrics result: {tool_result.output}",
            temperature=0.2,
            max_tokens=400,
        )

        evidence = state.get("evidence", [])
        evidence.append(
            {
                "evidence_type": "metric",
                "source_agent": self.name,
                "summary": result.text,
                "raw_data": tool_result.output or {},
            }
        )
        return {
            "evidence": evidence,
            "_reasoning": result.text,
            "_tool_calls": [{"tool": self.metrics_tool.name, "success": tool_result.success}],
            "_tokens_generated": result.completion_tokens,
            "_tokens_per_second": result.tokens_per_second,
        }
