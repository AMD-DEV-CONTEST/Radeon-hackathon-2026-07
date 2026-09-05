from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from uuid import UUID

import pytest

from app.experience_asset.delivery import (
    DeliveryOperation,
    E7DeliveryRepository,
    E7DeliveryService,
    FrozenE6ApprovalAdapter,
    LocalArtifactStore,
)
from app.experience_asset.delivery.filesystem import ArtifactStoreError
from app.experience_asset.delivery.models import DraftState, ExportRequestState
from app.experience_asset.delivery.repository import DeliveryConflictError
from app.experience_asset.delivery.service import canonical_asset_hash
from app.experience_asset.domain.enums import ExportFormat, ExportState, RouteType
from tests.e7_fixtures import (
    ASSET_ID,
    NOW,
    RELATION_PROJECTION_HASH,
    RUN_ID,
    approval_for,
    content_for,
    make_asset,
    register_approval,
)
from tests.unit.test_e7_renderers import identity_from_html, identity_from_markdown


class FailOneMarkdownWrite(LocalArtifactStore):
    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.failed = False

    def write(self, path: str, data: bytes) -> None:
        if path.endswith(".md") and not self.failed:
            self.failed = True
            raise ArtifactStoreError("FILESYSTEM_WRITE_FAILED", "Injected Markdown failure")
        super().write(path, data)


def build_service(database: Path, store: LocalArtifactStore) -> E7DeliveryService:
    repository = E7DeliveryRepository(database)
    repository.initialize()
    return E7DeliveryService(repository, store, FrozenE6ApprovalAdapter())


def save_public(delivery: E7DeliveryService):
    asset = make_asset("complete")
    return delivery.save_route_draft(
        create_request_id=UUID("30000000-0000-4000-8000-000000000001"),
        asset=asset,
        asset_version_hash=canonical_asset_hash(asset),
        relation_projection_hash=RELATION_PROJECTION_HASH,
        route=RouteType.PUBLIC,
        language="en",
        content=content_for(asset, "en"),
        created_by_run_id=RUN_ID,
        route_draft_id=UUID("30000000-0000-4000-8000-000000000002"),
        now=NOW,
    )


def test_export_bundle_is_idempotent_and_survives_restart(tmp_path) -> None:
    database = tmp_path / "e7.sqlite3"
    exports = tmp_path / "exports"
    delivery = build_service(database, LocalArtifactStore(exports))
    draft = save_public(delivery)
    approval = register_approval(delivery, draft)
    request_id = UUID("30000000-0000-4000-8000-000000000003")

    first = delivery.export_bundle(
        request_id=request_id,
        draft_id=draft.draft.route_draft_id,
        operation=DeliveryOperation.SHAREABLE_EXTERNAL_EXPORT,
        approval=approval,
        now=NOW + timedelta(seconds=2),
    )
    mtimes = {record.path: Path(record.path).stat().st_mtime_ns for record in first.records}
    restarted = build_service(database, LocalArtifactStore(exports))
    register_approval(restarted, draft, approval)
    second = restarted.export_bundle(
        request_id=request_id,
        draft_id=draft.draft.route_draft_id,
        operation=DeliveryOperation.SHAREABLE_EXTERNAL_EXPORT,
        approval=approval,
        now=NOW + timedelta(seconds=30),
    )

    assert first.state is second.state is ExportRequestState.COMPLETE
    assert [record.export_id for record in first.records] == [
        record.export_id for record in second.records
    ]
    assert all(record.state is ExportState.CURRENT for record in second.records)
    assert mtimes == {
        record.path: Path(record.path).stat().st_mtime_ns for record in second.records
    }
    assert restarted.repository.get_draft(draft.draft.route_draft_id) == draft

    content = {
        record.format: Path(record.path).read_text(encoding="utf-8") for record in first.records
    }
    json_identity = json.loads(content[ExportFormat.JSON])["identity"]
    assert identity_from_html(content[ExportFormat.HTML]) == json_identity
    assert identity_from_markdown(content[ExportFormat.MARKDOWN]) == json_identity
    assert {record.route_draft_hash for record in first.records} == {draft.draft.content_hash}


def test_partial_export_write_is_visible_and_same_request_recovers(tmp_path) -> None:
    store = FailOneMarkdownWrite(tmp_path / "exports")
    delivery = build_service(tmp_path / "e7.sqlite3", store)
    draft = save_public(delivery)
    approval = register_approval(delivery, draft)
    request_id = UUID("30000000-0000-4000-8000-000000000011")

    failed = delivery.export_bundle(
        request_id=request_id,
        draft_id=draft.draft.route_draft_id,
        operation=DeliveryOperation.SHAREABLE_EXTERNAL_EXPORT,
        approval=approval,
        now=NOW + timedelta(seconds=2),
    )
    recovered = delivery.export_bundle(
        request_id=request_id,
        draft_id=draft.draft.route_draft_id,
        operation=DeliveryOperation.SHAREABLE_EXTERNAL_EXPORT,
        approval=approval,
        now=NOW + timedelta(seconds=3),
    )

    assert failed.state is ExportRequestState.FAILED
    assert failed.failed_formats == [ExportFormat.MARKDOWN]
    assert recovered.state is ExportRequestState.COMPLETE
    assert recovered.failed_formats == []
    assert all(Path(record.path).exists() for record in recovered.records)
    assert {event.event_type for event in delivery.repository.list_audit_events(ASSET_ID)} >= {
        "EXPORT_FAILED",
        "EXPORT_COMPLETED",
    }


def test_new_corrected_draft_supersedes_prior_draft_and_outputs(tmp_path) -> None:
    delivery = build_service(tmp_path / "e7.sqlite3", LocalArtifactStore(tmp_path / "exports"))
    first = save_public(delivery)
    approval = register_approval(delivery, first)
    exported = delivery.export_bundle(
        request_id=UUID("30000000-0000-4000-8000-000000000021"),
        draft_id=first.draft.route_draft_id,
        operation=DeliveryOperation.SHAREABLE_EXTERNAL_EXPORT,
        approval=approval,
        now=NOW + timedelta(seconds=2),
    )
    corrected_asset = make_asset("correction", parent_version_id=first.draft.canonical_version_id)
    corrected = delivery.save_route_draft(
        create_request_id=UUID("30000000-0000-4000-8000-000000000022"),
        asset=corrected_asset,
        asset_version_hash=canonical_asset_hash(corrected_asset),
        relation_projection_hash=RELATION_PROJECTION_HASH,
        route=RouteType.PEER,
        language="en",
        content=content_for(corrected_asset, "en"),
        created_by_run_id=RUN_ID,
        now=NOW + timedelta(seconds=3),
    )

    historical = delivery.repository.get_draft(first.draft.route_draft_id)
    assert historical.state is DraftState.SUPERSEDED
    assert historical.superseded_by_draft_id == corrected.draft.route_draft_id
    assert all(
        record.state is ExportState.SUPERSEDED
        for record in delivery.repository.list_exports(draft_id=first.draft.route_draft_id)
    )
    assert "SUPERSEDED" in delivery.preview(first.draft.route_draft_id).html
    assert corrected.lineage_parent_version_id == first.draft.canonical_version_id
    assert all(Path(record.path).exists() for record in exported.records)
    with pytest.raises(DeliveryConflictError, match="superseded"):
        delivery.export_bundle(
            request_id=UUID("30000000-0000-4000-8000-000000000023"),
            draft_id=first.draft.route_draft_id,
            operation=DeliveryOperation.SHAREABLE_EXTERNAL_EXPORT,
            approval=approval_for(first),
            now=NOW + timedelta(seconds=4),
        )


def test_private_self_download_needs_no_external_approval_and_is_labelled(tmp_path) -> None:
    delivery = build_service(tmp_path / "e7.sqlite3", LocalArtifactStore(tmp_path / "exports"))
    asset = make_asset("complete")
    draft = delivery.save_route_draft(
        create_request_id=UUID("30000000-0000-4000-8000-000000000031"),
        asset=asset,
        asset_version_hash=canonical_asset_hash(asset),
        relation_projection_hash=RELATION_PROJECTION_HASH,
        route=RouteType.PRIVATE_SELF,
        language="en",
        content=content_for(asset, "en"),
        created_by_run_id=RUN_ID,
        now=NOW,
    )
    result = delivery.export_bundle(
        request_id=UUID("30000000-0000-4000-8000-000000000032"),
        draft_id=draft.draft.route_draft_id,
        operation=DeliveryOperation.PRIVATE_DOWNLOAD,
        now=NOW + timedelta(seconds=1),
    )

    html = next(record for record in result.records if record.format is ExportFormat.HTML)
    assert "not approved for external sharing" in Path(html.path).read_text(encoding="utf-8")


def test_export_request_identity_cannot_be_reused_for_another_draft(tmp_path) -> None:
    delivery = build_service(tmp_path / "e7.sqlite3", LocalArtifactStore(tmp_path / "exports"))
    first = save_public(delivery)
    first_approval = register_approval(delivery, first)
    request_id = UUID("30000000-0000-4000-8000-000000000041")
    delivery.export_bundle(
        request_id=request_id,
        draft_id=first.draft.route_draft_id,
        operation=DeliveryOperation.SHAREABLE_EXTERNAL_EXPORT,
        approval=first_approval,
        now=NOW + timedelta(seconds=1),
    )
    corrected_asset = make_asset("correction", parent_version_id=first.draft.canonical_version_id)
    second = delivery.save_route_draft(
        create_request_id=UUID("30000000-0000-4000-8000-000000000042"),
        asset=corrected_asset,
        asset_version_hash=canonical_asset_hash(corrected_asset),
        relation_projection_hash=RELATION_PROJECTION_HASH,
        route=RouteType.PEER,
        language="en",
        content=content_for(corrected_asset, "en"),
        created_by_run_id=RUN_ID,
        now=NOW + timedelta(seconds=2),
    )
    second_approval = register_approval(
        delivery,
        second,
        approval_for(second, approved_at=NOW + timedelta(seconds=3)),
    )
    with pytest.raises(DeliveryConflictError, match="other inputs"):
        delivery.export_bundle(
            request_id=request_id,
            draft_id=second.draft.route_draft_id,
            operation=DeliveryOperation.SHAREABLE_EXTERNAL_EXPORT,
            approval=second_approval,
            now=NOW + timedelta(seconds=4),
        )
