"""Stage I — External Integrations."""

from app.integrations.base import BaseConnector, ConnectorResult, ConfirmationRequired
from app.integrations.email import EmailConnector
from app.integrations.webhook import WebhookRegistry, WebhookDispatcher
from app.integrations.scm import SCMConnector, SCMTarget
from app.integrations.ci import CITriggerConnector

__all__ = [
    "BaseConnector",
    "ConnectorResult",
    "ConfirmationRequired",
    "EmailConnector",
    "WebhookRegistry",
    "WebhookDispatcher",
    "SCMConnector",
    "SCMTarget",
    "CITriggerConnector",
]
