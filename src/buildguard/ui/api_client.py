"""Small local-only client used by the Streamlit UI."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any, TypedDict

import httpx

from buildguard.security.network_guard import NetworkGuard


class StreamEvent(TypedDict):
    event: str
    data: dict[str, Any]


class LocalApiClient:
    def __init__(self, base_url: str, timeout_seconds: float = 30) -> None:
        self.base_url = base_url.rstrip("/")
        NetworkGuard([self.base_url]).validate(self.base_url)
        self.client = httpx.Client(base_url=self.base_url, timeout=timeout_seconds)

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        response = self.client.get(path, params=params)
        response.raise_for_status()
        return response.json()

    def post(
        self,
        path: str,
        payload: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        response = self.client.post(path, json=payload, params=params)
        response.raise_for_status()
        return response.json()

    def stream_chat(self, payload: dict[str, Any]) -> Iterator[StreamEvent]:
        """Yield validated server-sent events from the local chat endpoint."""
        timeout = httpx.Timeout(connect=10, read=60, write=30, pool=10)
        with self.client.stream(
            "POST",
            "/agent/chat/stream",
            json=payload,
            timeout=timeout,
        ) as response:
            response.raise_for_status()
            event_name = "message"
            data_lines: list[str] = []
            for line in response.iter_lines():
                if not line:
                    if data_lines:
                        raw = "\n".join(data_lines)
                        decoded = json.loads(raw)
                        if not isinstance(decoded, dict):
                            raise ValueError("Chat stream event data must be a JSON object")
                        yield {"event": event_name, "data": decoded}
                    event_name = "message"
                    data_lines = []
                    continue
                if line.startswith(":"):
                    continue
                field, _, value = line.partition(":")
                value = value.lstrip()
                if field == "event":
                    event_name = value
                elif field == "data":
                    data_lines.append(value)
            if data_lines:
                decoded = json.loads("\n".join(data_lines))
                if not isinstance(decoded, dict):
                    raise ValueError("Chat stream event data must be a JSON object")
                yield {"event": event_name, "data": decoded}

    def put(
        self,
        path: str,
        payload: dict[str, Any],
        params: dict[str, Any] | None = None,
    ) -> Any:
        response = self.client.put(path, json=payload, params=params)
        response.raise_for_status()
        return response.json()

    def delete(
        self,
        path: str,
        payload: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        response = self.client.request("DELETE", path, json=payload, params=params)
        response.raise_for_status()
        return response.json()

    def get_bytes(
        self,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> tuple[bytes, str]:
        response = self.client.get(path, params=params)
        response.raise_for_status()
        disposition = response.headers.get(
            "content-disposition",
            'attachment; filename="buildguard-export.bin"',
        )
        filename = disposition.split("filename=", 1)[-1].strip('"')
        return response.content, filename

    def upload_images(self, uploads: list[Any]) -> Any:
        files = [
            (
                "files",
                (
                    upload.name,
                    upload.getvalue(),
                    upload.type or "application/octet-stream",
                ),
            )
            for upload in uploads
        ]
        response = self.client.post("/uploads/images", files=files)
        response.raise_for_status()
        return response.json()

    def upload_videos(self, uploads: list[Any]) -> Any:
        files = [
            (
                "files",
                (
                    upload.name,
                    upload.getvalue(),
                    upload.type or "application/octet-stream",
                ),
            )
            for upload in uploads
        ]
        response = self.client.post("/uploads/videos", files=files)
        response.raise_for_status()
        return response.json()

    def upload_documents(self, uploads: list[Any], project: str | None = None) -> Any:
        files = [
            (
                "files",
                (
                    upload.name,
                    upload.getvalue(),
                    upload.type or "application/octet-stream",
                ),
            )
            for upload in uploads
        ]
        response = self.client.post(
            "/rag/documents/upload",
            files=files,
            params={"project": project} if project else None,
        )
        response.raise_for_status()
        return response.json()
