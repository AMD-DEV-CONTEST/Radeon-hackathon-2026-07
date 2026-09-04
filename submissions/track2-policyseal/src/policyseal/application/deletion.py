from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from policyseal.audit.chain import AuditChain
from policyseal.audit.models import AuditEventType
from policyseal.domain.models import DeletionTombstone
from policyseal.policy.schema import PolicyPack
from policyseal.security.fingerprints import KeyedFingerprinter
from policyseal.storage.file_store import ControlledFileStore, FileNamespace
from policyseal.storage.repositories import PolicySealRepository


def _utc_now() -> datetime:
    return datetime.now(UTC)


class DeletionService:
    def __init__(
        self,
        repository: PolicySealRepository,
        file_store: ControlledFileStore,
        fingerprinter: KeyedFingerprinter,
        policy_pack: PolicyPack,
        audit_chain: AuditChain,
        *,
        clock: Callable[[], datetime] = _utc_now,
        delete_task_state: Callable[[str], None] | None = None,
    ) -> None:
        self.repository = repository
        self.file_store = file_store
        self.fingerprinter = fingerprinter
        self.policy_pack = policy_pack
        self.audit_chain = audit_chain
        self._clock = clock
        self._delete_task_state = delete_task_state

    def delete(self, task_id: str, *, actor: str) -> DeletionTombstone:
        task = self.repository.get_task(task_id)
        revisions = self.repository.list_revisions(task_id)
        artifacts = self.repository.list_artifacts(task_id)
        actor_hmac = self.fingerprinter.digest("deletion-actor", actor, scope=task_id)
        deletion_fingerprint = self.fingerprinter.digest(
            "deletion",
            f"{task.id}:{task.source.sha256}:{len(revisions)}",
            scope=task_id,
        )
        tombstone = DeletionTombstone(
            id=f"tombstone-{uuid.uuid4().hex}",
            task_id=task.id,
            revision_count=len(revisions),
            source_sha256=task.source.sha256,
            deletion_fingerprint=deletion_fingerprint,
            actor_hmac=actor_hmac,
            policy_version=(
                revisions[-1].context.policy_version
                if revisions
                else self.policy_pack.definition.version
            ),
            deleted_at=self._clock().astimezone(UTC),
        )
        if self._delete_task_state is not None:
            self._delete_task_state(task_id)
        self.file_store.delete(FileNamespace.SOURCES, task.source_storage_id)
        for revision in revisions:
            if revision.output_storage_id is not None:
                self.file_store.delete(FileNamespace.OUTPUTS, revision.output_storage_id)
        for artifact in artifacts:
            self.file_store.delete(FileNamespace(artifact.namespace), artifact.storage_id)
        self.repository.delete_task_with_tombstone(tombstone)
        event = self.audit_chain.append(
            AuditEventType.TASK_DELETED,
            {
                "task_id": task.id,
                "revision_count": len(revisions),
                "source_sha256": task.source.sha256,
                "deletion_fingerprint": deletion_fingerprint,
                "status": "deleted",
            },
            actor=f"actor-{actor_hmac[:16]}",
            task_id=task.id,
            policy_sha256=self.policy_pack.sha256,
        )
        self.repository.append_audit_event(event)
        return tombstone
