from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

from PIL import Image
import pytest

from creative_hub.artifact_publication import ContentAddressedArtifactStore
from creative_hub.db.canonical import canonical_json_digest
from shared_contracts import AtomicArtifactRef

from shidu_api.competition_prompt_reference import (
    REFERENCE_PROFILE,
    REFERENCE_REMOTE_NAME,
    REFERENCE_ROLE,
    REFERENCE_VIEW,
    SOURCE_MODE,
)
from shidu_api.competition_stage_bundle import CompetitionProductionStages
from shidu_api.competition_vertical_slice_daemon import (
    CompetitionDaemonContext,
    StageInvocation,
)
from shidu_api.competition_vertical_slice_worker import (
    ClickedDeferredVideoJob,
    CoordinatorContractError,
    StageReceipt,
    TerminalWorkerStepError,
)
from shidu_api.deployment import JsonFileH3PersistedAuthorityStore
from shidu_api.visual_identity_preparation import PublishedVisualArtifact


PROJECT_ID = UUID("70000000-0000-4000-8000-000000000001")
BOOK_ID = UUID("70000000-0000-4000-8000-000000000002")
SCRIPT_ID = UUID("70000000-0000-4000-8000-000000000003")
DIRECTION_ID = UUID("70000000-0000-4000-8000-000000000004")
RESEARCH_ID = UUID("70000000-0000-4000-8000-000000000005")
ROOT = Path(__file__).resolve().parents[2]


def _job() -> ClickedDeferredVideoJob:
    row = SimpleNamespace(
        project_id=PROJECT_ID,
        book_id=BOOK_ID,
        trial_script_revision_id=SCRIPT_ID,
        external_job_id="shidu_clicked_bundle_test",
        status="queued",
        command_idempotency_key="clicked-once",
        payload={
            "bookId": str(BOOK_ID),
            "directionRevisionId": str(DIRECTION_ID),
            "trialScriptRevisionId": str(SCRIPT_ID),
            "contentMode": "source_grounded",
            "contentLabel": "AI-assisted historical adaptation",
            "contentNotice": "Adapted from cited historical sources.",
            "pipelineMode": "h3_vertical_slice",
            "targetDurationSeconds": 3.0,
            "sequenceCount": 1,
            "frameCount": 73,
            "fps": 24,
            "nativeAudio": True,
            "subtitles": False,
            "requestDigest": "a" * 64,
            "researchJobId": str(RESEARCH_ID),
            "safetyDecisionDigest": "b" * 64,
            "workflowRunId": "70000000-0000-4000-8000-000000000006",
        },
    )
    return ClickedDeferredVideoJob.from_projection_record(row)


def _snapshot() -> SimpleNamespace:
    return SimpleNamespace(
        character_name="苏轼",
        age_stage="middle-aged",
        historical_context="乌台诗案后，苏轼在黄州重新审视自己的生活。",
        book_identity_digest="0" * 64,
        direction_digest="3" * 64,
        trial_script_digest="1" * 64,
        research_digest="4" * 64,
        evidence_pack_digest="2" * 64,
        safety_release_decision_digest="5" * 64,
        trial_script_authority_payload={
            "payload": {
                "narration_cues": [{"text": "真正的旷达，是风雨之后仍愿意向前。"}],
                "six_shots": [
                    {
                        "action": "苏轼在江边停步，望向远处月光",
                        "location": "宋代黄州江岸",
                    }
                ],
            }
        },
    )


def _stage_receipt(
    stage: str, job: ClickedDeferredVideoJob, payload: dict[str, object]
) -> StageReceipt:
    return StageReceipt.build(
        stage=stage,
        job_authority_digest=job.authority_digest,
        payload=payload,
    )


class _Publisher:
    def publish(self, *, attempt: object, body: bytes, mime_type: str, logical_role: str, expected_digest: str, **_: object):
        assert attempt.attempt_number == 1
        assert mime_type == "image/png"
        assert logical_role == REFERENCE_ROLE
        assert hashlib.sha256(body).hexdigest() == expected_digest
        return PublishedVisualArtifact(
            artifact_ref=AtomicArtifactRef(
                artifact_id=UUID("70000000-0000-4000-8000-000000000020"),
                project_id=PROJECT_ID,
                content_digest=expected_digest,
                mime_type=mime_type,
                byte_size=len(body),
                logical_role=logical_role,
            ),
            publication_fencing_token=7,
        )


class _ApiService:
    def __init__(self) -> None:
        self.reference_calls: list[dict[str, object]] = []

    def publish_competition_reference_preview(self, **kwargs: object) -> dict[str, str]:
        self.reference_calls.append(dict(kwargs))
        return {"referenceDigest": "9" * 64}


def _stages(
    tmp_path: Path,
    *,
    runner_factory=lambda _arguments: None,
    snapshot_loader=lambda _job: _snapshot(),
) -> CompetitionProductionStages:
    persistent = tmp_path / "persistent" / "douyin-amd"
    persistent.mkdir(parents=True, exist_ok=True)
    store = ContentAddressedArtifactStore(persistent / "artifacts")

    @contextmanager
    def forbidden_preparer():
        raise AssertionError("competition prompt mode must not call historical preparer")
        yield

    return CompetitionProductionStages(
        context=CompetitionDaemonContext(
            project_id=PROJECT_ID,
            persistent_root=persistent,
            session_factory=lambda: None,
        ),
        preparer_opener=forbidden_preparer,
        snapshot_loader=snapshot_loader,
        runner_factory=runner_factory,
        reference_qc=lambda *_: (_ for _ in ()).throw(
            AssertionError("single prompt image must not forge three-view QC")
        ),
        visual_publisher=_Publisher(),
        visual_attempts=SimpleNamespace(
            begin_or_reuse=lambda **_: SimpleNamespace(attempt_number=1)
        ),
        authority_store=JsonFileH3PersistedAuthorityStore(
            persistent / "authorities" / "h3"
        ),
        artifact_store=store,
        api_service=_ApiService(),
        flux_manifest=ROOT
        / "drama_factory/config/flux2_dev_fp8mixed_amd_capability.json",
        flux_workflow_root=ROOT / "drama_factory/workflows",
        h3_capability_manifest=ROOT
        / "drama_factory/config/h3_ref2va_amd_capability.json",
        h3_template=ROOT / "drama_factory/workflows/h3_ref2va_amd_api.json",
    )


def _source(stages: CompetitionProductionStages, job: ClickedDeferredVideoJob) -> dict[str, object]:
    return dict(
        stages.source_prepared(
            StageInvocation(
                stage="source_prepared",
                job=job,
                prior_receipts=(),
                idempotency_key="single-source",
            )
        )
    )


def _generated_image(stages: CompetitionProductionStages) -> Path:
    path = stages.context.persistent_root / "reference-front-three-quarter.png"
    Image.new("RGB", (512, 768), (42, 32, 22)).save(path, format="PNG")
    return path


def test_source_stage_freezes_prompt_synthesized_single_image_authority(
    tmp_path: Path,
) -> None:
    job = _job()
    stages = _stages(tmp_path)

    result = _source(stages, job)

    assert result["referenceProfile"] == REFERENCE_PROFILE
    assert result["sourceMode"] == SOURCE_MODE
    assert result["requiredImages"] == 1
    assert result["view"] == REFERENCE_VIEW
    assert result["promptAuthority"]["generationInvocationCount"] == 1
    assert result["promptAuthority"]["technicalRetryLimit"] == 1
    assert "苏轼" in result["promptAuthority"]["visualPrompt"]


def test_source_stage_rejects_resealed_prompt_text_without_matching_prompt_sha(
    tmp_path: Path,
) -> None:
    job = _job()
    stages = _stages(tmp_path)
    source = _source(stages, job)
    authority = dict(source["promptAuthority"])
    authority["visualPrompt"] = "a different prompt"
    identity = dict(authority)
    identity.pop("authoritySha256")
    authority["authoritySha256"] = canonical_json_digest(identity)
    source["promptAuthority"] = authority
    invocation = StageInvocation(
        stage="flux_generated",
        job=job,
        prior_receipts=(_stage_receipt("source_prepared", job, source),),
        idempotency_key="resealed-prompt",
    )

    with pytest.raises(CoordinatorContractError):
        stages.flux_generated(invocation)


def test_flux_stage_persists_one_image_click_authority_and_binds_runner_output(
    tmp_path: Path,
) -> None:
    job = _job()
    stages = _stages(tmp_path)
    source = _source(stages, job)
    authority = source["promptAuthority"]
    path = _generated_image(stages)
    runner_result = SimpleNamespace(
        view_name=REFERENCE_VIEW,
        path=path,
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        prompt_id="prompt-single",
        prompt_sha256=authority["promptSha256"],
        seed=authority["seed"],
        workflow_sha256=authority["workflowSha256"],
        compiled_workflow_sha256="c" * 64,
        generation_attempt_ordinal=0,
        technical_failure_receipt_sha256=None,
    )
    stages.runner_factory = lambda arguments: SimpleNamespace(
        run_flux_stage=lambda: (runner_result,)
    )
    invocation = StageInvocation(
        stage="flux_generated",
        job=job,
        prior_receipts=(_stage_receipt("source_prepared", job, source),),
        idempotency_key="single-flux",
    )

    result = stages.flux_generated(invocation)

    click = json.loads(
        stages._runner_arguments(invocation).click_authority.read_text(encoding="utf-8")
    )
    workflow = json.loads(Path(click["workflowPath"]).read_text(encoding="utf-8"))
    assets = json.loads(Path(click["assetsManifestPath"]).read_text(encoding="utf-8"))
    generation = workflow["fluxReferenceGeneration"]
    assert generation["referenceProfile"] == REFERENCE_PROFILE
    assert generation["sourceMode"] == SOURCE_MODE
    assert generation["requiredImages"] == 1
    assert generation["view"] == REFERENCE_VIEW
    assert generation["promptSha256"] == authority["promptSha256"]
    assert generation["seed"] == authority["seed"]
    assert generation["workflowSha256"] == authority["workflowSha256"]
    assert assets == {
        "schemaVersion": "amd.prompt-single-reference-assets.v1",
        "referenceProfile": REFERENCE_PROFILE,
        "sourceMode": SOURCE_MODE,
        "requiredImages": 1,
        "view": REFERENCE_VIEW,
        "promptSha256": authority["promptSha256"],
        "seed": authority["seed"],
        "workflowSha256": authority["workflowSha256"],
    }
    assert result["reference"]["viewName"] == REFERENCE_VIEW
    assert result["reference"]["compiledWorkflowSha256"] == "c" * 64
    assert "references" not in result


def test_flux_stage_allows_only_one_technical_retry(tmp_path: Path) -> None:
    job = _job()
    stages = _stages(tmp_path)
    source = _source(stages, job)
    authority = source["promptAuthority"]
    path = _generated_image(stages)
    row = SimpleNamespace(
        view_name=REFERENCE_VIEW,
        path=path,
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        prompt_id="prompt-retry",
        prompt_sha256=authority["promptSha256"],
        seed=authority["seed"],
        workflow_sha256=authority["workflowSha256"],
        compiled_workflow_sha256="c" * 64,
        generation_attempt_ordinal=1,
        technical_failure_receipt_sha256=None,
    )
    stages.runner_factory = lambda _arguments: SimpleNamespace(
        run_flux_stage=lambda: (row,)
    )
    invocation = StageInvocation(
        stage="flux_generated",
        job=job,
        prior_receipts=(_stage_receipt("source_prepared", job, source),),
        idempotency_key="single-flux-retry",
    )

    with pytest.raises(TerminalWorkerStepError):
        stages.flux_generated(invocation)

    row.technical_failure_receipt_sha256 = "f" * 64
    result = stages.flux_generated(invocation)
    assert result["reference"]["generationAttemptOrdinal"] == 1
    assert result["reference"]["technicalFailureReceiptSha256"] == "f" * 64


def test_publish_and_h3_authority_use_exactly_the_one_validated_image(
    tmp_path: Path,
) -> None:
    job = _job()
    stages = _stages(tmp_path)
    source = _source(stages, job)
    authority = source["promptAuthority"]
    path = _generated_image(stages)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    flux = {
        "schemaVersion": "amd.flux-generated-stage.v2",
        "referenceProfile": REFERENCE_PROFILE,
        "sourceMode": SOURCE_MODE,
        "requiredImages": 1,
        "reference": {
            "viewName": REFERENCE_VIEW,
            "path": str(path),
            "sha256": digest,
            "promptId": "prompt-single",
            "promptSha256": authority["promptSha256"],
            "seed": authority["seed"],
            "workflowSha256": authority["workflowSha256"],
            "compiledWorkflowSha256": "c" * 64,
            "generationAttemptOrdinal": 0,
            "technicalFailureReceiptSha256": None,
        },
        "runnerCheckpointPath": str(stages.context.persistent_root / "checkpoint.json"),
        "outputDigest": "3" * 64,
    }
    source_receipt = _stage_receipt("source_prepared", job, source)
    flux_receipt = _stage_receipt("flux_generated", job, flux)
    publish_invocation = StageInvocation(
        stage="references_published",
        job=job,
        prior_receipts=(source_receipt, flux_receipt),
        idempotency_key="single-publish",
    )

    published = dict(stages.references_published(publish_invocation))

    assert published["requiredImages"] == 1
    assert published["reference"]["viewName"] == REFERENCE_VIEW
    assert published["reference"]["sha256"] == digest
    assert published["reference"]["mimeType"] == "image/png"
    assert published["reference"]["width"] == 512
    assert published["reference"]["height"] == 768
    assert published["reference"]["compiledWorkflowSha256"] == "c" * 64
    assert published["referencePreviewDigest"] == "9" * 64
    assert "references" not in published
    authority_invocation = StageInvocation(
        stage="authority_finalized",
        job=job,
        prior_receipts=(
            source_receipt,
            flux_receipt,
            _stage_receipt("references_published", job, published),
        ),
        idempotency_key="single-authority",
    )
    finalized = stages.authority_finalized(authority_invocation)
    base = json.loads(
        Path(finalized["h3RunnerAuthorityPath"]).read_text(encoding="utf-8")
    )
    reference_authority = json.loads(
        Path(finalized["competitionReferenceAuthorityPath"]).read_text(
            encoding="utf-8"
        )
    )

    assert base["plan"] == {
        "schemaVersion": "amd.competition-single-reference-h3-plan.v1",
        "referenceProfile": REFERENCE_PROFILE,
        "sourceMode": SOURCE_MODE,
        "requiredImages": 1,
        "view": REFERENCE_VIEW,
        "requestedDurationSeconds": 3.0,
        "frameCount": 73,
        "fps": 24,
        "prompt": authority["h3Prompt"],
        "promptSha256": authority["h3PromptSha256"],
    }
    assert len(base["referenceArtifacts"]) == 1
    assert base["referenceArtifacts"][0]["viewName"] == REFERENCE_VIEW
    assert base["referenceArtifacts"][0]["sha256"] == digest
    assert base["referenceArtifacts"][0]["compiledWorkflowSha256"] == "c" * 64
    assert reference_authority["jobAuthorityDigest"] == job.authority_digest
    assert reference_authority["generationAttemptOrdinal"] == 0
    assert reference_authority["artifactSha256"] == digest
    assert reference_authority["promptSha256"] == authority["promptSha256"]
    assert reference_authority["seed"] == authority["seed"]
    assert reference_authority["workflowSha256"] == authority["workflowSha256"]
    assert reference_authority["compiledWorkflowSha256"] == "c" * 64
    assert "persistedAuthorityRecordDigest" not in finalized


def test_publish_rejects_undecodable_single_image(tmp_path: Path) -> None:
    job = _job()
    stages = _stages(tmp_path)
    source = _source(stages, job)
    authority = source["promptAuthority"]
    path = stages.context.persistent_root / "broken.png"
    path.write_bytes(b"not-a-real-image")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    flux = {
        "referenceProfile": REFERENCE_PROFILE,
        "sourceMode": SOURCE_MODE,
        "requiredImages": 1,
        "reference": {
            "viewName": REFERENCE_VIEW,
            "path": str(path),
            "sha256": digest,
            "promptSha256": authority["promptSha256"],
            "seed": authority["seed"],
            "workflowSha256": authority["workflowSha256"],
            "compiledWorkflowSha256": "c" * 64,
            "generationAttemptOrdinal": 0,
            "technicalFailureReceiptSha256": None,
        },
        "outputDigest": "4" * 64,
    }
    invocation = StageInvocation(
        stage="references_published",
        job=job,
        prior_receipts=(
            _stage_receipt("source_prepared", job, source),
            _stage_receipt("flux_generated", job, flux),
        ),
        idempotency_key="single-invalid-image",
    )

    with pytest.raises(TerminalWorkerStepError):
        stages.references_published(invocation)
