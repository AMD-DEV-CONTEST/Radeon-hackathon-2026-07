from __future__ import annotations

from contextlib import contextmanager
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import NAMESPACE_URL, UUID, uuid5

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from creative_hub.db.canonical import canonical_json_digest
from creative_hub.artifact_publication import ContentAddressedArtifactStore
from creative_hub.db.models import (
    ArtifactPublicationClaimRecord,
    ArtifactRecordRow,
    BookRecord,
    OperationAttemptRecord,
    OperationRunRecord,
    ProductCommandLedgerRecord,
    ProjectRecord,
    VideoJobProjectionRecord,
)
from creative_hub.db.repositories import WorkflowRepository
from creative_hub.models import OrchestrationBase
from creative_hub.h3_workflow_compiler import H3SubmissionPolicyAuthority
from creative_hub.qc_policy import EvaluatorPin, FactoryQCPolicyPayload
from creative_hub.runtime_bootstrap import load_atomic_capability_registry
from shared_contracts import AtomicArtifactRef
from creative_hub.shidu.evidence_validator import (
    ConflictAdjudicator,
    EvidencePackCompiler,
    EvidenceValidator,
)
from creative_hub.shidu.repository import ShiduRepository
from creative_hub.shidu.resonance import (
    ClusterProposal,
    GroundedText,
    ResonanceService,
)
from creative_hub.shidu.schemas import (
    CreateResearchJob,
    EvidenceClaimDraft,
    StoreSourceDocument,
)
from creative_hub.shidu.trial_methodology import TrialMethodologyService
from creative_hub.shidu.trial_script_compiler import (
    DeterministicTrialScriptTransport,
    TrialScriptCompiler,
)
from shidu_api.competition_no_gpu_dry_run import (
    DRY_RUN_AUTHORITY_FIELD,
    DRY_RUN_EVIDENCE_FIELD,
    DRY_RUN_EVIDENCE_ROLE,
    DRY_RUN_MARKER,
    DryRunCasArtifactGateway,
    CompetitionNoGpuDryRunError,
    _deterministic_reference_png,
    frozen_no_gpu_contract,
    late_bound_stage_factory,
    probe_live_gpu_disabled_state,
    run_competition_no_gpu_dry_run,
)
from shidu_api.competition_stage_bundle import CompetitionProductionStages
from shidu_api.competition_vertical_slice_daemon import (
    CompetitionDaemonContext,
    ProductionStageFunctions,
)
from shidu_api.main import create_app
from shidu_api.deployment import (
    H3VisualIdentityBindingAttestation,
    H3WorkflowAuthorityBundle,
    JsonFileH3PersistedAuthorityStore,
    PersistentH3WorkflowAuthorityResolver,
    ProductionH3WorkflowSubmitter,
    h3_authority_bundle_digest,
    h3_visual_identity_binding_digest,
)
from shidu_api.security import ArtifactTokenSigner
from shidu_api.services import SqlAlchemyShiduService
from shidu_api.visual_identity_preparation import (
    PublishedVisualArtifact,
)


PROJECT_ID = UUID("d9000000-0000-4000-8000-000000000001")
AUTHORITY_ID = UUID("d9000000-0000-4000-8000-000000000002")


class _ConflictTransport:
    def adjudicate(self, _request: object) -> object:
        return {"decisions": []}


class _ClusterTransport:
    def __init__(self, payload: object) -> None:
        self.payload = payload

    def propose(self, _request: object) -> object:
        return self.payload


def _seed_real_click_context(session: Session) -> tuple[UUID, UUID, UUID, UUID, UUID]:
    repository = ShiduRepository(session)
    book_id = UUID("d9000000-0000-4000-8000-000000000010")
    session.add(
        BookRecord(
            id=book_id,
            project_id=PROJECT_ID,
            identity_digest=sha256(b"dry-run-book").hexdigest(),
            title="无GPU跨组件演练",
            author="测试权威",
            language="zh-CN",
            edition="isolated",
            translator="",
            command_idempotency_key="dry-run-book",
        )
    )
    session.flush()
    research = repository.create_or_reuse_research_job(
        CreateResearchJob(
            project_id=PROJECT_ID,
            book_id=book_id,
            provider_version="dry-run-research@v1",
            command_key="dry-run-research",
        )
    ).value
    sources = []
    claims = []
    specs = (
        ("a.example", "publisher", "plot_node", "主人公在冷雨里决定推开门"),
        ("b.example", "media", "emotional_reaction", "读者感到害怕又决绝"),
        ("c.example", "publisher", "reader_fit", "适合喜欢克制成长故事的读者"),
    )
    for ordinal, (host, source_type, claim_type, text) in enumerate(specs, start=1):
        content = "门外下着冷雨，我握住门把手，还是推开了门。"
        source = repository.store_source_revision(
            StoreSourceDocument(
                project_id=PROJECT_ID,
                research_job_id=research.id,
                canonical_url=f"https://{host}/dry-run/{ordinal}",
                content=content,
                command_key=f"dry-run-source:{ordinal}",
                source_type=source_type,
            )
        )
        sources.append(source)
        excerpt = "我握住门把手"
        start = content.index(excerpt)
        claim = EvidenceValidator(repository).validate(
            EvidenceClaimDraft(
                project_id=PROJECT_ID,
                research_job_id=research.id,
                source_document_revision_id=source.id,
                claim_type=claim_type,
                normalized_claim=text,
                source_span_start=start,
                source_span_end=start + len(excerpt),
                excerpt_digest=sha256(excerpt.encode("utf-8")).hexdigest(),
                is_direct_quote=False,
                spoiler_level="light",
                confidence=0.8,
            ),
            command_key=f"dry-run-claim:{ordinal}",
        )
        claims.append(claim)
    adjudicator = ConflictAdjudicator(
        repository=repository,
        transport=_ConflictTransport(),
        model_id="dry-run-conflict-v1",
    )
    pack = EvidencePackCompiler(
        repository,
        project_id=PROJECT_ID,
        adjudicator=adjudicator,
    ).freeze(research.id, evidence_ids=tuple(item.id for item in claims))
    proposal = ClusterProposal(
        cluster_key="dry-run-door",
        evidence_ids=tuple(item.id for item in claims),
        title="推开门之前",
        factual_statements=(
            GroundedText("主人公在冷雨里决定离开", (claims[0].id,)),
        ),
        first_person_entry=GroundedText(
            "我听见冷雨敲门，手还握着门把手。", (claims[0].id,)
        ),
        perceived_detail=GroundedText("冷雨敲门", (claims[0].id,)),
        fit_for=(
            GroundedText("喜欢克制成长故事的读者", (claims[2].id,)),
        ),
        not_fit_for=(
            GroundedText("期待轻松喜剧的读者", (claims[2].id,)),
        ),
        spoiler_level="light",
    )
    direction = ResonanceService(
        repository=repository,
        proposal_transport=_ClusterTransport(
            {"clusters": [proposal.model_dump(mode="json")]}
        ),
        model_version="dry-run-cluster-v1",
        prompt_version="dry-run-resonance-v1",
    ).publish(pack.id)[0]
    methodology = TrialMethodologyService(repository).freeze(PROJECT_ID)
    script = TrialScriptCompiler(
        repository=repository,
        transport=DeterministicTrialScriptTransport(),
        model_version="dry-run-script-v1",
    ).compile(
        project_id=PROJECT_ID,
        book_id=book_id,
        direction_revision_id=direction.id,
        methodology_revision_id=methodology.id,
        command_key="dry-run-script",
    )
    current = repository.get_research_job(research.id)
    for status in (
        "resolving",
        "searching",
        "reading",
        "extracting",
        "synthesizing",
        "ready",
    ):
        current = repository.transition_research_job(
            current.id,
            current.status,
            status,
        )
    return book_id, direction.id, script.id, research.id, pack.id


def _production_policy_authority() -> H3SubmissionPolicyAuthority:
    policy = FactoryQCPolicyPayload(stages={})
    final = policy.stages["final"].model_copy(
        update={
            "evaluator_pin": EvaluatorPin(
                prompt_revision_id=uuid5(NAMESPACE_URL, "dry-run-final-prompt"),
                prompt_digest="1" * 64,
                rubric_digest="2" * 64,
                operation_spec_digest="3" * 64,
                implementation_digest="4" * 64,
            )
        }
    )
    policy = policy.model_copy(update={"stages": {**policy.stages, "final": final}})
    revision_id = uuid5(NAMESPACE_URL, "dry-run-policy")
    identity = {
        "schema_version": "factory.shidu-h3-policy-authority.v1",
        "authority_revision_id": str(revision_id),
        "factory_qc_policy": policy.model_dump(mode="json"),
    }
    return H3SubmissionPolicyAuthority.model_validate(
        {
            **identity,
            "authority_revision_id": revision_id,
            "factory_qc_policy": policy,
            "authority_digest": canonical_json_digest(identity),
        },
        strict=True,
    )


def _production_h3_bundle(
    *,
    book_id: UUID,
    direction_id: UUID,
    script_id: UUID,
    research_id: UUID,
    evidence_id: UUID,
) -> H3WorkflowAuthorityBundle:
    roles = (
        ("h3.project.authority", "application/json"),
        ("h3.trial-script.authority", "application/json"),
        ("h3.evidence-pack.authority", "application/json"),
        ("h3.visual-identity-resolution.authority", "application/json"),
    )
    refs = tuple(
        AtomicArtifactRef(
            artifact_id=uuid5(NAMESPACE_URL, f"dry-run-h3-ref:{role}"),
            project_id=PROJECT_ID,
            content_digest=sha256(role.encode()).hexdigest(),
            mime_type=mime,
            byte_size=4_096,
            logical_role=role,
        )
        for role, mime in roles
    )
    resolution_id = uuid5(NAMESPACE_URL, "dry-run-h3-resolution")
    appearance_id = uuid5(NAMESPACE_URL, "dry-run-appearance-spec")
    visual = refs[3]
    binding_identity = {
        "schema_version": "factory.shidu-h3-visual-binding.v1",
        "visual_identity_mode": "script_synthesized",
        "visual_identity_resolution_id": str(resolution_id),
        "visual_identity_resolution_digest": "5" * 64,
        "authority_artifact_id": str(visual.artifact_id),
        "authority_artifact_digest": visual.content_digest,
        "source_artifact_id": None,
        "source_artifact_digest": None,
        "selected_basis_digest": "c" * 64,
        "verified": False,
        "historical": False,
        "non_ai": False,
        "ai_derived": True,
        "source_publication_fencing_token": None,
        "appearance_spec_revision_id": str(appearance_id),
        "appearance_spec_digest": "d" * 64,
    }
    binding = H3VisualIdentityBindingAttestation.model_validate(
        {
            **binding_identity,
            "visual_identity_resolution_id": resolution_id,
            "authority_artifact_id": visual.artifact_id,
            "source_artifact_id": None,
            "appearance_spec_revision_id": appearance_id,
            "attestation_digest": h3_visual_identity_binding_digest(
                binding_identity
            ),
        },
        strict=True,
    )
    policy = _production_policy_authority()
    identity = {
        "schema_version": "factory.shidu-h3-authority-bundle.v1",
        "project_id": str(PROJECT_ID),
        "book_id": str(book_id),
        "book_digest": sha256(b"dry-run-book").hexdigest(),
        "direction_revision_id": str(direction_id),
        "direction_digest": "7" * 64,
        "trial_script_revision_id": str(script_id),
        "trial_script_digest": "8" * 64,
        "research_job_id": str(research_id),
        "research_digest": "9" * 64,
        "evidence_pack_revision_id": str(evidence_id),
        "evidence_pack_digest": "a" * 64,
        "safety_release_decision_digest": "b" * 64,
        "visual_identity_mode": "script_synthesized",
        "visual_identity_resolution_id": str(resolution_id),
        "visual_identity_resolution_digest": "5" * 64,
        "requested_sequence_duration_seconds": 3.0,
        "sequence_count": 1,
        "input_artifact_refs": [ref.model_dump(mode="json") for ref in refs],
        "visual_binding_attestation": binding.model_dump(mode="json"),
        "policy_authority": policy.model_dump(mode="json"),
        "persisted_authority_record_digest": "e" * 64,
    }
    return H3WorkflowAuthorityBundle.model_validate(
        {
            **identity,
            "project_id": PROJECT_ID,
            "book_id": book_id,
            "direction_revision_id": direction_id,
            "trial_script_revision_id": script_id,
            "research_job_id": research_id,
            "evidence_pack_revision_id": evidence_id,
            "visual_identity_resolution_id": resolution_id,
            "input_artifact_refs": refs,
            "visual_binding_attestation": binding,
            "policy_authority": policy,
            "bundle_digest": h3_authority_bundle_digest(identity),
        },
        strict=True,
    )


class _FixedPersistentResolver(PersistentH3WorkflowAuthorityResolver):
    def __init__(self, bundle: H3WorkflowAuthorityBundle) -> None:
        self.bundle = bundle
        self.calls = 0

    def resolve(self, **kwargs) -> H3WorkflowAuthorityBundle:
        assert kwargs["project_id"] == self.bundle.project_id
        assert kwargs["book_id"] == self.bundle.book_id
        assert kwargs["direction_revision_id"] == self.bundle.direction_revision_id
        assert kwargs["trial_script_revision_id"] == self.bundle.trial_script_revision_id
        assert kwargs["requested_sequence_duration_seconds"] == 3.0
        assert kwargs["sequence_count"] == 1
        self.calls += 1
        return self.bundle


def _production_cpu_stage_factory(
    service: SqlAlchemyShiduService,
    prepared_reference: dict[str, object],
) -> callable:
    """Use real CompetitionProductionStages; replace only injected providers."""

    repo_root = Path(__file__).resolve().parents[2]

    def factory(context: CompetitionDaemonContext) -> ProductionStageFunctions:
        artifact_store = ContentAddressedArtifactStore(
            context.persistent_root / "s"
        )
        authority_store = JsonFileH3PersistedAuthorityStore(
            context.persistent_root / "a"
        )
        @contextmanager
        def open_preparer():
            raise AssertionError("single prompt mode must not open historical preparer")
            yield

        class ReferencePublisher:
            def publish(
                self,
                *,
                attempt,
                publication_key,
                body,
                mime_type,
                logical_role,
                expected_digest,
            ):
                del attempt, mime_type
                assert sha256(body).hexdigest() == expected_digest
                target = artifact_store.object_path(expected_digest)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(body)
                return PublishedVisualArtifact(
                    artifact_ref=AtomicArtifactRef(
                        artifact_id=uuid5(NAMESPACE_URL, publication_key),
                        project_id=context.project_id,
                        content_digest=expected_digest,
                        mime_type="image/png",
                        byte_size=len(body),
                        logical_role=logical_role,
                    ),
                    publication_fencing_token=1,
                )

        snapshot = SimpleNamespace(
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
                    "narration_cues": [{"text": "我在历史转折点作出选择。"}],
                    "six_shots": [
                        {
                            "action": "人物在书桌前展开旧信",
                            "location": "宋代黄州书斋",
                        }
                    ],
                }
            }
        )
        stages = CompetitionProductionStages(
            context=context,
            preparer_opener=open_preparer,
            snapshot_loader=lambda _job: snapshot,
            runner_factory=lambda _arguments: (_ for _ in ()).throw(
                AssertionError("GPU runner must not be constructed")
            ),
            reference_qc=lambda *_args: (_ for _ in ()).throw(
                AssertionError("single prompt mode must not forge three-view QC")
            ),
            visual_publisher=ReferencePublisher(),
            visual_attempts=SimpleNamespace(
                begin_or_reuse=lambda **_kwargs: SimpleNamespace()
            ),
            authority_store=authority_store,
            artifact_store=artifact_store,
            api_service=service,
            flux_manifest=repo_root
            / "drama_factory/config/flux2_dev_fp8mixed_amd_capability.json",
            flux_workflow_root=repo_root / "drama_factory/workflows",
            h3_capability_manifest=repo_root
            / "drama_factory/config/h3_ref2va_amd_capability.json",
            h3_template=repo_root
            / "drama_factory/workflows/h3_ref2va_amd_api.json",
            prepared_reference_loader=lambda prompt: {
                **prepared_reference,
                "fluxRuntimeProofPromptAuthority": prompt,
            },
        )
        return stages.functions()

    return factory


def test_no_gpu_dry_run_contract_is_explicit_and_never_claims_rendered_media() -> None:
    contract = frozen_no_gpu_contract()

    assert contract["marker"] == "DRY-RUN-NO-GPU"
    assert contract["requestedDurationSeconds"] == 3.0
    assert contract["requestedFrameCount"] == 73
    assert contract["requestedFps"] == 24
    assert contract["requestedNativeAudio"] is True
    assert contract["requestedSubtitles"] is False
    assert contract["mediaRendered"] is False
    assert contract["renderedFrameCount"] == 0


def test_live_stage_factory_is_late_bound_and_reports_the_remaining_dependency(
    tmp_path: Path,
) -> None:
    factory = late_bound_stage_factory(
        "not_installed_competition_stage_bundle:create_stage_bundle"
    )
    context = CompetitionDaemonContext(
        project_id=PROJECT_ID,
        persistent_root=tmp_path.resolve(),
        session_factory=lambda: None,
    )

    with pytest.raises(
        CompetitionNoGpuDryRunError,
        match="production StageFactory|live stage factory is unavailable",
    ):
        factory(context)


def test_live_gpu_disabled_probe_reads_cgroup_and_proc_without_side_effects(
    tmp_path: Path,
) -> None:
    cgroup = tmp_path / "cgroup"
    proc = tmp_path / "proc"
    cgroup.mkdir()
    proc.mkdir()
    (cgroup / "memory.current").write_text(str(2 * 1024**3), encoding="utf-8")
    (cgroup / "memory.max").write_text(str(55 * 1024**3), encoding="utf-8")
    (cgroup / "memory.stat").write_text(
        "anon 1048576\nfile 2097152\n", encoding="utf-8"
    )
    (cgroup / "memory.events.local").write_text(
        "low 0\nhigh 0\nmax 25707\noom 0\noom_kill 0\n",
        encoding="utf-8",
    )
    harmless = proc / "404"
    harmless.mkdir()
    (harmless / "cmdline").write_bytes(b"python\0-m\0http.server")

    proof = probe_live_gpu_disabled_state(cgroup_root=cgroup, proc_root=proc)

    assert proof["memoryCurrentBytes"] == 2 * 1024**3
    assert proof["fileCacheBytes"] == 2097152
    assert proof["memoryEventsLocal"]["max"] == 25707
    assert proof["comfyUiProcessCount"] == 0
    assert proof["activeProcessMatches"] == []

    active = proc / "405"
    active.mkdir()
    (active / "cmdline").write_bytes(b"python\0ComfyUI/main.py\0--listen")
    with pytest.raises(CompetitionNoGpuDryRunError, match="FLUX/H3/ComfyUI"):
        probe_live_gpu_disabled_state(cgroup_root=cgroup, proc_root=proc)


def test_real_cross_component_no_gpu_dry_run_resumes_and_downloads_cas_evidence(
    tmp_path: Path,
) -> None:
    engine = create_engine(
        "sqlite+pysqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def attach(connection, _record) -> None:
        connection.execute("ATTACH DATABASE ':memory:' AS orchestration")
        connection.execute("PRAGMA foreign_keys = ON")

    OrchestrationBase.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as session, session.begin():
        WorkflowRepository(session).create_project(
            project_key="competition-no-gpu-dry-run-isolated",
            title="Competition no-GPU dry-run isolated project",
            config={"marker": DRY_RUN_MARKER, "finalUserTask": False},
            project_id=PROJECT_ID,
        )
        (
            book_id,
            direction_id,
            script_id,
            research_id,
            evidence_id,
        ) = _seed_real_click_context(session)

    resolver = _FixedPersistentResolver(
        _production_h3_bundle(
            book_id=book_id,
            direction_id=direction_id,
            script_id=script_id,
            research_id=research_id,
            evidence_id=evidence_id,
        )
    )
    submitter = ProductionH3WorkflowSubmitter(
        session_factory=sessions,
        capability_registry=load_atomic_capability_registry(),
        authority_resolver=resolver,
    )
    persistent = tmp_path / "persistent"
    persistent.mkdir()
    imported_body = _deterministic_reference_png(width=880, height=1168)
    imported_sha = sha256(imported_body).hexdigest()
    imported_path = persistent / "prepared-reference" / f"steve-jobs-{imported_sha}.png"
    imported_path.parent.mkdir(parents=True)
    imported_path.write_bytes(imported_body)
    import_authority_sha = sha256(b"dry-run-steve-jobs-import-authority").hexdigest()
    prepared_reference: dict[str, object] = {
        "schemaVersion": "amd.competition-imported-reference.v1",
        "requestId": str(uuid5(NAMESPACE_URL, "dry-run-imported-reference-request")),
        "status": "prepared",
        "referenceProfile": "competition-imported-single-view-v1",
        "sourceMode": "preuploaded_imported",
        "requiredImages": 1,
        "importAuthoritySha256": import_authority_sha,
        "reference": {
            "path": str(imported_path),
            "viewName": "front_three_quarter",
            "sha256": imported_sha,
            "mimeType": "image/png",
            "width": 880,
            "height": 1168,
            "byteSize": len(imported_body),
            "generatedByCurrentFlux": False,
            "importedBeforeUserClick": True,
        },
    }
    service = SqlAlchemyShiduService(
        session_factory=sessions,
        workflow_submitter=submitter,
        actor_id="dry-run.no-gpu",
        competition_reference_lookup=lambda **_kwargs: prepared_reference,
    )
    cas_root = persistent / "cas"
    signer = ArtifactTokenSigner(
        b"isolated-dry-run-signing-secret-32-bytes-minimum",
        ttl_seconds=300,
    )
    gateway = DryRunCasArtifactGateway(
        session_factory=sessions,
        cas_root=cas_root,
        project_id=PROJECT_ID,
    )
    client = TestClient(
        create_app(
            service=service,
            signer=signer,
            artifact_gateway=gateway,
            project_id=PROJECT_ID,
        )
    )

    report = run_competition_no_gpu_dry_run(
        client=client,
        session_factory=sessions,
        project_id=PROJECT_ID,
        request={
            "bookId": str(book_id),
            "directionRevisionId": str(direction_id),
            "trialScriptRevisionId": str(script_id),
        },
        idempotency_key="dry-run-no-gpu:isolated-click",
        authority_id=AUTHORITY_ID,
        persistent_root=persistent,
        checkpoint_root=persistent / "checkpoints",
        cas_root=cas_root,
        signer=signer,
        base_stage_factory=_production_cpu_stage_factory(service, prepared_reference),
        gpu_disabled_probe=lambda: {
            "marker": "GPU-DISABLED-BEFORE-FINAL-USER-CLICK",
            "gpuEnabled": False,
            "comfyUiProcessCount": 0,
            "finalUserClickPerformed": False,
            "proofSource": "isolated-test-click-gate",
        },
        restart_after_stage="flux_generated",
    )

    assert report.marker == DRY_RUN_MARKER
    assert report.before_click_post_count == 0
    assert report.trigger_post_count == 1
    assert report.claim_owner_count == 1
    assert report.claim_attempt_ordinal == 2
    assert report.checkpoint_completed_stage == "delivered"
    assert report.checkpoint_revision == 8
    assert list(report.stage_audit) == [
        "source_prepared",
        "flux_generated",
        "references_published",
        "authority_finalized",
        "workflow_materialized",
        "h3_generated",
        "delivered",
    ]
    assert all(
        value["executionCount"] == 1 and value["replayCount"] == 0
        for value in report.stage_audit.values()
    )
    assert {
        stage
        for stage, value in report.stage_audit.items()
        if value["executorKind"] == "deterministic-no-gpu-stub"
    } == {"flux_generated", "h3_generated"}
    assert report.cas_publication_claim_count == 1
    assert report.head_status == 200
    assert report.range_status == 206
    assert report.full_status == 200
    assert report.full_download_sha256 == report.artifact_digest
    assert report.media_rendered is False
    assert report.rendered_frame_count == 0
    assert report.final_user_click_performed is False
    assert "production StageFactory" in report.live_stage_factory_dependency
    assert resolver.calls == 1

    flux_audit_path = (
        persistent
        / "competition-no-gpu"
        / "stage-audit"
        / str(AUTHORITY_ID)
        / "flux_generated.json"
    )
    flux_audit = json.loads(flux_audit_path.read_text(encoding="utf-8"))
    assert flux_audit["executorKind"] == "deterministic-no-gpu-stub"
    assert flux_audit["result"]["authorityPreparationSha256"] == sha256(
        Path(flux_audit["result"]["authorityPreparationPath"]).read_bytes()
    ).hexdigest()
    assert flux_audit["result"]["generationInvocationCount"] == 1
    assert "references" not in flux_audit["result"]
    assert flux_audit["result"]["requiredImages"] == 1
    assert flux_audit["result"]["referenceProfile"] == (
        "competition-imported-single-view-v1"
    )
    assert flux_audit["result"]["sourceMode"] == "preuploaded_imported"
    deterministic_reference = flux_audit["result"]["reference"]
    assert deterministic_reference["viewName"] == "front_three_quarter"
    assert deterministic_reference["sha256"] == imported_sha
    assert deterministic_reference["generatedByCurrentFlux"] is False
    assert deterministic_reference["fluxOutputUsed"] is False
    assert deterministic_reference["importAuthoritySha256"] == import_authority_sha
    assert len(deterministic_reference["promptSha256"]) == 64
    assert len(deterministic_reference["workflowSha256"]) == 64
    assert len(deterministic_reference["compiledWorkflowSha256"]) == 64
    assert type(deterministic_reference["seed"]) is int
    reference = Path(deterministic_reference["path"])
    assert reference.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert sha256(reference.read_bytes()).hexdigest() == (
        deterministic_reference["sha256"]
    )
    assert flux_audit["result"]["marker"] == DRY_RUN_MARKER

    published_audit_path = flux_audit_path.with_name("references_published.json")
    published_audit = json.loads(
        published_audit_path.read_text(encoding="utf-8")
    )
    published_reference = published_audit["result"]["reference"]
    assert published_audit["result"]["sourceMode"] == "preuploaded_imported"
    assert published_reference["sha256"] == imported_sha
    assert published_reference["workflowSha256"] == (
        deterministic_reference["workflowSha256"]
    )
    assert published_reference["compiledWorkflowSha256"] == (
        deterministic_reference["compiledWorkflowSha256"]
    )

    public = client.get(f"/api/video-jobs/{report.external_job_id}")
    assert public.status_code == 200
    assert "artifacts" not in public.json()
    assert "h3Product" not in public.json()

    with sessions() as session:
        assert session.scalar(
            select(func.count())
            .select_from(VideoJobProjectionRecord)
            .where(VideoJobProjectionRecord.project_id == PROJECT_ID)
        ) == 1
        job = session.scalar(
            select(VideoJobProjectionRecord).where(
                VideoJobProjectionRecord.external_job_id == report.external_job_id
            )
        )
        assert job.payload[DRY_RUN_AUTHORITY_FIELD]["marker"] == DRY_RUN_MARKER
        evidence = job.payload[DRY_RUN_EVIDENCE_FIELD]
        assert evidence["marker"] == DRY_RUN_MARKER
        assert evidence["mediaRendered"] is False
        assert evidence["renderedFrameCount"] == 0
        assert job.payload["competitionWorker"]["status"] == "delivered"
        assert session.scalar(
            select(func.count())
            .select_from(ProductCommandLedgerRecord)
            .where(
                ProductCommandLedgerRecord.project_id == PROJECT_ID,
                ProductCommandLedgerRecord.command_kind == "shidu.create_video_job",
            )
        ) == 1
        assert session.scalar(
            select(func.count())
            .select_from(ArtifactPublicationClaimRecord)
            .where(ArtifactPublicationClaimRecord.project_id == PROJECT_ID)
        ) == 1
        artifact = session.get(ArtifactRecordRow, UUID(report.artifact_id))
        assert artifact.status == "COMMITTED"
        assert artifact.mime_type == "application/json"
        assert artifact.logical_role == DRY_RUN_EVIDENCE_ROLE
        assert session.scalar(
            select(func.count())
            .select_from(OperationAttemptRecord)
            .where(
                OperationAttemptRecord.project_id == PROJECT_ID,
                OperationAttemptRecord.worker_id == DRY_RUN_MARKER,
            )
        ) == 1
        dry_run_operation = session.scalar(
            select(OperationRunRecord).where(
                OperationRunRecord.project_id == PROJECT_ID,
                OperationRunRecord.node_key
                == "competition.no-gpu.dry-run.evidence",
            )
        )
        assert dry_run_operation.status == "SUCCEEDED"
        assert dry_run_operation.accepted_attempt_id is not None

    object_path = cas_root / "objects" / "sha256" / report.artifact_digest[:2] / report.artifact_digest
    body = object_path.read_bytes()
    assert sha256(body).hexdigest() == report.artifact_digest
    payload = json.loads(body)
    assert payload["marker"] == DRY_RUN_MARKER
    assert payload["requestedContract"]["requestedFrameCount"] == 73
    assert payload["mediaRendered"] is False
    assert payload["renderedFrameCount"] == 0
    assert list(persistent.rglob("*.mp4")) == []
    assert (
        persistent
        / "competition-no-gpu"
        / str(AUTHORITY_ID)
        / "restart.json"
    ).is_file()

    engine.dispose()
