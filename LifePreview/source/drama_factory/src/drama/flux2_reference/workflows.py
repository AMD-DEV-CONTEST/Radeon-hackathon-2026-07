from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterator, Mapping
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any

from .model_registry import Flux2DevCapability, Flux2WorkflowRole
from .qc import ReferenceManufacturingError


_REFERENCE_COUNTS = {
    "text_to_image": 0,
    "single_reference_edit": 1,
    "dual_reference_edit": 2,
}
_PLACEHOLDERS = {
    "text_to_image": {
        "FLUX2_UNET",
        "FLUX2_CLIP",
        "POS_PROMPT",
        "FLUX2_GUIDANCE",
        "SEED",
        "FLUX2_STEPS",
        "WIDTH",
        "HEIGHT",
        "FLUX2_VAE",
        "FILENAME_PREFIX",
    },
    "single_reference_edit": {
        "FLUX2_UNET",
        "FLUX2_CLIP",
        "POS_PROMPT",
        "FLUX2_GUIDANCE",
        "REF_IMAGE",
        "FLUX2_REF_MEGAPIXELS",
        "FLUX2_VAE",
        "SEED",
        "FLUX2_STEPS",
        "WIDTH",
        "HEIGHT",
        "FILENAME_PREFIX",
    },
    "dual_reference_edit": {
        "FLUX2_UNET",
        "FLUX2_CLIP",
        "POS_PROMPT",
        "FLUX2_GUIDANCE",
        "REF_IMAGE",
        "REF_IMAGE2",
        "FLUX2_REF_MEGAPIXELS",
        "FLUX2_VAE",
        "SEED",
        "FLUX2_STEPS",
        "WIDTH",
        "HEIGHT",
        "FILENAME_PREFIX",
    },
}
_PLACEHOLDER_RE = re.compile(r"\{\{([A-Z0-9_]+)\}\}")
_SAFE_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_NODE_TYPES = {
    "text_to_image": {
        "1": "UNETLoader",
        "2": "CLIPLoader",
        "3": "CLIPTextEncode",
        "4": "FluxGuidance",
        "5": "BasicGuider",
        "6": "RandomNoise",
        "7": "KSamplerSelect",
        "8": "Flux2Scheduler",
        "9": "EmptyFlux2LatentImage",
        "10": "SamplerCustomAdvanced",
        "11": "VAELoader",
        "12": "VAEDecode",
        "13": "SaveImage",
    },
    "single_reference_edit": {
        "1": "UNETLoader",
        "2": "CLIPLoader",
        "3": "CLIPTextEncode",
        "4": "FluxGuidance",
        "5": "BasicGuider",
        "6": "RandomNoise",
        "7": "KSamplerSelect",
        "8": "Flux2Scheduler",
        "9": "EmptyFlux2LatentImage",
        "10": "SamplerCustomAdvanced",
        "12": "VAEDecode",
        "13": "SaveImage",
        "20": "LoadImage",
        "21": "ImageScaleToTotalPixels",
        "22": "VAELoader",
        "23": "VAEEncode",
        "24": "ReferenceLatent",
    },
    "dual_reference_edit": {
        "1": "UNETLoader",
        "2": "CLIPLoader",
        "3": "CLIPTextEncode",
        "4": "FluxGuidance",
        "5": "BasicGuider",
        "6": "RandomNoise",
        "7": "KSamplerSelect",
        "8": "Flux2Scheduler",
        "9": "EmptyFlux2LatentImage",
        "10": "SamplerCustomAdvanced",
        "12": "VAEDecode",
        "13": "SaveImage",
        "20": "LoadImage",
        "21": "ImageScaleToTotalPixels",
        "22": "VAELoader",
        "23": "VAEEncode",
        "24": "ReferenceLatent",
        "25": "LoadImage",
        "26": "ImageScaleToTotalPixels",
        "27": "VAEEncode",
        "28": "ReferenceLatent",
    },
}


def _sha256_bytes(value: bytes) -> str:
    # Git may materialize tracked JSON with CRLF on Windows. The repository and
    # Linux release digest is the canonical LF byte stream.
    return hashlib.sha256(value.replace(b"\r\n", b"\n")).hexdigest()


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _all_strings(value: object) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield str(key)
            yield from _all_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _all_strings(item)


def _validate_graph(role: str, graph: object) -> dict[str, dict[str, Any]]:
    if not isinstance(graph, dict) or not graph:
        raise ReferenceManufacturingError(f"FLUX.2-dev {role} workflow is not an API graph")
    for node_id, node in graph.items():
        if (
            not isinstance(node_id, str)
            or not node_id.isdigit()
            or not isinstance(node, dict)
            or set(node) != {"class_type", "inputs"}
            or not isinstance(node.get("class_type"), str)
            or not isinstance(node.get("inputs"), dict)
        ):
            raise ReferenceManufacturingError(
                f"FLUX.2-dev {role} workflow has an invalid API node"
            )
    node_types = {node_id: node["class_type"] for node_id, node in graph.items()}
    if node_types != _NODE_TYPES[role]:
        raise ReferenceManufacturingError(
            f"FLUX.2-dev {role} workflow topology is not the pinned core API graph"
        )
    serialized = json.dumps(graph, ensure_ascii=False, allow_nan=False)
    lowered = serialized.casefold()
    if any(token in lowered for token in ("cuda", "nvidia", "cogview", "cloud api")):
        raise ReferenceManufacturingError(
            f"FLUX.2-dev {role} workflow contains forbidden execution logic"
        )
    placeholders = set(_PLACEHOLDER_RE.findall(serialized))
    if placeholders != _PLACEHOLDERS[role]:
        raise ReferenceManufacturingError(
            f"FLUX.2-dev {role} workflow placeholders do not match the capability"
        )
    load_images = sum(
        node["class_type"] == "LoadImage" for node in graph.values()
    )
    if load_images != _REFERENCE_COUNTS[role]:
        raise ReferenceManufacturingError(
            f"FLUX.2-dev {role} workflow has the wrong reference count"
        )
    if (
        graph["1"]["inputs"] != {
            "unet_name": "{{FLUX2_UNET}}",
            "weight_dtype": "default",
        }
        or graph["2"]["inputs"] != {
            "clip_name": "{{FLUX2_CLIP}}",
            "type": "flux2",
            "device": "default",
        }
        or graph["7"]["inputs"] != {"sampler_name": "euler"}
        or graph["8"]["inputs"] != {
            "steps": "{{FLUX2_STEPS}}",
            "width": "{{WIDTH}}",
            "height": "{{HEIGHT}}",
        }
        or graph["13"]["inputs"].get("filename_prefix")
        != "{{FILENAME_PREFIX}}"
    ):
        raise ReferenceManufacturingError(
            f"FLUX.2-dev {role} workflow execution profile is not pinned"
        )
    output = graph.get("13")
    if output is None or output["class_type"] != "SaveImage":
        raise ReferenceManufacturingError(
            f"FLUX.2-dev {role} workflow output node is not pinned"
        )
    return graph


@dataclass(frozen=True, slots=True)
class Flux2WorkflowTemplate:
    role: Flux2WorkflowRole
    filename: str
    workflow: dict[str, dict[str, Any]]
    template_sha256: str
    source_bytes: bytes


class Flux2WorkflowTemplates(Mapping[str, Flux2WorkflowTemplate]):
    def __init__(
        self,
        values: Mapping[str, Flux2WorkflowTemplate],
        *,
        capability_digest: str,
    ) -> None:
        self._values = MappingProxyType(dict(values))
        self.capability_digest = capability_digest

    def __getitem__(self, key: str) -> Flux2WorkflowTemplate:
        return self._values[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)


@dataclass(frozen=True, slots=True)
class CompiledFlux2Workflow:
    role: Flux2WorkflowRole
    workflow_json: str
    workflow_digest: str
    template_sha256: str
    output_node_id: str

    def __post_init__(self) -> None:
        try:
            value = json.loads(self.workflow_json)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ReferenceManufacturingError(
                "compiled FLUX.2 workflow snapshot is invalid"
            ) from exc
        if not isinstance(value, dict) or _digest(value) != self.workflow_digest:
            raise ReferenceManufacturingError(
                "compiled FLUX.2 workflow digest does not match its snapshot"
            )

    @property
    def workflow(self) -> dict[str, dict[str, Any]]:
        """Return a disposable API payload; the digest-bound snapshot stays immutable."""

        value = json.loads(self.workflow_json)
        if not isinstance(value, dict):  # pragma: no cover - guarded in __post_init__
            raise ReferenceManufacturingError(
                "compiled FLUX.2 workflow snapshot is invalid"
            )
        return value


def load_flux2_workflow_templates(
    workflow_root: Path,
    capability: Flux2DevCapability,
) -> Flux2WorkflowTemplates:
    root = workflow_root.resolve()
    if not root.is_dir():
        raise ReferenceManufacturingError("FLUX.2-dev workflow root is unavailable")
    loaded: dict[str, Flux2WorkflowTemplate] = {}
    for revision in capability.workflows:
        path = (root / revision.filename).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ReferenceManufacturingError(
                "FLUX.2-dev workflow path escaped the configured root"
            ) from exc
        try:
            source = path.read_bytes()
            if _sha256_bytes(source) != revision.sha256:
                raise ReferenceManufacturingError(
                    f"FLUX.2-dev {revision.role} workflow SHA-256 mismatch"
                )
            graph = json.loads(source.decode("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ReferenceManufacturingError(
                f"FLUX.2-dev {revision.role} workflow cannot be loaded"
            ) from exc
        loaded[revision.role] = Flux2WorkflowTemplate(
            role=revision.role,
            filename=revision.filename,
            workflow=_validate_graph(revision.role, graph),
            template_sha256=revision.sha256,
            source_bytes=source,
        )
    if set(loaded) != set(_REFERENCE_COUNTS):
        raise ReferenceManufacturingError(
            "FLUX.2-dev workflow capability is missing a required role"
        )
    return Flux2WorkflowTemplates(loaded, capability_digest=capability.digest)


def _safe_reference_image(value: str) -> str:
    path = PurePosixPath(value)
    if (
        not value
        or "\\" in value
        or ":" in value
        or path.is_absolute()
        or path.name in {"", ".", ".."}
        or any(part in {"", ".", ".."} or not _SAFE_SEGMENT_RE.fullmatch(part) for part in path.parts)
        or path.suffix.casefold() not in {".png", ".jpg", ".jpeg", ".webp"}
    ):
        raise ReferenceManufacturingError("FLUX.2-dev source image name is unsafe")
    return value


def _safe_filename_prefix(value: str) -> str:
    path = PurePosixPath(value)
    if (
        not value
        or "\\" in value
        or ":" in value
        or path.is_absolute()
        or value.endswith("/")
        or any(part in {"", ".", ".."} or not _SAFE_SEGMENT_RE.fullmatch(part) for part in path.parts)
    ):
        raise ReferenceManufacturingError("FLUX.2-dev filename prefix is unsafe")
    return value


def _substitute(value: object, replacements: Mapping[str, object]) -> object:
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
                raise ReferenceManufacturingError(
                    f"FLUX.2-dev workflow placeholder {match.group(1)} is unresolved"
                ) from exc
        if "{{" in value or "}}" in value:
            raise ReferenceManufacturingError(
                "FLUX.2-dev workflow contains a partial placeholder"
            )
    return value


def compile_flux2_workflow(
    *,
    role: str,
    templates: Flux2WorkflowTemplates,
    capability: Flux2DevCapability,
    prompt: str,
    width: int,
    height: int,
    seed: int,
    reference_images: tuple[str, ...],
    filename_prefix: str,
) -> CompiledFlux2Workflow:
    if role not in _REFERENCE_COUNTS:
        raise ReferenceManufacturingError(f"unknown FLUX.2-dev workflow role: {role}")
    if templates.capability_digest != capability.digest:
        raise ReferenceManufacturingError(
            "FLUX.2-dev workflow templates do not match the capability"
        )
    if len(reference_images) != _REFERENCE_COUNTS[role]:
        raise ReferenceManufacturingError(
            f"FLUX.2-dev {role} requires exactly {_REFERENCE_COUNTS[role]} reference images"
        )
    if (
        isinstance(width, bool)
        or isinstance(height, bool)
        or width != capability.execution.width
        or height != capability.execution.height
    ):
        raise ReferenceManufacturingError(
            "FLUX.2-dev execution must use the pinned 512x768 resolution"
        )
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed < 2**64:
        raise ReferenceManufacturingError("FLUX.2-dev seed is outside the supported range")
    if not isinstance(prompt, str) or not prompt.strip() or "{{" in prompt or "}}" in prompt:
        raise ReferenceManufacturingError("FLUX.2-dev prompt is empty or unsafe")
    safe_references = tuple(_safe_reference_image(item) for item in reference_images)
    safe_prefix = _safe_filename_prefix(filename_prefix)
    template = templates[role]
    revision = capability.workflow(role)
    if (
        template.filename != revision.filename
        or template.template_sha256 != revision.sha256
        or _sha256_bytes(template.source_bytes) != revision.sha256
        or json.loads(template.source_bytes.decode("utf-8")) != template.workflow
    ):
        raise ReferenceManufacturingError(
            f"FLUX.2-dev {role} workflow template was altered after verification"
        )
    replacements: dict[str, object] = {
        "FLUX2_UNET": capability.diffusion_model.filename,
        "FLUX2_CLIP": capability.text_encoder.filename,
        "FLUX2_VAE": capability.vae.filename,
        "POS_PROMPT": prompt.strip(),
        "FLUX2_GUIDANCE": capability.execution.guidance,
        "FLUX2_STEPS": capability.execution.steps,
        "FLUX2_REF_MEGAPIXELS": capability.execution.reference_megapixels,
        "SEED": seed,
        "WIDTH": width,
        "HEIGHT": height,
        "FILENAME_PREFIX": safe_prefix,
    }
    if safe_references:
        replacements["REF_IMAGE"] = safe_references[0]
    if len(safe_references) == 2:
        replacements["REF_IMAGE2"] = safe_references[1]
    graph = _substitute(deepcopy(template.workflow), replacements)
    if not isinstance(graph, dict) or any(
        "{{" in item or "}}" in item for item in _all_strings(graph)
    ):
        raise ReferenceManufacturingError(
            f"FLUX.2-dev {role} workflow compilation left placeholders"
        )
    return CompiledFlux2Workflow(
        role=role,  # type: ignore[arg-type]
        workflow_json=json.dumps(
            graph,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        workflow_digest=_digest(graph),
        template_sha256=template.template_sha256,
        output_node_id=capability.execution.output_node_id,
    )


__all__ = [
    "CompiledFlux2Workflow",
    "Flux2WorkflowTemplate",
    "Flux2WorkflowTemplates",
    "compile_flux2_workflow",
    "load_flux2_workflow_templates",
]
