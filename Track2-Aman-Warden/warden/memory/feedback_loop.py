from warden.memory.audit_log import AuditLog
import logging

logger = logging.getLogger(__name__)

class FeedbackLoop:
    """
    Handles user overrides and feedback to correct the system's memory.
    
    If an input was incorrectly auto-blocked, the user can override it.
    The FeedbackLoop adjusts the SQLite memory so the system learns 
    not to block it in the future.
    """
    def __init__(self, audit_log: AuditLog):
        self.audit_log = audit_log

    def record_override(self, input_hash: str, expected_decision: str, actual_decision: str) -> bool:
        """
        Record a user override for a specific input hash.
        
        Args:
            input_hash: The SHA-256 hash of the input text
            expected_decision: What the user says the decision SHOULD have been ('allow')
            actual_decision: What the system actually decided ('block')
            
        Returns:
            True if successfully updated, False otherwise.
        """
        if not self.audit_log._conn:
            return False
            
        logger.info(f"Feedback loop triggered for {input_hash[:8]}: user override {actual_decision} -> {expected_decision}")

        with self.audit_log._lock:
            cursor = self.audit_log._conn.cursor()
            if expected_decision == "allow" and actual_decision == "block":
                # User is marking a blocked pattern as safe
                cursor.execute("""
                    UPDATE patterns 
                    SET auto_block = 0, last_decision = 'allow', times_seen = times_seen + 1
                    WHERE input_hash = ?
                """, (input_hash,))
                
                # If the pattern wasn't in the DB, we insert it as safe
                if cursor.rowcount == 0:
                    cursor.execute("""
                        INSERT INTO patterns (input_hash, first_seen, times_seen, last_decision, auto_block)
                        VALUES (?, datetime('now'), 1, 'allow', 0)
                    """, (input_hash,))
                    
            elif expected_decision == "block" and actual_decision == "allow":
                # User is marking a safe pattern as blocked
                cursor.execute("""
                    UPDATE patterns 
                    SET auto_block = 1, last_decision = 'block', times_seen = times_seen + 1
                    WHERE input_hash = ?
                """, (input_hash,))
                
                if cursor.rowcount == 0:
                    cursor.execute("""
                        INSERT INTO patterns (input_hash, first_seen, times_seen, last_decision, auto_block)
                        VALUES (?, datetime('now'), 1, 'block', 1)
                    """, (input_hash,))
                    
            self.audit_log._conn.commit()
            return True
