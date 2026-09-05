"""Independent recheck of PR #34's two reported blockers, at the integrated head.

The execution package is explicit that green isolated tests and the fix
author's own evidence do not substitute for this. PR #34's own compatibility
test loads a checked-in fixture for *both* sides of the E6/E7 seam, so it
proves the adapter accepts a fixture — not that the live E6 policy now sitting
in this tree computes the hash E7 consumes. These tests drive the live code.
"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from app.experience_asset.delivery import (
    DeliveryOperation,
    E7DeliveryRepository,
    E7DeliveryService,
    FrozenE6ApprovalAdapter,
    FrozenE6ApprovalBindingV1,
    LocalArtifactStore,
)
from app.experience_asset.delivery.models import (
    DeletionRequestState,
    ExportRequestState,
    StoredRouteDraftV1,
)
from app.experience_asset.delivery.repository import DeliveryConflictError
from app.experience_asset.domain.models import RouteDecision
from app.experience_asset.policy.m5 import route_draft_binding_hash
from tests.e7_fixtures import ASSET_ID, NOW
from tests.integration.test_e7_deletion import build_service, save_private_export

FIXTURE = Path(__file__).parents[1] / "fixtures" / "e6_e7_approval_compatibility.json"


def _payload() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _service(tmp_path: Path, bindings=()) -> E7DeliveryService:
    repository = E7DeliveryRepository(tmp_path / "e7.sqlite3")
    repository.initialize()
    return E7DeliveryService(
        repository,
        LocalArtifactStore(tmp_path / "exports"),
        FrozenE6ApprovalAdapter(bindings),
    )


# --------------------------------------------------------------------------
# Blocker 2: E6 must recompute the same canonical approval binding/hash E7 uses
# --------------------------------------------------------------------------


def test_live_e6_recomputes_the_binding_hash_e7_consumes() -> None:
    """The seam, checked against this tree's E6 rather than a frozen pair.

    The fixture records the exact E6 inputs and the resulting approval. If the
    integrated E6 produces a different hash for those inputs, every export
    approved before integration silently stops matching, and the failure would
    surface as "approval rejected" long after the cause.
    """

    payload = _payload()
    inputs = payload["e6_inputs"]
    draft = StoredRouteDraftV1.model_validate(payload["stored_route_draft"])
    binding = FrozenE6ApprovalBindingV1.model_validate(payload["approval_binding"])

    recomputed = route_draft_binding_hash(
        draft.draft,
        asset_content_hash=inputs["asset_content_hash"],
        relation_projection_hash=inputs["relation_projection_hash"],
        route_decision=RouteDecision.model_validate(inputs["route_decision"]),
        renderer_input_hash=inputs["renderer_input_hash"],
    )

    assert recomputed == binding.approval.route_draft_hash


def test_the_binding_hash_is_not_the_draft_content_hash() -> None:
    """Guards the assertion above from passing for a trivial reason."""

    payload = _payload()
    binding = FrozenE6ApprovalBindingV1.model_validate(payload["approval_binding"])

    assert binding.approval.route_draft_hash != binding.draft_content_hash
    assert binding.approval.route_draft_hash != binding.renderer_input_identity


@pytest.mark.parametrize(
    "field",
    ["asset_content_hash", "relation_projection_hash", "renderer_input_hash"],
)
def test_any_changed_bound_input_moves_the_binding_hash(field: str) -> None:
    """Staleness has to be expressible, or the binding proves nothing."""

    payload = _payload()
    inputs = dict(payload["e6_inputs"])
    draft = StoredRouteDraftV1.model_validate(payload["stored_route_draft"])
    binding = FrozenE6ApprovalBindingV1.model_validate(payload["approval_binding"])
    inputs[field] = "9" * 64

    moved = route_draft_binding_hash(
        draft.draft,
        asset_content_hash=inputs["asset_content_hash"],
        relation_projection_hash=inputs["relation_projection_hash"],
        route_decision=RouteDecision.model_validate(inputs["route_decision"]),
        renderer_input_hash=inputs["renderer_input_hash"],
    )

    assert moved != binding.approval.route_draft_hash


def test_external_export_still_accepts_the_live_binding(tmp_path: Path) -> None:
    """End to end at the integrated head: E6-issued approval, E7 export."""

    payload = _payload()
    draft = StoredRouteDraftV1.model_validate(payload["stored_route_draft"])
    binding = FrozenE6ApprovalBindingV1.model_validate(payload["approval_binding"])
    delivery = _service(tmp_path, (binding,))
    delivery.repository.save_draft(draft)

    result = delivery.export_bundle(
        request_id=uuid4(),
        draft_id=draft.draft.route_draft_id,
        operation=DeliveryOperation.SHAREABLE_EXTERNAL_EXPORT,
        approval=binding.approval,
        now=binding.approval.approved_at,
    )

    assert result.state is ExportRequestState.COMPLETE


# --------------------------------------------------------------------------
# Blocker 1: an expired deletion request must not permanently lock an asset
# --------------------------------------------------------------------------


def _managed_asset(tmp_path: Path):
    """One asset with real E7-managed drafts and exported files."""

    repository = E7DeliveryRepository(tmp_path / "e7.sqlite3")
    delivery = build_service(repository, LocalArtifactStore(tmp_path / "exports"))
    _, exported = save_private_export(delivery)
    return repository, delivery, exported


def test_expired_deletion_refuses_confirmation(tmp_path: Path) -> None:
    repository, delivery, _ = _managed_asset(tmp_path)
    expired = delivery.request_deletion(
        request_id=uuid4(), asset_id=ASSET_ID, now=NOW, expires_in=timedelta(seconds=1)
    )
    # Expiry is evaluated when the next request arrives, matching E7's design.
    delivery.request_deletion(
        request_id=uuid4(), asset_id=ASSET_ID, now=NOW + timedelta(seconds=2)
    )

    with pytest.raises(DeliveryConflictError, match="expired"):
        delivery.confirm_deletion(
            request_id=expired.request_id,
            confirmation_token=expired.confirmation_token,
            second_confirmation=True,
            now=NOW + timedelta(seconds=3),
        )
    assert (
        repository.get_deletion_request(expired.request_id).state
        is DeletionRequestState.EXPIRED
    )


def test_expired_deletion_does_not_permanently_lock_the_asset(tmp_path: Path) -> None:
    """The blocker itself, carried all the way to a completed deletion.

    PR #34's own expiry test stops once a second request can be *created*. That
    proves the request slot was released, not that the asset can still be
    deleted — and an asset that can never complete deletion is exactly the
    permanent lock this recheck exists to rule out.
    """

    repository, delivery, exported = _managed_asset(tmp_path)
    expired = delivery.request_deletion(
        request_id=uuid4(), asset_id=ASSET_ID, now=NOW, expires_in=timedelta(seconds=1)
    )
    retry = delivery.request_deletion(
        request_id=uuid4(), asset_id=ASSET_ID, now=NOW + timedelta(seconds=2)
    )
    assert retry.state is DeletionRequestState.REQUESTED
    assert retry.request_id != expired.request_id

    outcome = delivery.confirm_deletion(
        request_id=retry.request_id,
        confirmation_token=retry.confirmation_token,
        second_confirmation=True,
        now=NOW + timedelta(seconds=3),
    )

    assert outcome.terminal_state == "SUCCEEDED", outcome.safe_user_message
    assert repository.content_counts(ASSET_ID) == (0, 0)
    assert not any(Path(record.path).exists() for record in exported.records)


def test_second_deletion_confirmation_is_idempotent(tmp_path: Path) -> None:
    _, delivery, _ = _managed_asset(tmp_path)
    request = delivery.request_deletion(
        request_id=uuid4(), asset_id=ASSET_ID, now=NOW
    )

    first = delivery.confirm_deletion(
        request_id=request.request_id,
        confirmation_token=request.confirmation_token,
        second_confirmation=True,
        now=NOW + timedelta(seconds=1),
    )
    second = delivery.confirm_deletion(
        request_id=request.request_id,
        confirmation_token=request.confirmation_token,
        second_confirmation=True,
        now=NOW + timedelta(seconds=5),
    )

    assert first.terminal_state == second.terminal_state == "SUCCEEDED"
    assert first.request_id == second.request_id
