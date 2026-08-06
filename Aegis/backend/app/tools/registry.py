"""
Tool registry wiring. Called once per request/agent-run with the request's
DB session and actor identity, since several tools need per-request context
(a DB session for RAG search, an actor label for audit logging) rather than
being process-wide singletons.
"""
from sqlalchemy.ext.asyncio import AsyncSession

from app.tools.base import ToolRegistry
from app.tools.deploy_history import DeployHistoryTool
from app.tools.log_query import LogQueryTool
from app.tools.metrics_query import MetricsQueryTool
from app.tools.remediation_actions import RemediationActionsTool
from app.tools.runbook_search import RunbookSearchTool


def build_tool_registry(db: AsyncSession, actor_label: str) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(LogQueryTool())
    registry.register(MetricsQueryTool())
    registry.register(DeployHistoryTool())
    registry.register(RunbookSearchTool(db))
    registry.register(RemediationActionsTool(db, actor_label))
    return registry
