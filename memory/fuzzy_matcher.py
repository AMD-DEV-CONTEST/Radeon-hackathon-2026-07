"""Fuzzy event matcher — locate existing events from user descriptions.

Convention:
1. Date co-occurrence: users mentioning a year → candidate events from that year
2. Keyword overlap: score each candidate by shared keywords with user statement
3. Location match: if user mentions a place, boost events at that location
4. Score threshold: events above threshold → interviewer confirms with user
5. Fallback: if nothing matches → treat as new information

This replaces brittle substring matching with a proper scoring system.
"""

import logging
import re

from database.neo4j_client import Neo4jClient

logger = logging.getLogger(__name__)


def fuzzy_match_events(user_statement: str, min_score: float = 0.15) -> list[dict]:
    """Find events in the graph that match the user's description.

    Scoring:
        - Year match: +0.4 (strong signal)
        - Keyword overlap: +0.05 per shared keyword
        - Location match: +0.3 (user mentions the place)
        - Bonus for exact name match: +0.5

    Returns list of {event_label, year, score, match_reasons} sorted by score desc.
    """
    # Extract years from user statement
    years = [int(y) for y in re.findall(r"\b(19\d{2}|20\d{2})\b", user_statement)]

    # Extract keywords from user statement (Chinese + English)
    user_words = set()
    # Chinese: 2-char sequences
    for i in range(len(user_statement) - 1):
        chunk = user_statement[i : i + 2]
        if "\u4e00" <= chunk[0] <= "\u9fff" and "\u4e00" <= chunk[1] <= "\u9fff":
            user_words.add(chunk)
    # English: words > 2 chars
    user_words |= {w.lower() for w in re.findall(r"[a-zA-Z]{3,}", user_statement)}

    # Get candidate events (filter by year if available)
    if years:
        candidates = _get_events_in_years(years)
    else:
        candidates = _get_all_events(limit=200)

    scored = []
    for cand in candidates:
        score = 0.0
        reasons = []

        # Year match
        cand_year = cand.get("year", 0)
        if years and cand_year in years:
            score += 0.4
            reasons.append(f"year match ({cand_year})")
        elif years and any(abs(cand_year - y) <= 2 for y in years):
            score += 0.2
            reasons.append("year near match (±2yrs)")

        # Keyword overlap
        label = cand.get("label", "")
        desc = cand.get("description", "")
        combined = label + " " + (desc or "")
        label_words = set()
        for i in range(len(combined) - 1):
            chunk = combined[i : i + 2]
            if "\u4e00" <= chunk[0] <= "\u9fff" and "\u4e00" <= chunk[1] <= "\u9fff":
                label_words.add(chunk)
        label_words |= {w.lower() for w in re.findall(r"[a-zA-Z]{3,}", combined)}

        overlap = user_words & label_words
        kw_score = len(overlap) * 0.05
        score += kw_score
        if overlap:
            reasons.append(f"{len(overlap)} keywords: {list(overlap)[:3]}")

        # Exact label substring match (e.g., "学杂费" in label)
        for word in user_words:
            if len(word) >= 2 and word in label:
                score += 0.1
                reasons.append(f"substring: {word}")

        # Location match (check if any known place appears in user statement)
        cand_location = cand.get("location", "")
        if cand_location and cand_location in user_statement:
            score += 0.3
            reasons.append(f"location: {cand_location}")

        if score >= min_score:
            scored.append(
                {
                    "event": label,
                    "year": cand_year,
                    "score": round(score, 2),
                    "reasons": reasons,
                }
            )

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored


def _get_events_in_years(years: list[int]) -> list[dict]:
    """Get all events for specific years."""
    driver = Neo4jClient.get_driver()
    all_events = []
    for year in years:
        try:
            with driver.session(database="neo4j") as s:
                result = s.run(
                    "MATCH (ev:Event {time_period: $year}) "
                    "OPTIONAL MATCH (p:Entity {type: 'place'})-[:IN_EVENT]->(ev) "
                    "RETURN ev.label AS label, ev.description AS description, "
                    "ev.time_period AS year, collect(p.name) AS locations "
                    "LIMIT 50",
                    {"year": str(year)},
                )
                for r in result:
                    all_events.append(
                        {
                            "label": r["label"],
                            "description": r.get("description", ""),
                            "year": int(r["year"]) if r["year"].isdigit() else 0,
                            "location": r["locations"][0] if r["locations"] else "",
                        }
                    )
        except Exception:
            pass
    return all_events


def _get_all_events(limit: int = 200) -> list[dict]:
    """Get recent events (fallback when no year is specified)."""
    try:
        result = Neo4jClient.execute(
            "MATCH (ev:Event) RETURN ev.label AS label, ev.description AS description, "
            "ev.time_period AS year ORDER BY ev.order DESC LIMIT $limit",
            {"limit": limit},
        )
        return [
            {
                "label": r["label"],
                "description": r.get("description", ""),
                "year": int(r["year"]) if r["year"].isdigit() else 0,
                "location": "",
            }
            for r in result
        ]
    except Exception:
        return []


def format_match_for_interviewer(matches: list[dict], threshold: float = 0.3) -> str:
    """Format matched events as a gentle confirmation prompt for the interviewer."""
    good_matches = [m for m in matches if m["score"] >= threshold]

    if not good_matches:
        return ""

    if len(good_matches) == 1:
        m = good_matches[0]
        return (
            f"[EVENT MATCH]: User seems to be referring to '{m['event']}' ({m['year']}, "
            f"score={m['score']}). Consider confirming: '您说的是{m['year']}年的{m['event']}这件事吗？'"
        )

    best = good_matches[0]
    others = ", ".join(m["event"] for m in good_matches[1:3])
    return (
        f"[EVENT MATCH]: Multiple candidates. Best: '{best['event']}' ({best['year']}, "
        f"score={best['score']}). Others: {others}. "
        f"Consider: '我猜您说的是{best['year']}年的事？还是{others}？'"
    )
