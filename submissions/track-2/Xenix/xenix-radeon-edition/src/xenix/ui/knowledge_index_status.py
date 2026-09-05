from __future__ import annotations

from concurrent.futures import Future

from PySide6.QtCore import QObject, Signal

from ..services.knowledge_index_service import (
    KnowledgeIndexOverview,
    KnowledgeIndexService,
)


class KnowledgeIndexStatusRequest(QObject):
    """Bridge a service-owned status Future back onto the Qt event loop."""

    finished = Signal(object, int, object)

    def __init__(self, generation: int) -> None:
        super().__init__()
        self._generation = generation
        self._future: Future[KnowledgeIndexOverview] | None = None

    def start(self, service: KnowledgeIndexService) -> None:
        if self._future is not None:
            raise RuntimeError("Knowledge index status request has already started.")
        future = service.request_status()
        self._future = future
        future.add_done_callback(self._on_done)

    def cancel(self) -> None:
        if self._future is not None:
            self._future.cancel()

    def _on_done(self, future: Future[KnowledgeIndexOverview]) -> None:
        self._future = None
        try:
            status = future.result()
        except Exception:
            status = None
        self.finished.emit(self, self._generation, status)


__all__ = ["KnowledgeIndexStatusRequest"]
