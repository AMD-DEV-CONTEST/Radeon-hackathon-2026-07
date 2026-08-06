from __future__ import annotations

import threading
from importlib import import_module
from typing import Any


class LazyServiceProxy:
    def __init__(
        self,
        module_name: str,
        class_name: str,
        *service_args: Any,
        **service_kwargs: Any,
    ) -> None:
        self._module_name = module_name
        self._class_name = class_name
        self._service_args = service_args
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
                service_class = getattr(import_module(self._module_name), self._class_name)
                service = service_class(*self._service_args, **self._service_kwargs)
                self._service = service
            return service
