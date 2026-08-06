from __future__ import annotations

import asyncio
from typing import Any

import httpx


class EverOSError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        path: str,
        status_code: int | None = None,
        request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.path = path
        self.status_code = status_code
        self.request_id = request_id


class EverOSClient:
    def __init__(
        self,
        *,
        http: httpx.AsyncClient | None = None,
        base_url: str = "http://127.0.0.1:8001",
        app_id: str = "ai-glasses",
        project_id: str = "work-memory",
        timeout_seconds: float = 60.0,
    ) -> None:
        self.app_id = app_id
        self.project_id = project_id
        self._owns_http = http is None
        self._http = http
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds

    async def close(self) -> None:
        if self._owns_http and self._http is not None:
            await self._http.aclose()
            self._http = None

    @property
    def http(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout_seconds,
            )
        return self._http

    async def health(self) -> dict[str, Any]:
        return await self._request("GET", "/health")

    async def add_messages(
        self,
        session_id: str,
        messages: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/api/v1/memory/add",
            json={
                "session_id": session_id,
                "app_id": self.app_id,
                "project_id": self.project_id,
                "messages": messages,
            },
        )

    async def flush(self, session_id: str) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/api/v1/memory/flush",
            json={
                "session_id": session_id,
                "app_id": self.app_id,
                "project_id": self.project_id,
            },
        )

    async def search(
        self,
        user_id: str,
        query: str,
        *,
        top_k: int = 5,
        include_profile: bool = True,
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/api/v1/memory/search",
            json={
                "user_id": user_id,
                "app_id": self.app_id,
                "project_id": self.project_id,
                "query": query,
                "method": "hybrid",
                "top_k": top_k,
                "include_profile": include_profile,
            },
        )

    async def get_episodes(
        self,
        user_id: str,
        *,
        page: int = 1,
        page_size: int = 20,
        filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "user_id": user_id,
            "app_id": self.app_id,
            "project_id": self.project_id,
            "memory_type": "episode",
            "page": page,
            "page_size": page_size,
            "sort_by": "timestamp",
            "sort_order": "desc",
        }
        if filters:
            payload["filters"] = filters
        return await self._request("POST", "/api/v1/memory/get", json=payload)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        for attempt in range(3):
            try:
                response = await self.http.request(method, path, json=json)
            except httpx.TransportError as exc:
                if attempt == 2:
                    raise EverOSError(str(exc), path=path) from exc
                await asyncio.sleep(0.05 * (2**attempt))
                continue

            if response.is_success:
                return response.json()

            retryable = response.status_code == 429 or response.status_code >= 500
            if retryable and attempt < 2:
                await asyncio.sleep(0.05 * (2**attempt))
                continue

            request_id = response.headers.get("x-request-id")
            if not request_id:
                try:
                    payload = response.json()
                except ValueError:
                    payload = {}
                request_id = payload.get("request_id")
            raise EverOSError(
                f"EverOS request failed with HTTP {response.status_code}",
                path=path,
                status_code=response.status_code,
                request_id=request_id,
            )

        raise EverOSError("EverOS request exhausted retries", path=path)
