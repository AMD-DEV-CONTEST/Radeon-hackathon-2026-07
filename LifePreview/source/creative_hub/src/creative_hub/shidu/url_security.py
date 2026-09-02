"""Fail-closed URL validation for every Shidu Reader fetch target."""

from __future__ import annotations

import ipaddress
import posixpath
import socket
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl, quote, urlencode, urljoin, urlsplit, urlunsplit


class UnsafeSourceURL(ValueError):
    """The target is not safe to hand to a network-capable Reader."""


Resolver = Callable[[str], Iterable[Any]]


@dataclass(frozen=True)
class URLSecurityPolicy:
    """Production is HTTPS-only; HTTP exists solely for isolated tests."""

    allow_http_for_tests: bool = False
    max_url_length: int = 2_048


@dataclass(frozen=True)
class ReaderURLIdentity:
    canonical_url: str
    host: str
    approved_addresses: frozenset[str]


def _system_resolver(host: str) -> Iterable[Any]:
    return socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)


def _extract_address(answer: Any) -> str:
    if isinstance(answer, (ipaddress.IPv4Address, ipaddress.IPv6Address)):
        return str(answer)
    if isinstance(answer, str):
        return answer
    if isinstance(answer, tuple) and len(answer) >= 5:
        socket_address = answer[4]
        if isinstance(socket_address, tuple) and socket_address:
            return str(socket_address[0])
    raise UnsafeSourceURL("DNS returned an invalid address")


def _resolve_global_addresses(resolver: Resolver, host: str) -> frozenset[str]:
    try:
        raw_answers = tuple(resolver(host))
    except UnsafeSourceURL:
        raise
    except Exception as error:
        raise UnsafeSourceURL("DNS resolution failed") from error
    if not raw_answers:
        raise UnsafeSourceURL("DNS returned no addresses")

    addresses: set[str] = set()
    for answer in raw_answers:
        try:
            address = ipaddress.ip_address(_extract_address(answer))
        except UnsafeSourceURL:
            raise
        except ValueError as error:
            raise UnsafeSourceURL("DNS returned an invalid address") from error
        # is_global rejects loopback, private, link-local, reserved, multicast,
        # unspecified, documentation, and shared carrier-grade NAT ranges.
        if (
            not address.is_global
            or address.is_multicast
            or address.is_reserved
            or address.is_unspecified
            or address.is_loopback
            or address.is_link_local
            or address.is_private
        ):
            raise UnsafeSourceURL("DNS resolved to a non-public address")
        addresses.add(address.compressed)
    return frozenset(addresses)


def _canonical_path(path: str) -> str:
    if not path:
        return "/"
    # Normalise dot segments without decoding escaped slashes or other reserved
    # characters. A leading slash is mandatory for an authority URL.
    normalised = posixpath.normpath(path)
    if path.endswith("/") and not normalised.endswith("/"):
        normalised += "/"
    if not normalised.startswith("/"):
        normalised = "/" + normalised
    return quote(normalised, safe="/%:@-._~!$&'()*+,;=")


def _parse_identity(url: str, policy: URLSecurityPolicy) -> tuple[str, str]:
    if not isinstance(url, str) or not url or len(url) > policy.max_url_length:
        raise UnsafeSourceURL("source URL is missing or too long")
    if any(character.isspace() or ord(character) < 32 for character in url):
        raise UnsafeSourceURL("source URL contains invalid characters")
    if "\\" in url:
        raise UnsafeSourceURL("source URL contains an ambiguous separator")

    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as error:
        raise UnsafeSourceURL("source URL authority is invalid") from error

    scheme = parts.scheme.lower()
    permitted_schemes = {"https"}
    if policy.allow_http_for_tests:
        permitted_schemes.add("http")
    if scheme not in permitted_schemes:
        raise UnsafeSourceURL("source URL scheme is not permitted")
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        raise UnsafeSourceURL("source URL credentials are not permitted")
    if not parts.hostname:
        raise UnsafeSourceURL("source URL host is required")

    try:
        host = parts.hostname.encode("idna").decode("ascii").lower().rstrip(".")
    except UnicodeError as error:
        raise UnsafeSourceURL("source URL host is invalid") from error
    if not host or host == "localhost" or host.endswith(".localhost"):
        raise UnsafeSourceURL("local hostnames are not permitted")
    if any(not label or len(label) > 63 for label in host.split(".")):
        raise UnsafeSourceURL("source URL host is invalid")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise UnsafeSourceURL("IP-literal source URLs are not permitted")

    default_port = 443 if scheme == "https" else 80
    if port is not None and port != default_port:
        raise UnsafeSourceURL("non-default source URL ports are not permitted")

    query = urlencode(sorted(parse_qsl(parts.query, keep_blank_values=True)), doseq=True)
    canonical = urlunsplit((scheme, host, _canonical_path(parts.path), query, ""))
    return canonical, host


class ReaderURLGuard:
    """Validates syntax and pins two DNS observations before a fetch."""

    def __init__(
        self,
        *,
        resolver: Resolver | None = None,
        policy: URLSecurityPolicy | None = None,
    ) -> None:
        self._resolver = resolver or _system_resolver
        self._policy = policy or URLSecurityPolicy()

    def canonicalize(self, url: str) -> str:
        """Apply static URL policy without causing a DNS/network side effect."""

        canonical_url, _host = _parse_identity(url, self._policy)
        return canonical_url

    def validate(self, url: str) -> ReaderURLIdentity:
        canonical_url, host = _parse_identity(url, self._policy)
        first = _resolve_global_addresses(self._resolver, host)
        second = _resolve_global_addresses(self._resolver, host)
        if first != second:
            raise UnsafeSourceURL("DNS answers changed before fetch")
        return ReaderURLIdentity(
            canonical_url=canonical_url,
            host=host,
            approved_addresses=first,
        )

    def validate_redirect(
        self,
        source: ReaderURLIdentity,
        location: str,
    ) -> ReaderURLIdentity:
        if not isinstance(source, ReaderURLIdentity):
            raise TypeError("source must be a ReaderURLIdentity")
        if not isinstance(location, str) or not location:
            raise UnsafeSourceURL("redirect location is invalid")
        return self.validate(urljoin(source.canonical_url, location))

    @staticmethod
    def validate_reader_attestation(
        source: ReaderURLIdentity,
        *,
        document_url: str,
        resolved_address: str,
        redirect_chain: tuple[str, ...],
        redirect_policy: str,
        prefetch_policy: str,
    ) -> None:
        """Independently bind a Reader response to the approved fetch target."""

        if not isinstance(source, ReaderURLIdentity):
            raise TypeError("source must be a ReaderURLIdentity")
        try:
            peer = ipaddress.ip_address(resolved_address).compressed
        except ValueError as error:
            raise UnsafeSourceURL("Reader attested an invalid address") from error
        if (
            document_url != source.canonical_url
            or peer not in source.approved_addresses
            or redirect_chain != (source.canonical_url,)
            or redirect_policy != "forbid"
            or prefetch_policy != "connect-approved-address-only"
        ):
            raise UnsafeSourceURL("Reader security attestation mismatch")


def validate_reader_url(
    url: str,
    *,
    resolver: Resolver | None = None,
    policy: URLSecurityPolicy | None = None,
) -> ReaderURLIdentity:
    """Convenience entry point used by callers and tests."""

    return ReaderURLGuard(resolver=resolver, policy=policy).validate(url)


__all__ = [
    "ReaderURLGuard",
    "ReaderURLIdentity",
    "Resolver",
    "UnsafeSourceURL",
    "URLSecurityPolicy",
    "validate_reader_url",
]
