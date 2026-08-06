"""Intent routing inherited from the original Aperture product."""

from __future__ import annotations

from typing import Any


class IntentRouter:
    EDIT_TERMS = (
        "edit",
        "retouch",
        "crop",
        "replace sky",
        "color grade",
        "color correction",
        "colour correction",
        "fix exposure",
        "white balance",
        "exposure correction",
    )
    SHOOT_TERMS = (
        "shoot",
        "reshoot",
        "camera",
        "pose",
        "photograph",
    )

    def route(self, user_request: str) -> dict[str, Any]:
        text = user_request.strip().lower()
        if not text:
            text = "shoot"
        edit_hits = [term for term in self.EDIT_TERMS if term in text]
        shoot_hits = [term for term in self.SHOOT_TERMS if term in text]
        if edit_hits and shoot_hits:
            task_type = "hybrid"
            reason = (
                "The request combines on-location capture decisions with "
                "conservative post-processing."
            )
            matched_terms = edit_hits + shoot_hits
        elif edit_hits:
            task_type = "photo_edit"
            reason = "The request can be satisfied with post-processing."
            matched_terms = edit_hits
        else:
            task_type = "shooting"
            reason = "The request needs an executable on-location photography plan."
            matched_terms = shoot_hits
        return {
            "task_type": task_type,
            "reason": reason,
            "matched_terms": matched_terms,
            "privacy": "Local AMD Radeon GPU inference; no external AI API.",
            "preserve_constraints": [
                "Preserve subject identity.",
                "Preserve the real location and scene semantics.",
                "Avoid synthetic studio backgrounds and excessive filtering.",
            ],
        }
