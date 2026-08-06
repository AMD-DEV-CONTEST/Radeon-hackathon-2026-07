from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid5

from shared_contracts import (
    CloudExecutionPolicySnapshot,
    FallbackPolicySnapshot,
    FirstLastFrameRequest,
    GenerationMode,
    ImageToVideoRequest,
    TextToVideoRequest,
    VideoResolution,
    stable_json_sha256,
)

from ..runtime import atomic_write_json
from ..seeding import derive_initial_seed
from .artifact_catalog import FactoryArtifactCatalog
from .domain import (
    Clip,
    ClipContract,
    DirectorState,
    ProjectRevision,
    Scene,
)
from .model_registry import LocalModelRegistry
from .prompt_compiler import CompiledWanPrompt, WanPromptCompiler
from .state_store import FactoryStateStore


_SMOKE_NAMESPACE = UUID("b06ed80a-ff5c-5501-a8a4-e083af5a2ad2")
_RESOLUTION = VideoResolution(width=480, height=832)


@dataclass(frozen=True, slots=True)
class PreparedSmokeProject:
    project_root: Path
    project_id: UUID
    scene_id: UUID
    run_ids: dict[GenerationMode, UUID]


def _hashed_contract(model, payload: dict):
    identity = model.model_construct(
        **payload,
        snapshot_sha256="0" * 64,
    ).model_dump(mode="json", exclude={"snapshot_sha256"})
    return model(
        **identity,
        snapshot_sha256=stable_json_sha256(identity),
    )


def _clip(
    *,
    clip_id: UUID,
    scene_id: UUID,
    order: int,
    narrative_job: str,
    start_state: dict,
    end_state: dict,
) -> Clip:
    return Clip(
        clip_id=clip_id,
        scene_id=scene_id,
        order=order,
        felt_intent="克制地从迟疑推进到行动",
        narrative_job=narrative_job,
        locks=("同一灰色外套、木桌、暖色台灯保持不变",),
        contract=ClipContract(
            duration_seconds=3,
            aspect_ratio="9:16",
            resolution=_RESOLUTION,
            camera="固定中近景，轻微缓慢推近",
            motion=narrative_job,
            lighting="左侧暖色台灯为唯一主光，背景保留弱冷色轮廓",
        ),
        director_state=DirectorState(
            directing_voice="克制、亲密、动作可读",
            narrative_spine="人物结束回避并准备作出选择",
            felt_intent="克制地从迟疑推进到行动",
            narrative_job=narrative_job,
            primary_spend="motion",
            planned_start_state=start_state,
            planned_end_state=end_state,
        ),
    )


def prepare_smoke_project(
    project_root: str | Path,
    *,
    first_image: str | Path,
    last_image: str | Path,
    registry: LocalModelRegistry,
    t2v_model_id: str = "wan2.2-ti2v-5b",
    prepared_at: datetime | None = None,
) -> PreparedSmokeProject:
    root = Path(project_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    store = FactoryStateStore(root)
    if store.state_path.is_file():
        now = store.load().project_revision.created_at
    else:
        now = prepared_at or datetime.now(timezone.utc)
    project_id = uuid5(_SMOKE_NAMESPACE, "r3-local-e2e-project")
    revision_id = uuid5(_SMOKE_NAMESPACE, "r3-local-e2e-revision")
    scene_id = uuid5(_SMOKE_NAMESPACE, "r3-local-e2e-scene")
    clip_ids = {
        GenerationMode.T2V: uuid5(_SMOKE_NAMESPACE, "r3-local-e2e-t2v-clip"),
        GenerationMode.I2V: uuid5(_SMOKE_NAMESPACE, "r3-local-e2e-i2v-clip"),
        GenerationMode.FIRST_LAST_FRAME: uuid5(
            _SMOKE_NAMESPACE,
            "r3-local-e2e-flf-clip",
        ),
    }
    clips = (
        _clip(
            clip_id=clip_ids[GenerationMode.T2V],
            scene_id=scene_id,
            order=0,
            narrative_job="人物低头读信，右手把信缓慢折好",
            start_state={"pose": "低头读信", "prop": "信展开"},
            end_state={"pose": "仍低头", "prop": "信已折好"},
        ),
        _clip(
            clip_id=clip_ids[GenerationMode.I2V],
            scene_id=scene_id,
            order=1,
            narrative_job="人物把折好的信放到木桌中央并抬眼",
            start_state={"pose": "低头", "prop": "手持折好的信"},
            end_state={"pose": "抬眼", "prop": "信在木桌中央"},
        ),
        _clip(
            clip_id=clip_ids[GenerationMode.FIRST_LAST_FRAME],
            scene_id=scene_id,
            order=2,
            narrative_job="人物从坐姿平稳起身，停在桌边",
            start_state={"pose": "坐在桌边并抬眼"},
            end_state={"pose": "站在桌边", "prop": "信留在桌面"},
        ),
    )
    revision_payload = {
        "project_id": str(project_id),
        "revision_id": str(revision_id),
        "scene_id": str(scene_id),
        "clips": [item.model_dump(mode="json") for item in clips],
    }
    revision = ProjectRevision(
        project_id=project_id,
        revision_id=revision_id,
        content_hash=stable_json_sha256(revision_payload),
        created_at=now,
    )
    scene = Scene(
        scene_id=scene_id,
        project_revision_id=revision_id,
        order=0,
        narrative_spine="人物在暖色台灯下结束回避并起身",
        continuity_state={
            "location": "木桌旁",
            "wardrobe": "灰色外套",
            "key_light": "左侧暖色台灯",
        },
    )
    state = store.initialize(
        project_revision=revision,
        scenes=(scene,),
        clips=clips,
        initialized_at=now,
        outbox_event_id=uuid5(_SMOKE_NAMESPACE, "r3-smoke-initialized"),
    )

    catalog = FactoryArtifactCatalog(root)
    first = catalog.import_image(
        first_image,
        role="r3_smoke_first_frame",
        artifact_id=uuid5(_SMOKE_NAMESPACE, "r3-smoke-first-image"),
    )
    last = catalog.import_image(
        last_image,
        role="r3_smoke_last_frame",
        artifact_id=uuid5(_SMOKE_NAMESPACE, "r3-smoke-last-image"),
    )
    models = {
        GenerationMode.T2V: t2v_model_id,
        GenerationMode.I2V: "wan2.2-i2v-a14b-fp8",
        GenerationMode.FIRST_LAST_FRAME: "wan2.2-i2v-a14b-fp8",
    }
    run_ids: dict[GenerationMode, UUID] = {}
    for mode in (
        GenerationMode.T2V,
        GenerationMode.I2V,
        GenerationMode.FIRST_LAST_FRAME,
    ):
        run_id = uuid5(_SMOKE_NAMESPACE, f"r3-local-e2e-{mode.value}-run")
        prompt_id = uuid5(
            _SMOKE_NAMESPACE,
            f"r3-local-e2e-{mode.value}-prompt",
        )
        fallback_id = uuid5(
            _SMOKE_NAMESPACE,
            f"r3-local-e2e-{mode.value}-fallback",
        )
        seed = derive_initial_seed(
            project_revision_id=str(revision_id),
            clip_id=str(clip_ids[mode]),
            generation_mode=mode.value,
            model_id=models[mode],
        )
        common = {
            "project_revision_id": revision_id,
            "scene_id": scene_id,
            "clip_id": clip_ids[mode],
            "run_id": run_id,
            "prompt_snapshot_id": prompt_id,
            "prompt_compiler_version": WanPromptCompiler.VERSION,
            "resolved_seed": seed.resolved_seed,
            "seed_derivation_version": seed.seed_derivation_version,
            "seed_input_hash": seed.seed_input_hash,
            "attempt_index": 0,
            "duration_seconds": 3,
            "aspect_ratio": "9:16",
            "resolution": _RESOLUTION,
            "audio_intent": "视觉生成阶段保持静音",
            "model_id": models[mode],
            "capability_snapshot_id": registry.capability(
                model_id=models[mode],
                mode=mode,
            ).capability_id,
            "fallback_policy_snapshot_id": fallback_id,
            "idempotency_key": f"r3-smoke:{mode.value}",
        }
        if mode is GenerationMode.T2V:
            request = TextToVideoRequest(**common)
        elif mode is GenerationMode.I2V:
            request = ImageToVideoRequest(**common, first_image=first)
        else:
            request = FirstLastFrameRequest(
                **common,
                first_image=first,
                last_image=last,
            )
        fallback = _hashed_contract(
            FallbackPolicySnapshot,
            {
                "snapshot_id": fallback_id,
                "policy_version": 1,
                "default_block": True,
                "allowed_changes": (),
                "fallback_model_ids": (),
                "fallback_resolutions": (),
                "created_by_actor": "human.r3-smoke",
                "created_at": now,
            },
        )
        cloud = _hashed_contract(
            CloudExecutionPolicySnapshot,
            {
                "snapshot_id": uuid5(
                    _SMOKE_NAMESPACE,
                    f"r3-local-e2e-{mode.value}-cloud",
                ),
                "project_id": project_id,
                "run_id": run_id,
                "policy_version": 1,
                "provider_allowlist": (),
                "allowed_data_types": (),
                "provider_retention_notice": None,
                "consented_at": None,
                "created_by_actor": "human.r3-smoke",
                "created_at": now,
            },
        )
        capability = registry.capability(model_id=models[mode], mode=mode)
        clip = next(item for item in clips if item.clip_id == clip_ids[mode])
        compiled = WanPromptCompiler().compile(
            clip=clip,
            request=request,
            capability=capability,
            steps=4,
            cfg=1,
        )
        prompt_path = store.root / "prompts" / f"{prompt_id}.json"
        if prompt_path.is_file():
            existing = prompt_path.read_text(encoding="utf-8")
            if CompiledWanPrompt.model_validate_json(existing) != compiled:
                raise RuntimeError("smoke prompt snapshot identity conflict")
        else:
            atomic_write_json(prompt_path, compiled.model_dump(mode="json"))
        state = store.create_run(
            request=request,
            fallback_policy=fallback,
            cloud_policy=cloud,
            expected_state_version=state.state_version,
        )
        run_ids[mode] = run_id
    return PreparedSmokeProject(
        project_root=root,
        project_id=project_id,
        scene_id=scene_id,
        run_ids=run_ids,
    )
