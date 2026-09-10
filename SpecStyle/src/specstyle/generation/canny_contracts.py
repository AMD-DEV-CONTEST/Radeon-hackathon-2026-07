"""Lightweight contracts for deterministic Canny preprocessing."""

from __future__ import annotations

from dataclasses import dataclass

from specstyle.errors import DomainError


@dataclass(frozen=True, slots=True)
class CannyProcessorConfig:
    low_threshold: int
    high_threshold: int
    aperture_size: int
    l2_gradient: bool

    def __post_init__(self) -> None:
        if (
            type(self.low_threshold) is not int
            or type(self.high_threshold) is not int
            or not 0 <= self.low_threshold < self.high_threshold <= 255
            or type(self.aperture_size) is not int
            or self.aperture_size != 3
            or type(self.l2_gradient) is not bool
            or self.l2_gradient is not False
        ):
            raise DomainError("invalid Canny processor config")


def _rebuild_canny_processor_config(value: object, /) -> CannyProcessorConfig:
    if type(value) is not CannyProcessorConfig:
        raise DomainError("invalid Canny processor config")
    return CannyProcessorConfig(
        value.low_threshold,
        value.high_threshold,
        value.aperture_size,
        value.l2_gradient,
    )
