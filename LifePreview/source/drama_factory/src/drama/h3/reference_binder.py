from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID

from shared_contracts import (
    H3GenerationMode,
    H3SequencePlanV1,
    h3_sequence_compilation_identity,
)


_CANONICAL_VIEWS = ("front", "three_quarter_left", "profile_left")


class H3ReferenceBindingError(ValueError):
    """An H3 plan cannot be bound to its approved physical image assets."""


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


@dataclass(frozen=True, slots=True)
class ApprovedH3Asset:
    asset_id: UUID
    artifact_ref: str
    sha256: str
    media_type: str

    def __post_init__(self) -> None:
        if not self.artifact_ref or self.artifact_ref != self.artifact_ref.strip():
            raise H3ReferenceBindingError("approved H3 asset reference is required")
        if any(ord(character) < 32 for character in self.artifact_ref):
            raise H3ReferenceBindingError("approved H3 asset reference contains control text")
        if not _is_sha256(self.sha256):
            raise H3ReferenceBindingError("approved H3 asset digest is invalid")
        if self.media_type not in {"image", "video", "audio"}:
            raise H3ReferenceBindingError("approved H3 asset media type is invalid")


@dataclass(frozen=True, slots=True)
class H3ReferenceBindingItem:
    token: str
    subject_id: str
    reference_set_id: UUID
    reference_set_revision_id: UUID
    asset_id: UUID
    artifact_ref: str
    sha256: str
    media_type: str
    view_name: str


@dataclass(frozen=True, slots=True)
class H3ReferenceBindingSet:
    sequence_id: UUID
    compilation_identity_digest: str
    reference_set_revision_ids: tuple[UUID, ...]
    items: tuple[H3ReferenceBindingItem, ...]
    digest: str

    @property
    def sequence_digest(self) -> str:
        return self.compilation_identity_digest


def _compilation_digest(plan: H3SequencePlanV1) -> str:
    identity = h3_sequence_compilation_identity(plan)
    return hashlib.sha256(
        json.dumps(
            identity,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _binding_digest(
    *,
    sequence_id: UUID,
    compilation_identity_digest: str,
    reference_set_revision_ids: tuple[UUID, ...],
    items: tuple[H3ReferenceBindingItem, ...],
) -> str:
    payload = {
        "sequence_id": str(sequence_id),
        "compilation_identity_digest": compilation_identity_digest,
        "reference_set_revision_ids": [str(value) for value in reference_set_revision_ids],
        "items": [
            {
                "token": item.token,
                "subject_id": item.subject_id,
                "reference_set_id": str(item.reference_set_id),
                "reference_set_revision_id": str(item.reference_set_revision_id),
                "asset_id": str(item.asset_id),
                "artifact_ref": item.artifact_ref,
                "sha256": item.sha256,
                "media_type": item.media_type,
                "view_name": item.view_name,
            }
            for item in items
        ],
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


def bind_h3_references(
    plan: H3SequencePlanV1,
    approved_assets: Mapping[UUID, ApprovedH3Asset],
) -> H3ReferenceBindingSet:
    if plan.mode is not H3GenerationMode.REF2VA:
        raise H3ReferenceBindingError("MiniMax H3 AMD binding supports Ref2VA only")
    items: list[H3ReferenceBindingItem] = []
    revision_ids: list[UUID] = []
    for authority in plan.reference_bindings:
        reference_set = authority.reference_set
        if reference_set.state != "frozen":
            raise H3ReferenceBindingError("H3 references must come from a frozen set")
        if tuple(view.view_name for view in reference_set.views) != _CANONICAL_VIEWS:
            raise H3ReferenceBindingError("H3 reference views are not in canonical order")
        revision_id = reference_set.reference_set_revision_id
        if revision_id in revision_ids:
            raise H3ReferenceBindingError("H3 reference-set revisions must be unique")
        revision_ids.append(revision_id)
        for view in reference_set.views:
            approved = approved_assets.get(view.asset_id)
            if approved is None or approved.asset_id != view.asset_id:
                raise H3ReferenceBindingError(
                    f"reference view {view.asset_id} is not an approved H3 asset"
                )
            if approved.media_type != "image":
                raise H3ReferenceBindingError("approved H3 reference must be an image")
            if approved.sha256 != view.image_digest:
                raise H3ReferenceBindingError("approved H3 reference digest mismatch")
            ordinal = len(items) + 1
            items.append(
                H3ReferenceBindingItem(
                    token=f"<Picture {ordinal}>",
                    subject_id=authority.subject_id,
                    reference_set_id=reference_set.reference_set_id,
                    reference_set_revision_id=revision_id,
                    asset_id=view.asset_id,
                    artifact_ref=approved.artifact_ref,
                    sha256=approved.sha256,
                    media_type="image",
                    view_name=view.view_name,
                )
            )
    if not 1 <= len(items) <= 9:
        raise H3ReferenceBindingError("H3 Ref2VA requires between one and nine approved images")
    frozen_items = tuple(items)
    frozen_revisions = tuple(revision_ids)
    compilation_digest = _compilation_digest(plan)
    return H3ReferenceBindingSet(
        sequence_id=plan.sequence_id,
        compilation_identity_digest=compilation_digest,
        reference_set_revision_ids=frozen_revisions,
        items=frozen_items,
        digest=_binding_digest(
            sequence_id=plan.sequence_id,
            compilation_identity_digest=compilation_digest,
            reference_set_revision_ids=frozen_revisions,
            items=frozen_items,
        ),
    )


__all__ = [
    "ApprovedH3Asset",
    "H3ReferenceBindingError",
    "H3ReferenceBindingItem",
    "H3ReferenceBindingSet",
    "bind_h3_references",
]
