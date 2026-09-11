from __future__ import annotations

from dataclasses import dataclass
import math
import statistics


@dataclass(frozen=True)
class EpisodeResult:
    success: bool
    retries: int
    duration_seconds: float
    inference_latency_ms: tuple[float, ...]
    dropped: bool = False
    max_contact_force_n: float = 0.0

    def validate(self) -> None:
        if self.retries < 0:
            raise ValueError("retries cannot be negative")
        if self.duration_seconds <= 0:
            raise ValueError("duration_seconds must be positive")
        if any(value < 0 for value in self.inference_latency_ms):
            raise ValueError("inference latency cannot be negative")
        if self.max_contact_force_n < 0:
            raise ValueError("max contact force cannot be negative")


class MetricsAccumulator:
    def __init__(self) -> None:
        self._episodes: list[EpisodeResult] = []

    def add(self, result: EpisodeResult) -> None:
        result.validate()
        self._episodes.append(result)

    def summary(self) -> dict[str, float | int]:
        if not self._episodes:
            raise ValueError("at least one episode is required")

        count = len(self._episodes)
        successes = sum(result.success for result in self._episodes)
        first_attempt = sum(
            result.success and result.retries == 0 for result in self._episodes
        )
        retry_episodes = [result for result in self._episodes if result.retries > 0]
        recovered = sum(result.success for result in retry_episodes)
        dropped = sum(result.dropped for result in self._episodes)
        duration = sum(result.duration_seconds for result in self._episodes)
        latencies = sorted(
            latency
            for result in self._episodes
            for latency in result.inference_latency_ms
        )
        p95_index = max(0, math.ceil(0.95 * len(latencies)) - 1) if latencies else 0
        success_ci = wilson_interval(successes, count)
        first_attempt_ci = wilson_interval(first_attempt, count)
        recovery_ci = wilson_interval(recovered, len(retry_episodes))
        drop_ci = wilson_interval(dropped, count)

        return {
            "episodes": count,
            "successes": successes,
            "success_rate": successes / count,
            "success_rate_ci95_low": success_ci[0],
            "success_rate_ci95_high": success_ci[1],
            "first_attempt_successes": first_attempt,
            "first_attempt_success_rate": first_attempt / count,
            "first_attempt_success_rate_ci95_low": first_attempt_ci[0],
            "first_attempt_success_rate_ci95_high": first_attempt_ci[1],
            "retry_episodes": len(retry_episodes),
            "recovered_episodes": recovered,
            "recovery_success_rate": recovered / len(retry_episodes) if retry_episodes else 0.0,
            "recovery_success_rate_ci95_low": recovery_ci[0],
            "recovery_success_rate_ci95_high": recovery_ci[1],
            "dropped_episodes": dropped,
            "drop_rate": dropped / count,
            "drop_rate_ci95_low": drop_ci[0],
            "drop_rate_ci95_high": drop_ci[1],
            "mean_duration_seconds": duration / count,
            "successful_parcels_per_hour": successes / duration * 3600,
            "mean_inference_latency_ms": statistics.fmean(latencies) if latencies else 0.0,
            "p95_inference_latency_ms": latencies[p95_index] if latencies else 0.0,
            "max_contact_force_n": max(
                result.max_contact_force_n for result in self._episodes
            ),
        }


def wilson_interval(successes: int, trials: int, z: float = 1.959963984540054) -> tuple[float, float]:
    """Return a two-sided Wilson score interval for a binomial proportion.

    A zero-trial rate is unknown rather than observed-zero, so it deliberately
    returns the full [0, 1] interval. This matters for recovery metrics when no
    episode used a retry.
    """
    if trials < 0 or successes < 0 or successes > trials:
        raise ValueError("Wilson interval requires 0 <= successes <= trials")
    if not math.isfinite(z) or z <= 0:
        raise ValueError("Wilson interval requires a finite positive z score")
    if trials == 0:
        return 0.0, 1.0
    proportion = successes / trials
    z_squared = z * z
    denominator = 1.0 + z_squared / trials
    center = (proportion + z_squared / (2.0 * trials)) / denominator
    margin = (
        z
        * math.sqrt(
            proportion * (1.0 - proportion) / trials
            + z_squared / (4.0 * trials * trials)
        )
        / denominator
    )
    return max(0.0, center - margin), min(1.0, center + margin)
