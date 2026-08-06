from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen
from uuid import UUID

from fastapi import APIRouter, Request as FastAPIRequest
from fastapi.responses import JSONResponse, Response, StreamingResponse

from .media_gateway import SAFE_BROWSER_MEDIA_TYPES


FORWARDED_REQUEST_HEADERS = (
    "Range",
    "If-Range",
    "If-None-Match",
)
FORWARDED_RESPONSE_HEADERS = (
    "Accept-Ranges",
    "Cache-Control",
    "Content-Length",
    "Content-Range",
    "Content-Type",
    "ETag",
    "X-Content-Type-Options",
)


class ArtifactProxyError(RuntimeError):
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(f"artifact proxy failed with {status_code}")


@dataclass(slots=True)
class RemoteArtifact:
    status_code: int
    headers: dict[str, str]
    body: Iterator[bytes] | None


class ArtifactGateway(Protocol):
    def open(
        self,
        owner: str,
        artifact_id: UUID,
        *,
        method: str,
        headers: dict[str, str],
    ) -> RemoteArtifact: ...


class HttpArtifactGateway:
    """Bounded streaming adapter for the authenticated Analysis media API."""

    def __init__(
        self,
        base_url: str,
        *,
        service_token: str,
        allowed_hosts: frozenset[str] | None = None,
        timeout_seconds: float = 30.0,
        chunk_size: int = 64 * 1024,
    ) -> None:
        parsed = urlsplit(base_url)
        accepted = allowed_hosts or frozenset(
            {"127.0.0.1", "localhost", "::1"}
        )
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.hostname not in accepted
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ValueError("Analysis artifact gateway host is not allowed")
        if not service_token:
            raise ValueError("Analysis service token is required")
        if timeout_seconds <= 0 or chunk_size <= 0:
            raise ValueError("artifact gateway bounds must be positive")
        self._base_url = base_url.rstrip("/")
        self._service_token = service_token
        self._timeout_seconds = timeout_seconds
        self._chunk_size = chunk_size

    def open(
        self,
        owner: str,
        artifact_id: UUID,
        *,
        method: str,
        headers: dict[str, str],
    ) -> RemoteArtifact:
        upstream_headers = {
            "X-Internal-Service-Token": self._service_token,
            **{
                name: value
                for name, value in headers.items()
                if name in FORWARDED_REQUEST_HEADERS
            },
        }
        request = Request(
            f"{self._base_url}/api/v1/artifacts/"
            f"{quote(owner, safe='')}/{artifact_id}",
            headers=upstream_headers,
            method=method,
        )
        try:
            response = urlopen(request, timeout=self._timeout_seconds)
        except HTTPError as exc:
            status_code = exc.code
            response_headers = {
                name: value
                for name in FORWARDED_RESPONSE_HEADERS
                if (value := exc.headers.get(name)) is not None
            }
            exc.close()
            if status_code in {304, 404, 409, 415, 416}:
                return RemoteArtifact(status_code, response_headers, None)
            raise ArtifactProxyError(502) from None
        except (OSError, URLError, ValueError):
            raise ArtifactProxyError(503) from None

        response_headers = {
            name: value
            for name in FORWARDED_RESPONSE_HEADERS
            if (value := response.headers.get(name)) is not None
        }
        media_type = response_headers.get("Content-Type", "").split(
            ";", 1
        )[0]
        if media_type not in SAFE_BROWSER_MEDIA_TYPES:
            response.close()
            raise ArtifactProxyError(415)
        if method == "HEAD":
            response.close()
            return RemoteArtifact(response.status, response_headers, None)

        def chunks() -> Iterator[bytes]:
            with response:
                while chunk := response.read(self._chunk_size):
                    yield chunk

        return RemoteArtifact(response.status, response_headers, chunks())


def _metric_status(status_code: int) -> str:
    return "5xx" if 500 <= status_code <= 599 else str(status_code)


def create_artifact_proxy_router(
    gateway: ArtifactGateway, *, observability: object | None = None
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/artifacts", tags=["artifacts"])

    def _record(status_code: int) -> None:
        recorder = getattr(observability, "record_artifact_range_request", None)
        if recorder is not None:
            recorder(status=_metric_status(status_code))

    @router.api_route(
        "/{owner}/{artifact_id}",
        methods=["GET", "HEAD"],
        name="proxy_artifact",
    )
    def proxy_artifact(
        owner: str,
        artifact_id: UUID,
        request: FastAPIRequest,
    ) -> Response:
        try:
            remote = gateway.open(
                owner,
                artifact_id,
                method=request.method,
                headers={
                    name: value
                    for name in FORWARDED_REQUEST_HEADERS
                    if (value := request.headers.get(name)) is not None
                },
            )
        except ArtifactProxyError as exc:
            _record(exc.status_code)
            return JSONResponse(
                status_code=exc.status_code,
                content={"detail": "artifact unavailable"},
            )
        if remote.status_code not in {200, 206}:
            _record(remote.status_code)
            return Response(
                status_code=remote.status_code,
                headers=remote.headers,
            )
        if request.method == "HEAD":
            _record(remote.status_code)
            return Response(
                status_code=remote.status_code,
                headers=remote.headers,
            )
        if remote.body is None:
            _record(502)
            return JSONResponse(
                status_code=502,
                content={"detail": "artifact unavailable"},
            )
        _record(remote.status_code)
        return StreamingResponse(
            remote.body,
            status_code=remote.status_code,
            headers=remote.headers,
            media_type=None,
        )

    return router
