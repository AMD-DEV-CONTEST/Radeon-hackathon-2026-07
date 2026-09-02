from __future__ import annotations

import json
import re

from shared_contracts import (
    H3GenerationMode,
    H3SequencePlanV1,
    validate_h3_audio_safety,
)

from .model_registry import H3CapabilityRevision
from .reference_binder import (
    H3ReferenceBindingSet,
    _binding_digest,
    _compilation_digest,
)


class H3SequenceValidationError(ValueError):
    """A plan, binding, and capability do not share one H3 render authority."""


_RESERVED_TOKEN = re.compile(r"<(?:Picture|Video|Audio)\s+\d+>", re.IGNORECASE)
_PHYSICAL_AUTHORITY = re.compile(
    r"(?:\b[A-Za-z][A-Za-z0-9+.-]*://|[A-Za-z]:[\\/]|\\\\|"
    r"(?<![:A-Za-z0-9_.-])/(?:[A-Za-z0-9._~-]+(?:/[A-Za-z0-9._~-]+)*)|"
    r"(?:^|[\s\"'(\\/])\.\.(?:[\\/]|$)|\.safetensors\b|\bcomfyui\b)",
    re.IGNORECASE,
)


def validate_h3_sequence_for_render(
    plan: H3SequencePlanV1,
    binding: H3ReferenceBindingSet,
    capability: H3CapabilityRevision,
) -> None:
    try:
        capability.assert_exact_truth()
    except ValueError as exc:
        raise H3SequenceValidationError(str(exc)) from exc
    if not capability.available:
        raise H3SequenceValidationError("MiniMax H3 capability is unavailable")
    if (
        capability.family != "minimax-h3"
        or capability.revision != "h3-amd-local-v1"
        or capability.supported_modes != (H3GenerationMode.REF2VA,)
    ):
        raise H3SequenceValidationError("capability is not the pinned H3 AMD Ref2VA profile")
    if plan.mode is not H3GenerationMode.REF2VA:
        raise H3SequenceValidationError("MiniMax H3 AMD supports Ref2VA only")
    compilation_digest = _compilation_digest(plan)
    if (
        binding.sequence_id != plan.sequence_id
        or binding.compilation_identity_digest != compilation_digest
    ):
        raise H3SequenceValidationError("reference binding targets another compilation identity")
    expected_revisions = tuple(
        authority.reference_set.reference_set_revision_id
        for authority in plan.reference_bindings
    )
    if binding.reference_set_revision_ids != expected_revisions:
        raise H3SequenceValidationError("reference revisions do not match the plan authority")
    expected_items = tuple(
        (
            authority.subject_id,
            authority.reference_set.reference_set_id,
            authority.reference_set.reference_set_revision_id,
            view.asset_id,
            view.image_digest,
            view.view_name,
        )
        for authority in plan.reference_bindings
        for view in authority.reference_set.views
    )
    actual_items = tuple(
        (
            item.subject_id,
            item.reference_set_id,
            item.reference_set_revision_id,
            item.asset_id,
            item.sha256,
            item.view_name,
        )
        for item in binding.items
    )
    if actual_items != expected_items:
        raise H3SequenceValidationError("physical bindings do not match embedded reference views")
    expected_digest = _binding_digest(
        sequence_id=binding.sequence_id,
        compilation_identity_digest=binding.compilation_identity_digest,
        reference_set_revision_ids=binding.reference_set_revision_ids,
        items=binding.items,
    )
    if binding.digest != expected_digest:
        raise H3SequenceValidationError("reference binding digest does not match its payload")
    if not 1 <= len(binding.items) <= capability.max_reference_images:
        raise H3SequenceValidationError("Ref2VA binding exceeds the capability image limit")
    expected_tokens = tuple(
        f"<Picture {index}>" for index in range(1, len(binding.items) + 1)
    )
    if tuple(item.token for item in binding.items) != expected_tokens:
        raise H3SequenceValidationError("physical Picture tokens are not contiguous")
    if any(item.media_type != "image" for item in binding.items):
        raise H3SequenceValidationError("Ref2VA physical bindings must all be images")
    source_text = json.dumps(
        plan.model_dump(mode="json"),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
    )
    if _RESERVED_TOKEN.search(source_text):
        raise H3SequenceValidationError("H3 plan contains reserved physical token markup")
    if _PHYSICAL_AUTHORITY.search(source_text):
        raise H3SequenceValidationError(
            "H3 plan contains a forbidden physical path or runtime authority"
        )
    try:
        validate_h3_audio_safety(
            plan.audio_plan,
            sequence_duration_seconds=plan.duration_seconds,
        )
    except ValueError as exc:
        raise H3SequenceValidationError(f"H3 native audio safety failed: {exc}") from exc


__all__ = ["H3SequenceValidationError", "validate_h3_sequence_for_render"]
