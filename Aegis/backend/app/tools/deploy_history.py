"""
Deploy correlation tool — checks whether a recent deploy/config change lines up
with the incident window. Backed by whatever CI/CD system the org uses
(GitHub Actions, ArgoCD, Spinnaker); this implementation queries GitHub's
deployments API as the reference integration.
"""
from datetime import datetime, timedelta, timezone

import httpx

from app.tools.base import BaseTool


class DeployHistoryTool(BaseTool):
    name = "deploy_history"
    description = "List deployments to a given service/repo within a recent time window."

    def __init__(self, github_token: str | None = None) -> None:
        self.github_token = github_token

    async def _execute(self, repo: str, hours_back: int = 6) -> dict:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)
        headers = {"Authorization": f"Bearer {self.github_token}"} if self.github_token else {}

        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"https://api.github.com/repos/{repo}/deployments",
                headers=headers,
                params={"per_page": 20},
            )
            resp.raise_for_status()
            deployments = resp.json()

        recent = [
            d for d in deployments
            if datetime.fromisoformat(d["created_at"].replace("Z", "+00:00")) >= cutoff
        ]
        return {"repo": repo, "window_hours": hours_back, "recent_deployments": recent}
