from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from .artifacts import (
    ArtifactCorrupt,
    ArtifactMediaTypeRejected,
    ArtifactNotFound,
    ArtifactResolver,
    ResolvedArtifact,
    iter_file_range,
)


SAFE_BROWSER_MEDIA_TYPES = frozenset(
    {
        "video/mp4",
        "video/webm",
        "audio/wav",
        "audio/mpeg",
        "image/png",
        "image/jpeg",
        "image/webp",
        "application/x-subrip",
        "text/vtt",
    }
)


def _range_status_label(status_code: int) -> str:
    if 500 <= status_code <= 599:
        return "5xx"
    return str(status_code)


@dataclass(frozen=True, slots=True)
class ByteRange:
    start: int
    end: int

    @property
    def length(self) -> int:
        return self.end - self.start + 1


class RangeNotSatisfiable(ValueError):
    pass


def parse_single_range(value: str, size: int) -> ByteRange:
    if size <= 0 or not value.startswith("bytes="):
        raise RangeNotSatisfiable
    specification = value[6:].strip()
    if not specification or "," in specification or "-" not in specification:
        raise RangeNotSatisfiable
    raw_start, raw_end = specification.split("-", 1)

    try:
        if raw_start:
            start = int(raw_start)
            end = int(raw_end) if raw_end else size - 1
            if start < 0 or end < start or start >= size:
                raise RangeNotSatisfiable
            return ByteRange(start=start, end=min(end, size - 1))

        suffix = int(raw_end)
        if suffix <= 0:
            raise RangeNotSatisfiable
        suffix = min(suffix, size)
        return ByteRange(start=size - suffix, end=size - 1)
    except (TypeError, ValueError) as exc:
        if isinstance(exc, RangeNotSatisfiable):
            raise
        raise RangeNotSatisfiable from exc


def _etag(artifact: ResolvedArtifact) -> str:
    return f'"sha256-{artifact.ref.sha256}"'


def _base_headers(artifact: ResolvedArtifact) -> dict[str, str]:
    return {
        "Accept-Ranges": "bytes",
        "Cache-Control": "private, max-age=31536000, immutable",
        "Content-Type": artifact.ref.mime,
        "ETag": _etag(artifact),
        "X-Content-Type-Options": "nosniff",
    }


def create_artifact_router(
    resolver: ArtifactResolver,
    *,
    observability: "object | None" = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/artifacts", tags=["artifacts"])

    def _record(status_code: int) -> None:
        recorder = getattr(observability, "record_artifact_range_request", None)
        if recorder is None:
            return
        recorder(status=_range_status_label(status_code))

    @router.api_route(
        "/{owner}/{artifact_id}",
        methods=["GET", "HEAD"],
        name="read_artifact",
    )
    def read_artifact(
        owner: str,
        artifact_id: str,
        request: Request,
    ) -> Response:
        try:
            identity = UUID(artifact_id)
            artifact = resolver.resolve_identity(owner, identity)
        except (ValueError, ArtifactNotFound):
            _record(404)
            return JSONResponse(
                status_code=404,
                content={"detail": "artifact unavailable"},
            )
        except ArtifactMediaTypeRejected:
            _record(415)
            return JSONResponse(
                status_code=415,
                content={"detail": "artifact media type is not allowed"},
            )
        except ArtifactCorrupt:
            _record(409)
            return JSONResponse(
                status_code=409,
                content={"detail": "artifact unavailable"},
            )

        if artifact.ref.mime not in SAFE_BROWSER_MEDIA_TYPES:
            _record(415)
            return JSONResponse(
                status_code=415,
                content={"detail": "artifact media type is not allowed"},
            )

        headers = _base_headers(artifact)
        etag = headers["ETag"]
        if request.headers.get("if-none-match") == etag:
            _record(304)
            return Response(status_code=304, headers={"ETag": etag})

        selected_range: ByteRange | None = None
        range_header = request.headers.get("range")
        if range_header and request.headers.get("if-range", etag) == etag:
            try:
                selected_range = parse_single_range(
                    range_header,
                    artifact.ref.bytes,
                )
            except RangeNotSatisfiable:
                _record(416)
                return JSONResponse(
                    status_code=416,
                    content={"detail": "range not satisfiable"},
                    headers={
                        "Accept-Ranges": "bytes",
                        "Content-Range": f"bytes */{artifact.ref.bytes}",
                        "ETag": etag,
                    },
                )

        if selected_range is None:
            start = 0
            length = artifact.ref.bytes
            status_code = 200
        else:
            start = selected_range.start
            length = selected_range.length
            status_code = 206
            headers["Content-Range"] = (
                f"bytes {selected_range.start}-{selected_range.end}/"
                f"{artifact.ref.bytes}"
            )
        headers["Content-Length"] = str(length)

        if request.method == "HEAD":
            _record(status_code)
            return Response(status_code=status_code, headers=headers)

        _record(status_code)
        return StreamingResponse(
            iter_file_range(
                artifact.path,
                start=start,
                length=length,
                chunk_size=resolver.chunk_size,
            ),
            status_code=status_code,
            headers=headers,
            media_type=None,
        )

    return router
