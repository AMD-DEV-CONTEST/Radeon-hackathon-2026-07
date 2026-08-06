from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable
from typing import Any, Protocol

from glass_gateway.services.memory_review_store import MemoryReviewStore


class EverOSCorrectionAPI(Protocol):
    async def add_messages(self, session_id: str, messages: list[dict]) -> dict: ...

    async def flush(self, session_id: str) -> dict: ...


class CorrectionWritebackService:
    """Durable two-stage EverOS outbox for user-confirmed corrections."""

    def __init__(
        self,
        *,
        review_store_getter: Callable[[], MemoryReviewStore],
        everos_getter: Callable[[], EverOSCorrectionAPI],
        user_id: str,
        timeout_seconds: float = 60.0,
        retry_interval_seconds: float = 5.0,
        max_retry_seconds: float = 300.0,
        now_ms: Callable[[], int] | None = None,
    ) -> None:
        self._review_store_getter = review_store_getter
        self._everos_getter = everos_getter
        self.user_id = user_id
        self.timeout_seconds = max(0.01, float(timeout_seconds))
        self.retry_interval_seconds = max(0.05, float(retry_interval_seconds))
        self.max_retry_seconds = max(
            self.retry_interval_seconds, float(max_retry_seconds)
        )
        self._now_ms = now_ms or (lambda: int(time.time() * 1000))
        self._retry_task: asyncio.Task[None] | None = None
        self._locks: dict[str, asyncio.Lock] = {}

    async def process(self, correction_id: str) -> dict[str, Any]:
        lock = self._locks.setdefault(correction_id, asyncio.Lock())
        async with lock:
            store = self._review_store_getter()
            item = store.correction_by_id(correction_id)
            if item is None:
                raise KeyError(correction_id)
            if item.get("writeback_status") == "applied":
                return item

            stage = str(item.get("writeback_stage") or "pending_add")
            item = store.mark_correction_writeback(
                correction_id,
                writeback_status="pending_writeback",
                writeback_stage=stage,
                error=None,
                next_retry_at_ms=0,
                increment_attempt=True,
            )
            try:
                if stage == "pending_add":
                    add_result = await asyncio.wait_for(
                        self._everos_getter().add_messages(
                            str(item["everos_session_id"]),
                            [self._message(item)],
                        ),
                        timeout=self.timeout_seconds,
                    )
                    item = store.mark_correction_writeback(
                        correction_id,
                        writeback_status="pending_writeback",
                        writeback_stage="pending_flush",
                        response={"add": add_result},
                    )
                flush_result = await asyncio.wait_for(
                    self._everos_getter().flush(str(item["everos_session_id"])),
                    timeout=self.timeout_seconds,
                )
                return store.mark_correction_writeback(
                    correction_id,
                    writeback_status="applied",
                    writeback_stage="applied",
                    response={
                        **(item.get("last_writeback_response") or {}),
                        "flush": flush_result,
                    },
                )
            except (Exception, asyncio.CancelledError) as exc:
                if isinstance(exc, asyncio.CancelledError):
                    raise
                latest = store.correction_by_id(correction_id) or item
                delay_ms = self._retry_delay_ms(
                    int(latest.get("attempt_count") or 1)
                )
                error = (
                    f"EverOS writeback timed out after {self.timeout_seconds:g}s"
                    if isinstance(exc, asyncio.TimeoutError)
                    else str(exc)
                )
                return store.mark_correction_writeback(
                    correction_id,
                    writeback_status="failed_retryable",
                    writeback_stage=str(
                        latest.get("writeback_stage") or "pending_add"
                    ),
                    error=error,
                    next_retry_at_ms=self._now_ms() + delay_ms,
                )

    async def retry_pending(self, *, limit: int = 100) -> list[dict[str, Any]]:
        pending = self._review_store_getter().pending_corrections(
            now_ms=self._now_ms(), limit=limit
        )
        results: list[dict[str, Any]] = []
        for item in pending:
            results.append(await self.process(str(item["id"])))
        return results

    def start_retry_loop(self) -> None:
        if self._retry_task is not None and not self._retry_task.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._retry_task = loop.create_task(self._retry_pending_loop())

    async def stop_retry_loop(self) -> None:
        task = self._retry_task
        self._retry_task = None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _retry_pending_loop(self) -> None:
        while True:
            try:
                await self.retry_pending()
            except asyncio.CancelledError:
                raise
            except Exception:
                # Individual errors are persisted by process(). The loop itself
                # must stay alive across transient store/client faults.
                pass
            await asyncio.sleep(self.retry_interval_seconds)

    def _retry_delay_ms(self, attempt_count: int) -> int:
        seconds = min(
            self.max_retry_seconds,
            self.retry_interval_seconds * (2 ** min(max(attempt_count - 1, 0), 8)),
        )
        return int(seconds * 1000)

    def _message(self, item: dict[str, Any]) -> dict[str, Any]:
        operation = "撤销修正" if item.get("action") == "revert" else "确认修正"
        payload = {
            "correction_id": item.get("id"),
            "operation": operation,
            "target_type": item.get("target_type"),
            "target_id": item.get("target_id"),
            "field_path": item.get("field_path"),
            "version": item.get("version"),
            "decision_status": item.get("decision_status"),
            "old_value": item.get("old_value"),
            "new_value": item.get("new_value"),
            "reverts_id": item.get("reverts_id"),
            "evidence_refs": item.get("evidence_refs") or [],
            "note": item.get("note"),
        }
        return {
            "sender_id": self.user_id,
            "sender_name": "Beaver Memory 网页复核",
            "role": "user",
            "timestamp": self._now_ms(),
            "content": [
                {
                    "type": "text",
                    "text": "用户已在 Beaver Memory 确认一条记忆修正。\n"
                    + json.dumps(payload, ensure_ascii=False, sort_keys=True),
                }
            ],
        }
