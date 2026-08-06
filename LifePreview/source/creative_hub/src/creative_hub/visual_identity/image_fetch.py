"""Fail-closed fetch and decode boundary for discovered identity images."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from io import BytesIO
import ipaddress
import json
import socket
import ssl
from typing import Any, Callable
from urllib.parse import urlsplit

import httpx
import httpcore
from PIL import Image, UnidentifiedImageError


_ALLOWED_HOSTS = frozenset({"upload.wikimedia.org"})
_ALLOWED_MIME = frozenset({"image/jpeg", "image/png", "image/webp"})
_MAX_RAW_BYTES = 20_000_000
_MAX_DIMENSION = 8_192
_MAX_PIXELS = 40_000_000


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_sha256(value: Any) -> str:
    return _sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )


def _require_sha256(value: str, field_name: str) -> None:
    if (
        type(value) is not str
        or len(value) != 64
        or any(ch not in "0123456789abcdef" for ch in value)
    ):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")


class ImageFetchRetryableError(RuntimeError):
    """A transport or DNS failure that leaves the candidate unresolved."""

    failed_stage = "fetch"

    def __init__(self, safe_error_code: str) -> None:
        self.safe_error_code = safe_error_code
        super().__init__(f"image fetch failed: {safe_error_code}")


class ImageFetchSecurityError(ValueError):
    """A terminal security or content-policy rejection for one candidate."""


@dataclass(frozen=True, slots=True)
class SecureImageFetchResult:
    candidate_id: str
    canonical_url: str
    canonical_locator_sha256: str
    approved_ip_addresses: tuple[str, ...]
    resolved_peer_ip: str
    redirects_observed: int
    connect_approved_only: bool
    credentials_forbidden: bool
    http_status: int
    declared_mime_type: str
    magic_mime_type: str
    raw_byte_size: int
    fully_decoded: bool
    width_px: int
    height_px: int
    decoded_pixels: int
    frame_count: int
    raw_bytes: bytes
    sanitized_bytes: bytes
    raw_sha256: str
    sanitized_sha256: str
    artifact_id: str
    request_sha256: str
    response_sha256: str
    fetch_sha256: str


class _CoreResponseStream(httpx.SyncByteStream):
    def __init__(self, stream: Any) -> None:
        self._stream = stream

    def __iter__(self):
        yield from self._stream

    def close(self) -> None:
        self._stream.close()


class _PinnedNetworkBackend(httpcore.NetworkBackend):
    """Connects the approved hostname only to the pre-resolved public IP set."""

    def __init__(self, *, expected_host: str, approved_ip_addresses: tuple[str, ...]) -> None:
        self._expected_host = expected_host
        self._approved_ip_addresses = approved_ip_addresses
        self._delegate = httpcore.SyncBackend()

    def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Any = None,
    ) -> httpcore.NetworkStream:
        if host != self._expected_host or port != 443:
            raise httpcore.ConnectError("transport origin is outside the approved fence")
        last_error: Exception | None = None
        for approved_ip in self._approved_ip_addresses:
            try:
                return self._delegate.connect_tcp(
                    approved_ip,
                    port,
                    timeout=timeout,
                    local_address=local_address,
                    socket_options=socket_options,
                )
            except httpcore.ConnectError as exc:
                last_error = exc
        raise httpcore.ConnectError("all approved image peers were unavailable") from last_error

    def connect_unix_socket(self, *args: Any, **kwargs: Any) -> httpcore.NetworkStream:
        raise httpcore.ConnectError("Unix sockets are forbidden for image fetch")


class _PinnedHTTPTransport(httpx.BaseTransport):
    """Small synchronous transport that preserves TLS SNI while pinning TCP IP."""

    def __init__(self, *, expected_host: str, approved_ip_addresses: tuple[str, ...]) -> None:
        ssl_context = ssl.create_default_context()
        backend = _PinnedNetworkBackend(
            expected_host=expected_host,
            approved_ip_addresses=approved_ip_addresses,
        )
        self._pool = httpcore.ConnectionPool(
            ssl_context=ssl_context,
            max_connections=1,
            max_keepalive_connections=0,
            http1=True,
            http2=False,
            retries=0,
            network_backend=backend,
        )
        self._approved = approved_ip_addresses

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if not isinstance(request.stream, httpx.SyncByteStream):
            raise TypeError("pinned transport requires a synchronous request stream")
        core_request = httpcore.Request(
            method=request.method,
            url=httpcore.URL(
                scheme=request.url.raw_scheme,
                host=request.url.raw_host,
                port=request.url.port,
                target=request.url.raw_path,
            ),
            headers=request.headers.raw,
            content=request.stream,
            extensions=request.extensions,
        )
        try:
            core_response = self._pool.handle_request(core_request)
        except httpcore.TimeoutException as exc:
            raise httpx.TimeoutException(str(exc), request=request) from exc
        except (httpcore.NetworkError, httpcore.ProtocolError) as exc:
            raise httpx.TransportError(str(exc), request=request) from exc
        extensions = dict(core_response.extensions)
        network_stream = extensions.get("network_stream")
        server_addr = (
            network_stream.get_extra_info("server_addr")
            if network_stream is not None
            else None
        )
        if not isinstance(server_addr, tuple) or not server_addr:
            core_response.close()
            raise httpx.TransportError("connected peer address is unavailable", request=request)
        peer = ipaddress.ip_address(server_addr[0]).compressed
        if peer not in self._approved:
            core_response.close()
            raise httpx.TransportError("connected peer escaped the approved IP fence", request=request)
        extensions["resolved_peer_ip"] = peer
        extensions["connect_approved_only"] = True
        return httpx.Response(
            status_code=core_response.status,
            headers=core_response.headers,
            stream=_CoreResponseStream(core_response.stream),
            extensions=extensions,
        )

    def close(self) -> None:
        self._pool.close()


class SecureImageFetcher:
    """Fetches a Wikimedia image through an IP-pinning-aware HTTP transport.

    The supplied transport must consume the ``approved_ip_addresses`` request
    extension and attest the connected peer in the response extensions. A plain
    HTTP transport cannot make those guarantees and therefore fails closed.
    """

    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        resolver: Callable[[str], tuple[str, ...]] | None = None,
    ) -> None:
        if client is not None and not isinstance(client, httpx.Client):
            raise TypeError("client must be an httpx.Client")
        self._client = client
        self._resolver = resolver or self._resolve_host

    def fetch(
        self,
        candidate_id: str,
        canonical_url: str,
        canonical_locator_sha256: str,
    ) -> SecureImageFetchResult:
        if type(candidate_id) is not str or not candidate_id.strip():
            raise ValueError("candidate_id must be non-empty")
        _require_sha256(canonical_locator_sha256, "canonical_locator_sha256")
        host = self._validate_url(canonical_url)
        approved = self._resolve_public_addresses(host)
        request_payload = {
            "method": "GET",
            "canonical_url": canonical_url,
            "canonical_locator_sha256": canonical_locator_sha256,
            "approved_ip_addresses": approved,
            "redirects_forbidden": True,
            "credentials_forbidden": True,
            "max_raw_bytes": _MAX_RAW_BYTES,
        }
        request_sha256 = _canonical_sha256(request_payload)

        owned_client = self._client is None
        client = self._client or httpx.Client(
            transport=_PinnedHTTPTransport(
                expected_host=host,
                approved_ip_addresses=approved,
            ),
            timeout=httpx.Timeout(20.0),
            trust_env=False,
            follow_redirects=False,
        )
        try:
            with client.stream(
                "GET",
                canonical_url,
                headers={
                    "Accept": "image/jpeg, image/png, image/webp",
                    "Accept-Encoding": "identity",
                },
                follow_redirects=False,
                extensions={"approved_ip_addresses": approved},
            ) as response:
                if response.status_code in range(300, 400) or response.history:
                    raise ImageFetchSecurityError("redirects are forbidden")
                if response.status_code == 429 or response.status_code >= 500:
                    raise ImageFetchRetryableError("provider_unavailable")
                if response.status_code != 200:
                    raise ImageFetchSecurityError("unexpected HTTP status")
                content_encoding = response.headers.get("Content-Encoding", "identity").lower()
                if content_encoding not in {"", "identity"}:
                    raise ImageFetchSecurityError("encoded image responses are forbidden")
                peer = response.extensions.get("resolved_peer_ip")
                pinned = response.extensions.get("connect_approved_only")
                if pinned is not True or not isinstance(peer, str):
                    raise ImageFetchSecurityError(
                        "pinned transport peer attestation is required"
                    )
                self._validate_peer(peer, approved)

                declared = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
                if declared not in _ALLOWED_MIME:
                    raise ImageFetchSecurityError("declared MIME type is not allowed")
                content_length = response.headers.get("Content-Length")
                if content_length:
                    try:
                        declared_length = int(content_length)
                    except ValueError as exc:
                        raise ImageFetchSecurityError("invalid Content-Length") from exc
                    if declared_length < 0 or declared_length > _MAX_RAW_BYTES:
                        raise ImageFetchSecurityError("image exceeds byte limit")

                chunks: list[bytes] = []
                total = 0
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > _MAX_RAW_BYTES:
                        raise ImageFetchSecurityError("image exceeds byte limit")
                    chunks.append(chunk)
                body = b"".join(chunks)
                if not body:
                    raise ImageFetchSecurityError("empty image response")
                if content_length and len(body) != declared_length:
                    raise ImageFetchSecurityError("Content-Length mismatch")
                response_sha256 = _canonical_sha256(
                    {
                        "status": response.status_code,
                        "content_type": declared,
                        "content_length": len(body),
                        "raw_sha256": _sha256(body),
                        "resolved_peer_ip": peer,
                    }
                )
        except (ImageFetchSecurityError, ImageFetchRetryableError):
            raise
        except httpx.HTTPError as exc:
            raise ImageFetchRetryableError("transport_failure") from exc
        finally:
            if owned_client:
                client.close()

        magic_mime = self._magic_mime(body)
        if magic_mime != declared:
            raise ImageFetchSecurityError("declared MIME does not match image magic")
        width, height, frames, sanitized = self._decode_and_sanitize(body, magic_mime)
        raw_sha = _sha256(body)
        sanitized_sha = _sha256(sanitized)
        artifact_id = f"{candidate_id}.sanitized.{sanitized_sha[:16]}"
        fetch_payload = {
            "candidate_id": candidate_id,
            "canonical_url": canonical_url,
            "canonical_locator_sha256": canonical_locator_sha256,
            "approved_ip_addresses": approved,
            "resolved_peer_ip": peer,
            "http_status": 200,
            "declared_mime_type": declared,
            "magic_mime_type": magic_mime,
            "raw_byte_size": len(body),
            "fully_decoded": True,
            "width_px": width,
            "height_px": height,
            "decoded_pixels": width * height,
            "frame_count": frames,
            "raw_sha256": raw_sha,
            "sanitized_sha256": sanitized_sha,
            "artifact_id": artifact_id,
            "request_sha256": request_sha256,
            "response_sha256": response_sha256,
        }
        return SecureImageFetchResult(
            candidate_id=candidate_id,
            canonical_url=canonical_url,
            canonical_locator_sha256=canonical_locator_sha256,
            approved_ip_addresses=approved,
            resolved_peer_ip=peer,
            redirects_observed=0,
            connect_approved_only=True,
            credentials_forbidden=True,
            http_status=200,
            declared_mime_type=declared,
            magic_mime_type=magic_mime,
            raw_byte_size=len(body),
            fully_decoded=True,
            width_px=width,
            height_px=height,
            decoded_pixels=width * height,
            frame_count=frames,
            raw_bytes=body,
            sanitized_bytes=sanitized,
            raw_sha256=raw_sha,
            sanitized_sha256=sanitized_sha,
            artifact_id=artifact_id,
            request_sha256=request_sha256,
            response_sha256=response_sha256,
            fetch_sha256=_canonical_sha256(fetch_payload),
        )

    @staticmethod
    def _validate_url(value: str) -> str:
        if type(value) is not str or "\\" in value:
            raise ImageFetchSecurityError("canonical URL is invalid")
        parsed = urlsplit(value)
        host = parsed.hostname.lower() if parsed.hostname else ""
        if (
            parsed.scheme != "https"
            or host not in _ALLOWED_HOSTS
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port not in (None, 443)
            or parsed.query
            or parsed.fragment
            or not parsed.path.startswith("/")
            or "/../" in f"{parsed.path}/"
        ):
            raise ImageFetchSecurityError("canonical URL is not approved")
        return host

    def _resolve_public_addresses(self, host: str) -> tuple[str, ...]:
        try:
            values = self._resolver(host)
        except (OSError, socket.gaierror) as exc:
            raise ImageFetchRetryableError("dns_failure") from exc
        if not isinstance(values, tuple) or not values:
            raise ImageFetchRetryableError("dns_failure")
        canonical: set[str] = set()
        for value in values:
            try:
                address = ipaddress.ip_address(value)
            except ValueError as exc:
                raise ImageFetchSecurityError("DNS returned a non-IP address") from exc
            if not self._is_public_unicast(address):
                raise ImageFetchSecurityError("DNS address must be public")
            canonical.add(address.compressed)
        return tuple(sorted(canonical))

    @staticmethod
    def _validate_peer(peer: str, approved: tuple[str, ...]) -> None:
        try:
            canonical = ipaddress.ip_address(peer)
        except ValueError as exc:
            raise ImageFetchSecurityError("connected peer is not an IP address") from exc
        if not SecureImageFetcher._is_public_unicast(canonical) or canonical.compressed not in approved:
            raise ImageFetchSecurityError("connected peer is not an approved public IP")

    @staticmethod
    def _is_public_unicast(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
        if (
            not address.is_global
            or address.is_multicast
            or address.is_unspecified
            or address.is_loopback
            or address.is_link_local
            or address.is_private
            or address.is_reserved
        ):
            return False
        if isinstance(address, ipaddress.IPv6Address):
            if address.is_site_local:
                return False
            if address.ipv4_mapped is not None:
                return SecureImageFetcher._is_public_unicast(address.ipv4_mapped)
        return True

    @staticmethod
    def _resolve_host(host: str) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    entry[4][0]
                    for entry in socket.getaddrinfo(
                        host,
                        443,
                        family=socket.AF_UNSPEC,
                        type=socket.SOCK_STREAM,
                    )
                }
            )
        )

    @staticmethod
    def _magic_mime(body: bytes) -> str:
        if body.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png"
        if body.startswith(b"\xff\xd8\xff"):
            return "image/jpeg"
        if len(body) >= 12 and body[:4] == b"RIFF" and body[8:12] == b"WEBP":
            return "image/webp"
        raise ImageFetchSecurityError("unsupported image MIME magic")

    @staticmethod
    def _decode_and_sanitize(body: bytes, mime_type: str) -> tuple[int, int, int, bytes]:
        try:
            with Image.open(BytesIO(body)) as opened:
                frames = int(getattr(opened, "n_frames", 1))
                width, height = opened.size
                if frames != 1:
                    raise ImageFetchSecurityError("animated or multi-frame image is forbidden")
                if (
                    width <= 0
                    or height <= 0
                    or width > _MAX_DIMENSION
                    or height > _MAX_DIMENSION
                    or width * height > _MAX_PIXELS
                ):
                    raise ImageFetchSecurityError("decoded image dimensions exceed limits")
                opened.verify()
            with Image.open(BytesIO(body)) as decoded:
                decoded.load()
                clean = decoded.copy()
        except ImageFetchSecurityError:
            raise
        except (OSError, SyntaxError, ValueError, UnidentifiedImageError) as exc:
            raise ImageFetchSecurityError("image failed full decode") from exc

        output = BytesIO()
        try:
            if mime_type == "image/png":
                clean.save(output, format="PNG", optimize=False)
            elif mime_type == "image/jpeg":
                clean.convert("RGB").save(
                    output,
                    format="JPEG",
                    quality=95,
                    optimize=False,
                    progressive=False,
                )
            else:
                clean.save(output, format="WEBP", lossless=True, method=4)
        finally:
            clean.close()
        sanitized = output.getvalue()
        if not sanitized:
            raise ImageFetchSecurityError("image sanitization failed")
        return width, height, frames, sanitized


__all__ = [
    "ImageFetchRetryableError",
    "ImageFetchSecurityError",
    "SecureImageFetcher",
    "SecureImageFetchResult",
]

