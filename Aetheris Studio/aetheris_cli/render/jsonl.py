"""
JSONL renderer for structured machine output.
Outputs single-line JSON records per event, enabling integration with scripts and automated pipelines.
"""

import json
import sys
from aetheris_cli.render.base import BaseRenderer
from aetheris_cli.transport.events import SSEEvent


class JSONLRenderer(BaseRenderer):
    def __init__(self, stream=sys.stdout):
        self.stream = stream

    def render_event(self, event: SSEEvent) -> None:
        record = {
            "type": event.type,
            "data": event.data,
        }
        self.stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        self.stream.flush()

    def on_finish(self, final_text: str, exit_code: int = 0) -> None:
        record = {
            "type": "finished",
            "exit_code": exit_code,
            "final_text": final_text,
        }
        self.stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        self.stream.flush()
