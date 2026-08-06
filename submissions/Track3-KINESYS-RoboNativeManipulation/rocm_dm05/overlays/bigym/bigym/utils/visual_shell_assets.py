"""Download, verify, cache, and resolve optional BiGym 3DGS scene shells."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tarfile
import tempfile
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True)
class VisualShellAsset:
    """Immutable metadata for one named visual-shell profile."""

    bundle_url: str
    bundle_sha256: str
    bundle_bytes: int
    bundle_root: str
    profile_path: str


_BUNDLE_URL = os.environ.get(
    "BIGYM_VISUAL_SHELL_BUNDLE_URL",
    "",
)
_BUNDLE_SHA256 = (
    "bc72810aca750b3392e416ba696b81258218bbbcd54886cf1375da22e9b0dc26"
)
_BUNDLE_BYTES = 226_124_687

ASSET_REGISTRY: dict[str, VisualShellAsset] = {
    "dl3dv-kitchen-mujoco": VisualShellAsset(
        bundle_url=_BUNDLE_URL,
        bundle_sha256=_BUNDLE_SHA256,
        bundle_bytes=_BUNDLE_BYTES,
        bundle_root="dl3dv-kitchen-v1",
        profile_path="dl3dv-kitchen-mujoco.json",
    ),
    "dl3dv-kitchen-bigym-h1": VisualShellAsset(
        bundle_url=_BUNDLE_URL,
        bundle_sha256=_BUNDLE_SHA256,
        bundle_bytes=_BUNDLE_BYTES,
        bundle_root="dl3dv-kitchen-v1",
        profile_path="dl3dv-kitchen-bigym-h1.json",
    ),
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _cache_dir() -> Path:
    configured = os.environ.get("BIGYM_VISUAL_SHELL_CACHE")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path.home() / ".bigym" / "visual_shells"


def _download(url: str, destination: Path, retries: int = 3) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            request = urllib.request.Request(
                url,
                headers={"User-Agent": "bigym-visual-shell-installer/1"},
            )
            with urllib.request.urlopen(request, timeout=60) as response:
                with destination.open("wb") as output:
                    shutil.copyfileobj(response, output, length=8 * 1024 * 1024)
            return
        except Exception as exc:
            last_error = exc
            destination.unlink(missing_ok=True)
            if attempt < retries:
                time.sleep(float(attempt))
    raise RuntimeError(f"failed to download {url}: {last_error}") from last_error


def _validated_archive_members(archive: tarfile.TarFile) -> list[tarfile.TarInfo]:
    members = archive.getmembers()
    if not members:
        raise RuntimeError("visual-shell bundle is empty")
    for member in members:
        member_path = Path(member.name)
        if (
            member_path.is_absolute()
            or ".." in member_path.parts
            or member.issym()
            or member.islnk()
            or member.ischr()
            or member.isblk()
            or member.isfifo()
        ):
            raise RuntimeError(
                f"unsafe member in visual-shell bundle: {member.name}"
            )
    return members


def _safe_extract(bundle: Path, destination: Path) -> None:
    with tarfile.open(bundle, mode="r:*") as archive:
        members = _validated_archive_members(archive)
        if sys.version_info >= (3, 12):
            archive.extractall(destination, members=members, filter="data")
        else:
            archive.extractall(destination, members=members)


def verify_visual_shell_directory(root: str | Path) -> dict[str, object]:
    """Verify every file declared by the bundle's signed manifest."""

    root_path = Path(root).expanduser().resolve()
    manifest_path = root_path / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"missing visual-shell manifest: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1:
        raise RuntimeError("unsupported visual-shell manifest schema")
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise RuntimeError("visual-shell manifest does not contain files")
    for entry in files:
        relative = Path(str(entry["path"]))
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError(f"unsafe path in visual-shell manifest: {relative}")
        path = root_path / relative
        if not path.is_file():
            raise FileNotFoundError(f"missing visual-shell asset: {path}")
        expected_bytes = int(entry["bytes"])
        actual_bytes = path.stat().st_size
        if actual_bytes != expected_bytes:
            raise RuntimeError(
                f"size mismatch for {relative}: {actual_bytes} != {expected_bytes}"
            )
        expected_sha256 = str(entry["sha256"]).lower()
        actual_sha256 = _sha256(path)
        if actual_sha256 != expected_sha256:
            raise RuntimeError(
                f"SHA-256 mismatch for {relative}: "
                f"{actual_sha256} != {expected_sha256}"
            )
    return manifest


def _install_asset(
    asset: VisualShellAsset,
    *,
    cache_dir: Path,
    bundle_override: Path | None = None,
) -> Path:
    target = cache_dir / asset.bundle_root
    if target.is_dir():
        try:
            verify_visual_shell_directory(target)
            return target
        except Exception:
            quarantine = cache_dir / (
                f"{asset.bundle_root}.invalid-{int(time.time())}"
            )
            target.rename(quarantine)

    cache_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".visual-shell-install-",
        dir=cache_dir,
    ) as temporary:
        temporary_dir = Path(temporary)
        bundle = temporary_dir / "bundle.tar.gz"
        if bundle_override is None:
            _download(asset.bundle_url, bundle)
        else:
            source = bundle_override.expanduser().resolve()
            if not source.is_file():
                raise FileNotFoundError(
                    f"BIGYM_VISUAL_SHELL_BUNDLE does not exist: {source}"
                )
            shutil.copyfile(source, bundle)

        actual_bytes = bundle.stat().st_size
        if actual_bytes != asset.bundle_bytes:
            raise RuntimeError(
                f"visual-shell bundle size mismatch: "
                f"{actual_bytes} != {asset.bundle_bytes}"
            )
        actual_sha256 = _sha256(bundle)
        if actual_sha256 != asset.bundle_sha256:
            raise RuntimeError(
                f"visual-shell bundle SHA-256 mismatch: "
                f"{actual_sha256} != {asset.bundle_sha256}"
            )

        extracted = temporary_dir / "extracted"
        extracted.mkdir()
        _safe_extract(bundle, extracted)
        candidate = extracted / asset.bundle_root
        verify_visual_shell_directory(candidate)
        candidate.rename(target)
    return target


def install_visual_shell(
    name: str,
    *,
    cache_dir: str | Path | None = None,
    registry: Mapping[str, VisualShellAsset] = ASSET_REGISTRY,
) -> Path:
    """Install a named shell and return its verified profile path."""

    if name not in registry:
        available = ", ".join(sorted(registry))
        raise KeyError(f"unknown visual shell {name!r}; available: {available}")
    asset = registry[name]
    bundle_override_value = os.environ.get("BIGYM_VISUAL_SHELL_BUNDLE")
    bundle_override = (
        Path(bundle_override_value) if bundle_override_value else None
    )
    root = _install_asset(
        asset,
        cache_dir=(
            Path(cache_dir).expanduser().resolve()
            if cache_dir is not None
            else _cache_dir()
        ),
        bundle_override=bundle_override,
    )
    profile = root / asset.profile_path
    if not profile.is_file():
        raise FileNotFoundError(f"visual-shell profile is missing: {profile}")
    return profile


def resolve_visual_shell_profile(
    profile: str | Path,
    *,
    cache_dir: str | Path | None = None,
    registry: Mapping[str, VisualShellAsset] = ASSET_REGISTRY,
) -> Path:
    """Resolve a local profile path or install a registered profile by name."""

    candidate = Path(profile).expanduser()
    if candidate.is_file():
        return candidate.resolve()
    if str(profile) in registry:
        return install_visual_shell(
            str(profile),
            cache_dir=cache_dir,
            registry=registry,
        )
    available = ", ".join(sorted(registry))
    raise FileNotFoundError(
        f"visual-shell profile {profile!s} is neither a file nor a registered "
        f"name; available: {available}"
    )


def _main() -> int:
    parser = argparse.ArgumentParser(
        description="Install and verify optional BiGym 3DGS scene shells."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("list", help="list registered scene-shell profiles")
    install_parser = subparsers.add_parser(
        "install",
        help="download, verify, and cache a scene shell",
    )
    install_parser.add_argument("name", choices=sorted(ASSET_REGISTRY))
    verify_parser = subparsers.add_parser(
        "verify",
        help="verify an installed scene-shell directory",
    )
    verify_parser.add_argument("path", type=Path)
    args = parser.parse_args()
    if args.command == "list":
        for name, asset in sorted(ASSET_REGISTRY.items()):
            print(f"{name}\t{asset.profile_path}")
        return 0
    if args.command == "install":
        print(install_visual_shell(args.name))
        return 0
    result = verify_visual_shell_directory(args.path)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
