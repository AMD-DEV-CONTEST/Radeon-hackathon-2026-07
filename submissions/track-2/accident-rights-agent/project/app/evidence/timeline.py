"""Timeline normalization while preserving every source reference."""

from __future__ import annotations

from app.schemas.evidence import TimelineEvent


def merge_timeline(events: list[TimelineEvent]) -> list[TimelineEvent]:
    """Deduplicate identical events and assign a stable total order."""

    unique: dict[tuple[str, tuple[str, ...]], TimelineEvent] = {}
    for event in events:
        key = (event.label.strip(), tuple(sorted(event.source_node_ids)))
        current = unique.get(key)
        if current is None or event.confidence > current.confidence:
            unique[key] = event
    ordered = sorted(
        unique.values(),
        key=lambda item: (
            item.timestamp_seconds is None,
            item.timestamp_seconds if item.timestamp_seconds is not None else 0,
            item.relative_order,
            item.event_id,
        ),
    )
    return [
        TimelineEvent(
            event_id=item.event_id,
            case_id=item.case_id,
            label=item.label,
            relative_order=position,
            source_node_ids=item.source_node_ids,
            timestamp_seconds=item.timestamp_seconds,
            confidence=item.confidence,
            created_at=item.created_at,
        )
        for position, item in enumerate(ordered, start=1)
    ]
