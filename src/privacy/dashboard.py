import logging
from typing import Dict, Any, Optional

from .audit_logger import AuditLogger
from .data_flow_monitor import DataFlowMonitor

logger = logging.getLogger(__name__)

class PrivacyDashboard:
    """Backend aggregator for the privacy dashboard UI."""
    
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
        
        # Calculate overall local percentage (weighing events or bytes; here we use events for inference representation)
        total_inferences = audit_stats.get("inference_count", 0)
        external_inferences = 0 # Derive this if needed, assuming external backend count
        
        return {
            "local_inference_pct": audit_stats.get("local_percentage", 100.0),
            "total_inferences": total_inferences,
            "local_inferences": total_inferences, # Assuming all local unless we track otherwise
            "radeon_api_inferences": 0, # Update this based on your actual backend tracking
            "external_bytes": flow_stats.get("external_bytes", 0),
            "local_bytes": flow_stats.get("local_bytes", 0),
            "total_events": audit_stats.get("total_events", 0),
            "recent_events": recent_audit_events,
            "pending_approvals": flow_stats.get("pending_approvals", 0),
            "fallback_stats": model_stats
        }
    
    def get_formatted_status(self) -> str:
        """Generate a human-readable summary string for display.
        
        Returns:
            Formatted status string.
        """
        data = self.get_dashboard_data()
        
        status = (
            f"🔒 Privacy Status:\n"
            f"- Local Inference: {data['local_inference_pct']:.1f}%\n"
            f"- Total Inferences: {data['total_inferences']}\n"
            f"- External Data Sent: {data['external_bytes']} bytes\n"
            f"- Pending Approvals: {data['pending_approvals']}"
        )
        return status
