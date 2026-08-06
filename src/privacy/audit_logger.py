import json
import logging
import os
from datetime import datetime
from typing import Dict, List, Any, Optional

from .telemetry import BACKEND_FAILED, is_local_backend

logger = logging.getLogger(__name__)

class AuditLogger:
    """Comprehensive audit logging for all inferences, tool calls, and data access."""
    
    EVENT_INFERENCE = "inference"
    EVENT_TOOL_CALL = "tool_call"
    EVENT_DATA_ACCESS = "data_access"
    EVENT_USER_ACTION = "user_action"
    EVENT_PERMISSION = "permission"
    
    def __init__(self, log_path: Optional[str] = None, log_file: Optional[str] = None):
        """Initialize the AuditLogger.
        
        Args:
            log_path: Path to the JSONL audit log file.
            log_file: Alias for log_path.
        """
        if log_file is not None:
            self.log_path = log_file
        elif log_path is not None:
            self.log_path = log_path
        else:
            self.log_path = "./data/audit/audit.jsonl"
        
        # Create parent directories if they don't exist
        os.makedirs(os.path.dirname(os.path.abspath(self.log_path)), exist_ok=True)
        
        # Ensure file exists
        if not os.path.exists(self.log_path):
            with open(self.log_path, 'a', encoding='utf-8') as f:
                pass
                
        logger.info(f"AuditLogger initialized with log path: {self.log_path}")

    def log(self, event_type: str, details: Dict[str, Any], session_id: Optional[str] = None, is_local: bool = True, bytes_processed: int = 0) -> None:
        """Log a generic event to the audit log.
        
        Args:
            event_type: The type of event.
            details: Event-specific details (metadata only, no raw user data).
            session_id: Optional session identifier.
            is_local: Whether the event occurred locally.
            bytes_processed: Number of bytes processed (if applicable).
        """
        event = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "event_type": event_type,
            "session_id": session_id,
            "is_local": is_local,
            "bytes_processed": bytes_processed,
            "details": details
        }
        
        try:
            with open(self.log_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(event) + '\n')
        except Exception as e:
            logger.error(f"Failed to write to audit log: {e}")

    def log_inference(self, model: str, prompt_tokens: int, completion_tokens: int, backend: str, session_id: Optional[str] = None, latency_ms: float = 0) -> None:
        """Log an inference event.

        Args:
            model: Name of the model used.
            prompt_tokens: Number of prompt tokens.
            completion_tokens: Number of completion tokens.
            backend: The inference backend used (e.g., 'vllm', 'ollama',
                'local_secondary', 'radeon_api', 'failed').
            session_id: Optional session identifier.
            latency_ms: Inference latency in milliseconds.
        """
        is_local = is_local_backend(backend)
        details = {
            "model": model,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "backend": backend,
            "latency_ms": latency_ms
        }
        self.log(self.EVENT_INFERENCE, details, session_id=session_id, is_local=is_local)

    def log_tool_call(self, tool_name: str, params: Dict[str, Any], result_summary: str, approved: bool = True, session_id: Optional[str] = None) -> None:
        """Log a tool execution event.
        
        Args:
            tool_name: Name of the executed tool.
            params: Parameters passed to the tool (sanitize sensitive data!).
            result_summary: Summary of the tool result.
            approved: Whether the tool execution was approved by permissions/user.
            session_id: Optional session identifier.
        """
        details = {
            "tool_name": tool_name,
            "params": params,
            "result_summary": result_summary,
            "approved": approved
        }
        self.log(self.EVENT_TOOL_CALL, details, session_id=session_id, is_local=True)

    def log_user_action(self, action: str, details: Optional[Dict[str, Any]] = None, session_id: Optional[str] = None) -> None:
        """Log a user action event (e.g., login, dashboard view).
        
        Args:
            action: Description of the user action.
            details: Additional metadata about the action.
            session_id: Optional session identifier.
        """
        if details is None:
            details = {}
        details["action"] = action
        self.log(self.EVENT_USER_ACTION, details, session_id=session_id, is_local=True)

    def get_stats(self) -> Dict[str, Any]:
        """Parse log file and calculate privacy statistics.
        
        Returns:
            Dict containing event counts and local vs external statistics.
        """
        stats = {
            "total_events": 0,
            "inference_count": 0,
            "tool_call_count": 0,
            "local_events": 0,
            "external_events": 0,
            "local_bytes": 0,
            "external_bytes": 0,
            "local_percentage": 100.0,
            "local_inferences": 0,
            "external_inferences": 0,
            "failed_inferences": 0,
            "inferences_by_backend": {},
            "inference_local_percentage": 100.0
        }
        
        if not os.path.exists(self.log_path):
            return stats
            
        try:
            with open(self.log_path, 'r', encoding='utf-8') as f:
                for line in f:
                    try:
                        event = json.loads(line.strip())
                        stats["total_events"] += 1
                        
                        if event.get("event_type") == self.EVENT_INFERENCE:
                            stats["inference_count"] += 1
                            details = event.get("details") or {}
                            backend = str(details.get("backend", "unknown"))
                            stats["inferences_by_backend"][backend] = (
                                stats["inferences_by_backend"].get(backend, 0) + 1
                            )
                            if backend == BACKEND_FAILED:
                                stats["failed_inferences"] += 1
                            elif event.get("is_local", True):
                                stats["local_inferences"] += 1
                            else:
                                stats["external_inferences"] += 1
                        elif event.get("event_type") == self.EVENT_TOOL_CALL:
                            stats["tool_call_count"] += 1
                            
                        is_local = event.get("is_local", True)
                        if is_local:
                            stats["local_events"] += 1
                            stats["local_bytes"] += event.get("bytes_processed", 0)
                        else:
                            stats["external_events"] += 1
                            stats["external_bytes"] += event.get("bytes_processed", 0)
                    except json.JSONDecodeError:
                        continue
                        
            if stats["total_events"] > 0:
                stats["local_percentage"] = (stats["local_events"] / stats["total_events"]) * 100

            inference_total = (
                stats["local_inferences"]
                + stats["external_inferences"]
                + stats["failed_inferences"]
            )
            if inference_total > 0:
                stats["inference_local_percentage"] = (
                    stats["local_inferences"] / inference_total * 100
                )
        except Exception as e:
            logger.error(f"Error reading audit log stats: {e}")
            
        return stats

    def get_recent_events(self, n: int = 10) -> List[Dict[str, Any]]:
        """Retrieve the last N events from the audit log (newest first).
        
        Args:
            n: Number of recent events to retrieve.
            
        Returns:
            List of parsed event dictionaries.
        """
        if not os.path.exists(self.log_path):
            return []
            
        events = []
        try:
            with open(self.log_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                for line in reversed(lines[-n:]):
                    try:
                        events.append(json.loads(line.strip()))
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            logger.error(f"Error reading recent events: {e}")
            
        return events

    def close(self) -> None:
        """Close resources (if any)."""
        pass
