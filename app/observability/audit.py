from __future__ import annotations

import json
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.schemas.models import StepDef, StepTiming

_RUN_ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")


def validate_run_id(run_id: str) -> str:
    if not _RUN_ID_PATTERN.fullmatch(run_id):
        raise ValueError("run_id must be a 32-character lowercase hexadecimal identifier")
    return run_id


class StepTimer:
    """Context-manager that records step timing for a run."""

    def __init__(
        self,
        timing_list: list[StepTiming],
        step: StepDef,
        current_file: str | None = None,
    ):
        self._timing_list = timing_list
        self._step = step
        self._current_file = current_file
        self._start: float = 0.0
        self._timing: StepTiming | None = None

    def __enter__(self) -> StepTiming:
        self._start = time.monotonic()
        self._timing = StepTiming(
            step=self._step,
            started_at=datetime.now(UTC),
            current_file=self._current_file,
        )
        return self._timing

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:  # type: ignore[no-untyped-def]
        assert self._timing is not None
        now = datetime.now(UTC)
        self._timing.finished_at = now
        self._timing.elapsed_ms = round((time.monotonic() - self._start) * 1000, 2)
        if exc_val is not None and self._timing.error is None:
            self._timing.error = str(exc_val)
        self._timing_list.append(self._timing)


class AuditTrail:
    """Append JSONL events for one bounded application run."""

    def __init__(self, log_root: Path, run_id: str):
        self._run_id = validate_run_id(run_id)
        self._path = log_root / "runs" / f"{self._run_id}.jsonl"

    @property
    def path(self) -> Path:
        return self._path

    def write(self, event: str, payload: dict[str, Any] | None = None) -> None:
        record = {
            "timestamp": datetime.now(UTC).isoformat(),
            "run_id": self._run_id,
            "event": event,
            "payload": payload or {},
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")

    def step_timer(
        self, timing_list: list[StepTiming], step: StepDef, *, current_file: str | None = None
    ) -> StepTimer:
        """Return a context manager that records ``StepTiming`` into *timing_list*.

        Usage::

            with audit.step_timer(timing, StepDef.PARSE, current_file="readme.md") as st:
                # ... work ...
                st.current_file = "updated.md"
        """
        return StepTimer(timing_list, step, current_file=current_file)
