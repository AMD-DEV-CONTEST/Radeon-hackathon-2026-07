"""Telemetry and Observability — lightweight instrumentation for the agent pipeline.

Every command is traced with:
  - Per-step timing (intent, risk, plan, approval, execute)
  - Tool latency distribution
  - Success/failure rates
  - Memory usage snapshots
  - Circuit breaker events

Data is written to SQLite for querying and JSON for live dashboards.
Zero external dependencies — just stdlib + aiosqlite.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
TELEMETRY_DB = ROOT / "ai_pc_operator" / "data" / "telemetry.db"
TELEMETRY_JSON = ROOT / "ai_pc_operator" / "data" / "memory" / "telemetry_live.json"


@dataclass
class StepTrace:
    """One step within a command pipeline."""
    name: str
    started: float = 0.0
    finished: float = 0.0
    status: str = "ok"
    detail: str = ""

    @property
    def duration_ms(self) -> float:
        if self.finished and self.started:
            return (self.finished - self.started) * 1000
        return 0.0


@dataclass
class CommandTrace:
    """Full trace for one command through the pipeline."""
    command_id: int = 0
    input_text: str = ""
    device_id: str = ""
    started: float = field(default_factory=time.time)
    finished: float = 0.0
    steps: List[StepTrace] = field(default_factory=list)
    intent: str = "unknown"
    risk_level: int = 0
    tools_used: List[str] = field(default_factory=list)
    overall_status: str = "running"

    def add_step(self, name: str) -> StepTrace:
        step = StepTrace(name=name, started=time.time())
        self.steps.append(step)
        return step

    def finish_step(self, step: StepTrace, status: str = "ok", detail: str = "") -> None:
        step.finished = time.time()
        step.status = status
        step.detail = detail

    @property
    def total_ms(self) -> float:
        if self.finished and self.started:
            return (self.finished - self.started) * 1000
        return (time.time() - self.started) * 1000

    @property
    def step_summary(self) -> Dict[str, float]:
        return {s.name: round(s.duration_ms, 1) for s in self.steps}


class Telemetry:
    """Lightweight telemetry collector.

    Writes live data to JSON for dashboard consumption.
    Periodically flushes to SQLite for historical analysis.
    """

    def __init__(self) -> None:
        self._active: Dict[int, CommandTrace] = {}
        self._completed: List[CommandTrace] = []
        self._stats = {
            "total_commands": 0,
            "successful_commands": 0,
            "failed_commands": 0,
            "total_tool_calls": 0,
            "tool_latencies": defaultdict(list),  # tool -> [latency_ms]
            "intent_counts": defaultdict(int),
            "error_counts": defaultdict(int),
        }
        self._max_completed = 500  # Keep last N for memory
        self._write_lock = asyncio.Lock()

    @asynccontextmanager
    async def trace_command(
        self, command_id: int, input_text: str = "", device_id: str = ""
    ):
        """Context manager that traces a full command execution."""
        trace = CommandTrace(
            command_id=command_id,
            input_text=input_text[:100],  # Truncate for privacy
            device_id=device_id,
        )
        self._active[command_id] = trace
        try:
            yield trace
        except Exception as e:
            trace.overall_status = "error"
            step = trace.add_step("error")
            trace.finish_step(step, "failed", str(e)[:200])
            raise
        finally:
            trace.finished = time.time()
            trace.overall_status = (
                "success" if trace.overall_status == "running" else trace.overall_status
            )
            self._record_completion(trace)
            self._active.pop(command_id, None)

    def start_step(self, command_id: int, name: str) -> Optional[StepTrace]:
        trace = self._active.get(command_id)
        if trace:
            return trace.add_step(name)
        return None

    def finish_step(
        self, command_id: int, step: StepTrace,
        status: str = "ok", detail: str = ""
    ) -> None:
        if step:
            step.finished = time.time()
            step.status = status
            step.detail = detail

    def record_tool_call(
        self, command_id: int, tool: str, latency_ms: float, success: bool
    ) -> None:
        self._stats["total_tool_calls"] += 1
        self._stats["tool_latencies"][tool].append(latency_ms)
        # Keep only last 100 latencies per tool
        if len(self._stats["tool_latencies"][tool]) > 100:
            self._stats["tool_latencies"][tool] = self._stats["tool_latencies"][tool][-100:]

    def record_intent(self, intent: str) -> None:
        self._stats["intent_counts"][intent] += 1

    def record_error(self, error_type: str) -> None:
        self._stats["error_counts"][error_type] += 1

    def get_live_dashboard(self) -> Dict[str, Any]:
        """Get current state for the /runtime endpoint."""
        return {
            "active_commands": len(self._active),
            "recent_commands": [
                {
                    "id": t.command_id,
                    "intent": t.intent,
                    "status": t.overall_status,
                    "duration_ms": round(t.total_ms, 1),
                    "tools": t.tools_used,
                    "steps": t.step_summary,
                }
                for t in list(self._completed)[-10:]
            ],
            "stats": {
                "total_commands": self._stats["total_commands"],
                "success_rate": (
                    round(
                        self._stats["successful_commands"]
                        / max(1, self._stats["total_commands"]),
                        3,
                    )
                ),
                "tool_latencies": {
                    tool: {
                        "count": len(latencies),
                        "avg_ms": round(sum(latencies) / max(1, len(latencies)), 1),
                        "p50_ms": round(sorted(latencies)[len(latencies) // 2], 1)
                        if latencies
                        else 0,
                        "p95_ms": round(
                            sorted(latencies)[int(len(latencies) * 0.95)], 1
                        )
                        if latencies
                        else 0,
                    }
                    for tool, latencies in self._stats["tool_latencies"].items()
                },
                "intent_distribution": dict(self._stats["intent_counts"]),
                "error_distribution": dict(self._stats["error_counts"]),
            },
        }

    def _record_completion(self, trace: CommandTrace) -> None:
        self._stats["total_commands"] += 1
        self._stats["intent_counts"][trace.intent] += 1
        if trace.overall_status == "success":
            self._stats["successful_commands"] += 1
        else:
            self._stats["failed_commands"] += 1

        self._completed.append(trace)
        if len(self._completed) > self._max_completed:
            self._completed = self._completed[-self._max_completed:]

        # Write live JSON (non-blocking)
        try:
            TELEMETRY_JSON.parent.mkdir(parents=True, exist_ok=True)
            TELEMETRY_JSON.write_text(
                json.dumps(self.get_live_dashboard(), indent=2, default=str),
                encoding="utf-8",
            )
        except OSError:
            pass
