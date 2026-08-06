from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from shared_contracts import AtomicArtifactRef
from sqlalchemy.exc import DBAPIError, OperationalError

import shidu_api.deployment as deployment
from creative_hub.db.canonical import canonical_json_digest
from creative_hub.h3_workflow_compiler import H3SubmissionPolicyAuthority
from creative_hub.qc_policy import EvaluatorPin, FactoryQCPolicyPayload
from shidu_api.deployment import (
    H3AuthorityResolutionUnavailable,
    H3PersistedArtifactAuthority,
    H3PersistedVisualIdentityAuthority,
    H3PersistedWorkflowAuthorityRecord,
    H3VisualIdentityBindingAttestation,
    H3WorkflowAuthorityBundle,
    JsonFileH3PersistedAuthorityStore,
    PersistentH3WorkflowAuthorityResolver,
    ProductionH3WorkflowSubmitter,
    h3_authority_bundle_digest,
    h3_persisted_artifact_authority_digest,
    h3_persisted_visual_identity_authority_digest,
    h3_persisted_workflow_authority_record_digest,
    h3_visual_identity_binding_digest,
)
from shidu_api.services import DependencyUnavailable, WorkflowSubmission


PROJECT_ID = UUID("10000000-0000-4000-8000-000000000001")
BOOK_ID = UUID("10000000-0000-4000-8000-000000000002")
DIRECTION_ID = UUID("10000000-0000-4000-8000-000000000003")
SCRIPT_ID = UUID("10000000-0000-4000-8000-000000000004")
RESEARCH_ID = UUID("10000000-0000-4000-8000-000000000005")
EVIDENCE_ID = UUID("10000000-0000-4000-8000-000000000006")
RESOLUTION_ID = UUID("10000000-0000-4000-8000-000000000007")


def _ref(
    role: str,
    *,
    mime: str = "application/json",
) -> AtomicArtifactRef:
    return AtomicArtifactRef(
        artifact_id=uuid4(),
        project_id=PROJECT_ID,
        content_digest=f"{len(role) % 10}" * 64,
        mime_type=mime,
        byte_size=4_096,
        logical_role=role,
    )


def _policy_authority() -> H3SubmissionPolicyAuthority:
    policy = FactoryQCPolicyPayload(stages={})
    final = policy.stages["final"].model_copy(
        update={
            "evaluator_pin": EvaluatorPin(
                prompt_revision_id=uuid4(),
                prompt_digest="1" * 64,
                rubric_digest="2" * 64,
                operation_spec_digest="3" * 64,
                implementation_digest="4" * 64,
            )
        }
    )
    policy = policy.model_copy(
        update={"stages": {**policy.stages, "final": final}}
    )
    revision_id = uuid4()
    identity = {
        "schema_version": "factory.shidu-h3-policy-authority.v1",
        "authority_revision_id": str(revision_id),
        "factory_qc_policy": policy.model_dump(mode="json"),
    }
    return H3SubmissionPolicyAuthority.model_validate(
        {
            **identity,
            "authority_revision_id": revision_id,
            "authority_digest": canonical_json_digest(identity),
        }
    )


def _bundle(
    *,
    mode: str = "historical_image_grounded",
    duration: float = 3.0,
    sequence_count: int = 1,
) -> H3WorkflowAuthorityBundle:
    refs = [
        _ref("h3.project.authority"),
        _ref("h3.trial-script.authority"),
        _ref("h3.evidence-pack.authority"),
        _ref("h3.visual-identity-resolution.authority"),
    ]
    if mode == "historical_image_grounded":
        refs.append(_ref("character.source.image", mime="image/png"))
    visual_ref = refs[3]
    source_ref = refs[4] if len(refs) == 5 else None
    binding_identity = {
        "schema_version": "factory.shidu-h3-visual-binding.v1",
        "visual_identity_mode": mode,
        "visual_identity_resolution_id": str(RESOLUTION_ID),
        "visual_identity_resolution_digest": "5" * 64,
        "authority_artifact_id": str(visual_ref.artifact_id),
        "authority_artifact_digest": visual_ref.content_digest,
        "source_artifact_id": (
            str(source_ref.artifact_id) if source_ref is not None else None
        ),
        "source_artifact_digest": (
            source_ref.content_digest if source_ref is not None else None
        ),
        "selected_basis_digest": "c" * 64,
        "verified": source_ref is not None,
        "historical": source_ref is not None,
        "non_ai": source_ref is not None,
        "ai_derived": source_ref is None,
        "source_publication_fencing_token": (
            11 if source_ref is not None else None
        ),
        "appearance_spec_revision_id": None,
        "appearance_spec_digest": None,
    }
    binding = H3VisualIdentityBindingAttestation.model_validate(
        {
            **binding_identity,
            "visual_identity_resolution_id": RESOLUTION_ID,
            "authority_artifact_id": visual_ref.artifact_id,
            "source_artifact_id": (
                source_ref.artifact_id if source_ref is not None else None
            ),
            "attestation_digest": h3_visual_identity_binding_digest(
                binding_identity
            ),
        }
    )
    authority = _policy_authority()
    identity = {
        "schema_version": "factory.shidu-h3-authority-bundle.v1",
        "project_id": str(PROJECT_ID),
        "book_id": str(BOOK_ID),
        "book_digest": "6" * 64,
        "direction_revision_id": str(DIRECTION_ID),
        "direction_digest": "7" * 64,
        "trial_script_revision_id": str(SCRIPT_ID),
        "trial_script_digest": "8" * 64,
        "research_job_id": str(RESEARCH_ID),
        "research_digest": "9" * 64,
        "evidence_pack_revision_id": str(EVIDENCE_ID),
        "evidence_pack_digest": "a" * 64,
        "safety_release_decision_digest": "b" * 64,
        "visual_identity_mode": mode,
        "visual_identity_resolution_id": str(RESOLUTION_ID),
        "visual_identity_resolution_digest": "5" * 64,
        "requested_sequence_duration_seconds": duration,
        "sequence_count": sequence_count,
        "input_artifact_refs": [ref.model_dump(mode="json") for ref in refs],
        "visual_binding_attestation": binding.model_dump(mode="json"),
        "policy_authority": authority.model_dump(mode="json"),
        "persisted_authority_record_digest": "e" * 64,
    }
    return H3WorkflowAuthorityBundle.model_validate(
        {
            **identity,
            "project_id": PROJECT_ID,
            "book_id": BOOK_ID,
            "direction_revision_id": DIRECTION_ID,
            "trial_script_revision_id": SCRIPT_ID,
            "research_job_id": RESEARCH_ID,
            "evidence_pack_revision_id": EVIDENCE_ID,
            "visual_identity_resolution_id": RESOLUTION_ID,
            "input_artifact_refs": tuple(refs),
            "visual_binding_attestation": binding,
            "policy_authority": authority,
            "bundle_digest": h3_authority_bundle_digest(identity),
        }
    )


class _SessionContext:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def begin(self):
        return self


def _persisted_artifact(
    ref: AtomicArtifactRef,
    *,
    external_revision_id: UUID,
    external_revision_digest: str,
    fencing_token: int = 7,
) -> H3PersistedArtifactAuthority:
    identity = {
        "schema_version": "factory.shidu-h3-artifact-authority.v1",
        "external_revision_id": str(external_revision_id),
        "external_revision_digest": external_revision_digest,
        "artifact_ref": ref.model_dump(mode="json"),
        "publication_fencing_token": fencing_token,
    }
    return H3PersistedArtifactAuthority.model_validate(
        {
            **identity,
            "external_revision_id": external_revision_id,
            "artifact_ref": ref,
            "authority_digest": h3_persisted_artifact_authority_digest(
                identity
            ),
        },
        strict=True,
    )


def _persisted_visual(
    *,
    mode: str,
    visual_ref: AtomicArtifactRef,
    source_ref: AtomicArtifactRef | None,
) -> H3PersistedVisualIdentityAuthority:
    visual_artifact = _persisted_artifact(
        visual_ref,
        external_revision_id=RESOLUTION_ID,
        external_revision_digest="5" * 64,
    )
    source_artifact = (
        _persisted_artifact(
            source_ref,
            external_revision_id=source_ref.artifact_id,
            external_revision_digest=str(source_ref.content_digest),
            fencing_token=11,
        )
        if source_ref is not None
        else None
    )
    historical = mode == "historical_image_grounded"
    identity = {
        "schema_version": "factory.shidu-h3-visual-authority.v1",
        "project_id": str(PROJECT_ID),
        "visual_identity_mode": mode,
        "visual_identity_resolution_id": str(RESOLUTION_ID),
        "visual_identity_resolution_digest": "5" * 64,
        "basis_kind": (
            "searched_historical" if historical else "script_synthesized"
        ),
        "selected_basis_digest": "c" * 64,
        "verified": historical,
        "historical": historical,
        "non_ai": historical,
        "ai_derived": not historical,
        "trial_script_revision_id": str(SCRIPT_ID),
        "trial_script_digest": "8" * 64,
        "evidence_pack_revision_id": str(EVIDENCE_ID),
        "evidence_pack_digest": "a" * 64,
        "appearance_spec_revision_id": None if historical else str(uuid4()),
        "appearance_spec_digest": None if historical else "d" * 64,
        "authority_artifact": visual_artifact.model_dump(mode="json"),
        "source_artifact": (
            source_artifact.model_dump(mode="json")
            if source_artifact is not None
            else None
        ),
        "selected_source_artifact_id": (
            str(source_ref.artifact_id) if source_ref is not None else None
        ),
        "selected_source_content_digest": (
            str(source_ref.content_digest) if source_ref is not None else None
        ),
        "selected_source_fencing_token": 11 if source_ref is not None else None,
    }
    return H3PersistedVisualIdentityAuthority.model_validate(
        {
            **identity,
            "project_id": PROJECT_ID,
            "visual_identity_resolution_id": RESOLUTION_ID,
            "trial_script_revision_id": SCRIPT_ID,
            "evidence_pack_revision_id": EVIDENCE_ID,
            "appearance_spec_revision_id": (
                UUID(str(identity["appearance_spec_revision_id"]))
                if identity["appearance_spec_revision_id"] is not None
                else None
            ),
            "authority_artifact": visual_artifact,
            "source_artifact": source_artifact,
            "selected_source_artifact_id": (
                source_ref.artifact_id if source_ref is not None else None
            ),
            "authority_digest": (
                h3_persisted_visual_identity_authority_digest(identity)
            ),
        },
        strict=True,
    )


def _persisted_record(
    *,
    mode: str = "historical_image_grounded",
    project_revision_digest: str = "6" * 64,
) -> H3PersistedWorkflowAuthorityRecord:
    project_ref = _ref("h3.project.authority")
    script_ref = _ref("h3.trial-script.authority")
    evidence_ref = _ref("h3.evidence-pack.authority")
    visual_ref = _ref("h3.visual-identity-resolution.authority")
    source_ref = (
        _ref("character.source.image", mime="image/png")
        if mode == "historical_image_grounded"
        else None
    )
    project = _persisted_artifact(
        project_ref,
        external_revision_id=BOOK_ID,
        external_revision_digest=project_revision_digest,
    )
    script = _persisted_artifact(
        script_ref,
        external_revision_id=SCRIPT_ID,
        external_revision_digest="8" * 64,
    )
    evidence = _persisted_artifact(
        evidence_ref,
        external_revision_id=EVIDENCE_ID,
        external_revision_digest="a" * 64,
    )
    visual = _persisted_visual(
        mode=mode,
        visual_ref=visual_ref,
        source_ref=source_ref,
    )
    policy = _policy_authority()
    identity = {
        "schema_version": "factory.shidu-h3-persisted-authorities.v1",
        "project_id": str(PROJECT_ID),
        "book_id": str(BOOK_ID),
        "direction_revision_id": str(DIRECTION_ID),
        "direction_digest": "7" * 64,
        "trial_script_revision_id": str(SCRIPT_ID),
        "research_job_id": str(RESEARCH_ID),
        "research_digest": "9" * 64,
        "evidence_pack_revision_id": str(EVIDENCE_ID),
        "safety_release_decision_digest": "b" * 64,
        "project_authority": project.model_dump(mode="json"),
        "trial_script_authority": script.model_dump(mode="json"),
        "evidence_pack_authority": evidence.model_dump(mode="json"),
        "visual_identity_authority": visual.model_dump(mode="json"),
        "policy_authority": policy.model_dump(mode="json"),
    }
    return H3PersistedWorkflowAuthorityRecord.model_validate(
        {
            **identity,
            "project_id": PROJECT_ID,
            "book_id": BOOK_ID,
            "direction_revision_id": DIRECTION_ID,
            "trial_script_revision_id": SCRIPT_ID,
            "research_job_id": RESEARCH_ID,
            "evidence_pack_revision_id": EVIDENCE_ID,
            "project_authority": project,
            "trial_script_authority": script,
            "evidence_pack_authority": evidence,
            "visual_identity_authority": visual,
            "policy_authority": policy,
            "record_digest": h3_persisted_workflow_authority_record_digest(
                identity
            ),
        },
        strict=True,
    )


class _AuthorityStore:
    def __init__(self, record: object) -> None:
        self.record = record
        self.calls: list[dict[str, object]] = []

    def load_authorities(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.record, BaseException):
            raise self.record
        return self.record


def _persistent_resolver(
    outcome: object,
) -> tuple[PersistentH3WorkflowAuthorityResolver, _AuthorityStore]:
    store = _AuthorityStore(outcome)
    return (
        PersistentH3WorkflowAuthorityResolver(
            authority_store=store,
            repository_factory=_Repository,
        ),
        store,
    )


class _Repository:
    def __init__(self, _session: object) -> None:
        self.book = SimpleNamespace(
            id=BOOK_ID,
            project_id=PROJECT_ID,
            identity_digest="6" * 64,
        )
        self.script = SimpleNamespace(
            id=SCRIPT_ID,
            project_id=PROJECT_ID,
            book_id=BOOK_ID,
            resonance_direction_revision_id=DIRECTION_ID,
            digest="8" * 64,
            payload={},
        )
        self.direction = SimpleNamespace(
            id=DIRECTION_ID,
            project_id=PROJECT_ID,
            evidence_pack_revision_id=EVIDENCE_ID,
            digest="7" * 64,
        )
        self.pack = SimpleNamespace(
            id=EVIDENCE_ID,
            project_id=PROJECT_ID,
            research_job_id=RESEARCH_ID,
            publishable=True,
            digest="a" * 64,
        )
        self.research = SimpleNamespace(
            id=RESEARCH_ID,
            project_id=PROJECT_ID,
            book_id=BOOK_ID,
            status="ready",
            digest="9" * 64,
        )

    def get_book(self, project_id, book_id):
        assert (project_id, book_id) == (PROJECT_ID, BOOK_ID)
        return self.book

    def load_trial_script_context(self, script_id):
        assert script_id == SCRIPT_ID
        return (
            self.script,
            SimpleNamespace(),
            self.direction,
            self.pack,
            (),
            (),
        )

    def get_research_job(self, research_id):
        assert research_id == RESEARCH_ID
        return self.research


def test_json_file_authority_store_loads_only_canonical_durable_record(
    tmp_path,
) -> None:
    record = _persisted_record()
    store = JsonFileH3PersistedAuthorityStore(tmp_path)
    path = store.authority_path(
        project_id=PROJECT_ID,
        book_id=BOOK_ID,
        direction_revision_id=DIRECTION_ID,
        trial_script_revision_id=SCRIPT_ID,
    )
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(record.model_dump(mode="json")),
        encoding="utf-8",
    )

    loaded = store.load_authorities(
        session=_SessionContext(),  # type: ignore[arg-type]
        project_id=PROJECT_ID,
        book_id=BOOK_ID,
        direction_revision_id=DIRECTION_ID,
        trial_script_revision_id=SCRIPT_ID,
    )

    assert loaded == record


class _Materializer:
    mismatch: str | None = None
    calls: list[dict[str, object]] = []

    def __init__(self, **_kwargs) -> None:
        pass

    def materialize(self, **kwargs):
        type(self).calls.append(kwargs)
        definition = kwargs["definition"]
        input_digest = canonical_json_digest(kwargs["input_payload"])
        policy_digest = canonical_json_digest(kwargs["policy_snapshot"])
        operations = {node.key: SimpleNamespace() for node in definition.nodes}
        if self.mismatch == "input":
            input_digest = "f" * 64
        elif self.mismatch == "policy":
            policy_digest = "f" * 64
        elif self.mismatch == "operations":
            operations.pop(next(iter(operations)))
        return SimpleNamespace(
            run=SimpleNamespace(
                id=uuid4(),
                project_id=kwargs["project_id"],
                input_digest=input_digest,
                policy_digest=policy_digest,
            ),
            operations=operations,
        )


def _request(**overrides: object) -> dict[str, object]:
    request: dict[str, object] = {
        "bookId": str(BOOK_ID),
        "directionRevisionId": str(DIRECTION_ID),
        "trialScriptRevisionId": str(SCRIPT_ID),
        "targetDurationSeconds": 3.0,
        "sequenceCount": 1,
        "nativeAudio": True,
        "subtitles": False,
        "contentMode": "source_grounded",
        "contentLabel": "史料与原文核验改写",
        "contentNotice": "内容依据原文与资料核验改写",
    }
    request.update(overrides)
    return request


class _FailingTransaction:
    def __init__(self, phase: str, failure: BaseException) -> None:
        self.phase = phase
        self.failure = failure

    def __enter__(self):
        if self.phase == "begin":
            raise self.failure
        return self

    def __exit__(self, *_args):
        if self.phase == "commit":
            raise self.failure
        return False


class _FailingSession:
    def __init__(self, phase: str, failure: BaseException) -> None:
        self.phase = phase
        self.failure = failure

    def __enter__(self):
        if self.phase == "session":
            raise self.failure
        return self

    def __exit__(self, *_args):
        return False

    def begin(self):
        return _FailingTransaction(self.phase, self.failure)


@pytest.fixture(autouse=True)
def _production_boundaries(monkeypatch):
    _Materializer.calls = []
    _Materializer.mismatch = None
    monkeypatch.setattr(deployment, "WorkflowMaterializer", _Materializer)
    monkeypatch.setattr(
        deployment,
        "DurableDagScheduler",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(
        deployment,
        "require_trial_script_release",
        lambda _payload: SimpleNamespace(release_decision_digest="b" * 64),
    )


def test_production_submitter_rejects_caller_self_attested_bundle_resolver() -> None:
    class CallerResolver:
        def resolve(self, **_kwargs):
            return _bundle()

    with pytest.raises(ValueError, match="persistent|authority resolver"):
        ProductionH3WorkflowSubmitter(
            session_factory=_SessionContext,
            capability_registry=SimpleNamespace(is_frozen=True),
            authority_resolver=CallerResolver(),  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    "mode,expected_roles",
    [
        (
            "historical_image_grounded",
            (
                "h3.project.authority",
                "h3.trial-script.authority",
                "h3.evidence-pack.authority",
                "h3.visual-identity-resolution.authority",
                "character.source.image",
            ),
        ),
        (
            "script_synthesized",
            (
                "h3.project.authority",
                "h3.trial-script.authority",
                "h3.evidence-pack.authority",
                "h3.visual-identity-resolution.authority",
            ),
        ),
    ],
)
def test_persistent_resolver_cross_binds_repository_and_visual_authorities(
    monkeypatch,
    mode: str,
    expected_roles: tuple[str, ...],
) -> None:
    store = _AuthorityStore(_persisted_record(mode=mode))
    monkeypatch.setattr(
        deployment,
        "require_trial_script_release",
        lambda _payload: SimpleNamespace(release_decision_digest="b" * 64),
    )
    resolver = PersistentH3WorkflowAuthorityResolver(
        authority_store=store,
        repository_factory=_Repository,
    )

    bundle = resolver.resolve(
        session=_SessionContext(),
        project_id=PROJECT_ID,
        book_id=BOOK_ID,
        direction_revision_id=DIRECTION_ID,
        trial_script_revision_id=SCRIPT_ID,
        requested_sequence_duration_seconds=3.0,
        sequence_count=1,
    )

    assert tuple(ref.logical_role for ref in bundle.input_artifact_refs) == (
        expected_roles
    )
    assert bundle.visual_identity_mode == mode
    assert bundle.persisted_authority_record_digest == store.record.record_digest
    assert len(store.calls) == 1


def test_persistent_resolver_rejects_repacked_project_authority(
    monkeypatch,
) -> None:
    store = _AuthorityStore(
        _persisted_record(project_revision_digest="f" * 64)
    )
    monkeypatch.setattr(
        deployment,
        "require_trial_script_release",
        lambda _payload: SimpleNamespace(release_decision_digest="b" * 64),
    )
    resolver = PersistentH3WorkflowAuthorityResolver(
        authority_store=store,
        repository_factory=_Repository,
    )

    with pytest.raises(ValueError, match="lineage"):
        resolver.resolve(
            session=_SessionContext(),
            project_id=PROJECT_ID,
            book_id=BOOK_ID,
            direction_revision_id=DIRECTION_ID,
            trial_script_revision_id=SCRIPT_ID,
            requested_sequence_duration_seconds=3.0,
            sequence_count=1,
        )


def test_persisted_visual_authority_rejects_replacement_source_repack() -> None:
    visual_ref = _ref("h3.visual-identity-resolution.authority")
    source_ref = _ref("character.source.image", mime="image/png")
    visual = _persisted_visual(
        mode="historical_image_grounded",
        visual_ref=visual_ref,
        source_ref=source_ref,
    )
    tampered_identity = visual.model_dump(
        mode="json",
        exclude={"authority_digest"},
    )
    tampered_identity["selected_source_content_digest"] = "f" * 64

    with pytest.raises(ValueError, match="source|binding"):
        H3PersistedVisualIdentityAuthority.model_validate(
            {
                **tampered_identity,
                "project_id": PROJECT_ID,
                "visual_identity_resolution_id": RESOLUTION_ID,
                "trial_script_revision_id": SCRIPT_ID,
                "evidence_pack_revision_id": EVIDENCE_ID,
                "authority_artifact": visual.authority_artifact,
                "source_artifact": visual.source_artifact,
                "selected_source_artifact_id": source_ref.artifact_id,
                "authority_digest": (
                    h3_persisted_visual_identity_authority_digest(
                        tampered_identity
                    )
                ),
            },
            strict=True,
        )


@pytest.mark.parametrize(
    "mode",
    ["historical_image_grounded", "script_synthesized"],
)
def test_h3_submitter_materializes_exact_bundle_without_legacy_audio(
    mode: str,
) -> None:
    resolver, store = _persistent_resolver(_persisted_record(mode=mode))
    submitter = ProductionH3WorkflowSubmitter(
        session_factory=_SessionContext,
        capability_registry=SimpleNamespace(is_frozen=True),
        authority_resolver=resolver,
    )

    result = submitter.submit(
        project_id=PROJECT_ID,
        request=_request(),
        command_idempotency_key="h3-submit:1",
        created_by_actor="test.owner",
    )

    assert type(result) is WorkflowSubmission
    assert result.workflow_key == "factory.shidu-h3.v1"
    assert result.voice_preset_revision_id is None
    assert result.audio_alignment_policy_revision_id is None
    assert result.visual_identity_resolution_id == RESOLUTION_ID
    assert result.target_duration_seconds == 3.0
    assert result.sequence_count == 1
    assert result.input_authority_digest == (
        _Materializer.calls[0]["input_payload"]["structured_inputs"][
            "input_authority_digest"
        ]
    )
    assert len(store.calls) == 1
    call = _Materializer.calls[0]
    assert call["definition"].workflow_key == "factory.shidu-h3.v1"
    assert len(call["input_payload"]["authority_bundle_digest"]) == 64
    assert call["input_payload"]["persisted_authority_record_digest"] == (
        store.record.record_digest
    )
    assert call["input_payload"]["visual_identity_resolution_id"] == str(
        RESOLUTION_ID
    )
    assert call["input_payload"]["content_mode"] == "source_grounded"
    rendered = str(call).casefold()
    assert "voice_preset" not in rendered
    assert "audio_alignment" not in rendered
    assert "subtitle_authority" not in rendered


def test_h3_submitter_maps_infrastructure_failure_without_synthetic_fallback() -> None:
    resolver, store = _persistent_resolver(
        H3AuthorityResolutionUnavailable("authority store timeout")
    )
    submitter = ProductionH3WorkflowSubmitter(
        session_factory=_SessionContext,
        capability_registry=SimpleNamespace(is_frozen=True),
        authority_resolver=resolver,
    )

    with pytest.raises(DependencyUnavailable):
        submitter.submit(
            project_id=PROJECT_ID,
            request=_request(),
            command_idempotency_key="h3-submit:infra",
            created_by_actor="test.owner",
        )

    assert len(store.calls) == 1
    assert _Materializer.calls == []


def test_h3_submitter_maps_sqlalchemy_operational_failure_without_fallback() -> None:
    resolver, store = _persistent_resolver(
        OperationalError("select", {}, RuntimeError("connection lost"))
    )
    submitter = ProductionH3WorkflowSubmitter(
        session_factory=_SessionContext,
        capability_registry=SimpleNamespace(is_frozen=True),
        authority_resolver=resolver,
    )

    with pytest.raises(DependencyUnavailable):
        submitter.submit(
            project_id=PROJECT_ID,
            request=_request(),
            command_idempotency_key="h3-submit:db-infra",
            created_by_actor="test.owner",
        )

    assert len(store.calls) == 1
    assert _Materializer.calls == []


@pytest.mark.parametrize("phase", ["factory", "session", "begin", "commit"])
def test_h3_submitter_maps_database_failure_at_every_transaction_boundary(
    phase: str,
) -> None:
    failure = OperationalError(
        phase,
        {},
        RuntimeError(f"{phase} connection lost"),
    )

    def sessions():
        if phase == "factory":
            raise failure
        return _FailingSession(phase, failure)

    resolver, _store = _persistent_resolver(_persisted_record())
    submitter = ProductionH3WorkflowSubmitter(
        session_factory=sessions,
        capability_registry=SimpleNamespace(is_frozen=True),
        authority_resolver=resolver,
    )

    with pytest.raises(DependencyUnavailable):
        submitter.submit(
            project_id=PROJECT_ID,
            request=_request(),
            command_idempotency_key=f"h3-submit:db-{phase}",
            created_by_actor="test.owner",
        )


@pytest.mark.parametrize(
    "failure",
    [
        OperationalError("materialize", {}, RuntimeError("connection lost")),
        DBAPIError("flush", {}, RuntimeError("driver lost")),
    ],
)
def test_h3_submitter_maps_materialize_and_flush_database_failures(
    monkeypatch: pytest.MonkeyPatch,
    failure: DBAPIError,
) -> None:
    def fail_materialize(self, **_kwargs):
        raise failure

    monkeypatch.setattr(_Materializer, "materialize", fail_materialize)
    resolver, _store = _persistent_resolver(_persisted_record())
    submitter = ProductionH3WorkflowSubmitter(
        session_factory=_SessionContext,
        capability_registry=SimpleNamespace(is_frozen=True),
        authority_resolver=resolver,
    )

    with pytest.raises(DependencyUnavailable):
        submitter.submit(
            project_id=PROJECT_ID,
            request=_request(),
            command_idempotency_key="h3-submit:materialize-db",
            created_by_actor="test.owner",
        )


def test_h3_submitter_does_not_misclassify_materializer_validation_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_materialize(self, **_kwargs):
        raise ValueError("invalid workflow authority")

    monkeypatch.setattr(_Materializer, "materialize", fail_materialize)
    resolver, _store = _persistent_resolver(_persisted_record())
    submitter = ProductionH3WorkflowSubmitter(
        session_factory=_SessionContext,
        capability_registry=SimpleNamespace(is_frozen=True),
        authority_resolver=resolver,
    )

    with pytest.raises(ValueError, match="workflow authority"):
        submitter.submit(
            project_id=PROJECT_ID,
            request=_request(),
            command_idempotency_key="h3-submit:materialize-validation",
            created_by_actor="test.owner",
        )


@pytest.mark.parametrize(
    "override",
    [
        {"nativeAudio": False},
        {"nativeAudio": "true"},
        {"subtitles": True},
        {"subtitles": 0},
    ],
)
def test_h3_submitter_rejects_media_authority_conflict_before_resolver(
    override: dict[str, object],
) -> None:
    resolver, store = _persistent_resolver(_persisted_record())
    submitter = ProductionH3WorkflowSubmitter(
        session_factory=_SessionContext,
        capability_registry=SimpleNamespace(is_frozen=True),
        authority_resolver=resolver,
    )

    with pytest.raises(ValueError, match="workflow selection|media"):
        submitter.submit(
            project_id=PROJECT_ID,
            request=_request(**override),
            command_idempotency_key="h3-submit:media-conflict",
            created_by_actor="test.owner",
        )
    assert store.calls == []


@pytest.mark.parametrize("missing", ["nativeAudio", "subtitles"])
def test_h3_submitter_requires_explicit_media_authority(
    missing: str,
) -> None:
    request = _request()
    request.pop(missing)
    resolver, store = _persistent_resolver(_persisted_record())
    submitter = ProductionH3WorkflowSubmitter(
        session_factory=_SessionContext,
        capability_registry=SimpleNamespace(is_frozen=True),
        authority_resolver=resolver,
    )

    with pytest.raises(ValueError, match="workflow selection|media"):
        submitter.submit(
            project_id=PROJECT_ID,
            request=request,
            command_idempotency_key="h3-submit:media-missing",
            created_by_actor="test.owner",
        )
    assert store.calls == []


def test_create_service_selects_h3_submitter_from_persistent_authority_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("SHIDU_PROJECT_ID", str(PROJECT_ID))
    monkeypatch.setenv("SHIDU_ACTOR_ID", "test.owner")
    monkeypatch.setenv("SHIDU_H3_AUTHORITY_ROOT", str(tmp_path / "h3-authority"))
    monkeypatch.delenv("SHIDU_VOICE_PRESET_REVISION_ID", raising=False)
    monkeypatch.delenv("SHIDU_AUDIO_AUTHORITY_FILE", raising=False)
    sessions = lambda: _SessionContext()
    monkeypatch.setattr(deployment, "_session_factory", lambda: sessions)
    monkeypatch.setattr(
        deployment,
        "load_atomic_capability_registry",
        lambda: SimpleNamespace(is_frozen=True),
    )
    monkeypatch.setattr(
        deployment,
        "_create_book_discovery_factory",
        lambda: None,
    )

    service = deployment.create_service()

    assert isinstance(service._submitter, ProductionH3WorkflowSubmitter)
    assert isinstance(
        service._submitter._resolver,
        PersistentH3WorkflowAuthorityResolver,
    )
    assert isinstance(
        service._submitter._resolver._store,
        JsonFileH3PersistedAuthorityStore,
    )


def test_create_service_preserves_legacy_submitter_without_h3_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SHIDU_PROJECT_ID", str(PROJECT_ID))
    monkeypatch.setenv("SHIDU_ACTOR_ID", "test.owner")
    monkeypatch.setenv("SHIDU_VOICE_PRESET_REVISION_ID", str(uuid4()))
    monkeypatch.setenv("SHIDU_AUDIO_AUTHORITY_FILE", "audio-authority.json")
    monkeypatch.delenv("SHIDU_H3_AUTHORITY_ROOT", raising=False)
    sessions = lambda: _SessionContext()
    monkeypatch.setattr(deployment, "_session_factory", lambda: sessions)
    monkeypatch.setattr(
        deployment,
        "load_atomic_capability_registry",
        lambda: SimpleNamespace(is_frozen=True),
    )
    monkeypatch.setattr(
        deployment,
        "load_audio_authority_bundle",
        lambda *_args, **_kwargs: SimpleNamespace(),
    )
    monkeypatch.setattr(
        deployment,
        "_create_book_discovery_factory",
        lambda: None,
    )

    service = deployment.create_service()

    assert isinstance(
        service._submitter,
        deployment.ProductionWorkflowSubmitter,
    )


def test_h3_submitter_keeps_lineage_errors_as_value_error() -> None:
    resolver, _store = _persistent_resolver(
        _persisted_record(project_revision_digest="f" * 64)
    )
    submitter = ProductionH3WorkflowSubmitter(
        session_factory=_SessionContext,
        capability_registry=SimpleNamespace(is_frozen=True),
        authority_resolver=resolver,
    )

    with pytest.raises(ValueError, match="lineage"):
        submitter.submit(
            project_id=PROJECT_ID,
            request=_request(),
            command_idempotency_key="h3-submit:lineage",
            created_by_actor="test.owner",
        )
    assert _Materializer.calls == []


def test_h3_submitter_rejects_binding_attestation_tamper() -> None:
    record = _persisted_record()
    stale = record.model_copy(
        update={
            "visual_identity_authority": (
                record.visual_identity_authority.model_copy(
                    update={"selected_source_content_digest": "f" * 64}
                )
            )
        }
    )
    resolver, _store = _persistent_resolver(stale)
    submitter = ProductionH3WorkflowSubmitter(
        session_factory=_SessionContext,
        capability_registry=SimpleNamespace(is_frozen=True),
        authority_resolver=resolver,
    )

    with pytest.raises(ValueError, match="authority|bundle|binding"):
        submitter.submit(
            project_id=PROJECT_ID,
            request=_request(),
            command_idempotency_key="h3-submit:tamper",
            created_by_actor="test.owner",
        )
    assert _Materializer.calls == []


@pytest.mark.parametrize(
    "override",
    [
        {"targetDurationSeconds": 2.9},
        {"targetDurationSeconds": True},
        {"sequenceCount": 0},
        {"sequenceCount": True},
        {"voicePresetRevisionId": str(uuid4())},
        {"audioAlignmentPolicyRevisionId": str(uuid4())},
        {"subtitleAuthority": {"enabled": True}},
    ],
)
def test_h3_submitter_rejects_invalid_or_legacy_request_before_resolver(
    override: dict[str, object],
) -> None:
    resolver, store = _persistent_resolver(_persisted_record())
    submitter = ProductionH3WorkflowSubmitter(
        session_factory=_SessionContext,
        capability_registry=SimpleNamespace(is_frozen=True),
        authority_resolver=resolver,
    )

    with pytest.raises((TypeError, ValueError)):
        submitter.submit(
            project_id=PROJECT_ID,
            request=_request(**override),
            command_idempotency_key="h3-submit:invalid",
            created_by_actor="test.owner",
        )
    assert store.calls == []
    assert _Materializer.calls == []


@pytest.mark.parametrize("mismatch", ["input", "policy", "operations"])
def test_h3_submitter_rechecks_materialized_run_attestation(
    mismatch: str,
) -> None:
    _Materializer.mismatch = mismatch
    resolver, _store = _persistent_resolver(_persisted_record())
    submitter = ProductionH3WorkflowSubmitter(
        session_factory=_SessionContext,
        capability_registry=SimpleNamespace(is_frozen=True),
        authority_resolver=resolver,
    )

    with pytest.raises(DependencyUnavailable):
        submitter.submit(
            project_id=PROJECT_ID,
            request=_request(),
            command_idempotency_key=f"h3-submit:{mismatch}",
            created_by_actor="test.owner",
        )
