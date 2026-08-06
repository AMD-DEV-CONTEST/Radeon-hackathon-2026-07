from __future__ import annotations

import asyncio
import hashlib
import os
from datetime import UTC, datetime
from email.utils import formatdate
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from colorgraph.agent.creative_contracts import ContextBudget, canonical_sha256
from colorgraph.agent.creative_corpus import (
    LoadedCreativeKnowledgeCorpus,
    load_creative_knowledge_corpus,
)
from colorgraph.agent.creative_critic import CriticCalibrationGate
from colorgraph.agent.creative_pipeline import (
    OfflineCreativePipelineRunner,
    OfflineCreativeRunRequest,
)
from colorgraph.agent.creative_provider import (
    CreativeProviderRuntime,
    CreativeRole,
    JsonlProviderAuditSink,
    ProviderBoundary,
    ProviderResponseCache,
    RuntimeBudget,
    RuntimePolicy,
    configured_creative_provider,
    provider_runtime_configuration_digest,
)
from colorgraph.agent.creative_search import CandidateSearchBudget
from colorgraph.agent.creative_ui import (
    AgentApplicationResult,
    AgentApplyRequest,
    AgentFeedbackRequest,
    AgentPreferenceEntry,
    AgentPreferenceMemory,
    AgentRunUISnapshot,
    AgentUIControlAction,
    AgentUIStore,
    apply_agent_candidate,
    idle_agent_ui_snapshot,
)
from colorgraph.api.dependencies import compute_backend, project_store
from colorgraph.config import settings
from colorgraph.domain.jobs import JobStatus
from colorgraph.evaluation.creative_critic_calibration import (
    load_creative_critic_calibration,
)
from colorgraph.services.jobs import job_manager

router = APIRouter(prefix="/api/projects", tags=["creative-agent"])


class AgentControlAPIRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: AgentUIControlAction
    expected_snapshot_revision: int = Field(ge=0)


class AgentStartAPIRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_intent: str | None = Field(default=None, max_length=4_096)
    enable_provider_shadow: bool = False
    enable_reflection_shadow: bool = False
    confirm_cloud_run: bool = False
    consent_cloud_upload: bool = False
    maximum_provider_calls: int = Field(default=32, ge=1, le=128)
    maximum_provider_cost_usd: float = Field(default=1, ge=0, le=100)

    @model_validator(mode="after")
    def validate_provider_confirmation(self) -> AgentStartAPIRequest:
        if (
            self.enable_provider_shadow
            and not self.confirm_cloud_run
            and not settings.enable_ollama_creative_provider
        ):
            raise ValueError(
                "provider Shadow requires explicit cloud-run confirmation"
            )
        if not self.enable_provider_shadow and (
            self.confirm_cloud_run or self.consent_cloud_upload
        ):
            raise ValueError(
                "cloud confirmation or upload consent requires provider Shadow"
            )
        if self.enable_reflection_shadow and not self.enable_provider_shadow:
            raise ValueError(
                "Reflection Shadow requires provider Shadow"
            )
        return self


class AgentStartAPIResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    run_id: str
    job_id: str
    status: JobStatus
    mode: Literal["offline_shadow", "provider_shadow"] = "offline_shadow"
    snapshot: AgentRunUISnapshot


class AgentFeedbackAPIRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str = Field(min_length=1)
    feedback: str = Field(min_length=1, max_length=4_096)
    expected_snapshot_revision: int = Field(ge=0)
    mode: Literal["adjust_existing_strategy", "new_thesis_branch"] = Field(
        default="adjust_existing_strategy",
        pattern=r"^(adjust_existing_strategy|new_thesis_branch)$",
    )


class AgentPreferenceAPIRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entry_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    user_scope_id: str = Field(min_length=1)
    selected_candidate_id: str = Field(min_length=1)
    compared_candidate_ids: list[str] = Field(min_length=2)
    preferred_strength: float | None = Field(default=None, ge=0, le=1)
    recorded_at: AwareDatetime


def _ui_store(project_id: str) -> AgentUIStore:
    try:
        project = project_store().get(project_id)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc
    return AgentUIStore(project.root)


def _configured_knowledge_corpus(
    *,
    expected_sha256: str | None = None,
) -> LoadedCreativeKnowledgeCorpus | None:
    if not settings.enable_creative_knowledge_corpus:
        if expected_sha256 is not None:
            raise RuntimeError(
                "the immutable Agent run requires its configured knowledge corpus"
            )
        return None
    loaded = load_creative_knowledge_corpus(
        settings.creative_knowledge_corpus_path,
        expected_sha256=expected_sha256,
    )
    if not loaded.audit.passed or loaded.index is None:
        detail = "; ".join(loaded.audit.issues) or "unknown corpus audit failure"
        raise RuntimeError(f"creative knowledge corpus failed closed: {detail}")
    return loaded


def _configured_critic_calibration(
    *,
    expected_sha256: str | None = None,
) -> CriticCalibrationGate | None:
    if not settings.enable_creative_critic_calibration:
        if expected_sha256 is not None:
            raise RuntimeError(
                "the immutable Agent run requires its configured Critic calibration"
            )
        return None
    source = Path(settings.creative_critic_calibration_path).resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    loaded = load_creative_critic_calibration(
        source,
        expected_gate_sha256=expected_sha256,
    )
    if not loaded.audit.evidence_integrity_passed or loaded.gate is None:
        detail = "; ".join(loaded.audit.issues) or "unknown calibration audit failure"
        raise RuntimeError(
            f"creative Critic calibration failed closed: {detail}"
        )
    return loaded.gate


def _creative_provider_runtime(
    *,
    project_root: Path,
    run_id: str,
    context_budget: ContextBudget,
    search_budget: CandidateSearchBudget,
) -> CreativeProviderRuntime:
    provider = configured_creative_provider(
        settings,
        api_key_getter=lambda: os.getenv("OPENAI_API_KEY"),
    )
    safe_run_id = f"{run_id[:40]}-{hashlib.sha256(run_id.encode('utf-8')).hexdigest()[:12]}"
    return CreativeProviderRuntime(
        {role: provider for role in CreativeRole},
        policy=RuntimePolicy(
            network_enabled=settings.creative_network_enabled,
            cloud_provider_enabled=settings.enable_openai_creative_provider,
            timeout_seconds=(
                300 if provider.boundary == ProviderBoundary.LOCAL else 60
            ),
            maximum_retries=(
                0 if provider.boundary == ProviderBoundary.LOCAL else 2
            ),
            maximum_concurrency=(
                1 if provider.boundary == ProviderBoundary.LOCAL else 2
            ),
            requests_per_minute=30,
        ),
        budget=RuntimeBudget(
            maximum_provider_attempts=search_budget.maximum_model_calls,
            maximum_input_tokens=(
                context_budget.maximum_tokens
                * search_budget.maximum_model_calls
            ),
            maximum_output_tokens=(
                8_192 * search_budget.maximum_model_calls
            ),
            maximum_cost_usd=search_budget.maximum_cost_usd,
        ),
        cache=ProviderResponseCache(settings.cache_dir / "creative-provider"),
        audit_sink=JsonlProviderAuditSink(
            project_root
            / "creative-agent"
            / "provider-audit"
            / f"{safe_run_id}.jsonl"
        ),
    )


async def _run_offline_agent_job(
    *,
    job_id: str,
    project_id: str,
    run_id: str,
) -> None:
    await job_manager.update(
        job_id,
        status=JobStatus.RUNNING,
        stage="creative-agent",
        progress=2,
        message="Offline creative Shadow run started",
        device=compute_backend().info.runtime,
    )
    try:
        store = project_store()
        project = store.get(project_id)
        graph = store.load_graph(project_id)
        source = store.resolve_source(project)
        request = OfflineCreativePipelineRunner.load_request(
            project.root,
            run_id,
        )
        knowledge_corpus = (
            _configured_knowledge_corpus(
                expected_sha256=request.knowledge_corpus_sha256,
            )
            if request.knowledge_corpus_sha256 is not None
            else None
        )
        provider_runtime = (
            _creative_provider_runtime(
                project_root=project.root,
                run_id=request.run_id,
                context_budget=request.context_budget,
                search_budget=request.search_budget,
            )
            if request.provider_shadow_enabled
            else None
        )
        critic_calibration = (
            _configured_critic_calibration(
                expected_sha256=request.critic_calibration_sha256,
            )
            if request.critic_calibration_sha256 is not None
            else None
        )
        runner = OfflineCreativePipelineRunner(
            project_root=project.root,
            source=source,
            graph=graph,
            backend=compute_backend(),
            request=request,
            knowledge_index=(
                knowledge_corpus.index if knowledge_corpus is not None else None
            ),
            knowledge_corpus_audit=(
                knowledge_corpus.audit if knowledge_corpus is not None else None
            ),
            provider_runtime=provider_runtime,
            critic_calibration_gate=critic_calibration,
        )
        result = await asyncio.to_thread(runner.run)
        await job_manager.complete(
            job_id,
            {
                "run_id": run_id,
                "snapshot_revision": result.snapshot.snapshot_revision,
                "snapshot_digest": result.snapshot.snapshot_digest,
                "status": result.snapshot.status.value,
                "cancelled": result.cancelled,
                "current_graph_unchanged": True,
            },
        )
    except Exception as exc:
        await job_manager.fail(job_id, exc)


async def _resume_when_prior_job_finishes(
    *,
    project_id: str,
    run_id: str,
) -> None:
    for _ in range(100):
        active = await job_manager.find_active(
            kind="creative-agent",
            project_id=project_id,
        )
        if active is None:
            break
        await asyncio.sleep(0.05)
    job, created = await job_manager.create_unique(
        kind="creative-agent",
        project_id=project_id,
    )
    if created:
        job_manager.spawn(
            _run_offline_agent_job(
                job_id=job.id,
                project_id=project_id,
                run_id=run_id,
            )
        )


@router.get(
    "/{project_id}/creative-agent",
    response_model=AgentRunUISnapshot,
)
def get_creative_agent_snapshot(project_id: str) -> AgentRunUISnapshot:
    ui_store = _ui_store(project_id)
    snapshot = ui_store.load_snapshot()
    if snapshot is not None:
        return snapshot
    try:
        graph = project_store().load_graph(project_id)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="project graph not found") from exc
    return idle_agent_ui_snapshot(
        project_id=project_id,
        graph=graph,
    )


@router.post(
    "/{project_id}/creative-agent/runs",
    response_model=AgentStartAPIResponse,
    status_code=202,
)
async def start_creative_agent_run(
    project_id: str,
    request: AgentStartAPIRequest,
) -> AgentStartAPIResponse:
    try:
        store = project_store()
        project = store.get(project_id)
        graph = store.load_graph(project_id)
        source = store.resolve_source(project)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(
            status_code=404,
            detail="project, graph, or source media was not found",
        ) from exc
    active = await job_manager.find_active(
        kind="creative-agent",
        project_id=project_id,
    )
    if active is not None:
        snapshot = _ui_store(project_id).load_snapshot()
        if snapshot is None:
            raise HTTPException(
                status_code=409,
                detail="creative Agent job is active without a UI snapshot",
            )
        return AgentStartAPIResponse(
            project_id=project_id,
            run_id=snapshot.run_id,
            job_id=active.id,
            status=active.status,
            mode=(
                "provider_shadow"
                if snapshot.provider.provider_id != "offline-rules"
                else "offline_shadow"
            ),
            snapshot=snapshot,
        )

    run_id = f"run-{uuid4().hex}"
    scene_count = max(1, len(graph.scenes))
    if request.enable_provider_shadow:
        provider_configuration_issues: list[str] = []
        provider = None
        try:
            provider = configured_creative_provider(
                settings,
                api_key_getter=lambda: os.getenv("OPENAI_API_KEY"),
            )
        except ValueError as exc:
            provider_configuration_issues.append(str(exc))
        provider_enabled = (
            settings.enable_ollama_creative_provider
            or settings.enable_openai_creative_provider
        )
        if not provider_enabled:
            provider_configuration_issues.append(
                "no real creative provider feature flag is enabled"
            )
        if (
            provider is not None
            and provider.boundary != ProviderBoundary.LOCAL
            and not settings.creative_network_enabled
        ):
            provider_configuration_issues.append(
                "COLORGRAPH_CREATIVE_NETWORK is disabled"
            )
        if provider is not None and not provider.capabilities.image_input:
            provider_configuration_issues.append(
                "the configured provider does not declare image input"
            )
        if (
            provider is not None
            and not provider.capabilities.strict_structured_output
        ):
            provider_configuration_issues.append(
                "the configured provider does not declare strict structured output"
            )
        if (
            provider is not None
            and provider.capabilities.maximum_context_tokens < 32_192
        ):
            provider_configuration_issues.append(
                "the configured provider context limit is below 32,192 tokens"
            )
        if (
            provider is not None
            and provider.capabilities.maximum_images < 18
        ):
            provider_configuration_issues.append(
                "the configured provider image limit is below the 18-image "
                "blind Critic pair requirement"
            )
        if (
            provider is not None
            and provider.boundary != ProviderBoundary.LOCAL
            and not request.confirm_cloud_run
        ):
            provider_configuration_issues.append(
                "cloud provider execution was not explicitly confirmed"
            )
        if (
            provider is not None
            and provider.boundary != ProviderBoundary.LOCAL
            and not request.consent_cloud_upload
        ):
            provider_configuration_issues.append(
                "representative-frame upload consent was not granted"
            )
        if provider_configuration_issues:
            raise HTTPException(
                status_code=503,
                detail={
                    "message": "provider Shadow configuration failed closed",
                    "issues": provider_configuration_issues,
                },
            )
    maximum_images = min(
        48,
        max(3, len(graph.shots) * 3),
        (
            provider.capabilities.maximum_images
            if request.enable_provider_shadow
            else 48
        ),
    )
    context_budget = ContextBudget(
        maximum_images=maximum_images,
        maximum_image_edge=640,
        maximum_audio_seconds=min(
            graph.media.duration_seconds,
            600,
        ),
        maximum_tokens=24_000,
        maximum_context_bytes=32_000_000,
    )
    search_budget = CandidateSearchBudget(
        maximum_model_calls=(
            request.maximum_provider_calls
            if request.enable_provider_shadow
            else 0
        ),
        maximum_rendered_frames=scene_count * 9,
        maximum_wall_seconds=300,
        maximum_cost_usd=(
            request.maximum_provider_cost_usd
            if request.enable_provider_shadow
            else 0
        ),
        maximum_refinements=(
            1 if request.enable_reflection_shadow else 0
        ),
    )
    provider_runtime = (
        _creative_provider_runtime(
            project_root=project.root,
            run_id=run_id,
            context_budget=context_budget,
            search_budget=search_budget,
        )
        if request.enable_provider_shadow
        else None
    )
    try:
        knowledge_corpus = _configured_knowledge_corpus()
        critic_calibration = (
            _configured_critic_calibration()
            if request.enable_provider_shadow
            else None
        )
    except (OSError, ValueError, RuntimeError) as exc:
        raise HTTPException(
            status_code=503,
            detail=f"creative evidence configuration is unavailable: {exc}",
        ) from exc
    run_request = OfflineCreativeRunRequest(
        project_id=project_id,
        run_id=run_id,
        user_intent=(
            request.user_intent.strip()
            if request.user_intent and request.user_intent.strip()
            else None
        ),
        created_at=datetime.now(UTC),
        provider_shadow_enabled=provider_runtime is not None,
        reflection_shadow_enabled=request.enable_reflection_shadow,
        provider_configuration_sha256=(
            provider_runtime_configuration_digest(provider_runtime)
            if provider_runtime is not None
            else None
        ),
        cloud_upload_consent=(
            request.consent_cloud_upload
            if provider_runtime is not None
            else False
        ),
        critic_calibration_sha256=(
            canonical_sha256(critic_calibration)
            if critic_calibration is not None
            else None
        ),
        knowledge_corpus_id=(
            knowledge_corpus.audit.corpus_id
            if knowledge_corpus is not None
            else None
        ),
        knowledge_corpus_version=(
            knowledge_corpus.audit.corpus_version
            if knowledge_corpus is not None
            else None
        ),
        knowledge_corpus_sha256=(
            knowledge_corpus.audit.corpus_sha256
            if knowledge_corpus is not None
            else None
        ),
        context_budget=context_budget,
        search_budget=search_budget,
        maximum_pipeline_wall_seconds=600,
    )
    runner = OfflineCreativePipelineRunner(
        project_root=project.root,
        source=source,
        graph=graph,
        backend=compute_backend(),
        request=run_request,
        knowledge_index=(
            knowledge_corpus.index if knowledge_corpus is not None else None
        ),
        knowledge_corpus_audit=(
            knowledge_corpus.audit if knowledge_corpus is not None else None
        ),
        provider_runtime=provider_runtime,
        critic_calibration_gate=critic_calibration,
    )
    snapshot = await asyncio.to_thread(runner.initialize)
    job, created = await job_manager.create_unique(
        kind="creative-agent",
        project_id=project_id,
    )
    if not created:  # pragma: no cover - guarded above, retained for races
        raise HTTPException(
            status_code=409,
            detail="another creative Agent job started concurrently",
        )
    job_manager.spawn(
        _run_offline_agent_job(
            job_id=job.id,
            project_id=project_id,
            run_id=run_id,
        )
    )
    return AgentStartAPIResponse(
        project_id=project_id,
        run_id=run_id,
        job_id=job.id,
        status=job.status,
        mode=(
            "provider_shadow"
            if provider_runtime is not None
            else "offline_shadow"
        ),
        snapshot=snapshot,
    )


@router.post(
    "/{project_id}/creative-agent/control",
    response_model=AgentRunUISnapshot,
)
async def control_creative_agent(
    project_id: str,
    request: AgentControlAPIRequest,
) -> AgentRunUISnapshot:
    ui_store = _ui_store(project_id)
    try:
        snapshot = ui_store.request_control(
            request.action,
            expected_revision=request.expected_snapshot_revision,
        )
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=409,
            detail="creative Agent run has not started",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if request.action == AgentUIControlAction.RESUME:
        job, created = await job_manager.create_unique(
            kind="creative-agent",
            project_id=project_id,
        )
        if created:
            job_manager.spawn(
                _run_offline_agent_job(
                    job_id=job.id,
                    project_id=project_id,
                    run_id=snapshot.run_id,
                )
            )
        else:
            job_manager.spawn(
                _resume_when_prior_job_finishes(
                    project_id=project_id,
                    run_id=snapshot.run_id,
                )
            )
    return snapshot


@router.post(
    "/{project_id}/creative-agent/apply",
    response_model=AgentApplicationResult,
)
def apply_creative_agent_candidate(
    project_id: str,
    request: AgentApplyRequest,
) -> AgentApplicationResult:
    try:
        return apply_agent_candidate(
            store=project_store(),
            project_id=project_id,
            request=request,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post(
    "/{project_id}/creative-agent/feedback",
    response_model=AgentFeedbackRequest,
)
def request_creative_agent_feedback(
    project_id: str,
    request: AgentFeedbackAPIRequest,
) -> AgentFeedbackRequest:
    try:
        return _ui_store(project_id).request_feedback(
            candidate_id=request.candidate_id,
            feedback=request.feedback,
            expected_revision=request.expected_snapshot_revision,
            mode=request.mode,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get(
    "/{project_id}/creative-agent/preferences/{user_scope_id}",
    response_model=AgentPreferenceMemory,
)
def get_creative_agent_preferences(
    project_id: str,
    user_scope_id: str,
) -> AgentPreferenceMemory:
    try:
        return _ui_store(project_id).load_preferences(user_scope_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/{project_id}/creative-agent/preferences/{user_scope_id}",
    response_model=AgentPreferenceMemory,
)
def add_creative_agent_preference(
    project_id: str,
    user_scope_id: str,
    entry: AgentPreferenceAPIRequest,
) -> AgentPreferenceMemory:
    if entry.project_id != project_id or entry.user_scope_id != user_scope_id:
        raise HTTPException(
            status_code=422,
            detail="preference body differs from the URL scope",
        )
    try:
        domain_entry = AgentPreferenceEntry.model_validate(
            entry.model_dump(mode="python")
        )
        return _ui_store(project_id).add_preference(domain_entry)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete(
    "/{project_id}/creative-agent/preferences/{user_scope_id}",
    status_code=204,
)
def delete_creative_agent_preferences(
    project_id: str,
    user_scope_id: str,
) -> None:
    try:
        _ui_store(project_id).delete_preferences(user_scope_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get(
    "/{project_id}/creative-agent/preferences/{user_scope_id}/export",
)
def export_creative_agent_preferences(
    project_id: str,
    user_scope_id: str,
) -> JSONResponse:
    try:
        memory = _ui_store(project_id).load_preferences(user_scope_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return JSONResponse(
        content=memory.model_dump(mode="json"),
        headers={
            "Content-Disposition": (
                f'attachment; filename="colorgraph-{project_id}-preferences.json"'
            )
        },
    )


@router.get(
    "/{project_id}/creative-agent/assets/{asset_path:path}",
)
def get_creative_agent_public_asset(
    project_id: str,
    asset_path: str,
) -> FileResponse:
    ui_store = _ui_store(project_id)
    public_root = (ui_store.root / "public").resolve()
    candidate = (public_root / Path(asset_path)).resolve()
    if (
        candidate == public_root
        or not candidate.is_relative_to(public_root)
        or not candidate.is_file()
    ):
        raise HTTPException(status_code=404, detail="Agent asset not found")
    return FileResponse(
        candidate,
        headers={
            "Cache-Control": "private, max-age=31536000, immutable",
            "X-Content-Type-Options": "nosniff",
            "Last-Modified": formatdate(candidate.stat().st_mtime, usegmt=True),
        },
    )
