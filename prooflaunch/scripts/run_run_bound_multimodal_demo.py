#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import http.client
import io
import json
import tempfile
import threading
import zipfile
from pathlib import Path
from typing import Any, Mapping

from prooflaunch_remix.files import atomic_write_bytes, atomic_write_text, sha256_file
from prooflaunch_remix.v10_submission_production_api import make_production_server
from prooflaunch_remix.v10_submission_runtime import AgencyRunWorker, ProductionAgencyService
from prooflaunch_remix.v10_submission_store import SubmissionStore


ROOT = Path(__file__).resolve().parents[1]
PACK_ROOT = ROOT / "evidence/v10/local-campaign-pack-v1/delivery-v6"
PACK_MANIFEST = PACK_ROOT / "campaign-pack-manifest.json"
QUALIFICATION = ROOT / "evidence/v10/local-multimodal-qualification.json"
SOURCE_METADATA = (
    ROOT
    / "evidence/v10/local-campaign-pack-v1"
    / "openai-imagegen-evidence-engine-challenger-v1.metadata.json"
)
DEFAULT_OUTPUT = ROOT / "artifacts/run-bound-multimodal-demo-v1"
TENANT_ID = "prooflaunch-demo-tenant"
TENANT_TOKEN = "prooflaunch-demo-tenant-token-000000000001"
APPROVAL_TOKEN = "prooflaunch-demo-approval-token-000000001"
APPROVER = "synthetic-control-plane-operator@prooflaunch.local"
MEMORY_SECRET = b"prooflaunch-demo-memory-secret-0000000000000001"


def _canonical_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _digest_payload(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def _load_verified_json(path: Path, *, schema: str) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != schema:
        raise RuntimeError(f"unexpected schema in {path}")
    unsigned = dict(payload)
    supplied = unsigned.pop("content_sha256", None)
    legacy_digest = hashlib.sha256(
        json.dumps(
            unsigned,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    if supplied != legacy_digest:
        raise RuntimeError(f"invalid content digest in {path}")
    return payload


def _request(
    host: str,
    port: int,
    method: str,
    path: str,
    *,
    body: bytes | None = None,
    content_type: str | None = None,
    approval: bool = False,
    idempotency_key: str | None = None,
) -> tuple[int, dict[str, str], bytes]:
    headers = {"Authorization": f"Bearer {TENANT_TOKEN}"}
    if body is not None:
        headers["Content-Length"] = str(len(body))
    if content_type:
        headers["Content-Type"] = content_type
    if approval:
        headers["X-ProofLaunch-Approval-Token"] = APPROVAL_TOKEN
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    connection = http.client.HTTPConnection(host, port, timeout=30)
    try:
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        response_body = response.read()
        return (
            response.status,
            {key.casefold(): value for key, value in response.getheaders()},
            response_body,
        )
    finally:
        connection.close()


def _json_request(
    host: str,
    port: int,
    method: str,
    path: str,
    payload: Mapping[str, Any],
    *,
    approval: bool = False,
    idempotency_key: str | None = None,
) -> tuple[int, dict[str, Any]]:
    status, _, body = _request(
        host,
        port,
        method,
        path,
        body=_canonical_bytes(payload),
        content_type="application/json",
        approval=approval,
        idempotency_key=idempotency_key,
    )
    decoded = json.loads(body.decode("utf-8"))
    if not isinstance(decoded, dict):
        raise RuntimeError(f"non-object response from {path}")
    return status, decoded


def _upload(host: str, port: int, path: Path, media_type: str) -> str:
    body = path.read_bytes()
    digest = hashlib.sha256(body).hexdigest()
    status, _, response = _request(
        host,
        port,
        "PUT",
        f"/v1/artifacts/{digest}",
        body=body,
        content_type=media_type,
    )
    if status != 201:
        raise RuntimeError(f"artifact upload failed ({status}): {response!r}")
    return digest


def _upload_json(host: str, port: int, payload: Mapping[str, Any]) -> str:
    body = _canonical_bytes(payload)
    digest = hashlib.sha256(body).hexdigest()
    status, _, response = _request(
        host,
        port,
        "PUT",
        f"/v1/artifacts/{digest}",
        body=body,
        content_type="application/json",
    )
    if status != 201:
        raise RuntimeError(f"JSON artifact upload failed ({status}): {response!r}")
    return digest


def _upload_bytes(
    host: str, port: int, body: bytes, media_type: str = "application/json"
) -> str:
    digest = hashlib.sha256(body).hexdigest()
    status, _, response = _request(
        host,
        port,
        "PUT",
        f"/v1/artifacts/{digest}",
        body=body,
        content_type=media_type,
    )
    if status != 201:
        raise RuntimeError(f"artifact upload failed ({status}): {response!r}")
    return digest


def _bundle_documents(host: str, port: int, run_id: str) -> dict[str, bytes]:
    status, _, body = _request(host, port, "GET", f"/v1/runs/{run_id}/bundle")
    if status != 200:
        raise RuntimeError(f"bundle retrieval failed ({status}): {body!r}")
    selected = (
        "brief-intelligence.json",
        "product-evidence-register.json",
        "creative-strategy-kernel.json",
        "editorial-quality-receipt.json",
        "multimodal-direction-receipt.json",
        "gtm-strategy.json",
        "big-idea-and-message-hierarchy.json",
        "content-calendar.json",
        "distribution-operations.json",
        "revenue-journey-operations.json",
        "mechanism-abstraction-register.json",
        "promotion-governance.json",
        "channel-copy.json",
        "landing-page-draft.json",
        "lifecycle-email-draft.json",
        "analytics-plan.json",
        "seo-geo-faq-drafts.json",
        "seo-geo-questions.json",
        "graph-loop-harness.json",
        "channel-portfolio.json",
        "approved-learning-context.json",
    )
    documents: dict[str, bytes] = {}
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        names = archive.namelist()
        for artifact_role in selected:
            matches = [name for name in names if Path(name).name == artifact_role]
            if len(matches) != 1:
                raise RuntimeError(
                    f"bundle must contain exactly one {artifact_role}; observed {matches}"
                )
            document = archive.read(matches[0])
            decoded = json.loads(document.decode("utf-8"))
            if not isinstance(decoded, dict):
                raise RuntimeError(f"bundle document is not an object: {artifact_role}")
            documents[artifact_role] = document
    return documents


def _artifact(manifest: Mapping[str, Any], name: str) -> dict[str, Any]:
    for item in manifest["artifacts"]:
        if item["path"] == name:
            path = (PACK_ROOT / name).resolve(strict=True)
            if sha256_file(path) != item["sha256"] or path.stat().st_size != item["bytes"]:
                raise RuntimeError(f"campaign artifact drift: {name}")
            return {**item, "absolute_path": str(path)}
    raise RuntimeError(f"campaign artifact missing: {name}")


def run_demo(output: Path) -> dict[str, Any]:
    manifest = _load_verified_json(PACK_MANIFEST, schema="ProofLaunchLocalCampaignPackV1")
    qualification = _load_verified_json(
        QUALIFICATION, schema="ProofLaunchLocalMultimodalQualificationV1"
    )
    source_metadata = json.loads(SOURCE_METADATA.read_text(encoding="utf-8"))
    campaign = manifest["campaign"]
    campaign_id = campaign["campaign_id"]
    hero = _artifact(manifest, "prooflaunch-hero-4k.png")
    audio = _artifact(manifest, "prooflaunch-audio-master-48k-stereo-24bit.wav")
    video = _artifact(manifest, "prooflaunch-campaign-film-4k.mp4")
    if qualification["execution"]["local_model_inference_observed"] is not True:
        raise RuntimeError("local multimodal inference receipt is missing")
    if manifest["quality_gates"]["mechanical_campaign_pack_ready"] is not True:
        raise RuntimeError("campaign pack mechanical gate is not ready")
    if source_metadata.get("rights", {}).get("locator") != campaign["rights_locator"]:
        raise RuntimeError("source metadata and campaign rights locator disagree")

    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="prooflaunch-run-bound-media-") as temporary:
        store = SubmissionStore(Path(temporary).resolve() / "store")
        worker = AgencyRunWorker(store)
        service = ProductionAgencyService(store, worker=worker)
        server = make_production_server(
            "127.0.0.1",
            0,
            service=service,
            web_root=ROOT / "web",
            approval_token=APPROVAL_TOKEN,
            approver_identity=APPROVER,
            tenant_tokens={TENANT_ID: TENANT_TOKEN},
            memory_capsule_secret=MEMORY_SECRET,
            product_readiness_path=ROOT / "evidence/v10/aug3-product-readiness.json",
            public_signal_pilot_path=(
                ROOT / "artifacts/public-signal-gtm-pilot-v1/pilot-receipt.json"
            ),
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        host, port = server.server_address
        try:
            hero_sha = _upload(host, port, Path(hero["absolute_path"]), "image/png")
            audio_sha = _upload(host, port, Path(audio["absolute_path"]), "audio/wav")
            video_sha = _upload(host, port, Path(video["absolute_path"]), "video/mp4")
            launch = {
                "request_id": "run-bound-multimodal-demo-v1",
                "campaign_id": campaign_id,
                "campaign": {
                    "product_name": "ProofLaunch",
                    "specification_text": (
                        "A governed GTM employee that binds evidence, generation, review, "
                        "activation and learning without automatic external release."
                    ),
                    "market": "Global",
                    "platform": "linkedin",
                    "goal": (
                        "Earn qualified design-partner conversations with a zero-paid-media, "
                        "evidence-first launch while preserving human release control."
                    ),
                    "target_emotion": "joy",
                },
                "input_artifacts": {"product_image": hero_sha},
                "rights": {
                    "confirmed": True,
                    "basis": "Project-generated source plus locally rendered campaign pack.",
                },
                "maximum_actions": 12,
                "maximum_cost_usd": 0,
                "human_release_required": True,
                "data_class": "synthetic",
                "strategy": {
                    "org_id": TENANT_ID,
                    "project_id": "cortex-x-run-bound-quality",
                    "owner": "ProofLaunch project operator",
                    "industry": "B2B AI software",
                    "business_model": "b2b",
                    "lifecycle": "launch",
                    "budget": "zero",
                    "industry_risk": "standard",
                    "audience_name": "GTM leaders and founder-led growth teams",
                    "audience_problem": (
                        "fragmented strategy, content, approval and measurement tools that "
                        "slow execution and obscure accountability"
                    ),
                    "audience_outcome": (
                        "one traceable path from a rights-bound brief to review-ready GTM "
                        "artifacts"
                    ),
                    "buying_context": (
                        "A design partner needs a demonstrable local-first workflow before "
                        "adopting an autonomous GTM employee"
                    ),
                    "brand_purpose": (
                        "Turn marketing claims into inspectable evidence and safe, useful action."
                    ),
                    "customer_promise": (
                        "A complete review-ready GTM operating pack without automatic publishing."
                    ),
                    "brand_voice": "specific, inventive, calm, evidence-first",
                    "offer": (
                        "review the end-to-end evidence pack and join the design-partner cohort"
                    ),
                    "landing_url": "https://example.invalid/prooflaunch-design-partner",
                    "schedule_timezone": "America/New_York",
                    "claim_assurance": "owner_attested",
                },
            }
            status, created = _json_request(
                host,
                port,
                "POST",
                "/v1/runs",
                launch,
                idempotency_key="run-bound-multimodal-demo-v1",
            )
            if status != 202:
                raise RuntimeError(f"run creation failed: {created}")
            run_id = created["run_id"]
            prepared = worker.process_one()
            if prepared.status != "awaiting_release":
                snapshot = service.snapshot(run_id)
                events = store.events_after(run_id)
                job_errors = []
                for event in events:
                    job_id = event.payload.get("job_id")
                    if isinstance(job_id, str):
                        job = store.get_job(job_id)
                        if job.error:
                            job_errors.append(job.error)
                raise RuntimeError(
                    "run did not reach the release boundary: "
                    f"worker={prepared!r}; snapshot={snapshot!r}; "
                    f"job_errors={job_errors!r}"
                )
            status, release = _json_request(
                host,
                port,
                "POST",
                f"/v1/runs/{run_id}/approvals",
                {
                    "decision": "approve",
                    "reason": (
                        "Synthetic control-plane exercise only; this is not a real human "
                        "quality or publication decision."
                    ),
                    "idempotency_key": "run-bound-multimodal-release-v1",
                },
                approval=True,
                idempotency_key="run-bound-multimodal-release-v1",
            )
            if status != 202 or worker.process_one().status != "bundle_ready":
                raise RuntimeError(f"run release failed: {release}")

            bundle_documents = _bundle_documents(host, port, run_id)
            capability_registrations: list[dict[str, Any]] = []
            capability_receipts: list[dict[str, Any]] = []
            artifact_roles = {
                "data_strategy": "gtm-strategy.json",
                "content_scheduling": "content-calendar.json",
                "text_generation": "channel-copy.json",
                "data_analysis": "analytics-plan.json",
                "geo_visibility": "seo-geo-faq-drafts.json",
                "seo_operations": "seo-geo-questions.json",
                "employee_agent": "graph-loop-harness.json",
                "advertising": "channel-portfolio.json",
            }
            for capability_id, artifact_role in artifact_roles.items():
                document = bundle_documents[artifact_role]
                artifact_sha = _upload_bytes(host, port, document)
                execution_receipt = {
                    "schema": "ProofLaunchCapabilityExecutionReceiptV1",
                    "campaign_id": campaign_id,
                    "capability_id": capability_id,
                    "artifact_role": artifact_role,
                    "artifact_sha256": artifact_sha,
                    "model_id": "prooflaunch/gtm-deterministic-compiler-v10",
                    "model_revision": "run-bound-bundle:" + run_id,
                    "accelerator": "deterministic_python_cpu",
                    "source_kind": "deterministic_compiler",
                    "executed_at": qualification["generated_at"],
                    "external_api_calls": 0,
                    "local_model_inference_observed": False,
                    "radeon_execution_observed": False,
                    "production_effect_proven": False,
                    "four_a_quality_proven": False,
                }
                receipt_sha = _upload_json(host, port, execution_receipt)
                registration_id = f"run-bound-{capability_id}-v1"
                status, registration = _json_request(
                    host,
                    port,
                    "POST",
                    f"/v1/runs/{run_id}/capability-deliverables",
                    {
                        "registration_id": registration_id,
                        "capability_id": capability_id,
                        "artifact_role": artifact_role,
                        "artifact_sha256": artifact_sha,
                        "execution_receipt_sha256": receipt_sha,
                        "campaign_id": campaign_id,
                        "rights_confirmed": True,
                        "rights_basis": "original_generated_from_owned_inputs",
                        "rights_locator": campaign["rights_locator"],
                    },
                    approval=True,
                    idempotency_key=registration_id,
                )
                if status != 201:
                    raise RuntimeError(
                        f"capability deliverable registration failed: {registration}"
                    )
                capability_receipts.append(execution_receipt)
                capability_registrations.append(registration)

            audio_execution = {
                "schema": "ProofLaunchMultimodalExecutionReceiptV1",
                "campaign_id": campaign_id,
                "capability_id": "audio_generation",
                "artifact_sha256": audio_sha,
                "model_id": "prooflaunch/qwen3-tts-plus-local-mix-v1",
                "model_revision": (
                    qualification["models"]["speech"]["revision"]
                    + "+pack:"
                    + manifest["content_sha256"]
                ),
                "accelerator": "apple_metal_plus_deterministic_ffmpeg_cpu",
                "source_kind": "local_model_inference",
                "executed_at": qualification["generated_at"],
                "external_api_calls": 0,
                "local_model_inference_observed": True,
                "radeon_execution_observed": False,
                "production_effect_proven": False,
                "four_a_quality_proven": False,
            }
            video_execution = {
                "schema": "ProofLaunchMultimodalExecutionReceiptV1",
                "campaign_id": campaign_id,
                "capability_id": "video_generation",
                "artifact_sha256": video_sha,
                "model_id": "prooflaunch/provider-image-local-compose-v6",
                "model_revision": "pack:" + manifest["content_sha256"],
                "accelerator": "provider_managed_plus_apple_metal_plus_ffmpeg_cpu",
                "source_kind": "provider_api_generation",
                "executed_at": source_metadata["created_at"],
                "external_api_calls": manifest["source_generation"]["cloud_api_calls"],
                "local_model_inference_observed": True,
                "radeon_execution_observed": False,
                "production_effect_proven": False,
                "four_a_quality_proven": False,
            }
            audio_receipt_sha = _upload_json(host, port, audio_execution)
            video_receipt_sha = _upload_json(host, port, video_execution)
            registration_responses: list[dict[str, Any]] = []
            for capability_id, artifact_sha, receipt_sha in (
                ("audio_generation", audio_sha, audio_receipt_sha),
                ("video_generation", video_sha, video_receipt_sha),
            ):
                registration_id = f"run-bound-{capability_id}-v1"
                status, registration = _json_request(
                    host,
                    port,
                    "POST",
                    f"/v1/runs/{run_id}/multimodal-deliverables",
                    {
                        "registration_id": registration_id,
                        "capability_id": capability_id,
                        "artifact_sha256": artifact_sha,
                        "execution_receipt_sha256": receipt_sha,
                        "campaign_id": campaign_id,
                        "rights_confirmed": True,
                        "rights_basis": "original_generated_from_owned_inputs",
                        "rights_locator": campaign["rights_locator"],
                    },
                    approval=True,
                    idempotency_key=registration_id,
                )
                if status != 201:
                    raise RuntimeError(f"multimodal registration failed: {registration}")
                registration_responses.append(registration)
            status, cockpit = _json_request(
                host, port, "GET", f"/v1/runs/{run_id}/gtm-cockpit", {}
            )
            if status != 200:
                raise RuntimeError(f"cockpit retrieval failed: {cockpit}")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    deliverable_root = output / "production-deliverables"
    deliverable_root.mkdir(parents=True, exist_ok=True)
    production_deliverables: list[dict[str, Any]] = []
    for artifact_role, document in sorted(bundle_documents.items()):
        target = deliverable_root / artifact_role
        atomic_write_bytes(target, document)
        production_deliverables.append(
            {
                "artifact_role": artifact_role,
                "path": str(target.relative_to(ROOT)),
                "media_type": "application/json",
                "bytes": len(document),
                "sha256": hashlib.sha256(document).hexdigest(),
            }
        )

    matrix = cockpit["capability_effect_matrix"]
    if (
        matrix["generated_deliverable_count"] != 10
        or matrix["named_human_quality_count"] != 0
        or matrix["production_effect_attributed_count"] != 0
        or cockpit["four_a_effect_claim_eligible"] is not False
    ):
        raise RuntimeError("run-bound multimodal cockpit truth boundary failed")
    audio_path = output / "audio-execution-receipt.json"
    video_path = output / "video-execution-receipt.json"
    cockpit_path = output / "gtm-cockpit.json"
    capability_receipts_path = output / "capability-execution-receipts.json"
    atomic_write_text(audio_path, json.dumps(audio_execution, indent=2, sort_keys=True) + "\n")
    atomic_write_text(video_path, json.dumps(video_execution, indent=2, sort_keys=True) + "\n")
    atomic_write_text(cockpit_path, json.dumps(cockpit, indent=2, sort_keys=True) + "\n")
    atomic_write_text(
        capability_receipts_path,
        json.dumps(capability_receipts, indent=2, sort_keys=True) + "\n",
    )
    receipt: dict[str, Any] = {
        "schema": "ProofLaunchRunBoundMultimodalDemoV1",
        "evidence_class": "mixed_real_artifacts_synthetic_control_plane",
        "campaign_id": campaign_id,
        "run_id": cockpit["run_id"],
        "run_status": cockpit["run_status"],
        "real_artifact_count": 3,
        "registered_multimodal_deliverable_count": 2,
        "registered_capability_deliverable_count": 8,
        "registered_run_bound_deliverable_count": 10,
        "persisted_production_document_count": len(production_deliverables),
        "named_human_quality_count": 0,
        "production_effect_attributed_count": 0,
        "artifacts": [
            {
                "role": role,
                "path": str(Path(item["absolute_path"]).relative_to(ROOT)),
                "media_type": item["media_type"],
                "bytes": item["bytes"],
                "sha256": item["sha256"],
            }
            for role, item in (("product_image", hero), ("audio_master", audio), ("video_master", video))
        ],
        "evidence_files": [
            {"path": str(path.relative_to(ROOT)), "sha256": sha256_file(path)}
            for path in (
                audio_path,
                video_path,
                capability_receipts_path,
                cockpit_path,
            )
        ],
        "multimodal_registrations": registration_responses,
        "capability_registrations": capability_registrations,
        "production_deliverables": production_deliverables,
        "source_execution": {
            "local_model_inference_observed": True,
            "provider_api_generation_observed": True,
            "provider_api_call_count": manifest["source_generation"]["cloud_api_calls"],
            "new_model_calls_executed_by_this_demo": 0,
            "new_downloads_executed_by_this_demo": 0,
            "radeon_execution_observed": False,
        },
        "authority_boundary": {
            "synthetic_control_plane_approval_used": True,
            "real_named_human_media_review_observed": False,
            "external_publish_executed": False,
            "automatic_publish_enabled": False,
            "automatic_spend_enabled": False,
            "production_effect_proven": False,
            "four_a_quality_proven": False,
            "top1_standing_proven": False,
        },
        "truth_boundary": (
            "The WAV and MP4 bytes, source receipts, hashes, campaign binding and API "
            "registrations are real. The control-plane approval is a synthetic mechanics "
            "exercise, not a named human quality judgment. Publication, production effect, "
            "4A preference, Top-1 standing and Radeon execution remain unproven."
        ),
    }
    receipt["content_sha256"] = _digest_payload(receipt)
    receipt_path = output / "demo-receipt.json"
    atomic_write_text(receipt_path, json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()
    output = Path(args.output).expanduser().resolve()
    try:
        output.relative_to(ROOT)
    except ValueError as error:
        raise SystemExit("--output must remain inside the project root") from error
    receipt = run_demo(output)
    print(
        json.dumps(
            {
                "output": str(output / "demo-receipt.json"),
                "run_id": receipt["run_id"],
                "generated_deliverables": receipt[
                    "registered_run_bound_deliverable_count"
                ],
                "human_quality": receipt["named_human_quality_count"],
                "production_effect": receipt["production_effect_attributed_count"],
                "content_sha256": receipt["content_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
