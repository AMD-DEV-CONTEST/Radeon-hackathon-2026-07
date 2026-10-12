import pytest
from unittest.mock import patch, MagicMock
import json

from warden.guards.diff_guard import DiffGuard
from warden.tiers.base import VulnerabilityFinding


def test_diff_guard_semgrep_hit():
    """Test that DiffGuard successfully parses a Semgrep JSON output alongside AST findings."""
    guard = DiffGuard(llm_tier=None)

    # Mock Semgrep subprocess output with an exec finding
    mock_semgrep_output = {
        "results": [
            {
                "check_id": "python.lang.security.audit.exec-use.exec-use",
                "path": "test.py",
                "start": {"line": 10},
                "extra": {
                    "message": "Use of exec detected.",
                    "severity": "HIGH",
                    "metadata": {"cwe": "CWE-94"},
                },
            }
        ]
    }

    with patch("subprocess.run") as mock_run:
        mock_result = MagicMock()
        mock_result.stdout = json.dumps(mock_semgrep_output)
        mock_run.return_value = mock_result

        scan_result = guard.scan_diff("def test():\n    exec('print(1)')")

        assert scan_result.has_findings is True
        # AST will also catch exec(), so scanner includes ast_static_analysis
        assert "semgrep" in scan_result.scanner
        # At least the semgrep finding is present (AST may add its own)
        semgrep_vulns = [v for v in scan_result.vulnerabilities if v.source == "semgrep"]
        assert len(semgrep_vulns) >= 1
        assert semgrep_vulns[0].vuln_type == "python.lang.security.audit.exec-use.exec-use"
        assert semgrep_vulns[0].severity == "high"
        assert semgrep_vulns[0].line == 10
        assert semgrep_vulns[0].source == "semgrep"


def test_diff_guard_no_findings():
    """Test DiffGuard with a clean diff that has no vuln patterns."""
    guard = DiffGuard(llm_tier=None, escalation_threshold=50)

    with patch("subprocess.run") as mock_run:
        mock_result = MagicMock()
        mock_result.stdout = '{"results": []}'
        mock_run.return_value = mock_result

        # A truly benign diff - no dangerous patterns
        scan_result = guard.scan_diff("def greet(name: str) -> str:\n    return f'Hello, {name}!'")

        assert scan_result.has_findings is False
        assert scan_result.scanner == "none"


def test_diff_guard_escalate_to_llm():
    """Test DiffGuard escalating to LLM when diff is large."""
    mock_llm = MagicMock()
    mock_llm.is_available.return_value = True
    guard = DiffGuard(llm_tier=mock_llm, escalation_threshold=5)

    with patch.object(guard, "_run_semgrep", return_value=[]):
        with patch.object(guard, "_run_llm_scan") as mock_llm_scan:
            mock_llm_scan.return_value = [
                VulnerabilityFinding(vuln_type="IDOR", severity="high", source="llm")
            ]

            # Benign comment-only diff with > 5 ADDED lines (+ prefix = counted as added)
            large_diff = "\n".join([f"+ # comment line {i}" for i in range(10)])
            scan_result = guard.scan_diff(large_diff)

            assert scan_result.has_findings is True
            assert "llm" in scan_result.scanner
            assert scan_result.vulnerabilities[0].vuln_type == "IDOR"
