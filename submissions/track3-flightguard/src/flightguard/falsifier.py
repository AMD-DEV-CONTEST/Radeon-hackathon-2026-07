"""Deterministic search primitives for FlightGuard Causal Falsifier."""

from __future__ import annotations

import hashlib
import json
import math
import random
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

LATENT_NAMES = (
    "thrust_loss_over_0_07",
    "wind_x_over_0_6",
    "wind_y_over_0_6",
    "wind_z_over_0_2",
    "delay_latent",
)
INITIAL_MEAN = (0.5, 0.0, 0.0, 0.0, 0.5)
INITIAL_COVARIANCE_DIAGONAL = (
    1.0 / 12.0,
    0.25,
    0.25,
    1.0 / 3.0,
    1.0 / 12.0,
)
DELAY_LATENT_MAX = 1.0 - 2.0**-24
CANONICAL_DECIMAL_PLACES = 12


def canonicalize_float(value: float) -> float:
    """Quantize a finite scalar before it can affect ranking or later sampling."""

    numeric = float(value)
    if not math.isfinite(numeric):
        raise ValueError("canonical values must be finite")
    rounded = round(numeric, CANONICAL_DECIMAL_PLACES)
    return 0.0 if rounded == 0.0 else rounded


def canonicalize_latent(
    latent: Sequence[float],
) -> tuple[float, float, float, float, float]:
    """Return the frozen cross-platform representation of a valid latent point."""

    validated = _validate_latent(latent)
    canonical = tuple(canonicalize_float(value) for value in validated)
    return _validate_latent(canonical)


def canonical_fault_candidate(latent: Sequence[float]) -> FaultCandidate:
    """Build a candidate whose latent and derived burden share one quantization."""

    return FaultCandidate.from_latent(canonicalize_latent(latent))


def canonicalize_cem_state(state: CemState) -> CemState:
    """Quantize CEM state before serializing it or drawing another generation."""

    mean = tuple(canonicalize_float(value) for value in state.mean)
    covariance = tuple(
        tuple(canonicalize_float(value) for value in row) for row in state.covariance
    )
    return CemState(
        mean=mean,
        covariance=covariance,
        update_count=state.update_count,
    )


def require_registered_output_path(
    protocol: Mapping[str, Any],
    actual: Path,
    *relative_parts: str,
) -> Path:
    """Require an artifact path to occupy its only preregistered run slot."""

    independence = protocol.get("independence_from_v3")
    if not isinstance(independence, Mapping):
        raise TypeError("protocol independence contract is missing")
    raw_root = independence.get("output_root")
    if not isinstance(raw_root, str) or not raw_root:
        raise ValueError("protocol output root is missing")
    root = Path(raw_root).expanduser()
    if not root.is_absolute():
        raise ValueError("protocol output root must be absolute")
    expected = root.joinpath(*relative_parts).resolve()
    resolved = actual.expanduser().resolve()
    if resolved != expected:
        raise ValueError(
            f"artifact path differs from its preregistered slot: "
            f"expected {expected}, got {resolved}"
        )
    return resolved


def _canonical_sha256(payload: Mapping[str, Any]) -> str:
    serialized = json.dumps(
        payload,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(serialized).hexdigest()


def _validate_latent(
    latent: Sequence[float],
) -> tuple[float, float, float, float, float]:
    if len(latent) != len(LATENT_NAMES):
        raise ValueError(f"latent must have {len(LATENT_NAMES)} dimensions")
    values = tuple(float(value) for value in latent)
    if not all(math.isfinite(value) for value in values):
        raise ValueError("latent values must be finite")
    thrust_loss, wind_x, wind_y, wind_z, delay = values
    if not 0.0 <= thrust_loss <= 1.0:
        raise ValueError("thrust-loss latent must lie in [0, 1]")
    if wind_x * wind_x + wind_y * wind_y > 1.0 + 1.0e-12:
        raise ValueError("horizontal-wind latent must lie in the unit disk")
    if not -1.0 <= wind_z <= 1.0:
        raise ValueError("vertical-wind latent must lie in [-1, 1]")
    if not 0.0 <= delay <= DELAY_LATENT_MAX:
        raise ValueError("delay latent must lie in [0, 1 - 2^-24]")
    return values


@dataclass(frozen=True)
class FaultCandidate:
    """One bounded latent point and its decoded onset fault."""

    latent: tuple[float, float, float, float, float]
    thrust_scale: float
    wind_acceleration_mps2: tuple[float, float, float]
    action_delay_steps: int
    candidate_id: str
    fault_burden: float

    @classmethod
    def from_latent(cls, latent: Sequence[float]) -> FaultCandidate:
        values = _validate_latent(latent)
        thrust_scale = round(1.0 - 0.07 * values[0], 9)
        wind = (
            round(0.60 * values[1], 9),
            round(0.60 * values[2], 9),
            round(0.20 * values[3], 9),
        )
        action_delay_steps = math.floor(7.0 * min(values[4], DELAY_LATENT_MAX))
        decoded = {
            "action_delay_steps": action_delay_steps,
            "thrust_scale": round(thrust_scale, 9),
            "wind_acceleration_mps2": [round(value, 9) for value in wind],
        }
        burden = (
            math.sqrt(
                values[0] ** 2
                + math.hypot(values[1], values[2]) ** 2
                + abs(values[3]) ** 2
                + (action_delay_steps / 6.0) ** 2
            )
            / 2.0
        )
        return cls(
            latent=values,
            thrust_scale=thrust_scale,
            wind_acceleration_mps2=wind,
            action_delay_steps=action_delay_steps,
            candidate_id=_canonical_sha256(decoded),
            fault_burden=burden,
        )

    def to_record(
        self,
        *,
        algorithm: str,
        replicate_index: int,
        generation: int,
        candidate_index: int,
    ) -> dict[str, Any]:
        if algorithm not in {"cem", "uniform", "structural"}:
            raise ValueError("algorithm must be cem, uniform, or structural")
        for name, value in (
            ("replicate_index", replicate_index),
            ("generation", generation),
            ("candidate_index", candidate_index),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        return {
            "candidate_id": self.candidate_id,
            "algorithm": algorithm,
            "replicate_index": replicate_index,
            "generation": generation,
            "candidate_index": candidate_index,
            "latent": dict(zip(LATENT_NAMES, self.latent, strict=True)),
            "scheduled": {
                "thrust_scale": self.thrust_scale,
                "wind_acceleration_mps2": list(self.wind_acceleration_mps2),
                "action_delay_steps": self.action_delay_steps,
            },
            "fault_burden": self.fault_burden,
        }


@dataclass(frozen=True)
class CemState:
    """Full-covariance Gaussian proposal in the frozen latent space."""

    mean: tuple[float, float, float, float, float]
    covariance: tuple[
        tuple[float, float, float, float, float],
        tuple[float, float, float, float, float],
        tuple[float, float, float, float, float],
        tuple[float, float, float, float, float],
        tuple[float, float, float, float, float],
    ]
    update_count: int = 0

    @classmethod
    def initial(cls) -> CemState:
        covariance = np.diag(INITIAL_COVARIANCE_DIAGONAL)
        return canonicalize_cem_state(
            cls(
                mean=tuple(canonicalize_float(value) for value in INITIAL_MEAN),
                covariance=tuple(tuple(float(value) for value in row) for row in covariance),
            )
        )

    def __post_init__(self) -> None:
        if len(self.mean) != len(LATENT_NAMES):
            raise ValueError("CEM mean dimension mismatch")
        covariance = np.asarray(self.covariance, dtype=np.float64)
        if covariance.shape != (len(LATENT_NAMES), len(LATENT_NAMES)):
            raise ValueError("CEM covariance dimension mismatch")
        if not np.isfinite(covariance).all():
            raise ValueError("CEM covariance must be finite")
        if not np.allclose(covariance, covariance.T, atol=1.0e-12):
            raise ValueError("CEM covariance must be symmetric")
        if np.linalg.eigvalsh(covariance).min() <= 0.0:
            raise ValueError("CEM covariance must be positive definite")
        if (
            isinstance(self.update_count, bool)
            or not isinstance(self.update_count, int)
            or self.update_count < 0
        ):
            raise ValueError("CEM update_count must be non-negative")

    def to_record(self) -> dict[str, Any]:
        return {
            "mean": dict(zip(LATENT_NAMES, self.mean, strict=True)),
            "covariance": [list(row) for row in self.covariance],
            "update_count": self.update_count,
        }


def sample_initial_prior(
    *,
    count: int,
    seed: int,
) -> list[FaultCandidate]:
    if count <= 0:
        raise ValueError("count must be positive")
    generator = random.Random(seed)
    candidates = []
    for _ in range(count):
        radius = math.sqrt(generator.random())
        angle = 2.0 * math.pi * generator.random()
        delay_bin = generator.randrange(7)
        delay_latent = (delay_bin + generator.random()) / 7.0
        candidates.append(
            canonical_fault_candidate(
                (
                    generator.random(),
                    radius * math.cos(angle),
                    radius * math.sin(angle),
                    2.0 * generator.random() - 1.0,
                    delay_latent,
                )
            )
        )
    return candidates


def sample_cem_candidates(
    *,
    count: int,
    seed: int,
    state: CemState,
    maximum_proposals: int,
) -> list[FaultCandidate]:
    if count <= 0:
        raise ValueError("count must be positive")
    if maximum_proposals < count:
        raise ValueError("maximum_proposals must be at least count")
    generator = np.random.Generator(np.random.PCG64(seed))
    mean = np.asarray(state.mean, dtype=np.float64)
    covariance = np.asarray(state.covariance, dtype=np.float64)
    candidates: list[FaultCandidate] = []
    proposals = 0
    while len(candidates) < count and proposals < maximum_proposals:
        proposals += 1
        latent = generator.multivariate_normal(mean, covariance)
        try:
            candidates.append(canonical_fault_candidate(latent))
        except ValueError:
            continue
    if len(candidates) != count:
        raise RuntimeError(
            f"CEM accepted {len(candidates)}/{count} candidates after {proposals} proposals"
        )
    return candidates


def summarize_candidate_episodes(
    episodes: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    records = list(episodes)
    if not records:
        raise ValueError("candidate episode list is empty")
    valid = [record for record in records if record.get("valid_causal_failure") is True]
    strikes = [record for record in valid if record.get("failure_type") == "strike"]
    maximum_errors = np.asarray(
        [float(record["maximum_estimation_error_m"]) for record in records],
        dtype=np.float64,
    )
    if not np.isfinite(maximum_errors).all() or (maximum_errors < 0.0).any():
        raise ValueError("candidate maximum estimation errors are invalid")
    return {
        "episode_count": len(records),
        "valid_causal_failure_count": len(valid),
        "causal_strike_count": len(strikes),
        "p90_maximum_estimation_error_m": float(np.quantile(maximum_errors, 0.90)),
    }


def candidate_rank_key(
    *,
    summary: Mapping[str, Any],
    candidate: FaultCandidate,
) -> tuple[float, float, float, float, str]:
    return (
        -int(summary["valid_causal_failure_count"]),
        -int(summary["causal_strike_count"]),
        -float(summary["p90_maximum_estimation_error_m"]),
        float(candidate.fault_burden),
        candidate.candidate_id,
    )


def select_elite_indices(
    candidates: Sequence[FaultCandidate],
    summaries: Sequence[Mapping[str, Any]],
    *,
    elite_count: int,
) -> list[int]:
    if len(candidates) != len(summaries):
        raise ValueError("candidate and summary counts differ")
    if not 0 < elite_count <= len(candidates):
        raise ValueError("elite_count must lie in [1, candidate_count]")
    return sorted(
        range(len(candidates)),
        key=lambda index: candidate_rank_key(
            summary=summaries[index],
            candidate=candidates[index],
        ),
    )[:elite_count]


def update_cem_state(
    state: CemState,
    candidates: Sequence[FaultCandidate],
    summaries: Sequence[Mapping[str, Any]],
    *,
    elite_count: int,
    elite_weight: float,
    covariance_eigenvalue_floor: float,
    covariance_eigenvalue_ceiling: float,
) -> tuple[CemState, list[int]]:
    if not 0.0 < elite_weight <= 1.0:
        raise ValueError("elite_weight must lie in (0, 1]")
    if not (0.0 < covariance_eigenvalue_floor <= covariance_eigenvalue_ceiling):
        raise ValueError("covariance eigenvalue bounds are invalid")
    elite_indices = select_elite_indices(
        candidates,
        summaries,
        elite_count=elite_count,
    )
    elite_latents = np.asarray(
        [candidates[index].latent for index in elite_indices],
        dtype=np.float64,
    )
    elite_mean = elite_latents.mean(axis=0)
    centered = elite_latents - elite_mean
    elite_covariance = centered.T @ centered / len(elite_indices)
    old_mean = np.asarray(state.mean, dtype=np.float64)
    old_covariance = np.asarray(state.covariance, dtype=np.float64)
    updated_mean = (1.0 - elite_weight) * old_mean + elite_weight * elite_mean
    updated_covariance = (1.0 - elite_weight) * old_covariance + elite_weight * elite_covariance
    eigenvalues, eigenvectors = np.linalg.eigh(updated_covariance)
    clipped = np.clip(
        eigenvalues,
        covariance_eigenvalue_floor,
        covariance_eigenvalue_ceiling,
    )
    updated_covariance = eigenvectors @ np.diag(clipped) @ eigenvectors.T
    updated_covariance = 0.5 * (updated_covariance + updated_covariance.T)
    return (
        canonicalize_cem_state(
            CemState(
                mean=tuple(float(value) for value in updated_mean),
                covariance=tuple(
                    tuple(float(value) for value in row) for row in updated_covariance
                ),
                update_count=state.update_count + 1,
            )
        ),
        elite_indices,
    )


def summarize_discovery(
    candidate_summaries: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    summaries = list(candidate_summaries)
    cumulative_failures = 0
    auc = 0
    first_failure_candidate_index = None
    for index, summary in enumerate(summaries):
        discovered = int(summary["valid_causal_failure_count"])
        cumulative_failures += discovered
        auc += cumulative_failures
        if discovered and first_failure_candidate_index is None:
            first_failure_candidate_index = index + 1
    return {
        "evaluated_candidates": len(summaries),
        "valid_causal_failures_discovered": cumulative_failures,
        "first_failure_candidate_index": first_failure_candidate_index,
        "anytime_cumulative_failure_auc": auc,
    }
