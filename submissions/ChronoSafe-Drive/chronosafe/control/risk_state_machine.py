"""Hysteretic transition logic for degraded operation and MRM."""

from __future__ import annotations

from enum import IntEnum


class DrivingMode(IntEnum):
    NORMAL = 0
    DEGRADED = 1
    MINIMAL_RISK = 2


class RiskStateMachine:
    """Escalate immediately, recover slowly, and latch minimal-risk mode."""

    def __init__(
        self,
        degraded_threshold: float = 0.18,
        minimal_risk_threshold: float = 0.48,
        recovery_frames: int = 12,
        latch_minimal_risk: bool = True,
    ) -> None:
        if not 0 <= degraded_threshold < minimal_risk_threshold <= 1:
            raise ValueError("Risk thresholds must satisfy 0 <= degraded < minimal-risk <= 1")
        self.degraded_threshold = degraded_threshold
        self.minimal_risk_threshold = minimal_risk_threshold
        self.recovery_frames = recovery_frames
        self.latch_minimal_risk = latch_minimal_risk
        self.mode = DrivingMode.NORMAL
        self.safe_counter = 0

    def _target(self, risk_upper: float) -> DrivingMode:
        if risk_upper >= self.minimal_risk_threshold:
            return DrivingMode.MINIMAL_RISK
        if risk_upper >= self.degraded_threshold:
            return DrivingMode.DEGRADED
        return DrivingMode.NORMAL

    def update(self, risk_upper: float) -> DrivingMode:
        target = self._target(risk_upper)
        if self.latch_minimal_risk and self.mode is DrivingMode.MINIMAL_RISK:
            return self.mode
        if target > self.mode:
            self.mode = target
            self.safe_counter = 0
        elif target < self.mode:
            self.safe_counter += 1
            if self.safe_counter >= self.recovery_frames:
                self.mode = target
                self.safe_counter = 0
        else:
            self.safe_counter = 0
        return self.mode

    @staticmethod
    def longitudinal_action(mode: DrivingMode, speed_km_h: float) -> float:
        if mode is DrivingMode.NORMAL:
            return 0.28
        if mode is DrivingMode.DEGRADED:
            return -0.15 if speed_km_h > 18.0 else 0.08
        return -0.85 if speed_km_h > 1.0 else -1.0
