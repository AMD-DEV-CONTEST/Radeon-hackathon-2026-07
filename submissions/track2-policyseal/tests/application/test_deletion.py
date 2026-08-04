from __future__ import annotations

from pathlib import Path

import pytest

from policyseal.application.deletion import DeletionService
from policyseal.application.matrix import default_xlsx_contexts
from policyseal.domain.models import StoredArtifactRecord
from policyseal.storage.file_store import FileNamespace


def test_deletion_removes_controlled_content_and_retains_no_raw_tombstone(
    services,
    hero_xlsx: Path,
) -> None:
    created = services.analysis.create_task(
        hero_xlsx.read_bytes(),
        suffix=".xlsx",
        context=default_xlsx_contexts()[0],
        requester_id="delete-requester",
    )
    result = services.analysis.analyze_revision(created.revision.id)
    source_path = services.file_store.path_for(
        FileNamespace.SOURCES,
        result.task.source_storage_id,
    )
    assert result.revision.output_storage_id is not None
    output_path = services.file_store.path_for(
        FileNamespace.OUTPUTS,
        result.revision.output_storage_id,
    )
    preview = services.file_store.write(FileNamespace.PREVIEWS, b"safe preview", suffix=".png")
    services.repository.add_artifact(
        StoredArtifactRecord(
            result.task.id,
            result.revision.id,
            FileNamespace.PREVIEWS.value,
            preview.storage_id,
        )
    )
    deleted_task_ids: list[str] = []
    deletion = DeletionService(
        services.repository,
        services.file_store,
        services.fingerprinter,
        services.analysis.policy_pack,
        services.analysis.audit_chain,
        delete_task_state=lambda task_id: deleted_task_ids.append(task_id),
    )

    tombstone = deletion.delete(result.task.id, actor="delete-requester")

    assert not source_path.exists() and not output_path.exists() and not preview.path.exists()
    with pytest.raises(KeyError):
        services.repository.get_task(result.task.id)
    stored_tombstone = services.repository.get_tombstone(result.task.id)
    assert stored_tombstone == tombstone
    assert deleted_task_ids == [result.task.id]
    serialized = repr(tombstone)
    assert "delete-requester" not in serialized
    assert "Aster Works" not in serialized
