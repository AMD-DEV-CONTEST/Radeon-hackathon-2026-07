"""Self-growth candidate generation: generate pending rule/skill candidates from runtime feedback.

Design-audit fixes:
- M4: define the pending → review → approved/rejected → published lifecycle
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# M4: self-growth candidate status constants
CANDIDATE_PENDING = "pending"
CANDIDATE_REVIEW = "review"
CANDIDATE_APPROVED = "approved"
CANDIDATE_REJECTED = "rejected"
CANDIDATE_PUBLISHED = "published"

# M4: valid status transitions
VALID_TRANSITIONS = {
    CANDIDATE_PENDING: {CANDIDATE_REVIEW, CANDIDATE_REJECTED},
    CANDIDATE_REVIEW: {CANDIDATE_APPROVED, CANDIDATE_REJECTED},
    CANDIDATE_APPROVED: {CANDIDATE_PUBLISHED},
    CANDIDATE_REJECTED: set(),  # terminal state
    CANDIDATE_PUBLISHED: set(),  # terminal state
}


async def generate_candidates(
    memory_agent: Any,
    observations: list[dict],
    max_candidates: int = 5,
) -> list[dict]:
    """Generate pending rule/skill candidates from runtime feedback.

    M4 lifecycle: pending → review → approved/rejected → published
    This function only generates pending candidates; confirmation is decided by the business system.

    Args:
        memory_agent: the Agent instance used for analysis
        observations: observation records list, each item contains text and observation_id
        max_candidates: M4 maximum number of candidates to generate

    Returns:
        candidate list, each item contains candidate_type, summary, evidence_refs, status, created_at
    """
    try:
        result = await (
            memory_agent
            .input({"observations": observations})
            .instruct([
                "Analyze whether the observations contain long-term asset candidates worth preserving.",
                "Recurring requirements that must be followed are classified as rule; methods composed of executable steps are classified as skill.",
                "Only return candidates supported by observation_id; do not judge whether they are effective.",
                f"Return at most {max_candidates} candidates.",
            ])
            .output({
                "candidates": [{
                    "candidate_type": (str, "rule or skill", "not_null"),
                    "summary": (str, "candidate description", "not_null"),
                    "evidence_refs": [(str, "supporting observation_id", "not_null")],
                    "validation_needed": [(str, "validation before formal adoption", "not_null")],
                }],
            }, format="json")
            .async_start()
        )
        import time
        candidates = [
            {
                **c,
                "status": CANDIDATE_PENDING,  # M4: uniformly marked as pending
                "created_at": time.time(),
                "lifecycle": "pending → review → approved → published",
            }
            for c in result.get("candidates", [])[:max_candidates]
        ]
        logger.info("generated self-growth candidates: %d (status=pending)", len(candidates))
        return candidates
    except Exception as e:
        logger.error("self-growth candidate generation failed: %s", e)
        return []


def transition_candidate(candidate: dict, new_status: str) -> dict:
    """M4: execute a candidate status transition, validating its legality.

    Args:
        candidate: candidate dictionary (contains the status field)
        new_status: the target status

    Returns:
        the updated candidate dictionary

    Raises:
        ValueError: illegal status transition
    """
    current = candidate.get("status", CANDIDATE_PENDING)
    if new_status not in VALID_TRANSITIONS.get(current, set()):
        raise ValueError(
            f"Illegal status transition: {current} → {new_status}. "
            f"Valid targets: {VALID_TRANSITIONS.get(current, set())}"
        )
    return {**candidate, "status": new_status}