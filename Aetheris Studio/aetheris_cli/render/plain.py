"""
Plain text renderer for simple terminal displays, CI logs, and non-TTY environments.
Renders events directly to standard output without ANSI color codes or live widgets.
"""

import sys
from aetheris_cli.render.base import BaseRenderer
from aetheris_cli.transport.events import SSEEvent


class PlainRenderer(BaseRenderer):
    def __init__(self, stream=sys.stdout):
        self.stream = stream

    def render_event(self, event: SSEEvent) -> None:
        etype = event.type
        data = event.data

        if etype == "delta":
            delta_text = data.get("delta", "")
            self.stream.write(delta_text)
            self.stream.flush()
        elif etype == "reasoning_delta":
            text = data.get("text", "")
            self.stream.write(text)
            self.stream.flush()
        elif etype == "tool_start":
            tool_name = data.get("tool", "")
            round_num = data.get("round", 1)
            self.stream.write(f"\n[tool_start round={round_num}] {tool_name}\n")
            self.stream.flush()
        elif etype == "tool_output":
            tool_name = data.get("tool", "")
            result = data.get("result", {})
            out_preview = str(result.get("output") or result.get("content") or result.get("error") or "")[:300]
            self.stream.write(f"[tool_output] {tool_name} -> {out_preview}\n")
            self.stream.flush()
        elif etype == "plan_update":
            plan = data.get("plan", "")
            self.stream.write(f"\n[plan]\n{plan}\n")
            self.stream.flush()
        elif etype == "browser_action":
            tool_name = data.get("tool", "")
            self.stream.write(f"\n[browser_action] Tool '{tool_name}' is not supported in CLI.\n")
            self.stream.flush()
        elif etype == "loop_detected":
            tool_name = data.get("tool", "")
            self.stream.write(f"\n[loop_detected] Repeated tool invocation detected: {tool_name}\n")
            self.stream.flush()
        elif etype == "rounds_exhausted":
            self.stream.write("\n[rounds_exhausted] Maximum execution rounds reached.\n")
            self.stream.flush()
        elif etype == "error":
            err_msg = data.get("error", "Unknown error")
            self.stream.write(f"\n[error] {err_msg}\n")
            self.stream.flush()

    def on_finish(self, final_text: str, exit_code: int = 0) -> None:
        self.stream.write("\n")
        self.stream.flush()
