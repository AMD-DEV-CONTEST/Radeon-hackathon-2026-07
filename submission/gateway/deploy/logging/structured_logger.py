"""Structured JSON logger for UAS services.

Usage:
    from deploy.logging.structured_logger import get_logger
    log = get_logger("orchestrator")
    log.event("task.created", task_id=str(task_id), title=title)
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from typing import Any


LOG_DIR = os.environ.get("UAS_LOG_DIR", "/var/log/unionagents")
LOG_LEVEL = os.environ.get("UAS_LOG_LEVEL", "INFO").upper()


class StructuredLogger:
    def __init__(self, service: str, log_path: str | None = None) -> None:
        self.service = service
        self._path = log_path or os.path.join(LOG_DIR, f"{service}.jsonl")
        self._fh: Any = None
        self._std = logging.getLogger(f"uas.{service}")
        if not self._std.handlers:
            h = logging.StreamHandler(sys.stdout)
            h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))
            self._std.addHandler(h)
        self._std.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))

    def _open(self) -> None:
        if self._fh is None:
            try:
                os.makedirs(os.path.dirname(self._path), exist_ok=True)
                self._fh = open(self._path, "a", encoding="utf-8", buffering=1)
            except OSError:
                pass  # log dir may not exist in dev; fall back to stdout only

    def _write(self, record: dict[str, Any]) -> None:
        line = json.dumps(record, ensure_ascii=False, default=str)
        self._open()
        if self._fh:
            self._fh.write(line + "\n")
        self._std.log(
            logging.getLevelName(record.get("level", "INFO")),
            "%s %s",
            record.get("event_type", ""),
            " ".join(f"{k}={v}" for k, v in record.items()
                     if k not in ("ts", "service", "event_type", "level")),
        )

    def event(self, event_type: str, level: str = "INFO", **kwargs: Any) -> None:
        self._write({
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "service": self.service,
            "event_type": event_type,
            "level": level,
            **kwargs,
        })

    def info(self, event_type: str, **kwargs: Any) -> None:
        self.event(event_type, level="INFO", **kwargs)

    def warn(self, event_type: str, **kwargs: Any) -> None:
        self.event(event_type, level="WARN", **kwargs)

    def error(self, event_type: str, **kwargs: Any) -> None:
        self.event(event_type, level="ERROR", **kwargs)


_registry: dict[str, StructuredLogger] = {}


def get_logger(service: str, log_path: str | None = None) -> StructuredLogger:
    if service not in _registry:
        _registry[service] = StructuredLogger(service, log_path)
    return _registry[service]
