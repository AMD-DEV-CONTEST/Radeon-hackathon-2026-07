from __future__ import annotations

import json
import re
from datetime import timedelta
from pathlib import Path
from uuid import UUID

import pytest

from app.experience_asset.delivery import (
    ApprovalRejectedError,
    DeliveryOperation,
    E7DeliveryRepository,
    E7DeliveryService,
    FrozenE6ApprovalAdapter,
    LocalArtifactStore,
)
from app.experience_asset.delivery.models import DraftClaimV1
from app.experience_asset.delivery.service import (
    RouteDraftContractError,
    RouteIneligibleError,
    canonical_asset_hash,
)
from app.experience_asset.domain.enums import PrivacyResolution, RouteType
from tests.e7_fixtures import (
    NOW,
    RELATION_PROJECTION_HASH,
    RUN_ID,
    approval_binding_for,
    approval_for,
    content_for,
    make_asset,
    register_approval,
    scenarios,
)


def service(tmp_path) -> E7DeliveryService:
    repository = E7DeliveryRepository(tmp_path / "e7.sqlite3")
    repository.initialize()
    return E7DeliveryService(
        repository,
        LocalArtifactStore(tmp_path / "exports"),
        FrozenE6ApprovalAdapter(),
    )


def save_complete(service: E7DeliveryService, *, language: str = "en"):
    asset = make_asset("complete")
    return service.save_route_draft(
        create_request_id=UUID("20000000-0000-4000-8000-000000000001"),
        asset=asset,
        asset_version_hash=canonical_asset_hash(asset),
        relation_projection_hash=RELATION_PROJECTION_HASH,
        route=RouteType.PUBLIC,
        language=language,
        content=content_for(asset, language),
        created_by_run_id=RUN_ID,
        route_draft_id=UUID("20000000-0000-4000-8000-000000000002"),
        now=NOW,
    )


def identity_from_html(value: str) -> dict[str, object]:
    match = re.search(
        r'<script type="application/json" id="e7-delivery-identity">(.*?)</script>',
        value,
    )
    assert match
    return json.loads(match.group(1))


def identity_from_markdown(value: str) -> dict[str, object]:
    first_line = value.splitlines()[0]
    return json.loads(first_line.removeprefix("<!-- e7-delivery-identity:").removesuffix(" -->"))


def test_html_markdown_and_json_share_exact_version_and_hash(tmp_path) -> None:
    delivery = service(tmp_path)
    draft = save_complete(delivery)

    first = delivery.preview(draft.draft.route_draft_id)
    second = delivery.preview(draft.draft.route_draft_id)
    json_identity = json.loads(first.canonical_json)["identity"]

    assert first == second
    assert identity_from_html(first.html) == identity_from_markdown(first.markdown) == json_identity
    assert json_identity["version_id"] == str(draft.draft.canonical_version_id)
    assert json_identity["asset_version_hash"] == draft.asset_version_hash
    assert json_identity["route_draft_hash"] == draft.draft.content_hash
    assert json_identity["renderer_input_identity"] == draft.renderer_input_identity
    assert json_identity["relation_projection_hash"] == draft.relation_projection_hash
    assert draft.draft.content_hash != draft.renderer_input_identity
    assert "http://" not in first.html
    assert "https://" not in first.html


def test_checked_in_html_fixture_is_exact_renderer_output(tmp_path) -> None:
    delivery = service(tmp_path)
    draft = save_complete(delivery)
    expected = (Path(__file__).parents[1] / "fixtures" / "e7_complete_preview.html").read_text(
        encoding="utf-8"
    )

    assert delivery.preview(draft.draft.route_draft_id).html == expected


def test_route_draft_rejects_a_caller_supplied_asset_hash_mismatch(tmp_path) -> None:
    delivery = service(tmp_path)
    asset = make_asset("complete")

    with pytest.raises(RouteDraftContractError, match="canonical ExperienceAsset bytes"):
        delivery.save_route_draft(
            create_request_id=UUID("20000000-0000-4000-8000-000000000009"),
            asset=asset,
            asset_version_hash="f" * 64,
            relation_projection_hash=RELATION_PROJECTION_HASH,
            route=RouteType.PUBLIC,
            language="en",
            content=content_for(asset, "en"),
            created_by_run_id=RUN_ID,
            now=NOW,
        )


@pytest.mark.parametrize(
    ("language", "included", "excluded"),
    [
        ("en", "Decision evidence", "选择证据"),
        ("zh-CN", "选择证据", "Decision evidence"),
    ],
)
def test_one_draft_has_only_the_selected_language(
    tmp_path,
    language: str,
    included: str,
    excluded: str,
) -> None:
    delivery = service(tmp_path)
    draft = save_complete(delivery, language=language)
    preview = delivery.preview(draft.draft.route_draft_id)

    assert draft.draft.language == language
    assert included in preview.html
    assert excluded not in preview.html


def test_private_preview_never_requires_external_approval(tmp_path) -> None:
    delivery = service(tmp_path)
    asset = make_asset("privacy-risk")
    draft = delivery.save_route_draft(
        create_request_id=UUID("20000000-0000-4000-8000-000000000011"),
        asset=asset,
        asset_version_hash=canonical_asset_hash(asset),
        relation_projection_hash=RELATION_PROJECTION_HASH,
        route=RouteType.PUBLIC,
        language="zh-CN",
        content=content_for(asset, "zh-CN"),
        created_by_run_id=RUN_ID,
        now=NOW,
    )

    assert "私有预览" in delivery.preview(draft.draft.route_draft_id).html
    with pytest.raises(ApprovalRejectedError) as missing:
        delivery.export_bundle(
            request_id=UUID("20000000-0000-4000-8000-000000000012"),
            draft_id=draft.draft.route_draft_id,
            operation=DeliveryOperation.SHAREABLE_EXTERNAL_EXPORT,
        )
    assert missing.value.code == "APPROVAL_MISSING"


def test_external_export_rejects_open_and_wrong_bound_approvals(tmp_path) -> None:
    delivery = service(tmp_path)
    asset = make_asset("privacy-risk")
    draft = delivery.save_route_draft(
        create_request_id=UUID("20000000-0000-4000-8000-000000000021"),
        asset=asset,
        asset_version_hash=canonical_asset_hash(asset),
        relation_projection_hash=RELATION_PROJECTION_HASH,
        route=RouteType.PUBLIC,
        language="zh-CN",
        content=content_for(asset, "zh-CN"),
        created_by_run_id=RUN_ID,
        now=NOW,
    )
    open_approval = approval_for(draft)
    register_approval(delivery, draft, open_approval)
    with pytest.raises(ApprovalRejectedError) as open_error:
        delivery.export_bundle(
            request_id=UUID("20000000-0000-4000-8000-000000000022"),
            draft_id=draft.draft.route_draft_id,
            operation=DeliveryOperation.SHAREABLE_EXTERNAL_EXPORT,
            approval=open_approval,
            now=NOW + timedelta(seconds=2),
        )
    assert open_error.value.code == "PRIVACY_FINDINGS_OPEN"

    resolved_asset = make_asset(
        "privacy-risk",
        privacy_resolution=PrivacyResolution.ACKNOWLEDGED,
    )
    resolved = delivery.save_route_draft(
        create_request_id=UUID("20000000-0000-4000-8000-000000000023"),
        asset=resolved_asset,
        asset_version_hash=canonical_asset_hash(resolved_asset),
        relation_projection_hash=RELATION_PROJECTION_HASH,
        route=RouteType.PUBLIC,
        language="zh-CN",
        content=content_for(resolved_asset, "zh-CN"),
        created_by_run_id=RUN_ID,
        now=NOW + timedelta(seconds=3),
    )
    valid = approval_for(resolved, approved_at=NOW + timedelta(seconds=4))
    register_approval(delivery, resolved, valid)
    stale = valid.model_copy(update={"route_draft_hash": "f" * 64})
    with pytest.raises(ApprovalRejectedError) as mismatch:
        delivery.export_bundle(
            request_id=UUID("20000000-0000-4000-8000-000000000024"),
            draft_id=resolved.draft.route_draft_id,
            operation=DeliveryOperation.SHAREABLE_EXTERNAL_EXPORT,
            approval=stale,
            now=NOW + timedelta(seconds=5),
        )
    assert mismatch.value.code == "APPROVAL_BINDING_MISMATCH"


@pytest.mark.parametrize("change", ["content", "route", "language", "privacy"])
def test_any_bound_input_change_invalidates_old_approval(tmp_path, change: str) -> None:
    adapter = FrozenE6ApprovalAdapter()
    delivery = service(tmp_path)
    asset = make_asset("complete")
    first = save_complete(delivery)
    old_approval = approval_for(first)
    adapter.register_fixture(approval_binding_for(first, old_approval))
    next_asset = asset
    route = RouteType.PUBLIC
    language = "en"
    content = content_for(next_asset, language)
    if change == "content":
        content = content.model_copy(
            update={
                "summary": DraftClaimV1(
                    text="The same evidence now has a user-edited final summary.",
                    statement_ids=content.summary.statement_ids,
                )
            }
        )
    elif change == "route":
        route = RouteType.PEER
    elif change == "language":
        language = "zh-CN"
        content = content_for(next_asset, language)
    else:
        next_asset = make_asset("privacy-risk", privacy_resolution=PrivacyResolution.GENERALIZE)
        content = content_for(next_asset, language)
    request_ids = {
        "content": UUID("20000000-0000-4000-8000-000000000031"),
        "route": UUID("20000000-0000-4000-8000-000000000032"),
        "language": UUID("20000000-0000-4000-8000-000000000033"),
        "privacy": UUID("20000000-0000-4000-8000-000000000034"),
    }
    changed = delivery.save_route_draft(
        create_request_id=request_ids[change],
        asset=next_asset,
        asset_version_hash=canonical_asset_hash(next_asset),
        relation_projection_hash=RELATION_PROJECTION_HASH,
        route=route,
        language=language,
        content=content,
        created_by_run_id=RUN_ID,
        now=NOW + timedelta(seconds=10),
    )

    with pytest.raises(ApprovalRejectedError):
        adapter.validate_external_export(changed, old_approval)


def test_route_ineligible_fixture_cannot_create_a_draft(tmp_path) -> None:
    delivery = service(tmp_path)
    asset = make_asset("route-ineligible")
    with pytest.raises(RouteIneligibleError, match="CUSTOMER_EVALUATOR"):
        delivery.save_route_draft(
            create_request_id=UUID("20000000-0000-4000-8000-000000000041"),
            asset=asset,
            asset_version_hash=canonical_asset_hash(asset),
            relation_projection_hash=RELATION_PROJECTION_HASH,
            route=RouteType.CUSTOMER_EVALUATOR,
            language="en",
            content=content_for(asset, "en"),
            created_by_run_id=RUN_ID,
            now=NOW,
        )


def test_all_required_public_e7_fixture_categories_are_declared() -> None:
    assert set(scenarios()) == {"complete", "privacy-risk", "correction", "route-ineligible"}
