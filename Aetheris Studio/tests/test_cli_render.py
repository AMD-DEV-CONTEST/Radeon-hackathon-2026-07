"""
Unit tests for Aetheris CLI renderers.
Verifies deterministic text, JSONL, and Rich TUI output formatting across different SSE event payloads, header rendering, and generation metrics footers.
"""

import io
import json
from aetheris_cli.render.jsonl import JSONLRenderer
from aetheris_cli.render.plain import PlainRenderer
from aetheris_cli.render.tui import TUIRenderer
from aetheris_cli.transport.events import SSEEvent


def test_plain_renderer_output():
    buf = io.StringIO()
    renderer = PlainRenderer(stream=buf)

    e1 = SSEEvent(type="delta", data={"delta": "Hello "})
    e2 = SSEEvent(type="delta", data={"delta": "world!"})

    renderer.render_event(e1)
    renderer.render_event(e2)
    renderer.on_finish("Hello world!")

    out = buf.getvalue()
    assert out == "Hello world!\n"


def test_jsonl_renderer_output():
    buf = io.StringIO()
    renderer = JSONLRenderer(stream=buf)

    e1 = SSEEvent(type="tool_start", data={"tool": "write_file", "round": 1})
    renderer.render_event(e1)
    renderer.on_finish("", exit_code=0)

    lines = buf.getvalue().strip().split("\n")
    assert len(lines) == 2

    r1 = json.loads(lines[0])
    assert r1.get("type") == "tool_start"
    assert r1.get("data", {}).get("tool") == "write_file"

    r2 = json.loads(lines[1])
    assert r2.get("type") == "finished"
    assert r2.get("exit_code") == 0


def test_tui_renderer_header_and_metrics():
    renderer = TUIRenderer(theme_name="tokyo-night")
    renderer.render_header(
        model_name="granite-4.1:3b-q8_0",
        cart_status={"mapped_files": 5, "total_files": 5},
        telemetry={"vram_used_mb": 2048, "vram_total_mb": 8192},
        egress_status={"bytes_sent": 0},
    )

    renderer.start_thinking("Thinking test...")
    e1 = SSEEvent(type="delta", data={"delta": "Hello "})
    e2 = SSEEvent(type="delta", data={"delta": "world!"})

    renderer.render_event(e1)
    renderer.render_event(e2)
    renderer.on_finish("Hello world!")

    assert renderer.token_count == 2
