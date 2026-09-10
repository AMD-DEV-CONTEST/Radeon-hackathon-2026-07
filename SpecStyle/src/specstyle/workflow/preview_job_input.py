"""Independent, descriptor-rooted input contract for one Preview generation."""

from __future__ import annotations

from dataclasses import dataclass
import math
import threading
from types import TracebackType

from specstyle.domain.artifacts import AssetRef
from specstyle.domain.identifiers import AssetId, Identifier, Sha256
from specstyle.errors import DomainError, InfrastructureError
from specstyle.exporting.qa_report import canonical_json_bytes
from specstyle.generation.content_assets import (
    ContentAddressedStyleResolver,
    open_content_addressed_style_resolver,
)
from specstyle.generation.preprocess import (
    PreprocessPlan,
    PreparedImage,
    preprocess_image,
)
from specstyle.generation.requests import RenderedPrompt
from specstyle.observability.hashing import hash_bytes
from specstyle.production.context_config import ProductionContextConfig, _CONFIG_SEAL
from specstyle.spec.compiled_models import ResourcePin
from specstyle.spec.loader import load_style_spec_text
from specstyle.workflow._production_input_cas import store_style as _store_style
from specstyle.workflow.production_job_input import (
    _assert_no_secret,
    _assert_plain,
    _exact,
    _read_borrowed,
    _safe_url,
    _strict_json,
)

__all__ = (
    "PreviewJobInput",
    "PreviewJobInputMetadata",
    "load_preview_job_input_metadata",
    "open_preview_job_input",
)

_METADATA_BYTES = 64 * 1024
_SOURCE_BYTES = 32 * 1024 * 1024
_STYLE_BYTES = 32 * 1024 * 1024
_SPEC_BYTES = 1024 * 1024


def _domain() -> DomainError:
    return DomainError("invalid preview job input")


def _infra() -> InfrastructureError:
    return InfrastructureError("preview job input unavailable")


@dataclass(frozen=True, slots=True)
class PreviewJobInputMetadata:
    source_asset_id: AssetId
    style_asset_id: AssetId
    prompt: RenderedPrompt

    def __post_init__(self) -> None:
        if (
            type(self.source_asset_id) is not AssetId
            or type(self.style_asset_id) is not AssetId
            or self.source_asset_id == self.style_asset_id
            or type(self.prompt) is not RenderedPrompt
        ):
            raise _domain()
        rebuilt = RenderedPrompt(
            self.prompt.template_pin,
            self.prompt.preset_id,
            self.prompt.positive,
            self.prompt.negative,
        )
        _assert_no_secret(_prompt_primitive(rebuilt))
        _assert_plain(_prompt_primitive(rebuilt))
        object.__setattr__(self, "source_asset_id", AssetId(self.source_asset_id.value))
        object.__setattr__(self, "style_asset_id", AssetId(self.style_asset_id.value))
        object.__setattr__(self, "prompt", rebuilt)


def _prompt_primitive(prompt: RenderedPrompt) -> dict[str, object]:
    return {
        "template_pin": {
            "id": prompt.template_pin.id,
            "revision": prompt.template_pin.revision,
            "sha256": prompt.template_pin.sha256.value,
        },
        "preset_id": prompt.preset_id.value,
        "positive": prompt.positive,
        "negative": prompt.negative,
    }


def load_preview_job_input_metadata(metadata_fd: int, /) -> PreviewJobInputMetadata:
    try:
        raw = _strict_json(_read_borrowed(metadata_fd, _METADATA_BYTES))
        outer = _exact(raw, {"schema_version", "source", "style", "prompt"})
        if outer["schema_version"] != "specstyle.preview.job_input.v1":
            raise _domain()
        source = _exact(outer["source"], {"asset_id"})
        style = _exact(outer["style"], {"asset_id"})
        prompt = _exact(
            outer["prompt"],
            {"template_pin", "preset_id", "positive", "negative"},
        )
        pin = _exact(prompt["template_pin"], {"id", "revision", "sha256"})
        return PreviewJobInputMetadata(
            AssetId(source["asset_id"]),
            AssetId(style["asset_id"]),
            RenderedPrompt(
                ResourcePin(pin["id"], pin["revision"], Sha256(pin["sha256"])),
                Identifier(prompt["preset_id"]),
                prompt["positive"],
                prompt["negative"],
            ),
        )
    except DomainError:
        raise _domain() from None
    except Exception:
        raise _infra() from None


def _positive_zero(value: object) -> bool:
    return type(value) is float and value == 0.0 and math.copysign(1.0, value) == 1.0


def _validated_spec(data: bytes) -> tuple[object, str, tuple[int, int], str]:
    try:
        raw = load_style_spec_text(data)
        preview = raw.profiles.preview
        if (
            len(raw.outputs.profiles) != 1
            or len(raw.assets.style_references) != 1
            or raw.repair.policy_version != "1.0"
            or raw.repair.max_rounds != 1
            or raw.repair.stop_after_no_improvement != 1
            or raw.generation.batch_execution != "sequential"
            or raw.verification.l3 is not None
            or raw.domain.profile != "product_instance"
            or preview.pipeline != "lcm"
            or type(preview.steps) is not int
            or not 4 <= preview.steps <= 8
            or not _positive_zero(preview.guidance_scale)
        ):
            raise _domain()
        primitive = raw.model_dump(mode="json", round_trip=True)
        _assert_no_secret(primitive)
        _assert_plain(primitive)
        style = raw.assets.style_references[0]
        _safe_url(style.source_url)
        resolution = tuple(preview.resolution)
        if len(resolution) != 2 or any(type(item) is not int for item in resolution):
            raise _domain()
        return (
            raw,
            canonical_json_bytes(primitive).decode("utf-8"),
            resolution,
            raw.outputs.profiles[0],
        )
    except DomainError:
        raise _domain() from None


def _prepare(
    content: bytes,
    asset: AssetRef,
    resolution: tuple[int, int],
    config: ProductionContextConfig,
) -> PreparedImage:
    source = config.source_preprocess
    try:
        return preprocess_image(
            content,
            asset,
            PreprocessPlan(
                resolution,
                source.resize_mode,
                tuple(source.background),
                source.processor_pin,
            ),
        )
    except DomainError:
        raise _domain() from None
    except InfrastructureError:
        raise _infra() from None


class PreviewJobInput:
    __slots__ = (
        "_closed",
        "_lock",
        "_output_profile",
        "_prompt",
        "_source",
        "_spec_text",
        "_style_assets",
        "_style_references",
        "_variation_index",
    )

    def __init__(self, *_: object, **__: object) -> None:
        raise TypeError("preview job inputs are issued only by the loader")

    @property
    def spec_text(self) -> str:
        return self._spec_text

    @property
    def source(self) -> PreparedImage:
        return self._source

    @property
    def style_references(self) -> tuple[AssetRef, ...]:
        return self._style_references

    @property
    def prompt(self) -> RenderedPrompt:
        return self._prompt

    @property
    def output_profile(self) -> str:
        return self._output_profile

    @property
    def variation_index(self) -> int:
        return self._variation_index

    @property
    def style_assets(self) -> ContentAddressedStyleResolver:
        return self._style_assets

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        try:
            self._style_assets.close()
        except Exception:
            raise _infra() from None

    def __enter__(self) -> PreviewJobInput:
        with self._lock:
            if self._closed:
                raise _infra()
        return self

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        exc: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        try:
            self.close()
        except InfrastructureError:
            if exc is None:
                raise
            exc.add_note("preview job input cleanup failed")

    def __copy__(self) -> PreviewJobInput:
        raise TypeError("preview job inputs cannot be copied")

    def __deepcopy__(self, _memo: dict[int, object]) -> PreviewJobInput:
        raise TypeError("preview job inputs cannot be copied")

    def __reduce_ex__(self, _protocol: int) -> object:
        raise TypeError("preview job inputs cannot be serialized")


def _issue_input(
    spec_text: str,
    source: PreparedImage,
    style_reference: AssetRef,
    prompt: RenderedPrompt,
    output_profile: str,
    variation_index: int,
    resolver: ContentAddressedStyleResolver,
) -> PreviewJobInput:
    issued = object.__new__(PreviewJobInput)
    issued._spec_text = spec_text
    issued._source = source
    issued._style_references = (style_reference,)
    issued._prompt = prompt
    issued._output_profile = output_profile
    issued._variation_index = variation_index
    issued._style_assets = resolver
    issued._closed = False
    issued._lock = threading.Lock()
    return issued


def _validate_open(
    metadata: object, config: object, variation_index: object
) -> tuple[PreviewJobInputMetadata, ProductionContextConfig, int]:
    if (
        type(metadata) is not PreviewJobInputMetadata
        or type(config) is not ProductionContextConfig
        or getattr(config, "_seal", None) is not _CONFIG_SEAL
        or type(variation_index) is not int
        or not 0 <= variation_index < 2**31
    ):
        raise _domain()
    return metadata, config, variation_index


def _profile_matches(
    raw: object,
    metadata: PreviewJobInputMetadata,
    output_profile: str,
    context_config: ProductionContextConfig,
) -> bool:
    supported = tuple(
        item.profile
        for item in context_config.output_profiles
        if "preview" in item.supported_generation_profiles
    )
    return metadata.prompt.preset_id.value == raw.style.preset_id and (
        output_profile in supported
    )


def _prepare_materials(
    source_data: bytes,
    style_data: bytes,
    raw: object,
    resolution: tuple[int, int],
    metadata: PreviewJobInputMetadata,
    context_config: ProductionContextConfig,
    style_asset_root_fd: int,
) -> tuple[PreparedImage, AssetRef, ContentAddressedStyleResolver]:
    source_ref = AssetRef(metadata.source_asset_id, hash_bytes(source_data))
    source = _prepare(source_data, source_ref, resolution, context_config)
    style = _prepare(
        style_data,
        AssetRef(metadata.style_asset_id, hash_bytes(style_data)),
        resolution,
        context_config,
    )
    style_ref = AssetRef(metadata.style_asset_id, hash_bytes(style.content))
    if style_ref.sha256.value != raw.assets.style_references[0].asset_sha256:
        raise _domain()
    _store_style(style_asset_root_fd, style_ref.sha256.value, style.content, resolution)
    resolver = open_content_addressed_style_resolver(
        style_asset_root_fd, (style_ref,), resolution
    )
    return source, style_ref, resolver


def _close_failed_resolver(
    resolver: ContentAddressedStyleResolver | None, error: BaseException
) -> None:
    if resolver is None:
        return
    try:
        resolver.close()
    except Exception:
        error.add_note("preview job input cleanup failed")


def open_preview_job_input(
    source_fd: int,
    style_fd: int,
    spec_fd: int,
    style_asset_root_fd: int,
    metadata: PreviewJobInputMetadata,
    context_config: ProductionContextConfig,
    variation_index: int,
    /,
) -> PreviewJobInput:
    resolver: ContentAddressedStyleResolver | None = None
    try:
        metadata, context_config, variation_index = _validate_open(
            metadata, context_config, variation_index
        )
        source_data = _read_borrowed(source_fd, _SOURCE_BYTES)
        style_data = _read_borrowed(style_fd, _STYLE_BYTES)
        raw, spec_text, resolution, output_profile = _validated_spec(
            _read_borrowed(spec_fd, _SPEC_BYTES)
        )
        if not _profile_matches(raw, metadata, output_profile, context_config):
            raise _domain()
        source, style_ref, resolver = _prepare_materials(
            source_data,
            style_data,
            raw,
            resolution,
            metadata,
            context_config,
            style_asset_root_fd,
        )
        return _issue_input(
            spec_text,
            source,
            style_ref,
            metadata.prompt,
            output_profile,
            variation_index,
            resolver,
        )
    except (DomainError, InfrastructureError) as error:
        _close_failed_resolver(resolver, error)
        raise
    except Exception as error:
        _close_failed_resolver(resolver, error)
        raise _infra() from error
