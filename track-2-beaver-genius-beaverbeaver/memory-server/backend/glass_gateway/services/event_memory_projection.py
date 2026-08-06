from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo


_BEIJING = ZoneInfo("Asia/Shanghai")
_MAX_EVENT_TEXT_CHARS = 48_000


def build_event_message(
    queue: dict[str, Any],
    *,
    user_id: str,
    sender_name: str,
) -> dict[str, Any]:
    """Project one sealed semantic event into one EverOS input message."""

    entries = [
        item
        for item in queue.get("entries", [])
        if isinstance(item, dict)
    ]
    started_at_ms = int(
        queue.get("started_at_ms")
        or (entries[0].get("captured_at_ms") if entries else 0)
        or 0
    )
    ended_at_ms = int(
        queue.get("ended_at_ms")
        or (entries[-1].get("captured_at_ms") if entries else started_at_ms)
        or started_at_ms
    )
    summary = str(queue.get("rolling_summary") or "").strip()
    captions = _distinct_captions(entries)
    lines = [
        "[Beaver Memory · 完整事件]",
        f"时间：{_local_time(started_at_ms)} 至 {_local_time(ended_at_ms)}",
    ]
    if summary:
        lines.append(f"事件摘要：{summary}")
    if captions:
        lines.append("关键经历：")
        lines.extend(f"- {caption}" for caption in _milestone_captions(captions))
    text = "\n".join(lines)
    if len(text) > _MAX_EVENT_TEXT_CHARS:
        text = text[: _MAX_EVENT_TEXT_CHARS - 20].rstrip() + "\n（细节已压缩）"
    return {
        "sender_id": user_id,
        "sender_name": sender_name,
        "role": "user",
        "timestamp": started_at_ms,
        "content": [{"type": "text", "text": text}],
    }


def _distinct_captions(entries: list[dict[str, Any]]) -> list[str]:
    captions: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        projection = entry.get("stabilized_projection")
        interpretation = entry.get("window_interpretation")
        caption = str(
            (
                projection.get("corrected_caption")
                if isinstance(projection, dict)
                else ""
            )
            or (
                interpretation.get("first_person_caption")
                if isinstance(interpretation, dict)
                else ""
            )
            or ""
        ).strip()
        key = " ".join(caption.split()).casefold()
        if not caption or key in seen:
            continue
        seen.add(key)
        captions.append(caption)
    return captions


def _milestone_captions(captions: list[str], *, limit: int = 8) -> list[str]:
    """Keep a bounded first/last timeline; full detail remains in Capsules."""

    if len(captions) <= limit:
        return captions
    head = max(1, limit // 2)
    tail = max(1, limit - head)
    return [*captions[:head], *captions[-tail:]]


def _local_time(timestamp_ms: int) -> str:
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=_BEIJING).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
