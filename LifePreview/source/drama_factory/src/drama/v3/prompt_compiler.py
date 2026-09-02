from __future__ import annotations

import re
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from shared_contracts import (
    ArtifactRef,
    DirectionContractV1,
    FirstLastFrameRequest,
    GenerationMode,
    GenerationRequest,
    ImageToVideoRequest,
    ModelCapability,
    ReferenceDutyKind,
    TextToVideoRequest,
    VideoResolution,
    stable_json_sha256,
)

from .domain import Clip


class PromptCompilationError(RuntimeError):
    pass


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class WanReferenceBinding(FrozenModel):
    artifact: ArtifactRef
    workflow_input: str = Field(min_length=1, max_length=100)
    duty: Literal[
        "first_frame",
        "last_frame",
        "identity",
        "motion",
        "scene",
        "composition",
    ]
    description: str = Field(min_length=1, max_length=1000)
    exclusions: tuple[str, ...] = ()


class WanWorkflowParameters(FrozenModel):
    steps: int = Field(ge=1, le=100)
    cfg: float = Field(gt=0, le=30)
    seed: int = Field(ge=1, le=2**63 - 1)
    duration_seconds: float = Field(gt=0, le=60)
    resolution: VideoResolution
    aspect_ratio: str = Field(pattern=r"^[1-9][0-9]?:[1-9][0-9]?$")


class CompiledWanPrompt(FrozenModel):
    schema_version: Literal["factory.wan-prompt.v1"] = "factory.wan-prompt.v1"
    prompt_snapshot_id: UUID
    project_revision_id: UUID
    scene_id: UUID
    clip_id: UUID
    run_id: UUID
    mode: GenerationMode
    positive_prompt: str = Field(min_length=1, max_length=8000)
    negative_prompt: str = Field(min_length=1, max_length=4000)
    references: tuple[WanReferenceBinding, ...]
    workflow: WanWorkflowParameters
    model_id: str
    workflow_id: str
    workflow_version: str
    compiler_version: str
    input_state_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    prompt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def prompt_hash_matches(self):
        identity = self.model_dump(mode="json", exclude={"prompt_sha256"})
        if self.prompt_sha256 != stable_json_sha256(identity):
            raise ValueError("compiled prompt hash does not match content")
        return self


_SLOP_REPLACEMENTS = (
    (re.compile(r"\b(?:8k|4k|masterpiece|award[- ]winning|trending on artstation|raw)\b", re.I), ""),
    (re.compile(r"(?:电影感|大片感|高级感|氛围感|史诗级|杰作|顶级品质|超高清)"), ""),
    (re.compile(r"\b(?:cinematic|epic|stunning|beautiful|professional|dynamic)\b", re.I), ""),
)


def _clean_clause(value: str) -> str:
    cleaned = value.strip()
    for pattern, replacement in _SLOP_REPLACEMENTS:
        cleaned = pattern.sub(replacement, cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    cleaned = re.sub(r"[，,；;、]{2,}", "，", cleaned)
    return cleaned.strip(" ，,；;。")


def _state_clause(state: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in sorted(state):
        value = state[key]
        if value is None or value == "" or value == [] or value == {}:
            continue
        label = str(key).replace("_", " ")
        if isinstance(value, bool):
            rendered = "是" if value else "否"
        elif isinstance(value, (list, tuple, set)):
            rendered = "、".join(str(item) for item in value)
        elif isinstance(value, dict):
            rendered = "；".join(
                f"{str(child_key).replace('_', ' ')}为{child_value}"
                for child_key, child_value in sorted(value.items())
            )
        else:
            rendered = str(value)
        parts.append(f"{label}为{rendered}")
    return "，".join(parts)


def _reference_bindings(request: GenerationRequest) -> tuple[WanReferenceBinding, ...]:
    bindings: list[WanReferenceBinding] = []
    if isinstance(request, ImageToVideoRequest):
        bindings.append(
            WanReferenceBinding(
                artifact=request.first_image,
                workflow_input="start_image",
                duty="first_frame",
                description="作为真实首帧和静态起始状态",
            )
        )
    elif isinstance(request, FirstLastFrameRequest):
        bindings.extend(
            (
                WanReferenceBinding(
                    artifact=request.first_image,
                    workflow_input="start_image",
                    duty="first_frame",
                    description="作为真实首帧和静态起始状态",
                ),
                WanReferenceBinding(
                    artifact=request.last_image,
                    workflow_input="end_image",
                    duty="last_frame",
                    description="作为真实尾帧目标",
                ),
            )
        )
    elif not isinstance(request, TextToVideoRequest):
        raise PromptCompilationError("unsupported generation request type")

    for index, reference in enumerate(request.reference_duties):
        bindings.append(
            WanReferenceBinding(
                artifact=reference.artifact,
                workflow_input=f"reference_{index}",
                duty=reference.duty.value,
                description=reference.description,
                exclusions=request.reference_exclusions,
            )
        )

    artifact_ids = [binding.artifact.artifact_id for binding in bindings]
    if len(artifact_ids) != len(set(artifact_ids)):
        raise PromptCompilationError(
            "one artifact cannot occupy multiple workflow reference inputs"
        )
    return tuple(bindings)


class WanPromptCompiler:
    """Compile model-independent direction into one local Wan generation."""

    VERSION = "wan-prompt-compiler.v2"
    DEFAULT_NEGATIVE = (
        "画面不新增文字、字幕、水印或标志；主体身份、服装、道具归属和产品几何保持稳定；"
        "避免跳切、动作重复、肢体粘连、手部畸变、面部漂移和无来源闪光。"
    )

    def compile(
        self,
        *,
        clip: Clip,
        request: GenerationRequest,
        capability: ModelCapability,
        steps: int = 30,
        cfg: float = 5.0,
        rewrite_instruction: str | None = None,
        direction_contract: DirectionContractV1 | None = None,
    ) -> CompiledWanPrompt:
        if request.clip_id != clip.clip_id or request.scene_id != clip.scene_id:
            raise PromptCompilationError("request does not target the supplied clip")
        if request.mode is not capability.operation:
            raise PromptCompilationError("model capability does not support request mode")
        if request.model_id != capability.model_id:
            raise PromptCompilationError("request model does not match capability")
        if request.resolution not in capability.supported_resolutions:
            raise PromptCompilationError("requested resolution is unsupported")
        if request.duration_seconds not in capability.supported_durations_seconds:
            raise PromptCompilationError("requested duration is unsupported")
        if not capability.local_only:
            raise PromptCompilationError("video generation capability must be local")
        if clip.director_state.chain_depth >= 3:
            raise PromptCompilationError("continuation chain requires a canonical re-anchor")

        director = clip.director_state
        actual_start = (
            director.accepted_observed_state
            if director.accepted_observed_state is not None
            else director.planned_start_state
        )
        start_text = _state_clause(actual_start)
        end_text = _state_clause(director.planned_end_state)
        references = _reference_bindings(request)

        clauses: list[str] = []
        if start_text:
            source_kind = (
                "已接受素材的真实结尾"
                if director.accepted_observed_state is not None
                else "计划起始状态"
            )
            clauses.append(f"从{source_kind}开始：{start_text}")
        if director.open_motion_vectors:
            clauses.append(
                "延续开放动作："
                + "；".join(_clean_clause(value) for value in director.open_motion_vectors)
            )

        narrative_job = _clean_clause(
            direction_contract.narrative_job
            if direction_contract is not None
            else director.narrative_job
        )
        if not narrative_job:
            raise PromptCompilationError("narrative job contains no observable direction")
        clauses.append(f"本段只拍一个任务：{narrative_job}")
        if direction_contract is not None:
            felt_intent = _clean_clause(direction_contract.felt_intent)
            if not felt_intent:
                raise PromptCompilationError(
                    "direction contract felt intent contains no direction"
                )
            clauses.append(
                f"导演意图：{felt_intent}；主要生成预算只用于"
                f"{direction_contract.primary_spend}"
            )
        if rewrite_instruction:
            cleaned_rewrite = _clean_clause(rewrite_instruction)
            if not cleaned_rewrite:
                raise PromptCompilationError(
                    "rewrite instruction contains no observable direction"
                )
            clauses.append(f"本次改写要求：{cleaned_rewrite}")

        if direction_contract is None:
            for label, raw in (
                ("动作", clip.contract.motion),
                ("镜头", clip.contract.camera),
                ("光线", clip.contract.lighting),
            ):
                cleaned = _clean_clause(raw)
                if not cleaned:
                    raise PromptCompilationError(f"{label}指令缺少可观察内容")
                clauses.append(f"{label}：{cleaned}")
            clauses.append(f"声音：{_clean_clause(request.audio_intent)}")
        else:
            chain = direction_contract.action_chain
            action_chain = "；".join(
                (
                    f"初态{_clean_clause(chain.initial_state)}",
                    f"触发{_clean_clause(chain.trigger)}",
                    f"决定性变化{_clean_clause(chain.decisive_change)}",
                    f"反应{_clean_clause(chain.response)}",
                    f"跟随动作{_clean_clause(chain.follow_through)}",
                    f"局部终点{_clean_clause(chain.local_endpoint)}",
                )
            )
            clauses.append(f"可见动作链：{action_chain}")
            clauses.append(
                "镜头实际覆盖："
                + "；".join(map(_clean_clause, chain.camera_coverage))
            )
            for label, values in (
                ("构图", direction_contract.composition),
                ("镜头", direction_contract.camera),
                ("表演", direction_contract.performance),
                ("光线", direction_contract.lighting),
            ):
                cleaned_values = tuple(
                    value
                    for value in map(_clean_clause, values)
                    if value
                )
                if not cleaned_values:
                    raise PromptCompilationError(
                        f"direction contract {label}指令缺少可观察内容"
                    )
                clauses.append(f"{label}：{'；'.join(cleaned_values)}")
            sound = tuple(
                value
                for value in map(_clean_clause, direction_contract.sound)
                if value
            )
            clauses.append(
                "声音："
                + ("；".join(sound) if sound else _clean_clause(request.audio_intent))
            )
            if direction_contract.reference_duties:
                clauses.append(
                    "参考职责："
                    + "；".join(
                        f"{_clean_clause(duty.asset_ref)}只负责"
                        f"{'、'.join(duty.owns_dimensions)}，不得迁移"
                        f"{'、'.join(map(_clean_clause, duty.must_not_transfer)) or '未授权维度'}"
                        for duty in direction_contract.reference_duties
                    )
                )

        continuity_locks = tuple(
            dict.fromkeys(
                (
                    *clip.locks,
                    *(
                        direction_contract.continuity_locks
                        if direction_contract is not None
                        else ()
                    ),
                )
            )
        )
        if continuity_locks:
            clauses.append(
                "连续性保持：" + "；".join(map(_clean_clause, continuity_locks))
            )
        completed = tuple(
            dict.fromkeys(
                (
                    *director.completed_beats,
                    *(
                        direction_contract.completed_beats
                        if direction_contract is not None
                        else ()
                    ),
                )
            )
        )
        if completed:
            clauses.append(
                "已完成动作不重复："
                + "；".join(map(_clean_clause, completed))
            )
        reserved = tuple(
            dict.fromkeys(
                (
                    *director.reserved_beats,
                    *clip.reserved_beats,
                    *(
                        direction_contract.reserved_beats
                        if direction_contract is not None
                        else ()
                    ),
                )
            )
        )
        if reserved:
            clauses.append(
                "后续剧情暂不出现：" + "；".join(map(_clean_clause, reserved))
            )
        if end_text:
            clauses.append(f"停在清晰的新状态：{end_text}")

        positive = "。".join(clause for clause in clauses if clause) + "。"
        if "@" in positive:
            raise PromptCompilationError(
                "local Wan prompts cannot contain surface reference tags"
            )
        input_payload = {
            "clip": clip.model_dump(mode="json"),
            "request": request.model_dump(mode="json"),
            "capability": capability.model_dump(mode="json"),
            "steps": steps,
            "cfg": cfg,
            "compiler_version": self.VERSION,
        }
        if direction_contract is not None:
            input_payload["direction_contract"] = direction_contract.model_dump(
                mode="json"
            )
        if rewrite_instruction:
            input_payload["rewrite_instruction"] = rewrite_instruction
        input_hash = stable_json_sha256(input_payload)
        draft = {
            "schema_version": "factory.wan-prompt.v1",
            "prompt_snapshot_id": request.prompt_snapshot_id,
            "project_revision_id": request.project_revision_id,
            "scene_id": request.scene_id,
            "clip_id": request.clip_id,
            "run_id": request.run_id,
            "mode": request.mode,
            "positive_prompt": positive,
            "negative_prompt": self.DEFAULT_NEGATIVE,
            "references": references,
            "workflow": WanWorkflowParameters(
                steps=steps,
                cfg=cfg,
                seed=request.resolved_seed,
                duration_seconds=request.duration_seconds,
                resolution=request.resolution,
                aspect_ratio=request.aspect_ratio,
            ),
            "model_id": request.model_id,
            "workflow_id": capability.workflow_id,
            "workflow_version": capability.workflow_version,
            "compiler_version": self.VERSION,
            "input_state_sha256": input_hash,
        }
        serialized = CompiledWanPrompt.model_construct(
            **draft,
            prompt_sha256="0" * 64,
        ).model_dump(mode="json", exclude={"prompt_sha256"})
        return CompiledWanPrompt(
            **draft,
            prompt_sha256=stable_json_sha256(serialized),
        )
