from __future__ import annotations

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
from app.experience_asset.delivery.models import DeletionRequestState
from app.experience_asset.delivery.repository import (
    DeliveryConflictError,
    DeliveryPersistenceError,
)
from app.experience_asset.delivery.service import (
    SecondConfirmationRequiredError,
    canonical_asset_hash,
)
from app.experience_asset.domain.enums import RouteType
from tests.e7_fixtures import (
    ASSET_ID,
    NOW,
    RELATION_PROJECTION_HASH,
    RUN_ID,
    content_for,
    make_asset,
)


class FailOneDeleteStore(LocalArtifactStore):
    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.failed = False

    def delete(self, path: str) -> None:
        if path.endswith(".md") and not self.failed:
            self.failed = True
            raise ArtifactStoreError("FILESYSTEM_DELETE_FAILED", "Injected delete failure")
        super().delete(path)


class FailOnceBeginRepository(E7DeliveryRepository):
    def __init__(self, database_path: Path) -> None:
        super().__init__(database_path)
        self.failed = False

    def begin_deletion(self, *args, **kwargs):
        if not self.failed:
            self.failed = True
            raise DeliveryPersistenceError("injected begin failure")
        return super().begin_deletion(*args, **kwargs)


class FailOnceFinalizeRepository(E7DeliveryRepository):
    def __init__(self, database_path: Path) -> None:
        super().__init__(database_path)
        self.failed = False

    def finalize_deletion(self, *args, **kwargs):
        if not self.failed:
            self.failed = True
            raise DeliveryPersistenceError("injected finalize failure")
        return super().finalize_deletion(*args, **kwargs)


def build_service(repository: E7DeliveryRepository, store: LocalArtifactStore) -> E7DeliveryService:
    repository.initialize()
    return E7DeliveryService(repository, store, FrozenE6ApprovalAdapter())


def save_private_export(delivery: E7DeliveryService):
    asset = make_asset("complete")
    draft = delivery.save_route_draft(
        create_request_id=UUID("40000000-0000-4000-8000-000000000001"),
        asset=asset,
        asset_version_hash=canonical_asset_hash(asset),
        relation_projection_hash=RELATION_PROJECTION_HASH,
        route=RouteType.PRIVATE_SELF,
        language="en",
        content=content_for(asset, "en"),
        created_by_run_id=RUN_ID,
        route_draft_id=UUID("40000000-0000-4000-8000-000000000002"),
        now=NOW,
    )
    exported = delivery.export_bundle(
        request_id=UUID("40000000-0000-4000-8000-000000000003"),
        draft_id=draft.draft.route_draft_id,
        operation=DeliveryOperation.PRIVATE_DOWNLOAD,
        now=NOW + timedelta(seconds=1),
    )
    return draft, exported


def test_deletion_requires_second_confirmation_and_replays_idempotently(tmp_path) -> None:
    repository = E7DeliveryRepository(tmp_path / "e7.sqlite3")
    delivery = build_service(repository, LocalArtifactStore(tmp_path / "exports"))
    _, exported = save_private_export(delivery)
    request_id = UUID("40000000-0000-4000-8000-000000000011")

    first = delivery.request_deletion(request_id=request_id, asset_id=ASSET_ID, now=NOW)
    repeated = delivery.request_deletion(request_id=request_id, asset_id=ASSET_ID, now=NOW)
    assert first == repeated
    with pytest.raises(SecondConfirmationRequiredError):
        delivery.confirm_deletion(
            request_id=request_id,
            confirmation_token=first.confirmation_token,
            second_confirmation=False,
            now=NOW + timedelta(seconds=2),
        )
    assert all(Path(record.path).exists() for record in exported.records)

    completed = delivery.confirm_deletion(
        request_id=request_id,
        confirmation_token=first.confirmation_token,
        second_confirmation=True,
        now=NOW + timedelta(seconds=3),
    )
    replayed = delivery.confirm_deletion(
        request_id=request_id,
        confirmation_token=first.confirmation_token,
        second_confirmation=True,
        now=NOW + timedelta(seconds=4),
    )

    assert completed == replayed
    assert completed.state == "COMPLETED"
    assert completed.terminal_state == "SUCCEEDED"
    assert completed.deleted_file_count == 3
    assert repository.content_counts(ASSET_ID) == (0, 0)
    assert all(not Path(record.path).exists() for record in exported.records)
    assert repository.get_deletion_request(request_id).state is DeletionRequestState.COMPLETED
    events = repository.list_audit_events(ASSET_ID)
    assert [event.event_type for event in events].count("DELETION_COMPLETED") == 1
    assert all("chair" not in event.model_dump_json().lower() for event in events)


def test_filesystem_partial_failure_is_visible_locked_and_recovers_after_restart(tmp_path) -> None:
    database = tmp_path / "e7.sqlite3"
    root = tmp_path / "exports"
    repository = E7DeliveryRepository(database)
    delivery = build_service(repository, FailOneDeleteStore(root))
    _, exported = save_private_export(delivery)
    request_id = UUID("40000000-0000-4000-8000-000000000021")
    request = delivery.request_deletion(request_id=request_id, asset_id=ASSET_ID, now=NOW)

    partial = delivery.confirm_deletion(
        request_id=request_id,
        confirmation_token=request.confirmation_token,
        second_confirmation=True,
        now=NOW + timedelta(seconds=2),
    )

    assert partial.state == "PARTIAL_FAILURE"
    assert partial.terminal_state == "DELETION_FAILED"
    assert partial.retryable is True
    assert len(partial.failed_paths) == 1
    assert repository.content_counts(ASSET_ID) == (1, 3)
    remaining = [record.path for record in exported.records if Path(record.path).exists()]
    assert remaining == partial.failed_paths
    with pytest.raises(DeliveryConflictError, match="locked"):
        asset = make_asset("correction")
        delivery.save_route_draft(
            create_request_id=UUID("40000000-0000-4000-8000-000000000022"),
            asset=asset,
            asset_version_hash=canonical_asset_hash(asset),
            relation_projection_hash=RELATION_PROJECTION_HASH,
            route=RouteType.PEER,
            language="en",
            content=content_for(asset, "en"),
            created_by_run_id=RUN_ID,
            now=NOW + timedelta(seconds=3),
        )

    restarted_repository = E7DeliveryRepository(database)
    restarted = build_service(restarted_repository, LocalArtifactStore(root))
    recovered = restarted.retry_deletion(request_id, now=NOW + timedelta(seconds=4))
    assert recovered.state == "COMPLETED"
    assert restarted_repository.content_counts(ASSET_ID) == (0, 0)
    assert all(not Path(record.path).exists() for record in exported.records)


def test_sqlite_begin_failure_removes_no_files_and_confirmation_can_retry(tmp_path) -> None:
    repository = FailOnceBeginRepository(tmp_path / "e7.sqlite3")
    delivery = build_service(repository, LocalArtifactStore(tmp_path / "exports"))
    _, exported = save_private_export(delivery)
    request_id = UUID("40000000-0000-4000-8000-000000000031")
    request = delivery.request_deletion(request_id=request_id, asset_id=ASSET_ID, now=NOW)

    failed = delivery.confirm_deletion(
        request_id=request_id,
        confirmation_token=request.confirmation_token,
        second_confirmation=True,
        now=NOW + timedelta(seconds=2),
    )
    assert failed.state == "STORAGE_ERROR"
    assert failed.retryable is True
    assert all(Path(record.path).exists() for record in exported.records)
    assert repository.get_deletion_request(request_id).state is DeletionRequestState.REQUESTED

    recovered = delivery.confirm_deletion(
        request_id=request_id,
        confirmation_token=request.confirmation_token,
        second_confirmation=True,
        now=NOW + timedelta(seconds=3),
    )
    assert recovered.state == "COMPLETED"
    assert "DELETION_STORAGE_FAILURE" in {
        event.event_type for event in repository.list_audit_events(ASSET_ID)
    }


def test_sqlite_finalize_failure_persists_files_removed_and_restart_finishes(tmp_path) -> None:
    database = tmp_path / "e7.sqlite3"
    root = tmp_path / "exports"
    repository = FailOnceFinalizeRepository(database)
    delivery = build_service(repository, LocalArtifactStore(root))
    _, exported = save_private_export(delivery)
    request_id = UUID("40000000-0000-4000-8000-000000000041")
    request = delivery.request_deletion(request_id=request_id, asset_id=ASSET_ID, now=NOW)

    failed = delivery.confirm_deletion(
        request_id=request_id,
        confirmation_token=request.confirmation_token,
        second_confirmation=True,
        now=NOW + timedelta(seconds=2),
    )
    assert failed.state == "FILES_REMOVED"
    assert failed.terminal_state == "STORAGE_ERROR"
    assert all(not Path(record.path).exists() for record in exported.records)
    assert repository.content_counts(ASSET_ID) == (1, 3)

    restarted_repository = E7DeliveryRepository(database)
    restarted = build_service(restarted_repository, LocalArtifactStore(root))
    recovered = restarted.retry_deletion(request_id, now=NOW + timedelta(seconds=3))
    assert recovered.state == "COMPLETED"
    assert recovered.deleted_draft_count == 1
    assert recovered.deleted_export_count == 3
    assert restarted_repository.content_counts(ASSET_ID) == (0, 0)


def test_wrong_or_expired_confirmation_never_starts_deletion(tmp_path) -> None:
    repository = E7DeliveryRepository(tmp_path / "e7.sqlite3")
    delivery = build_service(repository, LocalArtifactStore(tmp_path / "exports"))
    _, exported = save_private_export(delivery)
    request_id = UUID("40000000-0000-4000-8000-000000000051")
    request = delivery.request_deletion(
        request_id=request_id,
        asset_id=ASSET_ID,
        now=NOW,
        expires_in=timedelta(seconds=1),
    )
    with pytest.raises(DeliveryConflictError, match="token"):
        delivery.confirm_deletion(
            request_id=request_id,
            confirmation_token="DELETE-WRONG",
            second_confirmation=True,
            now=NOW,
        )
    with pytest.raises(DeliveryConflictError, match="expired"):
        delivery.confirm_deletion(
            request_id=request_id,
            confirmation_token=request.confirmation_token,
            second_confirmation=True,
            now=NOW + timedelta(seconds=2),
        )
    assert all(Path(record.path).exists() for record in exported.records)


def test_expired_request_releases_asset_for_a_new_two_step_deletion(tmp_path) -> None:
    repository = E7DeliveryRepository(tmp_path / "e7.sqlite3")
    delivery = build_service(repository, LocalArtifactStore(tmp_path / "exports"))
    _, exported = save_private_export(delivery)
    first_id = UUID("40000000-0000-4000-8000-000000000061")
    second_id = UUID("40000000-0000-4000-8000-000000000062")
    first = delivery.request_deletion(
        request_id=first_id,
        asset_id=ASSET_ID,
        now=NOW,
        expires_in=timedelta(seconds=1),
    )

    second = delivery.request_deletion(
        request_id=second_id,
        asset_id=ASSET_ID,
        now=NOW + timedelta(seconds=2),
    )

    assert repository.get_deletion_request(first_id).state is DeletionRequestState.EXPIRED
    assert second.state is DeletionRequestState.REQUESTED
    with pytest.raises(DeliveryConflictError, match="expired"):
        delivery.confirm_deletion(
            request_id=first_id,
            confirmation_token=first.confirmation_token,
            second_confirmation=True,
            now=NOW + timedelta(seconds=2),
        )
    with pytest.raises(SecondConfirmationRequiredError):
        delivery.confirm_deletion(
            request_id=second_id,
            confirmation_token=second.confirmation_token,
            second_confirmation=False,
            now=NOW + timedelta(seconds=3),
        )
    assert repository.content_counts(ASSET_ID) == (1, 3)
    assert all(Path(record.path).exists() for record in exported.records)
    assert "DELETION_REQUEST_EXPIRED" in {
        event.event_type for event in repository.list_audit_events(ASSET_ID)
    }
