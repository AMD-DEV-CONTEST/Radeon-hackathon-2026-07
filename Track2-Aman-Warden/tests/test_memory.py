"""Tests for SQLite Audit Log."""

import os
from warden.memory.audit_log import AuditLog
from warden.tiers.base import SecurityEvent
from warden.config import Decision, ContentSource, TrustLevel

class TestAuditLog:
    def setup_method(self):
        self.db_path = "test_audit.db"
        self.log = AuditLog(db_path=self.db_path)
        self.log.initialize()

    def teardown_method(self):
        self.log.close()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_log_event(self):
        event = SecurityEvent(
            input_hash="hash123",
            input_preview="preview",
            source=ContentSource.USER_DIRECT.value,
            trust_level=TrustLevel.TRUSTED.value,
            tier_reached=0,
            decision=Decision.BLOCK.value,
            confidence=0.9,
            latency_ms=1.5
        )
        event_id = self.log.log_event(event)
        assert event_id > 0

    def test_mark_auto_block(self):
        event = SecurityEvent(
            input_hash="hash_to_block",
            input_preview="preview",
            source=ContentSource.USER_DIRECT.value,
            trust_level=TrustLevel.TRUSTED.value,
            tier_reached=0,
            decision=Decision.BLOCK.value,
            confidence=0.9,
            latency_ms=1.5
        )
        self.log.log_event(event)
        
        # Mark as auto-block
        assert self.log.mark_auto_block("hash_to_block")
        assert self.log.is_known_blocked("hash_to_block")

    def test_is_known_safe(self):
        event = SecurityEvent(
            input_hash="hash_safe",
            input_preview="preview",
            source=ContentSource.USER_DIRECT.value,
            trust_level=TrustLevel.TRUSTED.value,
            tier_reached=0,
            decision=Decision.ALLOW.value,
            confidence=0.1,
            latency_ms=1.5
        )
        # Log 3 times to make it safe
        self.log.log_event(event)
        self.log.log_event(event)
        self.log.log_event(event)
        
        assert self.log.is_known_safe("hash_safe")
