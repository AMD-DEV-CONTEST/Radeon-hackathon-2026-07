from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime, timedelta
from io import BytesIO
from uuid import uuid4

import pytest
from shared_contracts import RetentionClass

from creative_hub.artifact_publication import (
    ArtifactPublicationService,
    ArtifactStatus,
    ArtifactUnavailable,
    ContentAddressedArtifactStore,
    InMemoryArtifactRepository,
    PublicationCrash,
    StaleArtifactAttempt,
)


PNG = b"\x89PNG\r\n\x1a\n" + b"verified artifact bytes"


def _service(tmp_path, *, boundary: str | None = None):
    repository = InMemoryArtifactRepository()
    raised = False

    def crash_hook(name, _value):
        nonlocal raised
        if name == boundary and not raised:
            raised = True
            raise PublicationCrash(name)

    service = ArtifactPublicationService(
        repository=repository,
        store=ContentAddressedArtifactStore(tmp_path),
        crash_hook=crash_hook,
    )
    return repository, service


def _publish(service, *, project_id=None, key="output", payload=PNG):
    project_id = project_id or uuid4()
    run_id = uuid4()
    attempt_id = uuid4()
    record = service.publish(
        project_id=project_id,
        operation_run_id=run_id,
        attempt_id=attempt_id,
        attempt_number=1,
        fencing_token=7,
        publication_key=key,
        stream=BytesIO(payload),
        mime_type="image/png",
        logical_role="generated.image",
        retention_class=RetentionClass.EPHEMERAL,
        retain_until=datetime.now(UTC) - timedelta(seconds=1),
    )
    return project_id, run_id, attempt_id, record


@pytest.mark.parametrize(
    "boundary",
    ["after_register_pending", "after_promote", "after_commit"],
)
def test_finalize_recovers_every_durable_crash_boundary(tmp_path, boundary):
    repository, service = _service(tmp_path, boundary=boundary)
    project_id = uuid4()
    run_id = uuid4()
    attempt_id = uuid4()

    with pytest.raises(PublicationCrash, match=boundary):
        service.publish(
            project_id=project_id,
            operation_run_id=run_id,
            attempt_id=attempt_id,
            attempt_number=1,
            fencing_token=3,
            publication_key="scene-1",
            stream=BytesIO(PNG),
            mime_type="image/png",
            logical_role="scene.image",
            retention_class=RetentionClass.WORKFLOW,
        )

    claim = repository.begin_claim(
        project_id=project_id,
        operation_run_id=run_id,
        attempt_id=attempt_id,
        attempt_number=1,
        fencing_token=3,
        publication_key="scene-1",
        now=datetime.now(UTC),
    )
    if boundary == "after_commit":
        recovered = service.finalize(
            project_id=project_id,
            staging_token=claim.staging_token,
        )
    else:
        recovered = service.recover_pending(project_id=project_id)[0]
    replay = service.finalize(
        project_id=project_id,
        staging_token=claim.staging_token,
    )

    assert recovered == replay
    assert recovered.status is ArtifactStatus.COMMITTED
    assert service.store.object_path(recovered.content_digest).read_bytes() == PNG


def test_crash_after_staging_is_cleaned_as_orphan(tmp_path):
    repository, service = _service(tmp_path, boundary="after_stage")
    now = datetime(2026, 7, 30, tzinfo=UTC)
    service.clock = lambda: now
    project_id = uuid4()
    with pytest.raises(PublicationCrash, match="after_stage"):
        service.publish(
            project_id=project_id,
            operation_run_id=uuid4(),
            attempt_id=uuid4(),
            attempt_number=1,
            fencing_token=1,
            publication_key="orphan",
            stream=BytesIO(PNG),
            mime_type="image/png",
            logical_role="image",
            retention_class=RetentionClass.EPHEMERAL,
        )
    staged = next(service.store.staging_root.glob("*.part"))
    old = (now - timedelta(hours=2)).timestamp()
    os.utime(staged, (old, old))
    service.clock = lambda: now + timedelta(hours=2)

    deleted = service.cleanup_orphan_staging(older_than=timedelta(hours=1))

    assert len(deleted) == 1
    assert not staged.exists()
    assert repository.list_pending(project_id=project_id) == ()


def test_pending_is_invisible_and_tokens_are_project_scoped(tmp_path):
    repository, service = _service(tmp_path)
    project_id = uuid4()
    claim = service.begin(
        project_id=project_id,
        operation_run_id=uuid4(),
        attempt_id=uuid4(),
        attempt_number=1,
        fencing_token=1,
        publication_key="private",
    )
    staged = service.stage(
        claim=claim,
        stream=BytesIO(PNG),
        mime_type="image/png",
    )
    pending = service.register(
        claim=claim,
        staged=staged,
        logical_role="image",
        retention_class=RetentionClass.WORKFLOW,
    )

    with pytest.raises(ArtifactUnavailable):
        repository.get_visible(
            project_id=project_id,
            artifact_id=pending.artifact_id,
        )
    with pytest.raises(ArtifactUnavailable):
        service.adopt(
            project_id=uuid4(),
            staging_token=claim.staging_token,
        )
    assert repository.find_visible_by_digest(
        project_id=uuid4(),
        content_digest=pending.content_digest,
    ) == ()


def test_newer_fence_prevents_stale_attempt_registration(tmp_path):
    _repository, service = _service(tmp_path)
    project_id = uuid4()
    run_id = uuid4()
    stale = service.begin(
        project_id=project_id,
        operation_run_id=run_id,
        attempt_id=uuid4(),
        attempt_number=1,
        fencing_token=10,
        publication_key="attempt-1",
    )
    staged = service.stage(
        claim=stale,
        stream=BytesIO(PNG),
        mime_type="image/png",
    )
    service.begin(
        project_id=project_id,
        operation_run_id=run_id,
        attempt_id=uuid4(),
        attempt_number=2,
        fencing_token=11,
        # A logical output key is reusable by a newer attempt; idempotency is
        # scoped to the attempt, while fencing makes the old writer stale.
        publication_key="attempt-1",
    )

    with pytest.raises(StaleArtifactAttempt):
        service.register(
            claim=stale,
            staged=staged,
            logical_role="image",
            retention_class=RetentionClass.WORKFLOW,
        )


def test_streaming_digest_size_and_media_are_verified(tmp_path):
    _repository, service = _service(tmp_path)
    digest = hashlib.sha256(PNG).hexdigest()
    claim = service.begin(
        project_id=uuid4(),
        operation_run_id=uuid4(),
        attempt_id=uuid4(),
        attempt_number=1,
        fencing_token=0,
        publication_key="streamed",
    )
    staged = service.stage(
        claim=claim,
        stream=[PNG[:5], PNG[5:12], PNG[12:]],
        mime_type="image/png",
        expected_digest=digest,
        expected_size=len(PNG),
    )

    assert staged.content_digest == digest
    assert staged.byte_size == len(PNG)
