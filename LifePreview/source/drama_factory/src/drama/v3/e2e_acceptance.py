from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid5

from shared_contracts import GenerationMode

from .artifact_catalog import FactoryArtifactCatalog
from .audio_pipeline import (
    AudioPlan,
    DialogueCue,
    LocalDeliveryPipeline,
    TTSProvider,
)
from .domain import FactoryQCVerdict, HumanVerdict
from .quality import FactoryTechnicalQC
from .smoke import _SMOKE_NAMESPACE
from .state_store import FactoryStateStore


def finalize_smoke_project(
    project_root: str | Path,
    *,
    tts: TTSProvider,
    actor_id: str = "human.r3-smoke",
):
    """Exercise the immutable reject/NeedsHuman/accept/delivery gates."""
    store = FactoryStateStore(project_root)
    catalog = FactoryArtifactCatalog(project_root)
    qc = FactoryTechnicalQC()
    state = store.load()
    verdicts = {
        GenerationMode.T2V: FactoryQCVerdict.PASS,
        GenerationMode.I2V: FactoryQCVerdict.FAIL,
        GenerationMode.FIRST_LAST_FRAME: FactoryQCVerdict.NEEDS_HUMAN,
    }
    accepted_visual = None
    for mode, verdict in verdicts.items():
        run = next(item for item in state.runs if item.request.mode is mode)
        take = next(
            item for item in state.visual_takes if item.run_id == run.run_id
        )
        if take.factory_qc_evaluation_id is None:
            evaluation = qc.evaluate(
                subject_type="visual_take",
                subject_id=take.visual_take_id,
                artifact_ref=take.raw_video_ref,
                media_path=catalog.resolve(take.raw_video_ref),
                expected_resolution=run.request.resolution,
                expected_duration_seconds=run.request.duration_seconds,
                forced_verdict=verdict,
            )
            state = store.record_visual_qc(
                take.visual_take_id,
                evaluation=evaluation,
                expected_state_version=state.state_version,
            )
            take = next(
                item
                for item in state.visual_takes
                if item.visual_take_id == take.visual_take_id
            )
        if mode is GenerationMode.T2V:
            accepted_visual = take

    if accepted_visual is None:
        raise RuntimeError("smoke T2V visual take is unavailable")
    if not any(
        item.visual_take_id == accepted_visual.visual_take_id
        for item in state.continuity_acceptances
    ):
        state = store.apply_visual_verdict(
            accepted_visual.visual_take_id,
            verdict=HumanVerdict.KEEP,
            actor_id=actor_id,
            idempotency_key="r3-smoke:keep:t2v",
            expected_canon_version=0,
            expected_state_version=state.state_version,
        )
    accepted_visual = next(
        item
        for item in state.visual_takes
        if item.visual_take_id == accepted_visual.visual_take_id
    )

    if not state.delivery_takes:
        plan = AudioPlan(
            plan_id=uuid5(_SMOKE_NAMESPACE, "r3-smoke-audio-plan"),
            visual_take_id=accepted_visual.visual_take_id,
            duration_ms=3000,
            dialogue=(
                DialogueCue(
                    cue_id=uuid5(_SMOKE_NAMESPACE, "r3-smoke-dialogue"),
                    start_ms=200,
                    end_ms=2800,
                    text="信已经看完了，该往前走了。",
                    language="Chinese",
                    speaker="Vivian",
                    instruction="克制、坚定、低声说出",
                ),
            ),
            ambience_prompt="安静室内的轻微底噪",
            sfx_prompt="纸张轻响",
            music_prompt="极弱的低频氛围铺底",
            lipsync_required=False,
            created_at=datetime.now(timezone.utc),
        )
        state = LocalDeliveryPipeline(
            store=store,
            catalog=catalog,
            tts=tts,
        ).build(
            plan,
            expected_state_version=state.state_version,
        )
    delivery = state.delivery_takes[-1]
    if delivery.factory_qc_evaluation_id is None:
        run = next(
            item
            for item in state.runs
            if item.run_id
            == next(
                visual.run_id
                for visual in state.visual_takes
                if visual.visual_take_id == delivery.visual_take_id
            )
        )
        evaluation = qc.evaluate(
            subject_type="delivery_take",
            subject_id=delivery.delivery_take_id,
            artifact_ref=delivery.final_composite_ref,
            media_path=catalog.resolve(delivery.final_composite_ref),
            expected_resolution=run.request.resolution,
            expected_duration_seconds=run.request.duration_seconds,
        )
        state = store.record_delivery_qc(
            delivery.delivery_take_id,
            evaluation=evaluation,
            expected_state_version=state.state_version,
        )
        delivery = next(
            item
            for item in state.delivery_takes
            if item.delivery_take_id == delivery.delivery_take_id
        )
    if not any(
        item.delivery_take_id == delivery.delivery_take_id
        for item in state.delivery_acceptances
    ):
        state = store.accept_delivery(
            delivery.delivery_take_id,
            actor_id=actor_id,
            expected_delivery_version=0,
            expected_state_version=state.state_version,
        )
    return state
