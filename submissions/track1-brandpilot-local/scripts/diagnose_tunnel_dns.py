#!/usr/bin/env python3
"""Run privacy-aware DNS, TCP, TLS, and HTTPS diagnostics for rc-tunnel."""

from __future__ import annotations

import argparse
import copy
import ipaddress
import json
import os
import platform
import re
import socket
import ssl
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REDACTED_HOSTNAME = "<redacted-radeon-tunnel-hostname>"
REDACTED_ADDRESS = "<redacted-address>"
CLASSIFICATIONS = {
    "dns_resolved_https_reachable",
    "dns_resolved_tcp_failed",
    "dns_resolved_tls_failed",
    "dns_resolution_failed",
    "http_unreachable",
    "invalid_hostname",
    "diagnostic_error",
}
_HOSTNAME_RE = re.compile(
    r"(?=^.{1,253}\.?$)(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+"
    r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.?"
)
_IPV4_RE = re.compile(r"(?<![\w:])(?:\d{1,3}\.){3}\d{1,3}(?![\w:])")
_IPV6_RE = re.compile(
    r"(?<![\w:])(?:[0-9a-fA-F]{1,4}:){2,7}[0-9a-fA-F]{0,4}(?![\w:])"
)


class DiagnosticError(RuntimeError):
    """A safe, user-facing diagnostic failure."""


def valid_hostname(value: str) -> bool:
    if not value or value != value.strip():
        return False
    if "://" in value or any(character in value for character in "/\\?#@"):
        return False
    try:
        ipaddress.ip_address(value.rstrip("."))
        return False
    except ValueError:
        pass
    return _HOSTNAME_RE.fullmatch(value) is not None


def safe_error_message(error: BaseException, hostname: str) -> str:
    message = str(error) or error.__class__.__name__
    if hostname:
        message = re.sub(
            re.escape(hostname), REDACTED_HOSTNAME, message, flags=re.I
        )
    message = _IPV4_RE.sub(REDACTED_ADDRESS, message)
    message = _IPV6_RE.sub(REDACTED_ADDRESS, message)
    return message[:500]


def resolve_hostname(hostname: str, port: int) -> list[tuple[Any, ...]]:
    return socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)


def open_tcp(
    addresses: list[tuple[Any, ...]], timeout: float
) -> tuple[socket.socket, tuple[Any, ...]]:
    last_error: OSError | None = None
    for family, socktype, protocol, _canonical_name, sockaddr in addresses:
        connection = socket.socket(family, socktype, protocol)
        connection.settimeout(timeout)
        try:
            connection.connect(sockaddr)
            return connection, sockaddr
        except OSError as error:
            last_error = error
            connection.close()
    raise last_error or OSError("No resolved address accepted a TCP connection")


def perform_tls_http(
    connection: socket.socket, hostname: str, timeout: float
) -> dict[str, Any]:
    context = ssl.create_default_context()
    with context.wrap_socket(connection, server_hostname=hostname) as secure:
        secure.settimeout(timeout)
        request = (
            f"HEAD / HTTP/1.1\r\nHost: {hostname}\r\n"
            "User-Agent: BrandPilot-DNS-Diagnostic/1.0\r\n"
            "Connection: close\r\n\r\n"
        ).encode("ascii")
        secure.sendall(request)
        response = secure.recv(4096)
        first_line = response.split(b"\r\n", 1)[0].decode("ascii", "replace")
        match = re.match(r"^HTTP/\d(?:\.\d)?\s+(\d{3})(?:\s|$)", first_line)
        if not match:
            raise DiagnosticError("HTTPS endpoint returned no valid HTTP status")
        return {
            "tls_version": secure.version(),
            "certificate_validation": True,
            "http_status": int(match.group(1)),
        }


def _base_report(hostname: str, port: int, timeout: float) -> dict[str, Any]:
    now_utc = datetime.now(timezone.utc)
    now_local = now_utc.astimezone()
    return {
        "timestamp_utc": now_utc.isoformat(),
        "timestamp_local": now_local.isoformat(),
        "python_version": platform.python_version(),
        "operating_system": platform.platform(),
        "hostname": hostname,
        "port": port,
        "timeout_seconds": timeout,
        "dns_resolved": False,
        "ipv4_available": False,
        "ipv6_available": False,
        "resolved_addresses": [],
        "dns_error_type": None,
        "dns_error_code": None,
        "dns_error_message": None,
        "tcp_attempted": False,
        "tcp_connected": False,
        "tcp_error_type": None,
        "tcp_error_message": None,
        "tls_attempted": False,
        "tls_version": None,
        "certificate_validation": False,
        "tls_error_type": None,
        "tls_error_message": None,
        "http_attempted": False,
        "http_status": None,
        "http_error_type": None,
        "http_error_message": None,
        "total_duration_seconds": 0.0,
        "final_classification": "diagnostic_error",
    }


def diagnose(hostname: str, port: int = 443, timeout: float = 10.0) -> dict[str, Any]:
    started = time.monotonic()
    report = _base_report(hostname, port, timeout)
    connection: socket.socket | None = None
    try:
        if not valid_hostname(hostname) or not 1 <= port <= 65535 or timeout <= 0:
            report["final_classification"] = "invalid_hostname"
            return report

        try:
            addresses = resolve_hostname(hostname, port)
        except socket.gaierror as error:
            report.update(
                dns_error_type=error.__class__.__name__,
                dns_error_code=getattr(error, "errno", None),
                dns_error_message=str(error),
                final_classification="dns_resolution_failed",
            )
            return report
        except Exception as error:
            report.update(
                dns_error_type=error.__class__.__name__,
                dns_error_code=getattr(error, "errno", None),
                dns_error_message=str(error),
                final_classification="diagnostic_error",
            )
            return report

        report["dns_resolved"] = bool(addresses)
        report["ipv4_available"] = any(item[0] == socket.AF_INET for item in addresses)
        report["ipv6_available"] = any(item[0] == socket.AF_INET6 for item in addresses)
        report["resolved_addresses"] = sorted(
            {
                str(item[4][0])
                for item in addresses
                if item[0] in {socket.AF_INET, socket.AF_INET6}
            }
        )
        if not addresses:
            report["final_classification"] = "dns_resolution_failed"
            return report

        report["tcp_attempted"] = True
        try:
            connection, _sockaddr = open_tcp(addresses, timeout)
            report["tcp_connected"] = True
        except OSError as error:
            report.update(
                tcp_error_type=error.__class__.__name__,
                tcp_error_message=str(error),
                final_classification="dns_resolved_tcp_failed",
            )
            return report

        report["tls_attempted"] = True
        report["http_attempted"] = True
        try:
            tls_result = perform_tls_http(connection, hostname, timeout)
            report.update(tls_result)
            report["final_classification"] = "dns_resolved_https_reachable"
        except ssl.SSLError as error:
            report.update(
                tls_error_type=error.__class__.__name__,
                tls_error_message=str(error),
                final_classification="dns_resolved_tls_failed",
            )
        except (OSError, DiagnosticError) as error:
            report.update(
                http_error_type=error.__class__.__name__,
                http_error_message=str(error),
                final_classification="http_unreachable",
            )
        except Exception as error:
            report.update(
                http_error_type=error.__class__.__name__,
                http_error_message=str(error),
                final_classification="diagnostic_error",
            )
        return report
    finally:
        if connection is not None:
            connection.close()
        report["total_duration_seconds"] = round(time.monotonic() - started, 3)


def sanitized_report(report: dict[str, Any]) -> dict[str, Any]:
    sanitized = copy.deepcopy(report)
    hostname = str(report.get("hostname") or "")
    sanitized["hostname"] = REDACTED_HOSTNAME
    sanitized.pop("resolved_addresses", None)
    for key, value in tuple(sanitized.items()):
        if key.endswith("_message") and value:
            sanitized[key] = safe_error_message(
                RuntimeError(str(value)), hostname
            )
    return sanitized


def validate_output_path(
    value: str, *, private: bool, repository_root: Path | None = None
) -> Path:
    candidate = Path(value).expanduser()
    if ".." in candidate.parts:
        raise DiagnosticError("Output path traversal is not allowed")
    if candidate.suffix.lower() != ".json":
        raise DiagnosticError("Output report must use a .json filename")
    resolved = candidate.resolve()
    root = (repository_root or Path.cwd()).resolve()
    if private:
        try:
            resolved.relative_to(root)
        except ValueError:
            pass
        else:
            raise DiagnosticError(
                "Private output must be stored outside the repository"
            )
    return resolved


def write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, sort_keys=True)
            handle.write("\n")
        try:
            temporary.chmod(0o600)
        except OSError:
            pass
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Diagnose an official Radeon tunnel hostname without weakening TLS "
            "or changing local networking."
        )
    )
    parser.add_argument("--hostname", required=True, help="Private assigned hostname")
    parser.add_argument("--port", type=int, default=443)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument(
        "--output-private",
        help="Absolute .json path outside the repository; may contain hostname",
    )
    parser.add_argument(
        "--output-sanitized",
        help="Safe .json report path with hostname and addresses removed",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        private_path = (
            validate_output_path(args.output_private, private=True)
            if args.output_private
            else None
        )
        sanitized_path = (
            validate_output_path(args.output_sanitized, private=False)
            if args.output_sanitized
            else None
        )
        if private_path and sanitized_path and private_path == sanitized_path:
            raise DiagnosticError("Private and sanitized outputs must differ")
        report = diagnose(args.hostname, args.port, args.timeout)
        if private_path:
            write_report(private_path, report)
        if sanitized_path:
            write_report(sanitized_path, sanitized_report(report))
        print(f"classification={report['final_classification']}")
        return 0 if report["final_classification"] in CLASSIFICATIONS else 1
    except DiagnosticError as error:
        print(f"diagnostic_error={safe_error_message(error, args.hostname)}", file=sys.stderr)
        return 2
    except Exception:
        print("diagnostic_error=Unable to write diagnostic report safely", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
