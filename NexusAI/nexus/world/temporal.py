from .blueprint_models import BlueprintValue, TimeOfDay
from .context import ContextEvidence


TEMPORAL_TOKEN_HINTS = {
    TimeOfDay.DAWN: {
        "dawn": 3,
        "sunrise": 3,
        "morning": 2,
    },
    TimeOfDay.DAY: {
        "day": 3,
        "daytime": 3,
        "noon": 3,
        "afternoon": 2,
        "daylight": 2,
    },
    TimeOfDay.DUSK: {
        "dusk": 3,
        "sunset": 3,
        "evening": 2,
        "twilight": 3,
    },
    TimeOfDay.NIGHT: {
        "night": 3,
        "nighttime": 3,
        "midnight": 3,
        "moon": 2,
        "moonlight": 3,
        "stars": 2,
        "starlight": 3,
    },
}


TEMPORAL_PHRASE_HINTS = {
    TimeOfDay.DAWN: {
        "early morning": 4,
        "first light": 5,
        "rising sun": 5,
        "break of dawn": 5,
    },
    TimeOfDay.DAY: {
        "late afternoon": 3,
        "broad daylight": 5,
        "midday sun": 5,
    },
    TimeOfDay.DUSK: {
        "golden hour": 4,
        "setting sun": 5,
        "last light": 5,
        "orange horizon": 4,
        "evening sky": 4,
    },
    TimeOfDay.NIGHT: {
        "night sky": 5,
        "starry night": 5,
        "after dark": 5,
        "dark sky": 4,
        "under the stars": 5,
        "under moonlight": 5,
    },
}


def infer_time_of_day(context: ContextEvidence) -> BlueprintValue:
    best_time = TimeOfDay.DAY
    best_score = 0
    best_evidence: list[str] = []

    for time_of_day in TimeOfDay:
        score = 0
        evidence: list[str] = []

        for token, weight in TEMPORAL_TOKEN_HINTS.get(time_of_day, {}).items():
            if token in context.tokens:
                score += weight
                evidence.append(token)

        for phrase, weight in TEMPORAL_PHRASE_HINTS.get(time_of_day, {}).items():
            if phrase in context.text:
                score += weight
                evidence.append(phrase)

        if score > best_score:
            best_time = time_of_day
            best_score = score
            best_evidence = evidence

    if best_score == 0:
        return BlueprintValue(
            value=TimeOfDay.DAY.value,
            confidence=0.35,
            evidence=[],
        )

    return BlueprintValue(
        value=best_time.value,
        confidence=min(0.98, 0.55 + best_score * 0.05),
        evidence=sorted(set(best_evidence)),
    )