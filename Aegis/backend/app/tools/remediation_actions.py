"""
Remediation action tool — the ONLY tool in the system capable of making a
change to production. Every other tool is read-only by construction; this one
is deliberately isolated so its blast radius is auditable.

Safety model:
  1. `requires_approval = True` -> the LangGraph workflow (Phase 5) routes
     through a human-approval interrupt before this tool is ever invoked for
     anything above a "restart" action.
  2. Every invocation writes an AuditLog row (who/what/when/outcome) BEFORE
     the action executes, so even a crash mid-action leaves an audit trail.
  3. Action set is a fixed enum, not arbitrary shell/API calls — the agent
     cannot invent new remediation capabilities at runtime.
"""
import enum
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ToolExecutionError
from app.db.models.audit import AuditLog
from app.tools.base import BaseTool


class RemediationAction(str, enum.Enum):
    RESTART_SERVICE = "restart_service"
    ROLLBACK_DEPLOY = "rollback_deploy"
    SCALE_SERVICE = "scale_service"
    TOGGLE_FEATURE_FLAG = "toggle_feature_flag"


class RemediationActionsTool(BaseTool):
    name = "remediation_action"
    description = "Execute a pre-approved remediation action against a service."
    requires_approval = True

    def __init__(self, db: AsyncSession, actor_label: str) -> None:
        self.db = db
        self.actor_label = actor_label

    async def _execute(
        self, action: RemediationAction, service: str, resource_id: str, params: dict | None = None
    ) -> dict:
        audit_entry = AuditLog(
            id=uuid.uuid4(),
            actor_label=self.actor_label,
            action=f"remediation.{action.value}",
            resource_type="service",
            resource_id=resource_id,
            outcome="executed",
            context={"service": service, "params": params or {}},
        )
        self.db.add(audit_entry)
        await self.db.flush()

        # NOTE: the actual infra call (kubectl rollout restart, ArgoCD rollback API,
        # LaunchDarkly flag toggle, etc.) is the integration point an enterprise
        # wires in per their own infra — deliberately not hardcoded to one vendor.
        if action not in RemediationAction:
            raise ToolExecutionError(f"Unsupported remediation action: {action}")

        return {
            "action": action.value,
            "service": service,
            "resource_id": resource_id,
            "audit_log_id": str(audit_entry.id),
            "status": "executed",
        }
