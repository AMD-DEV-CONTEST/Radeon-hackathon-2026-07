from __future__ import annotations

from collections.abc import Callable

from .contracts import AudiencePulse, CreativeBrief


VALID_EMOTIONS = {"sadness", "joy", "love", "anger", "fear", "surprise"}


class GemmaAudiencePulse:
    """Adapter around the Notebook's `predict_emotion_ft` callable."""

    def __init__(
        self,
        classifier: Callable[[str], str],
        model_ref: str = "google/gemma-4-E4B-it+emotion-lora",
    ) -> None:
        self.classifier = classifier
        self.model_ref = model_ref

    def review(self, brief: CreativeBrief) -> AudiencePulse:
        prediction = self.classifier(brief.headline).strip().lower()
        valid = prediction in VALID_EMOTIONS
        return AudiencePulse(
            target_emotion=brief.target_emotion,
            predicted_emotion=prediction if valid else "invalid",
            confidence=1.0 if valid else 0.0,
            matched=valid and prediction == brief.target_emotion,
            model_ref=self.model_ref,
            limitations=(
                "Six coarse English labels do not measure persuasion.",
                "Output must not be used for psychological diagnosis.",
                "Cultural fit requires human and market-specific review.",
            ),
        )


class LexicalAudiencePulse:
    """Deterministic offline fallback; clearly separated from the Gemma model."""

    def review(self, brief: CreativeBrief) -> AudiencePulse:
        normalized = brief.headline.lower()
        cues = {
            "joy": ("joy", "bright", "delight", "launch"),
            "love": ("love", "care", "together"),
            "surprise": ("surprise", "unexpected", "discover"),
            "fear": ("fear", "risk", "protect"),
            "anger": ("anger", "frustration", "fight"),
            "sadness": ("sad", "loss", "miss"),
        }
        scores = {
            label: sum(token in normalized for token in tokens)
            for label, tokens in cues.items()
        }
        predicted = max(scores, key=scores.get) if max(scores.values()) > 0 else "invalid"
        return AudiencePulse(
            target_emotion=brief.target_emotion,
            predicted_emotion=predicted,
            confidence=0.51 if predicted != "invalid" else 0.0,
            matched=predicted == brief.target_emotion,
            model_ref="prooflaunch/lexical-pulse-v1",
            limitations=(
                "Deterministic lexical fallback; not an AI audience model.",
                "Does not measure persuasion or human response.",
                "Use the GemmaAudiencePulse adapter for the Radeon Notebook path.",
            ),
        )


class RecordedAudiencePulse:
    """Replays a signed-off model result after the heavy model is unloaded."""

    def __init__(self, pulse: AudiencePulse) -> None:
        self.pulse = pulse

    def review(self, brief: CreativeBrief) -> AudiencePulse:
        if brief.target_emotion != self.pulse.target_emotion:
            return AudiencePulse(
                target_emotion=brief.target_emotion,
                predicted_emotion=self.pulse.predicted_emotion,
                confidence=0.0,
                matched=False,
                model_ref=self.pulse.model_ref,
                limitations=(
                    *self.pulse.limitations,
                    "Recorded pulse target did not match the requested brief.",
                ),
            )
        return self.pulse
