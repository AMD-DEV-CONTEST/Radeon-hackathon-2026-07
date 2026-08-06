"""Regenerate the public E6 approval fixture from an exact E6 checkout."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import app.experience_asset.policy.m5 as policy
from app.experience_asset.application.m5 import ApprovalRequestV1, M5IsolatedService
from app.experience_asset.domain.enums import RouteType
from app.experience_asset.domain.models import RouteDraft
from tests.fixtures.m5 import (
    ASSET_ID,
    CONTENT_HASH,
    RENDERER_INPUT_HASH,
    RUN_ID,
    STATEMENT_IDS,
    VERSION_ID,
    complete_context,
)


class FixedDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 8, 2, 4, 30, tzinfo=UTC)


def main(fixture_path: str) -> None:
    policy.datetime = FixedDatetime
    fixture = json.loads(Path(fixture_path).read_text(encoding="utf-8"))
    service = M5IsolatedService()
    context = complete_context(include_sensitive_tags=False)
    review = service.review_privacy(context, proposals=[], run_id=RUN_ID)
    matrix = service.evaluate_routes(context, privacy_review=review)
    draft = RouteDraft(
        route_draft_id=UUID(int=500),
        route=RouteType.PUBLIC,
        language="zh-CN",
        canonical_version_id=VERSION_ID,
        statement_ids=[STATEMENT_IDS["event"], STATEMENT_IDS["lesson"]],
        content_hash=fixture["stored_route_draft"]["draft"]["content_hash"],
        created_by_run_id=RUN_ID,
    )
    decision = next(item for item in matrix.decisions if item.route is RouteType.PUBLIC)
    binding_hash = policy.route_draft_binding_hash(
        draft,
        asset_content_hash=CONTENT_HASH,
        relation_projection_hash=context.relation.projection_hash,
        route_decision=decision,
        renderer_input_hash=RENDERER_INPUT_HASH,
    )
    request = ApprovalRequestV1(
        expected_asset_id=ASSET_ID,
        expected_version_id=VERSION_ID,
        expected_content_hash=CONTENT_HASH,
        route=draft.route,
        language=draft.language,
        expected_route_draft_hash=binding_hash,
        expected_privacy_review_hash=review.review_hash,
        user_action="APPROVE_SHAREABLE_EXPORT",
        idempotency_key="e7-compatibility-v1",
    )
    approval = service.approve(
        context,
        matrix,
        review,
        draft=draft,
        renderer_input_hash=RENDERER_INPUT_HASH,
        request=request,
    )
    assert approval.model_dump(mode="json") == fixture["approval_binding"]["approval"]
    assert decision.model_dump(mode="json") == fixture["e6_inputs"]["route_decision"]
    assert binding_hash == fixture["approval_binding"]["approval"]["route_draft_hash"]
    print("PASS: E6 helper output exactly matches the E7 compatibility fixture")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: verify_e6_e7_approval_compatibility.py <fixture.json>")
    main(sys.argv[1])
