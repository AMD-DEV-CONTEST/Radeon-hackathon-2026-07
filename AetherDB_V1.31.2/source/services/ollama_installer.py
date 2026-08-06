"""Fixed platform actions for verified, separately installed Ollama packages."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from app.config import get_runtime_path
from services.ollama_installation import OllamaInstallPlan, TrustedOllamaArtifact


INSTALL_WAIT_SECONDS = 30 * 60


class OllamaInstallerError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.safe_message = message


@dataclass(frozen=True)
class InstallActionResult:
    method: str
    managed_root: str | None = None
    needs_post_discovery_addon: bool = False


def get_managed_install_root(version: str) -> Path:
    return get_runtime_path("app_data", "external", "ollama", f"v{version}")


def _safe_member(name: str) -> bool:
    normalized = name.replace("\\", "/")
    trimmed = normalized.rstrip("/")
    raw_parts = trimmed.split("/") if trimmed else []
    reserved = {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{index}" for index in range(1, 10)),
        *(f"LPT{index}" for index in range(1, 10)),
    }
    return bool(raw_parts) and not normalized.startswith("/") and all(
        part not in {"", ".", ".."}
        and "\x00" not in part
        and ":" not in part
        and part.rstrip(" .").split(".", 1)[0].upper() not in reserved
        for part in raw_parts
    )


def _safe_destination(root: Path, relative_name: str) -> Path:
    if not _safe_member(relative_name):
        raise OllamaInstallerError(
            "ARCHIVE_LAYOUT_INVALID", "Install archive contains an unsafe path"
        )
    root.mkdir(parents=True, exist_ok=True)
    if root.is_symlink():
        raise OllamaInstallerError(
            "ARCHIVE_LAYOUT_INVALID", "Install destination contains a symbolic link"
        )
    root_resolved = root.resolve()
    relative_parts = PurePosixPath(relative_name.replace("\\", "/")).parts
    target = root.joinpath(*relative_parts)
    current = root
    for part in relative_parts[:-1]:
        current = current / part
        if current.exists():
            if current.is_symlink() or not current.is_dir():
                raise OllamaInstallerError(
                    "ARCHIVE_LAYOUT_INVALID",
                    "Install destination contains an unsafe path",
                )
        else:
            current.mkdir()
    if target.exists() and target.is_symlink():
        raise OllamaInstallerError(
            "ARCHIVE_LAYOUT_INVALID", "Install destination contains a symbolic link"
        )
    try:
        target.resolve().relative_to(root_resolved)
    except ValueError as exc:
        raise OllamaInstallerError(
            "ARCHIVE_LAYOUT_INVALID", "Install archive escaped its destination"
        ) from exc
    return target


def _extract_zip(archive_path: Path, destination: Path) -> None:
    try:
        with zipfile.ZipFile(archive_path) as archive:
            members = archive.infolist()
            if not members:
                raise OllamaInstallerError(
                    "ARCHIVE_LAYOUT_INVALID", "Install archive is empty"
                )
            for member in members:
                mode = (member.external_attr >> 16) & 0o170000
                if mode == 0o120000:
                    raise OllamaInstallerError(
                        "ARCHIVE_LAYOUT_INVALID",
                        "Install archive contains a symbolic link",
                    )
                target = _safe_destination(destination, member.filename)
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                with archive.open(member) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output, length=1024 * 1024)
    except zipfile.BadZipFile as exc:
        raise OllamaInstallerError(
            "ARCHIVE_LAYOUT_INVALID", "Install archive could not be opened"
        ) from exc


def _list_tar_zstd(archive_path: Path) -> list[str]:
    try:
        result = subprocess.run(
            ["tar", "--list", "--zstd", "--file", str(archive_path)],
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise OllamaInstallerError(
            "ARCHIVE_INSTALLER_UNAVAILABLE", "System archive installer is unavailable"
        ) from exc
    names = result.stdout.splitlines()
    if (
        result.returncode != 0
        or not names
        or sum(len(name) for name in names) > 4 * 1024 * 1024
        or any(not _safe_member(name) for name in names)
    ):
        raise OllamaInstallerError(
            "ARCHIVE_LAYOUT_INVALID", "Install archive failed its path validation"
        )
    try:
        verbose = subprocess.run(
            ["tar", "--list", "--verbose", "--zstd", "--file", str(archive_path)],
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise OllamaInstallerError(
            "ARCHIVE_INSTALLER_UNAVAILABLE", "System archive installer is unavailable"
        ) from exc
    verbose_lines = verbose.stdout.splitlines()
    if (
        verbose.returncode != 0
        or sum(len(line) for line in verbose_lines) > 8 * 1024 * 1024
        or any(line[:1] in {"l", "h"} for line in verbose_lines)
    ):
        raise OllamaInstallerError(
            "ARCHIVE_LAYOUT_INVALID",
            "Install archive contains an unsupported link or invalid entry",
        )
    return names


def _extract_tar_zstd(archive_path: Path, destination: Path) -> None:
    _list_tar_zstd(archive_path)
    try:
        result = subprocess.run(
            [
                "tar",
                "--extract",
                "--zstd",
                "--file",
                str(archive_path),
                "--directory",
                str(destination),
                "--no-same-owner",
                "--no-same-permissions",
            ],
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=INSTALL_WAIT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise OllamaInstallerError(
            "ARCHIVE_INSTALL_FAILED", "Install archive extraction failed"
        ) from exc
    if result.returncode != 0:
        raise OllamaInstallerError(
            "ARCHIVE_INSTALL_FAILED", "Install archive extraction failed"
        )
    for item in destination.rglob("*"):
        if item.is_symlink():
            raise OllamaInstallerError(
                "ARCHIVE_LAYOUT_INVALID", "Install archive contains a symbolic link"
            )
        try:
            item.resolve().relative_to(destination.resolve())
        except ValueError as exc:
            raise OllamaInstallerError(
                "ARCHIVE_LAYOUT_INVALID", "Install archive escaped its destination"
            ) from exc


def _extract_artifact(artifact: TrustedOllamaArtifact, source: Path, destination: Path):
    if source.suffix.lower() == ".zip":
        _extract_zip(source, destination)
        return
    if source.name.lower().endswith(".tar.zst"):
        _extract_tar_zstd(source, destination)
        return
    raise OllamaInstallerError(
        "UNSUPPORTED_INSTALL_TYPE", "Unsupported user-level install archive"
    )


def _find_managed_executable(root: Path, platform: str) -> Path | None:
    names = ("ollama.exe",) if platform == "windows" else ("ollama",)
    candidates = [root / name for name in names]
    candidates.extend(root / "bin" / name for name in names)
    for candidate in candidates:
        if candidate.is_file() and not candidate.is_symlink():
            return candidate
    return None


def _merge_tree(source: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for item in sorted(source.rglob("*"), key=lambda value: len(value.parts)):
        if item.is_symlink():
            raise OllamaInstallerError(
                "ARCHIVE_LAYOUT_INVALID", "Install archive contains a symbolic link"
            )
        relative = item.relative_to(source).as_posix()
        target = _safe_destination(destination, relative)
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif item.is_file():
            os.replace(item, target)


def _install_user_archives(plan: OllamaInstallPlan) -> InstallActionResult:
    root = get_managed_install_root(plan.version)
    root.parent.mkdir(parents=True, exist_ok=True)
    existing = _find_managed_executable(root, plan.platform) if root.exists() else None
    if root.exists() and existing is None:
        raise OllamaInstallerError(
            "MANAGED_INSTALL_INCOMPLETE",
            "The managed Ollama install directory is incomplete",
        )

    if existing is None:
        with tempfile.TemporaryDirectory(
            dir=root.parent, prefix=f".{root.name}-install-"
        ) as temp_dir:
            staging = Path(temp_dir) / "payload"
            staging.mkdir()
            primary = plan.artifacts[0]
            _extract_artifact(
                primary, Path(plan.cache_root) / primary.filename, staging
            )
            executable = _find_managed_executable(staging, plan.platform)
            if executable is None:
                raise OllamaInstallerError(
                    "RUNTIME_NOT_DETECTED",
                    "Installed archive does not contain the Ollama executable",
                )
            if plan.platform != "windows":
                executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
            os.replace(staging, root)

    for addon in plan.artifacts[1:]:
        with tempfile.TemporaryDirectory(
            dir=root.parent, prefix=f".{root.name}-addon-"
        ) as temp_dir:
            staging = Path(temp_dir) / "payload"
            staging.mkdir()
            _extract_artifact(addon, Path(plan.cache_root) / addon.filename, staging)
            _merge_tree(staging, root)
    return InstallActionResult(method="managed_user_archive", managed_root=str(root))


def _launch_windows_installer(path: Path) -> None:
    if os.name != "nt":
        raise OllamaInstallerError(
            "INSTALLER_UNAVAILABLE", "Windows installer is unavailable on this host"
        )
    try:
        process = subprocess.Popen([str(path)], shell=False)
        return_code = process.wait(timeout=INSTALL_WAIT_SECONDS)
    except subprocess.TimeoutExpired as exc:
        raise OllamaInstallerError(
            "INSTALLER_TIMEOUT", "Ollama installer did not finish in time"
        ) from exc
    except OSError as exc:
        raise OllamaInstallerError(
            "INSTALLER_LAUNCH_FAILED", "Ollama installer could not be started"
        ) from exc
    if return_code != 0:
        raise OllamaInstallerError(
            "INSTALLER_CANCELLED",
            "Ollama installer was cancelled or returned an error",
        )


def _open_macos_disk_image(path: Path) -> None:
    if sys.platform != "darwin":
        raise OllamaInstallerError(
            "INSTALLER_UNAVAILABLE", "macOS installer is unavailable on this host"
        )
    try:
        process = subprocess.Popen(
            ["/usr/bin/open", str(path)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return_code = process.wait(timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise OllamaInstallerError(
            "INSTALLER_LAUNCH_FAILED", "Ollama disk image could not be opened"
        ) from exc
    if return_code != 0:
        raise OllamaInstallerError(
            "INSTALLER_LAUNCH_FAILED", "Ollama disk image could not be opened"
        )


def install_verified_plan(plan: OllamaInstallPlan) -> InstallActionResult:
    primary = plan.artifacts[0]
    primary_path = Path(plan.cache_root) / primary.filename
    if primary.install_type in {"user_archive", "system_archive"}:
        return _install_user_archives(plan)
    if primary.platform == "windows" and primary.install_type == "native_installer":
        _launch_windows_installer(primary_path)
        return InstallActionResult(
            method="official_windows_installer",
            needs_post_discovery_addon=len(plan.artifacts) > 1,
        )
    if primary.platform == "macos" and primary.install_type == "disk_image":
        _open_macos_disk_image(primary_path)
        return InstallActionResult(method="official_macos_disk_image")
    raise OllamaInstallerError(
        "UNSUPPORTED_INSTALL_TYPE", "Unsupported Ollama installation method"
    )


def apply_post_discovery_addons(
    plan: OllamaInstallPlan, executable: Path, action: InstallActionResult
) -> None:
    if not action.needs_post_discovery_addon:
        return
    install_root = executable.parent
    for addon in plan.artifacts[1:]:
        with tempfile.TemporaryDirectory(
            dir=install_root.parent, prefix=".ollama-addon-"
        ) as temp_dir:
            staging = Path(temp_dir) / "payload"
            staging.mkdir()
            _extract_artifact(addon, Path(plan.cache_root) / addon.filename, staging)
            _merge_tree(staging, install_root)
