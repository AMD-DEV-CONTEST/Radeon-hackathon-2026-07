from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path, PurePath, PurePosixPath
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator, field_validator
from shared_contracts import H3GenerationMode


Sha256Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
GitCommit = Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]

_MODEL_ROOT = "/persistent/douyin-amd/models/minimax-h3/h3-amd-local-v1"
_COMFY_RELEASE_ROOT = "/persistent/douyin-amd/comfyui/0.30.0-6f7cd7fc"
_COMFY_COMMIT = "6f7cd7fceaaf60d2669b554936394a7412c6fde5"
_COMFY_ARCHIVE_SHA256 = "4ab47e702474df58971b381884a86da392cab0219c0312f98d4ae860fc110caf"
_MODEL_FILES = {
    "h3_ref2va_diffusion": (
        "minimax_h3_ref2va_pruned_int8_convrot.safetensors",
        20_970_379_616,
        "9255f52b6677845ad238f20dfaafa94727053694127ab7f255c048f0f9365779",
    ),
    "qwen3vl_text_encoder": (
        "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
        15_687_142_551,
        "35a88d51044231fe332301d7a62aa81e3f2cba62febeb446e2c1e3e0ef76f2c6",
    ),
    "h3_video_vae": (
        "minimax_h3_video_vae_fp16.safetensors",
        5_207_808_496,
        "7c1f131492e7eddacaac9069a61b81bdd39de5cc96561e677c5eab1cdce5e522",
    ),
    "h3_audio_vae": (
        "minimax_h3_audio_vae_fp32.safetensors",
        605_254_808,
        "8e505d95dd1561d47abd43d4238fd40d9bb1ae9e147ed0a4cba778d76ae4db48",
    ),
}
_NODE_SCHEMAS = {
    "MiniMaxH3ReferenceToVideo": "5fb5d6ad93a32fa0729d4f8bad8067ed12e06c0526fa9b5278fdf533be7281e4",
    "MiniMaxH3SigmaShift": "c64f72f3d1a67d027e79433c7f5d5e20f2689ef29545bcbab6a230487c0ce6b6",
}


class H3CapabilityError(RuntimeError):
    """Base error for an invalid or unavailable H3 AMD capability."""


class H3CapabilityUnavailable(H3CapabilityError):
    """The pinned H3 Ref2VA AMD capability cannot be trusted or used."""


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class H3ModelFileRevision(_StrictFrozenModel):
    role: Literal[
        "h3_ref2va_diffusion",
        "qwen3vl_text_encoder",
        "h3_video_vae",
        "h3_audio_vae",
    ]
    filename: Annotated[str, Field(min_length=1, max_length=255)]
    size_bytes: Annotated[int, Field(gt=0)]
    sha256: Sha256Digest

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
            or any(token in lowered for token in ("t2va", "fl2va"))
        ):
            raise ValueError("H3 model filename must be pinned, local, and Ref2VA-only")
        return value


class H3ExecutionProfile(_StrictFrozenModel):
    width: Literal[1344]
    height: Literal[768]
    fps: Literal[24]
    sampler_name: Literal["res_multistep"]
    scheduler: Literal["simple"]
    steps: Literal[20]
    denoise: Literal[1.0]
    shift_video: Literal[12.0]
    shift_audio: Literal[3.0]
    max_reference_images: Literal[9]
    output_node_id: Literal["15"]


class H3CapabilityRevision(_StrictFrozenModel):
    family: Literal["minimax-h3"]
    model_id: Literal["minimax-h3"]
    revision: Literal["h3-amd-local-v1"]
    supported_modes: tuple[Literal[H3GenerationMode.REF2VA]]
    model_files: dict[str, H3ModelFileRevision]
    workflow_filename: Literal["h3_ref2va_amd_api.json"]
    workflow_sha256: Sha256Digest
    node_schema_sha256: dict[str, Sha256Digest]
    execution: H3ExecutionProfile
    available: Literal[True]

    @model_validator(mode="after")
    def exact_amd_ref2va_revision(self) -> "H3CapabilityRevision":
        self.assert_exact_truth()
        return self

    def assert_exact_truth(self) -> None:
        """Recheck mutable container fields at every execution trust boundary."""

        if self.supported_modes != (H3GenerationMode.REF2VA,):
            raise ValueError("MiniMax H3 AMD capability supports Ref2VA only")
        if tuple(self.model_files) != tuple(_MODEL_FILES):
            raise ValueError("MiniMax H3 capability has missing or unknown model roles")
        for role, revision in self.model_files.items():
            if revision.role != role:
                raise ValueError("MiniMax H3 model role does not match its registry key")
            expected = _MODEL_FILES[role]
            if (revision.filename, revision.size_bytes, revision.sha256) != expected:
                raise ValueError(f"MiniMax H3 {role} revision does not match AMD truth")
        if self.node_schema_sha256 != _NODE_SCHEMAS:
            raise ValueError("MiniMax H3 live node schema digests do not match AMD truth")

    def model_file(self, role: str) -> H3ModelFileRevision:
        try:
            return self.model_files[role]
        except KeyError as exc:
            raise H3CapabilityUnavailable(f"unknown MiniMax H3 model role: {role}") from exc

    def checkpoint_for_mode(self, mode: H3GenerationMode) -> H3ModelFileRevision:
        if mode is not H3GenerationMode.REF2VA:
            raise H3CapabilityUnavailable("MiniMax H3 AMD supports Ref2VA only")
        return self.model_files["h3_ref2va_diffusion"]

    @property
    def text_encoder(self) -> H3ModelFileRevision:
        return self.model_files["qwen3vl_text_encoder"]

    @property
    def video_vae(self) -> H3ModelFileRevision:
        return self.model_files["h3_video_vae"]

    @property
    def audio_vae(self) -> H3ModelFileRevision:
        return self.model_files["h3_audio_vae"]

    @property
    def ref2va(self) -> H3ModelFileRevision:
        return self.model_files["h3_ref2va_diffusion"]

    @property
    def fps(self) -> int:
        return self.execution.fps

    @property
    def max_reference_images(self) -> int:
        return self.execution.max_reference_images

    @property
    def workflow_template_digest(self) -> str:
        return self.workflow_sha256

    @property
    def digest(self) -> str:
        return _stable_digest(self.model_dump(mode="json"))


class H3AmdCapabilityManifest(_StrictFrozenModel):
    schema_version: Literal["h3-ref2va-amd-capability.v1"]
    model_root: Literal[
        "/persistent/douyin-amd/models/minimax-h3/h3-amd-local-v1"
    ]
    comfy_release_root: Literal[
        "/persistent/douyin-amd/comfyui/0.30.0-6f7cd7fc"
    ]
    comfy_source_commit: GitCommit
    comfy_source_archive_sha256: Sha256Digest
    capability: H3CapabilityRevision

    @model_validator(mode="after")
    def exact_amd_release(self) -> "H3AmdCapabilityManifest":
        if self.model_root != _MODEL_ROOT or self.comfy_release_root != _COMFY_RELEASE_ROOT:
            raise ValueError("MiniMax H3 must use the pinned AMD PVC and ComfyUI release")
        if "/workspace" in self.model_root.casefold() or "/workspace" in self.comfy_release_root.casefold():
            raise ValueError("MiniMax H3 authority cannot use /workspace")
        if self.comfy_source_commit != _COMFY_COMMIT:
            raise ValueError("MiniMax H3 ComfyUI commit mismatch")
        if self.comfy_source_archive_sha256 != _COMFY_ARCHIVE_SHA256:
            raise ValueError("MiniMax H3 ComfyUI source archive mismatch")
        return self


@dataclass(frozen=True, slots=True)
class LoadedH3Capability:
    manifest: H3AmdCapabilityManifest
    capability: H3CapabilityRevision
    model_root: PurePosixPath
    comfy_release_root: PurePosixPath
    files_verified: bool
    workflow_verified: bool


def _stable_digest(value: object) -> str:
    import json

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


def _repository_file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def verify_h3_capability_files(
    capability: H3CapabilityRevision,
    model_root: Path,
) -> None:
    try:
        capability.assert_exact_truth()
        canonical_root = model_root.resolve(strict=True)
    except (OSError, ValueError) as exc:
        raise H3CapabilityUnavailable(
            "MiniMax H3 model root cannot be verified"
        ) from exc
    if model_root.is_symlink() or canonical_root != model_root:
        raise H3CapabilityUnavailable(
            "MiniMax H3 model root must be a canonical non-symlink path"
        )
    locations = {
        "h3_ref2va_diffusion": "diffusion_models",
        "qwen3vl_text_encoder": "text_encoders",
        "h3_video_vae": "vae",
        "h3_audio_vae": "vae",
    }
    for role, folder in locations.items():
        revision = capability.model_files[role]
        directory = model_root / folder
        path = directory / revision.filename
        try:
            if directory.is_symlink() or path.is_symlink():
                raise H3CapabilityUnavailable(
                    f"MiniMax H3 {role} path cannot be a symlink"
                )
            resolved_directory = directory.resolve(strict=True)
            resolved_path = path.resolve(strict=True)
            if (
                not resolved_directory.is_relative_to(canonical_root)
                or not resolved_path.is_relative_to(canonical_root)
                or resolved_directory != directory
                or resolved_path != path
            ):
                raise H3CapabilityUnavailable(
                    f"MiniMax H3 {role} path escapes the canonical model root"
                )
            if not path.is_file() or path.stat().st_size != revision.size_bytes:
                raise H3CapabilityUnavailable(
                    f"MiniMax H3 {role} file is missing or incomplete"
                )
            if _sha256_file(path) != revision.sha256:
                raise H3CapabilityUnavailable(f"MiniMax H3 {role} digest mismatch")
        except H3CapabilityUnavailable:
            raise
        except OSError as exc:
            raise H3CapabilityUnavailable(
                f"MiniMax H3 {role} file cannot be verified"
            ) from exc


def verify_h3_comfy_archive_release(
    comfy_root: Path,
    *,
    expected_commit: str,
    expected_archive_sha256: str,
) -> None:
    """Verify the immutable source-archive markers used by the AMD cloud release."""

    revision_marker = comfy_root / ".source-revision"
    archive_marker = comfy_root / ".source-archive-sha256"
    try:
        canonical_root = comfy_root.resolve(strict=True)
        if (
            comfy_root.is_symlink()
            or canonical_root != comfy_root
            or revision_marker.is_symlink()
            or archive_marker.is_symlink()
            or revision_marker.resolve(strict=True).parent != canonical_root
            or archive_marker.resolve(strict=True).parent != canonical_root
        ):
            raise H3CapabilityUnavailable(
                "MiniMax H3 ComfyUI release markers must be canonical non-symlink files"
            )
        revision = revision_marker.read_text(encoding="utf-8").strip()
        archive_sha256 = archive_marker.read_text(encoding="utf-8").strip()
    except H3CapabilityUnavailable:
        raise
    except (OSError, UnicodeError) as exc:
        raise H3CapabilityUnavailable(
            "MiniMax H3 ComfyUI archive release cannot be verified"
        ) from exc
    if revision != expected_commit or archive_sha256 != expected_archive_sha256:
        raise H3CapabilityUnavailable(
            "MiniMax H3 ComfyUI archive release markers mismatch"
        )


def _read_source(source: Path | str) -> str:
    if isinstance(source, Path):
        return source.read_text(encoding="utf-8")
    if source.lstrip().startswith("{"):
        return source
    return Path(source).read_text(encoding="utf-8")


def load_h3_amd_capability(
    source: Path | str,
    *,
    workflow_path: Path,
    verify_files: bool = False,
) -> LoadedH3Capability:
    try:
        manifest = H3AmdCapabilityManifest.model_validate_json(_read_source(source))
        capability = manifest.capability
        if workflow_path.name != capability.workflow_filename:
            raise ValueError("MiniMax H3 workflow filename is not capability-authorized")
        if _repository_file_sha256(workflow_path) != capability.workflow_sha256:
            raise ValueError("MiniMax H3 checked-in workflow SHA-256 mismatch")
    except (OSError, ValueError) as exc:
        raise H3CapabilityUnavailable(f"invalid MiniMax H3 Ref2VA AMD capability: {exc}") from exc
    if verify_files:
        model_root = Path(manifest.model_root)
        comfy_root = Path(manifest.comfy_release_root)
        try:
            invalid_root = (
                model_root.is_symlink()
                or comfy_root.is_symlink()
                or model_root.resolve(strict=True) != model_root
                or comfy_root.resolve(strict=True) != comfy_root
            )
        except OSError as exc:
            raise H3CapabilityUnavailable(
                "MiniMax H3 runtime roots cannot be verified"
            ) from exc
        if invalid_root:
            raise H3CapabilityUnavailable(
                "MiniMax H3 runtime roots must be the canonical non-symlink PVC paths"
            )
        verify_h3_capability_files(capability, model_root)
        verify_h3_comfy_archive_release(
            comfy_root,
            expected_commit=manifest.comfy_source_commit,
            expected_archive_sha256=manifest.comfy_source_archive_sha256,
        )
    return LoadedH3Capability(
        manifest=manifest,
        capability=capability,
        model_root=PurePosixPath(manifest.model_root),
        comfy_release_root=PurePosixPath(manifest.comfy_release_root),
        files_verified=verify_files,
        workflow_verified=True,
    )


__all__ = [
    "H3AmdCapabilityManifest",
    "H3CapabilityError",
    "H3CapabilityRevision",
    "H3CapabilityUnavailable",
    "H3ExecutionProfile",
    "H3ModelFileRevision",
    "LoadedH3Capability",
    "load_h3_amd_capability",
    "verify_h3_capability_files",
    "verify_h3_comfy_archive_release",
]
