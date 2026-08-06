"""The frozen Shidu consumer HTTP surface."""

from __future__ import annotations

from collections.abc import Mapping
import math
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from creative_hub.artifact_proxy import (
    ArtifactGateway,
    ArtifactProxyError,
    FORWARDED_REQUEST_HEADERS,
)
from creative_hub.db.canonical import canonical_json_digest

from .competition_prepared_reference_backend import IMPORTED_REFERENCE_SHA256
from .h3_projection import (
    FLUX2_DEV_FP8_MIXED_CAPABILITY_V1,
    FluxCapabilityInput,
    H3ProjectionError,
    project_h3_product,
)
from .security import ArtifactTokenSigner
from .services import InvalidRequest, PUBLIC_JOB_STATES, ProjectionInvalid, ResourceNotFound, ShiduApiService


IdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=1, max_length=255),
]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class ResolveInputRequest(_StrictModel):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]

    @field_validator("title")
    @classmethod
    def title_must_not_be_a_url(cls, value: str) -> str:
        if (
            "://" in value
            or value.casefold().startswith("www.")
            or "|" in value
            or "\n" in value
            or "\r" in value
        ):
            raise ValueError("title must be plain text")
        return value


class SelectCandidateRequest(_StrictModel):
    candidate_id: UUID = Field(alias="candidateId")


class DirectorPreviewRequest(_StrictModel):
    book_id: UUID = Field(alias="bookId")
    direction_revision_id: UUID = Field(alias="directionRevisionId")
    custom_question: Annotated[str | None, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)] = Field(default=None, alias="customQuestion")


class VideoJobRequest(_StrictModel):
    book_id: UUID = Field(alias="bookId")
    direction_revision_id: UUID = Field(alias="directionRevisionId")
    trial_script_revision_id: UUID = Field(alias="trialScriptRevisionId")


class PreparedReferenceRequest(_StrictModel):
    book_id: UUID = Field(alias="bookId")
    direction_revision_id: UUID = Field(alias="directionRevisionId")
    trial_script_revision_id: UUID = Field(alias="trialScriptRevisionId")


class FeedbackRequest(_StrictModel):
    book_id: UUID = Field(alias="bookId")
    direction_revision_id: UUID = Field(alias="directionRevisionId")
    resonance_text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)] = Field(alias="resonanceText")
    job_id: Annotated[str | None, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)] = Field(default=None, alias="jobId")
    moment_revision_id: UUID | None = Field(default=None, alias="momentRevisionId")
    resonance_option_id: Annotated[str | None, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)] = Field(default=None, alias="resonanceOptionId")
    wants_to_read: bool | None = Field(default=None, alias="wantsToRead")
    spoiler_judgment: Literal["acceptable", "too_much", "none"] = Field(alias="spoilerJudgment")
    comment: Annotated[str | None, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)] = None


def _request_payload(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(mode="json", by_alias=True, exclude_none=True)


_GENERIC_RESONANCE_OPTIONS = (
    "我听见了人物当时的选择",
    "我更在意转折发生的原因",
    "我想带着自己的经历继续听",
)


def _payload_text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        text = value.get("text")
        if isinstance(text, str):
            return text.strip()
    return ""


def _text_items(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    output: list[str] = []
    for item in value:
        if isinstance(item, str):
            text = item.strip()
        elif isinstance(item, dict) and isinstance(item.get("text"), str):
            text = item["text"].strip()
        else:
            continue
        if text and text not in output:
            output.append(text)
    return output


def _public_direction(direction: dict[str, Any], ordinal: int) -> dict[str, Any]:
    payload = direction.get("payload")
    payload = payload if isinstance(payload, dict) else {}
    title = _payload_text(payload, "title") or f"阅读时刻 {ordinal:02d}"
    summary = (
        _payload_text(payload, "summary")
        or _payload_text(payload, "perceived_detail")
        or _payload_text(payload, "first_person_entry")
        or title
    )
    keywords = _text_items(payload.get("keywords"))
    if not keywords:
        keywords = [title, *_text_items(payload.get("fit_for"))]
    keywords = [f"{item[:11]}…" if len(item) > 12 else item for item in keywords[:3]]

    configured = payload.get("resonance_options")
    options: list[dict[str, str]] = []
    if isinstance(configured, list):
        for index, item in enumerate(configured):
            if isinstance(item, str):
                option_id, text = f"resonance-{index + 1}", item.strip()
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                option_id = str(item.get("id") or f"resonance-{index + 1}")
                text = item["text"].strip()
            else:
                continue
            if text and all(existing["text"] != text for existing in options):
                options.append({"id": option_id, "text": text})
    grounded = [
        _payload_text(payload, "first_person_entry"),
        _payload_text(payload, "perceived_detail"),
        *_text_items(payload.get("fit_for")),
        *_text_items(payload.get("factual_statements")),
    ]
    for text in [*grounded, *_GENERIC_RESONANCE_OPTIONS]:
        if text and all(existing["text"] != text for existing in options):
            options.append({"id": f"resonance-{len(options) + 1}", "text": text[:120]})
        if len(options) == 3:
            break
    return {
        **direction,
        "momentNumber": ordinal,
        "summary": summary,
        "keywords": keywords,
        "resonanceOptions": options[:3],
    }


def _public_book(book: dict[str, Any]) -> dict[str, Any]:
    directions = book.get("directions")
    projected = [
        _public_direction(item, index)
        for index, item in enumerate(directions if isinstance(directions, list) else [], start=1)
        if isinstance(item, dict)
    ]
    shelf_hook = projected[0]["summary"] if projected else "资料核验完成后，这里会出现可听的时刻。"
    return {**book, "directions": projected, "momentCount": len(projected), "shelfHook": shelf_hook}


def _public_prepared_reference(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProjectionInvalid()
    try:
        request_id = UUID(str(value["requestId"]))
        reference = value["reference"]
        if not isinstance(reference, dict):
            raise ValueError
        digests = (
            value["importAuthoritySha256"],
            value["fluxProofPromptSha256"],
            value["fluxProofTemplateWorkflowSha256"],
            reference["sha256"],
        )
        if (
            value["status"] != "prepared"
            or value["referenceProfile"]
            != "competition-imported-single-view-v1"
            or value["sourceMode"] != "preuploaded_imported"
            or value["requiredImages"] != 1
            or reference["viewName"] != "front_three_quarter"
            or reference["mimeType"]
            not in {"image/png", "image/jpeg", "image/webp"}
            or type(reference["width"]) is not int
            or type(reference["height"]) is not int
            or reference["width"] < 256
            or reference["height"] < 256
            or isinstance(value["fluxProofSeed"], bool)
            or not isinstance(value["fluxProofSeed"], int)
            or reference.get("importedBeforeUserClick") is not True
            or reference.get("generatedByCurrentFlux") is not False
            or any(
                not isinstance(item, str)
                or len(item) != 64
                or any(char not in "0123456789abcdef" for char in item)
                for item in digests
            )
        ):
            raise ValueError
    except (KeyError, TypeError, ValueError) as exc:
        raise ProjectionInvalid() from exc
    return {
        "referenceProfile": value["referenceProfile"],
        "sourceMode": value["sourceMode"],
        "requiredImages": 1,
        "status": "prepared",
        "label": "Prepared reference asset",
        "disclosureLabel": "Preuploaded imported asset",
        "requestId": str(request_id),
        "characterName": value["characterName"],
        "importAuthoritySha256": value["importAuthoritySha256"],
        "fluxProofPromptSha256": value["fluxProofPromptSha256"],
        "fluxProofSeed": value["fluxProofSeed"],
        "fluxProofTemplateWorkflowSha256": value[
            "fluxProofTemplateWorkflowSha256"
        ],
        "reference": {
            "artifactRef": f"prepared-reference:{request_id}",
            "imageUrl": f"/api/prepared-reference-assets/{request_id}/image",
            "sha256": reference["sha256"],
            "viewName": reference["viewName"],
            "mimeType": reference["mimeType"],
            "width": reference["width"],
            "height": reference["height"],
            "importedBeforeUserClick": True,
            "generatedByCurrentFlux": False,
        },
    }


def _public_job(
    payload: dict[str, Any],
    signer: ArtifactTokenSigner,
    *,
    expected_project_id: UUID,
    flux_capability: FluxCapabilityInput,
) -> dict[str, Any]:
    status = payload.get("status")
    if status not in PUBLIC_JOB_STATES:
        raise ProjectionInvalid()
    public = {
        key: payload[key]
        for key in (
            "jobId",
            "bookId",
            "status",
            "progress",
            "error",
            "contentMode",
            "contentLabel",
            "contentNotice",
        )
        if key in payload
    }
    disclosure_keys = {"contentMode", "contentLabel", "contentNotice"}
    present_disclosure = disclosure_keys.intersection(payload)
    if present_disclosure:
        if present_disclosure != disclosure_keys:
            raise ProjectionInvalid()
        if payload["contentMode"] not in {"source_grounded", "ai_completed"}:
            raise ProjectionInvalid()
        if not all(
            isinstance(payload[key], str) and payload[key].strip()
            for key in disclosure_keys
        ):
            raise ProjectionInvalid()
        if (
            payload["contentMode"] == "ai_completed"
            and "非原文"
            not in f"{payload['contentLabel']}{payload['contentNotice']}"
        ):
            raise ProjectionInvalid()
    preview = payload.get("competitionCharacterReference")
    if preview is not None:
        expected_preview_fields = {
            "schemaVersion",
            "jobAuthorityDigest",
            "referenceProfile",
            "sourceMode",
            "requiredImages",
            "viewName",
            "owner",
            "artifactId",
            "artifactSha256",
            "promptSha256",
            "seed",
            "workflowSha256",
            "compiledWorkflowSha256",
            "generationAttemptOrdinal",
            "technicalFailureReceiptSha256",
            "mimeType",
            "width",
            "height",
            "label",
            "referenceDigest",
            "generatedByCurrentFlux",
            "fluxOutputUsed",
            "importAuthoritySha256",
            "fluxProofPromptId",
            "fluxProofQueueId",
        }
        if not isinstance(preview, dict) or set(preview) != expected_preview_fields:
            raise ProjectionInvalid()
        identity = dict(preview)
        claimed_digest = identity.pop("referenceDigest")
        attempt = preview.get("generationAttemptOrdinal")
        failure_receipt = preview.get("technicalFailureReceiptSha256")
        digests = (
            preview.get("jobAuthorityDigest"),
            preview.get("artifactSha256"),
            preview.get("promptSha256"),
            preview.get("workflowSha256"),
            preview.get("compiledWorkflowSha256"),
            preview.get("importAuthoritySha256"),
        )
        if (
            preview.get("schemaVersion")
            != "amd.competition-imported-reference-preview.v1"
            or preview.get("referenceProfile")
            != "competition-imported-single-view-v1"
            or preview.get("sourceMode") != "preuploaded_imported"
            or preview.get("requiredImages") != 1
            or preview.get("viewName") != "front_three_quarter"
            or preview.get("owner") != "drama_factory"
            or preview.get("label") != "Preuploaded imported asset"
            or preview.get("generatedByCurrentFlux") is not False
            or preview.get("fluxOutputUsed") is not False
            or type(preview.get("fluxProofPromptId")) is not str
            or not preview["fluxProofPromptId"]
            or isinstance(preview.get("fluxProofQueueId"), bool)
            or type(preview.get("fluxProofQueueId")) is not int
            or preview["fluxProofQueueId"] < 0
            or preview.get("mimeType")
            not in {"image/png", "image/jpeg", "image/webp"}
            or type(preview.get("width")) is not int
            or type(preview.get("height")) is not int
            or preview["width"] < 256
            or preview["height"] < 256
            or isinstance(preview.get("seed"), bool)
            or not isinstance(preview.get("seed"), int)
            or type(attempt) is not int
            or attempt not in {0, 1}
            or (attempt == 0 and failure_receipt is not None)
            or (
                attempt == 1
                and (
                    not isinstance(failure_receipt, str)
                    or len(failure_receipt) != 64
                )
            )
            or any(
                not isinstance(value, str)
                or len(value) != 64
                or any(char not in "0123456789abcdef" for char in value)
                for value in digests
            )
            or claimed_digest != canonical_json_digest(identity)
        ):
            raise ProjectionInvalid()
        try:
            token = signer.issue(
                owner=preview["owner"],
                artifact_id=UUID(str(preview["artifactId"])),
                purpose="reference",
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ProjectionInvalid() from exc
        public["characterReference"] = {
            "referenceProfile": preview["referenceProfile"],
            "sourceMode": preview["sourceMode"],
            "requiredImages": 1,
            "reference": {
                "viewName": preview["viewName"],
                "imageUrl": f"/artifacts/{token}",
                "sha256": preview["artifactSha256"],
                "mimeType": preview["mimeType"],
                "width": preview["width"],
                "height": preview["height"],
            },
            "label": preview["label"],
            "generatedByCurrentFlux": False,
            "fluxOutputUsed": False,
        }
    runtime_proof = payload.get("_h3RuntimeProof")
    if runtime_proof is not None:
        if (
            status != "rendering"
            or not isinstance(runtime_proof, dict)
            or set(runtime_proof)
            != {
                "phase",
                "promptId",
                "queueId",
                "submissionNonce",
                "workflowSha256",
                "gpuActivityObserved",
                "processExited",
                "referenceSha256",
                "referenceSourceMode",
            }
            or runtime_proof.get("phase") not in {"flux", "h3"}
            or type(runtime_proof.get("promptId")) is not str
            or not 1 <= len(runtime_proof["promptId"]) <= 200
            or type(runtime_proof.get("submissionNonce")) is not str
            or len(runtime_proof["submissionNonce"]) != 32
            or any(
                char not in "0123456789abcdef"
                for char in runtime_proof["submissionNonce"]
            )
            or isinstance(runtime_proof.get("queueId"), bool)
            or type(runtime_proof.get("queueId")) is not int
            or runtime_proof["queueId"] < 0
            or type(runtime_proof.get("gpuActivityObserved")) is not bool
            or type(runtime_proof.get("processExited")) is not bool
            or runtime_proof.get("referenceSourceMode")
            != "preuploaded_imported"
            or (
                runtime_proof.get("referenceSha256") is not None
                and (
                    type(runtime_proof["referenceSha256"]) is not str
                    or len(runtime_proof["referenceSha256"]) != 64
                    or any(
                        char not in "0123456789abcdef"
                        for char in runtime_proof["referenceSha256"]
                    )
                )
            )
            or type(runtime_proof.get("workflowSha256")) is not str
            or len(runtime_proof["workflowSha256"]) != 64
            or any(
                char not in "0123456789abcdef"
                for char in runtime_proof["workflowSha256"]
            )
        ):
            raise ProjectionInvalid()
        if runtime_proof["phase"] == "flux":
            if runtime_proof["referenceSha256"] is not None:
                raise ProjectionInvalid()
        else:
            character_reference = public.get("characterReference")
            if (
                runtime_proof["referenceSha256"]
                != IMPORTED_REFERENCE_SHA256
                or not isinstance(character_reference, dict)
                or not isinstance(character_reference.get("reference"), dict)
                or character_reference["reference"].get("sha256")
                != runtime_proof["referenceSha256"]
                or character_reference.get("sourceMode")
                != "preuploaded_imported"
                or character_reference.get("generatedByCurrentFlux") is not False
                or character_reference.get("fluxOutputUsed") is not False
            ):
                raise ProjectionInvalid()
        public["gpuRuntimeProof"] = dict(runtime_proof)
    h3_envelope = payload.get("_h3Projection")
    if status != "succeeded":
        if h3_envelope is not None:
            raise ProjectionInvalid()
        return public
    if h3_envelope is not None:
        if "artifactRefs" in payload or not isinstance(h3_envelope, dict):
            raise ProjectionInvalid()
        if set(h3_envelope) != {"authority", "delivery_record", "asset_refs"}:
            raise ProjectionInvalid()
        authority = h3_envelope["authority"]
        delivery_record = h3_envelope["delivery_record"]
        asset_refs = h3_envelope["asset_refs"]
        if (
            not isinstance(authority, Mapping)
            or not isinstance(delivery_record, Mapping)
            or not isinstance(asset_refs, Mapping)
        ):
            raise ProjectionInvalid()

        def load_delivery_record(
            delivery_record_id: str,
            project_id: str,
        ) -> Mapping[str, Any]:
            if (
                delivery_record_id != delivery_record.get("delivery_record_id")
                or project_id != delivery_record.get("project_id")
            ):
                raise ValueError("delivery record scope mismatch")
            return delivery_record

        def resolve_asset(asset_id: str) -> str:
            ref = asset_refs.get(asset_id)
            if not isinstance(ref, Mapping) or set(ref) != {
                "owner",
                "artifact_id",
                "purpose",
            }:
                raise ValueError("H3 asset authority is unavailable")
            if str(ref.get("artifact_id")) != asset_id:
                raise ValueError("H3 asset authority identity mismatch")
            token = signer.issue(
                owner=ref.get("owner"),
                artifact_id=UUID(asset_id),
                purpose=ref.get("purpose"),
            )
            return f"/artifacts/{token}"

        try:
            h3_product = project_h3_product(
                authority,
                expected_project_id=str(expected_project_id),
                delivery_record_id=str(
                    delivery_record.get("delivery_record_id", "")
                ),
                delivery_record_loader=load_delivery_record,
                asset_url_resolver=resolve_asset,
                flux_capability=flux_capability,
            )
        except (H3ProjectionError, TypeError, ValueError) as exc:
            raise ProjectionInvalid() from exc
        disclosure = h3_product["disclosure"]
        expected_disclosure = {
            "contentMode": disclosure["contentMode"],
            "contentLabel": disclosure["label"],
            "contentNotice": disclosure["notice"],
        }
        if any(public.get(key) != value for key, value in expected_disclosure.items()):
            raise ProjectionInvalid()
        public["h3Product"] = h3_product
        return public
    competition_ref = payload.get("competitionVerticalSliceRef")
    if competition_ref is not None:
        expected_keys = {
            "owner",
            "artifactId",
            "requestedDurationSeconds",
            "frameCount",
            "fps",
            "nativeAudio",
            "subtitles",
            "actualDurationSeconds",
            "actualFrameCount",
            "actualFps",
            "mediaWarnings",
        }
        actual_duration = (
            competition_ref.get("actualDurationSeconds")
            if isinstance(competition_ref, dict)
            else None
        )
        actual_frames = (
            competition_ref.get("actualFrameCount")
            if isinstance(competition_ref, dict)
            else None
        )
        actual_fps = (
            competition_ref.get("actualFps")
            if isinstance(competition_ref, dict)
            else None
        )
        expected_warnings: list[str] = []
        if type(actual_frames) is int and actual_frames != 73:
            expected_warnings.append(
                "ACTUAL_FRAME_COUNT_DEVIATES_FROM_REQUESTED_73"
            )
        if (
            isinstance(actual_fps, (int, float))
            and not isinstance(actual_fps, bool)
            and not math.isclose(float(actual_fps), 24.0, rel_tol=0.0, abs_tol=0.01)
        ):
            expected_warnings.append("ACTUAL_FPS_DEVIATES_FROM_REQUESTED_24")
        if (
            isinstance(actual_duration, (int, float))
            and not isinstance(actual_duration, bool)
            and not math.isclose(
                float(actual_duration), 73 / 24, rel_tol=0.0, abs_tol=0.25
            )
        ):
            expected_warnings.append(
                "ACTUAL_DURATION_DEVIATES_FROM_EXPECTED_73_OVER_24"
            )
        if (
            "artifactRefs" in payload
            or not isinstance(competition_ref, dict)
            or set(competition_ref) != expected_keys
            or competition_ref.get("owner") != "drama_factory"
            or competition_ref.get("requestedDurationSeconds") != 3.0
            or competition_ref.get("frameCount") != 73
            or competition_ref.get("fps") != 24
            or competition_ref.get("nativeAudio") is not True
            or competition_ref.get("subtitles") is not False
            or isinstance(actual_duration, bool)
            or not isinstance(actual_duration, (int, float))
            or not 2.8 <= float(actual_duration) <= 3.5
            or type(actual_frames) is not int
            or not 65 <= actual_frames <= 90
            or isinstance(actual_fps, bool)
            or not isinstance(actual_fps, (int, float))
            or not 20.0 <= float(actual_fps) <= 30.0
            or not math.isclose(
                actual_frames / float(actual_fps),
                float(actual_duration),
                rel_tol=0.0,
                abs_tol=0.35,
            )
            or competition_ref.get("mediaWarnings") != expected_warnings
        ):
            raise ProjectionInvalid()
        try:
            token = signer.issue(
                owner=competition_ref["owner"],
                artifact_id=UUID(str(competition_ref["artifactId"])),
                purpose="video",
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ProjectionInvalid() from exc
        public["artifacts"] = {"video": f"/artifacts/{token}"}
        return public
    refs = payload.get("artifactRefs")
    if not isinstance(refs, dict) or set(refs) != {"video", "subtitle", "cover", "shareCard"}:
        raise ProjectionInvalid()
    purposes = {
        "video": "video",
        "subtitle": "subtitle",
        "cover": "cover",
        "shareCard": "share_card",
    }
    urls: dict[str, str] = {}
    try:
        for key, purpose in purposes.items():
            ref = refs[key]
            if not isinstance(ref, dict) or set(ref) != {"owner", "artifactId"}:
                raise ValueError("invalid artifact ref")
            token = signer.issue(
                owner=ref["owner"],
                artifact_id=UUID(str(ref["artifactId"])),
                purpose=purpose,
            )
            urls[key] = f"/artifacts/{token}"
    except (KeyError, TypeError, ValueError) as exc:
        raise ProjectionInvalid() from exc
    public["artifacts"] = urls
    return public


def create_public_router(
    *,
    service: ShiduApiService,
    signer: ArtifactTokenSigner,
    project_id: UUID,
    flux_capability: FluxCapabilityInput | None = None,
) -> APIRouter:
    router = APIRouter()
    h3_flux_capability = (
        FLUX2_DEV_FP8_MIXED_CAPABILITY_V1
        if flux_capability is None
        else flux_capability
    )

    @router.post("/api/resolve-input")
    def resolve_input(body: ResolveInputRequest, idempotency_key: IdempotencyKey):
        return service.resolve_input(
            project_id=project_id,
            raw_input=body.title,
            idempotency_key=idempotency_key,
        )

    @router.post("/api/resolve-input/{resolutionId}/select")
    def select_candidate(
        resolutionId: UUID,
        body: SelectCandidateRequest,
        idempotency_key: IdempotencyKey,
    ):
        return service.select_candidate(
            project_id=project_id,
            resolution_id=resolutionId,
            candidate_id=body.candidate_id,
            idempotency_key=idempotency_key,
        )

    @router.get("/api/books")
    def books(request: Request):
        if request.query_params:
            raise InvalidRequest()
        return {"books": [_public_book(book) for book in service.list_books(project_id=project_id, query="")]}

    @router.get("/api/shelf")
    def shelf(request: Request):
        if request.query_params:
            raise InvalidRequest()
        books = [_public_book(book) for book in service.list_books(project_id=project_id, query="")]
        return {"books": [book for book in books if book.get("researchStatus") == "ready" and book["momentCount"] > 0][:12]}

    @router.get("/api/books/{bookId}")
    def book(bookId: UUID):
        books = service.list_books(project_id=project_id, query="")
        for item in books:
            if str(item.get("id")) == str(bookId):
                return {"book": _public_book(item)}
        raise ResourceNotFound()

    @router.post("/api/books/{bookId}/research")
    def retry_research(bookId: UUID, idempotency_key: IdempotencyKey):
        return service.retry_research(
            project_id=project_id,
            book_id=bookId,
            idempotency_key=idempotency_key,
        )

    @router.post("/api/director-preview")
    def director_preview(body: DirectorPreviewRequest, idempotency_key: IdempotencyKey):
        result = service.director_preview(
            project_id=project_id,
            request=_request_payload(body),
            idempotency_key=idempotency_key,
        )
        lookup = getattr(service, "get_competition_prepared_reference", None)
        prepared = None if not callable(lookup) else lookup(
            project_id=project_id,
            request={
                "bookId": str(body.book_id),
                "directionRevisionId": str(body.direction_revision_id),
                "trialScriptRevisionId": result["scriptRevisionId"],
            },
        )
        if prepared is not None:
            result = {**result, "characterReference": _public_prepared_reference(prepared)}
        return result

    @router.post("/api/prepared-reference-assets")
    def prepare_reference(
        body: PreparedReferenceRequest, idempotency_key: IdempotencyKey
    ):
        prepared = service.prepare_competition_reference(
            project_id=project_id,
            request=_request_payload(body),
            idempotency_key=idempotency_key,
        )
        return {"characterReference": _public_prepared_reference(prepared)}

    @router.get("/api/prepared-reference-assets/{requestId}/image")
    def prepared_reference_image(requestId: UUID):
        body, mime_type, sha256 = service.get_competition_prepared_reference_image(
            project_id=project_id,
            request_id=requestId,
        )
        return Response(
            content=body,
            media_type=mime_type,
            headers={
                "Cache-Control": "private, max-age=300, immutable",
                "ETag": f'"sha256-{sha256}"',
                "X-Content-Type-Options": "nosniff",
            },
        )

    @router.post("/api/video-jobs", status_code=202)
    def create_video_job(body: VideoJobRequest, idempotency_key: IdempotencyKey):
        payload = service.create_video_job(
            project_id=project_id,
            request=_request_payload(body),
            idempotency_key=idempotency_key,
        )
        return _public_job(
            payload,
            signer,
            expected_project_id=project_id,
            flux_capability=h3_flux_capability,
        )

    @router.get("/api/video-jobs/{id}")
    def get_video_job(id: Annotated[str, StringConstraints(min_length=1, max_length=200)]):
        return _public_job(
            service.get_video_job(project_id=project_id, job_id=id),
            signer,
            expected_project_id=project_id,
            flux_capability=h3_flux_capability,
        )

    @router.post("/api/feedback")
    def feedback(body: FeedbackRequest, idempotency_key: IdempotencyKey):
        return service.add_feedback(
            project_id=project_id,
            request=_request_payload(body),
            idempotency_key=idempotency_key,
        )

    return router


def create_artifact_router(
    *, signer: ArtifactTokenSigner, gateway: ArtifactGateway
) -> APIRouter:
    router = APIRouter()

    @router.api_route(
        "/artifacts/{token}",
        methods=["GET", "HEAD"],
        include_in_schema=False,
    )
    def artifact(token: str, request: Request) -> Response:
        try:
            signed = signer.verify(token)
        except ValueError:
            return JSONResponse(
                status_code=403,
                content={
                    "error_code": "artifact_token_invalid",
                    "message": "下载链接无效或已过期",
                    "retryable": False,
                },
            )
        headers = {
            name: value
            for name in FORWARDED_REQUEST_HEADERS
            if (value := request.headers.get(name)) is not None
        }
        try:
            remote = gateway.open(
                signed.owner,
                signed.artifact_id,
                method=request.method,
                headers=headers,
            )
        except ArtifactProxyError as exc:
            return JSONResponse(
                status_code=exc.status_code,
                content={
                    "error_code": "artifact_unavailable",
                    "message": "交付文件暂不可用",
                    "retryable": exc.status_code >= 500,
                },
            )
        if remote.status_code not in {200, 206}:
            return Response(status_code=remote.status_code, headers=remote.headers)
        if request.method == "HEAD":
            return Response(status_code=remote.status_code, headers=remote.headers)
        if remote.body is None:
            return JSONResponse(
                status_code=502,
                content={
                    "error_code": "artifact_unavailable",
                    "message": "交付文件暂不可用",
                    "retryable": True,
                },
            )
        return StreamingResponse(
            remote.body,
            status_code=remote.status_code,
            headers=remote.headers,
            media_type=None,
        )

    return router


__all__ = ["create_artifact_router", "create_public_router"]
