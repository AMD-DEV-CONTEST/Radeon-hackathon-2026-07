from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from uuid import UUID

from shared_contracts import H3SequencePlanV1

from .model_registry import H3CapabilityRevision
from .reference_binder import H3ReferenceBindingSet
from .validator import validate_h3_sequence_for_render


class H3PromptRenderError(ValueError):
    """An authority-bound H3 prompt cannot be rendered safely."""


@dataclass(frozen=True, slots=True)
class H3RenderedPrompt:
    sequence_id: UUID
    compilation_identity_digest: str
    binding_digest: str
    capability_digest: str
    reference_set_revision_ids: tuple[UUID, ...]
    prompt: str
    prompt_digest: str

    @property
    def sequence_digest(self) -> str:
        return self.compilation_identity_digest


def _rendered_prompt_digest(
    *,
    sequence_id: UUID,
    compilation_identity_digest: str,
    binding_digest: str,
    capability_digest: str,
    reference_set_revision_ids: tuple[UUID, ...],
    prompt: str,
) -> str:
    payload = {
        "schema_version": "h3-ref2va-rendered-prompt.v1",
        "sequence_id": str(sequence_id),
        "compilation_identity_digest": compilation_identity_digest,
        "binding_digest": binding_digest,
        "capability_digest": capability_digest,
        "reference_set_revision_ids": [str(value) for value in reference_set_revision_ids],
        "prompt": prompt,
    }
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


class H3PromptRenderer:
    def render(
        self,
        plan: H3SequencePlanV1,
        binding: H3ReferenceBindingSet,
        capability: H3CapabilityRevision,
    ) -> H3RenderedPrompt:
        try:
            validate_h3_sequence_for_render(plan, binding, capability)
        except ValueError as exc:
            raise H3PromptRenderError(str(exc)) from exc

        lines = [
            "integrated_multimodal_description:",
            f"Mode: MiniMax H3 Ref2VA; sequence {plan.sequence_id}; 16:9 landscape.",
            "Identity references (use only for subject identity, age, hair, face, and attire):",
        ]
        lines.extend(
            (
                f"- {item.token}: subject {item.subject_id}; {item.view_name} view; "
                f"reference set revision {item.reference_set_revision_id}."
            )
            for item in binding.items
        )
        lines.append("Shots:")
        lines.extend(
            (
                f"- [Shot {shot.shot_ordinal}; {shot.start_seconds:g}s-{shot.end_seconds:g}s] "
                f"framing={shot.framing}; camera={shot.camera_move}; "
                f"subjects={', '.join(shot.subject_ids)}; action={shot.action}; "
                f"expression={shot.expression}."
            )
            for shot in plan.shots
        )
        audio = plan.audio_plan
        narration = audio.narration
        lines.extend(
            (
                "H3 native audio plan:",
                f"- Base ambience: {audio.base_ambience}.",
                (
                    f"- Native narration [{narration.start_seconds:g}s-"
                    f"{narration.end_seconds:g}s]: <d>[Chinese] {narration.text}</d>"
                ),
            )
        )
        if audio.action_sounds:
            lines.append("- Action-sound overlays:")
            lines.extend(
                f"  - [{sound.start_seconds:g}s-{sound.end_seconds:g}s] {sound.label}."
                for sound in audio.action_sounds
            )
        else:
            lines.append("- Action-sound overlays: none.")
        if audio.internal_cut_times:
            lines.append(
                "- Internal cuts: "
                + ", ".join(f"{value:g}s" for value in audio.internal_cut_times)
                + "."
            )
        lines.extend(
            (
                (
                    f"- Tail guard: final {audio.tail_guard_seconds:g}s is ambience only; "
                    "no new narration or important action sound."
                ),
                "Delivery constraints: use H3 native synchronized audio only; no external TTS; "
                "no subtitles, captions, visible labels, logos, or watermarks.",
            )
        )
        prompt = "\n".join(lines)
        digest = _rendered_prompt_digest(
            sequence_id=plan.sequence_id,
            compilation_identity_digest=binding.compilation_identity_digest,
            binding_digest=binding.digest,
            capability_digest=capability.digest,
            reference_set_revision_ids=binding.reference_set_revision_ids,
            prompt=prompt,
        )
        return H3RenderedPrompt(
            sequence_id=plan.sequence_id,
            compilation_identity_digest=binding.compilation_identity_digest,
            binding_digest=binding.digest,
            capability_digest=capability.digest,
            reference_set_revision_ids=binding.reference_set_revision_ids,
            prompt=prompt,
            prompt_digest=digest,
        )


__all__ = ["H3PromptRenderError", "H3PromptRenderer", "H3RenderedPrompt"]
