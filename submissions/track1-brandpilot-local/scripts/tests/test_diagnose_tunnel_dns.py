from __future__ import annotations

import json
import socket
import ssl
from pathlib import Path

import pytest

from scripts import diagnose_tunnel_dns as diagnostic


HOSTNAME = "assigned.example.test"
IPV4 = (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.0.2.10", 443))
IPV6 = (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2001:db8::10", 443, 0, 0))


def test_invalid_hostname_does_not_resolve(monkeypatch):
    monkeypatch.setattr(
        diagnostic,
        "resolve_hostname",
        lambda *_: pytest.fail("invalid hostname must not reach DNS"),
    )
    report = diagnostic.diagnose("https://unsafe.example.test/path")
    assert report["final_classification"] == "invalid_hostname"


def test_dns_resolution_failure_is_safely_redacted(monkeypatch):
    def fail(*_):
        raise socket.gaierror(11001, f"{HOSTNAME} did not resolve")

    monkeypatch.setattr(diagnostic, "resolve_hostname", fail)
    report = diagnostic.diagnose(HOSTNAME)
    sanitized = diagnostic.sanitized_report(report)
    assert report["final_classification"] == "dns_resolution_failed"
    assert sanitized["hostname"] == diagnostic.REDACTED_HOSTNAME
    assert HOSTNAME not in json.dumps(sanitized)


@pytest.mark.parametrize(
    ("addresses", "ipv4", "ipv6"),
    [([IPV4], True, False), ([IPV6], False, True), ([IPV4, IPV6], True, True)],
)
def test_ipv4_and_ipv6_availability(monkeypatch, addresses, ipv4, ipv6):
    monkeypatch.setattr(diagnostic, "resolve_hostname", lambda *_: addresses)
    monkeypatch.setattr(
        diagnostic, "open_tcp", lambda *_: (_ for _ in ()).throw(OSError("closed"))
    )
    report = diagnostic.diagnose(HOSTNAME)
    assert report["ipv4_available"] is ipv4
    assert report["ipv6_available"] is ipv6
    assert diagnostic.sanitized_report(report).get("resolved_addresses") is None


def test_tcp_failure_classification(monkeypatch):
    monkeypatch.setattr(diagnostic, "resolve_hostname", lambda *_: [IPV4])
    monkeypatch.setattr(
        diagnostic,
        "open_tcp",
        lambda *_: (_ for _ in ()).throw(ConnectionRefusedError("refused")),
    )
    report = diagnostic.diagnose(HOSTNAME)
    assert report["final_classification"] == "dns_resolved_tcp_failed"
    assert report["tls_attempted"] is False


def test_tls_validation_failure(monkeypatch):
    connection = FakeConnection()
    monkeypatch.setattr(diagnostic, "resolve_hostname", lambda *_: [IPV4])
    monkeypatch.setattr(diagnostic, "open_tcp", lambda *_: (connection, IPV4[4]))
    monkeypatch.setattr(
        diagnostic,
        "perform_tls_http",
        lambda *_: (_ for _ in ()).throw(
            ssl.SSLCertVerificationError("certificate verify failed")
        ),
    )
    report = diagnostic.diagnose(HOSTNAME)
    assert report["final_classification"] == "dns_resolved_tls_failed"
    assert report["certificate_validation"] is False


def test_https_success(monkeypatch):
    connection = FakeConnection()
    monkeypatch.setattr(diagnostic, "resolve_hostname", lambda *_: [IPV4])
    monkeypatch.setattr(diagnostic, "open_tcp", lambda *_: (connection, IPV4[4]))
    monkeypatch.setattr(
        diagnostic,
        "perform_tls_http",
        lambda *_: {
            "tls_version": "TLSv1.3",
            "certificate_validation": True,
            "http_status": 401,
        },
    )
    report = diagnostic.diagnose(HOSTNAME)
    assert report["final_classification"] == "dns_resolved_https_reachable"
    assert report["http_status"] == 401


def test_default_tls_context_is_required(monkeypatch):
    source = Path(diagnostic.__file__).read_text(encoding="utf-8")
    assert "ssl.create_default_context()" in source
    assert "_create_unverified_context" not in source
    assert "CERT_NONE" not in source


def test_unexpected_exception_output_is_safe(monkeypatch):
    monkeypatch.setattr(
        diagnostic,
        "resolve_hostname",
        lambda *_: (_ for _ in ()).throw(
            RuntimeError(f"failure for {HOSTNAME} at 192.0.2.10")
        ),
    )
    sanitized = diagnostic.sanitized_report(diagnostic.diagnose(HOSTNAME))
    encoded = json.dumps(sanitized)
    assert HOSTNAME not in encoded
    assert "192.0.2.10" not in encoded
    assert sanitized["final_classification"] == "diagnostic_error"


@pytest.mark.parametrize(
    "value", ["../private.json", "reports/../../private.json", "report.txt"]
)
def test_output_path_traversal_and_unsafe_extensions_are_rejected(value):
    with pytest.raises(diagnostic.DiagnosticError):
        diagnostic.validate_output_path(value, private=False)


def test_private_output_must_be_outside_repository(tmp_path, monkeypatch):
    repository = tmp_path / "repo"
    repository.mkdir()
    with pytest.raises(diagnostic.DiagnosticError):
        diagnostic.validate_output_path(
            str(repository / "private.json"),
            private=True,
            repository_root=repository,
        )
    outside = tmp_path / "private" / "report.json"
    assert diagnostic.validate_output_path(
        str(outside), private=True, repository_root=repository
    ) == outside.resolve()


def test_written_sanitized_report_has_no_hostname_or_addresses(tmp_path):
    report = diagnostic._base_report(HOSTNAME, 443, 10)
    report["resolved_addresses"] = ["192.0.2.10"]
    report["dns_error_message"] = f"{HOSTNAME} 192.0.2.10"
    output = tmp_path / "sanitized.json"
    diagnostic.write_report(output, diagnostic.sanitized_report(report))
    content = output.read_text(encoding="utf-8")
    assert HOSTNAME not in content
    assert "192.0.2.10" not in content


def test_powershell_wrapper_preserves_windows_networking_and_tls():
    source = (Path(diagnostic.__file__).with_name("diagnose_tunnel_dns.ps1")).read_text(
        encoding="utf-8"
    )
    assert "Resolve-DnsName" in source
    assert "Test-NetConnection" in source
    assert "curl.exe" in source
    for unsafe in (
        "--insecure",
        "curl -k",
        "Clear-DnsClientCache",
        "Set-DnsClientServerAddress",
        "Set-ItemProperty",
        "netsh",
    ):
        assert unsafe not in source


class FakeConnection:
    def close(self):
        return None
