from __future__ import annotations

from dataclasses import dataclass
import fcntl
import json
import os
import re
import stat
import threading
from types import TracebackType
from typing import Any, Literal
from urllib.parse import urlsplit

from specstyle.domain.artifacts import AssetRef
from specstyle.domain.identifiers import AssetId, Identifier, JobId, Sha256
from specstyle.errors import DomainError, InfrastructureError
from specstyle.exporting.manifest import AssetCredit
from specstyle.exporting.qa_report import canonical_json_bytes
from specstyle.generation.content_assets import (
    ContentAddressedStyleResolver,
    open_content_addressed_style_resolver,
)
from specstyle.generation.preprocess import PreprocessPlan, preprocess_image
from specstyle.generation.requests import RenderedPrompt
from specstyle.observability.hashing import hash_bytes
from specstyle.production.context_config import ProductionContextConfig, _CONFIG_SEAL
from specstyle.spec.compiled_models import ResourcePin
from specstyle.spec.loader import load_style_spec_text
from specstyle.workflow._production_input_cas import store_style as _store_style
from specstyle.workflow.production_service import ProductionJobRequest

__all__ = (
    "ProductionAssetProvenance",
    "ProductionJobInputMetadata",
    "ProductionJobSpecSummary",
    "load_production_job_input_metadata",
    "open_production_job_input",
    "validate_production_job_spec_text",
)

_METADATA_BYTES = 64 * 1024
_SOURCE_BYTES = 32 * 1024 * 1024
_STYLE_BYTES = 32 * 1024 * 1024
_SPEC_BYTES = 1024 * 1024
_READ_BYTES = 1024 * 1024
_METADATA_VERSION = "specstyle.production.job_input.v1"
_STRONG_SECRET_LABEL = (
    r"password|api[ _-]?key|access[ _-]?(?:key|token)|"
    r"client[ _-]?(?:key|secret)|private[ _-]?key|token|secret"
)
_AMBIGUOUS_SECRET_LABEL = r"credential|cookie|session|passwd"
_TOKEN_SHAPE = (
    r"(?:[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{4,}|"
    r"[A-Za-z0-9+/]{16,}={1,2}|[A-Za-z0-9_-]{32,})"
)
_SECRET = re.compile(
    r"(?:-----BEGIN [A-Z0-9 ]*(?:PRIVATE KEY|CERTIFICATE)-----|"
    r"(?<![A-Za-z0-9])authorization\s*(?:[:=]|\s)\s*\S+|"
    rf"(?<![A-Za-z0-9])(?:{_STRONG_SECRET_LABEL})"
    r"\s*(?:[:=]|\s)\s*\S+|"
    rf"(?<![A-Za-z0-9])(?:{_AMBIGUOUS_SECRET_LABEL})"
    rf"(?:\s*[:=]\s*\S+|\s+{_TOKEN_SHAPE})|"
    rf"(?<![A-Za-z0-9])(?:basic|bearer)\s+{_TOKEN_SHAPE})",
    re.IGNORECASE,
)
_SECRET_FIELD = re.compile(
    rf"(?:authorization|{_STRONG_SECRET_LABEL}|{_AMBIGUOUS_SECRET_LABEL})",
    re.IGNORECASE,
)
_PLAIN_PATH = re.compile(
    r"(?:^|[\s='\"(\[{,;])(?:~[/\\]|(?:[A-Za-z]:[\\/])|"
    r"\\\\[^\\\s]+\\|//[^/\s]+/|/(?!/)|\.\.[/\\])"
)
_COLON_PATH = re.compile(
    r":\s*(?:~[/\\]|[A-Za-z]:[\\/]|\\\\[^\\\s]+\\|"
    r"//[^/\s]+/|/(?!/)|\.\.[/\\])"
)
_WEB_SCHEME = re.compile(r"(?<![A-Za-z0-9])https?$", re.IGNORECASE)
_TRAVERSAL = re.compile(r"(?:^|[/\\])\.\.(?:[/\\]|$)")
_URL_TOKEN = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_BUNDLE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", re.ASCII)


@dataclass(frozen=True, slots=True)
class ProductionAssetProvenance:
    source_url: str | None
    license: str | None
    attribution: str | None
    consent: Literal["not_applicable", "obtained"] | None

    def __post_init__(self) -> None:
        source_url = _safe_text(self.source_url)
        license_ = _safe_text(self.license)
        attribution = _safe_text(self.attribution)
        if source_url is not None:
            _safe_url(source_url)
        if self.consent is not None and self.consent not in (
            "not_applicable",
            "obtained",
        ):
            raise _domain()
        _assert_no_secret((source_url, license_, attribution))
        _assert_plain((source_url, license_, attribution, self.consent))
        object.__setattr__(self, "source_url", source_url)
        object.__setattr__(self, "license", license_)
        object.__setattr__(self, "attribution", attribution)


@dataclass(frozen=True, slots=True)
class ProductionJobInputMetadata:
    source_asset_id: AssetId
    style_asset_id: AssetId
    prompt: RenderedPrompt
    source_provenance: ProductionAssetProvenance

    def __post_init__(self) -> None:
        if (
            type(self.source_asset_id) is not AssetId
            or type(self.style_asset_id) is not AssetId
            or type(self.prompt) is not RenderedPrompt
            or type(self.source_provenance) is not ProductionAssetProvenance
            or self.source_asset_id == self.style_asset_id
        ):
            raise _domain()
        object.__setattr__(self, "source_asset_id", AssetId(self.source_asset_id.value))
        object.__setattr__(self, "style_asset_id", AssetId(self.style_asset_id.value))
        object.__setattr__(
            self,
            "prompt",
            RenderedPrompt(
                self.prompt.template_pin,
                self.prompt.preset_id,
                self.prompt.positive,
                self.prompt.negative,
            ),
        )
        prompt_strings = _prompt_strings(self.prompt)
        _assert_no_secret(prompt_strings)
        _assert_plain(prompt_strings)
        object.__setattr__(
            self,
            "source_provenance",
            ProductionAssetProvenance(
                self.source_provenance.source_url,
                self.source_provenance.license,
                self.source_provenance.attribution,
                self.source_provenance.consent,
            ),
        )


@dataclass(frozen=True, slots=True)
class ProductionJobSpecSummary:
    preset_id: str
    max_rounds: int

    def __post_init__(self) -> None:
        if (
            type(self.preset_id) is not str
            or not self.preset_id
            or type(self.max_rounds) is not int
            or not 1 <= self.max_rounds <= 10
        ):
            raise _domain()


def _prompt_strings(prompt: RenderedPrompt) -> tuple[str, ...]:
    return (
        prompt.template_pin.id,
        prompt.template_pin.revision,
        prompt.template_pin.sha256.value,
        prompt.preset_id.value,
        prompt.positive,
        prompt.negative,
    )


def _domain() -> DomainError: return DomainError("invalid production job input")  # fmt: skip


def _infra() -> InfrastructureError: return InfrastructureError("production job input unavailable")  # fmt: skip


def _dup(fd: object) -> int:
    if type(fd) is not int or fd < 0:
        raise _domain()
    try:
        return fcntl.fcntl(fd, fcntl.F_DUPFD_CLOEXEC, 0)
    except (OSError, OverflowError):
        raise _infra() from None


# fmt: off
def _snapshot(value: os.stat_result) -> tuple[int, ...]:
    return (value.st_dev, value.st_ino, value.st_mode, value.st_nlink, value.st_uid, value.st_gid, value.st_size, value.st_mtime_ns, value.st_ctime_ns)
# fmt: on


def _read_regular(fd: int, limit: int) -> bytes:
    try:
        before = os.fstat(fd)
        mode = stat.S_IMODE(before.st_mode)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.geteuid()
            or before.st_nlink != 1
            or mode not in (0o400, 0o600)
            or not 1 <= before.st_size <= limit
        ):
            raise _domain()
        offset, remaining, parts = 0, before.st_size, []
        while remaining:
            part = os.pread(fd, min(remaining, _READ_BYTES), offset)
            if not part or len(part) > remaining:
                raise _infra()
            parts.append(part)
            remaining -= len(part)
            offset += len(part)
        if os.pread(fd, 1, offset) or _snapshot(before) != _snapshot(os.fstat(fd)):
            raise _infra()
        return b"".join(parts)
    except (DomainError, InfrastructureError):
        raise
    except OSError:
        raise _infra() from None


def _close(fd: int, primary: BaseException | None = None) -> None:
    try:
        os.close(fd)
    except OSError:
        if primary is not None:
            primary.add_note("production job input cleanup failed")
        else:
            raise _infra() from None


def _read_borrowed(fd: object, limit: int) -> bytes:
    duplicate = _dup(fd)
    try:
        content = _read_regular(duplicate, limit)
    except BaseException as error:
        _close(duplicate, error)
        raise
    _close(duplicate)
    return content


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if type(key) is not str or key in result:
            raise _domain()
        result[key] = value
    return result


def _strict_json(data: bytes) -> dict[str, Any]:
    try:
        decoded = data.decode("utf-8")
        value = json.loads(decoded, object_pairs_hook=_pairs, parse_constant=_pairs)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        raise _domain() from None
    if type(value) is not dict:
        raise _domain()
    return value


def _exact(value: object, keys: set[str]) -> dict[str, Any]:
    if type(value) is not dict or set(value) != keys:
        raise _domain()
    return value


def _safe_text(value: object, *, empty: bool = False) -> str | None:
    if value is None:
        return None
    if type(value) is not str or (not empty and not value):
        raise _domain()
    if (
        len(value) > 2048
        or value != value.strip()
        or any(ord(c) < 32 or ord(c) == 127 for c in value)
    ):
        raise _domain()
    return str(value)


def _provenance(value: object) -> ProductionAssetProvenance:
    raw = _exact(value, {"source_url", "license", "attribution", "consent"})
    source_url = _safe_text(raw["source_url"])
    if source_url is not None:
        _safe_url(source_url)
    consent = raw["consent"]
    if consent is not None and consent not in ("not_applicable", "obtained"):
        raise _domain()
    return ProductionAssetProvenance(
        source_url, _safe_text(raw["license"]), _safe_text(raw["attribution"]), consent
    )


def _metadata(data: bytes) -> ProductionJobInputMetadata:
    raw = _exact(_strict_json(data), {"schema_version", "source", "style", "prompt"})
    if raw["schema_version"] != _METADATA_VERSION:
        raise _domain()
    source = _exact(raw["source"], {"asset_id", "credit"})
    style = _exact(raw["style"], {"asset_id"})
    prompt = _exact(
        raw["prompt"], {"template_pin", "preset_id", "positive", "negative"}
    )
    pin = _exact(prompt["template_pin"], {"id", "revision", "sha256"})
    try:
        issued = RenderedPrompt(
            ResourcePin(pin["id"], pin["revision"], Sha256(pin["sha256"])),
            Identifier(prompt["preset_id"]),
            _safe_text(prompt["positive"]) or "",
            _safe_text(prompt["negative"], empty=True) or "",
        )
        source_id, style_id = AssetId(source["asset_id"]), AssetId(style["asset_id"])
    except (DomainError, TypeError, ValueError):
        raise _domain() from None
    if source_id == style_id:
        raise _domain()
    return ProductionJobInputMetadata(
        source_id, style_id, issued, _provenance(source["credit"])
    )


def load_production_job_input_metadata(
    metadata_fd: int, /
) -> ProductionJobInputMetadata:
    try:
        return _metadata(_read_borrowed(metadata_fd, _METADATA_BYTES))
    except (DomainError, InfrastructureError):
        raise
    except Exception:
        raise _domain() from None


def _safe_url(value: str) -> None:
    try:
        parts = urlsplit(value)
        invalid = (
            parts.scheme not in ("http", "https")
            or not parts.hostname
            or parts.username is not None
            or parts.password is not None
            or bool(parts.query or parts.fragment)
            or any(character.isspace() for character in value)
        )
        _ = parts.port
    except ValueError:
        raise _domain() from None
    if invalid:
        raise _domain()


def _assert_no_secret(value: object) -> None:
    if type(value) is str:
        if _SECRET.search(value) is not None or value.lower().startswith("file:"):
            raise _domain()
    elif type(value) is dict:
        for key, item in value.items():
            if type(key) is not str or _SECRET_FIELD.fullmatch(key) is not None:
                raise _domain()
            _assert_no_secret(key)
            _assert_no_secret(item)
    elif type(value) in (list, tuple):
        for item in value:
            _assert_no_secret(item)
    elif value is not None and type(value) not in (bool, int, float):
        raise _domain()


def _has_colon_path(value: str) -> bool:
    for match in _COLON_PATH.finditer(value):
        prefix = value[: match.start()]
        if match.group(0).startswith("://") and _WEB_SCHEME.search(prefix):
            continue
        return True
    return False


def _assert_plain(value: object) -> None:
    if type(value) is str:
        if (
            _PLAIN_PATH.search(value)
            or _has_colon_path(value)
            or _TRAVERSAL.search(value)
        ):
            raise _domain()
        for match in _URL_TOKEN.finditer(value):
            _safe_url(match.group(0))
    elif type(value) is dict:
        for key, item in value.items():
            _assert_plain(key)
            _assert_plain(item)
    elif type(value) in (list, tuple):
        for item in value:
            _assert_plain(item)
    elif value is not None and type(value) not in (bool, int, float):
        raise _domain()


def _validate_spec(raw: object) -> tuple[object, str, tuple[int, int]]:
    if (
        len(raw.outputs.profiles) != 1
        or len(raw.assets.style_references) != 1
        or raw.repair.policy_version != "1.0"
        or raw.repair.max_rounds != 1
        or raw.repair.stop_after_no_improvement != 1
        or raw.generation.batch_execution != "sequential"
        or raw.verification.l3 is not None
        or raw.domain.profile != "product_instance"
    ):
        raise _domain()
    primitive = raw.model_dump(mode="json", round_trip=True)
    _assert_no_secret(primitive)
    _assert_plain(primitive)
    for style in raw.assets.style_references:
        _safe_url(style.source_url)
        _assert_plain((style.license, style.attribution))
    resolution = tuple(raw.profiles.production.resolution)
    if len(resolution) != 2 or any(type(item) is not int for item in resolution):
        raise _domain()
    return raw, canonical_json_bytes(primitive).decode("utf-8"), resolution


def validate_production_job_spec_text(text: str, /) -> ProductionJobSpecSummary:
    try:
        if type(text) is not str:
            raise _domain()
        raw, _canonical, _resolution = _validate_spec(load_style_spec_text(text))
        return ProductionJobSpecSummary(raw.style.preset_id, raw.repair.max_rounds)
    except DomainError:
        raise _domain() from None
    except Exception:
        raise _domain() from None


def _preprocess(
    content: bytes, asset: AssetRef, raw: object, config: ProductionContextConfig
):
    source = config.source_preprocess
    plan = PreprocessPlan(
        tuple(raw.profiles.production.resolution),
        source.resize_mode,
        tuple(source.background),
        source.processor_pin,
    )
    try:
        return preprocess_image(content, asset, plan)
    except DomainError:
        raise _domain() from None
    except InfrastructureError:
        raise _infra() from None


def _credits(
    source: AssetRef, style: AssetRef, metadata: ProductionJobInputMetadata, raw: object
) -> tuple[AssetCredit, ...]:
    provenance = metadata.source_provenance
    style_info = raw.assets.style_references[0]
    values = (
        AssetCredit(
            source,
            ("input",),
            provenance.source_url,
            provenance.license,
            provenance.attribution,
            provenance.consent,
        ),
        AssetCredit(
            style,
            ("style_reference",),
            style_info.source_url,
            style_info.license,
            style_info.attribution,
            style_info.consent,
        ),
    )
    return tuple(
        sorted(
            values,
            key=lambda item: (item.asset.asset_id.value, item.asset.sha256.value),
        )
    )


# fmt: off
class ProductionJobInput:
    __slots__ = ("_asset_credits", "_closed", "_lock", "_request", "_style_assets")
    def __init__(self, *_: object) -> None:
        raise TypeError("production job inputs are issued only by the loader")
    @property
    def request(self) -> ProductionJobRequest:
        return self._request
    @property
    def asset_credits(self) -> tuple[AssetCredit, ...]:
        return self._asset_credits
    @property
    def style_assets(self) -> ContentAddressedStyleResolver:
        return self._style_assets
    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            resolver = self._style_assets
        try:
            resolver.close()
        except Exception:
            raise _infra() from None
    def __enter__(self) -> ProductionJobInput:
        with self._lock:
            if self._closed:
                raise _infra()
        return self
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
        /,
    ) -> None:
        try:
            self.close()
        except InfrastructureError:
            if exc is None:
                raise
            exc.add_note("production job input cleanup failed")
    def __copy__(self) -> ProductionJobInput:
        raise TypeError("production job inputs cannot be copied")
    def __deepcopy__(self, _memo: dict[int, object]) -> ProductionJobInput:
        raise TypeError("production job inputs cannot be copied")
    def __reduce_ex__(self, _protocol: int) -> object:
        raise TypeError("production job inputs cannot be serialized")
# fmt: on


def _issue(
    request: ProductionJobRequest,
    credits: tuple[AssetCredit, ...],
    resolver: ContentAddressedStyleResolver,
) -> ProductionJobInput:
    issued = object.__new__(ProductionJobInput)
    issued._request, issued._asset_credits, issued._style_assets = (
        request,
        credits,
        resolver,
    )
    issued._lock, issued._closed = threading.Lock(), False
    return issued


def _metadata_primitives(metadata: ProductionJobInputMetadata) -> dict[str, object]:
    try:
        prompt = metadata.prompt
        provenance = metadata.source_provenance
        return {
            "source_asset_id": metadata.source_asset_id.value,
            "style_asset_id": metadata.style_asset_id.value,
            "prompt": {
                "template_pin": {
                    "id": prompt.template_pin.id,
                    "revision": prompt.template_pin.revision,
                    "sha256": prompt.template_pin.sha256.value,
                },
                "preset_id": prompt.preset_id.value,
                "positive": prompt.positive,
                "negative": prompt.negative,
            },
            "source_provenance": {
                "source_url": provenance.source_url,
                "license": provenance.license,
                "attribution": provenance.attribution,
                "consent": provenance.consent,
            },
        }
    except (AttributeError, TypeError):
        raise _domain() from None


def _validate_metadata_strings(metadata: ProductionJobInputMetadata) -> None:
    primitive = _metadata_primitives(metadata)
    _assert_no_secret(primitive)
    _assert_plain(primitive)
    source_url = primitive["source_provenance"]["source_url"]
    if source_url is not None:
        if type(source_url) is not str:
            raise _domain()
        _safe_url(source_url)


def _validate_open_inputs(
    metadata: object,
    context_config: object,
    job_id: object,
    bundle_name: object,
    variation_index: object,
) -> tuple[ProductionJobInputMetadata, ProductionContextConfig, JobId, str, int]:
    if (
        type(metadata) is not ProductionJobInputMetadata
        or type(context_config) is not ProductionContextConfig
        or getattr(context_config, "_seal", None) is not _CONFIG_SEAL
        or type(job_id) is not JobId
        or type(bundle_name) is not str
        or type(variation_index) is not int
        or not 0 <= variation_index < 2**31
    ):
        raise _domain()
    _validate_metadata_strings(metadata)
    _assert_no_secret(bundle_name)
    _assert_plain(bundle_name)
    if _BUNDLE.fullmatch(bundle_name) is None:
        raise _domain()
    return metadata, context_config, job_id, bundle_name, variation_index


def _load_materials(
    source_fd: int,
    style_fd: int,
    spec_fd: int,
    metadata: ProductionJobInputMetadata,
    config: ProductionContextConfig,
) -> tuple[object, str, tuple[int, int], AssetRef, object, AssetRef, bytes]:
    try:
        source_data = _read_borrowed(source_fd, _SOURCE_BYTES)
        style_data = _read_borrowed(style_fd, _STYLE_BYTES)
        raw, spec_text, resolution = _validate_spec(
            load_style_spec_text(_read_borrowed(spec_fd, _SPEC_BYTES))
        )
        if metadata.prompt.preset_id.value != raw.style.preset_id:
            raise _domain()
        source_ref = AssetRef(metadata.source_asset_id, hash_bytes(source_data))
        source = _preprocess(source_data, source_ref, raw, config)
        style = _preprocess(
            style_data,
            AssetRef(metadata.style_asset_id, hash_bytes(style_data)),
            raw,
            config,
        )
        style_ref = AssetRef(metadata.style_asset_id, hash_bytes(style.content))
        if style_ref.sha256.value != raw.assets.style_references[0].asset_sha256:
            raise _domain()
        return raw, spec_text, resolution, source_ref, source, style_ref, style.content
    except DomainError:
        raise _domain() from None


def open_production_job_input(
    source_fd: int,
    style_fd: int,
    spec_fd: int,
    style_asset_root_fd: int,
    metadata: ProductionJobInputMetadata,
    context_config: ProductionContextConfig,
    job_id: JobId,
    bundle_name: str,
    /,
    *,
    variation_index: int = 0,
) -> ProductionJobInput:
    resolver: ContentAddressedStyleResolver | None = None
    try:
        metadata, context_config, job_id, bundle_name, variation_index = (
            _validate_open_inputs(
                metadata, context_config, job_id, bundle_name, variation_index
            )
        )
        raw, spec_text, resolution, source_ref, source, style_ref, style_content = (
            _load_materials(source_fd, style_fd, spec_fd, metadata, context_config)
        )
        output_profile = raw.outputs.profiles[0]
        if output_profile not in tuple(
            item.profile for item in context_config.output_profiles
        ):
            raise _domain()
        _store_style(
            style_asset_root_fd, style_ref.sha256.value, style_content, resolution
        )
        resolver = open_content_addressed_style_resolver(
            style_asset_root_fd, (style_ref,), resolution
        )
        request = ProductionJobRequest(
            job_id,
            spec_text,
            source,
            (style_ref,),
            metadata.prompt,
            output_profile,
            variation_index,
            bundle_name,
        )
        return _issue(request, _credits(source_ref, style_ref, metadata, raw), resolver)
    except (DomainError, InfrastructureError) as error:
        _close_resolver(resolver, error)
        raise
    except Exception as error:
        _close_resolver(resolver, error)
        raise _infra() from None


def _close_resolver(
    resolver: ContentAddressedStyleResolver | None, primary: BaseException
) -> None:
    if resolver is None:
        return
    try:
        resolver.close()
    except Exception:
        primary.add_note("production job input cleanup failed")
