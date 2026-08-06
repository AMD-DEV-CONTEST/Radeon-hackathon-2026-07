from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tempfile
from typing import Any, Iterator
from uuid import uuid4
import zipfile

from packaging.utils import InvalidWheelFilename, canonicalize_name, parse_wheel_filename

from agent_factory.file_lock import exclusive_file_lock
from agent_factory.paths import factory_artifact_path

from .versions import DEPENDENCY_POOL_VERSION


class DependencyPoolError(RuntimeError):
    def __init__(self, status: str, message: str) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True, slots=True)
class DependencyPoolResolution:
    python_entries: list[dict[str, str]]
    system_entries: list[dict[str, str]]
    npm_profile: dict[str, str] | None
    profile_key: str = ""
    cache_status: str = "resolved"

    def to_lock_payload(self) -> dict[str, Any]:
        return {
            "version": DEPENDENCY_POOL_VERSION,
            "python_entries": self.python_entries,
            "system_entries": self.system_entries,
            "npm_profile": self.npm_profile,
        }


class DependencyPool:
    """Content-addressed dependency artifacts shared by all AgentPackages."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or factory_artifact_path("dependency_pool")).resolve()

    def references_available(self, payload: object) -> bool:
        if not isinstance(payload, dict) or payload.get("version") != DEPENDENCY_POOL_VERSION:
            return False
        for key in ("python_entries", "system_entries"):
            entries = payload.get(key)
            if not isinstance(entries, list):
                return False
            for entry in entries:
                if not isinstance(entry, dict) or not self._entry_exists(entry.get("path")):
                    return False
                if key == "python_entries" and not self._entry_exists(entry.get("artifact_path")):
                    return False
        npm_profile = payload.get("npm_profile")
        return npm_profile is None or (
            isinstance(npm_profile, dict) and self._entry_exists(npm_profile.get("path"))
        )

    def _store_wheel(self, wheel: Path) -> dict[str, str]:
        with self._exclusive_lock():
            return self._store_wheel_locked(wheel)

    def _store_wheel_locked(self, wheel: Path) -> dict[str, str]:
        digest = _sha256_file(wheel)
        wheel_metadata = _wheel_metadata(wheel.name)
        relative = PurePosixPath("python") / "wheels" / digest
        target = self.root / relative
        artifact_relative = PurePosixPath("python") / "artifacts" / digest / wheel.name
        artifact = self.root / artifact_relative
        if not artifact.is_file():
            artifact.parent.mkdir(parents=True, exist_ok=True)
            temporary_artifact = artifact.with_name(f".{artifact.name}.{uuid4().hex}.tmp")
            shutil.copy2(wheel, temporary_artifact)
            temporary_artifact.replace(artifact)
        site_packages = target / "site-packages"
        if not site_packages.is_dir():
            temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
            temporary.mkdir(parents=True, exist_ok=False)
            try:
                extracted = temporary / "site-packages"
                extracted.mkdir()
                _safe_extract_wheel(wheel, extracted)
                metadata = {
                    **wheel_metadata,
                    "filename": wheel.name,
                    "sha256": digest,
                    "artifact_path": artifact_relative.as_posix(),
                }
                (temporary / "metadata.json").write_text(
                    json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    shutil.rmtree(temporary)
                else:
                    temporary.replace(target)
            finally:
                if temporary.exists():
                    shutil.rmtree(temporary)
        index = self._read_python_artifact_index()
        index["artifacts"][digest] = {
            **wheel_metadata,
            "filename": wheel.name,
            "sha256": digest,
            "artifact_path": artifact_relative.as_posix(),
        }
        distributions = index["distributions"]
        versions = distributions.setdefault(wheel_metadata["name"], {})
        digests = versions.setdefault(wheel_metadata["version"], [])
        if digest not in digests:
            digests.append(digest)
            digests.sort()
        self._write_python_artifact_index(index)
        return {
            "path": relative.as_posix(),
            "sha256": digest,
            "filename": wheel.name,
            "artifact_path": artifact_relative.as_posix(),
            **wheel_metadata,
        }

    def _store_file(self, source: Path, *, directory: str) -> dict[str, str]:
        with self._exclusive_lock():
            digest = _sha256_file(source)
            suffix = source.suffix
            relative = PurePosixPath(directory) / f"{digest}{suffix}"
            target = self.root / relative
            if not target.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
                shutil.copy2(source, temporary)
                temporary.replace(target)
            return {"path": relative.as_posix(), "sha256": digest, "filename": source.name}

    def _materialize_python_wheelhouse(self, destination: Path) -> None:
        index = self._read_python_artifact_index()
        for record in index["artifacts"].values():
            filename = record.get("filename")
            artifact_path = record.get("artifact_path")
            if not isinstance(filename, str) or Path(filename).name != filename:
                continue
            if not isinstance(artifact_path, str):
                continue
            try:
                source = self.root / _safe_relative_path(artifact_path)
            except ValueError:
                continue
            if not source.is_file():
                continue
            target = destination / filename
            if target.exists():
                if _sha256_file(target) != record.get("sha256"):
                    raise DependencyPoolError("pool_conflict", f"conflicting cached wheel filename: {filename}")
                continue
            try:
                target.hardlink_to(source)
            except OSError:
                shutil.copy2(source, target)

    def _read_python_artifact_index(self) -> dict[str, Any]:
        path = self.root / "python" / "artifact_index.json"
        value: object = None
        if path.is_file():
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                value = None
        artifacts: dict[str, dict[str, Any]] = {}
        if (
            isinstance(value, dict)
            and value.get("version") == "python_artifact_index.v1"
            and isinstance(value.get("artifacts"), dict)
        ):
            artifacts = {
                str(key): dict(record)
                for key, record in value["artifacts"].items()
                if isinstance(record, dict)
            }
        artifacts.update(self._python_artifacts_from_storage())
        return {
            "version": "python_artifact_index.v1",
            "artifacts": artifacts,
            "distributions": _distribution_index(artifacts),
        }

    def _python_artifacts_from_storage(self) -> dict[str, dict[str, str]]:
        root = self.root / "python" / "artifacts"
        if not root.is_dir():
            return {}
        artifacts: dict[str, dict[str, str]] = {}
        for digest_directory in root.iterdir():
            digest = digest_directory.name
            if (
                not digest_directory.is_dir()
                or len(digest) != 64
                or any(character not in "0123456789abcdef" for character in digest)
            ):
                continue
            for wheel in digest_directory.iterdir():
                if not wheel.is_file() or wheel.suffix != ".whl":
                    continue
                try:
                    metadata = _wheel_metadata(wheel.name)
                except DependencyPoolError:
                    continue
                artifact_path = PurePosixPath("python") / "artifacts" / digest / wheel.name
                artifacts[digest] = {
                    **metadata,
                    "filename": wheel.name,
                    "sha256": digest,
                    "artifact_path": artifact_path.as_posix(),
                }
        return artifacts

    def _write_python_artifact_index(self, index: dict[str, Any]) -> None:
        path = self.root / "python" / "artifact_index.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        temporary.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)

    def _entry_exists(self, value: object) -> bool:
        if not isinstance(value, str) or not value:
            return False
        try:
            relative = _safe_relative_path(value)
        except ValueError:
            return False
        return (self.root / relative).exists()

    def _read_profile(self, key: str) -> DependencyPoolResolution | None:
        path = self.root / "profiles" / f"{key}.json"
        if not path.is_file():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if value.get("version") != DEPENDENCY_POOL_VERSION:
                return None
            python_entries = value.get("python_entries")
            system_entries = value.get("system_entries")
            npm_profile = value.get("npm_profile")
        except (OSError, json.JSONDecodeError, AttributeError):
            return None
        if not isinstance(python_entries, list) or not isinstance(system_entries, list):
            return None
        if npm_profile is not None and not isinstance(npm_profile, dict):
            return None
        if not all(isinstance(item, dict) for item in [*python_entries, *system_entries]):
            return None
        return DependencyPoolResolution(
            python_entries=[dict(item) for item in python_entries],
            system_entries=[dict(item) for item in system_entries],
            npm_profile=dict(npm_profile) if isinstance(npm_profile, dict) else None,
        )

    def _write_profile(
        self,
        key: str,
        resolution: DependencyPoolResolution,
        *,
        request: dict[str, Any],
    ) -> None:
        path = self.root / "profiles" / f"{key}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".json.tmp")
        payload = {**resolution.to_lock_payload(), "request": request}
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)

    @contextmanager
    def _exclusive_lock(self) -> Iterator[None]:
        lock_path = self.root / ".pool.lock"
        with exclusive_file_lock(lock_path):
            yield

    @contextmanager
    def _profile_lock(self, profile_key: str) -> Iterator[None]:
        lock_path = self.root / "profiles" / ".locks" / f"{profile_key}.lock"
        with exclusive_file_lock(lock_path):
            yield

    @contextmanager
    def _cache_lock(self, ecosystem: str) -> Iterator[None]:
        lock_path = self.root / ".cache_locks" / f"{ecosystem}.lock"
        with exclusive_file_lock(lock_path):
            yield

    @contextmanager
    def _staging_directory(self) -> Iterator[Path]:
        staging_root = self.root / "staging"
        staging_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="resolve-", dir=staging_root) as value:
            yield Path(value)

    def _run(self, command: list[str], *, timeout_seconds: int | None, action: str) -> None:
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise DependencyPoolError("build_failed", f"{action} timed out after {timeout_seconds}s") from exc
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or f"{action} failed").strip()
            raise DependencyPoolError("build_failed", f"{action} failed: {detail[-4000:]}")


def dependency_pool_path() -> Path:
    return factory_artifact_path("dependency_pool")


def _normalized_values(values: list[str]) -> list[str]:
    return sorted({value.strip() for value in values if value and value.strip()})


def _assert_installable_requirements(values: list[str], *, ecosystem: str) -> None:
    invalid = [value for value in values if value.startswith("-")]
    if invalid:
        raise DependencyPoolError(
            "unsupported",
            f"{ecosystem} dependency declarations must be package requirements, not package-manager options: {', '.join(invalid)}",
        )


def _wheel_metadata(filename: str) -> dict[str, str]:
    try:
        name, version, build, tags = parse_wheel_filename(filename)
    except InvalidWheelFilename as exc:
        raise DependencyPoolError("unsupported", f"invalid Python wheel filename {filename!r}: {exc}") from exc
    return {
        "name": canonicalize_name(name),
        "version": str(version),
        "build": ".".join(str(part) for part in build),
        "tags": ",".join(sorted(str(tag) for tag in tags)),
    }


def _empty_python_artifact_index() -> dict[str, Any]:
    return {
        "version": "python_artifact_index.v1",
        "artifacts": {},
        "distributions": {},
    }


def _distribution_index(artifacts: dict[str, dict[str, Any]]) -> dict[str, dict[str, list[str]]]:
    result: dict[str, dict[str, list[str]]] = {}
    for digest, record in artifacts.items():
        name = record.get("name")
        version = record.get("version")
        if not isinstance(name, str) or not isinstance(version, str):
            continue
        result.setdefault(name, {}).setdefault(version, []).append(digest)
    for versions in result.values():
        for digests in versions.values():
            digests.sort()
    return result


def _safe_extract_wheel(wheel: Path, destination: Path) -> None:
    with zipfile.ZipFile(wheel) as archive:
        for member in archive.infolist():
            relative = _safe_relative_path(member.filename)
            target = destination / relative
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)


def _safe_relative_path(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"unsafe dependency pool path: {value}")
    return path


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fingerprint(value: dict[str, Any]) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
