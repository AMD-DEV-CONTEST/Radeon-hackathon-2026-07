"""
SSE event definitions and tolerant streaming event parser.
Defines data structures for backend SSE stream events and provides parsing functions that degrade gracefully when encountering unknown events.
"""

from dataclasses import dataclass, field
import json
from typing import Any, Dict, Iterator, Optional


@dataclass
class SSEEvent:
    type: str
    data: Dict[str, Any] = field(default_factory=dict)
    raw_payload: str = ""

    @property
    def is_done(self) -> bool:
        return self.type == "done" or self.raw_payload == "[DONE]"


def parse_sse_payload(payload: str) -> Optional[SSEEvent]:
    payload_str = payload.strip()
    if not payload_str:
        return None

    if payload_str == "[DONE]":
        return SSEEvent(type="done", raw_payload=payload_str)

    try:
        data = json.loads(payload_str)
        if not isinstance(data, dict):
            return SSEEvent(type="raw", raw_payload=payload_str)
        
        event_type = data.get("type")
        if not event_type:
            if "delta" in data:
                event_type = "delta"
            elif "error" in data:
                event_type = "error"
            else:
                event_type = "unknown"

        return SSEEvent(type=str(event_type), data=data, raw_payload=payload_str)
    except json.JSONDecodeError:
        return SSEEvent(type="raw", raw_payload=payload_str)


def parse_sse_stream_lines(line_iterator: Iterator[str]) -> Iterator[SSEEvent]:
    for line in line_iterator:
        if not line:
            continue
        line_str = line.strip() if isinstance(line, str) else line.decode("utf-8", errors="replace").strip()
        if not line_str.startswith("data: "):
            continue
        payload = line_str[6:]
        event = parse_sse_payload(payload)
        if event:
            yield event
            if event.is_done:
                break
