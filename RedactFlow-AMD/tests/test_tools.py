from app.tools import redact_text, scan_sensitive


def test_scan_and_redact_multiple_secret_types() -> None:
    source = "Mail a@example.com, call 13800138000, connect 10.24.8.16, key sk-demo1234567890123456"
    findings = scan_sensitive(source)
    kinds = {finding["kind"] for finding in findings}
    assert {"email", "phone", "ipv4", "api_key"} <= kinds
    redacted = redact_text(source, findings)
    assert "a@example.com" not in redacted
    assert "[PHONE]" in redacted
    assert "[IP_ADDRESS]" in redacted

