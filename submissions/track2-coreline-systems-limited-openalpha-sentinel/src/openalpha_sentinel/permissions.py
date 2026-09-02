from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit

from .config import Settings
from .database import Database


class PermissionGate:
    def __init__(self, settings: Settings, database: Database):
        self.settings = settings
        self.database = database

    def is_offline(self) -> bool:
        return bool(self.database.preferences().get("offline_mode", self.settings.offline))

    def set_offline(self, enabled: bool) -> None:
        self.database.set_preference("offline_mode", enabled)
        self.database.audit("offline_mode_changed", {"enabled": enabled})

    def allowed_domains(self) -> list[str]:
        extra = self.database.preferences().get("allowed_domains", [])
        return sorted(set(self.settings.allowed_domains).union(str(item).lower() for item in extra))

    def grant_domain(self, domain: str) -> None:
        clean = domain.strip().lower().lstrip(".")
        if not clean:
            raise ValueError("domain must not be empty")
        domains = self.database.preferences().get("allowed_domains", [])
        if clean not in domains:
            domains.append(clean)
            self.database.set_preference("allowed_domains", domains)
        self.database.audit("domain_granted", {"domain": clean})

    def check_url(self, url: str, *, allow_explicit_feed: bool = False) -> None:
        if self.is_offline():
            raise PermissionError("OpenAlpha Sentinel is in offline mode")
        try:
            parsed = urlsplit(url)
        except ValueError as exc:
            raise PermissionError("Source URL is malformed") from exc
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            raise PermissionError("Only absolute HTTP(S) URLs are allowed")
        if parsed.username is not None or parsed.password is not None:
            raise PermissionError("Credentials are not allowed in source URLs")

        host = parsed.hostname.lower().rstrip(".")
        try:
            port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
        except ValueError as exc:
            raise PermissionError("Source URL contains an invalid port") from exc
        approved = any(
            host == domain or host.endswith(f".{domain}")
            for domain in self.allowed_domains()
        )
        if not allow_explicit_feed and not approved:
            raise PermissionError(f"Domain is not approved: {host}")

        self._check_public_destination(host, port)
        if allow_explicit_feed:
            self.grant_domain(host)

    @staticmethod
    def _check_public_destination(host: str, port: int) -> None:
        try:
            literal = ipaddress.ip_address(host)
            addresses = {literal}
        except ValueError:
            try:
                resolved = socket.getaddrinfo(
                    host,
                    port,
                    type=socket.SOCK_STREAM,
                )
            except socket.gaierror as exc:
                raise PermissionError(f"Could not resolve source domain: {host}") from exc
            addresses = {
                ipaddress.ip_address(item[4][0].split("%", 1)[0])
                for item in resolved
            }

        if not addresses:
            raise PermissionError(f"Could not resolve source domain: {host}")
        unsafe = sorted(str(address) for address in addresses if not address.is_global)
        if unsafe:
            raise PermissionError(
                f"Source domain resolves to a non-public address: {host} ({', '.join(unsafe)})"
            )
