"""Generation requests and their deterministic hash material."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field, replace
from typing import Literal

from specstyle.domain.artifacts import AssetRef
from specstyle.domain.identifiers import AttemptId, Identifier, JobId, Sha256
from specstyle.errors import DomainError
from specstyle.generation.preprocess import (
    PreparedImage,
    PreprocessPlan,
    PreprocessSnapshot,
    _rebuild_asset_ref,
    _rebuild_resource_pin,
)
from specstyle.generation.seed_policy import SeedSnapshot, derive_seed
from specstyle.spec.compiled_models import (
    CompiledExecutionGraph,
    CompiledStyleSpec,
    GenerationProfile,
    OutputProfile,
    ResourcePin,
)


def _safe_text(value: object, *, empty: bool) -> str:
    if (
        type(value) is not str
        or (not empty and not value)
        or value != value.strip()
        or any(ord(char) <= 31 or ord(char) == 127 for char in value)
    ):
        raise DomainError("invalid prompt text")
    if len(value) > 2048:
        raise DomainError("invalid prompt text")
    return value


def _hash(domain: str, payload: dict[str, object]) -> Sha256:
    encoded = json.dumps(
        {"domain": domain, **payload},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return Sha256(hashlib.sha256(encoded).hexdigest())


def _sha(value: object) -> str:
    if type(value) is not Sha256:
        raise DomainError("invalid hash material")
    return Sha256(value.value).value


def _identifier(value: object, expected: type[Identifier]) -> str:
    if type(value) is not expected:
        raise DomainError("invalid identifier material")
    return expected(value.value).value


def _pin(value: object) -> dict[str, str]:
    pin = _rebuild_resource_pin(value)
    return {"id": pin.id, "revision": pin.revision, "sha256": _sha(pin.sha256)}


def _asset(value: object) -> dict[str, str]:
    ref = _rebuild_asset_ref(value)
    return {"asset_id": ref.asset_id.value, "sha256": _sha(ref.sha256)}


def _plan(value: object) -> dict[str, object]:
    if type(value) is not PreprocessPlan:
        raise DomainError("invalid plan material")
    rebuilt = PreprocessPlan(
        value.target_size, value.resize_mode, value.background, value.processor_pin
    )
    return {
        "target_size": list(rebuilt.target_size),
        "resize_mode": rebuilt.resize_mode,
        "background": list(rebuilt.background),
        "processor_pin": _pin(rebuilt.processor_pin),
    }


def _snapshot(value: object) -> dict[str, object]:
    if type(value) is not PreprocessSnapshot:
        raise DomainError("invalid snapshot material")
    rebuilt = PreprocessSnapshot(
        value.plan,
        value.input_format,
        value.input_mode,
        value.input_size,
        value.exif_orientation,
        value.pillow_version,
    )
    return {
        "plan": _plan(rebuilt.plan),
        "input_format": rebuilt.input_format,
        "input_mode": rebuilt.input_mode,
        "input_size": list(rebuilt.input_size),
        "exif_orientation": rebuilt.exif_orientation,
        "pillow_version": rebuilt.pillow_version,
    }


def _prepared(value: object) -> dict[str, object]:
    if type(value) is not PreparedImage:
        raise DomainError("invalid prepared image material")
    rebuilt = PreparedImage(value.source, value.content, value.snapshot)
    return {
        "source": _asset(rebuilt.source),
        "sha256": _sha(rebuilt.sha256),
        "snapshot": _snapshot(rebuilt.snapshot),
    }


@dataclass(frozen=True, slots=True)
class RenderedPrompt:
    template_pin: ResourcePin
    preset_id: Identifier
    positive: str
    negative: str

    def __post_init__(self) -> None:
        if type(self.preset_id) is not Identifier:
            raise DomainError("invalid rendered prompt")
        pin = _rebuild_resource_pin(self.template_pin)
        preset = Identifier(self.preset_id.value)
        positive = _safe_text(self.positive, empty=False)
        negative = _safe_text(self.negative, empty=True)
        object.__setattr__(self, "template_pin", pin)
        object.__setattr__(self, "preset_id", preset)
        object.__setattr__(self, "positive", positive)
        object.__setattr__(self, "negative", negative)


@dataclass(frozen=True, slots=True)
class PreparedControlInput:
    kind: Literal["canny", "depth", "pose"]
    image: PreparedImage

    def __post_init__(self) -> None:
        if type(self.kind) is not str or self.kind not in {"canny", "depth", "pose"}:
            raise DomainError("invalid control input")
        image = PreparedImage(
            self.image.source, self.image.content, self.image.snapshot
        )
        object.__setattr__(self, "image", image)

    @property
    def source(self) -> AssetRef:
        return self.image.source

    @property
    def processor_pin(self) -> ResourcePin:
        return self.image.snapshot.plan.processor_pin


@dataclass(frozen=True, slots=True)
class GenerationParameters:
    ip_adapter_scale: float
    img2img_strength: float
    controlnet_scale: float

    def __post_init__(self) -> None:
        for value in (
            self.ip_adapter_scale,
            self.img2img_strength,
            self.controlnet_scale,
        ):
            if (
                type(value) is not float
                or not math.isfinite(value)
                or not 0 <= value <= 1
            ):
                raise DomainError("invalid generation parameters")


@dataclass(frozen=True, slots=True)
class GenerationRequest:
    job_id: JobId
    attempt_id: AttemptId
    parent_attempt_id: AttemptId | None
    compiled_spec: CompiledStyleSpec
    generation_profile: GenerationProfile
    output_profile: OutputProfile
    source: PreparedImage
    style_references: tuple[AssetRef, ...]
    prompt: RenderedPrompt
    control_input: PreparedControlInput
    variation_index: int
    environment_hash: Sha256
    execution_parameters: GenerationParameters | None = None
    seed: SeedSnapshot = field(init=False)
    request_hash: Sha256 = field(init=False)
    generation_fingerprint: Sha256 = field(init=False)

    def __post_init__(self) -> None:
        self._validate_types()
        recomputed = replace(self.compiled_spec)
        if recomputed.compiled_spec_hash != self.compiled_spec.compiled_spec_hash:
            raise DomainError("forged compiled spec hash")
        graph = self._resolve_graph()
        self._resolve_execution_parameters(graph)
        self._validate_materials(graph)
        seed = derive_seed(
            self.source.source.sha256,
            self.compiled_spec.compiled_spec_hash,
            self.output_profile,
            self.variation_index,
        )
        object.__setattr__(self, "seed", seed)
        fingerprint = _hash(
            "specstyle.generation.materials.v2",
            self._fingerprint_materials(graph, seed),
        )
        object.__setattr__(self, "generation_fingerprint", fingerprint)
        object.__setattr__(
            self,
            "request_hash",
            _hash(
                "specstyle.generation.request.v2",
                {
                    "generation_fingerprint": _sha(fingerprint),
                    "job_id": _identifier(self.job_id, JobId),
                    "attempt_id": _identifier(self.attempt_id, AttemptId),
                    "parent_attempt_id": (
                        None
                        if self.parent_attempt_id is None
                        else _identifier(self.parent_attempt_id, AttemptId)
                    ),
                    "environment_hash": _sha(self.environment_hash),
                },
            ),
        )

    def _validate_types(self) -> None:
        if (
            type(self.job_id) is not JobId
            or type(self.attempt_id) is not AttemptId
            or (
                self.parent_attempt_id is not None
                and type(self.parent_attempt_id) is not AttemptId
            )
            or type(self.compiled_spec) is not CompiledStyleSpec
            or type(self.source) is not PreparedImage
            or type(self.prompt) is not RenderedPrompt
            or type(self.control_input) is not PreparedControlInput
            or type(self.environment_hash) is not Sha256
        ):
            raise DomainError("invalid generation request")
        object.__setattr__(self, "job_id", JobId(self.job_id.value))
        object.__setattr__(self, "attempt_id", AttemptId(self.attempt_id.value))
        if self.parent_attempt_id is not None:
            object.__setattr__(
                self, "parent_attempt_id", AttemptId(self.parent_attempt_id.value)
            )
        object.__setattr__(
            self, "environment_hash", Sha256(self.environment_hash.value)
        )
        if (
            type(self.generation_profile) is not str
            or type(self.output_profile) is not str
            or self.generation_profile
            not in {
                "preview",
                "production",
            }
            or self.output_profile
            not in {
                "xhs_grid",
                "talking_head_cover",
                "background_sequence",
            }
        ):
            raise DomainError("invalid generation selector")

    def _resolve_execution_parameters(
        self, graph: CompiledExecutionGraph
    ) -> GenerationParameters:
        defaults = GenerationParameters(
            graph.ip_adapter_scale,
            graph.img2img_strength,
            graph.controlnet_scale,
        )
        if self.execution_parameters is None:
            object.__setattr__(self, "execution_parameters", defaults)
            return defaults
        if type(self.execution_parameters) is not GenerationParameters:
            raise DomainError("invalid generation parameters")
        parameters = GenerationParameters(
            self.execution_parameters.ip_adapter_scale,
            self.execution_parameters.img2img_strength,
            self.execution_parameters.controlnet_scale,
        )
        if parameters != self.execution_parameters:
            raise DomainError("forged generation parameters")
        if self.parent_attempt_id is None and parameters != defaults:
            raise DomainError("generation parameter override requires parent attempt")
        object.__setattr__(self, "execution_parameters", parameters)
        return parameters

    def _resolve_graph(self) -> CompiledExecutionGraph:
        graphs = (
            self.compiled_spec.preview_graphs
            if self.generation_profile == "preview"
            else self.compiled_spec.production_graphs
        )
        matched = tuple(
            graph for graph in graphs if graph.output_profile == self.output_profile
        )
        if len(matched) != 1:
            raise DomainError("generation selectors must resolve exactly one graph")
        return matched[0]

    def _validate_materials(self, graph: CompiledExecutionGraph) -> None:
        prompt = RenderedPrompt(
            self.prompt.template_pin,
            self.prompt.preset_id,
            self.prompt.positive,
            self.prompt.negative,
        )
        if prompt != self.prompt:
            raise DomainError("forged rendered prompt")
        source = PreparedImage(
            self.source.source, self.source.content, self.source.snapshot
        )
        control_image = PreparedImage(
            self.control_input.image.source,
            self.control_input.image.content,
            self.control_input.image.snapshot,
        )
        if (
            type(self.style_references) is not tuple
            or not self.style_references
            or any(type(item) is not AssetRef for item in self.style_references)
        ):
            raise DomainError("style references must be a nonempty exact tuple")
        if (
            tuple(item.sha256 for item in self.style_references)
            != graph.style_reference_hashes
        ):
            raise DomainError("style references do not match graph")
        if (
            self.prompt.preset_id != graph.preset_id
            or self.control_input.kind != graph.controlnet.controlnet_type
        ):
            raise DomainError("request inputs do not match graph")
        if (
            source.width != graph.resolution[0]
            or source.height != graph.resolution[1]
            or control_image.width != graph.resolution[0]
            or control_image.height != graph.resolution[1]
            or control_image.source != source.source
        ):
            raise DomainError("request image dimensions or source do not match graph")
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "prompt", prompt)
        object.__setattr__(
            self,
            "control_input",
            PreparedControlInput(self.control_input.kind, control_image),
        )

    @property
    def graph(self) -> CompiledExecutionGraph:
        """The unique execution graph resolved by the request selectors."""
        return self._resolve_graph()

    def _fingerprint_materials(
        self, graph: CompiledExecutionGraph, seed: SeedSnapshot
    ) -> dict[str, object]:
        return {
            "compiled_spec_hash": _sha(self.compiled_spec.compiled_spec_hash),
            "generation_profile": self.generation_profile,
            "output_profile": self.output_profile,
            "source": _prepared(self.source),
            "style_references": [_asset(item) for item in self.style_references],
            "prompt": {
                "template_pin": _pin(self.prompt.template_pin),
                "preset_id": self.prompt.preset_id.value,
                "positive": self.prompt.positive,
                "negative": self.prompt.negative,
            },
            "control_kind": self.control_input.kind,
            "control_image": _prepared(self.control_input.image),
            "execution_parameters": {
                "ip_adapter_scale": self.execution_parameters.ip_adapter_scale,
                "img2img_strength": self.execution_parameters.img2img_strength,
                "controlnet_scale": self.execution_parameters.controlnet_scale,
            },
            "variation_index": self.variation_index,
            "seed": seed.seed,
        }
