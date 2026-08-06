from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from uuid import UUID


HEARTBEAT_INTERVAL_SECONDS = 30


class HeartbeatThread:
    def __init__(
        self,
        *,
        orchestrator_url: str,
        task_id: UUID,
        agent_id: UUID,
        post_json: Callable[[str, str, dict], dict],
        logger: logging.Logger,
        interval_seconds: int = HEARTBEAT_INTERVAL_SECONDS,
    ) -> None:
        self.orchestrator_url = orchestrator_url
        self.task_id = task_id
        self.agent_id = agent_id
        self.post_json = post_json
        self.logger = logger
        self.interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)

    def _run(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            try:
                self.post_json(
                    self.orchestrator_url,
                    f"/tasks/{self.task_id}/heartbeat",
                    {"agent_id": str(self.agent_id)},
                )
            except Exception as exc:  # noqa: BLE001 - heartbeat must not kill the worker.
                self.logger.warning("heartbeat failed for task %s: %s", self.task_id, exc)
