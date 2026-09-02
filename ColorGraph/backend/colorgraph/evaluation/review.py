from __future__ import annotations

import hashlib
import math
import random
from collections import defaultdict
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated

import numpy as np
from pydantic import Field, model_validator

from colorgraph.evaluation.metrics import fleiss_kappa
from colorgraph.evaluation.models import StrictEvaluationModel


class Preference(StrEnum):
    A = "a"
    B = "b"
    TIE = "tie"
    REJECT = "reject"


class ExpertReviewer(StrictEvaluationModel):
    id: str
    years_experience: Annotated[float, Field(ge=1)]
    roles: list[str] = Field(min_length=1)
    color_vision_screened: bool
    display_calibration_confirmed: bool


class ViewingEnvironment(StrictEvaluationModel):
    display_model: str
    calibration_profile_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    white_point: str
    peak_luminance_nits: Annotated[float, Field(gt=0)]
    black_luminance_nits: Annotated[float, Field(ge=0)]
    color_space: str
    eotf: str
    ambient_lux: Annotated[float, Field(ge=0)]
    viewing_distance_meters: Annotated[float, Field(gt=0)]
    calibration_date: datetime


class ReviewPair(StrictEvaluationModel):
    id: str
    source_id: str
    candidate_a_id: str
    candidate_b_id: str


class BlindedAssignment(StrictEvaluationModel):
    pair_id: str
    source_id: str
    blind_a: str
    blind_b: str


class ReviewerSession(StrictEvaluationModel):
    reviewer_id: str
    assignments: list[BlindedAssignment]


class ReviewSessionKey(StrictEvaluationModel):
    session_id: str
    seed: int
    canonical_pairs: dict[str, dict[str, str]]
    mappings: dict[str, dict[str, str]]


class ReviewSession(StrictEvaluationModel):
    schema_version: str = "colorgraph.subjective-review/v1"
    session_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    protocol: str = "BT.500/P.910-inspired paired comparison"
    viewing_environment: ViewingEnvironment
    reviewers: list[ExpertReviewer] = Field(min_length=3)
    sessions: list[ReviewerSession]

    @model_validator(mode="after")
    def validate_reviewers(self) -> ReviewSession:
        reviewer_ids = [reviewer.id for reviewer in self.reviewers]
        if len(reviewer_ids) != len(set(reviewer_ids)):
            raise ValueError("reviewer ids must be unique")
        if not all(
            reviewer.color_vision_screened
            and reviewer.display_calibration_confirmed
            for reviewer in self.reviewers
        ):
            raise ValueError(
                "every expert reviewer must confirm color-vision screening "
                "and display calibration"
            )
        session_reviewer_ids = [
            session.reviewer_id
            for session in self.sessions
        ]
        if (
            len(session_reviewer_ids) != len(set(session_reviewer_ids))
            or set(session_reviewer_ids) != set(reviewer_ids)
        ):
            raise ValueError("review sessions must cover every reviewer exactly once")
        return self


class ReviewResponse(StrictEvaluationModel):
    session_id: str
    reviewer_id: str
    pair_id: str
    preference: Preference
    rejection_reason: str | None = None
    confidence: Annotated[int, Field(ge=1, le=5)]
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def validate_rejection_reason(self) -> ReviewResponse:
        if self.preference == Preference.REJECT and not self.rejection_reason:
            raise ValueError("rejected pairs require a rejection_reason")
        if self.preference != Preference.REJECT and self.rejection_reason:
            raise ValueError("rejection_reason is only valid for rejected pairs")
        return self


class PairReviewSummary(StrictEvaluationModel):
    pair_id: str
    valid_ratings: int
    rejected_ratings: int
    candidate_a_preference: float
    candidate_a_ci95_low: float
    candidate_a_ci95_high: float
    ties: int
    rejection_reasons: list[str]


class ReviewAggregate(StrictEvaluationModel):
    schema_version: str = "colorgraph.subjective-review-aggregate/v1"
    session_id: str
    pair_summaries: list[PairReviewSummary]
    fleiss_kappa: float
    minimum_three_experts_met: bool


def _blind_code(session_id: str, reviewer_id: str, pair_id: str, side: str) -> str:
    digest = hashlib.sha256(
        f"{session_id}|{reviewer_id}|{pair_id}|{side}".encode()
    ).hexdigest()
    return digest[:10].upper()


def build_blinded_review_session(
    session_id: str,
    pairs: list[ReviewPair],
    reviewers: list[ExpertReviewer],
    *,
    seed: int,
    viewing_environment: ViewingEnvironment,
) -> tuple[ReviewSession, ReviewSessionKey]:
    if len(reviewers) < 3:
        raise ValueError("subjective review requires at least three expert reviewers")
    sessions: list[ReviewerSession] = []
    mappings: dict[str, dict[str, str]] = {}
    for reviewer_index, reviewer in enumerate(reviewers):
        randomizer = random.Random(seed + reviewer_index * 104729)
        shuffled = list(pairs)
        randomizer.shuffle(shuffled)
        assignments: list[BlindedAssignment] = []
        for pair in shuffled:
            swap = bool(randomizer.getrandbits(1))
            candidate_a = pair.candidate_b_id if swap else pair.candidate_a_id
            candidate_b = pair.candidate_a_id if swap else pair.candidate_b_id
            blind_a = _blind_code(session_id, reviewer.id, pair.id, "a")
            blind_b = _blind_code(session_id, reviewer.id, pair.id, "b")
            assignments.append(
                BlindedAssignment(
                    pair_id=pair.id,
                    source_id=pair.source_id,
                    blind_a=blind_a,
                    blind_b=blind_b,
                )
            )
            mappings[f"{reviewer.id}:{pair.id}"] = {
                blind_a: candidate_a,
                blind_b: candidate_b,
            }
        sessions.append(
            ReviewerSession(
                reviewer_id=reviewer.id,
                assignments=assignments,
            )
        )
    return (
        ReviewSession(
            session_id=session_id,
            viewing_environment=viewing_environment,
            reviewers=reviewers,
            sessions=sessions,
        ),
        ReviewSessionKey(
            session_id=session_id,
            seed=seed,
            canonical_pairs={
                pair.id: {
                    "candidate_a": pair.candidate_a_id,
                    "candidate_b": pair.candidate_b_id,
                }
                for pair in pairs
            },
            mappings=mappings,
        ),
    )


def _wilson_interval(successes: int, total: int) -> tuple[float, float]:
    if total == 0:
        return 0.0, 1.0
    z = 1.959963984540054
    proportion = successes / total
    denominator = 1 + z**2 / total
    center = (proportion + z**2 / (2 * total)) / denominator
    margin = (
        z
        * math.sqrt(
            proportion * (1 - proportion) / total
            + z**2 / (4 * total**2)
        )
        / denominator
    )
    return max(0.0, center - margin), min(1.0, center + margin)


def aggregate_review_responses(
    session: ReviewSession,
    session_key: ReviewSessionKey,
    responses: list[ReviewResponse],
) -> ReviewAggregate:
    if session_key.session_id != session.session_id:
        raise ValueError("review session key belongs to another session")
    reviewer_ids = {reviewer.id for reviewer in session.reviewers}
    pair_ids = {
        assignment.pair_id
        for reviewer_session in session.sessions
        for assignment in reviewer_session.assignments
    }
    seen: set[tuple[str, str]] = set()
    grouped: dict[str, list[ReviewResponse]] = defaultdict(list)
    for response in responses:
        if response.session_id != session.session_id:
            raise ValueError("review response belongs to another session")
        if response.reviewer_id not in reviewer_ids or response.pair_id not in pair_ids:
            raise ValueError("review response references an unknown reviewer or pair")
        key = (response.reviewer_id, response.pair_id)
        if key in seen:
            raise ValueError(f"duplicate review response for {key}")
        seen.add(key)
        grouped[response.pair_id].append(response)

    summaries: list[PairReviewSummary] = []
    category_counts: list[list[int]] = []
    minimum_met = True
    assignments = {
        (reviewer_session.reviewer_id, assignment.pair_id): assignment
        for reviewer_session in session.sessions
        for assignment in reviewer_session.assignments
    }
    for pair_id in sorted(pair_ids):
        pair_responses = grouped.get(pair_id, [])
        valid = [
            response
            for response in pair_responses
            if response.preference != Preference.REJECT
        ]
        minimum_met &= len(valid) >= 3
        canonical = session_key.canonical_pairs.get(pair_id)
        if canonical is None:
            raise ValueError(f"review key lacks canonical mapping for {pair_id!r}")
        a_count = 0
        b_count = 0
        for response in valid:
            if response.preference == Preference.TIE:
                continue
            assignment = assignments[(response.reviewer_id, pair_id)]
            blind_code = (
                assignment.blind_a
                if response.preference == Preference.A
                else assignment.blind_b
            )
            mapping = session_key.mappings.get(
                f"{response.reviewer_id}:{pair_id}",
                {},
            )
            selected_candidate = mapping.get(blind_code)
            if selected_candidate == canonical["candidate_a"]:
                a_count += 1
            elif selected_candidate == canonical["candidate_b"]:
                b_count += 1
            else:
                raise ValueError(
                    f"review key cannot resolve {response.reviewer_id}:{pair_id}"
                )
        ties = sum(response.preference == Preference.TIE for response in valid)
        decisive = a_count + b_count
        low, high = _wilson_interval(a_count, decisive)
        summaries.append(
            PairReviewSummary(
                pair_id=pair_id,
                valid_ratings=len(valid),
                rejected_ratings=len(pair_responses) - len(valid),
                candidate_a_preference=(a_count / decisive if decisive else 0.5),
                candidate_a_ci95_low=low,
                candidate_a_ci95_high=high,
                ties=ties,
                rejection_reasons=[
                    response.rejection_reason
                    for response in pair_responses
                    if response.rejection_reason is not None
                ],
            )
        )
        category_counts.append([a_count, b_count, ties])
    if not minimum_met:
        raise ValueError("every pair requires at least three valid expert ratings")
    return ReviewAggregate(
        session_id=session.session_id,
        pair_summaries=summaries,
        fleiss_kappa=fleiss_kappa(np.asarray(category_counts)),
        minimum_three_experts_met=minimum_met,
    )
