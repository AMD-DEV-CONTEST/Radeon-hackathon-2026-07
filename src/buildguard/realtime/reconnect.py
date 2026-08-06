"""Deterministic exponential reconnect policy."""

from __future__ import annotations

import time
from collections.abc import Callable

from pydantic import BaseModel, Field


class ReconnectDecision(BaseModel):
    attempt: int = Field(ge=1)
    delay_seconds: float = Field(ge=0, le=30)


class ExponentialReconnect:
    def __init__(
        self,
        initial_seconds: float,
        multiplier: float,
        max_seconds: float,
        *,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if initial_seconds < 0:
            raise ValueError("initial_seconds must be non-negative")
        if multiplier < 1:
            raise ValueError("multiplier must be at least one")
        if not 0 < max_seconds <= 30:
            raise ValueError("max_seconds must be within (0, 30]")
        self.initial_seconds = initial_seconds
        self.multiplier = multiplier
        self.max_seconds = max_seconds
        self.sleeper = sleeper
        self.attempts = 0

    def next(self) -> ReconnectDecision:
        self.attempts += 1
        delay = min(
            self.max_seconds,
            self.initial_seconds * self.multiplier ** (self.attempts - 1),
        )
        return ReconnectDecision(attempt=self.attempts, delay_seconds=delay)

    def wait(self) -> ReconnectDecision:
        decision = self.next()
        self.sleeper(decision.delay_seconds)
        return decision

    def reset(self) -> None:
        self.attempts = 0
