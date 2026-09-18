"""Network destination allowlist."""

from __future__ import annotations

import ipaddress
from urllib.parse import urlparse

from buildguard.exceptions import EndpointSecurityError


class NetworkGuard:
    """Allow only explicitly configured local service origins."""

    def __init__(self, allowed_endpoints: list[str], allowed_lan_cidrs: list[str] | None = None) -> None:
        self.allowed_origins = {self._origin(endpoint) for endpoint in allowed_endpoints}
        self.allowed_lan_cidrs = [
            ipaddress.ip_network(value, strict=False) for value in (allowed_lan_cidrs or [])
        ]

    @staticmethod
    def _origin(url: str) -> tuple[str, str, int | None]:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise EndpointSecurityError("Endpoint must be a valid HTTP(S) URL")
        return parsed.scheme, parsed.hostname.lower(), parsed.port

    def validate(self, url: str) -> None:
        origin = self._origin(url)
        if origin not in self.allowed_origins:
            raise EndpointSecurityError("Network destination is not a configured local service")
        host = origin[1]
        if host == "localhost":
            return
        try:
            address = ipaddress.ip_address(host)
        except ValueError as exc:
            raise EndpointSecurityError("Non-local hostnames are blocked") from exc
        if address.is_loopback:
            return
        if any(address in network for network in self.allowed_lan_cidrs):
            return
        raise EndpointSecurityError("Public and unapproved LAN addresses are blocked")

