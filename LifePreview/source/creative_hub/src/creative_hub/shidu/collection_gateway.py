"""Strict client contract for the internal Shidu collection route."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from http.client import HTTPConnection, HTTPSConnection
from typing import Protocol
from urllib.parse import urlencode, urlsplit


COLLECTION_ROUTE = "/internal/shidu/collection-videos"
MAX_COLLECTION_PAGE = 10_000
MAX_COLLECTION_COUNT = 50
MAX_RESPONSE_BYTES = 1_000_000


class CollectionGatewayError(RuntimeError):
    pass


@dataclass(frozen=True)
class CollectionVideo:
    video_id: str
    public_title: str
    public_description: str
    collection_id: str

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


class CollectionGateway(Protocol):
    def list_videos(
        self, *, page: int = 0, count: int = 20
    ) -> tuple[CollectionVideo, ...]: ...


def _bounded_integer(value: int, *, low: int, high: int, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f"{label} must be between {low} and {high}")
    return value


def _parse_video(item: object) -> CollectionVideo:
    if not isinstance(item, dict) or set(item) != {
        "video_id",
        "public_title",
        "public_description",
        "collection_id",
    }:
        raise CollectionGatewayError("collection response contract is invalid")
    limits = {
        "video_id": 200,
        "public_title": 500,
        "public_description": 5_000,
        "collection_id": 200,
    }
    for key, maximum in limits.items():
        value = item[key]
        if not isinstance(value, str) or len(value) > maximum:
            raise CollectionGatewayError("collection response contract is invalid")
    if not item["video_id"] or not item["collection_id"]:
        raise CollectionGatewayError("collection response contract is invalid")
    return CollectionVideo(**item)


class HttpCollectionGateway:
    def __init__(
        self,
        base_url: str,
        *,
        control_token: str,
        allowed_hosts: frozenset[str] = frozenset(
            {"upstream-api", "127.0.0.1", "localhost", "::1"}
        ),
        timeout_seconds: float = 5.0,
    ) -> None:
        parsed = urlsplit(base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.hostname not in allowed_hosts
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("collection gateway endpoint is not allowed")
        if not control_token or control_token != control_token.strip():
            raise ValueError("collection gateway control token is invalid")
        self._scheme = parsed.scheme
        self._host = parsed.hostname
        self._port = parsed.port or (443 if parsed.scheme == "https" else 80)
        self._control_token = control_token
        self._timeout_seconds = timeout_seconds

    def list_videos(
        self, *, page: int = 0, count: int = 20
    ) -> tuple[CollectionVideo, ...]:
        page = _bounded_integer(
            page, low=0, high=MAX_COLLECTION_PAGE, label="page"
        )
        count = _bounded_integer(
            count, low=1, high=MAX_COLLECTION_COUNT, label="count"
        )
        connection_type = HTTPSConnection if self._scheme == "https" else HTTPConnection
        connection = connection_type(
            self._host, self._port, timeout=self._timeout_seconds
        )
        path = f"{COLLECTION_ROUTE}?{urlencode({'page': page, 'count': count})}"
        try:
            connection.request(
                "GET",
                path,
                headers={
                    "Authorization": f"Bearer {self._control_token}",
                    "Accept": "application/json",
                },
            )
            response = connection.getresponse()
            body = response.read(MAX_RESPONSE_BYTES + 1)
            if response.status != 200 or len(body) > MAX_RESPONSE_BYTES:
                raise CollectionGatewayError("collection service is unavailable")
            payload = json.loads(body.decode("utf-8"))
        except CollectionGatewayError:
            raise
        except (OSError, UnicodeError, json.JSONDecodeError):
            raise CollectionGatewayError("collection service is unavailable") from None
        finally:
            connection.close()
        if not isinstance(payload, list) or len(payload) > MAX_COLLECTION_COUNT:
            raise CollectionGatewayError("collection response contract is invalid")
        videos = tuple(_parse_video(item) for item in payload)
        if len(videos) > count:
            raise CollectionGatewayError("collection response exceeded requested count")
        return videos


__all__ = [
    "COLLECTION_ROUTE",
    "CollectionGateway",
    "CollectionGatewayError",
    "CollectionVideo",
    "HttpCollectionGateway",
    "MAX_COLLECTION_COUNT",
    "MAX_COLLECTION_PAGE",
]
