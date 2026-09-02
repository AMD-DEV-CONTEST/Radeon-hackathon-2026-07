"""Regression tests proving production model paths use the Stage J queue."""

from __future__ import annotations

import asyncio

import httpx

from app.config import Settings
from app.llm.client import LLMClient
from app.rag.embedder import LLMEmbedder
from app.services import task_queue as queue_module
from app.services.task_queue import TaskQueue


def _reset_queue(settings: Settings) -> TaskQueue:
    queue = TaskQueue(settings)
    queue_module._task_queue_instance = queue
    return queue


def test_project_scoped_llm_request_uses_runtime_queue() -> None:
    settings = Settings(global_max_concurrent_llm_calls=1)
    queue = _reset_queue(settings)
    transport = httpx.MockTransport(
        lambda _: httpx.Response(200, json={"choices": [{"message": {"content": "queued"}}]})
    )

    result = asyncio.run(
        LLMClient(settings, transport=transport).generate_text("hello", project_id="project-a")
    )

    assert result == "queued"
    assert queue.stats.total_completed == 1
    assert queue.stats.active_llm_calls == 0


def test_project_scoped_embedding_request_uses_runtime_queue() -> None:
    settings = Settings(global_max_concurrent_embedding_calls=1)
    queue = _reset_queue(settings)
    embedder = LLMEmbedder("http://embedding.local/v1", "test-model", project_id="project-a", settings=settings)

    async def fake_request(*, texts: list[str]) -> dict:
        return {"data": [{"embedding": [float(len(text))]} for text in texts]}

    embedder._embed_request = fake_request  # type: ignore[method-assign]
    vectors = embedder.embed(["one", "four"])

    assert vectors.tolist() == [[3.0], [4.0]]
    assert queue.stats.total_completed == 1
    assert queue.stats.active_embedding_calls == 0
