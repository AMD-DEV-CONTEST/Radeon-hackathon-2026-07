from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterable

from fastapi.responses import StreamingResponse

from policyseal.domain.models import RevisionStageEvent


def stage_event_stream(
    events: Iterable[RevisionStageEvent],
    *,
    after_sequence: int = 0,
) -> StreamingResponse:
    async def generate() -> AsyncIterator[str]:
        for event in events:
            if event.sequence <= after_sequence:
                continue
            payload = {
                "revision_id": event.revision_id,
                "sequence": event.sequence,
                "stage": event.stage,
                "status": event.status,
                "occurred_at": event.occurred_at.isoformat(),
            }
            yield (
                f"id: {event.sequence}\n"
                "event: revision-stage\n"
                f"data: {json.dumps(payload, separators=(',', ':'))}\n\n"
            )

    return StreamingResponse(generate(), media_type="text/event-stream")
