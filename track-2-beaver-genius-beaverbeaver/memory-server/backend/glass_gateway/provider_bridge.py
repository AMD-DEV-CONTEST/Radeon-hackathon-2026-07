from __future__ import annotations

"""Local protocol bridge for EverOS; all model inference remains remote."""

from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request

from glass_gateway.config import get_settings


app = FastAPI(title="Beaver Memory Provider Protocol Bridge", version="1")


def _require_loopback(request: Request) -> None:
    host = request.client.host if request.client else ""
    if host not in {"127.0.0.1", "::1", "localhost", "testclient"}:
        raise HTTPException(status_code=403, detail="loopback access only")


async def _post_remote(
    url: str,
    payload: dict[str, Any],
    *,
    api_key: str,
    key_name: str,
) -> dict[str, Any]:
    settings = get_settings()
    if not api_key:
        raise HTTPException(status_code=503, detail=f"{key_name} is not configured")
    try:
        async with httpx.AsyncClient(
            timeout=settings.memory_search_model_timeout_seconds,
            trust_env=False,
        ) as client:
            response = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        response.raise_for_status()
        value = response.json()
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:300]
        raise HTTPException(
            status_code=502,
            detail=f"remote provider HTTP {exc.response.status_code}: {detail}",
        ) from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(
            status_code=502,
            detail=f"remote provider failed: {type(exc).__name__}",
        ) from exc
    if not isinstance(value, dict):
        raise HTTPException(status_code=502, detail="remote provider returned non-object JSON")
    return value


@app.get("/healthz")
async def healthz(request: Request) -> dict[str, str]:
    _require_loopback(request)
    return {"status": "ok"}


@app.post("/v1/embeddings")
async def embeddings(request: Request, body: dict[str, Any]) -> dict[str, Any]:
    _require_loopback(request)
    settings = get_settings()
    raw_input = body.get("input")
    texts = raw_input if isinstance(raw_input, list) else [raw_input]
    if not texts or any(not isinstance(value, str) or not value.strip() for value in texts):
        raise HTTPException(status_code=422, detail="input must be text or a non-empty text list")
    payload = {
        "model": settings.memory_search_embedding_model,
        "input": {"contents": [{"text": value} for value in texts]},
        "parameters": {"dimension": 1024},
    }
    remote = await _post_remote(
        settings.memory_search_embedding_url,
        payload,
        api_key=settings.memory_search_embedding_api_key,
        key_name="MEMORY_SEARCH_EMBEDDING_API_KEY",
    )
    output = remote.get("output")
    rows = output.get("embeddings") if isinstance(output, dict) else None
    if not isinstance(rows, list) or len(rows) != len(texts):
        raise HTTPException(status_code=502, detail="remote embedding response is invalid")
    data = []
    for index, row in enumerate(rows):
        vector = row.get("embedding") if isinstance(row, dict) else None
        if not isinstance(vector, list) or len(vector) != 1024:
            raise HTTPException(status_code=502, detail="remote embedding dimension is not 1024")
        data.append({"object": "embedding", "index": index, "embedding": vector})
    return {
        "object": "list",
        "model": settings.memory_search_embedding_model,
        "data": data,
        "usage": remote.get("usage") or {},
    }


@app.post("/v1/rerank")
async def rerank(request: Request, body: dict[str, Any]) -> dict[str, Any]:
    _require_loopback(request)
    settings = get_settings()
    query = body.get("query")
    documents = body.get("documents")
    if not isinstance(query, str) or not query.strip():
        raise HTTPException(status_code=422, detail="query must be non-empty text")
    if not isinstance(documents, list) or not documents:
        raise HTTPException(status_code=422, detail="documents must be a non-empty list")
    normalized_documents: list[dict[str, str]] = []
    for document in documents:
        text = document if isinstance(document, str) else document.get("text") if isinstance(document, dict) else None
        if not isinstance(text, str) or not text.strip():
            raise HTTPException(status_code=422, detail="every document must contain text")
        normalized_documents.append({"text": text})
    top_n = int(body.get("top_n") or len(normalized_documents))
    payload = {
        "model": settings.memory_search_reranker_model,
        "input": {
            "query": {"text": query},
            "documents": normalized_documents,
        },
        "parameters": {
            "return_documents": bool(body.get("return_documents", True)),
            "top_n": min(max(1, top_n), len(normalized_documents)),
        },
    }
    remote = await _post_remote(
        settings.memory_search_reranker_url,
        payload,
        api_key=settings.memory_search_reranker_api_key,
        key_name="MEMORY_SEARCH_RERANKER_API_KEY",
    )
    output = remote.get("output")
    results = output.get("results") if isinstance(output, dict) else None
    if not isinstance(results, list):
        raise HTTPException(status_code=502, detail="remote rerank response is invalid")
    return {
        "id": remote.get("request_id") or remote.get("id"),
        "model": settings.memory_search_reranker_model,
        "results": results,
        "usage": remote.get("usage") or {},
    }
