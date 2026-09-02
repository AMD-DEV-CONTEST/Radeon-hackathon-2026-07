"""Internal Event Bus — lightweight pub/sub for decoupled communication.

V1.24 Extension Point architecture.
Not a user-facing plugin system; reserved for future expansion.
"""
from typing import Callable, Dict, List
import logging

log = logging.getLogger(__name__)

# ── Event constants (hook points) ───────────────────────────────────────────
ENTITY_CREATED = "entity.created"
ENTITY_UPDATED = "entity.updated"
ENTITY_DELETED = "entity.deleted"
SEARCH_COMPLETED = "search.completed"
IMPORT_COMPLETED = "import.completed"
CONSISTENCY_CHECKED = "consistency.checked"

# ── EventBus ────────────────────────────────────────────────────────────────

class EventBus:
    """Simple in-memory event bus. Singleton.
    
    Usage:
        bus = EventBus.get()
        bus.on(ENTITY_CREATED, my_handler)
        bus.emit(ENTITY_CREATED, entity_id="CHR_0001")
    """
    _instance = None
    _handlers: Dict[str, List[Callable]] = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._handlers = {}
        return cls._instance

    @classmethod
    def get(cls):
        return cls()

    def on(self, event: str, handler: Callable):
        """Register a handler for an event."""
        self._handlers.setdefault(event, []).append(handler)

    def emit(self, event: str, **data):
        """Fire an event. All registered handlers are called."""
        for handler in self._handlers.get(event, []):
            try:
                handler(event=event, **data)
            except Exception as e:
                log.warning("Event handler error [%s]: %s", event, e)

    def off(self, event: str, handler: Callable = None):
        """Unregister a handler. If handler is None, clear all for this event."""
        if handler:
            try:
                self._handlers[event].remove(handler)
            except ValueError:
                pass
        else:
            self._handlers[event] = []

    def handlers_for(self, event: str) -> list:
        """List registered handlers for an event (introspection)."""
        return list(self._handlers.get(event, []))
