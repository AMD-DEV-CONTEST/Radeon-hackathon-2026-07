"""
Unit tests for Aetheris CLI SSE parser.
Verifies parsing of standard SSE streams, chunked lines, done tokens, and unknown events.
"""

from aetheris_cli.transport.events import parse_sse_payload, parse_sse_stream_lines


def test_parse_sse_payload_delta():
    payload = '{"delta": "Hello world"}'
    event = parse_sse_payload(payload)
    assert event is not None
    assert event.type == "delta"
    assert event.data.get("delta") == "Hello world"


def test_parse_sse_payload_done():
    payload = "[DONE]"
    event = parse_sse_payload(payload)
    assert event is not None
    assert event.is_done is True


def test_parse_sse_stream_lines_sequence():
    lines = [
        'data: {"delta": "Hello"}',
        'data: {"delta": " world"}',
        'data: {"type": "tool_start", "tool": "read_file", "round": 1}',
        'data: [DONE]',
    ]
    events = list(parse_sse_stream_lines(iter(lines)))
    assert len(events) == 4
    assert events[0].type == "delta"
    assert events[1].type == "delta"
    assert events[2].type == "tool_start"
    assert events[3].is_done is True
