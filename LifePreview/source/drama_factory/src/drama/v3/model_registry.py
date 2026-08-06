from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Literal
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_core import to_jsonable_python
from shared_contracts import (
    FallbackChange,
    FallbackPolicySnapshot,
    GenerationMode,
    GenerationRequest,
    ModelCapability,
    ModelInstallStatus,
    ModelRegistryEntry,
    ModelSourceType,
    ModelVerificationStatus,
    VideoResolution,
    stable_json_sha256,
)

from ..runtime import atomic_write_json


_REGISTRY_NAMESPACE = UUID("a262e5ff-3875-5f34-9df4-b629543a7ccc")
_CAPABILITY_NAMESPACE = UUID("4169d554-6edc-587a-850f-a2dc250e953a")
_COMFY_REVISION = "fb1388adc906ab39ffc26ee40e96b22886b56bc4"
_COMFY_SOURCE = "https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged"


class ModelSelectionBlocked(RuntimeError):
    pass


class ModelManifestError(RuntimeError):
    pass


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ModelBundleAsset(_FrozenModel):
    relative_path: str = Field(min_length=1, max_length=1000)
    bytes: int = Field(gt=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_url: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def path_is_relative_and_normalized(self):
        path = PurePosixPath(self.relative_path.replace("\\", "/"))
        if (
            path.is_absolute()
            or ".." in path.parts
            or any(part in {"", "."} for part in path.parts)
            or path.as_posix() != self.relative_path
        ):
            raise ValueError("model bundle asset path is unsafe")
        return self


class ModelBundleManifest(_FrozenModel):
    model_id: str = Field(min_length=1, max_length=100)
    source_revision: str = Field(min_length=7, max_length=100)
    license_name: str = Field(min_length=1, max_length=100)
    model_root: str = Field(min_length=1, max_length=2000)
    assets: tuple[ModelBundleAsset, ...] = Field(min_length=1)
    verification_status: ModelVerificationStatus
    hash_verified_at: datetime | None = None
    load_verified_at: datetime | None = None
    load_verified_workflow_ids: tuple[str, ...] = ()
    bundle_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_manifest(self):
        paths = [item.relative_path for item in self.assets]
        if len(paths) != len(set(paths)):
            raise ValueError("model bundle asset paths must be unique")
        if self.verification_status in {
            ModelVerificationStatus.HASH_VERIFIED,
            ModelVerificationStatus.LOAD_VERIFIED,
        } and self.hash_verified_at is None:
            raise ValueError("verified model bundle requires hash verification time")
        if self.verification_status is ModelVerificationStatus.LOAD_VERIFIED and (
            self.load_verified_at is None
            or not self.load_verified_workflow_ids
        ):
            raise ValueError(
                "load-verified bundle requires workflow evidence and time"
            )
        identity = self.model_dump(mode="json", exclude={"bundle_sha256"})
        if self.bundle_sha256 != stable_json_sha256(identity):
            raise ValueError("model bundle hash does not match content")
        return self


class ModelRegistryManifest(_FrozenModel):
    schema_version: Literal["factory.model-registry.v1"] = (
        "factory.model-registry.v1"
    )
    bundles: tuple[ModelBundleManifest, ...]
    updated_at: datetime
    registry_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_registry_manifest(self):
        model_ids = [item.model_id for item in self.bundles]
        if len(model_ids) != len(set(model_ids)):
            raise ValueError("model manifest ids must be unique")
        identity = self.model_dump(mode="json", exclude={"registry_sha256"})
        if self.registry_sha256 != stable_json_sha256(identity):
            raise ValueError("model registry manifest hash does not match content")
        return self


def _with_bundle_hash(payload: dict) -> ModelBundleManifest:
    payload = dict(payload)
    payload.pop("bundle_sha256", None)
    identity = to_jsonable_python(payload)
    return ModelBundleManifest(
        **payload,
        bundle_sha256=stable_json_sha256(identity),
    )


def _with_registry_hash(payload: dict) -> ModelRegistryManifest:
    payload = dict(payload)
    payload.pop("registry_sha256", None)
    draft = ModelRegistryManifest.model_construct(
        **payload,
        registry_sha256="0" * 64,
    )
    identity = draft.model_dump(mode="json", exclude={"registry_sha256"})
    return ModelRegistryManifest(
        **payload,
        registry_sha256=stable_json_sha256(identity),
    )


def _hashed_capability(payload: dict) -> ModelCapability:
    identity = ModelCapability.model_construct(
        snapshot_sha256="0" * 64,
        **payload,
    ).model_dump(mode="json", exclude={"snapshot_sha256"})
    return ModelCapability(
        **identity,
        snapshot_sha256=stable_json_sha256(identity),
    )


def _hashed_entry(payload: dict) -> ModelRegistryEntry:
    identity = ModelRegistryEntry.model_construct(
        snapshot_sha256="0" * 64,
        **payload,
    ).model_dump(mode="json", exclude={"snapshot_sha256"})
    return ModelRegistryEntry(
        **identity,
        snapshot_sha256=stable_json_sha256(identity),
    )


@dataclass(frozen=True, slots=True)
class RegisteredModel:
    entry: ModelRegistryEntry
    capabilities: tuple[ModelCapability, ...]


@dataclass(frozen=True, slots=True)
class ModelSelection:
    entry: ModelRegistryEntry
    capability: ModelCapability
    fallback_from_model_id: str | None
    changed: tuple[FallbackChange, ...]


class LocalModelRegistry:
    def __init__(self, models: tuple[RegisteredModel, ...]) -> None:
        ids = [model.entry.model_id for model in models]
        if len(ids) != len(set(ids)):
            raise ValueError("model registry ids must be unique")
        self._models = {model.entry.model_id: model for model in models}
        for model in models:
            expected = set(model.entry.capability_ids)
            actual = {item.capability_id for item in model.capabilities}
            if expected != actual:
                raise ValueError("registry entry capability ids do not match")

    def list_models(self) -> tuple[RegisteredModel, ...]:
        return tuple(self._models.values())

    def capability(
        self,
        *,
        model_id: str,
        mode: GenerationMode,
    ) -> ModelCapability:
        model = self._models.get(model_id)
        if model is None:
            raise ModelSelectionBlocked("requested model is not registered")
        for capability in model.capabilities:
            if capability.operation is mode:
                return capability
        raise ModelSelectionBlocked("requested model does not support operation")

    @staticmethod
    def _usable(
        model: RegisteredModel,
        request: GenerationRequest,
        available_vram_mib: int,
    ) -> ModelCapability | None:
        if (
            model.entry.install_status is not ModelInstallStatus.INSTALLED
            or model.entry.verification_status
            is not ModelVerificationStatus.LOAD_VERIFIED
        ):
            return None
        for capability in model.capabilities:
            if (
                capability.operation is request.mode
                and capability.verified
                and request.resolution in capability.supported_resolutions
                and request.duration_seconds
                in capability.supported_durations_seconds
                and capability.estimated_vram_mib <= available_vram_mib
            ):
                return capability
        return None

    def select(
        self,
        request: GenerationRequest,
        *,
        fallback_policy: FallbackPolicySnapshot,
        available_vram_mib: int,
    ) -> ModelSelection:
        primary = self._models.get(request.model_id)
        if primary is None:
            raise ModelSelectionBlocked("requested model is not registered")
        capability = self._usable(primary, request, available_vram_mib)
        if capability is not None:
            return ModelSelection(primary.entry, capability, None, ())

        if (
            FallbackChange.MODEL not in fallback_policy.allowed_changes
            or not fallback_policy.fallback_model_ids
        ):
            raise ModelSelectionBlocked(
                "requested local model is unavailable and fallback is blocked"
            )
        for fallback_id in fallback_policy.fallback_model_ids:
            candidate = self._models.get(fallback_id)
            if candidate is None:
                continue
            capability = self._usable(candidate, request, available_vram_mib)
            if capability is not None:
                return ModelSelection(
                    candidate.entry,
                    capability,
                    request.model_id,
                    (FallbackChange.MODEL,),
                )
        raise ModelSelectionBlocked("no approved local fallback is executable")


def _capability(
    model_id: str,
    operation: GenerationMode,
    workflow_id: str,
    *,
    estimated_vram_mib: int,
    verified: bool = False,
    resolutions: tuple[VideoResolution, ...] | None = None,
) -> ModelCapability:
    capability_id = uuid5(
        _CAPABILITY_NAMESPACE,
        f"{model_id}:{operation.value}:{workflow_id}:v1",
    )
    return _hashed_capability(
        {
            "capability_id": capability_id,
            "model_id": model_id,
            "operation": operation,
            "workflow_id": workflow_id,
            "workflow_version": "v1",
            "local_only": True,
            "supported_resolutions": resolutions
            or (
                VideoResolution(width=480, height=832),
                VideoResolution(width=720, height=1280),
                VideoResolution(width=832, height=480),
                VideoResolution(width=1280, height=720),
            ),
            "supported_durations_seconds": (3.0, 5.0, 8.0),
            "supported_dtypes": ("bf16", "fp8"),
            "estimated_vram_mib": estimated_vram_mib,
            "warm_load_cost_seconds": 120,
            "verified": verified,
        }
    )


def _entry(
    model_id: str,
    display_name: str,
    source_url: str,
    license_name: str,
    capabilities: tuple[ModelCapability, ...],
) -> RegisteredModel:
    entry = _hashed_entry(
        {
            "registry_entry_id": uuid5(_REGISTRY_NAMESPACE, model_id),
            "model_id": model_id,
            "display_name": display_name,
            "source_url": source_url,
            "source_type": ModelSourceType.HUGGING_FACE,
            "license_name": license_name,
            "license_snapshot_sha256": stable_json_sha256(
                {"model_id": model_id, "license": license_name}
            ),
            "expected_size_bytes": None,
            "artifact_sha256": None,
            "local_path": None,
            "install_status": ModelInstallStatus.NOT_INSTALLED,
            "verification_status": ModelVerificationStatus.UNVERIFIED,
            "verified_at": None,
            "capability_ids": tuple(item.capability_id for item in capabilities),
            "compiler_profile": "wan-prompt-compiler.v1",
        }
    )
    return RegisteredModel(entry=entry, capabilities=capabilities)


def default_wan_registry() -> LocalModelRegistry:
    ti2v_id = "wan2.2-ti2v-5b"
    t2v_id = "wan2.2-t2v-a14b-fp8"
    i2v_id = "wan2.2-i2v-a14b-fp8"
    ti2v_resolutions = (
        VideoResolution(width=480, height=832),
        VideoResolution(width=704, height=1280),
        VideoResolution(width=832, height=480),
        VideoResolution(width=1280, height=704),
    )
    ti2v = (
        _capability(
            ti2v_id,
            GenerationMode.T2V,
            "wan22-ti2v-t2v",
            estimated_vram_mib=24576,
            resolutions=ti2v_resolutions,
        ),
        _capability(
            ti2v_id,
            GenerationMode.I2V,
            "wan22-ti2v-i2v",
            estimated_vram_mib=24576,
            resolutions=ti2v_resolutions,
        ),
    )
    t2v = (
        _capability(
            t2v_id,
            GenerationMode.T2V,
            "wan22-t2v-a14b",
            estimated_vram_mib=45056,
        ),
    )
    i2v = (
        _capability(
            i2v_id,
            GenerationMode.I2V,
            "wan22-i2v-a14b",
            estimated_vram_mib=45056,
        ),
        _capability(
            i2v_id,
            GenerationMode.FIRST_LAST_FRAME,
            "wan22-i2v-a14b-flf",
            estimated_vram_mib=46080,
        ),
    )
    return LocalModelRegistry(
        (
            _entry(
                ti2v_id,
                "Wan2.2 TI2V 5B",
                "https://huggingface.co/Wan-AI/Wan2.2-TI2V-5B",
                "Apache-2.0",
                ti2v,
            ),
            _entry(
                t2v_id,
                "Wan2.2 T2V A14B FP8",
                "https://huggingface.co/Wan-AI/Wan2.2-T2V-A14B",
                "Apache-2.0",
                t2v,
            ),
            _entry(
                i2v_id,
                "Wan2.2 I2V A14B FP8",
                "https://huggingface.co/Wan-AI/Wan2.2-I2V-A14B",
                "Apache-2.0",
                i2v,
            ),
        )
    )


def mark_model_load_verified(
    model: RegisteredModel,
    *,
    local_path: str,
    artifact_sha256: str,
    expected_size_bytes: int,
    verified_at: datetime | None = None,
) -> RegisteredModel:
    verified_at = verified_at or datetime.now(timezone.utc)
    capabilities_list: list[ModelCapability] = []
    for capability in model.capabilities:
        draft = capability.model_copy(
            update={
                "verified": True,
                "snapshot_sha256": "0" * 64,
            }
        )
        identity = draft.model_dump(mode="json", exclude={"snapshot_sha256"})
        capabilities_list.append(
            ModelCapability(
                **identity,
                snapshot_sha256=stable_json_sha256(identity),
            )
        )
    capabilities = tuple(capabilities_list)
    return _entry_from_verified(
        model,
        capabilities=capabilities,
        local_path=local_path,
        artifact_sha256=artifact_sha256,
        expected_size_bytes=expected_size_bytes,
        verified_at=verified_at,
    )


def mark_model_hash_verified(
    model: RegisteredModel,
    *,
    local_path: str,
    artifact_sha256: str,
    expected_size_bytes: int,
    verified_at: datetime | None = None,
) -> RegisteredModel:
    verified_at = verified_at or datetime.now(timezone.utc)
    draft = model.entry.model_copy(
        update={
            "expected_size_bytes": expected_size_bytes,
            "artifact_sha256": artifact_sha256,
            "local_path": local_path,
            "install_status": ModelInstallStatus.INSTALLED,
            "verification_status": ModelVerificationStatus.HASH_VERIFIED,
            "verified_at": verified_at,
            "snapshot_sha256": "0" * 64,
        }
    )
    identity = draft.model_dump(mode="json", exclude={"snapshot_sha256"})
    return RegisteredModel(
        entry=ModelRegistryEntry(
            **identity,
            snapshot_sha256=stable_json_sha256(identity),
        ),
        capabilities=model.capabilities,
    )


def _entry_from_verified(
    model: RegisteredModel,
    *,
    capabilities: tuple[ModelCapability, ...],
    local_path: str,
    artifact_sha256: str,
    expected_size_bytes: int,
    verified_at: datetime,
) -> RegisteredModel:
    draft = model.entry.model_copy(
        update={
            "expected_size_bytes": expected_size_bytes,
            "artifact_sha256": artifact_sha256,
            "local_path": local_path,
            "install_status": ModelInstallStatus.INSTALLED,
            "verification_status": ModelVerificationStatus.LOAD_VERIFIED,
            "verified_at": verified_at,
            "capability_ids": tuple(item.capability_id for item in capabilities),
            "snapshot_sha256": "0" * 64,
        }
    )
    identity = draft.model_dump(mode="json", exclude={"snapshot_sha256"})
    return RegisteredModel(
        entry=ModelRegistryEntry(
            **identity,
            snapshot_sha256=stable_json_sha256(identity),
        ),
        capabilities=capabilities,
    )


def _asset(
    relative_path: str,
    *,
    bytes: int,
    sha256: str,
) -> ModelBundleAsset:
    source_path = relative_path.replace("\\", "/")
    if source_path.startswith("diffusion_models/"):
        upstream = f"split_files/{source_path}"
    elif source_path.startswith("text_encoders/"):
        upstream = f"split_files/{source_path}"
    elif source_path.startswith("vae/"):
        upstream = f"split_files/{source_path}"
    elif source_path.startswith("loras/"):
        upstream = f"split_files/{source_path}"
    else:  # pragma: no cover - all locked assets use known Comfy directories
        raise ModelManifestError("unsupported Comfy model directory")
    return ModelBundleAsset(
        relative_path=source_path,
        bytes=bytes,
        sha256=sha256,
        source_url=(
            f"{_COMFY_SOURCE}/resolve/{_COMFY_REVISION}/{upstream}"
        ),
    )


_TEXT_ENCODER_ASSET = _asset(
    "text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors",
    bytes=6_735_906_897,
    sha256="c3355d30191f1f066b26d93fba017ae9809dce6c627dda5f6a66eaa651204f68",
)
_WAN21_VAE_ASSET = _asset(
    "vae/wan_2.1_vae.safetensors",
    bytes=253_815_318,
    sha256="2fc39d31359a4b0a64f55876d8ff7fa8d780956ae2cb13463b0223e15148976b",
)


def default_wan_bundle_specs(
    model_root: str | Path,
) -> tuple[ModelBundleManifest, ...]:
    root = str(Path(model_root).resolve())
    base = {
        "source_revision": _COMFY_REVISION,
        "license_name": "Apache-2.0",
        "model_root": root,
        "verification_status": ModelVerificationStatus.UNVERIFIED,
        "hash_verified_at": None,
        "load_verified_at": None,
        "load_verified_workflow_ids": (),
    }
    return (
        _with_bundle_hash(
            {
                **base,
                "model_id": "wan2.2-ti2v-5b",
                "assets": (
                    _asset(
                        "diffusion_models/wan2.2_ti2v_5B_fp16.safetensors",
                        bytes=9_999_658_848,
                        sha256="456f901338bd9eadbded3828b819109a9b68e8a525ca5cf8d0049a69fcfeca1e",
                    ),
                    _TEXT_ENCODER_ASSET,
                    _asset(
                        "vae/wan2.2_vae.safetensors",
                        bytes=1_409_400_960,
                        sha256="e40321bd36b9709991dae2530eb4ac303dd168276980d3e9bc4b6e2b75fed156",
                    ),
                ),
            }
        ),
        _with_bundle_hash(
            {
                **base,
                "model_id": "wan2.2-t2v-a14b-fp8",
                "assets": (
                    _asset(
                        "diffusion_models/wan2.2_t2v_high_noise_14B_fp8_scaled.safetensors",
                        bytes=14_293_923_632,
                        sha256="cad711ae211c8b23455ec68cd6a190a33a3d874234a77eb57266d73f8f0e6c9f",
                    ),
                    _asset(
                        "diffusion_models/wan2.2_t2v_low_noise_14B_fp8_scaled.safetensors",
                        bytes=14_293_923_632,
                        sha256="e71b96d7c82e638694c5e7fb98fac4bfb0e4ddc5fbbb4b1df40da8f0f1278a97",
                    ),
                    _TEXT_ENCODER_ASSET,
                    _WAN21_VAE_ASSET,
                    _asset(
                        "loras/wan2.2_t2v_lightx2v_4steps_lora_v1.1_high_noise.safetensors",
                        bytes=1_226_977_424,
                        sha256="698321cb86bd30c4af06c9b84e656a1048c8cb54e06d50694536fb5de37fde41",
                    ),
                    _asset(
                        "loras/wan2.2_t2v_lightx2v_4steps_lora_v1.1_low_noise.safetensors",
                        bytes=1_226_977_424,
                        sha256="ec95216e614b3c132c11bfb387b11feedf62163150ccc9068bca8a189771e75a",
                    ),
                ),
            }
        ),
        _with_bundle_hash(
            {
                **base,
                "model_id": "wan2.2-i2v-a14b-fp8",
                "assets": (
                    _asset(
                        "diffusion_models/wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors",
                        bytes=14_294_742_832,
                        sha256="6122e79d55e0f235698d11d657f3b196c5273c830da00b2b013c5a048d5e6a42",
                    ),
                    _asset(
                        "diffusion_models/wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors",
                        bytes=14_294_742_832,
                        sha256="5471a457b6ac404202a5fbe6c11595a3d5641fc766b00f38763f72303fffc21e",
                    ),
                    _TEXT_ENCODER_ASSET,
                    _WAN21_VAE_ASSET,
                    _asset(
                        "loras/wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors",
                        bytes=1_226_977_424,
                        sha256="d176c808d6fc461999b68e321efcb7501b20b8c3797523ed0df14f7d1deff11e",
                    ),
                    _asset(
                        "loras/wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors",
                        bytes=1_226_977_424,
                        sha256="024f21de095bc8fad9809ded3e9e49a2e170dcf27075da8145ba7d60d8aab7f9",
                    ),
                ),
            }
        ),
    )


def verify_model_bundle_hashes(
    bundle: ModelBundleManifest,
    *,
    verified_at: datetime | None = None,
) -> ModelBundleManifest:
    root = Path(bundle.model_root).resolve()
    if not root.is_dir():
        raise ModelManifestError("model root is unavailable")
    for asset in bundle.assets:
        path = (root / Path(asset.relative_path)).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ModelManifestError("model asset escapes model root") from exc
        if not path.is_file() or path.stat().st_size != asset.bytes:
            raise ModelManifestError(
                f"model asset is missing or has wrong size: {asset.relative_path}"
            )
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while chunk := handle.read(8 * 1024 * 1024):
                digest.update(chunk)
        if digest.hexdigest() != asset.sha256:
            raise ModelManifestError(
                f"model asset hash does not match: {asset.relative_path}"
            )
    now = verified_at or datetime.now(timezone.utc)
    return _with_bundle_hash(
        {
            **bundle.model_dump(mode="python", exclude={"bundle_sha256"}),
            "verification_status": (
                ModelVerificationStatus.LOAD_VERIFIED
                if bundle.verification_status
                is ModelVerificationStatus.LOAD_VERIFIED
                else ModelVerificationStatus.HASH_VERIFIED
            ),
            "hash_verified_at": now,
        }
    )


def mark_bundle_load_verified(
    bundle: ModelBundleManifest,
    *,
    workflow_ids: tuple[str, ...],
    verified_at: datetime | None = None,
) -> ModelBundleManifest:
    if bundle.verification_status not in {
        ModelVerificationStatus.HASH_VERIFIED,
        ModelVerificationStatus.LOAD_VERIFIED,
    }:
        raise ModelManifestError("bundle must pass hash verification first")
    if not workflow_ids or len(workflow_ids) != len(set(workflow_ids)):
        raise ModelManifestError("load verification workflow ids are invalid")
    now = verified_at or datetime.now(timezone.utc)
    return _with_bundle_hash(
        {
            **bundle.model_dump(mode="python", exclude={"bundle_sha256"}),
            "verification_status": ModelVerificationStatus.LOAD_VERIFIED,
            "load_verified_at": now,
            "load_verified_workflow_ids": workflow_ids,
        }
    )


class ModelRegistryManifestStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load(self) -> ModelRegistryManifest:
        if not self.path.is_file():
            raise ModelManifestError("model registry manifest is unavailable")
        return ModelRegistryManifest.model_validate_json(
            self.path.read_text(encoding="utf-8")
        )

    def write(
        self,
        bundles: tuple[ModelBundleManifest, ...],
        *,
        updated_at: datetime | None = None,
    ) -> ModelRegistryManifest:
        manifest = _with_registry_hash(
            {
                "schema_version": "factory.model-registry.v1",
                "bundles": bundles,
                "updated_at": updated_at or datetime.now(timezone.utc),
            }
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(
            self.path,
            manifest.model_dump(mode="json"),
        )
        return manifest

    def initialize(
        self,
        model_root: str | Path,
        *,
        updated_at: datetime | None = None,
    ) -> ModelRegistryManifest:
        if self.path.exists():
            return self.load()
        return self.write(
            default_wan_bundle_specs(model_root),
            updated_at=updated_at,
        )


def registry_from_manifest(
    manifest: ModelRegistryManifest,
) -> LocalModelRegistry:
    defaults = default_wan_registry().list_models()
    by_id = {item.model_id: item for item in manifest.bundles}
    resolved: list[RegisteredModel] = []
    for model in defaults:
        bundle = by_id.get(model.entry.model_id)
        if bundle is None or bundle.verification_status not in {
            ModelVerificationStatus.HASH_VERIFIED,
            ModelVerificationStatus.LOAD_VERIFIED,
        }:
            resolved.append(model)
            continue
        total_bytes = sum(item.bytes for item in bundle.assets)
        if bundle.verification_status is ModelVerificationStatus.LOAD_VERIFIED:
            resolved.append(
                mark_model_load_verified(
                    model,
                    local_path=bundle.model_root,
                    artifact_sha256=bundle.bundle_sha256,
                    expected_size_bytes=total_bytes,
                    verified_at=bundle.load_verified_at,
                )
            )
        else:
            resolved.append(
                mark_model_hash_verified(
                    model,
                    local_path=bundle.model_root,
                    artifact_sha256=bundle.bundle_sha256,
                    expected_size_bytes=total_bytes,
                    verified_at=bundle.hash_verified_at,
                )
            )
    return LocalModelRegistry(tuple(resolved))


def configured_wan_registry() -> LocalModelRegistry:
    path = os.getenv("DRAMA_MODEL_REGISTRY_MANIFEST", "").strip()
    if not path:
        return default_wan_registry()
    store = ModelRegistryManifestStore(path)
    try:
        return registry_from_manifest(store.load())
    except ModelManifestError:
        return default_wan_registry()
