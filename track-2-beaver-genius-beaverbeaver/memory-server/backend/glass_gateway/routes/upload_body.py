from __future__ import annotations

import asyncio

from fastapi import HTTPException, Request, status


async def read_upload_body(
    request: Request,
    *,
    timeout_seconds: float,
    media_label: str,
) -> bytes:
    """Read a device upload without allowing a partial body to hang forever."""

    try:
        return await asyncio.wait_for(
            request.body(),
            timeout=max(0.1, timeout_seconds),
        )
    except TimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_408_REQUEST_TIMEOUT,
            detail=f"{media_label} upload body timed out",
        ) from exc
