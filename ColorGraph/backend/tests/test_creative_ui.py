from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from test_creative_evidence import _write_evidence_video

from colorgraph.agent.creative_contracts import (
    CreativeDirection,
    CritiqueDimension,
    StrategyScope,
    canonical_sha256,
)
from colorgraph.agent.creative_ui import (
    AgentApplicationManifest,
    AgentApplyRequest,
    AgentPreferenceEntry,
    AgentUIBudgetSnapshot,
    AgentUICritiqueDimension,
    AgentUIDirectionSnapshot,
    AgentUIEvidenceSnapshot,
    AgentUIProviderSnapshot,
    AgentUIRunStatus,
    AgentUISceneSnapshot,
    AgentUISelectionSnapshot,
    AgentUIStage,
    AgentUIStore,
    CandidateApplicationAsset,
    apply_agent_candidate,
    idle_agent_ui_snapshot,
    seal_snapshot,
)
from colorgraph.api.routes import creative_agent
from colorgraph.devices import TorchComputeBackend
from colorgraph.domain.grade_graph import (
    ColorSpace,
    GradeGraph,
    MediaInfo,
    NodeType,
    TimeRange,
)
from colorgraph.domain.jobs import JobStatus
from colorgraph.grading.looks import graph_digest
from colorgraph.services.graph_builder import build_initial_graph
from colorgraph.services.jobs import JobManager
from colorgraph.storage import ProjectStore

NOW = datetime(2026, 7, 30, 4, tzinfo=UTC)


def test_provider_shadow_start_requires_explicit_confirmation_and_upload_consent() -> None:
    with pytest.raises(ValueError, match="cloud-run confirmation"):
        creative_agent.AgentStartAPIRequest(
            enable_provider_shadow=True,
            consent_cloud_upload=True,
        )
    request = creative_agent.AgentStartAPIRequest(
        enable_provider_shadow=True,
        confirm_cloud_run=True,
        consent_cloud_upload=True,
    )
    assert request.confirm_cloud_run
    assert request.consent_cloud_upload


def test_local_provider_shadow_does_not_require_cloud_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        creative_agent,
        "settings",
        SimpleNamespace(enable_ollama_creative_provider=True),
    )

    request = creative_agent.AgentStartAPIRequest(enable_provider_shadow=True)

    assert request.enable_provider_shadow
    assert not request.confirm_cloud_run
    assert not request.consent_cloud_upload


def test_reflection_shadow_requires_provider_but_not_a_preexisting_calibration() -> None:
    with pytest.raises(ValueError, match="requires provider Shadow"):
        creative_agent.AgentStartAPIRequest(
            enable_reflection_shadow=True,
        )

    request = creative_agent.AgentStartAPIRequest(
        enable_provider_shadow=True,
        enable_reflection_shadow=True,
        confirm_cloud_run=True,
    )

    assert request.enable_reflection_shadow


def _project(tmp_path: Path):
    store = ProjectStore(tmp_path / "projects")
    project = store.create("Creative UI")
    graph = build_initial_graph(
        project_id=project.id,
        project_name="Creative UI",
        media=MediaInfo(
            path="source.mp4",
            duration_seconds=4,
            width=640,
            height=360,
            fps=25,
            frame_count=100,
            codec="h264",
            input_color_space=ColorSpace.BT709_OETF,
        ),
        shot_ranges=[TimeRange(start_seconds=0, end_seconds=4)],
        representative_frames=[Path("frame.jpg")],
    )
    store.save_graph(project, graph)
    return store, project, graph


def _critique() -> list[AgentUICritiqueDimension]:
    return [
        AgentUICritiqueDimension(
            dimension=dimension,
            score=(
                0.2
                if dimension == CritiqueDimension.OVERGRADING_RISK
                else 0.8
            ),
            confidence=0.75,
            concise_reason=f"{dimension.value} is grounded in the cited frame.",
        )
        for dimension in CritiqueDimension
    ]


def _direction(
    project_id: str,
    direction: CreativeDirection,
    *,
    candidate_id: str | None,
    preferred: bool = False,
    runner_up: bool = False,
) -> AgentUIDirectionSnapshot:
    has_candidate = candidate_id is not None
    return AgentUIDirectionSnapshot(
        brief_id=f"brief:{direction.value}",
        direction=direction,
        title=f"{direction.value.title()} direction",
        interpretation=f"A bounded {direction.value} interpretation.",
        emotional_target=f"{direction.value} attention",
        support_evidence_ids=["frame:support"],
        counterevidence_ids=["frame:counter"],
        protections=["highlight detail", "project continuity"],
        intentional_exceptions=[],
        failure_conditions=["The subject hierarchy becomes unclear."],
        candidate_id=candidate_id,
        candidate_thumbnail_urls=(
            [f"/api/projects/{project_id}/creative-agent/assets/{candidate_id}.png"]
            if has_candidate
            else []
        ),
        qc_status="pass" if has_candidate else "pending",
        critique=_critique() if has_candidate else [],
        is_pareto=has_candidate,
        is_preferred=preferred,
        is_runner_up=runner_up,
        application_scopes=(
            [
                StrategyScope(
                    project_id=project_id,
                    scene_id="scene_001",
                )
            ]
            if has_candidate
            else []
        ),
    )


def _snapshot(
    project_id: str,
    graph: GradeGraph,
    *,
    revision: int = 0,
    status: AgentUIRunStatus = AgentUIRunStatus.READY_FOR_REVIEW,
    stage: AgentUIStage = AgentUIStage.READY,
):
    preferred = "candidate:faithful"
    runner_up = "candidate:counterpoint"
    scene = AgentUISceneSnapshot(
        scene_id="scene_001",
        scene_label="Scene 1",
        narrative_role="Open the film with restrained visual tension.",
        continuity_notes=["Retain neutral highlights across the project."],
        evidence=[
            AgentUIEvidenceSnapshot(
                evidence_id="frame:support",
                label="Representative lake frame",
                role="support",
                scene_id="scene_001",
                shot_id="shot_001",
                frame_index=25,
            ),
            AgentUIEvidenceSnapshot(
                evidence_id="frame:counter",
                label="Current grade counterevidence",
                role="counterevidence",
                scene_id="scene_001",
                shot_id="shot_001",
                frame_index=50,
            ),
        ],
        directions=[
            _direction(
                project_id,
                CreativeDirection.FAITHFUL,
                candidate_id=preferred,
                preferred=True,
            ),
            _direction(
                project_id,
                CreativeDirection.AMPLIFIED,
                candidate_id="candidate:amplified",
            ),
            _direction(
                project_id,
                CreativeDirection.COUNTERPOINT,
                candidate_id=runner_up,
                runner_up=True,
            ),
        ],
    )
    return seal_snapshot(
        project_id=project_id,
        run_id="run:creative-ui",
        snapshot_revision=revision,
        status=status,
        stage=stage,
        progress=100 if status == AgentUIRunStatus.READY_FOR_REVIEW else 60,
        message="Creative candidates are ready for an explicit user decision.",
        updated_at=NOW,
        shadow_mode=True,
        current_graph_digest=graph_digest(graph),
        current_graph_unchanged=True,
        offline_available=True,
        project_visual_thesis="A restrained study of reflected light.",
        palette_character="Neutral highlights with bounded cool shadows.",
        contrast_character="Soft structure with selective local separation.",
        provider=AgentUIProviderSnapshot(
            provider_id="local-test",
            model_id="critic-test",
            model_revision="v1",
            boundary="local",
            network_enabled=False,
            cloud_upload_required=False,
            cloud_upload_consented=False,
        ),
        budget=AgentUIBudgetSnapshot(
            model_calls_used=4,
            model_calls_limit=8,
            rendered_frames_used=9,
            rendered_frames_limit=12,
            cost_usd_used=0,
            cost_usd_limit=1,
            elapsed_seconds=12,
            wall_seconds_limit=60,
            refinements_used=0,
            refinements_limit=1,
        ),
        scenes=[scene],
        selection=AgentUISelectionSnapshot(
            status="selected-shadow-requires-confirmation",
            preferred_candidate_id=preferred,
            runner_up_candidate_id=runner_up,
            pareto_candidate_ids=[
                preferred,
                "candidate:amplified",
                runner_up,
            ],
            gate_trace=[
                "technical_delivery",
                "intent_and_protection",
                "temporal_consistency",
                "human_preference:skipped",
            ],
            automatic_selection_allowed=False,
            requires_user_confirmation=True,
        ),
        cancellation_requested=False,
        resume_requested=False,
        last_error=None,
    )


def _candidate_graph(graph: GradeGraph) -> GradeGraph:
    payload = graph.model_dump(mode="python")
    nodes = [item.model_copy(deep=True) for item in graph.nodes]
    look = next(item for item in nodes if item.type == NodeType.LOOK)
    look.parameters["contrast"] = 0.1
    payload["nodes"] = [item.model_dump(mode="python") for item in nodes]
    payload["updated_at"] = NOW
    return GradeGraph.model_validate(payload)


def test_snapshot_exposes_three_directions_evidence_dimensions_and_shadow_state(
    tmp_path: Path,
) -> None:
    _, project, graph = _project(tmp_path)
    snapshot = _snapshot(project.id, graph)

    assert snapshot.shadow_mode is True
    assert snapshot.current_graph_unchanged is True
    assert snapshot.selection.requires_user_confirmation is True
    assert snapshot.selection.automatic_selection_allowed is False
    assert len(snapshot.scenes[0].directions) == 3
    assert {
        item.direction for item in snapshot.scenes[0].directions
    } == set(CreativeDirection)
    assert all(
        set(score.dimension for score in direction.critique)
        == set(CritiqueDimension)
        for direction in snapshot.scenes[0].directions
    )
    payload = snapshot.model_dump(mode="python")
    payload["message"] = "tampered"
    with pytest.raises(ValueError, match="digest mismatch"):
        type(snapshot).model_validate(payload)


def test_store_preserves_revisions_and_records_truthful_control_requests(
    tmp_path: Path,
) -> None:
    _, project, graph = _project(tmp_path)
    running = _snapshot(
        project.id,
        graph,
        status=AgentUIRunStatus.RUNNING,
        stage=AgentUIStage.RENDERING,
    )
    ui_store = AgentUIStore(project.root)
    ui_store.save_snapshot(running)

    cancelled = ui_store.request_control(
        creative_agent.AgentUIControlAction.CANCEL,
        expected_revision=0,
        requested_at=NOW,
    )

    assert cancelled.snapshot_revision == 1
    assert cancelled.status == AgentUIRunStatus.RUNNING
    assert cancelled.cancellation_requested is True
    assert ui_store.control_path.is_file()
    assert (ui_store.root / "ui-snapshot-000000.json").is_file()
    assert (ui_store.root / "ui-snapshot-000001.json").is_file()
    with pytest.raises(ValueError, match="stale"):
        ui_store.request_control(
            creative_agent.AgentUIControlAction.CANCEL,
            expected_revision=0,
        )


def test_store_migrates_only_a_valid_pre_skipped_stages_snapshot(
    tmp_path: Path,
) -> None:
    _, project, graph = _project(tmp_path)
    snapshot = _snapshot(project.id, graph)
    ui_store = AgentUIStore(project.root)
    payload = snapshot.model_dump(mode="json")
    payload.pop("skipped_stages")
    payload["snapshot_digest"] = "0" * 64
    payload["snapshot_digest"] = canonical_sha256(payload)
    ui_store.root.mkdir(parents=True)
    ui_store.current_snapshot_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    migrated = ui_store.load_snapshot()

    assert migrated is not None
    assert migrated.skipped_stages == []
    assert migrated.snapshot_digest != payload["snapshot_digest"]

    tampered = payload | {"message": "tampered"}
    ui_store.current_snapshot_path.write_text(
        json.dumps(tampered, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="digest mismatch"):
        ui_store.load_snapshot()


def test_preference_memory_is_project_user_scoped_exportable_and_deletable(
    tmp_path: Path,
) -> None:
    _, project, _ = _project(tmp_path)
    ui_store = AgentUIStore(project.root)
    entry = AgentPreferenceEntry(
        entry_id="preference:001",
        project_id=project.id,
        user_scope_id="user-local",
        selected_candidate_id="candidate:faithful",
        compared_candidate_ids=[
            "candidate:faithful",
            "candidate:counterpoint",
        ],
        preferred_strength=0.6,
        recorded_at=NOW,
    )

    memory = ui_store.add_preference(entry)
    loaded = ui_store.load_preferences("user-local")

    assert memory == loaded
    assert loaded.entries == [entry]
    assert "user-local" in str(ui_store.preference_path("user-local"))
    ui_store.delete_preferences("user-local")
    assert ui_store.load_preferences("user-local").entries == []


def test_preference_api_accepts_json_datetime_and_preserves_strict_domain(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store, project, _ = _project(tmp_path)
    monkeypatch.setattr(creative_agent, "project_store", lambda: store)
    request = creative_agent.AgentPreferenceAPIRequest.model_validate(
        {
            "entry_id": "preference:api",
            "project_id": project.id,
            "user_scope_id": "browser-user",
            "selected_candidate_id": "candidate:faithful",
            "compared_candidate_ids": [
                "candidate:faithful",
                "candidate:counterpoint",
            ],
            "preferred_strength": None,
            "recorded_at": "2026-07-30T04:00:00Z",
        }
    )

    memory = creative_agent.add_creative_agent_preference(
        project.id,
        "browser-user",
        request,
    )

    assert memory.entries[0].recorded_at == NOW
    assert isinstance(memory.entries[0], AgentPreferenceEntry)


def test_explicit_apply_saves_undo_and_rejects_stale_or_unretained_candidate(
    tmp_path: Path,
) -> None:
    store, project, graph = _project(tmp_path)
    ui_store = AgentUIStore(project.root)
    snapshot = _snapshot(project.id, graph)
    ui_store.save_snapshot(snapshot)
    candidate = _candidate_graph(graph)
    candidate_dir = project.root / "creative-agent" / "candidates"
    candidate_dir.mkdir(parents=True)
    candidate_path = candidate_dir / "faithful.json"
    undo_path = candidate_dir / "faithful-undo.json"
    candidate_path.write_text(candidate.model_dump_json(indent=2), encoding="utf-8")
    undo_path.write_text(graph.model_dump_json(indent=2), encoding="utf-8")
    manifest = AgentApplicationManifest(
        project_id=project.id,
        run_id=snapshot.run_id,
        source_graph_digest=graph_digest(graph),
        candidates=[
            CandidateApplicationAsset(
                candidate_id="candidate:faithful",
                graph_relative_path=candidate_path.relative_to(project.root).as_posix(),
                graph_digest=graph_digest(candidate),
                undo_graph_relative_path=undo_path.relative_to(project.root).as_posix(),
                application_scopes=[
                    StrategyScope(
                        project_id=project.id,
                        scene_id="scene_001",
                    )
                ],
            )
        ],
    )
    ui_store.save_application_manifest(manifest)

    result = apply_agent_candidate(
        store=store,
        project_id=project.id,
        request=AgentApplyRequest(
            candidate_id="candidate:faithful",
            expected_graph_digest=graph_digest(graph),
            expected_snapshot_revision=0,
            confirmation=True,
        ),
    )

    assert result.previous_graph_digest == graph_digest(graph)
    assert result.applied_graph_digest == graph_digest(candidate)
    assert graph_digest(store.load_graph(project.id)) == graph_digest(candidate)
    assert (project.root / result.undo_revision).is_file()
    applied_snapshot = ui_store.load_snapshot()
    assert applied_snapshot is not None
    assert applied_snapshot.snapshot_revision == 1
    assert applied_snapshot.shadow_mode is False
    assert applied_snapshot.current_graph_unchanged is False
    assert applied_snapshot.current_graph_digest == graph_digest(candidate)
    assert applied_snapshot.selection.applied_candidate_id == "candidate:faithful"
    assert applied_snapshot.selection.undo_revision == result.undo_revision
    assert applied_snapshot.selection.requires_user_confirmation is False

    store.save_graph(project, graph)
    restored_snapshot = ui_store.reconcile_graph(graph, updated_at=NOW)
    assert restored_snapshot is not None
    assert restored_snapshot.snapshot_revision == 2
    assert restored_snapshot.status == AgentUIRunStatus.READY_FOR_REVIEW
    assert restored_snapshot.shadow_mode is True
    assert restored_snapshot.current_graph_unchanged is True
    assert restored_snapshot.selection.applied_candidate_id is None
    assert restored_snapshot.selection.requires_user_confirmation is True

    with pytest.raises(ValueError, match="stale"):
        apply_agent_candidate(
            store=store,
            project_id=project.id,
            request=AgentApplyRequest(
                candidate_id="candidate:faithful",
                expected_graph_digest=graph_digest(graph),
                expected_snapshot_revision=1,
                confirmation=True,
            ),
        )


def test_external_graph_change_marks_frozen_agent_run_stale(
    tmp_path: Path,
) -> None:
    _, project, graph = _project(tmp_path)
    ui_store = AgentUIStore(project.root)
    ui_store.save_snapshot(_snapshot(project.id, graph))
    changed = _candidate_graph(graph)

    reconciled = ui_store.reconcile_graph(changed, updated_at=NOW)

    assert reconciled is not None
    assert reconciled.status == AgentUIRunStatus.FAILED
    assert reconciled.selection.status == "stale-source-graph-changed"
    assert reconciled.last_error is not None
    assert reconciled.current_graph_digest == graph_digest(changed)


async def test_idle_api_is_truthful_and_control_route_reports_conflicts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store, project, graph = _project(tmp_path)
    monkeypatch.setattr(creative_agent, "project_store", lambda: store)

    idle = creative_agent.get_creative_agent_snapshot(project.id)

    assert idle == idle_agent_ui_snapshot(
        project_id=project.id,
        graph=graph,
        updated_at=idle.updated_at,
    )
    assert idle.status == AgentUIRunStatus.IDLE
    assert idle.scenes == []
    assert idle.provider.network_enabled is False
    with pytest.raises(HTTPException) as raised:
        await creative_agent.control_creative_agent(
            project.id,
            creative_agent.AgentControlAPIRequest(
                action="cancel",
                expected_snapshot_revision=0,
            ),
        )
    assert raised.value.status_code == 409


async def test_start_api_runs_real_offline_shadow_job_without_graph_mutation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = ProjectStore(tmp_path / "projects")
    project = store.create("Offline Creative Agent")
    source = project.input_dir / "source.avi"
    _write_evidence_video(source)
    graph = build_initial_graph(
        project_id=project.id,
        project_name="Offline Creative Agent",
        media=MediaInfo(
            path=str(source),
            duration_seconds=2,
            width=64,
            height=36,
            fps=10,
            frame_count=20,
            codec="mjpeg",
            input_color_space=ColorSpace.BT709_OETF,
        ),
        shot_ranges=[
            TimeRange(start_seconds=0, end_seconds=1),
            TimeRange(start_seconds=1, end_seconds=2),
        ],
        representative_frames=[Path("shot-1.jpg"), Path("shot-2.jpg")],
        scene_groups=[[0], [1]],
    )
    store.save_graph(project, graph)
    manager = JobManager()
    backend = TorchComputeBackend("cpu")
    monkeypatch.setattr(creative_agent, "project_store", lambda: store)
    monkeypatch.setattr(creative_agent, "job_manager", manager)
    monkeypatch.setattr(creative_agent, "compute_backend", lambda: backend)
    original_digest = graph_digest(graph)

    started = await creative_agent.start_creative_agent_run(
        project.id,
        creative_agent.AgentStartAPIRequest(
            user_intent="Keep both scenes restrained.",
        ),
    )

    assert started.status == JobStatus.QUEUED
    assert started.mode == "offline_shadow"
    assert started.snapshot.status == AgentUIRunStatus.RUNNING
    assert started.snapshot.shadow_mode is True
    assert started.snapshot.current_graph_unchanged is True

    for _ in range(200):
        job = await manager.get(started.job_id)
        if job.status in {JobStatus.COMPLETED, JobStatus.FAILED}:
            break
        await asyncio.sleep(0.05)
    else:  # pragma: no cover - deterministic local fixture completes quickly
        pytest.fail("offline creative Agent job did not finish")

    assert job.status == JobStatus.COMPLETED, job.error
    snapshot = creative_agent.get_creative_agent_snapshot(project.id)
    assert snapshot.status == AgentUIRunStatus.OFFLINE_FALLBACK
    assert snapshot.stage == AgentUIStage.READY
    assert len(snapshot.scenes) == 2
    assert all(len(scene.directions) == 3 for scene in snapshot.scenes)
    assert snapshot.skipped_stages == [
        AgentUIStage.CRITICIZING,
        AgentUIStage.REFINING,
    ]
    assert graph_digest(store.load_graph(project.id)) == original_digest
