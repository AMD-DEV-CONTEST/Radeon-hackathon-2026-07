from __future__ import annotations

import os
import sys
from threading import Thread


PARENT_STDIN_WATCHDOG_ENV = "AGENTFACTORY_PARENT_STDIN_WATCHDOG"


def start_parent_process_watchdog() -> None:
    if os.getenv(PARENT_STDIN_WATCHDOG_ENV) != "1":
        return
    Thread(
        target=_exit_when_parent_pipe_closes,
        name="desktop-parent-watchdog",
        daemon=True,
    ).start()


def _exit_when_parent_pipe_closes() -> None:
    try:
        sys.stdin.buffer.read()
    except (AttributeError, OSError, ValueError):
        pass
    os._exit(0)
