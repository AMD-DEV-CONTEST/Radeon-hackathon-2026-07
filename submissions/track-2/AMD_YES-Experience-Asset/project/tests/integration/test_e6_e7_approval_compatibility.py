from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import pytest

from app.experience_asset.delivery import (
    ApprovalRejectedError,
    DeliveryOperation,
    E7DeliveryRepository,
    E7DeliveryService,
    FrozenE6ApprovalAdapter,
    FrozenE6ApprovalBindingV1,
    LocalArtifactStore,
)
from app.experience_asset.delivery.models import ExportRequestState, StoredRouteDraftV1


def compatibility_fixture() -> dict[str, object]:
    path = Path(__file__).parents[1] / "fixtures" / "e6_e7_approval_compatibility.json"
    return json.loads(path.read_text(encoding="utf-8"))


def fixture_models() -> tuple[StoredRouteDraftV1, FrozenE6ApprovalBindingV1]:
    payload = compatibility_fixture()
    return (
        StoredRouteDraftV1.model_validate(payload["stored_route_draft"]),
        FrozenE6ApprovalBindingV1.model_validate(payload["approval_binding"]),
    )


def test_real_e6_helper_approval_is_accepted_for_external_export(tmp_path) -> None:
    draft, binding = fixture_models()
    repository = E7DeliveryRepository(tmp_path / "e7.sqlite3")
    repository.initialize()
    repository.save_draft(draft)
    delivery = E7DeliveryService(
        repository,
        LocalArtifactStore(tmp_path / "exports"),
        FrozenE6ApprovalAdapter((binding,)),
    )

    result = delivery.export_bundle(
        request_id=UUID("50000000-0000-4000-8000-000000000001"),
        draft_id=draft.draft.route_draft_id,
        operation=DeliveryOperation.SHAREABLE_EXTERNAL_EXPORT,
        approval=binding.approval,
        now=binding.approval.approved_at,
    )

    assert result.state is ExportRequestState.COMPLETE
    assert all(Path(record.path).exists() for record in result.records)
    assert {record.route_draft_hash for record in result.records} == {draft.draft.content_hash}
    assert binding.approval.route_draft_hash not in {
        draft.draft.content_hash,
        draft.renderer_input_identity,
    }


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("asset_version_hash", "9" * 64),
        ("relation_projection_hash", "8" * 64),
        ("privacy_state_hash", "7" * 64),
        ("renderer_input_identity", "6" * 64),
    ],
)
def test_frozen_e6_binding_rejects_changed_e7_snapshot(
    field: str,
    replacement: str,
) -> None:
    draft, binding = fixture_models()
    changed = draft.model_copy(update={field: replacement})

    with pytest.raises(ApprovalRejectedError) as rejected:
        FrozenE6ApprovalAdapter((binding,)).validate_external_export(
            changed,
            binding.approval,
        )

    assert rejected.value.code == "APPROVAL_BINDING_MISMATCH"


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("route", "PEER"),
        ("language", "en"),
        ("content_hash", "5" * 64),
    ],
)
def test_frozen_e6_binding_rejects_changed_route_draft(
    field: str,
    replacement: str,
) -> None:
    draft, binding = fixture_models()
    changed = draft.model_copy(
        update={"draft": draft.draft.model_copy(update={field: replacement})}
    )

    with pytest.raises(ApprovalRejectedError) as rejected:
        FrozenE6ApprovalAdapter((binding,)).validate_external_export(
            changed,
            binding.approval,
        )

    assert rejected.value.code == "APPROVAL_BINDING_MISMATCH"
