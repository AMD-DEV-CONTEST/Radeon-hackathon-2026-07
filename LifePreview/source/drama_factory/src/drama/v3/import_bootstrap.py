from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

from shared_contracts import FactoryDocument, FactoryProjectSnapshot, VideoResolution

from ..imports import FactoryImportRevision, load_revision_snapshot
from .domain import (
    Clip,
    ClipContract,
    DirectorState,
    FactoryProjectState,
    ProjectRevision,
    Scene,
)
from .state_store import FactoryStateStore


_PROJECT_NAMESPACE = UUID("f9b3df04-0e5a-56ea-a387-83fc10e93ad5")
_SCENE_NAMESPACE = UUID("f6167144-3936-5c1e-a239-fea52af54374")
_CLIP_NAMESPACE = UUID("2432c54e-0812-536f-915f-baa46fb65d15")
_OUTBOX_NAMESPACE = UUID("356ac30c-20dd-5eca-995a-615357402867")


class ImportBootstrapError(RuntimeError):
    pass


def _documents(snapshot: FactoryProjectSnapshot) -> dict[FactoryDocument, dict]:
    output: dict[FactoryDocument, dict] = {}
    for document in snapshot.documents:
        try:
            value = json.loads(document.content_json)
        except json.JSONDecodeError:
            raise ImportBootstrapError(
                "factory import document is invalid"
            ) from None
        if not isinstance(value, dict):
            raise ImportBootstrapError("factory import document must be an object")
        output[document.document] = value
    return output


def _shots(document: dict[str, Any]) -> list[dict[str, Any]]:
    episodes = document.get("episodes")
    if not isinstance(episodes, dict):
        return []
    output: list[dict[str, Any]] = []
    for episode_id in sorted(episodes):
        episode = episodes[episode_id]
        if not isinstance(episode, dict):
            raise ImportBootstrapError("factory episode shot list is invalid")
        shots = episode.get("shots") or ()
        if not isinstance(shots, list):
            raise ImportBootstrapError("factory episode shots are invalid")
        for shot in shots:
            if not isinstance(shot, dict):
                raise ImportBootstrapError("factory shot is invalid")
            output.append(shot)
    return output


def bootstrap_import_revision(
    revision_root: str | Path,
    project_root: str | Path,
) -> tuple[FactoryImportRevision, FactoryProjectState]:
    import_revision, snapshot = load_revision_snapshot(revision_root)
    docs = _documents(snapshot)
    story = docs.get(FactoryDocument.STORY_BIBLE, {})
    scene_bible = docs.get(FactoryDocument.SCENE_BIBLE, {})
    shot_list = docs.get(FactoryDocument.SHOT_LIST, {})
    shots = _shots(shot_list)
    project_id = uuid5(
        _PROJECT_NAMESPACE,
        f"{import_revision.project_key}:{import_revision.revision_id}",
    )
    scene_details = {
        str(item.get("scene_id")): item
        for item in scene_bible.get("scenes", ())
        if isinstance(item, dict) and item.get("scene_id")
    }
    scene_names: list[str] = []
    for shot in shots:
        scene_name = str(shot.get("scene_id") or "unassigned")
        if scene_name not in scene_names:
            scene_names.append(scene_name)
    scenes = tuple(
        Scene(
            scene_id=uuid5(
                _SCENE_NAMESPACE,
                f"{import_revision.revision_id}:{name}",
            ),
            project_revision_id=import_revision.revision_id,
            order=index,
            narrative_spine=str(
                story.get("logline")
                or story.get("novel_title")
                or f"场景 {name}"
            ),
            continuity_state={
                "source_scene_id": name,
                "source_scene": scene_details.get(name, {}),
            },
            reanchor_policy="block",
        )
        for index, name in enumerate(scene_names)
    )
    scene_ids = {
        name: scene.scene_id for name, scene in zip(scene_names, scenes)
    }
    aspect_ratio = str(story.get("aspect_ratio") or "9:16")
    if ":" not in aspect_ratio:
        aspect_ratio = "9:16"
    clips: list[Clip] = []
    for index, shot in enumerate(shots):
        source_shot_id = str(shot.get("shot_id") or f"shot-{index + 1}")
        scene_name = str(shot.get("scene_id") or "unassigned")
        action = str(shot.get("action") or "").strip() or "完成当前分镜动作"
        emotion = str(shot.get("emotion") or "").strip() or action
        scene_detail = scene_details.get(scene_name, {})
        characters = tuple(str(item) for item in shot.get("characters", ()) if item)
        clips.append(
            Clip(
                clip_id=uuid5(
                    _CLIP_NAMESPACE,
                    f"{import_revision.revision_id}:{source_shot_id}",
                ),
                scene_id=scene_ids[scene_name],
                order=index,
                felt_intent=emotion,
                narrative_job=action,
                locks=(
                    (
                        f"角色身份：{'、'.join(characters)}"
                        if characters
                        else "保持当前主体身份"
                    ),
                    f"场景身份：{scene_name}",
                ),
                contract=ClipContract(
                    duration_seconds=float(shot.get("duration_sec") or 4.0),
                    aspect_ratio=aspect_ratio,
                    resolution=VideoResolution(width=720, height=1280),
                    camera=str(shot.get("camera_motion") or "固定镜头"),
                    motion=str(shot.get("video_prompt_en") or action),
                    lighting=str(
                        scene_detail.get("lighting")
                        or "使用场景内可见光源形成主光"
                    ),
                    exclusions=tuple(
                        value.strip()
                        for value in str(
                            shot.get("negative_prompt") or ""
                        ).split(",")
                        if value.strip()
                    ),
                ),
                director_state=DirectorState(
                    directing_voice=str(
                        story.get("visual_style")
                        or "克制、清晰、以叙事动作优先"
                    ),
                    narrative_spine=str(
                        story.get("logline")
                        or story.get("novel_title")
                        or "完成当前项目叙事"
                    ),
                    felt_intent=emotion,
                    narrative_job=action,
                    primary_spend="motion",
                    planned_end_state={"action_endpoint": action},
                ),
            )
        )
    manifest_path = Path(revision_root) / "import_manifest.json"
    created_at = datetime.fromtimestamp(
        manifest_path.stat().st_mtime,
        tz=timezone.utc,
    )
    project_revision = ProjectRevision(
        project_id=project_id,
        revision_id=import_revision.revision_id,
        parent_revision_id=import_revision.base_revision_id,
        content_hash=import_revision.revision_sha256,
        created_at=created_at,
        source_kind="native",
    )
    state = FactoryStateStore(project_root).initialize(
        project_revision=project_revision,
        scenes=scenes,
        clips=tuple(clips),
        initialized_at=created_at,
        outbox_event_id=uuid5(
            _OUTBOX_NAMESPACE,
            str(import_revision.revision_id),
        ),
    )
    return import_revision, state
