from __future__ import annotations

import signal
import threading

from .service import OpenAlphaService


class CollectorWorker:
    def __init__(self, service: OpenAlphaService | None = None):
        self.service = service or OpenAlphaService()
        self.stop_event = threading.Event()

    def run_forever(self) -> None:
        for signum in (signal.SIGINT, signal.SIGTERM):
            signal.signal(signum, lambda *_: self.stop_event.set())
        while not self.stop_event.is_set():
            self.run_once()
            self.stop_event.wait(self.service.settings.worker_poll_seconds)

    def run_once(self) -> list[dict[str, str]]:
        outcomes = []
        for rule in self.service.database.due_watch_rules():
            try:
                result = self.service.run_watch_rule(rule)
                outcomes.append({"rule_id": rule["id"], "state": result.state})
            except Exception as exc:
                self.service.database.audit(
                    "watch_rule_failed", {"rule_id": rule["id"], "error": str(exc)}, actor="worker"
                )
                self.service.database.mark_watch_run(rule["id"], int(rule["interval_minutes"]))
                outcomes.append({"rule_id": rule["id"], "state": "FAILED", "error": str(exc)})
        return outcomes


def main() -> None:
    CollectorWorker().run_forever()


if __name__ == "__main__":
    main()
