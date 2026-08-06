from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Callable
from hashlib import sha256
from pathlib import Path
import re
import shutil
import stat
import tempfile
from uuid import uuid4
import zipfile

from agent_factory.paths import project_root, system_package_root
from agent_factory.package_distribution import (
    distribution_extension_preview,
    export_distribution_archive,
    import_distribution_extensions,
)
from agent_factory.runtime_contracts import AgentPackageLoader, LoadedAgentPackage


DEFAULT_AGENT_PACKAGE_ROOT = ".agentfactory/packages"
MAX_IMPORT_ARCHIVE_BYTES = 200 * 1024 * 1024
MAX_IMPORT_FILES = 5_000
MAX_IMPORT_UNCOMPRESSED_BYTES = 500 * 1024 * 1024
IMPORT_TRANSIENT_PARTS = frozenset({".agent_runtime", ".factory", ".env", "__pycache__"})


@dataclass(slots=True)
class AgentPackageRepository:
    package_root: Path
    system_package_root: Path
    loader: AgentPackageLoader = field(default_factory=AgentPackageLoader)

    @classmethod
    def from_paths(
        cls,
        *,
        package_root: str | Path | None = None,
        system_package_root: str | Path | None = None,
    ) -> "AgentPackageRepository":
        return cls(
            package_root=Path(package_root).expanduser() if package_root else default_package_root(),
            system_package_root=(
                Path(system_package_root).expanduser()
                if system_package_root
                else default_system_package_root()
            ),
        )

    def manifest_paths(self) -> list[Path]:
        self.package_root.mkdir(parents=True, exist_ok=True)
        self.system_package_root.mkdir(parents=True, exist_ok=True)
        paths_by_package_id: dict[str, Path] = {}
        for path in sorted(self.system_package_root.glob("*/agent_package.json")):
            paths_by_package_id[path.parent.name] = path
        for path in sorted(self.package_root.glob("*/agent_package.json")):
            paths_by_package_id[path.parent.name] = path
        return sorted(paths_by_package_id.values())

    def load(self, package_id: str) -> LoadedAgentPackage:
        return self.loader.load_path(self.manifest_path(package_id))

    def load_manifest(self, manifest_path: Path) -> LoadedAgentPackage:
        return self.loader.load_path(manifest_path)

    def manifest_path(self, package_id: str) -> Path:
        return self.package_dir(package_id) / "agent_package.json"

    def package_origin(self, manifest_path: Path) -> str:
        resolved_manifest = manifest_path.resolve()
        resolved_system_root = self.system_package_root.resolve()
        try:
            resolved_manifest.relative_to(resolved_system_root)
        except ValueError:
            return "user"
        return "system"

    def package_capabilities(self, manifest_path: Path) -> dict[str, bool]:
        user_managed = self.package_origin(manifest_path) == "user"
        return {
            "deletable": user_managed,
            "exportable": user_managed,
        }

    def package_dir(self, package_id: str, *, include_system_packages: bool = True) -> Path:
        if not package_id or "/" in package_id or "\\" in package_id or package_id in {".", ".."}:
            raise ValueError(f"invalid agent package id: {package_id}")
        user_target = safe_child(self.package_root, package_id, label="agent package")
        if user_target.exists() or not include_system_packages:
            return user_target
        system_target = safe_child(self.system_package_root, package_id, label="system package")
        if system_target.exists():
            return system_target
        return user_target

    def delete_user_package(self, package_id: str) -> dict[str, object]:
        target = self.package_dir(package_id, include_system_packages=False)
        if not target.exists():
            system_target = safe_child(self.system_package_root, package_id, label="system package")
            if system_target.exists():
                raise ValueError(f"built-in agent package cannot be deleted: {package_id}")
            raise FileNotFoundError(f"agent package not found: {package_id}")
        shutil.rmtree(target)
        return {"package_id": package_id, "deleted": True}

    def distribution_preview(self, package_id: str) -> dict[str, object]:
        target = self._require_exportable_user_package(package_id)
        return distribution_extension_preview(target, package_id)

    def export_user_package_archive(
        self,
        package_id: str,
        *,
        extension_overrides: dict[str, object] | None = None,
    ) -> Path:
        target = self._require_exportable_user_package(package_id)
        archive_stem = safe_archive_stem(package_id)
        with tempfile.NamedTemporaryFile(prefix=f"{archive_stem}-", suffix=".zip", delete=False) as handle:
            archive_path = Path(handle.name)
        try:
            export_distribution_archive(
                target,
                package_id,
                archive_path,
                extension_overrides=extension_overrides,
            )
        except Exception:
            archive_path.unlink(missing_ok=True)
            raise
        return archive_path

    def _require_exportable_user_package(self, package_id: str) -> Path:
        target = self.package_dir(package_id, include_system_packages=False)
        manifest_path = target / "agent_package.json"
        if not manifest_path.is_file():
            system_target = safe_child(self.system_package_root, package_id, label="system package")
            if (system_target / "agent_package.json").is_file():
                raise ValueError(f"built-in agent package cannot be exported: {package_id}")
            raise FileNotFoundError(f"agent package not found: {package_id}")
        return target

    def install_user_package_archive(
        self,
        archive_path: str | Path,
        *,
        expected_sha256: str,
        expected_package_id: str,
        replace: bool = False,
        prepare_package: Callable[[Path], None] | None = None,
    ) -> LoadedAgentPackage:
        source = Path(archive_path)
        if not source.is_file():
            raise FileNotFoundError(f"agent package archive not found: {source}")
        if source.stat().st_size > MAX_IMPORT_ARCHIVE_BYTES:
            raise ValueError("agent package archive exceeds the import size limit")
        actual_sha256 = file_sha256(source)
        if actual_sha256 != expected_sha256.casefold():
            raise ValueError("agent package archive checksum does not match the published release")

        self.package_root.mkdir(parents=True, exist_ok=True)
        staging_parent = self.package_root / ".install_staging"
        staging_parent.mkdir(parents=True, exist_ok=True)
        transaction_root = staging_parent / uuid4().hex
        extracted_root = transaction_root / "extracted"
        backup_root = transaction_root / "previous"
        extracted_root.mkdir(parents=True)
        try:
            manifest_path = _extract_package_archive(source, extracted_root)
            package = self.loader.load_path(manifest_path)
            package_id = package.manifest.agent.id
            if package_id != expected_package_id:
                raise ValueError(
                    f"downloaded package id {package_id!r} does not match release "
                    f"{expected_package_id!r}"
                )
            target = self.package_dir(package_id, include_system_packages=False)
            system_target = safe_child(
                self.system_package_root,
                package_id,
                label="system package",
            )
            if (system_target / "agent_package.json").is_file():
                raise ValueError(f"built-in agent package cannot be replaced: {package_id}")
            if target.exists() and not replace:
                raise FileExistsError(f"agent package is already installed: {package_id}")

            staged_package_root = manifest_path.parent
            if prepare_package is not None:
                prepare_package(staged_package_root)
                package = self.loader.load_path(manifest_path)
            if target.exists():
                target.rename(backup_root)
            try:
                staged_package_root.rename(target)
                import_distribution_extensions(target)
            except Exception:
                if target.exists():
                    shutil.rmtree(target)
                if backup_root.exists():
                    backup_root.rename(target)
                raise
            if backup_root.exists():
                shutil.rmtree(backup_root)
            return self.loader.load_path(target / "agent_package.json")
        finally:
            shutil.rmtree(transaction_root, ignore_errors=True)
            try:
                staging_parent.rmdir()
            except OSError:
                pass


def default_package_root() -> Path:
    return project_root() / DEFAULT_AGENT_PACKAGE_ROOT


def default_system_package_root() -> Path:
    return system_package_root()


def safe_child(root: Path, child_name: str, *, label: str) -> Path:
    resolved_root = root.resolve()
    target = (resolved_root / child_name).resolve()
    try:
        target.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(f"{label} escapes package root: {child_name}") from exc
    return target


def safe_archive_stem(value: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._-")
    return stem or "agent-package"


def file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _extract_package_archive(archive_path: Path, destination: Path) -> Path:
    try:
        archive = zipfile.ZipFile(archive_path)
    except zipfile.BadZipFile as exc:
        raise ValueError("downloaded agent package is not a valid ZIP archive") from exc
    with archive:
        files = [item for item in archive.infolist() if not item.is_dir()]
        if not files or len(files) > MAX_IMPORT_FILES:
            raise ValueError("agent package archive has an invalid file count")
        total_size = 0
        seen: set[str] = set()
        manifest_candidates: list[Path] = []
        for item in files:
            relative = _safe_archive_member(item)
            key = relative.as_posix()
            if key in seen:
                raise ValueError(f"agent package archive contains a duplicate path: {key}")
            seen.add(key)
            total_size += item.file_size
            if total_size > MAX_IMPORT_UNCOMPRESSED_BYTES:
                raise ValueError("agent package archive exceeds the uncompressed size limit")
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(item) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)
            if relative.name == "agent_package.json" and len(relative.parts) in {1, 2}:
                manifest_candidates.append(target)
        if len(manifest_candidates) != 1:
            raise ValueError("agent package archive must contain one root agent_package.json")
        return manifest_candidates[0]


def _safe_archive_member(item: zipfile.ZipInfo) -> Path:
    raw = item.filename
    if not raw or "\x00" in raw or "\\" in raw:
        raise ValueError(f"agent package archive contains an invalid path: {raw!r}")
    relative = Path(raw)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise ValueError(f"agent package archive contains an unsafe path: {raw}")
    mode = (item.external_attr >> 16) & 0xFFFF
    if stat.S_ISLNK(mode):
        raise ValueError(f"agent package archive contains a symbolic link: {raw}")
    if any(part in IMPORT_TRANSIENT_PARTS for part in relative.parts):
        raise ValueError(f"agent package archive contains runtime or secret content: {raw}")
    if relative.suffix.casefold() in {".pyc", ".pyo"}:
        raise ValueError(f"agent package archive contains compiled Python content: {raw}")
    return relative
