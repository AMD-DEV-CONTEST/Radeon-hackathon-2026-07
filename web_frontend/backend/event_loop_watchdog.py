from __future__ import annotations

import asyncio
import logging
import os
import sys
import threading
import time
import traceback


WATCHDOG_INTERVAL_ENV = "AGENTFACTORY_WEB_EVENT_LOOP_WATCHDOG_INTERVAL_SECONDS"
WATCHDOG_LAG_THRESHOLD_ENV = "AGENTFACTORY_WEB_EVENT_LOOP_LAG_THRESHOLD_SECONDS"
WATCHDOG_DUMP_INTERVAL_ENV = "AGENTFACTORY_WEB_EVENT_LOOP_STACK_DUMP_INTERVAL_SECONDS"


class EventLoopWatchdog:
    """Detect ASGI loop starvation without attaching an external debugger."""

    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger
        self._interval = _positive_float(WATCHDOG_INTERVAL_ENV, 1.0)
        self._lag_threshold = _positive_float(WATCHDOG_LAG_THRESHOLD_ENV, 5.0)
        self._dump_interval = _positive_float(WATCHDOG_DUMP_INTERVAL_ENV, 30.0)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._probe_pending = False
        self._probe_started_at = 0.0
        self._last_dump_at = 0.0

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._loop = loop
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="asgi-event-loop-watchdog",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=max(1.0, self._interval * 2))
        self._thread = None
        self._loop = None

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            loop = self._loop
            if loop is None or loop.is_closed():
                continue
            now = time.monotonic()
            with self._lock:
                if not self._probe_pending:
                    self._probe_pending = True
                    self._probe_started_at = now
                    loop.call_soon_threadsafe(self._acknowledge_probe)
                    continue
                lag = now - self._probe_started_at
                should_dump = lag >= self._lag_threshold and now - self._last_dump_at >= self._dump_interval
                if should_dump:
                    self._last_dump_at = now
            if should_dump:
                self._logger.error(
                    "ASGI event loop has not acknowledged the watchdog for %.3f seconds\n%s",
                    lag,
                    _thread_stack_dump(),
                )

    def _acknowledge_probe(self) -> None:
        with self._lock:
            self._probe_pending = False
            self._probe_started_at = 0.0


def _thread_stack_dump() -> str:
    names = {thread.ident: thread.name for thread in threading.enumerate()}
    sections: list[str] = []
    for thread_id, frame in sys._current_frames().items():
        name = names.get(thread_id, "unknown")
        sections.append(
            f"--- thread {name} ({thread_id}) ---\n"
            + "".join(traceback.format_stack(frame))
        )
    return "\n".join(sections)


def _positive_float(name: str, default: float) -> float:
    raw = str(os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return value
