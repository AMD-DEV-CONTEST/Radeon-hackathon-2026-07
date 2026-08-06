from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

try:
    from .radeon_runtime_discovery import (
        discover_radeon_runtime,
        preflight_radeon_runtime,
    )
    from .rendering_engine import ExecutionPlan, ExecutionResult
except ImportError:
    from radeon_runtime_discovery import (
        discover_radeon_runtime,
        preflight_radeon_runtime,
    )
    from rendering_engine import ExecutionPlan, ExecutionResult


PACKAGE_SCHEMA = "aahj.radeon-cloud-execution-package/v1"
JOB_SCHEMA = "aahj.radeon-cloud-job/v1"
CLOUD_RESULT_SCHEMA = "aahj.radeon-cloud-result/v1"
MANIFEST_SCHEMA = "aahj.radeon-cloud-manifest/v1"
DEFAULT_OUTPUT_DIRECTORY = "outputs"
MAX_CAPTURE_BYTES = 1024 * 1024


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"missing JSON file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {path}: {exc}") from exc


def write_json(path: Path, value: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(value, indent=2, sort_keys=True) + "\n"
    path.write_text(rendered, encoding="utf-8")
    return path


def _required_text(name: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")
    return value.strip()


def _safe_relative_path(name: str, value: Any) -> str:
    text = _required_text(name, value)
    path = Path(text)
    if path.is_absolute() or ".." in path.parts or text in {".", ""}:
        raise ValueError(f"{name} must be a safe relative path")
    return path.as_posix()


def _string_mapping(name: str, value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    result: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not key:
            raise ValueError(f"{name} keys must be non-empty strings")
        if not isinstance(item, str):
            raise ValueError(f"{name} values must be strings")
        result[key] = item
    return dict(sorted(result.items()))


@dataclass(frozen=True)
class RadeonCloudJob:
    argv: tuple[str, ...]
    environment: Mapping[str, str]
    working_directory: str
    output_paths: tuple[str, ...]
    timeout_seconds: float
    schema_version: str = JOB_SCHEMA

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "RadeonCloudJob":
        if value.get("schema_version") != JOB_SCHEMA:
            raise ValueError(f"schema_version must be {JOB_SCHEMA}")
        raw_argv = value.get("argv")
        if (
            not isinstance(raw_argv, list)
            or not raw_argv
            or not all(isinstance(item, str) and item for item in raw_argv)
        ):
            raise ValueError("argv must be a non-empty array of strings")
        raw_outputs = value.get("output_paths")
        if (
            not isinstance(raw_outputs, list)
            or not raw_outputs
            or not all(isinstance(item, str) for item in raw_outputs)
        ):
            raise ValueError("output_paths must be a non-empty array")
        timeout = value.get("timeout_seconds", 3600)
        if (
            not isinstance(timeout, (int, float))
            or isinstance(timeout, bool)
            or timeout <= 0
        ):
            raise ValueError("timeout_seconds must be greater than zero")
        return cls(
            argv=tuple(raw_argv),
            environment=_string_mapping(
                "environment", value.get("environment", {})
            ),
            working_directory=_safe_relative_path(
                "working_directory",
                value.get("working_directory", "payload"),
            ),
            output_paths=tuple(
                _safe_relative_path("output_path", item)
                for item in raw_outputs
            ),
            timeout_seconds=float(timeout),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "argv": list(self.argv),
            "environment": dict(self.environment),
            "working_directory": self.working_directory,
            "output_paths": list(self.output_paths),
            "timeout_seconds": self.timeout_seconds,
        }

    @property
    def job_id(self) -> str:
        return sha256_bytes(canonical_json(self.as_dict()).encode("utf-8"))


@dataclass(frozen=True)
class PackageEntry:
    path: str
    sha256: str
    size_bytes: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
        }


def _normalized_tar_bytes(files: Mapping[str, bytes]) -> bytes:
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for name in sorted(files):
            data = files[name]
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o644
            info.mtime = 0
            info.uid = 0
            info.gid = 0
            info.uname = ""
            info.gname = ""
            archive.addfile(info, io.BytesIO(data))
    compressed = io.BytesIO()
    with gzip.GzipFile(fileobj=compressed, mode="wb", mtime=0) as stream:
        stream.write(raw.getvalue())
    return compressed.getvalue()


def build_cloud_package(
    *,
    execution_plan: ExecutionPlan,
    job: RadeonCloudJob,
    payload_files: Mapping[str, Path],
    destination: Path,
) -> Path:
    files: dict[str, bytes] = {
        "execution-plan.json": (
            json.dumps(execution_plan.as_dict(), indent=2, sort_keys=True) + "\n"
        ).encode("utf-8"),
        "job.json": (
            json.dumps(job.as_dict(), indent=2, sort_keys=True) + "\n"
        ).encode("utf-8"),
    }

    for package_path, source in sorted(payload_files.items()):
        safe_path = _safe_relative_path("payload path", package_path)
        if not safe_path.startswith("payload/"):
            raise ValueError("payload files must be stored under payload/")
        source = source.expanduser().resolve()
        if not source.is_file():
            raise ValueError(f"payload source is missing: {source}")
        if safe_path in files:
            raise ValueError(f"duplicate package path: {safe_path}")
        files[safe_path] = source.read_bytes()

    entries = tuple(
        PackageEntry(
            path=name,
            sha256=sha256_bytes(data),
            size_bytes=len(data),
        )
        for name, data in sorted(files.items())
    )
    manifest_without_id = {
        "schema_version": PACKAGE_SCHEMA,
        "plan_id": execution_plan.plan_id,
        "job_id": job.job_id,
        "entries": [entry.as_dict() for entry in entries],
    }
    package_id = sha256_bytes(
        canonical_json(manifest_without_id).encode("utf-8")
    )
    manifest = {**manifest_without_id, "package_id": package_id}
    files["manifest.json"] = (
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(_normalized_tar_bytes(files))
    return destination


def _safe_extract(package: Path, destination: Path) -> None:
    with tarfile.open(package, mode="r:gz") as archive:
        for member in archive.getmembers():
            path = Path(member.name)
            if (
                member.isdir()
                or path.is_absolute()
                or ".." in path.parts
                or not member.isfile()
            ):
                raise ValueError(f"unsafe package member: {member.name}")
        archive.extractall(destination, filter="data")


def verify_extracted_package(root: Path) -> Mapping[str, Any]:
    manifest = read_json(root / "manifest.json")
    if manifest.get("schema_version") != PACKAGE_SCHEMA:
        raise ValueError(f"manifest schema must be {PACKAGE_SCHEMA}")
    raw_entries = manifest.get("entries")
    if not isinstance(raw_entries, list):
        raise ValueError("manifest entries must be an array")

    expected_without_id = {
        "schema_version": manifest["schema_version"],
        "plan_id": manifest.get("plan_id"),
        "job_id": manifest.get("job_id"),
        "entries": raw_entries,
    }
    observed_package_id = sha256_bytes(
        canonical_json(expected_without_id).encode("utf-8")
    )
    if manifest.get("package_id") != observed_package_id:
        raise ValueError("package_id does not match manifest")

    declared = set()
    for item in raw_entries:
        if not isinstance(item, Mapping):
            raise ValueError("manifest entry must be an object")
        relative = _safe_relative_path("entry.path", item.get("path"))
        declared.add(relative)
        path = root / relative
        if not path.is_file():
            raise ValueError(f"package entry is missing: {relative}")
        if sha256_file(path) != item.get("sha256"):
            raise ValueError(f"package entry digest mismatch: {relative}")
        if path.stat().st_size != item.get("size_bytes"):
            raise ValueError(f"package entry size mismatch: {relative}")

    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.name != "manifest.json"
    }
    if actual != declared:
        raise ValueError("package contains undeclared or missing entries")
    return manifest


def inspect_cloud_package(package: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        _safe_extract(package, root)
        manifest = verify_extracted_package(root)
        plan = ExecutionPlan.from_mapping(read_json(root / "execution-plan.json"))
        job = RadeonCloudJob.from_mapping(read_json(root / "job.json"))
        if plan.plan_id != manifest.get("plan_id"):
            raise ValueError("plan_id does not match manifest")
        if job.job_id != manifest.get("job_id"):
            raise ValueError("job_id does not match manifest")
        return {
            "package_id": manifest["package_id"],
            "plan_id": plan.plan_id,
            "job_id": job.job_id,
            "entries": len(manifest["entries"]),
            "backend": plan.backend,
            "output_paths": list(job.output_paths),
        }


def _collect_output_files(
    root: Path, output_paths: Sequence[str]
) -> tuple[Path, ...]:
    discovered: set[Path] = set()
    for relative in output_paths:
        target = root / relative
        if target.is_file():
            discovered.add(target)
        elif target.is_dir():
            discovered.update(path for path in target.rglob("*") if path.is_file())
        else:
            raise RuntimeError(f"declared output is missing: {relative}")
    return tuple(sorted(discovered, key=lambda item: item.relative_to(root).as_posix()))


def execute_cloud_package(
    package: Path,
    *,
    result_directory: Path,
    require_radeon: bool = True,
) -> Path:
    result_directory = result_directory.expanduser().resolve()
    result_directory.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="aahj-radeon-cloud-") as temporary:
        root = Path(temporary)
        _safe_extract(package, root)
        manifest = verify_extracted_package(root)
        plan = ExecutionPlan.from_mapping(read_json(root / "execution-plan.json"))
        job = RadeonCloudJob.from_mapping(read_json(root / "job.json"))

        if plan.plan_id != manifest.get("plan_id"):
            raise ValueError("plan_id does not match manifest")
        if job.job_id != manifest.get("job_id"):
            raise ValueError("job_id does not match manifest")

        runtime_evidence: dict[str, Any] = {"required": require_radeon}
        if require_radeon:
            observation = discover_radeon_runtime()
            preflight = preflight_radeon_runtime(observation)
            runtime_evidence.update(
                {
                    "observation_id": observation.observation_id,
                    "preflight_id": preflight.as_dict()["preflight_id"],
                    "ready": preflight.ready,
                }
            )
            if not preflight.ready:
                failed = [
                    check.name
                    for check in preflight.checks
                    if check.required and not check.passed
                ]
                raise RuntimeError(
                    "Radeon runtime preflight failed: " + ", ".join(failed)
                )

        workdir = (root / job.working_directory).resolve()
        if root not in workdir.parents and workdir != root:
            raise ValueError("working_directory escapes package root")
        if not workdir.is_dir():
            raise ValueError(
                f"working_directory does not exist: {job.working_directory}"
            )

        environment = os.environ.copy()
        environment.update(job.environment)
        environment.update(
            {
                "AAHJ_PLAN_ID": plan.plan_id,
                "AAHJ_PACKAGE_ID": manifest["package_id"],
                "AAHJ_RESULT_DIRECTORY": str(result_directory),
            }
        )

        started = time.monotonic()
        try:
            completed = subprocess.run(
                list(job.argv),
                cwd=workdir,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=job.timeout_seconds,
                check=False,
                start_new_session=True,
            )
            timed_out = False
        except subprocess.TimeoutExpired as exc:
            completed = None
            timed_out = True
            stdout = (exc.stdout or b"")[-MAX_CAPTURE_BYTES:]
            stderr = (exc.stderr or b"")[-MAX_CAPTURE_BYTES:]
        elapsed = time.monotonic() - started

        if completed is not None:
            stdout = completed.stdout[-MAX_CAPTURE_BYTES:]
            stderr = completed.stderr[-MAX_CAPTURE_BYTES:]
            return_code = completed.returncode
        else:
            return_code = None

        stdout_path = result_directory / "stdout.log"
        stderr_path = result_directory / "stderr.log"
        stdout_path.write_bytes(stdout)
        stderr_path.write_bytes(stderr)

        outputs = []
        status = "failed"
        error: dict[str, Any] | None = None
        if timed_out:
            error = {
                "code": "timeout",
                "message": f"job exceeded {job.timeout_seconds:g} seconds",
            }
        elif return_code != 0:
            error = {
                "code": "nonzero-exit",
                "message": f"job exited with code {return_code}",
            }
        else:
            files = _collect_output_files(root, job.output_paths)
            for source in files:
                relative = source.relative_to(root).as_posix()
                destination = result_directory / "artifacts" / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
                outputs.append(
                    {
                        "path": destination.relative_to(result_directory).as_posix(),
                        "source_path": relative,
                        "sha256": sha256_file(destination),
                        "size_bytes": destination.stat().st_size,
                    }
                )
            status = "succeeded"

        result = ExecutionResult(
            plan_id=plan.plan_id,
            status=status,
            outputs=tuple(outputs),
            evidence={
                "package_id": manifest["package_id"],
                "job_id": job.job_id,
                "runtime": runtime_evidence,
                "elapsed_seconds": round(elapsed, 6),
                "return_code": return_code,
                "stdout": {
                    "path": "stdout.log",
                    "sha256": sha256_file(stdout_path),
                },
                "stderr": {
                    "path": "stderr.log",
                    "sha256": sha256_file(stderr_path),
                },
            },
            error=error,
        )
        payload = {
            "schema_version": CLOUD_RESULT_SCHEMA,
            "package_id": manifest["package_id"],
            "job_id": job.job_id,
            "execution_result": result.as_dict(),
            "result_id": result.result_id,
        }
        return write_json(result_directory / "result.json", payload)


def verify_cloud_result(
    result_file: Path,
    *,
    expected_plan_id: str | None = None,
    result_root: Path | None = None,
) -> ExecutionResult:
    payload = read_json(result_file)
    if payload.get("schema_version") != CLOUD_RESULT_SCHEMA:
        raise ValueError(f"schema_version must be {CLOUD_RESULT_SCHEMA}")
    result = ExecutionResult.from_mapping(payload.get("execution_result", {}))
    if payload.get("result_id") != result.result_id:
        raise ValueError("result_id does not match execution result")
    if expected_plan_id is not None and result.plan_id != expected_plan_id:
        raise ValueError("result belongs to a different execution plan")

    root = (
        result_root.expanduser().resolve()
        if result_root is not None
        else result_file.expanduser().resolve().parent
    )
    for output in result.outputs:
        relative = _safe_relative_path("output.path", output.get("path"))
        path = root / relative
        if not path.is_file():
            raise ValueError(f"result artifact is missing: {relative}")
        if sha256_file(path) != output.get("sha256"):
            raise ValueError(f"result artifact digest mismatch: {relative}")
        if path.stat().st_size != output.get("size_bytes"):
            raise ValueError(f"result artifact size mismatch: {relative}")
    for name in ("stdout", "stderr"):
        diagnostic = result.evidence.get(name)
        if diagnostic is None:
            continue
        if not isinstance(diagnostic, Mapping):
            raise ValueError(f"result {name} evidence must be an object")
        relative = _safe_relative_path(
            f"evidence.{name}.path", diagnostic.get("path")
        )
        path = root / relative
        if not path.is_file():
            raise ValueError(f"result diagnostic is missing: {relative}")
        if sha256_file(path) != diagnostic.get("sha256"):
            raise ValueError(f"result diagnostic digest mismatch: {relative}")
    return result
