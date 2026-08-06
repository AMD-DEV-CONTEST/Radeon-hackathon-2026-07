from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

import numpy as np

RecognitionLanguage = Literal["zh", "en"]


@dataclass(frozen=True)
class LanguageCandidateScores:
    selected_language: RecognitionLanguage
    eligible_indices: tuple[int, ...]
    ranked_indices: tuple[int, ...]
    probabilities: Mapping[int, float]


def validate_recognition_language(value: object) -> RecognitionLanguage:
    if not isinstance(value, str) or value not in {"zh", "en"}:
        raise ValueError("recognition language must be 'zh' or 'en'")
    return value


def score_language_candidates(
    logits, phrase_languages: Sequence[str], language: object
) -> LanguageCandidateScores:
    selected_language = validate_recognition_language(language)
    values = np.asarray(logits, dtype=np.float64)
    if values.ndim != 1:
        raise ValueError("logits must be one-dimensional")
    if values.shape[0] != len(phrase_languages):
        raise ValueError("logits and phrase_languages must have matching lengths")

    eligible_indices = tuple(
        index
        for index, phrase_language in enumerate(phrase_languages)
        if phrase_language == selected_language
    )
    if not eligible_indices:
        raise ValueError(f"no candidates are available for language {selected_language!r}")

    eligible_logits = values[list(eligible_indices)]
    if not np.all(np.isfinite(eligible_logits)):
        raise ValueError("eligible logits must be finite")
    shifted = eligible_logits - np.max(eligible_logits)
    unnormalized = np.exp(shifted)
    probabilities = unnormalized / np.sum(unnormalized)
    if not np.all(np.isfinite(probabilities)):
        raise ValueError("language candidate probabilities must be finite")

    ranked_positions = np.argsort(-probabilities, kind="stable")
    ranked_indices = tuple(eligible_indices[int(position)] for position in ranked_positions)
    probability_by_index = MappingProxyType(
        {
            eligible_indices[index]: float(probability)
            for index, probability in enumerate(probabilities)
        }
    )
    return LanguageCandidateScores(
        selected_language=selected_language,
        eligible_indices=eligible_indices,
        ranked_indices=ranked_indices,
        probabilities=probability_by_index,
    )
