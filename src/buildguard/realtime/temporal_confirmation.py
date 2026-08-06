"""Per-event M-of-N confirmation with exponential smoothing."""

from __future__ import annotations

import math
from collections import deque

from buildguard.config import TemporalRuleConfig
from buildguard.realtime.schemas import ConfirmationResult


class MOfNConfirmation:
    def __init__(
        self,
        rules: dict[str, TemporalRuleConfig],
        *,
        time_evidence_enabled: bool = False,
        evidence_window_seconds: float = 5.0,
        evidence_half_life_seconds: float = 1.5,
        evidence_min_positive_seconds: float = 0.5,
        evidence_confirm_threshold: float = 0.55,
    ) -> None:
        if not rules:
            raise ValueError("At least one temporal confirmation rule is required")
        self.rules = rules
        if evidence_window_seconds <= 0 or evidence_half_life_seconds <= 0:
            raise ValueError("Temporal evidence windows must be positive")
        if not 0 <= evidence_min_positive_seconds <= evidence_window_seconds:
            raise ValueError("Temporal positive duration is outside its window")
        if not 0 <= evidence_confirm_threshold <= 1:
            raise ValueError("Temporal evidence threshold must be within 0..1")
        self.time_evidence_enabled = time_evidence_enabled
        self.evidence_window_seconds = evidence_window_seconds
        self.evidence_half_life_seconds = evidence_half_life_seconds
        self.evidence_min_positive_seconds = evidence_min_positive_seconds
        self.evidence_confirm_threshold = evidence_confirm_threshold
        self._history: dict[tuple[str, str], deque[bool]] = {}
        self._smoothed: dict[tuple[str, str], float] = {}
        self._timed_history: dict[
            tuple[str, str], deque[tuple[float, bool]]
        ] = {}
        self._evidence: dict[tuple[str, str], float] = {}
        self._last_evidence_at: dict[tuple[str, str], float] = {}

    def update(
        self,
        event_type: str,
        identity: str,
        *,
        detected: bool,
        confidence: float,
        timestamp_seconds: float | None = None,
    ) -> ConfirmationResult:
        if event_type not in self.rules:
            raise KeyError(f"No temporal confirmation rule for {event_type}")
        if not 0 <= confidence <= 1:
            raise ValueError("Temporal confidence must be within 0..1")
        rule = self.rules[event_type]
        key = (event_type, identity)
        history = self._history.setdefault(key, deque(maxlen=rule.n))
        history.append(detected)
        previous = self._smoothed.get(key)
        current = confidence if detected else 0.0
        smoothed = (
            current if previous is None else rule.alpha * current + (1 - rule.alpha) * previous
        )
        self._smoothed[key] = smoothed
        positives = sum(history)
        legacy_confirmed = positives >= rule.m
        if not self.time_evidence_enabled or timestamp_seconds is None:
            return ConfirmationResult(
                event_type=event_type,
                identity=identity,
                positives=positives,
                window_size=len(history),
                required=rule.m,
                confirmed=legacy_confirmed,
                suspected=positives > 0,
                smoothed_confidence=smoothed,
                evidence_score=smoothed,
                decision_source="m_of_n",
            )
        if timestamp_seconds < 0:
            raise ValueError("Temporal evidence timestamp must be non-negative")
        previous_at = self._last_evidence_at.get(key)
        if previous_at is not None and timestamp_seconds < previous_at:
            self._timed_history.pop(key, None)
            self._evidence.pop(key, None)
            previous_at = None
        elapsed = 0.0 if previous_at is None else timestamp_seconds - previous_at
        decay = math.exp(
            -math.log(2) * elapsed / self.evidence_half_life_seconds
        )
        previous_evidence = self._evidence.get(key, 0.0) * decay
        current_evidence = confidence if detected else 0.0
        evidence = (
            current_evidence
            if previous_at is None
            else rule.alpha * current_evidence + (1 - rule.alpha) * previous_evidence
        )
        evidence = max(0.0, min(1.0, evidence))
        self._evidence[key] = evidence
        self._last_evidence_at[key] = timestamp_seconds
        timed = self._timed_history.setdefault(key, deque())
        timed.append((timestamp_seconds, detected))
        cutoff = timestamp_seconds - self.evidence_window_seconds
        while timed and timed[0][0] < cutoff:
            timed.popleft()
        positive_times = [when for when, positive in timed if positive]
        positive_duration = (
            positive_times[-1] - positive_times[0]
            if len(positive_times) >= 2
            else 0.0
        )
        required_duration = (
            0.0 if rule.m == 1 else self.evidence_min_positive_seconds
        )
        time_confirmed = (
            evidence >= self.evidence_confirm_threshold
            and positive_duration + 1e-12
            >= required_duration
        )
        return ConfirmationResult(
            event_type=event_type,
            identity=identity,
            positives=positives,
            window_size=len(history),
            required=rule.m,
            confirmed=legacy_confirmed and time_confirmed,
            suspected=legacy_confirmed or evidence >= self.evidence_confirm_threshold * 0.5,
            smoothed_confidence=smoothed,
            evidence_score=evidence,
            positive_duration_seconds=positive_duration,
            decision_source="m_of_n+time_evidence",
        )

    def reset(self, event_type: str | None = None, identity: str | None = None) -> None:
        keys = [
            key
            for key in self._history
            if (event_type is None or key[0] == event_type)
            and (identity is None or key[1] == identity)
        ]
        for key in keys:
            self._history.pop(key, None)
            self._smoothed.pop(key, None)
            self._timed_history.pop(key, None)
            self._evidence.pop(key, None)
            self._last_evidence_at.pop(key, None)

    def identities(self) -> set[tuple[str, str]]:
        return set(self._history)
