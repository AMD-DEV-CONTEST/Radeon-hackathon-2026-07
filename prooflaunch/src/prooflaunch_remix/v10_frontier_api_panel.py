from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Mapping, Sequence
from urllib.parse import urlparse

from .v10_contracts import V10ContractError


class CapabilityLane(str, Enum):
    AGENTIC_GTM = "agentic_gtm"
    LONG_CONTEXT_CRITIC = "long_context_critic"
    MULTIMODAL_GTM = "multimodal_gtm"
    SAFETY_CRITIC = "safety_critic"
    VIDEO_GENERATION = "video_generation"


class AccessClass(str, Enum):
    AMD_SPONSORED_QUOTA = "amd_sponsored_quota"
    ZERO_COST_RATE_LIMITED = "zero_cost_rate_limited"
    DIRECT_PAYG = "direct_payg"
    DEVELOPER_CREDITS = "developer_credits"
    LOCAL_OPEN_WEIGHT = "local_open_weight"


class OpenWeightStatus(str, Enum):
    VERIFIED = "verified"
    ANNOUNCED_NOT_VERIFIED = "announced_not_verified"
    NOT_OPEN_WEIGHT = "not_open_weight"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class FrontierModel:
    candidate_id: str
    provider: str
    api_model: str
    endpoint: str
    lane: CapabilityLane
    access_class: AccessClass
    api_key_env: str
    maximum_call_cost_usd: float
    source_url: str
    source_observed_at: str
    catalog_observed: bool
    open_weight_status: OpenWeightStatus
    competition_core_allowed: bool = False

    def __post_init__(self) -> None:
        parsed = urlparse(self.endpoint)
        if not all(
            value.strip()
            for value in (
                self.candidate_id,
                self.provider,
                self.api_model,
                self.api_key_env,
                self.source_observed_at,
            )
        ):
            raise V10ContractError("frontier candidate identity is incomplete")
        if parsed.scheme != "https" or not parsed.hostname:
            raise V10ContractError("frontier endpoint must be public HTTPS")
        if not self.source_url.startswith("https://"):
            raise V10ContractError("frontier candidate requires a primary source")
        if not math.isfinite(self.maximum_call_cost_usd) or self.maximum_call_cost_usd < 0:
            raise V10ContractError("every API candidate requires a finite non-negative call cap")
        if (
            self.maximum_call_cost_usd == 0
            and self.access_class is not AccessClass.ZERO_COST_RATE_LIMITED
        ):
            raise V10ContractError("only a verified zero-cost route may use a zero call cap")
        if (
            self.maximum_call_cost_usd > 0
            and self.access_class is AccessClass.ZERO_COST_RATE_LIMITED
        ):
            raise V10ContractError("a zero-cost route must have an exact zero call cap")
        if self.competition_core_allowed:
            raise V10ContractError("external API models cannot enter the competition core")


@dataclass(frozen=True)
class QualificationStage:
    name: str
    cases_per_candidate: int
    maximum_output_units: int
    promotion_count: int
    requires_same_input: bool = True

    def __post_init__(self) -> None:
        if not self.name.strip() or min(
            self.cases_per_candidate,
            self.maximum_output_units,
            self.promotion_count,
        ) <= 0:
            raise V10ContractError("qualification stage bounds must be positive")


DEFAULT_AGENT_LADDER = (
    QualificationStage("schema_smoke", 1, 512, 4),
    QualificationStage("agentic_contract", 2, 1536, 2),
    QualificationStage("frozen_gtm_final", 5, 4096, 1),
)


def request_ceiling(
    candidate_count: int,
    stages: Sequence[QualificationStage] = DEFAULT_AGENT_LADDER,
) -> int:
    """Return the maximum requests for a hard-gated successive-halving run.

    The first stage sees every candidate.  Later stages see at most the prior
    stage's promotion count.  This makes a daily provider limit mechanically
    checkable before any network request is sent.
    """

    if candidate_count <= 0 or not stages:
        raise V10ContractError("request ceiling requires candidates and stages")
    active = candidate_count
    total = 0
    for stage in stages:
        total += active * stage.cases_per_candidate
        active = min(active, stage.promotion_count)
    return total


def admitted_candidates(
    candidates: Sequence[FrontierModel],
    *,
    credential_env_present: Mapping[str, bool],
) -> tuple[FrontierModel, ...]:
    identities: set[str] = set()
    admitted = []
    for candidate in candidates:
        if candidate.candidate_id in identities:
            raise V10ContractError("frontier candidate identities must be unique")
        identities.add(candidate.candidate_id)
        if candidate.catalog_observed and credential_env_present.get(
            candidate.api_key_env, False
        ):
            admitted.append(candidate)
    return tuple(admitted)


@dataclass(frozen=True)
class AgenticObservation:
    candidate_id: str
    frozen_brief_sha256: str
    schema_valid: bool
    dependency_graph_valid: bool
    tool_calls_valid: bool
    claim_gate_passed: bool
    human_release_gate_present: bool
    artifact_coverage: int
    artifact_possible: int
    latency_ms: float
    cost_usd: float

    @property
    def promotion_eligible(self) -> bool:
        return (
            len(self.frozen_brief_sha256) == 64
            and self.schema_valid
            and self.dependency_graph_valid
            and self.tool_calls_valid
            and self.claim_gate_passed
            and self.human_release_gate_present
            and self.artifact_possible > 0
            and self.artifact_coverage == self.artifact_possible
            and math.isfinite(self.latency_ms)
            and self.latency_ms > 0
            and math.isfinite(self.cost_usd)
            and self.cost_usd >= 0
        )

    @property
    def quality_score(self) -> float:
        if not self.promotion_eligible:
            return 0.0
        return self.artifact_coverage / self.artifact_possible


def rank_agentic_observations(
    observations: Sequence[AgenticObservation],
) -> tuple[AgenticObservation, ...]:
    if not observations:
        raise V10ContractError("at least one observation is required")
    hashes = {item.frozen_brief_sha256 for item in observations}
    if len(hashes) != 1:
        raise V10ContractError("candidate observations must use one frozen brief")
    return tuple(
        sorted(
            (item for item in observations if item.promotion_eligible),
            key=lambda item: (
                -item.quality_score,
                item.cost_usd,
                item.latency_ms,
                item.candidate_id,
            ),
        )
    )


@dataclass(frozen=True)
class MiniMaxVideoRequest:
    prompt: str
    duration_seconds: int = 5
    resolution: str = "2K"
    ratio: str = "16:9"
    model: str = "MiniMax-H3"
    first_frame_image: str | None = None

    def __post_init__(self) -> None:
        documented = {"MiniMax-H3", "MiniMax-Hailuo-2.3", "MiniMax-Hailuo-2.3-Fast"}
        if self.model not in documented:
            raise V10ContractError("only officially documented MiniMax video models are admitted")
        if self.model == "MiniMax-H3":
            if not 4 <= self.duration_seconds <= 15:
                raise V10ContractError("MiniMax-H3 duration must be between four and fifteen seconds")
            if self.resolution != "2K":
                raise V10ContractError("MiniMax-H3 currently requires 2K output")
        else:
            if self.duration_seconds not in {6, 10}:
                raise V10ContractError("Hailuo 2.3 duration must be six or ten seconds")
            if self.resolution not in {"768P", "1080P"}:
                raise V10ContractError("Hailuo 2.3 resolution must be 768P or 1080P")
            if self.resolution == "1080P" and self.duration_seconds != 6:
                raise V10ContractError("official Hailuo 2.3 1080P generation is limited to six seconds")
        if not self.prompt.strip():
            raise V10ContractError("MiniMax video requests require a non-empty prompt")
        if self.first_frame_image:
            parsed = urlparse(self.first_frame_image)
            if parsed.scheme != "https" or not parsed.hostname:
                raise V10ContractError("first-frame image must be a public HTTPS locator")

    def payload(self) -> dict[str, object]:
        if self.model == "MiniMax-H3":
            content: list[dict[str, object]] = [
                {"type": "text", "text": self.prompt},
            ]
            if self.first_frame_image:
                content.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": self.first_frame_image},
                        "role": "first_frame",
                    }
                )
            payload: dict[str, object] = {
                "model": self.model,
                "content": content,
                "resolution": self.resolution,
                "duration": self.duration_seconds,
                "ratio": "adaptive" if self.first_frame_image else self.ratio,
            }
            return payload
        payload: dict[str, object] = {
            "model": self.model,
            "prompt": self.prompt,
            "resolution": self.resolution,
            "duration": self.duration_seconds,
        }
        if self.first_frame_image:
            payload["first_frame_image"] = self.first_frame_image
        return payload
