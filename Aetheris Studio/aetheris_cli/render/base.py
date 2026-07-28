"""
Abstract base class definition for event renderers.
Establishes standard lifecycle methods for processing SSE stream events.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict
from aetheris_cli.transport.events import SSEEvent


class BaseRenderer(ABC):
    @abstractmethod
    def render_event(self, event: SSEEvent) -> None:
        pass

    def on_start(self, prompt: str) -> None:
        pass

    def on_finish(self, final_text: str, exit_code: int = 0) -> None:
        pass
