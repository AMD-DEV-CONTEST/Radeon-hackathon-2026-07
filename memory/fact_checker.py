"""Fact conflict detector — cross-references user statements against the world fact graph.

When a user mentions an event or time period, checks if their timeline
is consistent with known historical facts. Flags conflicts for gentle
confirmation by the interviewer agent.
"""

import logging

from database.neo4j_client import Neo4jClient

logger = logging.getLogger(__name__)


class FactConflict:
    """A detected conflict between user narrative and world facts."""

    def __init__(self, conflict_type: str, user_claim: str, fact: str, detail: str = ""):
        self.type = conflict_type  # "temporal", "location", "identity", "anomaly"
        self.user_claim = user_claim
        self.fact = fact
        self.detail = detail


def check_temporal_consistency(
    user_birth_year: int | None,
    event_year: int,
    event_label: str,
    user_age_at_event: int | None = None,
) -> FactConflict | None:
    """Check if a user's claimed event participation makes temporal sense.

    Args:
        user_birth_year: User's birth year (None if unknown).
        event_year: Year the historical event occurred.
        event_label: Name of the event.
        user_age_at_event: Age the user claims they were (if mentioned).

    Returns:
        FactConflict if something doesn't add up, None if consistent.
    """
    if user_birth_year is None:
        return None

    # Can't participate before birth
    if event_year < user_birth_year:
        return FactConflict(
            "temporal",
            f"User claims involvement in {event_label}",
            f"{event_label} occurred in {event_year}, but user was born in {user_birth_year}",
            f"The event happened {user_birth_year - event_year} years before the user was born",
        )

    # Implausible age (e.g., 2-year-old attending university)
    if user_age_at_event is not None:
        age_at_event = event_year - user_birth_year
        if age_at_event != user_age_at_event and abs(age_at_event - user_age_at_event) > 3:
            return FactConflict(
                "temporal",
                f"User claims they were {user_age_at_event} at {event_label}",
                f"Based on birth year {user_birth_year}, they would have been {age_at_event}",
                "Age discrepancy > 3 years",
            )

    return None


def check_location_consistency(
    user_locations: list[str], event_location: str, event_year: int, context: str = ""
) -> FactConflict | None:
    """Check if user's claimed location makes geographic sense for an event.

    Args:
        user_locations: Places the user has lived/traveled.
        event_location: Where the event occurred.
        event_year: When it happened.
        context: Additional context about the user's travel.

    Returns:
        FactConflict if the user couldn't have been at that location.
    """
    if not user_locations or not event_location:
        return None

    # Simple: if event is in a country the user never mentioned, flag for confirmation
    # This is a soft check — people travel
    if event_location not in user_locations:
        return FactConflict(
            "location",
            f"User claims to have been at {event_location} during {event_year}",
            f"This location hasn't appeared in the user's known locations: {user_locations}",
            "User may have traveled — ask for confirmation",
        )

    return None


def check_identity_consistency(
    user_name: str, claimed_identity: str, context: str = ""
) -> FactConflict | None:
    """Check if a user's claimed identity makes sense against known facts.

    This is a soft check — mostly for extreme cases like claiming to be
    a historical figure or holding an impossible combination of roles.
    """
    # Future: check against a list of historical figures
    # For now, just log for manual review
    logger.debug("Identity check: %s claims %s", user_name, claimed_identity)
    return None


def detect_fact_conflicts(
    user_query: str, user_birth_year: int | None = None, user_locations: list[str] | None = None
) -> list[FactConflict]:
    """Run all consistency checks against a user statement.

    Args:
        user_query: The user's latest statement.
        user_birth_year: Known birth year (from persona or previous answers).
        user_locations: Known locations from the user's graph.

    Returns:
        List of FactConflict objects (empty if all consistent).
    """
    conflicts = []

    # Extract years mentioned in the query
    import re

    years = [int(y) for y in re.findall(r"\b(19\d{2}|20\d{2})\b", user_query)]

    # Extract age mentions
    age_match = re.search(r"(\d+)\s*岁", user_query)
    claimed_age = int(age_match.group(1)) if age_match else None

    if user_birth_year and years:
        for year in years:
            conflict = check_temporal_consistency(
                user_birth_year,
                year,
                f"event in {year}",
                claimed_age,
            )
            if conflict:
                conflicts.append(conflict)

    # Check for event references
    known_events = _get_known_events()
    for event in known_events:
        if event["label"] in user_query or (
            event.get("keywords") and any(k in user_query for k in event.get("keywords", []))
        ):
            if user_birth_year:
                conflict = check_temporal_consistency(
                    user_birth_year,
                    event["year"],
                    event["label"],
                )
                if conflict:
                    conflicts.append(conflict)
            if user_locations and event.get("location"):
                conflict = check_location_consistency(
                    user_locations,
                    event["location"],
                    event["year"],
                )
                if conflict:
                    conflicts.append(conflict)

    return conflicts


def _get_known_events() -> list[dict]:
    """Fetch all events from the fact graph for cross-referencing."""
    try:
        result = Neo4jClient.execute(
            "MATCH (ev:Event) "
            "WHERE ev.time_period IS NOT NULL "
            "RETURN ev.label AS label, ev.time_period AS time_period, "
            "ev.description AS description "
            "ORDER BY ev.order ASC "
            "LIMIT 500"
        )
        return [
            {
                "label": r["label"],
                "year": int(r["time_period"]) if r["time_period"].isdigit() else 0,
                "keywords": r.get("description", "").split(),
            }
            for r in result
        ]
    except Exception:
        return []


def format_conflict_for_interviewer(conflicts: list[FactConflict]) -> str:
    """Format detected conflicts as a natural, gentle confirmation prompt.

    Used by the interviewer agent to ask the user for clarification.
    """
    if not conflicts:
        return ""

    if len(conflicts) == 1:
        c = conflicts[0]
        return (
            f"[FACT CHECK]: {c.detail}. "
            f"Consider asking: '您提到{c.user_claim}, 但{c.fact}。"
            f"可能是时间记错了？还是有什么特殊的情况？'"
        )

    lines = ["[FACT CHECK]: Multiple potential inconsistencies detected:"]
    for c in conflicts:
        lines.append(f"  - {c.type}: {c.detail}")
    lines.append("  Ask the user gently: '我注意到您提到的一些时间似乎对不上，能帮我确认一下吗？'")
    return "\n".join(lines)
