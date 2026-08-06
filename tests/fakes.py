"""Explicit test doubles. These are never selected by production configuration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class FakeModelClient:
    async def health(self) -> bool:
        return True

    async def chat(
        self, messages: list[dict[str, Any]], *, temperature: float = 0.2, max_tokens: int = 1200
    ) -> str:
        system = str(messages[0]["content"])
        if "CandidateComparison" in system:
            context = json.loads(str(messages[1]["content"]))
            image_ids = context["image_ids"]
            return json.dumps(
                {
                    "recommended_image_id": image_ids[0],
                    "candidates": [
                        {
                            "image_id": image_id,
                            "crop_resilience": 4,
                            "small_size_clarity": 4,
                            "privacy_safety": 5,
                            "intent_alignment": 4,
                            "contextual_ambiguity": 1,
                            "rationale": "The candidate is suitable for the supplied test goals.",
                        }
                        for image_id in image_ids
                    ],
                    "decision_rule": "Privacy overrides the aggregate score.",
                    "caveat": "This is a deterministic test response.",
                }
            )
        if "Extract one reusable fact" in system:
            return json.dumps(
                {
                    "text": "Red is an intentional brand color.",
                    "memory_type": "correction",
                    "reason": "The user stated this reusable correction explicitly.",
                }
            )
        if "StructuredReportDraft" in system:
            raw_context = str(messages[1]["content"]).split("\n", 1)[1]
            context = json.loads(raw_context)
            return json.dumps(
                {
                    "summary": "The image was reviewed against the supplied goals.",
                    "observed": ["A primary subject is visible."],
                    "privacy": ["Review all local privacy findings before sharing."],
                    "context": ["The assessment is relative to the selected platform."],
                    "recommendations": ["Use the clearest safe crop."],
                    "limitations": ["No identity or sensitive trait was inferred."],
                    "cited_card_ids": [card["card_id"] for card in context["evidence"][:2]],
                }
            )
        if "FollowUpDraft" in system:
            context = json.loads(str(messages[1]["content"]))
            evidence = context["cached_evidence"]
            return json.dumps(
                {
                    "answer": "Candidate A remains safer for the stated audience.",
                    "supporting_points": [
                        "The answer reuses the completed comparison and privacy findings."
                    ],
                    "cited_card_ids": [card["card_id"] for card in evidence[:1]],
                    "limitations": ["The images were not visually re-inspected."],
                }
            )
        return json.dumps({"error": "unexpected fake-model prompt"})

    async def inspect_image(self, path: Path, prompt: str) -> dict[str, Any]:
        if "private Lens Tool" in prompt:
            return {
                "observed_motifs": ["A centered subject with a bright background."],
                "symbolic_associations": [
                    "Within the private course framework, strong backlight can reduce "
                    "visual grounding."
                ],
                "technique_references": ["Technique #28"],
                "uncertainties": ["The background boundary is partly ambiguous."],
            }
        return {
            "visible_elements": ["one primary visual subject"],
            "composition": "centered",
            "text_candidates": [],
            "privacy_candidates": [],
            "rights_candidates": [],
            "uncertainties": ["test double; no model inference"],
        }
