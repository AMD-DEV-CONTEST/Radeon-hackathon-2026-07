"""Trusted, non-executing Ollama installation manifest and platform resolver."""

from __future__ import annotations

import json
import platform as host_platform
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlparse

from app.config import get_resource_path, get_runtime_path


TARGET_VERSION = "0.32.0"
DEFAULT_MANIFEST_PATH = get_resource_path(
    "resources", "ollama_install_manifests", f"v{TARGET_VERSION}.json"
)
SUPPORTED_PLATFORMS = {"windows", "macos", "linux"}
SUPPORTED_ARCHITECTURES = {"x86_64", "arm64"}
SUPPORTED_INSTALL_TYPES = {
    "native_installer",
    "user_archive",
    "disk_image",
    "system_archive",
    "runtime_addon",
}
SUPPORTED_VERIFICATION = {
    "sha256",
    "authenticode",
    "pe_signature",
    "codesign",
    "notarization",
    "archive_layout",
}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")


class OllamaInstallationError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.safe_message = message


@dataclass(frozen=True)
class TrustedOllamaArtifact:
    id: str
    platform: str
    architectures: tuple[str, ...]
    role: str
    install_type: str
    filename: str
    url: str
    size: int
    sha256: str
    verification: tuple[str, ...]
    requires_user_confirmation: bool
    accelerator: str | None = None


@dataclass(frozen=True)
class TrustedOllamaManifest:
    version: str
    tag: str
    channel: str
    published_at: str
    release_url: str
    assets: tuple[TrustedOllamaArtifact, ...]


@dataclass(frozen=True)
class OllamaInstallPlan:
    version: str
    platform: str
    architecture: str
    accelerator: str | None
    cache_root: str
    artifacts: tuple[TrustedOllamaArtifact, ...]

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["artifacts"] = [asdict(item) for item in self.artifacts]
        return payload


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(f"Invalid trusted Ollama manifest: {message}")


def _normalize_platform(value: str) -> str:
    normalized = value.strip().lower()
    aliases = {"windows": "windows", "darwin": "macos", "macos": "macos", "linux": "linux"}
    try:
        return aliases[normalized]
    except KeyError as exc:
        raise OllamaInstallationError("UNSUPPORTED_PLATFORM", "Unsupported operating system") from exc


def _normalize_architecture(value: str) -> str:
    normalized = value.strip().lower()
    aliases = {
        "amd64": "x86_64",
        "x86_64": "x86_64",
        "x64": "x86_64",
        "arm64": "arm64",
        "aarch64": "arm64",
    }
    try:
        return aliases[normalized]
    except KeyError as exc:
        raise OllamaInstallationError("UNSUPPORTED_ARCHITECTURE", "Unsupported processor architecture") from exc


def _load_artifact(raw: dict, tag: str) -> TrustedOllamaArtifact:
    filename = raw.get("filename")
    url = raw.get("url")
    parsed = urlparse(str(url))
    _require(isinstance(filename, str) and filename == Path(filename).name, "unsafe filename")
    expected_prefix = f"/ollama/ollama/releases/download/{tag}/"
    _require(
        parsed.scheme == "https"
        and parsed.hostname == "github.com"
        and parsed.path == expected_prefix + filename
        and not parsed.query
        and not parsed.fragment,
        f"untrusted asset URL for {filename}",
    )
    architectures = tuple(raw.get("architectures") or ())
    verification = tuple(raw.get("verification") or ())
    _require(raw.get("platform") in SUPPORTED_PLATFORMS, f"unsupported platform for {filename}")
    _require(bool(architectures) and set(architectures) <= SUPPORTED_ARCHITECTURES, f"invalid architectures for {filename}")
    _require(raw.get("role") in {"primary", "accelerator_addon"}, f"invalid role for {filename}")
    _require(raw.get("install_type") in SUPPORTED_INSTALL_TYPES, f"invalid install type for {filename}")
    _require(isinstance(raw.get("size"), int) and raw["size"] > 0, f"invalid size for {filename}")
    _require(_SHA256.fullmatch(str(raw.get("sha256", ""))) is not None, f"invalid sha256 for {filename}")
    _require("sha256" in verification and set(verification) <= SUPPORTED_VERIFICATION, f"invalid verification for {filename}")
    _require(raw.get("requires_user_confirmation") is True, f"confirmation is required for {filename}")
    if raw.get("role") == "accelerator_addon":
        _require(raw.get("accelerator") == "rocm", f"unsupported accelerator for {filename}")
    else:
        _require(raw.get("accelerator") is None, f"primary asset cannot select an accelerator for {filename}")
    return TrustedOllamaArtifact(
        id=str(raw.get("id")),
        platform=raw["platform"],
        architectures=architectures,
        role=raw["role"],
        install_type=raw["install_type"],
        filename=filename,
        url=url,
        size=raw["size"],
        sha256=raw["sha256"],
        verification=verification,
        requires_user_confirmation=True,
        accelerator=raw.get("accelerator"),
    )


def load_trusted_manifest(path: Path = DEFAULT_MANIFEST_PATH) -> TrustedOllamaManifest:
    raw = json.loads(path.read_text(encoding="utf-8"))
    _require(raw.get("schema_version") == 1, "schema_version must be 1")
    version = str(raw.get("version", ""))
    tag = str(raw.get("tag", ""))
    _require(_VERSION.fullmatch(version) is not None and version == TARGET_VERSION, "unexpected version")
    _require(tag == f"v{version}", "tag does not match version")
    _require(raw.get("channel") == "stable", "only stable releases are accepted")
    release_url = str(raw.get("release_url", ""))
    _require(release_url == f"https://github.com/ollama/ollama/releases/tag/{tag}", "untrusted release URL")
    assets = tuple(_load_artifact(item, tag) for item in raw.get("assets") or ())
    _require(len(assets) == 7, "seven pinned installation assets are required")
    _require(len({item.id for item in assets}) == len(assets), "asset ids must be unique")
    for operating_system in SUPPORTED_PLATFORMS:
        for architecture in SUPPORTED_ARCHITECTURES:
            matches = [
                item
                for item in assets
                if item.role == "primary"
                and item.platform == operating_system
                and architecture in item.architectures
            ]
            _require(len(matches) == 1, f"one primary asset required for {operating_system}/{architecture}")
    return TrustedOllamaManifest(
        version=version,
        tag=tag,
        channel=raw["channel"],
        published_at=str(raw.get("published_at", "")),
        release_url=release_url,
        assets=assets,
    )


def resolve_install_plan(
    *,
    system: str | None = None,
    machine: str | None = None,
    accelerator: str | None = None,
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
) -> OllamaInstallPlan:
    operating_system = _normalize_platform(system or host_platform.system())
    architecture = _normalize_architecture(machine or host_platform.machine())
    selected_accelerator = accelerator.strip().lower() if accelerator else None
    if selected_accelerator not in {None, "rocm"}:
        raise OllamaInstallationError("UNSUPPORTED_ACCELERATOR", "Unsupported Ollama accelerator package")
    manifest = load_trusted_manifest(manifest_path)
    primary = next(
        item
        for item in manifest.assets
        if item.role == "primary"
        and item.platform == operating_system
        and architecture in item.architectures
    )
    artifacts = [primary]
    if selected_accelerator:
        addon = next(
            (
                item
                for item in manifest.assets
                if item.role == "accelerator_addon"
                and item.platform == operating_system
                and architecture in item.architectures
                and item.accelerator == selected_accelerator
            ),
            None,
        )
        if addon is None:
            raise OllamaInstallationError(
                "UNSUPPORTED_ACCELERATOR",
                "The selected accelerator package is unavailable on this platform",
            )
        artifacts.append(addon)
    cache_root = get_runtime_path(
        "app_data", "cache", "ollama", "installers", f"v{manifest.version}"
    )
    return OllamaInstallPlan(
        version=manifest.version,
        platform=operating_system,
        architecture=architecture,
        accelerator=selected_accelerator,
        cache_root=str(cache_root),
        artifacts=tuple(artifacts),
    )
