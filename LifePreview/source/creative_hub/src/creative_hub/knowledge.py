from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from uuid import UUID

from pydantic import ValidationError
from shared_contracts import (
    ApprovedKnowledgeRevision,
    EvidenceConsumer,
    FactoryDocument,
    FactoryDocumentSnapshot,
    FactoryProjectSnapshot,
    FieldLock,
    ImportAction,
    ImportCompatibilityIssue,
    ImportOperation,
    ImportPlan,
    KnowledgeCard,
    KnowledgeMapping,
    KnowledgeMappingPolicy,
    KnowledgePack,
    KnowledgePackTarget,
    KnowledgeReviewDecision,
    KnowledgeRevision,
    KnowledgeRevisionRef,
    RejectedKnowledgeRevision,
    TimelineEvidenceBundle,
    build_import_plan,
    build_knowledge_pack_contract,
    build_knowledge_review,
    build_knowledge_revision,
    canonical_json,
    stable_json_sha256,
)


class KnowledgeEvidenceError(ValueError):
    """The claim cannot be traced to the referenced timeline evidence."""


class KnowledgeRevisionConflict(RuntimeError):
    """An edit was based on a stale card revision."""


class ImportPlanMismatch(ValueError):
    """An ImportPlan was compiled for a different factory snapshot."""


def _validated_revision(
    revision: KnowledgeRevision,
) -> KnowledgeRevision:
    return KnowledgeRevision.model_validate(revision.model_dump(mode="json"))


def create_knowledge_revision(
    *,
    knowledge_id: UUID,
    revision: int,
    card: KnowledgeCard,
    created_by: str,
    created_at: datetime,
    model_version: str | None = None,
    prompt_version: str | None = None,
) -> KnowledgeRevision:
    return build_knowledge_revision(
        knowledge_id=knowledge_id,
        revision=revision,
        card=card,
        created_by=created_by,
        model_version=model_version,
        prompt_version=prompt_version,
        created_at=created_at,
    )


def revise_knowledge_card(
    current: KnowledgeRevision,
    *,
    expected_revision: int,
    card: KnowledgeCard,
    created_by: str,
    created_at: datetime,
) -> KnowledgeRevision:
    current = _validated_revision(current)
    if current.revision != expected_revision:
        raise KnowledgeRevisionConflict(
            f"expected revision {expected_revision}, current revision is "
            f"{current.revision}"
        )
    return build_knowledge_revision(
        knowledge_id=current.knowledge_id,
        revision=current.revision + 1,
        card=card,
        created_by=created_by,
        created_at=created_at,
    )


def _validate_evidence_span(
    revision: KnowledgeRevision,
    bundles: Mapping[UUID, TimelineEvidenceBundle],
) -> None:
    for span in revision.card.evidence_spans:
        bundle = bundles.get(span.bundle_id)
        if bundle is None:
            raise KnowledgeEvidenceError(
                "knowledge evidence bundle is unavailable"
            )
        if EvidenceConsumer.LEARNING not in bundle.consumers:
            raise KnowledgeEvidenceError(
                "knowledge evidence bundle does not support learning"
            )
        if span.end_ms > bundle.duration_ms:
            raise KnowledgeEvidenceError(
                "knowledge evidence span exceeds the source timeline"
            )

        windows = {item.window_id: item for item in bundle.windows}
        frames = {item.frame_id: item for item in bundle.frames}
        transcript = {
            item.segment_id: item for item in bundle.transcript
        }
        for window_id in span.window_ids:
            window = windows.get(window_id)
            if window is None:
                raise KnowledgeEvidenceError(
                    "knowledge evidence window reference is invalid"
                )
            if window.end_ms <= span.start_ms or window.start_ms >= span.end_ms:
                raise KnowledgeEvidenceError(
                    "knowledge evidence window is outside the claimed span"
                )
        for frame_id in span.frame_ids:
            frame = frames.get(frame_id)
            if frame is None:
                raise KnowledgeEvidenceError(
                    "knowledge evidence frame reference is invalid"
                )
            if not span.start_ms <= frame.timestamp_ms <= span.end_ms:
                raise KnowledgeEvidenceError(
                    "knowledge evidence frame is outside the claimed span"
                )
        for segment_id in span.transcript_segment_ids:
            segment = transcript.get(segment_id)
            if segment is None:
                raise KnowledgeEvidenceError(
                    "knowledge evidence transcript reference is invalid"
                )
            if (
                segment.end_ms <= span.start_ms
                or segment.start_ms >= span.end_ms
            ):
                raise KnowledgeEvidenceError(
                    "knowledge evidence transcript is outside the claimed span"
                )


def validate_knowledge_evidence(
    revision: KnowledgeRevision,
    *,
    bundles: Mapping[UUID, TimelineEvidenceBundle],
) -> None:
    if any(bundle_id != bundle.bundle_id for bundle_id, bundle in bundles.items()):
        raise KnowledgeEvidenceError(
            "knowledge evidence bundle identity does not match its lookup key"
        )
    _validate_evidence_span(_validated_revision(revision), bundles)


def approve_knowledge_revision(
    revision: KnowledgeRevision,
    *,
    bundles: Mapping[UUID, TimelineEvidenceBundle],
    reviewed_by: str,
    reviewed_at: datetime,
    reason: str | None = None,
) -> ApprovedKnowledgeRevision:
    try:
        revision = _validated_revision(revision)
    except ValidationError:
        raise KnowledgeEvidenceError(
            "knowledge revision integrity check failed"
        ) from None
    _validate_evidence_span(revision, bundles)
    review = build_knowledge_review(
        revision,
        decision=KnowledgeReviewDecision.APPROVED,
        reviewed_by=reviewed_by,
        reason=reason,
        reviewed_at=reviewed_at,
    )
    return ApprovedKnowledgeRevision(revision=revision, review=review)


def reject_knowledge_revision(
    revision: KnowledgeRevision,
    *,
    reviewed_by: str,
    reason: str,
    reviewed_at: datetime,
) -> RejectedKnowledgeRevision:
    revision = _validated_revision(revision)
    review = build_knowledge_review(
        revision,
        decision=KnowledgeReviewDecision.REJECTED,
        reviewed_by=reviewed_by,
        reason=reason,
        reviewed_at=reviewed_at,
    )
    return RejectedKnowledgeRevision(revision=revision, review=review)


def build_knowledge_pack(
    *,
    approved_revisions: tuple[ApprovedKnowledgeRevision, ...],
    target: KnowledgePackTarget,
    target_schema_version: str,
    required_capabilities: tuple[str, ...],
    mappings: tuple[KnowledgeMapping, ...],
    forbidden_fields: tuple[FieldLock, ...],
    created_by: str,
    created_at: datetime,
) -> KnowledgePack:
    if not approved_revisions:
        raise ValueError("knowledge pack requires an approved revision")
    approved_revisions = tuple(
        ApprovedKnowledgeRevision.model_validate(
            item.model_dump(mode="json")
        )
        for item in approved_revisions
    )
    revisions = tuple(
        KnowledgeRevisionRef(
            knowledge_id=item.revision.knowledge_id,
            revision_id=item.revision.revision_id,
            revision=item.revision.revision,
            revision_sha256=item.revision.revision_sha256,
            approval_id=item.review.review_id,
            approval_sha256=item.review.review_sha256,
        )
        for item in approved_revisions
    )
    return build_knowledge_pack_contract(
        revisions=revisions,
        target=target,
        target_schema_version=target_schema_version,
        required_capabilities=required_capabilities,
        mappings=mappings,
        forbidden_fields=forbidden_fields,
        created_by=created_by,
        created_at=created_at,
    )


def _snapshot_identity(snapshot: FactoryProjectSnapshot) -> dict:
    return {
        "schema_version": snapshot.schema_version,
        "capabilities": sorted(snapshot.capabilities),
        "documents": [
            item.model_dump(mode="json")
            for item in sorted(
                snapshot.documents,
                key=lambda item: item.document.value,
            )
        ],
        "locked_fields": [
            item.model_dump(mode="json")
            for item in sorted(
                snapshot.locked_fields,
                key=lambda item: (item.document.value, item.path),
            )
        ],
    }


def _snapshot_sha256(snapshot: FactoryProjectSnapshot) -> str:
    return stable_json_sha256(_snapshot_identity(snapshot))


def _pointer_parts(path: str) -> tuple[str, ...]:
    return tuple(
        part.replace("~1", "/").replace("~0", "~")
        for part in path[1:].split("/")
    )


def _lookup_pointer(document: object, path: str) -> tuple[bool, object | None]:
    current = document
    for part in _pointer_parts(path):
        if isinstance(current, dict):
            if part not in current:
                return False, None
            current = current[part]
            continue
        if isinstance(current, list):
            if not part.isdigit():
                return False, None
            index = int(part)
            if index >= len(current):
                return False, None
            current = current[index]
            continue
        return False, None
    return True, current


def _parent_exists(document: object, path: str) -> bool:
    parts = _pointer_parts(path)
    if len(parts) == 1:
        return isinstance(document, dict)
    parent_path = "/" + "/".join(
        part.replace("~", "~0").replace("/", "~1")
        for part in parts[:-1]
    )
    exists, parent = _lookup_pointer(document, parent_path)
    return exists and isinstance(parent, (dict, list))


def _set_pointer(document: object, path: str, value: object) -> None:
    parts = _pointer_parts(path)
    current = document
    for part in parts[:-1]:
        if isinstance(current, dict):
            current = current[part]
        elif isinstance(current, list) and part.isdigit():
            current = current[int(part)]
        else:
            raise ImportPlanMismatch("import plan target path is unavailable")
    final = parts[-1]
    if isinstance(current, dict):
        current[final] = value
        return
    if isinstance(current, list) and final.isdigit():
        index = int(final)
        if index == len(current):
            current.append(value)
        elif index < len(current):
            current[index] = value
        else:
            raise ImportPlanMismatch("import plan array target is unavailable")
        return
    raise ImportPlanMismatch("import plan target path is unavailable")


def _paths_overlap(first: str, second: str) -> bool:
    return (
        first == second
        or first.startswith(second + "/")
        or second.startswith(first + "/")
    )


def _field_lock_for(
    snapshot: FactoryProjectSnapshot,
    mapping: KnowledgeMapping,
) -> FieldLock | None:
    return next(
        (
            lock
            for lock in snapshot.locked_fields
            if lock.document is mapping.document
            and _paths_overlap(lock.path, mapping.path)
        ),
        None,
    )


def _preserved_current(
    *,
    exists: bool,
    current_json: str | None,
) -> str | None:
    return current_json if exists else None


class KnowledgePackCompiler:
    """Pure, versioned KnowledgePack-to-ImportPlan compiler."""

    def __init__(self, *, version: str) -> None:
        self.version = version

    def compile(
        self,
        pack: KnowledgePack,
        target: FactoryProjectSnapshot,
    ) -> ImportPlan:
        pack = KnowledgePack.model_validate(pack.model_dump(mode="json"))
        target = FactoryProjectSnapshot.model_validate(
            target.model_dump(mode="json")
        )
        issues: list[ImportCompatibilityIssue] = []
        if pack.target_schema_version != target.schema_version:
            issues.append(
                ImportCompatibilityIssue(
                    code="schema_version_mismatch",
                    message=(
                        f"KnowledgePack requires {pack.target_schema_version}; "
                        f"target provides {target.schema_version}."
                    ),
                    action=(
                        "Upgrade the factory schema or recompile the knowledge "
                        "pack for this target version."
                    ),
                )
            )
        missing_required = sorted(
            set(pack.required_capabilities) - set(target.capabilities)
        )
        if missing_required:
            issues.append(
                ImportCompatibilityIssue(
                    code="missing_required_capability",
                    message=(
                        "Target is missing required capabilities: "
                        + ", ".join(missing_required)
                        + "."
                    ),
                    action=(
                        "Enable the required factory capabilities or choose a "
                        "compatible knowledge pack."
                    ),
                )
            )

        documents = {
            item.document: json.loads(item.content_json)
            for item in target.documents
        }
        operations: list[ImportOperation] = []
        for mapping in pack.mappings:
            document = documents.get(mapping.document)
            exists, current = (
                _lookup_pointer(document, mapping.path)
                if document is not None
                else (False, None)
            )
            current_json = canonical_json(current) if exists else None
            common = {
                "mapping_id": mapping.mapping_id,
                "source_revision_id": mapping.source_revision_id,
                "document": mapping.document,
                "path": mapping.path,
                "current_exists": exists,
                "current_json": current_json,
                "incoming_json": mapping.incoming_json,
            }

            if issues:
                operations.append(
                    ImportOperation(
                        **common,
                        action=ImportAction.DISABLED,
                        resolved_json=_preserved_current(
                            exists=exists,
                            current_json=current_json,
                        ),
                        reason="Import is disabled because the target is incompatible.",
                    )
                )
                continue
            if not mapping.enabled:
                operations.append(
                    ImportOperation(
                        **common,
                        action=ImportAction.DISABLED,
                        resolved_json=_preserved_current(
                            exists=exists,
                            current_json=current_json,
                        ),
                        reason=mapping.disabled_reason,
                    )
                )
                continue
            missing_mapping_capabilities = sorted(
                set(mapping.required_capabilities) - set(target.capabilities)
            )
            if missing_mapping_capabilities:
                operations.append(
                    ImportOperation(
                        **common,
                        action=ImportAction.DISABLED,
                        resolved_json=_preserved_current(
                            exists=exists,
                            current_json=current_json,
                        ),
                        reason=(
                            "Mapping is disabled because capabilities are "
                            "unavailable: "
                            + ", ".join(missing_mapping_capabilities)
                            + "."
                        ),
                    )
                )
                continue
            if exists and current_json == mapping.incoming_json:
                operations.append(
                    ImportOperation(
                        **common,
                        action=ImportAction.UNCHANGED,
                        resolved_json=current_json,
                        reason="Target already contains the mapped value.",
                    )
                )
                continue

            lock = _field_lock_for(target, mapping)
            if lock is not None:
                operations.append(
                    ImportOperation(
                        **common,
                        action=ImportAction.LOCKED,
                        resolved_json=_preserved_current(
                            exists=exists,
                            current_json=current_json,
                        ),
                        reason=lock.reason,
                        requires_resolution=True,
                    )
                )
                continue
            if document is None or not _parent_exists(document, mapping.path):
                operations.append(
                    ImportOperation(
                        **common,
                        action=ImportAction.CONFLICT,
                        reason=(
                            "Target document or parent path does not exist; "
                            "human mapping is required."
                        ),
                        requires_resolution=True,
                    )
                )
                continue
            if not exists:
                operations.append(
                    ImportOperation(
                        **common,
                        action=ImportAction.ADD,
                        resolved_json=mapping.incoming_json,
                        reason="Target field is absent and can be added.",
                    )
                )
                continue
            if mapping.policy is KnowledgeMappingPolicy.REPLACE:
                operations.append(
                    ImportOperation(
                        **common,
                        action=ImportAction.REPLACE,
                        resolved_json=mapping.incoming_json,
                        reason="Mapping explicitly allows replacement.",
                    )
                )
                continue
            operations.append(
                ImportOperation(
                    **common,
                    action=ImportAction.CONFLICT,
                    reason=(
                        "Target and KnowledgePack values differ; human "
                        "resolution is required."
                    ),
                    requires_resolution=True,
                )
            )

        locks_by_target = {
            (item.document, item.path): item for item in target.locked_fields
        }
        for item in pack.forbidden_fields:
            locks_by_target.setdefault((item.document, item.path), item)
        return build_import_plan(
            pack=pack,
            compiler_version=self.version,
            target_snapshot_sha256=_snapshot_sha256(target),
            compatibility_issues=tuple(issues),
            operations=tuple(operations),
            resulting_locks=tuple(locks_by_target.values()),
        )


def preview_import_plan(
    target: FactoryProjectSnapshot,
    plan: ImportPlan,
) -> FactoryProjectSnapshot:
    """Apply only unambiguous operations to a disposable target preview."""

    target = FactoryProjectSnapshot.model_validate(
        target.model_dump(mode="json")
    )
    plan = ImportPlan.model_validate(plan.model_dump(mode="json"))
    if _snapshot_sha256(target) != plan.target_snapshot_sha256:
        raise ImportPlanMismatch(
            "import plan was compiled for a different target snapshot"
        )
    documents = {
        item.document: json.loads(item.content_json)
        for item in target.documents
    }
    for operation in plan.operations:
        if operation.action not in {ImportAction.ADD, ImportAction.REPLACE}:
            continue
        if operation.resolved_json is None:
            raise ImportPlanMismatch(
                "applicable import operation has no resolved value"
            )
        document = documents.get(operation.document)
        if document is None:
            raise ImportPlanMismatch("import plan target document is unavailable")
        _set_pointer(
            document,
            operation.path,
            json.loads(operation.resolved_json),
        )
    return FactoryProjectSnapshot(
        schema_version=target.schema_version,
        capabilities=target.capabilities,
        documents=tuple(
            FactoryDocumentSnapshot(
                document=document,
                content_json=canonical_json(content),
            )
            for document, content in sorted(
                documents.items(),
                key=lambda item: item[0].value,
            )
        ),
        locked_fields=plan.resulting_locks,
    )
