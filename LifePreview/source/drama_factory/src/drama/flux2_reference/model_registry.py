from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path, PurePath, PurePosixPath
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


Sha256Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
GitCommit = Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
Flux2WorkflowRole = Literal[
    "text_to_image",
    "single_reference_edit",
    "dual_reference_edit",
]

_MODEL_FILES = {
    "diffusion_model": (
        "flux2_dev_fp8mixed.safetensors",
        35_455_599_592,
        "863a82e4ff950a42a6b0e80bea824828f129eb1a8fbbdbd9e8cb29859127b486",
    ),
    "text_encoder": (
        "mistral_3_small_flux2_fp8.safetensors",
        18_034_640_095,
        "e3467b7d912a234fb929cdf215dc08efdb011810b44bc21081c4234cc75b370e",
    ),
    "vae": (
        "flux2-vae.safetensors",
        336_213_556,
        "d64f3a68e1cc4f9f4e29b6e0da38a0204fe9a49f2d4053f0ec1fa1ca02f9c4b5",
    ),
}
_WORKFLOW_FILENAMES = {
    "text_to_image": "keyframe_flux2_t2i_api.json",
    "single_reference_edit": "keyframe_flux2_edit_api.json",
    "dual_reference_edit": "keyframe_flux2_edit_dual_api.json",
}
_MODEL_ROOT = "/persistent/douyin-amd/models/flux2-dev/flux2-dev-fp8mixed-v1"
_COMFY_RELEASE_ROOT = "/persistent/douyin-amd/comfyui/0.30.0-6f7cd7fc"
_COMFY_COMMIT = "6f7cd7fceaaf60d2669b554936394a7412c6fde5"


class Flux2CapabilityError(RuntimeError):
    """Base error for unavailable or untrusted FLUX.2-dev capabilities."""


class Flux2CapabilityUnavailable(Flux2CapabilityError):
    """The pinned FLUX.2-dev capability cannot be used safely."""


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Flux2ModelFileRevision(_StrictFrozenModel):
    role: Literal["diffusion_model", "text_encoder", "vae"]
    filename: Annotated[str, Field(min_length=1, max_length=255)]
    sha256: Sha256Digest
    size_bytes: Annotated[int, Field(gt=0)]

    @field_validator("filename")
    @classmethod
    def registry_local_filename(cls, value: str) -> str:
        lowered = value.casefold()
        if (
            PurePath(value).name != value
            or "/" in value
            or "\\" in value
            or "*" in value
            or "?" in value
            or "latest" in lowered
            or "klein" in lowered
        ):
            raise ValueError("FLUX.2-dev model filename must be pinned and registry-local")
        return value


class Flux2WorkflowRevision(_StrictFrozenModel):
    role: Flux2WorkflowRole
    workflow_id: Annotated[str, Field(min_length=1, max_length=160)]
    filename: Annotated[str, Field(min_length=1, max_length=255)]
    sha256: Sha256Digest
    status: Literal["verified"]

    @field_validator("filename")
    @classmethod
    def local_json_filename(cls, value: str) -> str:
        if (
            PurePath(value).name != value
            or "/" in value
            or "\\" in value
            or "*" in value
            or "?" in value
            or not value.endswith("_api.json")
        ):
            raise ValueError("FLUX.2 workflow filename must be a pinned local API JSON")
        return value


class Flux2ExecutionProfile(_StrictFrozenModel):
    width: Literal[512]
    height: Literal[768]
    sampler_name: Literal["euler"]
    steps: Literal[20]
    guidance: Literal[4.0]
    reference_megapixels: Literal[1.0]
    output_node_id: Literal["13"]


class Flux2DevCapability(_StrictFrozenModel):
    family: Literal["flux2-dev"]
    model_id: Literal["flux2-dev-fp8mixed.v1"]
    revision: Literal["flux2-dev-fp8mixed.v1"]
    diffusion_model: Flux2ModelFileRevision
    text_encoder: Flux2ModelFileRevision
    vae: Flux2ModelFileRevision
    workflows: tuple[Flux2WorkflowRevision, Flux2WorkflowRevision, Flux2WorkflowRevision]
    execution: Flux2ExecutionProfile
    license_snapshot: Literal["FLUX Non-Commercial License"]
    available: Literal[True]

    @model_validator(mode="after")
    def exact_amd_revision(self) -> "Flux2DevCapability":
        models = (self.diffusion_model, self.text_encoder, self.vae)
        if tuple(item.role for item in models) != tuple(_MODEL_FILES):
            raise ValueError("FLUX.2-dev capability has missing or unknown model roles")
        for item in models:
            expected = _MODEL_FILES[item.role]
            if (item.filename, item.size_bytes, item.sha256) != expected:
                raise ValueError(f"FLUX.2-dev {item.role} revision does not match AMD truth")
        roles = tuple(item.role for item in self.workflows)
        if roles != tuple(_WORKFLOW_FILENAMES):
            raise ValueError("FLUX.2-dev capability has missing, unknown, or unordered workflow roles")
        for item in self.workflows:
            if item.filename != _WORKFLOW_FILENAMES[item.role]:
                raise ValueError(f"FLUX.2-dev {item.role} workflow filename is not pinned")
        return self

    def model_file(self, role: str) -> Flux2ModelFileRevision:
        try:
            return {
                "diffusion_model": self.diffusion_model,
                "text_encoder": self.text_encoder,
                "vae": self.vae,
            }[role]
        except KeyError as exc:
            raise Flux2CapabilityUnavailable(
                f"unknown FLUX.2-dev model role: {role}"
            ) from exc

    def workflow(self, role: str) -> Flux2WorkflowRevision:
        for workflow in self.workflows:
            if workflow.role == role:
                return workflow
        raise Flux2CapabilityUnavailable(f"unknown FLUX.2-dev workflow role: {role}")

    @property
    def digest(self) -> str:
        return _digest(self.model_dump(mode="json"))


class Flux2AmdCapabilityManifest(_StrictFrozenModel):
    schema_version: Literal["flux2-dev-amd-capability.v1"]
    model_root: Literal[
        "/persistent/douyin-amd/models/flux2-dev/flux2-dev-fp8mixed-v1"
    ]
    comfy_release_root: Literal[
        "/persistent/douyin-amd/comfyui/0.30.0-6f7cd7fc"
    ]
    comfy_source_commit: GitCommit
    capability: Flux2DevCapability

    @model_validator(mode="after")
    def exact_amd_paths(self) -> "Flux2AmdCapabilityManifest":
        values = (self.model_root, self.comfy_release_root)
        if any("/workspace" in value.casefold() for value in values):
            raise ValueError("FLUX.2-dev capability cannot use /workspace")
        if self.model_root != _MODEL_ROOT or self.comfy_release_root != _COMFY_RELEASE_ROOT:
            raise ValueError("FLUX.2-dev capability paths must use the pinned AMD PVC release")
        if self.comfy_source_commit != _COMFY_COMMIT:
            raise ValueError("FLUX.2-dev ComfyUI commit mismatch")
        return self


@dataclass(frozen=True, slots=True)
class LoadedFlux2Capability:
    manifest: Flux2AmdCapabilityManifest
    capability: Flux2DevCapability
    model_root: PurePosixPath
    comfy_release_root: PurePosixPath
    files_verified: bool


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


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def verify_flux2_capability_files(
    capability: Flux2DevCapability,
    model_root: Path,
) -> None:
    locations = {
        "diffusion_model": ("diffusion_models", capability.diffusion_model),
        "text_encoder": ("text_encoders", capability.text_encoder),
        "vae": ("vae", capability.vae),
    }
    for role, (folder, revision) in locations.items():
        path = model_root / folder / revision.filename
        if not path.is_file() or path.stat().st_size != revision.size_bytes:
            raise Flux2CapabilityUnavailable(
                f"FLUX.2-dev {role} file is missing or incomplete"
            )
        if _sha256_file(path) != revision.sha256:
            raise Flux2CapabilityUnavailable(f"FLUX.2-dev {role} digest mismatch")


def _read_manifest_source(source: Path | str) -> str:
    if isinstance(source, Path):
        return source.read_text(encoding="utf-8")
    if source.lstrip().startswith("{"):
        return source
    return Path(source).read_text(encoding="utf-8")


def load_flux2_dev_capability(
    source: Path | str,
    *,
    verify_files: bool = False,
) -> LoadedFlux2Capability:
    try:
        manifest = Flux2AmdCapabilityManifest.model_validate_json(
            _read_manifest_source(source)
        )
    except (OSError, ValueError) as exc:
        raise Flux2CapabilityUnavailable(
            f"invalid flux2-dev AMD capability: {exc}"
        ) from exc
    if verify_files:
        verify_flux2_capability_files(
            manifest.capability,
            Path(manifest.model_root),
        )
    return LoadedFlux2Capability(
        manifest=manifest,
        capability=manifest.capability,
        model_root=PurePosixPath(manifest.model_root),
        comfy_release_root=PurePosixPath(manifest.comfy_release_root),
        files_verified=verify_files,
    )


__all__ = [
    "Flux2AmdCapabilityManifest",
    "Flux2CapabilityError",
    "Flux2CapabilityUnavailable",
    "Flux2DevCapability",
    "Flux2ExecutionProfile",
    "Flux2ModelFileRevision",
    "Flux2WorkflowRevision",
    "LoadedFlux2Capability",
    "load_flux2_dev_capability",
    "verify_flux2_capability_files",
]
