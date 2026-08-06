from __future__ import annotations

import json
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator
from shared_contracts import (
    ArtifactRef,
    AtomicArtifactRef,
    CompiledPromptBundleV1,
    ComponentName,
    DirectionContractV1,
    GenerationMode,
    GenerationRequest,
    ModelCapability,
    ReferenceDuty,
    VideoResolution,
    stable_json_sha256,
)

from .agents.asset_generator import AssetGenerator
from .agents.asset_planner import AssetPlanner
from .agents.assembler import Assembler
from .agents.character_designer import CharacterDesigner
from .agents.keyframe_generator import KeyframeGenerator
from .agents.novel_splitter import NovelSplitter
from .agents.scene_designer import SceneDesigner
from .agents.story_bible import StoryBibleAgent, sanitize_visual_style
from .agents.storyboard import Storyboard
from .agents.subtitle_agent import SubtitleAgent
from .agents.tts_agent import TTSAgent
from .atomic_factory import (
    FactoryArtifactGateway,
    FactoryAtomicContractError,
    FactoryCoreError,
    FactoryCoreOutput,
    FactoryProducedArtifact,
    FactoryProviderOutcomeUnknown,
)
from .atomic_plugin import KeyframeProfile, keyframe_profile
from .context import Context
from .input_loader import load_text
from .schemas import (
    Chapter,
    ChapterManifest,
    CharacterBible,
    SceneBible,
    Shot,
    ShotList,
    StoryBible,
)
from .utils.ffmpeg import mux_audio
from .v3.audio_pipeline import (
    AudioAlignmentRevision,
    AudioAlignmentPolicyRevision,
    AudioPlan,
    DialogueCue,
    FinalAudioAuthorityResolver,
    FinalAudioTrack,
    TTSProvider,
    _write_aligned_srt,
    _run as run_media_command,
    assemble_shidu_delivery,
    compile_audio_alignment,
    derive_shidu_delivery_surfaces,
    materialize_shidu_audio_mix,
    materialize_shidu_tts_take,
    resolve_final_audio_tracks,
)
from .v3.domain import Clip, ClipContract, DirectorState
from .v3.model_registry import ModelSelectionBlocked, default_wan_registry
from .v3.prompt_compiler import CompiledWanPrompt, WanPromptCompiler
from .v3.workflows import WanQualityProfile, WanWorkflowBuilder


_GENERATION_REQUEST_ADAPTER = TypeAdapter(GenerationRequest)
_TWO_SHOT_SCHEMA_VERSION = "factory.two-shot-input.v1"
_EPISODE_PLAN_SCHEMA_VERSION = "factory.episode-plan.v1"


def _validate_keyframe_runtime_profile(
    context: Context,
    profile: KeyframeProfile,
) -> None:
    cfg = getattr(context, "cfg", None)
    if not callable(cfg):
        raise RuntimeError(
            "keyframe runtime configuration is unavailable"
        )

    missing = object()

    def configured(*keys: str, default: object = missing) -> object:
        try:
            return cfg(*keys, default=default)
        except Exception:
            raise RuntimeError(
                "keyframe runtime configuration is unavailable"
            ) from None

    core_only = configured("keyframe", "core_only", default=False)
    if not isinstance(core_only, bool):
        raise RuntimeError("keyframe runtime configuration does not match profile")

    if profile.provider_identity == "local-sdxl-comfy":
        matches = (
            core_only is True
            and configured("keyframe", "model_name") == "sdxl"
            and configured("keyframe", "checkpoint")
            == "sd_xl_base_1.0.safetensors"
            and configured("workflows", "keyframe")
            == "keyframe_flux_api.json"
        )
    elif profile.provider_identity == "local-qwen-image-comfy":
        matches = core_only is False
    else:
        matches = False
    if not matches:
        raise RuntimeError("keyframe runtime configuration does not match profile")


class _GenerationBlueprint(BaseModel):
    """Frame-independent portion of a strict GenerationRequest."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: GenerationMode
    duration_seconds: float = Field(gt=0, le=60)
    aspect_ratio: str = Field(pattern=r"^[1-9][0-9]?:[1-9][0-9]?$")
    resolution: VideoResolution
    audio_intent: str = Field(min_length=1, max_length=4_000)
    reference_duties: tuple[ReferenceDuty, ...] = Field(
        default=(),
        max_length=16,
    )
    reference_exclusions: tuple[str, ...] = Field(
        default=(),
        max_length=32,
    )
    model_id: str = Field(min_length=1, max_length=100)
    attempt_index: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def exclusions_are_unique(self):
        if len(self.reference_exclusions) != len(
            set(self.reference_exclusions)
        ):
            raise ValueError("reference exclusions must be unique")
        return self


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        indent=2,
    ).encode("utf-8")


def _json_artifact(value: object, role: str) -> FactoryProducedArtifact:
    return FactoryProducedArtifact(
        payload=_json_bytes(value),
        mime_type="application/json",
        logical_role=role,
    )


def _read_json(
    request,
    gateway: FactoryArtifactGateway,
    *roles: str,
) -> dict[str, Any]:
    artifact = _find_ref(request.input_artifact_refs, *roles)
    try:
        decoded = json.loads(gateway.read_bytes(artifact).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FactoryAtomicContractError(
            f"input artifact {artifact.logical_role} is not UTF-8 JSON"
        ) from exc
    if not isinstance(decoded, dict):
        raise FactoryAtomicContractError(
            f"input artifact {artifact.logical_role} must contain a JSON object"
        )
    return decoded


def _find_ref(
    refs: tuple[AtomicArtifactRef, ...],
    *roles: str,
) -> AtomicArtifactRef:
    role_set = set(roles)
    matches = [item for item in refs if item.logical_role in role_set]
    if len(matches) != 1:
        raise FactoryAtomicContractError(
            "expected exactly one input ArtifactRef with role "
            + " or ".join(sorted(role_set))
        )
    return matches[0]


def _find_optional_ref(
    refs: tuple[AtomicArtifactRef, ...],
    *roles: str,
) -> AtomicArtifactRef | None:
    role_set = set(roles)
    matches = [item for item in refs if item.logical_role in role_set]
    if len(matches) > 1:
        raise FactoryAtomicContractError(
            "expected at most one input ArtifactRef with role "
            + " or ".join(sorted(role_set))
        )
    return matches[0] if matches else None


def _media_suffix(mime_type: str) -> str:
    return {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "video/mp4": ".mp4",
        "video/webm": ".webm",
        "audio/wav": ".wav",
        "audio/mpeg": ".mp3",
        "application/x-subrip": ".srt",
    }.get(mime_type, ".bin")


def _materialize(
    gateway: FactoryArtifactGateway,
    artifact: AtomicArtifactRef,
    directory: Path,
) -> Path:
    destination = directory / (
        f"{artifact.artifact_id}{_media_suffix(artifact.mime_type)}"
    )
    destination.write_bytes(gateway.read_bytes(artifact))
    return destination


def _file_artifact(
    path: str | Path,
    *,
    role: str,
    mime_type: str,
) -> FactoryProducedArtifact:
    source = Path(path)
    if not source.is_file():
        raise FactoryCoreError(f"wrapped core did not produce {role}")
    return FactoryProducedArtifact(
        payload=source.read_bytes(),
        mime_type=mime_type,
        logical_role=role,
    )


def _as_contract_artifact(artifact: AtomicArtifactRef) -> ArtifactRef:
    """Convert Hub's transport ref into the immutable Factory domain ref."""

    return ArtifactRef(
        owner=ComponentName.DRAMA_FACTORY,
        artifact_id=artifact.artifact_id,
        sha256=artifact.content_digest,
        bytes=artifact.byte_size,
        mime=artifact.mime_type,
        version=1,
    )


def _validate_two_shot_spec(raw: object) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise FactoryAtomicContractError(
            "two-shot workflow input must be a JSON object"
        )
    if raw.get("schema_version") != _TWO_SHOT_SCHEMA_VERSION:
        raise FactoryAtomicContractError(
            f"two-shot schema_version must be {_TWO_SHOT_SCHEMA_VERSION}"
        )
    try:
        project_revision_id = UUID(str(raw["project_revision_id"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise FactoryAtomicContractError(
            "two-shot project_revision_id must be a UUID"
        ) from exc
    episode_id = str(raw.get("episode_id") or "").strip()
    if not episode_id:
        raise FactoryAtomicContractError(
            "two-shot episode_id must not be empty"
        )
    novel_title = str(raw.get("novel_title") or "").strip()
    character_payload = raw.get("character_bible")
    world_payload = raw.get("world_bible")
    if not isinstance(character_payload, dict) or not isinstance(
        world_payload, dict
    ):
        raise FactoryAtomicContractError(
            "two-shot character_bible and world_bible must be objects"
        )
    characters = CharacterBible.from_dict(character_payload)
    worlds = SceneBible.from_dict(world_payload)
    shot_entries = raw.get("shots")
    if not isinstance(shot_entries, list) or len(shot_entries) != 2:
        raise FactoryAtomicContractError(
            "two-shot workflow requires exactly two shot entries"
        )

    normalized_shots: list[dict[str, Any]] = []
    legacy_ids: set[str] = set()
    clip_ids: set[UUID] = set()
    for index, entry in enumerate(shot_entries):
        if not isinstance(entry, dict):
            raise FactoryAtomicContractError(
                f"two-shot shot {index} must be an object"
            )
        try:
            shot_raw = entry["shot"]
            clip_raw = entry["clip"]
            generation_raw = entry["generation"]
            capability_raw = entry["model_capability"]
            if not all(
                isinstance(value, dict)
                for value in (
                    shot_raw,
                    clip_raw,
                    generation_raw,
                    capability_raw,
                )
            ):
                raise TypeError
            shot = Shot(**shot_raw)
            clip = Clip.model_validate(clip_raw)
            generation = _GenerationBlueprint.model_validate(generation_raw)
            capability = ModelCapability.model_validate(capability_raw)
        except Exception as exc:
            raise FactoryAtomicContractError(
                f"two-shot shot {index} violates the Factory input contract"
            ) from exc
        if shot.episode_id != episode_id:
            raise FactoryAtomicContractError(
                f"two-shot shot {index} episode_id does not match the workflow"
            )
        if (
            clip.contract.duration_seconds != generation.duration_seconds
            or clip.contract.aspect_ratio != generation.aspect_ratio
            or clip.contract.resolution != generation.resolution
        ):
            raise FactoryAtomicContractError(
                f"two-shot shot {index} clip and generation contract differ"
            )
        if (
            capability.operation is not generation.mode
            or capability.model_id != generation.model_id
            or generation.resolution not in capability.supported_resolutions
            or generation.duration_seconds
            not in capability.supported_durations_seconds
            or not capability.local_only
        ):
            raise FactoryAtomicContractError(
                f"two-shot shot {index} is unsupported by its model capability"
            )
        if shot.shot_id.lower() in legacy_ids or clip.clip_id in clip_ids:
            raise FactoryAtomicContractError(
                "two-shot shot_id and clip_id values must be unique"
            )
        legacy_ids.add(shot.shot_id.lower())
        clip_ids.add(clip.clip_id)
        normalized_shots.append(
            {
                "shot": asdict(shot),
                "clip": clip.model_dump(mode="json"),
                "generation": generation.model_dump(mode="json"),
                "model_capability": capability.model_dump(mode="json"),
            }
        )

    return {
        "schema_version": _TWO_SHOT_SCHEMA_VERSION,
        "project_revision_id": str(project_revision_id),
        "episode_id": episode_id,
        "novel_title": novel_title,
        "character_bible": characters.to_dict(),
        "world_bible": worlds.to_dict(),
        "shots": normalized_shots,
    }


def _episode_text(value: object, *, limit: int, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise FactoryAtomicContractError(
            f"episode plan {field_name} must not be empty"
        )
    return text[:limit]


def _episode_optional_uuid(value: object, *, field_name: str) -> str | None:
    if value in (None, ""):
        return None
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError) as exc:
        raise FactoryAtomicContractError(
            f"episode plan {field_name} must be a UUID"
        ) from exc


def _episode_optional_digest(value: object, *, field_name: str) -> str | None:
    if value in (None, ""):
        return None
    digest = str(value).strip().lower()
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise FactoryAtomicContractError(
            f"episode plan {field_name} must be a SHA-256 digest"
        )
    return digest


def _episode_resolution(value: object) -> VideoResolution:
    if isinstance(value, dict):
        try:
            return VideoResolution.model_validate(value)
        except Exception as exc:
            raise FactoryAtomicContractError(
                "episode plan resolution is invalid"
            ) from exc
    normalized = str(value or "480p").strip().lower()
    aliases = {
        "480p": (480, 832),
        "480x832": (480, 832),
        "720p": (704, 1280),
        "704x1280": (704, 1280),
        "landscape-480p": (832, 480),
        "832x480": (832, 480),
        "landscape-720p": (1280, 704),
        "1280x704": (1280, 704),
    }
    try:
        width, height = aliases[normalized]
    except KeyError as exc:
        raise FactoryAtomicContractError(
            "episode plan resolution is unsupported"
        ) from exc
    return VideoResolution(width=width, height=height)


def _validate_episode_plan(raw: object) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise FactoryAtomicContractError(
            "episode plan must be a JSON object"
        )
    if raw.get("schema_version") != _EPISODE_PLAN_SCHEMA_VERSION:
        raise FactoryAtomicContractError(
            "episode plan schema_version is unsupported"
        )
    try:
        project_revision_id = UUID(str(raw["project_revision_id"]))
        project_id = UUID(str(raw["project_id"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise FactoryAtomicContractError(
            "episode plan project identities must be UUIDs"
        ) from exc
    episode_id = _episode_text(
        raw.get("episode_id"),
        limit=100,
        field_name="episode_id",
    )
    strategy = raw.get("generation_strategy")
    if not isinstance(strategy, dict):
        raise FactoryAtomicContractError(
            "episode plan generation_strategy must be an object"
        )
    shots = raw.get("shots")
    if not isinstance(shots, list) or not shots or len(shots) > 500:
        raise FactoryAtomicContractError(
            "episode plan shots must contain between 1 and 500 entries"
        )
    normalized_shots: list[dict[str, Any]] = []
    unit_keys: set[str] = set()
    shot_ids: set[str] = set()
    for index, entry in enumerate(shots, start=1):
        if not isinstance(entry, dict):
            raise FactoryAtomicContractError(
                f"episode plan shot {index} must be an object"
            )
        unit_key = _episode_text(
            entry.get("unit_key"),
            limit=100,
            field_name=f"shot {index} unit_key",
        )
        shot_id = _episode_text(
            entry.get("shot_id") or f"s{index:03d}",
            limit=100,
            field_name=f"shot {index} shot_id",
        ).lower()
        if any(
            character not in "abcdefghijklmnopqrstuvwxyz0123456789_-"
            for character in shot_id
        ):
            raise FactoryAtomicContractError(
                f"episode plan shot {index} shot_id is invalid"
            )
        ordinal = entry.get("ordinal")
        if isinstance(ordinal, bool) or ordinal != index:
            raise FactoryAtomicContractError(
                "episode plan shot ordinals must be contiguous from one"
            )
        if unit_key in unit_keys or shot_id in shot_ids:
            raise FactoryAtomicContractError(
                "episode plan unit_key and shot_id values must be unique"
            )
        unit_keys.add(unit_key)
        shot_ids.add(shot_id)
        try:
            mode = GenerationMode(
                str(
                    entry.get("generation_mode")
                    or strategy.get("generation_mode")
                    or "t2v"
                )
            )
        except ValueError as exc:
            raise FactoryAtomicContractError(
                f"episode plan shot {index} generation mode is invalid"
            ) from exc
        direction_contract = None
        if entry.get("direction_contract") is not None:
            try:
                direction_contract = DirectionContractV1.model_validate(
                    entry["direction_contract"]
                ).model_dump(mode="json")
            except Exception as exc:
                raise FactoryAtomicContractError(
                    f"episode plan shot {index} direction_contract is invalid"
                ) from exc
        compiled_prompt_bundle = None
        if entry.get("compiled_prompt_bundle") is not None:
            try:
                compiled_prompt_bundle = CompiledPromptBundleV1.model_validate(
                    entry["compiled_prompt_bundle"]
                ).model_dump(mode="json")
            except Exception as exc:
                raise FactoryAtomicContractError(
                    f"episode plan shot {index} compiled_prompt_bundle is invalid"
                ) from exc
        compiled_prompt_bundles: dict[str, Any] = {}
        raw_bundles = entry.get("compiled_prompt_bundles")
        if raw_bundles is not None:
            if not isinstance(raw_bundles, dict) or len(raw_bundles) > 8:
                raise FactoryAtomicContractError(
                    f"episode plan shot {index} compiled_prompt_bundles is invalid"
                )
            try:
                compiled_prompt_bundles = {
                    _episode_text(
                        role,
                        limit=100,
                        field_name=f"shot {index} compiled bundle role",
                    ): CompiledPromptBundleV1.model_validate(bundle).model_dump(
                        mode="json"
                    )
                    for role, bundle in raw_bundles.items()
                }
            except FactoryAtomicContractError:
                raise
            except Exception as exc:
                raise FactoryAtomicContractError(
                    f"episode plan shot {index} compiled_prompt_bundles is invalid"
                ) from exc
        prompt_compilation_id = _episode_optional_uuid(
            entry.get("prompt_compilation_id"),
            field_name=f"shot {index} prompt_compilation_id",
        )
        methodology_snapshot_id = _episode_optional_uuid(
            entry.get("methodology_snapshot_id"),
            field_name=f"shot {index} methodology_snapshot_id",
        )
        methodology_snapshot_digest = _episode_optional_digest(
            entry.get("methodology_snapshot_digest"),
            field_name=f"shot {index} methodology_snapshot_digest",
        )
        if prompt_compilation_id is not None and direction_contract is None:
            raise FactoryAtomicContractError(
                f"episode plan shot {index} has compiled lineage without a direction contract"
            )
        normalized = {
            "unit_key": unit_key,
            "shot_id": shot_id,
            "ordinal": index,
            "prompt": _episode_text(
                entry.get("prompt"),
                limit=20_000,
                field_name=f"shot {index} prompt",
            ),
            "generation_mode": mode.value,
        }
        for prompt_field in ("first_frame_prompt", "last_frame_prompt"):
            if entry.get(prompt_field) not in (None, ""):
                normalized[prompt_field] = _episode_text(
                    entry[prompt_field],
                    limit=20_000,
                    field_name=f"shot {index} {prompt_field}",
                )
        if direction_contract is not None:
            normalized["direction_contract"] = direction_contract
        if compiled_prompt_bundle is not None:
            normalized["compiled_prompt_bundle"] = compiled_prompt_bundle
        if compiled_prompt_bundles:
            normalized["compiled_prompt_bundles"] = compiled_prompt_bundles
        if prompt_compilation_id is not None:
            normalized["prompt_compilation_id"] = prompt_compilation_id
        if methodology_snapshot_id is not None:
            normalized["methodology_snapshot_id"] = methodology_snapshot_id
        if methodology_snapshot_digest is not None:
            normalized["methodology_snapshot_digest"] = methodology_snapshot_digest
        normalized_shots.append(normalized)
    return {
        "schema_version": _EPISODE_PLAN_SCHEMA_VERSION,
        "project_revision_id": str(project_revision_id),
        "project_id": str(project_id),
        "episode_id": episode_id,
        "novel_title": str(raw.get("novel_title") or "动态短剧")[:200],
        "generation_strategy": dict(strategy),
        "shots": normalized_shots,
    }


def _episode_shot(plan: dict[str, Any], entry: dict[str, Any]) -> Shot:
    prompt = str(entry["prompt"])
    duration = float(
        plan["generation_strategy"].get("duration_seconds") or 5.0
    )
    return Shot(
        shot_id=str(entry["shot_id"]),
        episode_id=str(plan["episode_id"]),
        chapter_id="CH001",
        scene_id=f"scene-{int(entry['ordinal']):03d}",
        duration_sec=duration,
        action=prompt[:4_000],
        visual_prompt_en=prompt[:4_000],
        video_prompt_en=prompt[:4_000],
        audio_notes=str(
            plan["generation_strategy"].get("audio_intent")
            or "保留与画面一致的环境声"
        )[:1_000],
    )


@dataclass(slots=True)
class LegacyFactoryOperationRunner:
    """Thin adapters over the existing agents and V3 generation cores.

    This class deliberately does not persist run state, schedule work, retry,
    or reconcile providers. It only converts ArtifactRef payloads to existing
    core inputs and converts their unchanged outputs back into artifacts.
    """

    context: Context
    prompt_compiler: WanPromptCompiler
    workflow_builder: WanWorkflowBuilder
    shidu_tts_provider: TTSProvider | None = None
    shidu_final_audio_authority_resolver: (
        FinalAudioAuthorityResolver | None
    ) = None

    @classmethod
    def create(
        cls,
        context: Context,
        *,
        shidu_tts_provider: TTSProvider | None = None,
        shidu_final_audio_authority_resolver: (
            FinalAudioAuthorityResolver | None
        ) = None,
    ) -> LegacyFactoryOperationRunner:
        return cls(
            context=context,
            prompt_compiler=WanPromptCompiler(),
            workflow_builder=WanWorkflowBuilder(),
            shidu_tts_provider=shidu_tts_provider,
            shidu_final_audio_authority_resolver=(
                shidu_final_audio_authority_resolver
            ),
        )

    def run(
        self,
        request,
        artifacts: FactoryArtifactGateway,
        /,
    ) -> FactoryCoreOutput:
        method = getattr(
            self,
            "_run_" + request.op_type.replace(".", "_"),
            None,
        )
        if method is None:
            raise FactoryAtomicContractError(
                f"legacy adapter does not support {request.op_type}"
            )
        try:
            return method(request, artifacts)
        except (FactoryAtomicContractError, FactoryCoreError):
            raise
        except Exception as exc:
            if (
                exc.__class__.__module__ == "drama.v3.durable_comfy"
                and exc.__class__.__name__ == "ComfySubmissionOutcomeUnknown"
            ):
                raise FactoryProviderOutcomeUnknown from exc
            raise FactoryCoreError from exc

    def _run_two_shot_bootstrap(self, request, gateway) -> FactoryCoreOutput:
        del gateway
        normalized = _validate_two_shot_spec(dict(request.structured_inputs))
        return FactoryCoreOutput(
            artifacts=(
                _json_artifact(normalized, "two_shot_spec"),
            ),
            structured_output={
                "schema_version": normalized["schema_version"],
                "shot_count": 2,
            },
            provider_identity="factory-local-core",
        )

    def _run_two_shot_plan(self, request, gateway) -> FactoryCoreOutput:
        spec = _validate_two_shot_spec(
            _read_json(request, gateway, "two_shot_spec")
        )
        shot_index = request.structured_inputs.get("shot_index")
        if (
            isinstance(shot_index, bool)
            or not isinstance(shot_index, int)
            or shot_index not in {0, 1}
        ):
            raise FactoryAtomicContractError(
                "two_shot.plan shot_index must be 0 or 1"
            )
        seed = request.parameter_snapshot.get("video_seed")
        if (
            isinstance(seed, bool)
            or not isinstance(seed, int)
            or seed < 1
            or seed > 2**63 - 1
        ):
            raise FactoryAtomicContractError(
                "two_shot.plan requires a pinned video_seed"
            )
        entry = spec["shots"][shot_index]
        shot = Shot(**entry["shot"])
        clip = Clip.model_validate(entry["clip"])
        blueprint = _GenerationBlueprint.model_validate(entry["generation"])
        capability = ModelCapability.model_validate(entry["model_capability"])
        prompt_snapshot_id = uuid5(
            request.workflow_run_id,
            f"two-shot:prompt:{clip.clip_id}",
        )
        generation_run_id = uuid5(
            request.workflow_run_id,
            f"two-shot:generation:{clip.clip_id}:{seed}",
        )
        fallback_policy_snapshot_id = uuid5(
            request.workflow_run_id,
            f"two-shot:fallback:{clip.clip_id}",
        )
        seed_input_hash = stable_json_sha256(
            {
                "project_revision_id": spec["project_revision_id"],
                "clip_id": str(clip.clip_id),
                "mode": blueprint.mode.value,
                "pinned_seed": seed,
                "seed_derivation_version": "catalog-pinned-v1",
            }
        )
        intent = {
            "project_revision_id": spec["project_revision_id"],
            "scene_id": str(clip.scene_id),
            "clip_id": str(clip.clip_id),
            "run_id": str(generation_run_id),
            "prompt_snapshot_id": str(prompt_snapshot_id),
            "prompt_compiler_version": WanPromptCompiler.VERSION,
            "resolved_seed": seed,
            "seed_derivation_version": "catalog-pinned-v1",
            "seed_input_hash": seed_input_hash,
            "attempt_index": blueprint.attempt_index,
            "duration_seconds": blueprint.duration_seconds,
            "aspect_ratio": blueprint.aspect_ratio,
            "resolution": blueprint.resolution.model_dump(mode="json"),
            "audio_intent": blueprint.audio_intent,
            "reference_duties": [
                item.model_dump(mode="json")
                for item in blueprint.reference_duties
            ],
            "reference_exclusions": list(
                blueprint.reference_exclusions
            ),
            "model_id": blueprint.model_id,
            "capability_snapshot_id": str(capability.capability_id),
            "fallback_policy_snapshot_id": str(
                fallback_policy_snapshot_id
            ),
            "idempotency_key": (
                f"{request.command_idempotency_key}:generation"
            ),
            "mode": blueprint.mode.value,
            "output_role": f"clip.{shot.shot_id.lower()}",
        }
        return FactoryCoreOutput(
            artifacts=(
                _json_artifact(asdict(shot), "shot"),
                _json_artifact(entry["clip"], "clip"),
                _json_artifact(
                    spec["character_bible"],
                    "character_bible",
                ),
                _json_artifact(spec["world_bible"], "world_bible"),
                _json_artifact(intent, "generation_intent"),
                _json_artifact(
                    entry["model_capability"],
                    "model_capability",
                ),
            ),
            structured_output={
                "shot_index": shot_index,
                "shot_id": shot.shot_id,
                "mode": blueprint.mode.value,
                "video_seed": seed,
                "output_role": intent["output_role"],
            },
            provider_identity="factory-local-core",
        )

    def _run_episode_shot_plan(self, request, gateway) -> FactoryCoreOutput:
        plan = _validate_episode_plan(
            _read_json(request, gateway, "episode_plan")
        )
        ordinal = request.structured_inputs.get("ordinal")
        unit_key = str(request.structured_inputs.get("unit_key") or "")
        if (
            isinstance(ordinal, bool)
            or not isinstance(ordinal, int)
            or ordinal < 1
            or ordinal > len(plan["shots"])
        ):
            raise FactoryAtomicContractError(
                "episode.shot.plan ordinal is invalid"
            )
        entry = plan["shots"][ordinal - 1]
        if entry["unit_key"] != unit_key:
            raise FactoryAtomicContractError(
                "episode.shot.plan unit_key does not match ordinal"
            )
        seed = request.parameter_snapshot.get("video_seed")
        if (
            isinstance(seed, bool)
            or not isinstance(seed, int)
            or seed < 1
            or seed > 2**63 - 1
        ):
            raise FactoryAtomicContractError(
                "episode.shot.plan requires a pinned video_seed"
            )

        strategy = plan["generation_strategy"]
        try:
            mode = GenerationMode(str(entry["generation_mode"]))
            duration = float(strategy.get("duration_seconds") or 5.0)
            resolution = _episode_resolution(
                strategy.get("resolution") or "480p"
            )
            aspect_ratio = str(strategy.get("aspect_ratio") or "9:16")
            model_id = str(
                strategy.get("model_id") or "wan2.2-ti2v-5b"
            )
            blueprint = _GenerationBlueprint(
                mode=mode,
                duration_seconds=duration,
                aspect_ratio=aspect_ratio,
                resolution=resolution,
                audio_intent=str(
                    strategy.get("audio_intent")
                    or "保留与画面一致的环境声"
                ),
                reference_duties=tuple(
                    strategy.get("reference_duties") or ()
                ),
                reference_exclusions=tuple(
                    strategy.get("reference_exclusions") or ()
                ),
                model_id=model_id,
            )
            capability = default_wan_registry().capability(
                model_id=model_id,
                mode=mode,
            )
        except (TypeError, ValueError, ModelSelectionBlocked) as exc:
            raise FactoryAtomicContractError(
                "episode.shot.plan generation strategy is invalid"
            ) from exc
        if (
            resolution not in capability.supported_resolutions
            or duration not in capability.supported_durations_seconds
            or not capability.local_only
        ):
            raise FactoryAtomicContractError(
                "episode.shot.plan strategy is unsupported by the local model"
            )

        shot = _episode_shot(plan, entry)
        prompt = str(entry["prompt"])
        bounded_prompt = prompt[:4_000]
        direction_contract = (
            DirectionContractV1.model_validate(entry["direction_contract"])
            if entry.get("direction_contract") is not None
            else None
        )
        felt_intent = (
            direction_contract.felt_intent
            if direction_contract is not None
            else prompt[:1_000]
        )
        project_revision_id = UUID(plan["project_revision_id"])
        scene_id = uuid5(
            project_revision_id,
            f"episode:{plan['episode_id']}:scene:{unit_key}",
        )
        clip_id = uuid5(
            project_revision_id,
            f"episode:{plan['episode_id']}:clip:{unit_key}",
        )
        primary_spend = "motion"
        if direction_contract is not None:
            if direction_contract.primary_spend == "identity":
                primary_spend = "identity"
            elif direction_contract.primary_spend == "environment":
                primary_spend = "scene"
        action_chain = (
            "；".join(
                (
                    direction_contract.action_chain.initial_state,
                    direction_contract.action_chain.trigger,
                    direction_contract.action_chain.decisive_change,
                    direction_contract.action_chain.response,
                    direction_contract.action_chain.follow_through,
                    direction_contract.action_chain.local_endpoint,
                )
            )
            if direction_contract is not None
            else bounded_prompt
        )
        clip = Clip(
            clip_id=clip_id,
            scene_id=scene_id,
            order=ordinal - 1,
            felt_intent=felt_intent,
            narrative_job=(
                direction_contract.narrative_job
                if direction_contract is not None
                else felt_intent
            ),
            contract=ClipContract(
                duration_seconds=blueprint.duration_seconds,
                aspect_ratio=blueprint.aspect_ratio,
                resolution=blueprint.resolution,
                camera=(
                    "；".join(
                        (
                            *direction_contract.composition,
                            *direction_contract.camera,
                        )
                    )[:1_000]
                    if direction_contract is not None
                    else "按已确认中文分镜执行"
                ),
                motion=action_chain[:1_000],
                lighting=(
                    "；".join(direction_contract.lighting)[:1_000]
                    if direction_contract is not None
                    else "按已确认中文分镜执行"
                ),
                reference_duties=blueprint.reference_duties,
                exclusions=blueprint.reference_exclusions,
            ),
            director_state=DirectorState(
                directing_voice=(
                    "结构化方法论已由上游模型内化；忠实执行 DirectionContract"
                    if direction_contract is not None
                    else "忠实执行已确认中文分镜"
                ),
                narrative_spine=(
                    f"{direction_contract.scene_function}；{direction_contract.dramatic_turn}"
                    if direction_contract is not None
                    else bounded_prompt
                ),
                felt_intent=felt_intent,
                narrative_job=(
                    direction_contract.narrative_job
                    if direction_contract is not None
                    else felt_intent
                ),
                completed_beats=(
                    direction_contract.completed_beats
                    if direction_contract is not None
                    else ()
                ),
                reserved_beats=(
                    direction_contract.reserved_beats
                    if direction_contract is not None
                    else ()
                ),
                primary_spend=primary_spend,
                planned_start_state=(
                    {"description": direction_contract.action_chain.initial_state}
                    if direction_contract is not None
                    else {}
                ),
                planned_end_state=(
                    {"description": direction_contract.action_chain.local_endpoint}
                    if direction_contract is not None
                    else {}
                ),
            ),
        )
        prompt_snapshot_id = uuid5(
            request.workflow_run_id,
            f"episode:prompt:{clip.clip_id}",
        )
        generation_run_id = uuid5(
            request.workflow_run_id,
            f"episode:generation:{clip.clip_id}:{seed}",
        )
        fallback_policy_snapshot_id = uuid5(
            request.workflow_run_id,
            f"episode:fallback:{clip.clip_id}",
        )
        seed_input_hash = stable_json_sha256(
            {
                "project_revision_id": plan["project_revision_id"],
                "clip_id": str(clip.clip_id),
                "mode": blueprint.mode.value,
                "pinned_seed": seed,
                "seed_derivation_version": "episode-compiler.v1",
            }
        )
        intent = {
            "project_revision_id": plan["project_revision_id"],
            "scene_id": str(clip.scene_id),
            "clip_id": str(clip.clip_id),
            "run_id": str(generation_run_id),
            "prompt_snapshot_id": str(prompt_snapshot_id),
            "prompt_compiler_version": WanPromptCompiler.VERSION,
            "resolved_seed": seed,
            "seed_derivation_version": "episode-compiler.v1",
            "seed_input_hash": seed_input_hash,
            "attempt_index": blueprint.attempt_index,
            "duration_seconds": blueprint.duration_seconds,
            "aspect_ratio": blueprint.aspect_ratio,
            "resolution": blueprint.resolution.model_dump(mode="json"),
            "audio_intent": blueprint.audio_intent,
            "reference_duties": [
                item.model_dump(mode="json")
                for item in blueprint.reference_duties
            ],
            "reference_exclusions": list(
                blueprint.reference_exclusions
            ),
            "model_id": blueprint.model_id,
            "capability_snapshot_id": str(capability.capability_id),
            "fallback_policy_snapshot_id": str(
                fallback_policy_snapshot_id
            ),
            "idempotency_key": (
                f"{request.command_idempotency_key}:generation"
            ),
            "mode": blueprint.mode.value,
            "output_role": f"clip.{shot.shot_id.lower()}",
        }
        characters = CharacterBible(
            novel_title=str(plan["novel_title"]),
        )
        worlds = SceneBible(novel_title=str(plan["novel_title"]))
        return FactoryCoreOutput(
            artifacts=(
                _json_artifact(asdict(shot), "shot"),
                _json_artifact(clip.model_dump(mode="json"), "clip"),
                _json_artifact(characters.to_dict(), "character_bible"),
                _json_artifact(worlds.to_dict(), "world_bible"),
                _json_artifact(intent, "generation_intent"),
                _json_artifact(
                    capability.model_dump(mode="json"),
                    "model_capability",
                ),
            ),
            structured_output={
                "ordinal": ordinal,
                "unit_key": unit_key,
                "shot_id": shot.shot_id,
                "mode": blueprint.mode.value,
                "video_seed": seed,
                "output_role": intent["output_role"],
            },
            provider_identity="factory-local-core",
        )

    def _run_generation_bind(self, request, gateway) -> FactoryCoreOutput:
        intent = _read_json(request, gateway, "generation_intent")
        try:
            mode = GenerationMode(str(intent["mode"]))
        except (KeyError, ValueError) as exc:
            raise FactoryAtomicContractError(
                "generation.bind intent has an invalid mode"
            ) from exc
        first_ref = _find_optional_ref(
            request.input_artifact_refs,
            "first_frame",
        )
        last_ref = _find_optional_ref(
            request.input_artifact_refs,
            "last_frame",
        )
        if mode is GenerationMode.I2V and first_ref is None:
            raise FactoryAtomicContractError(
                "generation.bind i2v requires first_frame"
            )
        if mode is GenerationMode.FIRST_LAST_FRAME and (
            first_ref is None or last_ref is None
        ):
            raise FactoryAtomicContractError(
                "generation.bind first_last_frame requires both endpoint frames"
            )
        payload = {
            key: value
            for key, value in intent.items()
            if key != "output_role"
        }
        if mode is GenerationMode.I2V:
            payload["first_image"] = _as_contract_artifact(
                first_ref  # type: ignore[arg-type]
            ).model_dump(mode="json")
        elif mode is GenerationMode.FIRST_LAST_FRAME:
            payload["first_image"] = _as_contract_artifact(
                first_ref  # type: ignore[arg-type]
            ).model_dump(mode="json")
            payload["last_image"] = _as_contract_artifact(
                last_ref  # type: ignore[arg-type]
            ).model_dump(mode="json")
        try:
            generation = _GENERATION_REQUEST_ADAPTER.validate_python(payload)
        except Exception as exc:
            raise FactoryAtomicContractError(
                "generation.bind could not construct GenerationRequest"
            ) from exc
        return FactoryCoreOutput(
            artifacts=(
                _json_artifact(
                    generation.model_dump(mode="json"),
                    "generation_request",
                ),
            ),
            structured_output={
                "mode": generation.mode.value,
                "resolved_seed": generation.resolved_seed,
            },
            provider_identity="factory-local-core",
        )

    def _run_assembly_plan(self, request, gateway) -> FactoryCoreOutput:
        two_shot_ref = _find_optional_ref(
            request.input_artifact_refs,
            "two_shot_spec",
        )
        if two_shot_ref is not None:
            spec = _validate_two_shot_spec(
                _read_json(request, gateway, "two_shot_spec")
            )
            shot_list = ShotList(
                episode_id=spec["episode_id"],
                novel_title=spec["novel_title"],
                shots=[
                    Shot(**entry["shot"])
                    for entry in spec["shots"]
                ],
            )
            artifacts = (_json_artifact(shot_list.to_dict(), "shot_list"),)
        else:
            plan = _validate_episode_plan(
                request.structured_inputs.get("episode_plan")
            )
            shot_list = ShotList(
                episode_id=plan["episode_id"],
                novel_title=plan["novel_title"],
                shots=[
                    _episode_shot(plan, entry)
                    for entry in plan["shots"]
                ],
            )
            artifacts = (
                _json_artifact(plan, "episode_plan"),
                _json_artifact(shot_list.to_dict(), "shot_list"),
            )
        return FactoryCoreOutput(
            artifacts=artifacts,
            structured_output={
                "episode_id": shot_list.episode_id,
                "shot_count": len(shot_list.shots),
            },
            provider_identity="factory-local-core",
        )

    def _run_book_split(self, request, gateway) -> FactoryCoreOutput:
        source = _find_ref(request.input_artifact_refs, "source_book")
        source_format = str(
            request.structured_inputs.get("source_format", "txt")
        ).lower()
        suffix = "." + source_format.lstrip(".")
        with tempfile.TemporaryDirectory(prefix="factory-book-split-") as raw:
            path = Path(raw) / f"source{suffix}"
            path.write_bytes(gateway.read_bytes(source))
            text = load_text(path)
        title = str(request.structured_inputs.get("novel_title") or "untitled")
        chapters = NovelSplitter(self.context)._rule_split(text)
        payload = {
            "novel_title": title,
            "chapters": [
                {
                    "index": index,
                    "heading": heading,
                    "raw_text": body.strip(),
                }
                for index, (heading, body) in enumerate(chapters, start=1)
            ],
        }
        return FactoryCoreOutput(
            artifacts=(_json_artifact(payload, "book_split"),),
            structured_output={"chapter_count": len(chapters)},
            provider_identity="factory-local-core",
        )

    def _run_chapter_enrich(self, request, gateway) -> FactoryCoreOutput:
        split = _read_json(request, gateway, "book_split")
        splitter = NovelSplitter(self.context)
        chapters: list[Chapter] = []
        for index, source in enumerate(split.get("chapters", ()), start=1):
            if not isinstance(source, dict):
                raise FactoryAtomicContractError(
                    "book_split chapters must be JSON objects"
                )
            heading = str(source.get("heading") or f"片段{index}")
            body = str(source.get("raw_text") or "")
            meta = splitter._analyze(heading, body)
            chapters.append(
                Chapter(
                    chapter_id=f"CH{index:03d}",
                    title=meta.get("title", heading[:40]) or heading[:40],
                    summary=meta.get("summary", ""),
                    characters=meta.get("characters", []),
                    locations=meta.get("locations", []),
                    conflict=meta.get("conflict", ""),
                    emotion_arc=meta.get("emotion_arc", ""),
                    raw_text=body.strip(),
                )
            )
        manifest = ChapterManifest(
            novel_title=str(split.get("novel_title") or ""),
            chapters=chapters,
        )
        return FactoryCoreOutput(
            artifacts=(
                _json_artifact(manifest.to_dict(), "chapter_manifest"),
            ),
            structured_output={"chapter_count": len(chapters)},
            provider_identity="factory-llm-router",
        )

    def _run_bible_story_generate(self, request, gateway) -> FactoryCoreOutput:
        manifest = ChapterManifest.from_dict(
            _read_json(request, gateway, "chapter_manifest")
        )
        bible = StoryBibleAgent(self.context).run(
            manifest,
            episodes=int(request.structured_inputs.get("episodes") or 0),
            aspect_ratio=str(
                request.structured_inputs.get("aspect_ratio") or "9:16"
            ),
        )
        return FactoryCoreOutput(
            artifacts=(_json_artifact(bible.to_dict(), "story_bible"),),
            provider_identity="factory-llm-router",
        )

    def _run_bible_character_generate(self, request, gateway) -> FactoryCoreOutput:
        manifest = ChapterManifest.from_dict(
            _read_json(request, gateway, "chapter_manifest")
        )
        bible = StoryBible.from_dict(
            _read_json(request, gateway, "story_bible")
        )
        characters = CharacterDesigner(self.context).run(manifest, bible)
        return FactoryCoreOutput(
            artifacts=(
                _json_artifact(characters.to_dict(), "character_bible"),
            ),
            provider_identity="factory-llm-router",
        )

    def _run_bible_world_generate(self, request, gateway) -> FactoryCoreOutput:
        manifest = ChapterManifest.from_dict(
            _read_json(request, gateway, "chapter_manifest")
        )
        bible = StoryBible.from_dict(
            _read_json(request, gateway, "story_bible")
        )
        worlds = SceneDesigner(self.context).run(manifest, bible)
        return FactoryCoreOutput(
            artifacts=(_json_artifact(worlds.to_dict(), "world_bible"),),
            provider_identity="factory-llm-router",
        )

    def _run_bible_style_generate(self, request, gateway) -> FactoryCoreOutput:
        bible = StoryBible.from_dict(
            _read_json(request, gateway, "story_bible")
        )
        visual_style, dropped = sanitize_visual_style(bible.visual_style)
        style = {
            "visual_style": visual_style,
            "palette": bible.palette,
            "tone": bible.tone,
            "aspect_ratio": bible.aspect_ratio,
        }
        return FactoryCoreOutput(
            artifacts=(_json_artifact(style, "style_bible"),),
            structured_output={"removed_clause_count": len(dropped)},
            provider_identity="factory-local-core",
            warnings=(
                ("Removed non-style scene clauses from the global style.",)
                if dropped
                else ()
            ),
        )

    def _run_asset_plan(self, request, gateway) -> FactoryCoreOutput:
        manifest = ChapterManifest.from_dict(
            _read_json(request, gateway, "chapter_manifest")
        )
        story = StoryBible.from_dict(
            _read_json(request, gateway, "story_bible")
        )
        characters = CharacterBible.from_dict(
            _read_json(request, gateway, "character_bible")
        )
        worlds = SceneBible.from_dict(
            _read_json(request, gateway, "world_bible", "scene_bible")
        )
        registry = AssetPlanner(self.context).run(
            manifest,
            story,
            characters,
            worlds,
        )
        return FactoryCoreOutput(
            artifacts=(_json_artifact(registry.to_dict(), "asset_plan"),),
            provider_identity="factory-llm-router",
        )

    def _story_style(self, request, gateway) -> str:
        story_ref = _find_optional_ref(
            request.input_artifact_refs,
            "story_bible",
        )
        if story_ref is not None:
            payload = json.loads(gateway.read_bytes(story_ref).decode("utf-8"))
            return str(payload.get("visual_style") or "")
        style_ref = _find_optional_ref(
            request.input_artifact_refs,
            "style_bible",
        )
        if style_ref is not None:
            payload = json.loads(gateway.read_bytes(style_ref).decode("utf-8"))
            return str(payload.get("visual_style") or "")
        return ""

    def _run_asset_character_generate(self, request, gateway) -> FactoryCoreOutput:
        characters = CharacterBible.from_dict(
            _read_json(request, gateway, "character_bible")
        )
        seed = int(request.parameter_snapshot["seed"])
        for offset, character in enumerate(characters.characters):
            character.seed = (seed + offset) & 0x7FFFFFFF
        generated = AssetGenerator(self.context).run_characters(
            characters,
            self._story_style(request, gateway),
            save=False,
        )
        produced = [
            _json_artifact(generated.to_dict(), "character_bible"),
        ]
        for character in generated.characters:
            for index, path in enumerate(character.ref_images):
                produced.append(
                    _file_artifact(
                        path,
                        role="character_asset",
                        mime_type="image/png",
                    )
                )
        return FactoryCoreOutput(
            artifacts=tuple(produced),
            seed=seed,
            provider_identity="local-qwen-image-comfy",
        )

    def _run_asset_scene_generate(self, request, gateway) -> FactoryCoreOutput:
        worlds = SceneBible.from_dict(
            _read_json(request, gateway, "world_bible", "scene_bible")
        )
        seed = int(request.parameter_snapshot["seed"])
        for offset, scene in enumerate(worlds.scenes):
            scene.seed = (seed + offset) & 0x7FFFFFFF
        generated = AssetGenerator(self.context).run_scenes(
            worlds,
            self._story_style(request, gateway),
            save=False,
        )
        produced = [_json_artifact(generated.to_dict(), "world_bible")]
        for scene in generated.scenes:
            for path in (*scene.ref_images, *scene.angle_refs.values()):
                produced.append(
                    _file_artifact(
                        path,
                        role="scene_asset",
                        mime_type="image/png",
                    )
                )
        return FactoryCoreOutput(
            artifacts=tuple(produced),
            seed=seed,
            provider_identity="local-qwen-image-comfy",
        )

    def _run_asset_prop_generate(self, request, gateway) -> FactoryCoreOutput:
        props = request.structured_inputs.get("props")
        if not isinstance(props, list) or not props:
            raise FactoryAtomicContractError(
                "asset.prop.generate requires a non-empty props list"
            )
        seed = int(request.parameter_snapshot["seed"])
        generator = AssetGenerator(self.context)
        produced: list[FactoryProducedArtifact] = []
        manifest: list[dict[str, object]] = []
        for index, prop in enumerate(props):
            if not isinstance(prop, dict):
                raise FactoryAtomicContractError("prop entries must be objects")
            prop_id = str(prop.get("prop_id") or f"prop_{index:03d}")
            prompt = str(prop.get("prompt") or "").strip()
            if not prompt:
                raise FactoryAtomicContractError("prop prompt is required")
            destination = (
                self.context.paths.root
                / "assets"
                / "props"
                / prop_id
                / f"{prop_id}.png"
            )
            prop_seed = (seed + index) & 0x7FFFFFFF
            if self.context.dry_run:
                path = self.context.llm.generate_image(
                    prompt,
                    destination,
                    size=generator._portrait(),
                    seed=prop_seed,
                )
            else:
                path = generator._qwen_asset(
                    prompt,
                    destination,
                    prop_seed,
                    generator._portrait(),
                )
            produced.append(
                _file_artifact(
                    path,
                    role="prop_asset",
                    mime_type="image/png",
                )
            )
            manifest.append({"prop_id": prop_id, "seed": prop_seed})
        produced.insert(0, _json_artifact({"props": manifest}, "prop_manifest"))
        return FactoryCoreOutput(
            artifacts=tuple(produced),
            seed=seed,
            provider_identity="local-qwen-image-comfy",
        )

    def _run_storyboard_generate(self, request, gateway) -> FactoryCoreOutput:
        manifest = ChapterManifest.from_dict(
            _read_json(request, gateway, "chapter_manifest")
        )
        story = StoryBible.from_dict(
            _read_json(request, gateway, "story_bible")
        )
        characters = CharacterBible.from_dict(
            _read_json(request, gateway, "character_bible")
        )
        worlds = SceneBible.from_dict(
            _read_json(request, gateway, "world_bible", "scene_bible")
        )
        episode = request.structured_inputs.get("episode")
        if not isinstance(episode, dict):
            raise FactoryAtomicContractError(
                "storyboard.generate requires an episode object"
            )
        shots = Storyboard(self.context).run(
            episode,
            manifest,
            story,
            characters,
            worlds,
        )
        return FactoryCoreOutput(
            artifacts=(_json_artifact(shots.to_dict(), "shot_list"),),
            provider_identity="factory-llm-router",
        )

    def _run_prompt_compile(self, request, gateway) -> FactoryCoreOutput:
        clip = Clip.model_validate(_read_json(request, gateway, "clip"))
        generation = _GENERATION_REQUEST_ADAPTER.validate_python(
            _read_json(request, gateway, "generation_request")
        )
        capability = ModelCapability.model_validate(
            _read_json(request, gateway, "model_capability")
        )
        raw_direction_contract = request.structured_inputs.get(
            "direction_contract"
        )
        if (
            request.structured_inputs.get("prompt_compilation_id")
            and raw_direction_contract is None
        ):
            raise FactoryAtomicContractError(
                "prompt.compile has methodology lineage without a direction contract"
            )
        try:
            direction_contract = (
                DirectionContractV1.model_validate(raw_direction_contract)
                if raw_direction_contract is not None
                else None
            )
        except Exception as exc:
            raise FactoryAtomicContractError(
                "prompt.compile direction_contract is invalid"
            ) from exc
        compiled = self.prompt_compiler.compile(
            clip=clip,
            request=generation,
            capability=capability,
            steps=int(request.structured_inputs.get("steps") or 30),
            cfg=float(request.structured_inputs.get("cfg") or 5.0),
            rewrite_instruction=(
                str(request.structured_inputs["rewrite_instruction"])
                if request.structured_inputs.get("rewrite_instruction")
                else None
            ),
            direction_contract=direction_contract,
        )
        return FactoryCoreOutput(
            artifacts=(
                _json_artifact(
                    compiled.model_dump(mode="json"),
                    "compiled_prompt",
                ),
            ),
            structured_output={
                "prompt_sha256": compiled.prompt_sha256,
                "prompt_compilation_id": request.structured_inputs.get(
                    "prompt_compilation_id"
                ),
                "methodology_snapshot_id": request.structured_inputs.get(
                    "methodology_snapshot_id"
                ),
                "methodology_snapshot_digest": request.structured_inputs.get(
                    "methodology_snapshot_digest"
                ),
                "methodology_execution_status": (
                    "APPLIED" if direction_contract is not None else "NOT_SELECTED"
                ),
            },
            provider_identity="factory-local-core",
        )

    def _run_keyframe_generate(self, request, gateway) -> FactoryCoreOutput:
        profile = keyframe_profile()
        _validate_keyframe_runtime_profile(self.context, profile)
        shot = Shot(**_read_json(request, gateway, "shot"))
        keyframe_prompt = request.structured_inputs.get("prompt")
        if keyframe_prompt not in (None, ""):
            bounded_keyframe_prompt = _episode_text(
                keyframe_prompt,
                limit=4_000,
                field_name="keyframe prompt",
            )
            shot.action = bounded_keyframe_prompt
            shot.visual_prompt_en = bounded_keyframe_prompt
            shot.video_prompt_en = bounded_keyframe_prompt
        characters = CharacterBible.from_dict(
            _read_json(request, gateway, "character_bible")
        )
        world_ref = _find_optional_ref(
            request.input_artifact_refs,
            "world_bible",
            "scene_bible",
        )
        worlds = (
            None
            if world_ref is None
            else SceneBible.from_dict(
                json.loads(gateway.read_bytes(world_ref).decode("utf-8"))
            )
        )
        seed = int(request.parameter_snapshot["seed"])
        shot.keyframe_seed = seed
        KeyframeGenerator(self.context, characters, worlds)(
            shot,
            int(request.structured_inputs.get("gpu_shard") or 0),
        )
        frame_role = str(
            request.structured_inputs.get("frame_role") or "keyframe"
        )
        if frame_role not in {"keyframe", "first_frame", "last_frame"}:
            raise FactoryAtomicContractError(
                "keyframe.generate frame_role must be keyframe, "
                "first_frame, or last_frame"
            )
        return FactoryCoreOutput(
            artifacts=(
                _json_artifact(asdict(shot), "shot"),
                _file_artifact(
                    shot.keyframe_path,
                    role=frame_role,
                    mime_type="image/png",
                ),
            ),
            structured_output={"frame_role": frame_role},
            seed=seed,
            provider_identity=profile.provider_identity,
        )

    def _run_video_generate(self, request, gateway) -> FactoryCoreOutput:
        generation = _GENERATION_REQUEST_ADAPTER.validate_python(
            _read_json(request, gateway, "generation_request")
        )
        compiled = CompiledWanPrompt.model_validate(
            _read_json(request, gateway, "compiled_prompt")
        )
        mode = str(request.structured_inputs["mode"])
        if generation.mode.value != mode:
            raise FactoryAtomicContractError(
                "video mode does not match generation request"
            )
        seed = int(request.parameter_snapshot["seed"])
        if generation.resolved_seed != seed:
            raise FactoryAtomicContractError(
                "video seed does not match generation request"
            )
        intent_ref = _find_optional_ref(
            request.input_artifact_refs,
            "generation_intent",
        )
        output_role = "raw_video"
        if intent_ref is not None:
            intent = json.loads(
                gateway.read_bytes(intent_ref).decode("utf-8")
            )
            if not isinstance(intent, dict):
                raise FactoryAtomicContractError(
                    "generation_intent must contain a JSON object"
                )
            output_role = str(intent.get("output_role") or "")
            if (
                not output_role.startswith("clip.")
                or len(output_role) > 160
                or any(
                    character not in (
                        "abcdefghijklmnopqrstuvwxyz"
                        "0123456789._-"
                    )
                    for character in output_role
                )
            ):
                raise FactoryAtomicContractError(
                    "generation_intent output_role is invalid"
                )
        quality = WanQualityProfile(
            str(request.structured_inputs.get("quality") or "quality")
        )
        with tempfile.TemporaryDirectory(prefix="factory-video-") as raw:
            staging = Path(raw)
            first_ref = _find_optional_ref(
                request.input_artifact_refs,
                "first_frame",
            )
            last_ref = _find_optional_ref(
                request.input_artifact_refs,
                "last_frame",
            )
            if mode == GenerationMode.T2V.value:
                first_ref = None
                last_ref = None
            elif mode == GenerationMode.I2V.value:
                last_ref = None
            first_path = (
                _materialize(gateway, first_ref, staging)
                if first_ref is not None
                else None
            )
            last_path = (
                _materialize(gateway, last_ref, staging)
                if last_ref is not None
                else None
            )
            comfy = self.context.comfy(
                int(request.structured_inputs.get("gpu_shard") or 0),
                model_name=generation.model_id,
                min_vram_mib=24_576,
            )
            if first_path is not None and not self.context.dry_run:
                comfy.upload_image(first_path)
            if last_path is not None and not self.context.dry_run:
                comfy.upload_image(last_path)
            build = self.workflow_builder.build(
                request=generation,
                compiled=compiled,
                quality=quality,
                first_image_filename=(
                    first_path.name if first_path is not None else None
                ),
                last_image_filename=(
                    last_path.name if last_path is not None else None
                ),
            )
            paths = comfy.run(
                build.workflow,
                self.context.paths.clips / str(generation.clip_id),
                prefix=str(generation.run_id),
                save_node_types=("videos", "gifs", "images"),
            )
        videos = [
            path
            for path in paths
            if path.suffix.lower() in {".mp4", ".webm", ".gif"}
        ] or paths
        if not videos:
            raise FactoryCoreError("V3 Wan core produced no video")
        return FactoryCoreOutput(
            artifacts=(
                _file_artifact(
                    videos[0],
                    role=output_role,
                    mime_type=(
                        "video/webm"
                        if videos[0].suffix.lower() == ".webm"
                        else "video/mp4"
                    ),
                ),
            ),
            structured_output={
                "mode": mode,
                "workflow_id": build.workflow_id,
                "workflow_version": build.workflow_version,
                "workflow_sha256": build.workflow_sha256,
                "frame_count": build.frame_count,
                "output_role": output_role,
            },
            seed=seed,
            provider_identity="local-wan-comfy",
        )

    def _run_speech_synthesize(self, request, gateway) -> FactoryCoreOutput:
        if (
            request.structured_inputs.get("compiler_revision")
            == "shidu-episode-compiler.v2"
        ):
            return self._run_shidu_speech_synthesize(request, gateway)
        shot = Shot(**_read_json(request, gateway, "shot"))
        characters = CharacterBible.from_dict(
            _read_json(request, gateway, "character_bible")
        )
        TTSAgent(self.context, characters)(shot)
        if not shot.voice_path:
            # Preserve the legacy no-dialogue behavior while still producing a
            # contract artifact rather than publishing an empty media file.
            return FactoryCoreOutput(
                artifacts=(_json_artifact(asdict(shot), "shot"),),
                provider_identity="factory-tts-provider",
            )
        mime = (
            "audio/mpeg"
            if Path(shot.voice_path).suffix.lower() == ".mp3"
            else "audio/wav"
        )
        return FactoryCoreOutput(
            artifacts=(
                _json_artifact(asdict(shot), "shot"),
                _file_artifact(
                    shot.voice_path,
                    role="dialogue_track",
                    mime_type=mime,
                ),
            ),
            provider_identity="factory-tts-provider",
        )

    def _run_shidu_speech_synthesize(
        self,
        request,
        gateway,
    ) -> FactoryCoreOutput:
        del gateway
        if self.shidu_tts_provider is None:
            raise FactoryAtomicContractError(
                "Shidu speech requires an injected Qwen CustomVoice provider"
            )
        raw_cue = request.structured_inputs.get("cue")
        raw_preset = request.structured_inputs.get("voice_preset_snapshot")
        if not isinstance(raw_cue, dict) or not isinstance(raw_preset, dict):
            raise FactoryAtomicContractError(
                "Shidu speech requires frozen cue and voice preset snapshots"
            )
        try:
            from .v3.qwen_tts_mcp import VoicePresetRevision

            preset = VoicePresetRevision.model_validate(raw_preset)
            cue_key = str(request.structured_inputs["cue_key"])
            if (
                cue_key != raw_cue.get("cue_key")
                or preset.project_id != request.project_id
                or str(preset.voice_preset_revision_id)
                != str(request.structured_inputs["voice_preset_revision_id"])
                or preset.digest
                != request.structured_inputs["voice_preset_digest"]
            ):
                raise ValueError("frozen authority mismatch")
            if (
                not cue_key
                or len(cue_key) > 100
                or any(
                    value
                    not in "abcdefghijklmnopqrstuvwxyz0123456789._-"
                    for value in cue_key.casefold()
                )
            ):
                raise ValueError("invalid cue key")
            cue = DialogueCue(
                cue_id=UUID(str(raw_cue["cue_id"])),
                trial_script_revision_id=UUID(
                    str(request.structured_inputs["trial_script_revision_id"])
                ),
                cue_key=cue_key,
                start_ms=round(float(raw_cue["start_time"]) * 1000),
                end_ms=round(float(raw_cue["end_time"]) * 1000),
                text=str(raw_cue["text"]),
                language=preset.language,
                speaker=preset.speaker,
                instruction=preset.instruction,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise FactoryAtomicContractError(
                "Shidu speech frozen authority is invalid"
            ) from exc
        with tempfile.TemporaryDirectory(prefix="factory-shidu-tts-") as raw:
            destination = Path(raw) / f"{cue_key}.wav"
            take = materialize_shidu_tts_take(
                provider=self.shidu_tts_provider,
                cue=cue,
                voice_preset=preset,
                destination=destination,
                idempotency_key=request.command_idempotency_key,
            )
            artifacts = (
                _file_artifact(
                    destination,
                    role=f"dialogue.{cue_key}",
                    mime_type="audio/wav",
                ),
                _json_artifact(
                    take.model_dump(mode="json"),
                    f"tts_take.{cue_key}",
                ),
            )
        return FactoryCoreOutput(
            artifacts=artifacts,
            structured_output={
                "cue_key": cue_key,
                "tts_take_id": str(take.take_id),
                "tts_take_digest": take.take_digest,
                "voice_preset_revision_id": str(
                    preset.voice_preset_revision_id
                ),
                "voice_preset_digest": preset.digest,
                "measured_duration_ms": round(
                    take.audio_quality.duration_seconds * 1000
                ),
                "lipsync_required": False,
            },
            provider_identity="qwen3-tts-custom-voice-mcp",
        )

    def _run_subtitle_generate(self, request, gateway) -> FactoryCoreOutput:
        if (
            request.structured_inputs.get("compiler_revision")
            == "shidu-episode-compiler.v2"
        ):
            return self._run_shidu_subtitle_generate(request, gateway)
        shots = ShotList.from_dict(
            _read_json(request, gateway, "shot_list")
        )
        path = SubtitleAgent(self.context).run(shots)
        return FactoryCoreOutput(
            artifacts=(
                _file_artifact(
                    path,
                    role="subtitle_track",
                    mime_type="application/x-subrip",
                ),
            ),
            provider_identity="factory-local-core",
        )

    def _run_shidu_subtitle_generate(
        self,
        request,
        gateway,
    ) -> FactoryCoreOutput:
        try:
            from .v3.qwen_tts_mcp import TTSTake

            cue_key = str(request.structured_inputs["cue_key"])
            raw_cue = request.structured_inputs["cue"]
            if not isinstance(raw_cue, dict) or raw_cue.get("cue_key") != cue_key:
                raise ValueError("cue mismatch")
            take = TTSTake.model_validate(
                _read_json(request, gateway, f"tts_take.{cue_key}")
            )
            dialogue_ref = _find_ref(
                request.input_artifact_refs,
                f"dialogue.{cue_key}",
            )
            if (
                take.cue_id != UUID(str(raw_cue["cue_id"]))
                or take.cue_key != cue_key
                or take.trial_script_revision_id
                != UUID(
                    str(request.structured_inputs["trial_script_revision_id"])
                )
                or take.audio_artifact.sha256
                != dialogue_ref.content_digest
                or take.audio_artifact.byte_size != dialogue_ref.byte_size
                or dialogue_ref.mime_type != "audio/wav"
            ):
                raise ValueError("take mismatch")
            measured_duration_ms = round(
                take.audio_quality.duration_seconds * 1000
            )
            start_ms = round(float(raw_cue["start_time"]) * 1000)
            segment = {
                "schema_version": "factory.shidu-subtitle-segment.v1",
                "trial_script_revision_id": str(
                    take.trial_script_revision_id
                ),
                "cue_id": str(take.cue_id),
                "cue_key": cue_key,
                "text": str(raw_cue["text"]),
                "tts_take_id": str(take.take_id),
                "tts_take_digest": take.take_digest,
                "audio_artifact_id": str(take.audio_artifact.artifact_id),
                "audio_artifact_sha256": take.audio_artifact.sha256,
                "planned_start_ms": start_ms,
                "measured_duration_ms": measured_duration_ms,
                "preview_end_ms": start_ms + measured_duration_ms,
                "timing_authority": "measured_tts_take",
            }
        except (KeyError, TypeError, ValueError) as exc:
            raise FactoryAtomicContractError(
                "Shidu subtitle requires one exact measured TTS take"
            ) from exc
        return FactoryCoreOutput(
            artifacts=(
                _json_artifact(segment, f"subtitle.{cue_key}"),
            ),
            structured_output={
                "cue_key": cue_key,
                "tts_take_id": str(take.take_id),
                "tts_take_digest": take.take_digest,
                "measured_duration_ms": measured_duration_ms,
                "timing_authority": "measured_tts_take",
            },
            provider_identity="factory-local-core",
        )

    def _run_audio_mix(self, request, gateway) -> FactoryCoreOutput:
        if (
            request.structured_inputs.get("compiler_revision")
            == "shidu-episode-compiler.v2"
        ):
            return self._run_shidu_audio_mix(request, gateway)
        video = _find_optional_ref(request.input_artifact_refs, "video_track")
        tracks = [
            item
            for item in request.input_artifact_refs
            if item.logical_role
            in {
                "dialogue_track",
                "ambience_track",
                "sfx_track",
                "music_track",
            }
        ]
        if not tracks:
            raise FactoryAtomicContractError(
                "audio.mix requires at least one audio track ArtifactRef"
            )
        with tempfile.TemporaryDirectory(prefix="factory-audio-mix-") as raw:
            staging = Path(raw)
            track_paths = [
                _materialize(gateway, track, staging) for track in tracks
            ]
            if video is not None and len(track_paths) == 1:
                video_path = _materialize(gateway, video, staging)
                destination = staging / "mixed.mp4"
                mux_audio(
                    video_path,
                    track_paths[0],
                    destination,
                    target_sec=(
                        float(request.structured_inputs["duration_seconds"])
                        if request.structured_inputs.get("duration_seconds")
                        is not None
                        else None
                    ),
                )
                produced = FactoryProducedArtifact(
                    payload=destination.read_bytes(),
                    mime_type="video/mp4",
                    logical_role="mixed_video",
                )
            else:
                destination = staging / "mix.wav"
                command = ["ffmpeg", "-y"]
                for path in track_paths:
                    command.extend(("-i", str(path)))
                command.extend(
                    (
                        "-filter_complex",
                        (
                            f"amix=inputs={len(track_paths)}:"
                            "duration=longest:normalize=0"
                        ),
                        "-c:a",
                        "pcm_s16le",
                        str(destination),
                    )
                )
                run_media_command(command)
                produced = FactoryProducedArtifact(
                    payload=destination.read_bytes(),
                    mime_type="audio/wav",
                    logical_role="mixed_audio",
                )
        return FactoryCoreOutput(
            artifacts=(produced,),
            structured_output={"track_count": len(tracks)},
            provider_identity="factory-local-core",
        )

    def _run_shidu_audio_mix(self, request, gateway) -> FactoryCoreOutput:
        resolver = self.shidu_final_audio_authority_resolver
        if resolver is None:
            raise FactoryAtomicContractError(
                "Shidu audio mix requires a trusted final-audio authority resolver"
            )
        try:
            from .v3.qwen_tts_mcp import TTSTake

            script_id = UUID(
                str(request.structured_inputs["trial_script_revision_id"])
            )
            duration_ms = int(request.structured_inputs["target_duration_ms"])
            raw_cues = request.structured_inputs["narration_cues"]
            if (
                not isinstance(raw_cues, list)
                or len(raw_cues) != 6
                or not 50_000 <= duration_ms <= 70_000
            ):
                raise ValueError("invalid audio plan")
            policy = AudioAlignmentPolicyRevision.model_validate(
                request.structured_inputs["alignment_policy_snapshot"]
            )
            if policy.project_id != request.project_id:
                raise ValueError("alignment project mismatch")
            tracks = tuple(
                FinalAudioTrack.model_validate(item)
                for item in request.structured_inputs["final_audio_tracks"]
            )
            cues = tuple(
                DialogueCue(
                    cue_id=UUID(str(item["cue_id"])),
                    trial_script_revision_id=script_id,
                    cue_key=str(item["cue_key"]),
                    start_ms=round(float(item["start_time"]) * 1000),
                    end_ms=round(float(item["end_time"]) * 1000),
                    text=str(item["text"]),
                )
                for item in raw_cues
            )
            take_payloads = tuple(
                TTSTake.model_validate(
                    _read_json(
                        request,
                        gateway,
                        f"tts_take.{cue.cue_key}",
                    )
                )
                for cue in cues
            )
            dialogue_refs = tuple(
                _find_ref(
                    request.input_artifact_refs,
                    f"dialogue.{cue.cue_key}",
                )
                for cue in cues
            )
            for cue, take, dialogue_ref in zip(
                cues,
                take_payloads,
                dialogue_refs,
                strict=True,
            ):
                subtitle = _read_json(
                    request,
                    gateway,
                    f"subtitle.{cue.cue_key}",
                )
                if (
                    take.cue_id != cue.cue_id
                    or take.cue_key != cue.cue_key
                    or take.trial_script_revision_id != script_id
                    or take.audio_artifact.sha256
                    != dialogue_ref.content_digest
                    or take.audio_artifact.byte_size
                    != dialogue_ref.byte_size
                    or subtitle.get("tts_take_id") != str(take.take_id)
                    or subtitle.get("tts_take_digest") != take.take_digest
                    or subtitle.get("audio_artifact_sha256")
                    != take.audio_artifact.sha256
                ):
                    raise ValueError("cue/take/subtitle lineage mismatch")
            visual_ids = tuple(
                uuid5(script_id, f"shidu:visual:{index:03d}")
                for index in range(1, 7)
            )
            plan = AudioPlan(
                plan_id=uuid5(script_id, "shidu:audio-plan:v1"),
                visual_take_id=visual_ids[0],
                visual_take_ids=visual_ids,
                duration_ms=duration_ms,
                sample_rate=24_000,
                dialogue=cues,
                lipsync_required=False,
                created_at=policy.created_at,
            )
            alignment = compile_audio_alignment(
                plan=plan,
                takes=take_payloads,
                policy=policy,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise FactoryAtomicContractError(
                "Shidu audio mix requires six exact measured cue authorities"
            ) from exc

        class _GatewayCatalog:
            def __init__(self, directory: Path) -> None:
                self.directory = directory

            def resolve(self, ref: ArtifactRef) -> Path:
                match = next(
                    (
                        item
                        for item in request.input_artifact_refs
                        if item.artifact_id == ref.artifact_id
                    ),
                    None,
                )
                if match is None:
                    match = AtomicArtifactRef(
                        artifact_id=ref.artifact_id,
                        project_id=request.project_id,
                        content_digest=ref.sha256,
                        mime_type=ref.mime,
                        byte_size=ref.bytes,
                        logical_role="accepted_audio",
                    )
                payload = gateway.read_bytes(match)
                if (
                    len(payload) != ref.bytes
                    or __import__("hashlib").sha256(payload).hexdigest()
                    != ref.sha256
                ):
                    raise FactoryAtomicContractError(
                        "accepted audio bytes do not match frozen authority"
                    )
                path = self.directory / f"{ref.artifact_id}.wav"
                path.write_bytes(payload)
                return path

        with tempfile.TemporaryDirectory(prefix="factory-shidu-mix-") as raw:
            staging = Path(raw)
            tts_paths = tuple(
                _materialize(gateway, ref, staging) for ref in dialogue_refs
            )
            accepted_paths, accepted_refs, silence_bindings = (
                resolve_final_audio_tracks(
                    tracks=tracks,
                    project_id=request.project_id,
                    duration_ms=duration_ms,
                    catalog=_GatewayCatalog(staging),  # type: ignore[arg-type]
                    authority_resolver=resolver,
                    probe_wav_bytes=True,
                )
            )
            dialogue_path, mix_path = materialize_shidu_audio_mix(
                plan=plan,
                alignment=alignment,
                tts_takes=take_payloads,
                tts_paths=tts_paths,
                accepted_track_paths=accepted_paths,
                output_dir=staging / "output",
            )
            subtitle_path = staging / "output" / "subtitles.srt"
            _write_aligned_srt(alignment, subtitle_path)
            artifacts = (
                _file_artifact(
                    dialogue_path,
                    role="dialogue_track",
                    mime_type="audio/wav",
                ),
                _file_artifact(
                    mix_path,
                    role="mixed_audio",
                    mime_type="audio/wav",
                ),
                _json_artifact(
                    alignment.model_dump(mode="json"),
                    "audio_alignment",
                ),
                _file_artifact(
                    subtitle_path,
                    role="subtitle_track",
                    mime_type="application/x-subrip",
                ),
            )
        return FactoryCoreOutput(
            artifacts=artifacts,
            structured_output={
                "cue_count": len(cues),
                "duration_ms": duration_ms,
                "audio_alignment_revision_id": str(
                    alignment.audio_alignment_revision_id
                ),
                "audio_alignment_digest": alignment.digest,
                "tts_take_ids": [str(item.take_id) for item in take_payloads],
                "accepted_optional_audio": {
                    role: {
                        "artifact_id": str(ref.artifact_id),
                        "sha256": ref.sha256,
                    }
                    for role, ref in accepted_refs.items()
                },
                "silence_policy_bindings": [
                    item.model_dump(mode="json") for item in silence_bindings
                ],
                "speed_change_allowed": False,
                "lipsync_required": False,
            },
            provider_identity="factory-local-core",
        )

    def _run_final_assemble(self, request, gateway) -> FactoryCoreOutput:
        if (
            request.structured_inputs.get("compiler_revision")
            == "shidu-episode-compiler.v2"
        ):
            return self._run_shidu_final_assemble(request, gateway)
        shots = ShotList.from_dict(
            _read_json(request, gateway, "shot_list")
        )
        with tempfile.TemporaryDirectory(prefix="factory-assemble-") as raw:
            staging = Path(raw)
            for shot in shots.shots:
                clip_ref = _find_optional_ref(
                    request.input_artifact_refs,
                    f"clip.{shot.shot_id.lower()}",
                )
                voice_ref = _find_optional_ref(
                    request.input_artifact_refs,
                    f"voice.{shot.shot_id.lower()}",
                )
                if clip_ref is not None:
                    shot.clip_path = str(
                        _materialize(gateway, clip_ref, staging)
                    )
                if voice_ref is not None:
                    shot.voice_path = str(
                        _materialize(gateway, voice_ref, staging)
                    )
            subtitle_ref = _find_optional_ref(
                request.input_artifact_refs,
                "subtitle_track",
            )
            subtitle_path = (
                str(_materialize(gateway, subtitle_ref, staging))
                if subtitle_ref is not None
                else ""
            )
            episode = Assembler(self.context).run(shots, subtitle_path)
        return FactoryCoreOutput(
            artifacts=(
                _json_artifact(episode.to_dict(), "episode_manifest"),
                _file_artifact(
                    episode.final_path,
                    role="final_episode",
                    mime_type="video/mp4",
                ),
            ),
            structured_output={
                "episode_id": episode.episode_id,
                "duration_seconds": episode.duration_sec,
            },
            provider_identity="factory-local-core",
        )

    def _run_shidu_final_assemble(self, request, gateway) -> FactoryCoreOutput:
        try:
            shots = ShotList.from_dict(
                _read_json(request, gateway, "shot_list")
            )
            if len(shots.shots) != 6:
                raise ValueError("six shots required")
            clip_refs = tuple(
                _find_ref(
                    request.input_artifact_refs,
                    f"clip.{shot.shot_id.lower()}",
                )
                for shot in shots.shots
            )
            if len({item.artifact_id for item in clip_refs}) != 6:
                raise ValueError("six unique clips required")
            mix_ref = _find_ref(request.input_artifact_refs, "mixed_audio")
            subtitle_ref = _find_ref(
                request.input_artifact_refs,
                "subtitle_track",
            )
            alignment = AudioAlignmentRevision.model_validate(
                _read_json(request, gateway, "audio_alignment")
            )
            script_id = UUID(
                str(request.structured_inputs["trial_script_revision_id"])
            )
            duration_ms = int(request.structured_inputs["target_duration_ms"])
            if (
                alignment.trial_script_revision_id != script_id
                or alignment.duration_ms != duration_ms
                or len(alignment.segments) != 6
                or mix_ref.mime_type != "audio/wav"
                or subtitle_ref.mime_type != "application/x-subrip"
                or not 50_000 <= duration_ms <= 70_000
            ):
                raise ValueError("final authority mismatch")
        except (KeyError, TypeError, ValueError) as exc:
            raise FactoryAtomicContractError(
                "Shidu final assembly requires six clips and exact audio authority"
            ) from exc
        with tempfile.TemporaryDirectory(prefix="factory-shidu-final-") as raw:
            staging = Path(raw)
            visual_sources = tuple(
                _materialize(gateway, ref, staging) for ref in clip_refs
            )
            mix_path = _materialize(gateway, mix_ref, staging)
            subtitle_path = _materialize(gateway, subtitle_ref, staging)
            _concat, _muxed, final_path = assemble_shidu_delivery(
                visual_sources=visual_sources,
                mix_path=mix_path,
                subtitle_path=subtitle_path,
                duration_ms=duration_ms,
                output_dir=staging / "output",
            )
            cover_path, share_card_path = derive_shidu_delivery_surfaces(
                final_path=final_path,
                output_dir=staging / "output" / "surfaces",
            )
            clip_lineage = [
                {
                    "ordinal": index,
                    "shot_id": shot.shot_id,
                    "artifact_id": str(ref.artifact_id),
                    "artifact_digest": ref.content_digest,
                    "byte_size": ref.byte_size,
                    "logical_role": ref.logical_role,
                }
                for index, (shot, ref) in enumerate(
                    zip(shots.shots, clip_refs, strict=True),
                    start=1,
                )
            ]
            episode_manifest = {
                "schema_version": "factory.shidu-final-episode.v1",
                "project_id": str(request.project_id),
                "trial_script_revision_id": str(script_id),
                "trial_script_digest": str(
                    request.structured_inputs["trial_script_digest"]
                ),
                "episode_id": shots.episode_id,
                "duration_ms": duration_ms,
                "clip_lineage": clip_lineage,
                "audio_lineage": {
                    "mixed_audio_artifact_id": str(mix_ref.artifact_id),
                    "mixed_audio_artifact_digest": mix_ref.content_digest,
                    "audio_alignment_revision_id": str(
                        alignment.audio_alignment_revision_id
                    ),
                    "audio_alignment_digest": alignment.digest,
                    "tts_take_ids": [
                        str(item.tts_take_id) for item in alignment.segments
                    ],
                    "speed_change_allowed": False,
                },
                "subtitle_lineage": {
                    "artifact_id": str(subtitle_ref.artifact_id),
                    "artifact_digest": subtitle_ref.content_digest,
                    "audio_alignment_digest": alignment.digest,
                },
                "lipsync_required": False,
            }
            artifacts = (
                _json_artifact(episode_manifest, "episode_manifest"),
                _file_artifact(
                    final_path,
                    role="final_episode",
                    mime_type="video/mp4",
                ),
                _file_artifact(
                    cover_path,
                    role="cover_image",
                    mime_type="image/jpeg",
                ),
                _file_artifact(
                    share_card_path,
                    role="share_card",
                    mime_type="image/jpeg",
                ),
            )
        return FactoryCoreOutput(
            artifacts=artifacts,
            structured_output={
                "episode_id": shots.episode_id,
                "duration_ms": duration_ms,
                "clip_lineage": clip_lineage,
                "mixed_audio_artifact_id": str(mix_ref.artifact_id),
                "mixed_audio_artifact_digest": mix_ref.content_digest,
                "audio_alignment_revision_id": str(
                    alignment.audio_alignment_revision_id
                ),
                "audio_alignment_digest": alignment.digest,
                "subtitle_artifact_id": str(subtitle_ref.artifact_id),
                "subtitle_artifact_digest": subtitle_ref.content_digest,
                "cover_role": "cover_image",
                "share_card_role": "share_card",
                "speed_change_allowed": False,
                "lipsync_required": False,
            },
            provider_identity="factory-local-core",
        )


__all__ = ["LegacyFactoryOperationRunner"]
