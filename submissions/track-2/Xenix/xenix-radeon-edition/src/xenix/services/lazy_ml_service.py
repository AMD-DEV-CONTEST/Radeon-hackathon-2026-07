from __future__ import annotations

import threading
from typing import Any


class LazyMLService:
    def __init__(self, **service_kwargs: Any) -> None:
        self._service_kwargs = service_kwargs
        self._service = None
        self._lock = threading.Lock()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._resolve(), name)

    def _resolve(self):
        service = self._service
        if service is not None:
            return service
        with self._lock:
            service = self._service
            if service is None:
                from .ml_service import MLService

                service = MLService(**self._service_kwargs)
                self._service = service
            return service
