"""
Metrics query tool — queries a Prometheus-compatible backend via its HTTP API
(instant/range queries). This is the same Prometheus instance Phase 13's
/metrics endpoint feeds, so Aegis can investigate its own infrastructure.
"""
from typing import Optional

import httpx

from app.tools.base import BaseTool


class MetricsQueryTool(BaseTool):
    name = "metrics_query"
    description = (
        "Run a PromQL query against the metrics backend over a time range and "
        "return the resulting time series."
    )

    def __init__(self, prometheus_url: str = "http://localhost:9090") -> None:
        self.prometheus_url = prometheus_url

    async def _execute(self, promql: str, range_minutes: int = 30, step_seconds: int = 60) -> dict:
        import time as _time

        end = int(_time.time())
        start = end - range_minutes * 60

        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{self.prometheus_url}/api/v1/query_range",
                params={"query": promql, "start": start, "end": end, "step": step_seconds},
            )
            resp.raise_for_status()
            data = resp.json()

        return {"promql": promql, "result": data.get("data", {}).get("result", [])}
