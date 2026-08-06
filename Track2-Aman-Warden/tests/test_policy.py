"""Tests for Policy Engine."""

from warden.guards.policy import PolicyEngine


class TestPolicyEngine:
    def setup_method(self):
        self.engine = PolicyEngine()
        # Mocking rules for tests
        self.engine.rules = [
            {
                "name": "block-secret",
                "match": {"patterns": ["AKIA[A-Z0-9]{16}"]},
                "action": "block"
            },
            {
                "name": "flag-network",
                "match": {"imports_any": ["requests"]},
                "action": "flag"
            },
            {
                "name": "allow-test",
                "match": {"patterns": ["test_pattern"]},
                "action": "allow"
            }
        ]
        self.engine._loaded = True

    def test_evaluate_blocks_on_pattern(self):
        result = self.engine.evaluate("My key is AKIAIOSFODNN7EXAMPLE")
        assert result is not None
        assert result["decision"] == "block"
        assert result["is_definitive"]

    def test_evaluate_flags_on_import(self):
        result = self.engine.evaluate("import requests")
        assert result is not None
        assert result["decision"] == "flag"
        assert not result["is_definitive"]

    def test_evaluate_allows_on_pattern(self):
        result = self.engine.evaluate("Here is a test_pattern")
        assert result is not None
        assert result["decision"] == "allow"
        assert result["is_definitive"]

    def test_evaluate_none_on_no_match(self):
        result = self.engine.evaluate("This is safe text")
        assert result is None

    def test_evaluate_tool_call_match(self):
        # Add a tool call rule
        self.engine.rules.append({
            "name": "block-destructive-tool",
            "scope": "tool_calls",
            "match": {
                "tool_name": {"any_of": ["delete_file", "rmdir"]},
                "args": {"path_matches": ["/etc/*"]}
            },
            "action": "block",
            "message": "Destructive operation"
        })
        
        # Should match tool name and path
        result = self.engine.evaluate_tool_call("delete_file", {"path": "/etc/passwd"})
        assert result is not None
        assert result["decision"] == "block"
        
        # Should not match tool name
        result_safe1 = self.engine.evaluate_tool_call("read_file", {"path": "/etc/passwd"})
        assert result_safe1 is None
        
        # Should not match path
        result_safe2 = self.engine.evaluate_tool_call("delete_file", {"path": "/var/log/syslog"})
        assert result_safe2 is None
