"""
Browser replay recorder — captures full action sequences for reproducibility and corpus.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agents.base_agent import ActionResult, AgentAction, AgentObservation

log = logging.getLogger(__name__)


@dataclass
class ReplayFrame:
    step: int
    timestamp: float
    action: dict
    observation_before: dict
    observation_after: dict | None
    result: dict

    def to_dict(self) -> dict:
        return {
            "step": self.step,
            "timestamp": self.timestamp,
            "action": self.action,
            "observation_before": self.observation_before,
            "observation_after": self.observation_after,
            "result": self.result,
        }


class ReplayRecorder:
    def __init__(self, task_id: str, output_dir: str | Path = ".") -> None:
        self.task_id = task_id
        self.output_dir = Path(output_dir)
        self.frames: list[ReplayFrame] = []
        self._start_time = time.time()

    def record(
        self,
        step: int,
        action: AgentAction,
        observation_before: AgentObservation,
        result: ActionResult,
    ) -> None:
        frame = ReplayFrame(
            step=step,
            timestamp=time.time() - self._start_time,
            action=action.to_dict(),
            observation_before=observation_before.to_dict(),
            observation_after=result.observation_after.to_dict()
            if result.observation_after
            else None,
            result=result.to_dict(),
        )
        self.frames.append(frame)

    def save(self, filename: str | None = None) -> Path:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        fname = filename or f"replay_{self.task_id}.json"
        path = self.output_dir / fname
        with open(path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "task_id": self.task_id,
                    "total_steps": len(self.frames),
                    "frames": [fr.to_dict() for fr in self.frames],
                },
                f,
                indent=2,
            )
        log.info("[replay_recorder] saved %d frames → %s", len(self.frames), path)
        return path

    def to_corpus_payload(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "total_steps": len(self.frames),
            "replay_available": True,
            "frames": [fr.to_dict() for fr in self.frames],
        }
