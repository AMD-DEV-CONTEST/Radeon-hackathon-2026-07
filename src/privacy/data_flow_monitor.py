import logging
from typing import List, Callable, Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

class DataFlowMonitor:
    """Real-time data flow tracking with event listeners."""
    
    def __init__(self):
        """Initialize the DataFlowMonitor."""
        self._events: List[Dict[str, Any]] = []
        self._listeners: List[Callable[[Dict[str, Any]], None]] = []
        self._total_bytes_processed: int = 0
        self._local_bytes: int = 0
        self._external_bytes: int = 0
        self._pending_approvals: int = 0
        self._max_events: int = 100  # Keep memory footprint reasonable
        
        logger.info("DataFlowMonitor initialized.")
    
    @property
    def stats(self) -> Dict[str, Dict[str, int]]:
        """Return byte and count statistics for local vs external flows."""
        local_count = sum(1 for e in self._events if e.get("is_local", True))
        external_count = sum(1 for e in self._events if not e.get("is_local", True))
        return {
            "local": {"bytes": self._local_bytes, "count": local_count},
            "external": {"bytes": self._external_bytes, "count": external_count},
        }

    def get_local_percentage(self) -> float:
        """Calculate percentage of bytes processed locally."""
        if self._total_bytes_processed > 0:
            return (self._local_bytes / self._total_bytes_processed) * 100.0
        return 100.0

    def record_event(
        self,
        event_type: str,
        source: Any = None,
        destination: Optional[str] = None,
        bytes_count: int = 0,
        is_local: bool = True,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record a data flow event and notify listeners.
        
        Supports both structured 5-arg signature and legacy 2-arg signature record_event("local", 100).
        """
        if destination is None and (isinstance(source, (int, float)) or source is None):
            target = str(event_type).lower()
            is_local_flag = (target == "local")
            bytes_val = int(source) if source is not None else 0
            event_type = "data_flow"
            actual_source = "local" if is_local_flag else "external"
            destination = "local" if is_local_flag else "external"
            bytes_count = bytes_val
            is_local = is_local_flag
        else:
            actual_source = str(source) if source is not None else "local"

        if metadata is None:
            metadata = {}
            
        event = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "event_type": event_type,
            "source": actual_source,
            "destination": destination or "local",
            "bytes": bytes_count,
            "is_local": is_local,
            "metadata": metadata
        }
        
        self._events.append(event)
        
        # Trim history
        if len(self._events) > self._max_events:
            self._events.pop(0)
            
        self._total_bytes_processed += bytes_count
        if is_local:
            self._local_bytes += bytes_count
        else:
            self._external_bytes += bytes_count
            
        # Notify listeners
        for listener in self._listeners:
            try:
                listener(event)
            except Exception as e:
                logger.error(f"Error in data flow listener: {e}")

    def add_listener(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        """Register a callback for new data flow events.
        
        Args:
            callback: Function to call with the new event dict.
        """
        if callback not in self._listeners:
            self._listeners.append(callback)
    
    def remove_listener(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        """Unregister a listener callback.
        
        Args:
            callback: The function to remove.
        """
        if callback in self._listeners:
            self._listeners.remove(callback)
    
    def set_pending_approvals(self, count: int) -> None:
        """Update the number of pending user approvals.
        
        Args:
            count: Number of pending approvals.
        """
        self._pending_approvals = count
    
    def get_current_status(self) -> Dict[str, Any]:
        """Get the current aggregated status of data flows.
        
        Returns:
            Dict containing metrics and recent events.
        """
        total_events = len(self._events)
        local_percentage = 100.0
        
        if self._total_bytes_processed > 0:
            local_percentage = (self._local_bytes / self._total_bytes_processed) * 100
            
        return {
            "total_events": total_events,
            "total_bytes_processed": self._total_bytes_processed,
            "local_bytes": self._local_bytes,
            "external_bytes": self._external_bytes,
            "local_percentage": local_percentage,
            "pending_approvals": self._pending_approvals,
            "alerts": [],
            "recent_events": self._events[-10:] if self._events else []
        }
    
    def reset(self) -> None:
        """Reset all monitor counters and history."""
        self._events = []
        self._total_bytes_processed = 0
        self._local_bytes = 0
        self._external_bytes = 0
        self._pending_approvals = 0
        logger.info("DataFlowMonitor reset.")
