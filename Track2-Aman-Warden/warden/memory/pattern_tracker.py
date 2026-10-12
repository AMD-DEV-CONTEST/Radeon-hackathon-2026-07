"""
Pattern Tracker for identifying repeat attack vectors.

Monitors incoming attack signatures and upon reaching a repetition threshold
(default: 3 blocks), triggers permanent DB persistence via mark_auto_block.
This enables the instant memory shortcut in Intelligent Routing.
"""

from __future__ import annotations

import logging
import threading
from typing import Optional

from warden.config import Decision
from warden.memory.audit_log import AuditLog

logger = logging.getLogger(__name__)


class PatternTracker:
    """Tracks repeating threat signatures to activate automatic blocking."""

    def __init__(self, audit_log: Optional[AuditLog] = None, block_threshold: int = 3):
        self.audit_log = audit_log
        self.block_threshold = block_threshold
        self._counts: dict[str, int] = {}
        self._lock = threading.Lock()

        # Perform cross-session sweep to activate any auto-blocks from past sessions
        if self.audit_log and hasattr(self.audit_log, 'sweep_repeat_offenders'):
            try:
                swept = self.audit_log.sweep_repeat_offenders(threshold=self.block_threshold)
                if swept > 0:
                    logger.info(f"Cross-session sweep activated {swept} pending repeat offenders.")
            except Exception as e:
                logger.warning(f"Failed to sweep repeat offenders: {e}")

    def record(self, content_hash: str, decision: Decision, explanation: str = "") -> bool:
        """
        Record a routed decision for a content hash.
        If blocked >= block_threshold times, mark in AuditLog for instant auto-blocking.

        Returns:
            True if newly auto-blocked, False otherwise.
        """
        if decision != Decision.BLOCK or not self.audit_log:
            return False

        with self._lock:
            # Query cross-process SQLite database for the true count
            count = self.audit_log.get_pattern_count(content_hash)
            
            # Note: The count was already incremented by log_event() before this is called
            # We also keep an in-memory cache just for stats if needed
            self._counts[content_hash] = count
            logger.debug(f"Pattern {content_hash[:8]} blocked {count}/{self.block_threshold} times")

            if count >= self.block_threshold:
                if not self.audit_log.is_known_blocked(content_hash):
                    logger.info(f"Threshold reached! Auto-blocking repeat pattern {content_hash[:8]}")
                    self.audit_log.mark_auto_block(
                        input_hash=content_hash,
                        reason=f"Repeated attack vector (blocked {count} times): {explanation}",
                    )
                    return True
        return False

    def get_count(self, content_hash: str) -> int:
        if self.audit_log:
            return self.audit_log.get_pattern_count(content_hash)
        with self._lock:
            return self._counts.get(content_hash, 0)

    def reset(self):
        with self._lock:
            self._counts.clear()
