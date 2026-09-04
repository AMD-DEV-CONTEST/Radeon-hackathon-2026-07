from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import Response, StreamingResponse

from policyseal.api.dependencies import AppServices, get_services
from policyseal.api.schemas import (
    EvidenceRecordResponse,
    ReviewRegionResponse,
    ReviewResponse,
    RevisionResponse,
)
from policyseal.api.sse import stage_event_stream
from policyseal.domain.enums import Action
from policyseal.domain.models import DocumentRegion, PolicyDecision
from policyseal.storage.file_store import FileNamespace

router = APIRouter(prefix="/api/revisions", tags=["revisions"])


def _output_preview(region: DocumentRegion, decision: PolicyDecision) -> str | None:
    if decision.action in {Action.REMOVE, Action.BLOCK}:
        return None
    if decision.action in {Action.KEEP, Action.REQUIRE_APPROVAL}:
        return region.text
    if decision.transform == "mask_last_four":
        digits = "".join(character for character in region.text if character.isdigit())
        return f"Account ending {digits[-4:]}" if len(digits) >= 4 else "Masked value"
    labels = {
        "keep_name_work_email": "Filtered contact fields",
        "keep_audit_amount": "Audit amount only",
        "generalize_approval_status": "Generalized approval status",
        "generalize_shortlist_status": "Generalized shortlist status",
        "stable_asset_alias": "Stable asset alias",
        "stable_person_alias": "Stable person alias",
        "placeholder_buyer": "[Original Buyer]",
        "placeholder_supplier": "[Original Supplier]",
        "placeholder_corporate_id": "[Corporate Identifier]",
        "placeholder_contact": "[Original Contact]",
        "placeholder_contract_date": "[Original Contract Date]",
        "placeholder_historical_pricing": "[Historical Pricing Removed]",
    }
    if decision.action is Action.FILTER:
        return labels.get(decision.transform or "")
    return labels.get(decision.transform or "", f"{decision.action.value.title()} output")


def _evidence_excerpt(path: Path, evidence_id: str) -> str:
    marker = f"<!-- evidence-id: {evidence_id} -->"
    text = path.read_text(encoding="utf-8")
    section = text.partition(marker)[2].partition("<!-- evidence-id:")[0]
    lines = [line.strip() for line in section.splitlines() if line.strip()]
    return " ".join(re.sub(r"^#+\s*", "", line) for line in lines)[:800]


@router.post("/{revision_id}/analyze", response_model=RevisionResponse)
def analyze(
    revision_id: str,
    services: Annotated[AppServices, Depends(get_services)],
) -> RevisionResponse:
    return RevisionResponse.from_result(services.analysis.analyze_revision(revision_id))


@router.get("/{revision_id}/events")
def events(
    revision_id: str,
    services: Annotated[AppServices, Depends(get_services)],
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> StreamingResponse:
    try:
        after = int(last_event_id) if last_event_id is not None else 0
    except ValueError:
        after = 0
    services.repository.get_revision(revision_id)
    return stage_event_stream(
        services.repository.list_stage_events(revision_id),
        after_sequence=after,
    )


@router.get("/{revision_id}/review", response_model=ReviewResponse)
def review(
    revision_id: str,
    services: Annotated[AppServices, Depends(get_services)],
) -> ReviewResponse:
    result = services.analysis.get_result(revision_id)
    decisions = {decision.region_id: decision for decision in result.decisions}
    rules = {rule.id: rule for rule in services.analysis.policy_pack.rules}
    evidence_records = {record.id: record for record in services.analysis.policy_pack.evidence}
    cited_evidence = tuple(
        dict.fromkeys(
            evidence_id for decision in result.decisions for evidence_id in decision.evidence_ids
        )
    )
    artifacts = tuple(
        artifact
        for artifact in services.repository.list_artifacts(result.task.id)
        if artifact.revision_id == revision_id
        and artifact.namespace == FileNamespace.PREVIEWS.value
    )
    return ReviewResponse(
        revision_id=revision_id,
        task_id=result.task.id,
        file_kind=result.task.file_kind,
        regions=tuple(
            ReviewRegionResponse(
                region_id=region.id,
                location=region.location,
                order=region.order,
                category=region.category,
                source_text=region.text,
                output_preview=_output_preview(region, decisions[region.id]),
                action=decisions[region.id].action,
                rule_ids=decisions[region.id].rule_ids,
                rule_reasons=tuple(
                    rules[rule_id].reason for rule_id in decisions[region.id].rule_ids
                ),
                evidence_ids=decisions[region.id].evidence_ids,
                reason_code=decisions[region.id].reason_code,
                transform=decisions[region.id].transform,
            )
            for region in sorted(result.regions, key=lambda item: item.order)
            if region.id in decisions
        ),
        evidence=tuple(
            EvidenceRecordResponse(
                id=evidence_id,
                title=evidence_records[evidence_id].title,
                tags=evidence_records[evidence_id].tags,
                excerpt=_evidence_excerpt(
                    services.analysis.policy_pack.root / evidence_records[evidence_id].path,
                    evidence_id,
                ),
            )
            for evidence_id in cited_evidence
        ),
        preview_urls=tuple(
            f"/api/revisions/{revision_id}/previews/{index}"
            for index, _artifact in enumerate(artifacts)
        ),
    )


@router.get("/{revision_id}/previews/{preview_index}")
def preview(
    revision_id: str,
    preview_index: int,
    services: Annotated[AppServices, Depends(get_services)],
) -> Response:
    revision = services.repository.get_revision(revision_id)
    artifacts = tuple(
        artifact
        for artifact in services.repository.list_artifacts(revision.task_id)
        if artifact.revision_id == revision_id
        and artifact.namespace == FileNamespace.PREVIEWS.value
    )
    if preview_index < 0 or preview_index >= len(artifacts):
        raise KeyError(preview_index)
    storage_id = artifacts[preview_index].storage_id
    data = services.analysis.file_store.read(FileNamespace.PREVIEWS, storage_id)
    media_type = "image/png" if storage_id.endswith(".png") else "application/octet-stream"
    return Response(data, media_type=media_type)


@router.get("/{revision_id}/download")
def download(
    revision_id: str,
    services: Annotated[AppServices, Depends(get_services)],
    approval_id: Annotated[str | None, Query()] = None,
) -> Response:
    artifact = services.exports.business_file(revision_id, approval_id=approval_id)
    return Response(
        artifact.data,
        media_type=artifact.media_type,
        headers={"Content-Disposition": f'attachment; filename="{artifact.filename}"'},
    )


@router.get("/{revision_id}/evidence")
def evidence(
    revision_id: str,
    services: Annotated[AppServices, Depends(get_services)],
) -> Response:
    artifact = services.exports.evidence_file(revision_id)
    return Response(
        artifact.data,
        media_type=artifact.media_type,
        headers={"Content-Disposition": f'attachment; filename="{artifact.filename}"'},
    )
