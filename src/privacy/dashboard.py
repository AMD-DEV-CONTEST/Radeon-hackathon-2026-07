import logging
from typing import Dict, Any, Optional

from .audit_logger import AuditLogger
from .data_flow_monitor import DataFlowMonitor

logger = logging.getLogger(__name__)

class PrivacyDashboard:
    """Backend aggregator for the privacy dashboard UI.

    Local vs external inference counts are derived from the AuditLogger's
    persisted events (grouped by backend); byte totals come from the
    DataFlowMonitor; backend-tier counters come from ModelManager. There are
    no hardcoded assumptions (e.g. ``local == total`` or ``radeon == 0``).
    """

    def __init__(self, audit_logger: AuditLogger, data_flow_monitor: DataFlowMonitor, model_manager: Optional[Any] = None):
        """Initialize the PrivacyDashboard.
        
        Args:
            audit_logger: Instance of AuditLogger for historical stats.
            data_flow_monitor: Instance of DataFlowMonitor for real-time stats.
            model_manager: Optional manager for model-specific statistics.
        """
        self.audit_logger = audit_logger
        self.data_flow_monitor = data_flow_monitor
        self.model_manager = model_manager
        logger.info("PrivacyDashboard initialized.")

    def get_dashboard_data(self) -> Dict[str, Any]:
        """Aggregate stats from logger, monitor, and model manager.
        
        Returns:
            Complete dashboard state dictionary.
        """
        audit_stats = self.audit_logger.get_stats()
        flow_stats = self.data_flow_monitor.get_current_status()

        model_stats = {}
        if self.model_manager and hasattr(self.model_manager, 'get_stats'):
            model_stats = self.model_manager.get_stats()

        recent_audit_events = self.audit_logger.get_recent_events(10)

        local_inferences = audit_stats.get("local_inferences", 0)
        external_inferences = audit_stats.get("external_inferences", 0)
        failed_inferences = audit_stats.get("failed_inferences", 0)
        total_inferences = audit_stats.get("inference_count", 0)

        if total_inferences > 0:
            local_pct = local_inferences / total_inferences * 100
        else:
            local_pct = 100.0

        inferences_by_backend = audit_stats.get("inferences_by_backend", {})

        return {
            "local_inference_pct": round(local_pct, 1),
            "total_inferences": total_inferences,
            "local_inferences": local_inferences,
            "external_inferences": external_inferences,
            "failed_inferences": failed_inferences,
            "radeon_api_inferences": inferences_by_backend.get("radeon_api", 0),
            "inferences_by_backend": inferences_by_backend,
            "external_bytes": flow_stats.get("external_bytes", 0),
            "local_bytes": flow_stats.get("local_bytes", 0),
            "local_events": audit_stats.get("local_events", 0),
            "external_events": audit_stats.get("external_events", 0),
            "total_events": audit_stats.get("total_events", 0),
            "is_fully_local": (
                total_inferences == 0
                or (external_inferences == 0 and failed_inferences == 0)
            ),
            "recent_events": recent_audit_events,
            "pending_approvals": flow_stats.get("pending_approvals", 0),
            "fallback_stats": model_stats,
        }

    def get_formatted_status(self) -> str:
        """Generate a human-readable summary string for display.
        
        Returns:
            Formatted status string.
        """
        data = self.get_dashboard_data()

        status = (
            f"🔒 Privacy Status:\n"
            f"- Local Inference: {data['local_inference_pct']:.1f}% "
            f"({data['local_inferences']}/{data['total_inferences']} local)\n"
            f"- External Inferences: {data['external_inferences']}\n"
            f"- Failed Inferences: {data['failed_inferences']}\n"
            f"- External Data Sent: {data['external_bytes']} bytes\n"
            f"- Pending Approvals: {data['pending_approvals']}"
        )
        if not data["is_fully_local"]:
            status += "\n- ⚠️ Not fully local: at least one inference used an external or failed backend."
        return status
