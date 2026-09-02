from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from shared_contracts import H3GenerationMode, H3SequencePlanV1

from .model_registry import H3CapabilityRevision
from .prompt_renderer import H3PromptRenderer, H3RenderedPrompt
from .reference_binder import H3ReferenceBindingSet
from .validator import validate_h3_sequence_for_render


class H3WorkflowBuildError(ValueError):
    """An H3 abstract or concrete workflow is unsafe or authority-mismatched."""


@dataclass(frozen=True, slots=True)
class H3CompiledWorkflow:
    workflow_json: str
    workflow_digest: str

    def __post_init__(self) -> None:
        value = json.loads(self.workflow_json)
        if not isinstance(value, dict) or _stable_digest(value) != self.workflow_digest:
            raise H3WorkflowBuildError(
                "compiled H3 workflow snapshot does not match its digest"
            )

    @property
    def workflow(self) -> dict[str, object]:
        value = json.loads(self.workflow_json)
        if not isinstance(value, dict):  # pragma: no cover - guarded above
            raise H3WorkflowBuildError("compiled H3 workflow snapshot is invalid")
        return value


@dataclass(frozen=True, slots=True)
class H3ConcreteWorkflow:
    workflow_json: str
    workflow_digest: str
    source_workflow_digest: str
    template_sha256: str
    output_node_id: str

    def __post_init__(self) -> None:
        value = json.loads(self.workflow_json)
        if not isinstance(value, dict) or _stable_digest(value) != self.workflow_digest:
            raise H3WorkflowBuildError(
                "concrete H3 workflow snapshot does not match its digest"
            )

    @property
    def workflow(self) -> dict[str, dict[str, Any]]:
        value = json.loads(self.workflow_json)
        if not isinstance(value, dict):  # pragma: no cover - guarded above
            raise H3WorkflowBuildError("concrete H3 workflow snapshot is invalid")
        return value


@dataclass(frozen=True, slots=True)
class H3StagedReference:
    asset_id: Any
    sha256: str
    remote_name: str

    def __post_init__(self) -> None:
        from uuid import UUID

        if not isinstance(self.asset_id, UUID):
            raise H3WorkflowBuildError("staged H3 reference asset id is invalid")
        if (
            not isinstance(self.sha256, str)
            or len(self.sha256) != 64
            or any(character not in "0123456789abcdef" for character in self.sha256)
        ):
            raise H3WorkflowBuildError("staged H3 reference digest is invalid")
        _safe_remote_reference(self.remote_name)


_PLACEHOLDER_RE = re.compile(r"\{\{([A-Z0-9_]+)\}\}")
_SAFE_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_REFERENCE_NODE_IDS = tuple(str(value) for value in range(16, 25))
_BASE_NODE_TYPES = {
    "1": "UNETLoader",
    "2": "CLIPLoader",
    "3": "VAELoader",
    "4": "VAELoader",
    "5": "MiniMaxH3SigmaShift",
    "6": "MiniMaxH3ReferenceToVideo",
    "7": "RandomNoise",
    "8": "KSamplerSelect",
    "9": "BasicScheduler",
    "10": "BasicGuider",
    "11": "SamplerCustomAdvanced",
    "12": "VAEDecode",
    "13": "VAEDecodeAudio",
    "14": "CreateVideo",
    "15": "SaveVideo",
}
_EXPECTED_PLACEHOLDERS = {
    "H3_DIFFUSION",
    "H3_TEXT_ENCODER",
    "H3_VIDEO_VAE",
    "H3_AUDIO_VAE",
    "SHIFT_VIDEO",
    "SHIFT_AUDIO",
    "PROMPT",
    "WIDTH",
    "HEIGHT",
    "FRAME_COUNT",
    "SEED",
    "SAMPLER",
    "SCHEDULER",
    "STEPS",
    "DENOISE",
    "FPS",
    "FILENAME_PREFIX",
    *{f"REF_IMAGE_{index}" for index in range(1, 10)},
}


def _stable_digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _repository_file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _compiled_authority(
    capability: H3CapabilityRevision,
) -> dict[str, object]:
    return {
        "family": capability.family,
        "model_id": capability.model_id,
        "revision": capability.revision,
        "mode": H3GenerationMode.REF2VA.value,
        "model_files": {
            role: revision.model_dump(mode="json")
            for role, revision in capability.model_files.items()
        },
        "workflow_filename": capability.workflow_filename,
        "workflow_sha256": capability.workflow_sha256,
        "node_schema_sha256": dict(capability.node_schema_sha256),
    }


def build_h3_workflow(
    plan: H3SequencePlanV1,
    rendered: H3RenderedPrompt,
    binding: H3ReferenceBindingSet,
    capability: H3CapabilityRevision,
) -> H3CompiledWorkflow:
    try:
        validate_h3_sequence_for_render(plan, binding, capability)
    except ValueError as exc:
        raise H3WorkflowBuildError(str(exc)) from exc
    canonical = H3PromptRenderer().render(plan, binding, capability)
    if rendered != canonical:
        raise H3WorkflowBuildError("H3 rendered prompt is not the canonical authority")
    if "{{" in rendered.prompt or "}}" in rendered.prompt:
        raise H3WorkflowBuildError("H3 rendered prompt contains workflow markup")
    workflow: dict[str, object] = {
        "schema_version": "h3-ref2va-compiled-workflow.v1",
        "sequence_id": str(plan.sequence_id),
        "compilation_identity_digest": binding.compilation_identity_digest,
        "binding_digest": binding.digest,
        "reference_set_revision_ids": [
            str(value) for value in binding.reference_set_revision_ids
        ],
        "capability_digest": capability.digest,
        "model_authority": _compiled_authority(capability),
        "prompt": rendered.prompt,
        "prompt_digest": rendered.prompt_digest,
        "inputs": [
            {
                "token": item.token,
                "subject_id": item.subject_id,
                "asset_id": str(item.asset_id),
                "artifact_ref": item.artifact_ref,
                "sha256": item.sha256,
                "view_name": item.view_name,
                "reference_set_revision_id": str(item.reference_set_revision_id),
                "media_type": item.media_type,
            }
            for item in binding.items
        ],
        "frame_count": plan.frame_count,
        "fps": plan.fps,
        "execution": capability.execution.model_dump(mode="json"),
        "audio_source": "h3_native",
    }
    return H3CompiledWorkflow(
        workflow_json=json.dumps(
            workflow,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        workflow_digest=_stable_digest(workflow),
    )


def _load_template(
    template_path: Path,
    capability: H3CapabilityRevision,
) -> dict[str, dict[str, Any]]:
    if template_path.name != capability.workflow_filename:
        raise H3WorkflowBuildError("H3 workflow filename is not capability-authorized")
    try:
        if _repository_file_sha256(template_path) != capability.workflow_sha256:
            raise H3WorkflowBuildError("H3 workflow template SHA-256 mismatch")
        graph = json.loads(template_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise H3WorkflowBuildError("H3 workflow template cannot be loaded") from exc
    if not isinstance(graph, dict) or not graph:
        raise H3WorkflowBuildError("H3 workflow template is not an API graph")
    expected_types = {
        **_BASE_NODE_TYPES,
        **{node_id: "LoadImage" for node_id in _REFERENCE_NODE_IDS},
    }
    if any(
        not isinstance(node_id, str)
        or not isinstance(node, dict)
        or set(node) != {"class_type", "inputs"}
        or not isinstance(node.get("class_type"), str)
        or not isinstance(node.get("inputs"), dict)
        for node_id, node in graph.items()
    ):
        raise H3WorkflowBuildError("H3 workflow template contains an invalid API node")
    if {node_id: node["class_type"] for node_id, node in graph.items()} != expected_types:
        raise H3WorkflowBuildError("H3 workflow template topology is not pinned")
    serialized = json.dumps(graph, ensure_ascii=False, allow_nan=False)
    if set(_PLACEHOLDER_RE.findall(serialized)) != _EXPECTED_PLACEHOLDERS:
        raise H3WorkflowBuildError("H3 workflow template placeholders are not pinned")
    lowered = serialized.casefold()
    if any(token in lowered for token in ("cuda", "nvidia", "t2va", "fl2va")):
        raise H3WorkflowBuildError("H3 workflow contains a forbidden platform or mode")
    if (
        graph["2"]["inputs"].get("type") != "minimax"
        or graph["8"]["inputs"].get("sampler_name") != "{{SAMPLER}}"
        or graph["9"]["inputs"].get("scheduler") != "{{SCHEDULER}}"
        or graph["15"]["inputs"].get("format") != "mp4"
    ):
        raise H3WorkflowBuildError("H3 workflow execution profile is not pinned")
    return graph


def _safe_remote_reference(value: str) -> str:
    if not isinstance(value, str):
        raise H3WorkflowBuildError("staged H3 reference name is unsafe")
    path = PurePosixPath(value)
    if (
        not value.startswith("h3/")
        or value.endswith("/")
        or "\\" in value
        or ":" in value
        or path.is_absolute()
        or any(
            part in {"", ".", ".."} or not _SAFE_SEGMENT_RE.fullmatch(part)
            for part in path.parts
        )
        or path.suffix.casefold() not in {".png", ".jpg", ".jpeg", ".webp"}
    ):
        raise H3WorkflowBuildError("staged H3 reference name is unsafe")
    return value


def _substitute(value: object, replacements: dict[str, object]) -> object:
    if isinstance(value, dict):
        return {key: _substitute(item, replacements) for key, item in value.items()}
    if isinstance(value, list):
        return [_substitute(item, replacements) for item in value]
    if isinstance(value, str):
        match = _PLACEHOLDER_RE.fullmatch(value)
        if match:
            try:
                return replacements[match.group(1)]
            except KeyError as exc:
                raise H3WorkflowBuildError(
                    f"H3 workflow placeholder {match.group(1)} is unresolved"
                ) from exc
        if "{{" in value or "}}" in value:
            raise H3WorkflowBuildError("H3 workflow contains a partial placeholder")
    return value


def build_h3_comfy_api_workflow(
    compiled: H3CompiledWorkflow,
    *,
    plan: H3SequencePlanV1,
    rendered: H3RenderedPrompt,
    binding: H3ReferenceBindingSet,
    capability: H3CapabilityRevision,
    template_path: Path,
    staged_references: tuple[H3StagedReference, ...],
    seed: int,
) -> H3ConcreteWorkflow:
    canonical_compiled = build_h3_workflow(plan, rendered, binding, capability)
    if compiled != canonical_compiled:
        raise H3WorkflowBuildError(
            "compiled H3 workflow is not the canonical plan and binding authority"
        )
    try:
        capability.assert_exact_truth()
    except ValueError as exc:
        raise H3WorkflowBuildError(str(exc)) from exc
    if _stable_digest(compiled.workflow) != compiled.workflow_digest:
        raise H3WorkflowBuildError("compiled H3 workflow digest does not match payload")
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= 2**63 - 1:
        raise H3WorkflowBuildError("H3 seed is outside the supported range")
    abstract = compiled.workflow
    if (
        abstract.get("capability_digest") != capability.digest
        or abstract.get("model_authority") != _compiled_authority(capability)
        or abstract.get("audio_source") != "h3_native"
    ):
        raise H3WorkflowBuildError("compiled H3 capability authority mismatch")
    inputs = abstract.get("inputs")
    if not isinstance(inputs, list):
        raise H3WorkflowBuildError("compiled H3 workflow inputs are invalid")
    if not 1 <= len(inputs) <= capability.max_reference_images:
        raise H3WorkflowBuildError("H3 Ref2VA requires between one and nine images")
    if len(staged_references) != len(inputs):
        raise H3WorkflowBuildError("staged H3 references do not match binding inputs")
    safe_names = tuple(
        _safe_remote_reference(item.remote_name) for item in staged_references
    )
    if len(safe_names) != len(set(safe_names)):
        raise H3WorkflowBuildError("staged H3 reference names must be unique")
    if any(
        not isinstance(item, dict)
        or item.get("media_type") != "image"
        or not isinstance(item.get("sha256"), str)
        or len(item["sha256"]) != 64
        or any(character not in "0123456789abcdef" for character in item["sha256"])
        for item in inputs
    ):
        raise H3WorkflowBuildError("compiled H3 binding accepts image references only")
    expected_staging = tuple(
        (str(item.get("asset_id")), str(item.get("sha256"))) for item in inputs
    )
    actual_staging = tuple(
        (str(item.asset_id), item.sha256) for item in staged_references
    )
    if actual_staging != expected_staging:
        raise H3WorkflowBuildError(
            "staged H3 references do not match asset and digest binding order"
        )

    graph = deepcopy(_load_template(template_path, capability))
    conditioning = graph["6"]["inputs"]
    for index in range(len(safe_names), capability.max_reference_images):
        graph.pop(_REFERENCE_NODE_IDS[index])
        conditioning.pop(f"ref_images.ref_image_{index}")
    execution = capability.execution
    sequence_id = abstract.get("sequence_id")
    frame_count = abstract.get("frame_count")
    prompt = abstract.get("prompt")
    if (
        not isinstance(sequence_id, str)
        or not isinstance(prompt, str)
        or not prompt
        or not isinstance(frame_count, int)
        or frame_count < 73
        or frame_count > 362
        or frame_count % 17 != 5
        or abstract.get("fps") != execution.fps
        or abstract.get("execution") != execution.model_dump(mode="json")
    ):
        raise H3WorkflowBuildError("compiled H3 execution authority is invalid")
    replacements: dict[str, object] = {
        "H3_DIFFUSION": capability.ref2va.filename,
        "H3_TEXT_ENCODER": capability.text_encoder.filename,
        "H3_VIDEO_VAE": capability.video_vae.filename,
        "H3_AUDIO_VAE": capability.audio_vae.filename,
        "SHIFT_VIDEO": execution.shift_video,
        "SHIFT_AUDIO": execution.shift_audio,
        "PROMPT": prompt,
        "WIDTH": execution.width,
        "HEIGHT": execution.height,
        "FRAME_COUNT": frame_count,
        "SEED": seed,
        "SAMPLER": execution.sampler_name,
        "SCHEDULER": execution.scheduler,
        "STEPS": execution.steps,
        "DENOISE": execution.denoise,
        "FPS": float(execution.fps),
        "FILENAME_PREFIX": f"h3/{sequence_id}/{compiled.workflow_digest[:16]}",
    }
    replacements.update(
        {f"REF_IMAGE_{index}": name for index, name in enumerate(safe_names, 1)}
    )
    concrete = _substitute(graph, replacements)
    if not isinstance(concrete, dict):
        raise H3WorkflowBuildError("concrete H3 workflow is not an API graph")
    serialized = json.dumps(concrete, ensure_ascii=False, allow_nan=False)
    if _PLACEHOLDER_RE.search(serialized):
        raise H3WorkflowBuildError("concrete H3 workflow contains placeholders")
    if any(
        token in serialized.casefold()
        for token in (
            "cuda",
            "nvidia",
            "/workspace",
            "/persistent",
            "file://",
            "http://",
            "https://",
        )
    ):
        raise H3WorkflowBuildError("concrete H3 workflow contains a forbidden path")
    return H3ConcreteWorkflow(
        workflow_json=json.dumps(
            concrete,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        workflow_digest=_stable_digest(concrete),
        source_workflow_digest=compiled.workflow_digest,
        template_sha256=capability.workflow_sha256,
        output_node_id=execution.output_node_id,
    )


def build_competition_single_reference_comfy_api_workflow(
    *,
    capability: H3CapabilityRevision,
    template_path: Path,
    sequence_id: str,
    prompt: str,
    prompt_sha256: str,
    staged_reference: H3StagedReference,
    seed: int,
) -> H3ConcreteWorkflow:
    """Build the isolated competition profile without weakening V1 contracts.

    The production ``CharacterReferenceSetV1`` and binder continue to require
    three frozen canonical views.  Today's competition adapter intentionally
    carries one prompt-synthesized ``front_three_quarter`` image and compiles
    it directly into the already pinned H3 Ref2VA API template.
    """

    try:
        capability.assert_exact_truth()
    except ValueError as exc:
        raise H3WorkflowBuildError(str(exc)) from exc
    if (
        not isinstance(sequence_id, str)
        or not sequence_id.strip()
        or not isinstance(prompt, str)
        or not prompt.strip()
        or hashlib.sha256(prompt.encode("utf-8")).hexdigest() != prompt_sha256
        or isinstance(seed, bool)
        or not isinstance(seed, int)
        or not 0 <= seed <= 2**63 - 1
    ):
        raise H3WorkflowBuildError("competition single-reference authority is invalid")
    safe_name = _safe_remote_reference(staged_reference.remote_name)
    execution = capability.execution
    if execution.fps != 24:
        raise H3WorkflowBuildError("competition H3 capability must run at 24 fps")
    graph = deepcopy(_load_template(template_path, capability))
    conditioning = graph["6"]["inputs"]
    for index in range(1, capability.max_reference_images):
        graph.pop(_REFERENCE_NODE_IDS[index])
        conditioning.pop(f"ref_images.ref_image_{index}")
    authority = {
        "schemaVersion": "amd.competition-single-reference-h3-workflow.v1",
        "referenceProfile": "competition-prompt-single-view-v1",
        "sourceMode": "prompt_synthesized",
        "requiredImages": 1,
        "view": "front_three_quarter",
        "sequenceId": sequence_id,
        "promptSha256": prompt_sha256,
        "referenceAssetId": str(staged_reference.asset_id),
        "referenceSha256": staged_reference.sha256,
        "referenceRemoteName": safe_name,
        "requestedDurationSeconds": 3.0,
        "frameCount": 73,
        "fps": 24,
        "nativeAudio": True,
        "subtitles": False,
        "capabilityDigest": capability.digest,
        "seed": seed,
    }
    source_digest = _stable_digest(authority)
    replacements: dict[str, object] = {
        "H3_DIFFUSION": capability.ref2va.filename,
        "H3_TEXT_ENCODER": capability.text_encoder.filename,
        "H3_VIDEO_VAE": capability.video_vae.filename,
        "H3_AUDIO_VAE": capability.audio_vae.filename,
        "SHIFT_VIDEO": execution.shift_video,
        "SHIFT_AUDIO": execution.shift_audio,
        "PROMPT": prompt,
        "WIDTH": execution.width,
        "HEIGHT": execution.height,
        "FRAME_COUNT": 73,
        "SEED": seed,
        "SAMPLER": execution.sampler_name,
        "SCHEDULER": execution.scheduler,
        "STEPS": execution.steps,
        "DENOISE": execution.denoise,
        "FPS": 24.0,
        "FILENAME_PREFIX": f"h3/{sequence_id}/{source_digest[:16]}",
        "REF_IMAGE_1": safe_name,
    }
    concrete = _substitute(graph, replacements)
    if not isinstance(concrete, dict):
        raise H3WorkflowBuildError("competition H3 workflow is not an API graph")
    serialized = json.dumps(concrete, ensure_ascii=False, allow_nan=False)
    if _PLACEHOLDER_RE.search(serialized):
        raise H3WorkflowBuildError("competition H3 workflow contains placeholders")
    if any(
        token in serialized.casefold()
        for token in (
            "cuda",
            "nvidia",
            "/workspace",
            "/persistent",
            "file://",
            "http://",
            "https://",
            "subtitle",
            ".srt",
            ".vtt",
        )
    ):
        raise H3WorkflowBuildError("competition H3 workflow contains forbidden authority")
    return H3ConcreteWorkflow(
        workflow_json=json.dumps(
            concrete,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        workflow_digest=_stable_digest(concrete),
        source_workflow_digest=source_digest,
        template_sha256=capability.workflow_sha256,
        output_node_id=execution.output_node_id,
    )


def validate_h3_comfy_api_workflow(
    concrete: H3ConcreteWorkflow,
    object_info: dict[str, Any],
    *,
    capability: H3CapabilityRevision,
) -> None:
    try:
        capability.assert_exact_truth()
    except ValueError as exc:
        raise H3WorkflowBuildError(str(exc)) from exc
    if _stable_digest(concrete.workflow) != concrete.workflow_digest:
        raise H3WorkflowBuildError("concrete H3 workflow digest does not match payload")
    output = concrete.workflow.get(concrete.output_node_id)
    if output is None or output.get("class_type") != "SaveVideo":
        raise H3WorkflowBuildError("concrete H3 workflow output node is invalid")
    for node_id, node in concrete.workflow.items():
        class_type = node.get("class_type")
        inputs = node.get("inputs")
        schema = object_info.get(class_type) if isinstance(class_type, str) else None
        if not isinstance(inputs, dict) or not isinstance(schema, dict):
            raise H3WorkflowBuildError(f"Comfy schema is missing for H3 node {node_id}")
        input_schema = schema.get("input")
        if not isinstance(input_schema, dict):
            raise H3WorkflowBuildError(f"Comfy input schema is invalid for H3 node {node_id}")
        required = input_schema.get("required") or {}
        optional = input_schema.get("optional") or {}
        hidden = input_schema.get("hidden") or {}
        if not all(isinstance(value, dict) for value in (required, optional, hidden)):
            raise H3WorkflowBuildError(f"Comfy input schema is invalid for H3 node {node_id}")
        expected_schema_digest = capability.node_schema_sha256.get(str(class_type))
        if (
            expected_schema_digest is not None
            and _stable_digest(schema) != expected_schema_digest
        ):
            raise H3WorkflowBuildError(
                f"Comfy live schema digest mismatch for H3 node {class_type}"
            )
        input_specs = {**required, **optional, **hidden}
        allowed = set(input_specs)

        def allowed_input(key: str) -> bool:
            if key in allowed:
                return True
            for container, spec in input_specs.items():
                if not key.startswith(f"{container}."):
                    continue
                if (
                    not isinstance(spec, list)
                    or len(spec) < 2
                    or spec[0] != "COMFY_AUTOGROW_V3"
                    or not isinstance(spec[1], dict)
                ):
                    return False
                suffix = key[len(container) + 1 :]
                template = spec[1].get("template")
                if not isinstance(template, dict):
                    return False
                prefix = template.get("prefix")
                maximum = template.get("max")
                if not isinstance(prefix, str) or not isinstance(maximum, int):
                    return False
                ordinal = suffix.removeprefix(prefix)
                return (
                    suffix.startswith(prefix)
                    and ordinal.isascii()
                    and ordinal.isdigit()
                    and str(int(ordinal)) == ordinal
                    and 0 <= int(ordinal) < maximum
                )
            return False

        unknown = sorted(
            key
            for key in inputs
            if not allowed_input(key)
        )
        if unknown:
            raise H3WorkflowBuildError(
                f"H3 node {node_id} has unknown input: {', '.join(unknown)}"
            )
        missing = sorted(set(required) - set(inputs))
        if missing:
            raise H3WorkflowBuildError(
                f"H3 node {node_id} is missing required input: {', '.join(missing)}"
            )
        for value in inputs.values():
            if (
                isinstance(value, list)
                and len(value) == 2
                and isinstance(value[0], str)
                and isinstance(value[1], int)
                and value[0] not in concrete.workflow
            ):
                raise H3WorkflowBuildError(f"H3 node {node_id} references a missing node")


__all__ = [
    "H3CompiledWorkflow",
    "H3ConcreteWorkflow",
    "H3StagedReference",
    "H3WorkflowBuildError",
    "build_h3_comfy_api_workflow",
    "build_h3_workflow",
    "validate_h3_comfy_api_workflow",
]
