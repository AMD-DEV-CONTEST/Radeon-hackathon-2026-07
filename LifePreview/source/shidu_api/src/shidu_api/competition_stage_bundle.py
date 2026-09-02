"""Concrete seven-stage production bridge for the AMD competition slice.

The daemon imports this factory lazily only after the user's POST has produced
an eligible deferred row and the coordinator has persisted its ``clicked``
checkpoint.  Importing this module is CPU-only.  FLUX and H3 are invoked only
inside their two named stage functions through the crash-safe staged runner.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from creative_hub.artifact_publication import (
    ArtifactPublicationService,
    ContentAddressedArtifactStore,
    PostgresArtifactRepository,
)
from creative_hub.db.canonical import canonical_json_digest
from creative_hub.shidu.repository import ShiduRepository
from shared_contracts import AtomicArtifactRef

from .competition_prompt_reference import (
    CompetitionPromptReferenceError,
    REFERENCE_PROFILE,
    REFERENCE_REMOTE_NAME,
    REFERENCE_ROLE,
    REFERENCE_VIEW,
    SOURCE_MODE,
    build_competition_prompt_authority,
    validate_competition_reference_image,
    validate_imported_competition_reference_image,
)
from .competition_runtime_wiring import create_runner
from .competition_vertical_slice import publish_competition_vertical_slice
from .competition_vertical_slice_daemon import (
    CompetitionDaemonContext,
    ProductionStageFunctions,
    StageInvocation,
)
from .competition_vertical_slice_worker import (
    CoordinatorContractError,
    RetryableWorkerStepError,
    StageReceipt,
    TerminalWorkerStepError,
)
from .competition_visual_identity_runtime import (
    PostgresVisualPreparationAttemptSource,
)
from .deployment import (
    JsonFileH3PersistedAuthorityStore,
    create_service,
)
from .services import DependencyUnavailable, InvalidRequest
from .visual_identity_preparation import ArtifactPublicationServiceAdapter, ShiduRepositorySnapshotSource


_VIDEO_CONTRACT = {
    "requestedDurationSeconds": 3.0,
    "frameCount": 73,
    "fps": 24,
    "nativeAudio": True,
    "subtitles": False,
}


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _is_sha256(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    # Preserve deliberately canonical view order in nested prompt maps.  Every
    # embedded authority still carries its own order-independent canonical
    # digest; the outer file is bound by its exact byte SHA in the click row.
    return json.dumps(
        dict(value),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=False,
        separators=(",", ":"),
    ).encode("utf-8")


def _append_only_json(path: Path, value: Mapping[str, Any]) -> str:
    body = _canonical_bytes(value)
    digest = _sha256_bytes(body)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.is_symlink() or path.read_bytes() != body:
            raise CoordinatorContractError("persistent stage authority conflicts")
        return digest
    temporary = path.with_name(f".{path.name}.{os.getpid()}.partial")
    try:
        with temporary.open("xb") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.read_bytes() != body:
                raise CoordinatorContractError("persistent stage authority conflicts")
    finally:
        temporary.unlink(missing_ok=True)
    return digest


def _payload(**values: Any) -> dict[str, Any]:
    identity = dict(values)
    return {**identity, "outputDigest": canonical_json_digest(identity)}


def _receipt(
    invocation: StageInvocation, stage: str
) -> Mapping[str, Any]:
    for receipt in invocation.prior_receipts:
        if receipt.stage == stage:
            return receipt.payload
    raise CoordinatorContractError(f"{invocation.stage} lacks {stage} receipt")


def _strict_path(value: object, root: Path, label: str) -> Path:
    if type(value) is not str:
        raise CoordinatorContractError(f"{label} path is invalid")
    try:
        path = Path(value).resolve(strict=True)
        path.relative_to(root.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise CoordinatorContractError(f"{label} path is unavailable") from exc
    if path.is_symlink() or not path.is_file():
        raise CoordinatorContractError(f"{label} path is unsafe")
    return path


class CompetitionProductionStages:
    """State transforms shared by the real factory and deterministic tests."""

    def __init__(
        self,
        *,
        context: CompetitionDaemonContext,
        preparer_opener: Callable[[], Any],
        snapshot_loader: Callable[[Any], Any],
        runner_factory: Callable[[Any], Any],
        reference_qc: Callable[[Any, tuple[Any, ...]], tuple[str, ...]],
        visual_publisher: ArtifactPublicationServiceAdapter,
        visual_attempts: PostgresVisualPreparationAttemptSource,
        authority_store: JsonFileH3PersistedAuthorityStore,
        artifact_store: ContentAddressedArtifactStore,
        api_service: Any,
        flux_manifest: Path,
        flux_workflow_root: Path,
        h3_capability_manifest: Path,
        h3_template: Path,
        prepared_reference_loader: Callable[[Mapping[str, Any]], Mapping[str, Any] | None] | None = None,
        cleanup_after_delivery: Callable[[], None] | None = None,
    ) -> None:
        self.context = context
        self.preparer_opener = preparer_opener
        self.snapshot_loader = snapshot_loader
        self.runner_factory = runner_factory
        self.reference_qc = reference_qc
        self.visual_publisher = visual_publisher
        self.visual_attempts = visual_attempts
        self.authority_store = authority_store
        self.artifact_store = artifact_store
        self.api_service = api_service
        self.flux_manifest = Path(flux_manifest)
        self.flux_workflow_root = Path(flux_workflow_root)
        self.h3_capability_manifest = Path(h3_capability_manifest)
        self.h3_template = Path(h3_template)
        self.prepared_reference_loader = prepared_reference_loader
        self.cleanup_after_delivery = cleanup_after_delivery

    def functions(self) -> ProductionStageFunctions:
        return ProductionStageFunctions(
            source_prepared=self.source_prepared,
            flux_generated=self.flux_generated,
            references_published=self.references_published,
            authority_finalized=self.authority_finalized,
            workflow_materialized=self.workflow_materialized,
            h3_generated=self.h3_generated,
            delivered=self.delivered,
        )

    def _job_root(self, invocation: StageInvocation) -> Path:
        root = (
            self.context.persistent_root
            / "vertical-slice"
            / "jobs"
            / invocation.job.authority_digest
        )
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _runner_arguments(self, invocation: StageInvocation) -> SimpleNamespace:
        root = self._job_root(invocation)
        return SimpleNamespace(
            persistent_root=self.context.persistent_root,
            click_authority=root / "user-click.json",
            checkpoint=root / "runner-checkpoint.json",
            evidence_root=root / "runner-evidence",
            output=root / "result" / "vertical-slice.mp4",
            flux_manifest=self.flux_manifest,
            flux_workflow_root=self.flux_workflow_root,
            h3_manifest=root / "h3-execution-authority.json",
            h3_template=self.h3_template,
        )

    def source_prepared(self, invocation: StageInvocation) -> Mapping[str, Any]:
        try:
            snapshot = self.snapshot_loader(invocation.job)
            prompt_authority = build_competition_prompt_authority(
                snapshot=snapshot,
                job_authority_digest=invocation.job.authority_digest,
                flux_manifest=self.flux_manifest,
            )
        except CompetitionPromptReferenceError as exc:
            raise TerminalWorkerStepError(
                "source_prepared", "PROMPT_REFERENCE_AUTHORITY_INVALID"
            ) from exc
        except Exception as exc:
            raise RetryableWorkerStepError(
                "source_prepared", "PROMPT_SNAPSHOT_UNAVAILABLE"
            ) from exc
        return _payload(
            schemaVersion="amd.competition-prompt-source-stage.v1",
            referenceProfile=REFERENCE_PROFILE,
            sourceMode=SOURCE_MODE,
            requiredImages=1,
            view=REFERENCE_VIEW,
            promptAuthority=prompt_authority,
        )

    @staticmethod
    def _prompt_authority(invocation: StageInvocation) -> Mapping[str, Any]:
        source = _receipt(invocation, "source_prepared")
        authority = source.get("promptAuthority")
        if (
            source.get("referenceProfile") != REFERENCE_PROFILE
            or source.get("sourceMode") != SOURCE_MODE
            or source.get("requiredImages") != 1
            or source.get("view") != REFERENCE_VIEW
            or type(authority) is not dict
        ):
            raise CoordinatorContractError("prompt source receipt is invalid")
        identity = dict(authority)
        claimed = identity.pop("authoritySha256", None)
        if (
            set(authority)
            != {
                "schemaVersion",
                "referenceProfile",
                "sourceMode",
                "requiredImages",
                "view",
                "characterName",
                "ageStage",
                "historicalContext",
                "bookIdentitySha256",
                "directionSha256",
                "trialScriptSha256",
                "researchSha256",
                "evidencePackSha256",
                "safetyReleaseDecisionSha256",
                "visualPrompt",
                "promptSha256",
                "h3Prompt",
                "h3PromptSha256",
                "seed",
                "workflowSha256",
                "generationInvocationCount",
                "technicalRetryLimit",
                "authoritySha256",
            }
            or authority.get("schemaVersion")
            != "amd.competition-prompt-reference-authority.v1"
            or authority.get("referenceProfile") != REFERENCE_PROFILE
            or authority.get("sourceMode") != SOURCE_MODE
            or authority.get("requiredImages") != 1
            or authority.get("view") != REFERENCE_VIEW
            or authority.get("generationInvocationCount") != 1
            or authority.get("technicalRetryLimit") != 1
            or type(authority.get("visualPrompt")) is not str
            or not authority["visualPrompt"].strip()
            or hashlib.sha256(authority["visualPrompt"].encode("utf-8")).hexdigest()
            != authority.get("promptSha256")
            or type(authority.get("h3Prompt")) is not str
            or not authority["h3Prompt"].strip()
            or hashlib.sha256(authority["h3Prompt"].encode("utf-8")).hexdigest()
            != authority.get("h3PromptSha256")
            or any(
                not _is_sha256(authority.get(name))
                for name in (
                    "bookIdentitySha256",
                    "directionSha256",
                    "trialScriptSha256",
                    "researchSha256",
                    "evidencePackSha256",
                    "safetyReleaseDecisionSha256",
                )
            )
            or not _is_sha256(authority.get("workflowSha256"))
            or isinstance(authority.get("seed"), bool)
            or not isinstance(authority.get("seed"), int)
            or not 0 <= authority["seed"] < 2**64
            or claimed != canonical_json_digest(identity)
        ):
            raise CoordinatorContractError("prompt authority digest is invalid")
        return authority

    def _ensure_click_authority(self, invocation: StageInvocation) -> None:
        prompt = self._prompt_authority(invocation)
        root = self._job_root(invocation)
        logical_prompt = uuid5(
            NAMESPACE_URL,
            f"amd-three-second-prompt:{invocation.job.authority_digest}",
        )
        nonce = hashlib.sha256(
            f"amd-three-second-nonce:{invocation.job.authority_digest}".encode()
        ).hexdigest()[:32]
        generation_identity = {
            "schemaVersion": "amd.flux-prompt-single-reference-generation.v1",
            "referenceProfile": REFERENCE_PROFILE,
            "sourceMode": SOURCE_MODE,
            "requiredImages": 1,
            "view": REFERENCE_VIEW,
            "prompt": prompt["visualPrompt"],
            "promptSha256": prompt["promptSha256"],
            "seed": prompt["seed"],
            "workflowSha256": prompt["workflowSha256"],
            "generationInvocationCount": 1,
            "technicalRetryLimit": 1,
        }
        generation = {
            **generation_identity,
            "authoritySha256": canonical_json_digest(generation_identity),
        }
        workflow = {
            "schemaVersion": "amd.three-second-vertical-slice.v1",
            **_VIDEO_CONTRACT,
            "fluxReferenceGeneration": generation,
        }
        workflow_path = root / "workflow-authority.json"
        workflow_sha = _append_only_json(workflow_path, workflow)
        assets = {
            "schemaVersion": "amd.prompt-single-reference-assets.v1",
            "referenceProfile": REFERENCE_PROFILE,
            "sourceMode": SOURCE_MODE,
            "requiredImages": 1,
            "view": REFERENCE_VIEW,
            "promptSha256": prompt["promptSha256"],
            "seed": prompt["seed"],
            "workflowSha256": prompt["workflowSha256"],
        }
        prepared_binding = getattr(invocation.job, "prepared_reference", None)
        if prepared_binding is not None:
            binding = dict(prepared_binding)
            if (
                binding.get("sourceMode") != "preuploaded_imported"
                or not _is_sha256(binding.get("artifactSha256"))
                or not _is_sha256(binding.get("importAuthoritySha256"))
            ):
                raise CoordinatorContractError(
                    "clicked prepared reference diverges from prompt authority"
                )
            assets["preparedReference"] = binding
        assets_path = root / "assets-manifest.json"
        assets_sha = _append_only_json(assets_path, assets)
        state = {
            "schemaVersion": "amd.three-second-prepared-state.v1",
            "status": "prepared",
            "promptId": str(logical_prompt),
            "submissionNonce": nonce,
            "workflowSha256": workflow_sha,
            "assetsManifestSha256": assets_sha,
            **_VIDEO_CONTRACT,
        }
        state_path = root / "prepared-state.json"
        state_sha = _append_only_json(state_path, state)
        click = {
            "schemaVersion": "amd.user-gpu-click.v1",
            "userClick": True,
            "action": "start_generation",
            "promptId": str(logical_prompt),
            "submissionNonce": nonce,
            "workflowPath": str(workflow_path),
            "workflowSha256": workflow_sha,
            "assetsManifestPath": str(assets_path),
            "assetsManifestSha256": assets_sha,
            "statePath": str(state_path),
            "stateSha256": state_sha,
        }
        _append_only_json(root / "user-click.json", click)

    def flux_generated(self, invocation: StageInvocation) -> Mapping[str, Any]:
        self._ensure_click_authority(invocation)
        prompt = self._prompt_authority(invocation)
        if getattr(invocation.job, "prepared_reference", None) is None:
            if invocation.job.pipeline_mode == "h3_deferred_vertical_slice":
                raise TerminalWorkerStepError(
                    "flux_generated", "IMPORTED_REFERENCE_BINDING_REQUIRED"
                )
            # The already-materialized legacy pipeline remains readable, but
            # every new deferred user-click job is fail-closed above.
            try:
                values = self.runner_factory(
                    self._runner_arguments(invocation)
                ).run_flux_stage()
            except Exception as exc:
                raise RetryableWorkerStepError(
                    "flux_generated", "FLUX_STAGE_UNAVAILABLE"
                ) from exc
            if not isinstance(values, (tuple, list)) or len(values) != 1:
                raise TerminalWorkerStepError(
                    "flux_generated", "FLUX_SINGLE_REFERENCE_REQUIRED"
                )
            item = values[0]
            path = _strict_path(
                str(getattr(item, "path", "")),
                self.context.persistent_root,
                "FLUX front-three-quarter",
            )
            if (
                getattr(item, "view_name", None) != REFERENCE_VIEW
                or getattr(item, "sha256", None) != _sha256_file(path)
                or getattr(item, "prompt_sha256", None) != prompt["promptSha256"]
                or getattr(item, "seed", None) != prompt["seed"]
                or getattr(item, "workflow_sha256", None)
                != prompt["workflowSha256"]
                or not _is_sha256(
                    getattr(item, "compiled_workflow_sha256", None)
                )
            ):
                raise TerminalWorkerStepError(
                    "flux_generated", "FLUX_PROMPT_AUTHORITY_CHANGED"
                )
            attempt_ordinal = getattr(item, "generation_attempt_ordinal", None)
            failure_receipt = getattr(
                item, "technical_failure_receipt_sha256", None
            )
            if (
                type(attempt_ordinal) is not int
                or attempt_ordinal not in {0, 1}
                or (attempt_ordinal == 0 and failure_receipt is not None)
                or (attempt_ordinal == 1 and not _is_sha256(failure_receipt))
                or type(getattr(item, "prompt_id", None)) is not str
                or not item.prompt_id.strip()
            ):
                raise TerminalWorkerStepError(
                    "flux_generated", "FLUX_TECHNICAL_RETRY_AUTHORITY_INVALID"
                )
            reference = {
                "viewName": REFERENCE_VIEW,
                "path": str(path),
                "sha256": item.sha256,
                "promptId": item.prompt_id,
                "promptSha256": prompt["promptSha256"],
                "seed": prompt["seed"],
                "workflowSha256": prompt["workflowSha256"],
                "compiledWorkflowSha256": item.compiled_workflow_sha256,
                "generationAttemptOrdinal": attempt_ordinal,
                "technicalFailureReceiptSha256": failure_receipt,
                "cacheHit": False,
                "preparationRequestId": None,
            }
            return _payload(
                schemaVersion="amd.flux-generated-stage.v2",
                referenceProfile=REFERENCE_PROFILE,
                sourceMode=SOURCE_MODE,
                requiredImages=1,
                reference=reference,
                runnerCheckpointPath=str(
                    self._runner_arguments(invocation).checkpoint
                ),
            )
        if self.prepared_reference_loader is None:
            raise TerminalWorkerStepError(
                "flux_generated", "IMPORTED_REFERENCE_AUTHORITY_UNAVAILABLE"
            )
        prepared = self.prepared_reference_loader(prompt)
        try:
            if prepared is None:
                raise ValueError
            row = prepared["reference"]
            binding = getattr(invocation.job, "prepared_reference", None)
            path = _strict_path(
                row["path"], self.context.persistent_root, "imported Steve Jobs reference"
            )
            if (
                prepared["schemaVersion"]
                != "amd.competition-imported-reference.v1"
                or prepared["status"] != "prepared"
                or prepared["sourceMode"] != "preuploaded_imported"
                or prepared["referenceProfile"]
                != "competition-imported-single-view-v1"
                or prepared["fluxRuntimeProofPromptAuthority"] != prompt
                or row["viewName"] != REFERENCE_VIEW
                or row["sha256"] != _sha256_file(path)
                or row["generatedByCurrentFlux"] is not False
                or row["importedBeforeUserClick"] is not True
                or not isinstance(binding, Mapping)
                or binding.get("artifactSha256") != row["sha256"]
                or binding.get("importAuthoritySha256")
                != prepared["importAuthoritySha256"]
            ):
                raise ValueError
        except (KeyError, OSError, TypeError, ValueError) as exc:
            raise TerminalWorkerStepError(
                "flux_generated", "IMPORTED_REFERENCE_AUTHORITY_INVALID"
            ) from exc
        runner_arguments = self._runner_arguments(invocation)
        try:
            values = self.runner_factory(runner_arguments).run_flux_runtime_proof_stage(
                {
                    "requestId": prepared["requestId"],
                    "path": str(path),
                    "sha256": row["sha256"],
                    "mimeType": row["mimeType"],
                    "width": row["width"],
                    "height": row["height"],
                    "byteSize": row["byteSize"],
                    "importAuthoritySha256": prepared["importAuthoritySha256"],
                }
            )
        except Exception as exc:
            raise RetryableWorkerStepError(
                "flux_generated", "FLUX_RUNTIME_PROOF_UNAVAILABLE"
            ) from exc
        if not isinstance(values, (tuple, list)) or len(values) != 1:
            raise TerminalWorkerStepError(
                "flux_generated", "IMPORTED_SINGLE_REFERENCE_REQUIRED"
            )
        item = values[0]
        checkpoint_path = runner_arguments.checkpoint
        try:
            checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            proof = checkpoint["flux"]["runtimeProof"]
        except (KeyError, OSError, TypeError, json.JSONDecodeError) as exc:
            raise TerminalWorkerStepError(
                "flux_generated", "FLUX_RUNTIME_PROOF_INVALID"
            ) from exc
        if (
            proof.get("status") != "stopped_after_gpu_activity"
            or proof.get("outputUsedByH3") is not False
            or proof.get("processExited") is not True
            or proof.get("vramIdleAfterStop") is not True
            or proof.get("gpuActivity", {}).get("gpuActivityObserved") is not True
            or item.sha256 != row["sha256"]
            or getattr(item, "source_mode", None) != "preuploaded_imported"
            or getattr(item, "generated_by_current_flux", True) is not False
            or getattr(item, "flux_output_used", True) is not False
        ):
            raise TerminalWorkerStepError(
                "flux_generated", "FLUX_IMPORT_LINEAGE_INVALID"
            )
        reference = {
            "viewName": REFERENCE_VIEW,
            "path": str(item.path),
            "sha256": item.sha256,
            "sourceMode": "preuploaded_imported",
            "generatedByCurrentFlux": False,
            "fluxOutputUsed": False,
            "importAuthoritySha256": prepared["importAuthoritySha256"],
            "fluxProofPromptId": proof["promptId"],
            "fluxProofQueueId": proof["queueId"],
            "promptSha256": prompt["promptSha256"],
            "seed": prompt["seed"],
            "workflowSha256": prompt["workflowSha256"],
            "compiledWorkflowSha256": item.compiled_workflow_sha256,
            "generationAttemptOrdinal": 0,
            "technicalFailureReceiptSha256": None,
        }
        return _payload(
            schemaVersion="amd.flux-runtime-proof-stage.v1",
            referenceProfile="competition-imported-single-view-v1",
            sourceMode="preuploaded_imported",
            requiredImages=1,
            reference=reference,
            fluxRuntimeProof=proof,
            runnerCheckpointPath=str(checkpoint_path),
        )

    def _visual_input_digest(self, invocation: StageInvocation) -> str:
        return str(self._prompt_authority(invocation)["authoritySha256"])

    def references_published(self, invocation: StageInvocation) -> Mapping[str, Any]:
        generated = _receipt(invocation, "flux_generated")
        row = generated.get("reference")
        imported = (
            generated.get("referenceProfile")
            == "competition-imported-single-view-v1"
            and generated.get("sourceMode") == "preuploaded_imported"
        )
        legacy = (
            generated.get("referenceProfile") == REFERENCE_PROFILE
            and generated.get("sourceMode") == SOURCE_MODE
        )
        if (
            not (imported or legacy)
            or generated.get("requiredImages") != 1
            or type(row) is not dict
            or row.get("viewName") != REFERENCE_VIEW
            or (
                imported
                and (
                    row.get("generatedByCurrentFlux") is not False
                    or row.get("fluxOutputUsed") is not False
                    or not _is_sha256(row.get("importAuthoritySha256"))
                )
            )
        ):
            raise CoordinatorContractError("FLUX proof/import receipt is incomplete")
        prompt = self._prompt_authority(invocation)
        if (
            row.get("promptSha256") != prompt["promptSha256"]
            or row.get("seed") != prompt["seed"]
            or row.get("workflowSha256") != prompt["workflowSha256"]
            or not _is_sha256(row.get("compiledWorkflowSha256"))
        ):
            raise TerminalWorkerStepError(
                "references_published", "FLUX_PROMPT_AUTHORITY_CHANGED"
            )
        path = _strict_path(
            row.get("path"), self.context.persistent_root, "FLUX single reference"
        )
        try:
            media = (
                validate_imported_competition_reference_image(
                    path, expected_sha256=row.get("sha256")
                )
                if imported
                else validate_competition_reference_image(
                    path, expected_sha256=row.get("sha256")
                )
            )
        except CompetitionPromptReferenceError as exc:
            raise TerminalWorkerStepError(
                "references_published", "FLUX_REFERENCE_MEDIA_INVALID"
            ) from exc
        input_digest = self._visual_input_digest(invocation)
        attempt = self.visual_attempts.begin_or_reuse(
            project_id=invocation.job.project_id,
            input_digest=input_digest,
        )
        body = path.read_bytes()
        result = self.visual_publisher.publish(
            attempt=attempt,
            publication_key=(
                f"competition-prompt.v1:{input_digest}:01:{REFERENCE_ROLE}:"
                f"attempt-{row['generationAttemptOrdinal']}"
            ),
            body=body,
            mime_type=media["mimeType"],
            logical_role=REFERENCE_ROLE,
            expected_digest=media["sha256"],
        )
        published: dict[str, Any] = {
            "viewName": REFERENCE_VIEW,
            "artifactRef": result.artifact_ref.model_dump(mode="json"),
            "publicationFencingToken": result.publication_fencing_token,
            "sourcePath": str(path),
            "sha256": media["sha256"],
            "promptSha256": prompt["promptSha256"],
            "seed": prompt["seed"],
            "workflowSha256": prompt["workflowSha256"],
            "compiledWorkflowSha256": row["compiledWorkflowSha256"],
            "generationAttemptOrdinal": row["generationAttemptOrdinal"],
            "technicalFailureReceiptSha256": row[
                "technicalFailureReceiptSha256"
            ],
            "remoteName": REFERENCE_REMOTE_NAME,
            **media,
        }
        if imported:
            published.update(
                {
                    "sourceMode": "preuploaded_imported",
                    "generatedByCurrentFlux": False,
                    "fluxOutputUsed": False,
                    "importAuthoritySha256": row["importAuthoritySha256"],
                    "fluxProofPromptId": row["fluxProofPromptId"],
                    "fluxProofQueueId": row["fluxProofQueueId"],
                }
            )
        try:
            preview = self.api_service.publish_competition_reference_preview(
                project_id=invocation.job.project_id,
                job_id=invocation.job.external_job_id,
                job_authority_digest=invocation.job.authority_digest,
                reference=published,
            )
        except InvalidRequest as exc:
            raise TerminalWorkerStepError(
                "references_published", "REFERENCE_PREVIEW_AUTHORITY_INVALID"
            ) from exc
        except Exception as exc:
            raise RetryableWorkerStepError(
                "references_published", "REFERENCE_PREVIEW_PUBLICATION_UNAVAILABLE"
            ) from exc
        return _payload(
            schemaVersion="amd.references-published-stage.v2",
            referenceProfile=generated["referenceProfile"],
            sourceMode=generated["sourceMode"],
            requiredImages=1,
            reference=published,
            referencePreviewDigest=preview["referenceDigest"],
        )

    def _published_reference(self, invocation: StageInvocation) -> Mapping[str, Any]:
        payload = _receipt(invocation, "references_published")
        row = payload.get("reference")
        accepted_mode = (
            (
                payload.get("referenceProfile")
                == "competition-imported-single-view-v1"
                and payload.get("sourceMode") == "preuploaded_imported"
            )
            or (
                payload.get("referenceProfile") == REFERENCE_PROFILE
                and payload.get("sourceMode") == SOURCE_MODE
            )
        )
        if (
            not accepted_mode
            or payload.get("requiredImages") != 1
            or type(row) is not dict
            or row.get("viewName") != REFERENCE_VIEW
        ):
            raise CoordinatorContractError("published reference receipt is incomplete")
        try:
            ref = AtomicArtifactRef.model_validate_json(
                json.dumps(row["artifactRef"], ensure_ascii=False, allow_nan=False)
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise CoordinatorContractError(
                "published reference authority is invalid"
            ) from exc
        if (
            ref.logical_role != REFERENCE_ROLE
            or str(ref.content_digest) != row.get("sha256")
            or row.get("remoteName") != REFERENCE_REMOTE_NAME
        ):
            raise CoordinatorContractError("published reference lineage changed")
        return row

    def _plan(self, invocation: StageInvocation) -> dict[str, Any]:
        prompt = self._prompt_authority(invocation)
        published = _receipt(invocation, "references_published")
        return {
            "schemaVersion": "amd.competition-single-reference-h3-plan.v1",
            "referenceProfile": published["referenceProfile"],
            "sourceMode": published["sourceMode"],
            "requiredImages": 1,
            "view": REFERENCE_VIEW,
            "requestedDurationSeconds": 3.0,
            "frameCount": 73,
            "fps": 24,
            "prompt": prompt["h3Prompt"],
            "promptSha256": prompt["h3PromptSha256"],
        }

    def authority_finalized(self, invocation: StageInvocation) -> Mapping[str, Any]:
        reference = self._published_reference(invocation)
        plan_payload = self._plan(invocation)
        imported = plan_payload["sourceMode"] == "preuploaded_imported"
        capability_sha = _sha256_file(self.h3_capability_manifest)
        reference_identity = {
            "schemaVersion": "amd.competition-single-reference-authority.v1",
            "jobAuthorityDigest": invocation.job.authority_digest,
            "referenceProfile": plan_payload["referenceProfile"],
            "sourceMode": plan_payload["sourceMode"],
            "requiredImages": 1,
            "view": REFERENCE_VIEW,
            "promptAuthoritySha256": self._prompt_authority(invocation)[
                "authoritySha256"
            ],
            "promptSha256": reference["promptSha256"],
            "artifactRef": reference["artifactRef"],
            "artifactSha256": reference["sha256"],
            "generationAttemptOrdinal": reference["generationAttemptOrdinal"],
            "seed": reference["seed"],
            "workflowSha256": reference["workflowSha256"],
            "compiledWorkflowSha256": reference["compiledWorkflowSha256"],
        }
        if imported:
            reference_identity.update(
                {
                    "generatedByCurrentFlux": False,
                    "fluxOutputUsed": False,
                    "importAuthoritySha256": reference[
                        "importAuthoritySha256"
                    ],
                    "fluxProofPromptId": reference["fluxProofPromptId"],
                    "fluxProofQueueId": reference["fluxProofQueueId"],
                }
            )
        reference_authority = {
            **reference_identity,
            "authoritySha256": canonical_json_digest(reference_identity),
        }
        reference_authority_path = (
            self._job_root(invocation) / "competition-reference-authority.json"
        )
        reference_authority_sha = _append_only_json(
            reference_authority_path, reference_authority
        )
        identity = {
            "schemaVersion": "amd.h3-runner-authority.v1",
            "capabilityManifestPath": str(self.h3_capability_manifest.resolve()),
            "capabilityManifestSha256": capability_sha,
            "plan": plan_payload,
            "planSha256": canonical_json_digest(plan_payload),
            "referenceArtifacts": [
                {
                    "viewName": REFERENCE_VIEW,
                    "assetId": reference["artifactRef"]["artifact_id"],
                    "artifactRef": f"cas://sha256/{reference['sha256']}",
                    "sha256": reference["sha256"],
                    "remoteName": REFERENCE_REMOTE_NAME,
                    "compiledWorkflowSha256": reference[
                        "compiledWorkflowSha256"
                    ],
                }
            ],
            "seed": int(invocation.job.authority_digest[:15], 16),
        }
        manifest = {**identity, "authoritySha256": canonical_json_digest(identity)}
        manifest_path = self._job_root(invocation) / "h3-runner-authority-base.json"
        manifest_sha = _append_only_json(manifest_path, manifest)
        return _payload(
            schemaVersion="amd.authority-finalized-stage.v2",
            referenceProfile=plan_payload["referenceProfile"],
            sourceMode=plan_payload["sourceMode"],
            requiredImages=1,
            competitionReferenceAuthorityPath=str(reference_authority_path),
            competitionReferenceAuthoritySha256=reference_authority_sha,
            h3RunnerAuthorityPath=str(manifest_path),
            h3RunnerAuthoritySha256=manifest_sha,
        )

    def workflow_materialized(self, invocation: StageInvocation) -> Mapping[str, Any]:
        try:
            submission = self.api_service.materialize_deferred_video_job(
                project_id=invocation.job.project_id,
                job_id=invocation.job.external_job_id,
            )
        except DependencyUnavailable as exc:
            raise RetryableWorkerStepError(
                "workflow_materialized", "H3_SUBMITTER_UNAVAILABLE"
            ) from exc
        except InvalidRequest as exc:
            raise TerminalWorkerStepError(
                "workflow_materialized", "H3_SUBMISSION_INVALID"
            ) from exc
        finalized = _receipt(invocation, "authority_finalized")
        base_path = _strict_path(
            finalized.get("h3RunnerAuthorityPath"),
            self.context.persistent_root,
            "H3 base authority",
        )
        if finalized.get("h3RunnerAuthoritySha256") != _sha256_file(base_path):
            raise TerminalWorkerStepError(
                "workflow_materialized", "H3_BASE_AUTHORITY_CHANGED"
            )
        try:
            base = json.loads(base_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise TerminalWorkerStepError(
                "workflow_materialized", "H3_BASE_AUTHORITY_INVALID"
            ) from exc
        if type(base) is not dict or type(base.get("authoritySha256")) is not str:
            raise TerminalWorkerStepError(
                "workflow_materialized", "H3_BASE_AUTHORITY_INVALID"
            )
        base_identity = dict(base)
        base_digest = base_identity.pop("authoritySha256")
        if base_digest != canonical_json_digest(base_identity):
            raise TerminalWorkerStepError(
                "workflow_materialized", "H3_BASE_AUTHORITY_INVALID"
            )
        execution_identity = {
            **base_identity,
            "schemaVersion": "amd.h3-execution-authority.v1",
            "jobAuthorityDigest": invocation.job.authority_digest,
            "inputAuthorityDigest": submission.input_authority_digest,
            "workflowRunId": str(submission.workflow_run_id),
        }
        execution = {
            **execution_identity,
            "authoritySha256": canonical_json_digest(execution_identity),
        }
        execution_path = self._runner_arguments(invocation).h3_manifest
        execution_sha = _append_only_json(execution_path, execution)
        return _payload(
            schemaVersion="amd.workflow-materialized-stage.v1",
            workflowRunId=str(submission.workflow_run_id),
            inputAuthorityDigest=submission.input_authority_digest,
            targetDurationSeconds=submission.target_duration_seconds,
            sequenceCount=submission.sequence_count,
            h3ExecutionAuthorityPath=str(execution_path),
            h3ExecutionAuthoritySha256=execution_sha,
        )

    def h3_generated(self, invocation: StageInvocation) -> Mapping[str, Any]:
        materialized = _receipt(invocation, "workflow_materialized")
        execution_path = _strict_path(
            materialized.get("h3ExecutionAuthorityPath"),
            self.context.persistent_root,
            "H3 execution authority",
        )
        if (
            execution_path != self._runner_arguments(invocation).h3_manifest.resolve()
            or materialized.get("h3ExecutionAuthoritySha256")
            != _sha256_file(execution_path)
        ):
            raise TerminalWorkerStepError(
                "h3_generated", "H3_EXECUTION_AUTHORITY_CHANGED"
            )
        try:
            result = self.runner_factory(
                self._runner_arguments(invocation)
            ).run_h3_stage()
        except Exception as exc:
            raise RetryableWorkerStepError(
                "h3_generated", "H3_STAGE_UNAVAILABLE"
            ) from exc
        return _payload(
            schemaVersion="amd.h3-generated-stage.v1",
            resultPath=str(result.output_path),
            resultSha256=result.output_sha256,
            promptId=result.prompt_id,
            submissionNonce=result.submission_nonce,
            workflowSha256=result.workflow_sha256,
            frameCount=result.frame_count,
            fps=result.fps,
            nativeAudio=result.native_audio,
            subtitles=result.subtitles,
            runnerCheckpointPath=str(self._runner_arguments(invocation).checkpoint),
            inputAuthorityDigest=materialized.get("inputAuthorityDigest"),
            h3ExecutionAuthoritySha256=materialized.get(
                "h3ExecutionAuthoritySha256"
            ),
        )

    def delivered(self, invocation: StageInvocation) -> Mapping[str, Any]:
        generated = _receipt(invocation, "h3_generated")
        result_path = _strict_path(
            generated.get("resultPath"), self.context.persistent_root, "H3 result"
        )
        checkpoint = _strict_path(
            generated.get("runnerCheckpointPath"),
            self.context.persistent_root,
            "runner checkpoint",
        )
        materialized = _receipt(invocation, "workflow_materialized")
        if (
            generated.get("inputAuthorityDigest")
            != materialized.get("inputAuthorityDigest")
            or generated.get("h3ExecutionAuthoritySha256")
            != materialized.get("h3ExecutionAuthoritySha256")
        ):
            raise TerminalWorkerStepError(
                "delivered", "H3_EXECUTION_AUTHORITY_CHANGED"
            )
        try:
            persisted = json.loads(checkpoint.read_text(encoding="utf-8"))
            runner_result = persisted["result"]
            runner_digest = canonical_json_digest(runner_result)
            envelope = publish_competition_vertical_slice(
                session_factory=self.context.session_factory,
                cas_root=self.artifact_store.root,
                project_id=invocation.job.project_id,
                job_id=invocation.job.external_job_id,
                result_path=result_path,
                runner_checkpoint_path=checkpoint,
                runner_result_digest=runner_digest,
                expected_job_authority_digest=invocation.job.authority_digest,
                expected_input_authority_digest=materialized.get(
                    "inputAuthorityDigest"
                ),
                expected_h3_execution_authority_sha256=materialized.get(
                    "h3ExecutionAuthoritySha256"
                ),
            )
        except Exception as exc:
            raise RetryableWorkerStepError(
                "delivered", "DELIVERY_PUBLICATION_UNAVAILABLE"
            ) from exc
        if self.cleanup_after_delivery is not None:
            self.cleanup_after_delivery()
        return _payload(
            schemaVersion="amd.delivered-stage.v1",
            deliveryEnvelope=envelope,
            runnerResultDigest=runner_digest,
        )


def create_production_stage_functions(
    context: CompetitionDaemonContext,
) -> ProductionStageFunctions:
    """Build all CPU dependencies after a clicked checkpoint exists."""

    release = Path(os.environ["AMD_RELEASE_DIR"]).resolve(strict=True)
    artifact_root = Path(os.environ["CREATIVE_HUB_ARTIFACT_STORE_ROOT"]).resolve(
        strict=True
    )
    authority_root = Path(os.environ["SHIDU_H3_AUTHORITY_ROOT"]).resolve(
        strict=False
    )
    authority_store = JsonFileH3PersistedAuthorityStore(authority_root)
    artifact_store = ContentAddressedArtifactStore(artifact_root)
    publication = ArtifactPublicationService(
        repository=PostgresArtifactRepository(context.session_factory),
        store=artifact_store,
    )
    attempts = PostgresVisualPreparationAttemptSource(
        session_factory=context.session_factory,
        actor_id=os.environ["SHIDU_ACTOR_ID"],
    )
    visual_publisher = ArtifactPublicationServiceAdapter(
        service=publication,
        attempts=attempts,
    )
    from .competition_prepared_reference_backend import (
        CompetitionPreparedReferenceBackend,
    )

    prepared_backend = CompetitionPreparedReferenceBackend.from_environment(
        session_factory=context.session_factory
    )
    @contextmanager
    def no_historical_preparer() -> Iterator[None]:
        # The competition profile is prompt-synthesized.  Keeping this inert
        # dependency slot preserves the stage constructor used by CPU fakes
        # without reading a GLM key or opening a historical-image provider.
        yield None

    def snapshot_loader(job: Any) -> Any:
        with context.session_factory() as session:
            return ShiduRepositorySnapshotSource(ShiduRepository(session)).load(
                project_id=job.project_id,
                book_id=job.book_id,
                direction_revision_id=job.direction_revision_id,
                trial_script_revision_id=job.trial_script_revision_id,
            )

    stages = CompetitionProductionStages(
        context=context,
        preparer_opener=no_historical_preparer,
        snapshot_loader=snapshot_loader,
        runner_factory=create_runner,
        reference_qc=lambda _snapshot, _rows: (),
        visual_publisher=visual_publisher,
        visual_attempts=attempts,
        authority_store=authority_store,
        artifact_store=artifact_store,
        api_service=create_service(),
        flux_manifest=release
        / "drama_factory/config/flux2_dev_fp8mixed_amd_capability.json",
        flux_workflow_root=release / "drama_factory/workflows",
        h3_capability_manifest=release
        / "drama_factory/config/h3_ref2va_amd_capability.json",
        h3_template=release / "drama_factory/workflows/h3_ref2va_amd_api.json",
        prepared_reference_loader=prepared_backend.load_for_prompt,
    )
    return stages.functions()


__all__ = [
    "CompetitionProductionStages",
    "create_production_stage_functions",
]
