from __future__ import annotations

import hashlib
import json
import os
import queue
import shutil
import struct
import subprocess
import threading
import time
import urllib.request
from contextlib import AbstractContextManager
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Callable, Protocol
from uuid import uuid4
from zipfile import ZipFile, ZipInfo

from ..config import AppPaths, package_root
from ..exceptions import ValidationError
from ..release_config import ReleaseConfig, load_release_config


NATIVE_OCR_PROTOCOL_VERSION = 2
RUNTIME_MANIFEST_SCHEMA_VERSION = 1
BUNDLE_CATALOG_SCHEMA_VERSION = 1
MAX_STATUS_BYTES = 64 * 1024
MAX_PROTOCOL_MESSAGE_BYTES = 16 * 1024 * 1024
PROTOCOL_POLL_INTERVAL_SECONDS = 0.05
PROCESS_TERMINATE_GRACE_SECONDS = 1.0
_SHA256_CHARS = frozenset("0123456789abcdef")
_RUNTIME_MANIFEST_NAME = "runtime.json"
_ACTIVE_MANIFEST_NAME = "active.json"
_VERIFICATION_RECORD_NAME = "verification.json"
_CATALOG_RESOURCE_NAME = "runtime_catalog.json"
_VERIFICATION_SCHEMA_VERSION = 1
_VERIFICATION_MAX_AGE_SECONDS = 24 * 60 * 60
_CATALOG_OVERRIDE_ENV = "XENIX_KNOWLEDGE_OCR_CATALOG"
_LOCAL_ARTIFACT_OVERRIDE_ENV = "XENIX_KNOWLEDGE_OCR_ARTIFACT"


class PaddleOcrState(StrEnum):
    CHECKING = "checking"
    READY = "ready"
    NOT_INSTALLED = "not_installed"
    REPAIR_REQUIRED = "repair_required"
    INSTALLING = "installing"
    FAILED = "failed"


@dataclass(frozen=True)
class PaddleOcrStatus:
    state: PaddleOcrState
    reason_code: str | None = None
    runtime_id: str | None = None
    model_pack_id: str | None = None
    generation_id: str | None = None

    @property
    def installed(self) -> bool:
        return self.state in {PaddleOcrState.READY, PaddleOcrState.REPAIR_REQUIRED}

    @property
    def models_ready(self) -> bool:
        return self.state is PaddleOcrState.READY

    @property
    def detail(self) -> str | None:
        return self.reason_code


@dataclass(frozen=True)
class PaddleOcrBundleCatalog:
    artifact_name: str
    artifact_bytes: int
    artifact_sha256: str
    protocol_version: int
    runtime_id: str
    model_pack_id: str

    @classmethod
    def from_payload(cls, payload: object) -> PaddleOcrBundleCatalog:
        if not isinstance(payload, dict) or payload.keys() != {
            "schema_version",
            "artifact_name",
            "artifact_bytes",
            "artifact_sha256",
            "protocol_version",
            "runtime_id",
            "model_pack_id",
        }:
            raise ValueError("Native OCR catalog shape is invalid.")
        if payload.get("schema_version") != BUNDLE_CATALOG_SCHEMA_VERSION:
            raise ValueError("Native OCR catalog schema is incompatible.")
        artifact_name = _safe_file_name(payload.get("artifact_name"))
        artifact_bytes = _positive_int(payload.get("artifact_bytes"))
        artifact_sha256 = _sha256_text(payload.get("artifact_sha256"))
        protocol_version = _positive_int(payload.get("protocol_version"))
        if protocol_version != NATIVE_OCR_PROTOCOL_VERSION:
            raise ValueError("Native OCR protocol is incompatible.")
        runtime_id = _bounded_identity(payload.get("runtime_id"))
        model_pack_id = _bounded_identity(payload.get("model_pack_id"))
        return cls(
            artifact_name=artifact_name,
            artifact_bytes=artifact_bytes,
            artifact_sha256=artifact_sha256,
            protocol_version=protocol_version,
            runtime_id=runtime_id,
            model_pack_id=model_pack_id,
        )


class PaddleOcrBundleSource(Protocol):
    """Catalog authority plus one way to materialize its exact archive."""

    @property
    def catalog(self) -> PaddleOcrBundleCatalog: ...

    def ensure_available(self) -> None:
        """Fail with a safe typed error when this source cannot provide its archive."""

    def materialize(self, destination: Path) -> None:
        """Write the source artifact to one private destination."""


@dataclass(frozen=True)
class LocalPaddleOcrBundleSource:
    """A development or smoke archive paired with its generated catalog."""

    catalog: PaddleOcrBundleCatalog
    artifact_path: Path

    def ensure_available(self) -> None:
        source = self.artifact_path
        if source.name != self.catalog.artifact_name:
            raise ValidationError(
                "Local OCR bundle does not match its catalog.",
                error_code="knowledge_ocr_bundle_source_mismatch",
            )
        if not source.is_file():
            raise ValidationError(
                "Local OCR bundle is unavailable.",
                error_code="knowledge_ocr_bundle_source_unavailable",
            )

    def materialize(self, destination: Path) -> None:
        source = self.artifact_path
        self.ensure_available()
        try:
            with source.open("rb") as input_stream, destination.open("wb") as output:
                shutil.copyfileobj(input_stream, output, length=1024 * 1024)
                output.flush()
                os.fsync(output.fileno())
        except OSError as exc:
            destination.unlink(missing_ok=True)
            raise ValidationError(
                "Local OCR bundle is unavailable.",
                error_code="knowledge_ocr_bundle_source_unavailable",
            ) from exc


@dataclass(frozen=True)
class ReleasePaddleOcrBundleSource:
    """A catalog-owned archive resolved through the immutable release origin."""

    catalog: PaddleOcrBundleCatalog
    release_config: ReleaseConfig

    def _artifact_url(self) -> str:
        artifact_url = self.release_config.artifact_url(self.catalog.artifact_name)
        if not artifact_url:
            raise ValidationError(
                "Local OCR download is unavailable in this build.",
                error_code="knowledge_ocr_download_unavailable",
            )
        return artifact_url

    def ensure_available(self) -> None:
        self._artifact_url()

    def materialize(self, destination: Path) -> None:
        artifact_url = self._artifact_url()
        try:
            with urllib.request.urlopen(artifact_url, timeout=120) as response, destination.open(
                "wb"
            ) as output:
                shutil.copyfileobj(response, output, length=1024 * 1024)
                output.flush()
                os.fsync(output.fileno())
        except OSError as exc:
            destination.unlink(missing_ok=True)
            raise ValidationError(
                "Local OCR component could not be downloaded.",
                error_code="knowledge_ocr_download_failed",
            ) from exc


@dataclass(frozen=True)
class PaddleOcrRuntime:
    generation_id: str
    generation_path: Path
    executable_path: Path
    detection_model_path: Path
    recognition_model_path: Path
    runtime_id: str
    model_pack_id: str
    engine_version: str
    manifest_sha256: str

    @property
    def descriptor(self) -> PaddleOcrRuntimeDescriptor:
        return PaddleOcrRuntimeDescriptor(
            generation_id=self.generation_id,
            runtime_id=self.runtime_id,
            model_pack_id=self.model_pack_id,
            engine="paddle-inference",
            engine_version=self.engine_version,
            protocol_version=NATIVE_OCR_PROTOCOL_VERSION,
            manifest_sha256=self.manifest_sha256,
        )


@dataclass(frozen=True)
class PaddleOcrRuntimeDescriptor:
    generation_id: str
    runtime_id: str
    model_pack_id: str
    engine: str
    engine_version: str
    protocol_version: int
    manifest_sha256: str

    def to_payload(self) -> dict[str, object]:
        return {
            "generation_id": self.generation_id,
            "runtime_id": self.runtime_id,
            "model_pack_id": self.model_pack_id,
            "engine": self.engine,
            "engine_version": self.engine_version,
            "protocol_version": self.protocol_version,
            "manifest_sha256": self.manifest_sha256,
        }


class PaddleOcrDeploymentService:
    """Activate one immutable, verified native Paddle Inference generation."""

    def __init__(
        self,
        paths: AppPaths,
        *,
        bundle_source: PaddleOcrBundleSource | None = None,
        catalog: PaddleOcrBundleCatalog | None = None,
        release_config: ReleaseConfig | None = None,
    ) -> None:
        if bundle_source is not None and (catalog is not None or release_config is not None):
            raise ValueError("Bundle source cannot be combined with catalog or release configuration.")
        self._paths = paths
        self._root = paths.cache / "knowledge-ocr"
        self._bundles = self._root / "bundles"
        self._downloads = self._root / "downloads"
        self._staging = self._root / "staging"
        self._active_path = self._root / _ACTIVE_MANIFEST_NAME
        self._verification_path = self._root / _VERIFICATION_RECORD_NAME
        if bundle_source is not None:
            self._bundle_source = bundle_source
        elif catalog is not None:
            # Keep the former catalog/release injection seam as an explicit
            # release-source compatibility path for existing callers.
            self._bundle_source = ReleasePaddleOcrBundleSource(
                catalog,
                release_config or load_release_config(),
            )
        else:
            self._bundle_source = _load_default_bundle_source(
                release_config or load_release_config()
            )
        self._state_lock = threading.Lock()
        self._transient_status: PaddleOcrStatus | None = None

    @property
    def catalog(self) -> PaddleOcrBundleCatalog | None:
        source = self._bundle_source
        return source.catalog if source is not None else None

    @property
    def bundle_source(self) -> PaddleOcrBundleSource | None:
        return self._bundle_source

    def status_snapshot(self) -> PaddleOcrStatus:
        with self._state_lock:
            transient = self._transient_status
        if transient is not None:
            return transient
        try:
            runtime = self._resolve_active_runtime()
        except FileNotFoundError:
            return PaddleOcrStatus(PaddleOcrState.NOT_INSTALLED, "runtime_missing")
        except (OSError, TypeError, ValueError):
            return PaddleOcrStatus(PaddleOcrState.REPAIR_REQUIRED, "runtime_manifest_invalid")
        catalog = self.catalog
        if catalog is not None and (
            runtime.runtime_id != catalog.runtime_id
            or runtime.model_pack_id != catalog.model_pack_id
        ):
            return PaddleOcrStatus(
                PaddleOcrState.REPAIR_REQUIRED,
                "runtime_catalog_incompatible",
                runtime.runtime_id,
                runtime.model_pack_id,
                runtime.generation_id,
            )
        verification_reason = self._verification_reason(runtime)
        if verification_reason is not None:
            return PaddleOcrStatus(
                PaddleOcrState.CHECKING,
                verification_reason,
                runtime.runtime_id,
                runtime.model_pack_id,
                runtime.generation_id,
            )
        return PaddleOcrStatus(
            PaddleOcrState.READY,
            runtime_id=runtime.runtime_id,
            model_pack_id=runtime.model_pack_id,
            generation_id=runtime.generation_id,
        )

    def status(self) -> PaddleOcrStatus:
        """Compatibility alias for existing service consumers."""

        return self.status_snapshot()

    def install(self, progress: Callable[[str], None] | None = None) -> PaddleOcrStatus:
        source = self._bundle_source
        if source is None:
            raise ValidationError(
                "Local OCR is unavailable in this build.",
                error_code="knowledge_ocr_catalog_unavailable",
            )
        source.ensure_available()
        catalog = source.catalog
        report = progress or (lambda _phase: None)
        self._set_transient(PaddleOcrStatus(PaddleOcrState.INSTALLING, "starting"))
        staging_root = self._staging / uuid4().hex
        try:
            for directory in (self._root, self._bundles, self._downloads, self._staging):
                directory.mkdir(parents=True, exist_ok=True)
            report("downloading_bundle")
            archive = self._materialize_verified_bundle(source)
            report("extracting_bundle")
            extracted = staging_root / "extracted"
            extracted.mkdir(parents=True)
            _safe_extract_zip(archive, extracted)
            candidate = _single_bundle_root(extracted)
            report("verifying_bundle")
            runtime = self._runtime_from_generation(
                candidate,
                generation_id=_generation_id(catalog),
                expected_catalog=catalog,
                verify_all_files=True,
            )
            generation_path = self._bundles / runtime.generation_id
            if generation_path.exists():
                _remove_private_tree(generation_path, root=self._bundles)
            os.replace(candidate, generation_path)
            activated = self._runtime_from_generation(
                generation_path,
                generation_id=runtime.generation_id,
                expected_catalog=catalog,
                verify_all_files=False,
            )
            report("self_testing")
            try:
                # Paddle resolves model members from their final filesystem path.
                # A staging-path self-test cannot prove that the activated Windows
                # path remains usable (notably around native path-length limits).
                self._self_test(activated)
            except Exception:
                _remove_private_tree(generation_path, root=self._bundles)
                raise
            report("activating_bundle")
            _write_json_atomic(
                self._active_path,
                {
                    "schema_version": 1,
                    "generation_id": activated.generation_id,
                    "runtime_id": activated.runtime_id,
                    "model_pack_id": activated.model_pack_id,
                    "manifest_sha256": activated.manifest_sha256,
                    "artifact_sha256": catalog.artifact_sha256,
                },
            )
            self._write_verification_record(activated)
            status = PaddleOcrStatus(
                PaddleOcrState.READY,
                runtime_id=activated.runtime_id,
                model_pack_id=activated.model_pack_id,
                generation_id=activated.generation_id,
            )
            report("ready")
            return status
        except ValidationError:
            self._set_transient(PaddleOcrStatus(PaddleOcrState.FAILED, "setup_failed"))
            raise
        except Exception as exc:
            self._set_transient(PaddleOcrStatus(PaddleOcrState.FAILED, "setup_failed"))
            raise ValidationError(
                "Local OCR setup failed.",
                error_code="knowledge_ocr_setup_failed",
            ) from exc
        finally:
            if staging_root.exists():
                _remove_private_tree(staging_root, root=self._staging)
            self._clear_transient_if(PaddleOcrState.INSTALLING)

    def repair(self, progress: Callable[[str], None] | None = None) -> PaddleOcrStatus:
        return self.install(progress)

    def verify_active(self) -> PaddleOcrStatus:
        self._set_transient(PaddleOcrStatus(PaddleOcrState.CHECKING, "verifying"))
        try:
            runtime = self._resolve_active_runtime(verify_all_files=True)
            self._self_test(runtime)
            self._write_verification_record(runtime)
            return PaddleOcrStatus(
                PaddleOcrState.READY,
                runtime_id=runtime.runtime_id,
                model_pack_id=runtime.model_pack_id,
                generation_id=runtime.generation_id,
            )
        except FileNotFoundError:
            return PaddleOcrStatus(PaddleOcrState.NOT_INSTALLED, "runtime_missing")
        except Exception:
            return PaddleOcrStatus(PaddleOcrState.REPAIR_REQUIRED, "verification_failed")
        finally:
            self._clear_transient_if(PaddleOcrState.CHECKING)

    def open_runtime(self) -> PaddleOcrRuntime:
        try:
            runtime = self._resolve_active_runtime()
        except FileNotFoundError as exc:
            raise ValidationError(
                "Local OCR is not installed.",
                error_code="knowledge_ocr_not_installed",
            ) from exc
        except (OSError, TypeError, ValueError) as exc:
            raise ValidationError(
                "Local OCR requires repair.",
                error_code="knowledge_ocr_repair_required",
            ) from exc
        if self._verification_reason(runtime) is not None:
            raise ValidationError(
                "Local OCR verification is required.",
                error_code="knowledge_ocr_verification_required",
                retryable=True,
            )
        return runtime

    def _verification_reason(self, runtime: PaddleOcrRuntime) -> str | None:
        try:
            payload = _bounded_json_file(self._verification_path)
        except (FileNotFoundError, OSError, TypeError, ValueError):
            return "verification_required"
        expected = {
            "schema_version",
            "generation_id",
            "runtime_id",
            "model_pack_id",
            "engine_version",
            "protocol_version",
            "manifest_sha256",
            "verified_at",
        }
        if not isinstance(payload, dict) or payload.keys() != expected:
            return "verification_required"
        verified_at = payload.get("verified_at")
        if type(verified_at) not in {int, float} or float(verified_at) <= 0:
            return "verification_required"
        if time.time() - float(verified_at) > _VERIFICATION_MAX_AGE_SECONDS:
            return "verification_stale"
        if (
            payload.get("schema_version") != _VERIFICATION_SCHEMA_VERSION
            or payload.get("generation_id") != runtime.generation_id
            or payload.get("runtime_id") != runtime.runtime_id
            or payload.get("model_pack_id") != runtime.model_pack_id
            or payload.get("engine_version") != runtime.engine_version
            or payload.get("protocol_version") != NATIVE_OCR_PROTOCOL_VERSION
            or payload.get("manifest_sha256") != runtime.manifest_sha256
        ):
            return "verification_required"
        return None

    def _write_verification_record(self, runtime: PaddleOcrRuntime) -> None:
        _write_json_atomic(
            self._verification_path,
            {
                "schema_version": _VERIFICATION_SCHEMA_VERSION,
                "generation_id": runtime.generation_id,
                "runtime_id": runtime.runtime_id,
                "model_pack_id": runtime.model_pack_id,
                "engine_version": runtime.engine_version,
                "protocol_version": NATIVE_OCR_PROTOCOL_VERSION,
                "manifest_sha256": runtime.manifest_sha256,
                "verified_at": time.time(),
            },
        )

    def _set_transient(self, status: PaddleOcrStatus | None) -> None:
        with self._state_lock:
            self._transient_status = status

    def _clear_transient_if(self, state: PaddleOcrState) -> None:
        with self._state_lock:
            if self._transient_status is not None and self._transient_status.state is state:
                self._transient_status = None

    def _materialize_verified_bundle(
        self,
        source: PaddleOcrBundleSource,
    ) -> Path:
        catalog = source.catalog
        source.ensure_available()
        target = self._downloads / catalog.artifact_name
        if _matches_catalog_artifact(target, catalog):
            return target
        partial = target.with_suffix(target.suffix + ".part")
        partial.unlink(missing_ok=True)
        try:
            source.materialize(partial)
            if not _matches_catalog_artifact(partial, catalog):
                raise ValidationError(
                    "Local OCR bundle failed integrity verification.",
                    error_code="knowledge_ocr_bundle_integrity_failed",
                )
            os.replace(partial, target)
        except Exception:
            partial.unlink(missing_ok=True)
            raise
        return target

    def _resolve_active_runtime(self, *, verify_all_files: bool = False) -> PaddleOcrRuntime:
        if not self._active_path.is_file():
            raise FileNotFoundError(self._active_path)
        active = _bounded_json_file(self._active_path)
        if not isinstance(active, dict) or active.keys() != {
            "schema_version",
            "generation_id",
            "runtime_id",
            "model_pack_id",
            "manifest_sha256",
            "artifact_sha256",
        }:
            raise ValueError("Active native OCR pointer is invalid.")
        if active.get("schema_version") != 1:
            raise ValueError("Active native OCR pointer is incompatible.")
        generation_id = _bounded_identity(active.get("generation_id"))
        runtime = self._runtime_from_generation(
            self._bundles / generation_id,
            generation_id=generation_id,
            expected_catalog=None,
            verify_all_files=verify_all_files,
        )
        if (
            runtime.runtime_id != active.get("runtime_id")
            or runtime.model_pack_id != active.get("model_pack_id")
            or runtime.manifest_sha256 != active.get("manifest_sha256")
            or not _is_sha256(active.get("artifact_sha256"))
        ):
            raise ValueError("Active native OCR identity is inconsistent.")
        return runtime

    def _runtime_from_generation(
        self,
        generation_path: Path,
        *,
        generation_id: str,
        expected_catalog: PaddleOcrBundleCatalog | None,
        verify_all_files: bool,
    ) -> PaddleOcrRuntime:
        manifest_path = generation_path / _RUNTIME_MANIFEST_NAME
        payload = _bounded_json_file(manifest_path, max_bytes=MAX_STATUS_BYTES)
        manifest = _validate_runtime_manifest(payload)
        manifest_sha256 = _sha256(manifest_path)
        if expected_catalog is not None and (
            manifest["protocol_version"] != expected_catalog.protocol_version
            or manifest["runtime_id"] != expected_catalog.runtime_id
            or manifest["model_pack_id"] != expected_catalog.model_pack_id
        ):
            raise ValueError("Native OCR bundle identity does not match its catalog.")
        executable = _resolve_member(generation_path, manifest["executable"])
        detection = _resolve_member(generation_path, manifest["models"]["detection"])
        recognition = _resolve_member(generation_path, manifest["models"]["recognition"])
        if not executable.is_file() or not detection.is_dir() or not recognition.is_dir():
            raise ValueError("Native OCR bundle is incomplete.")
        if verify_all_files:
            _verify_runtime_files(generation_path, manifest)
        return PaddleOcrRuntime(
            generation_id=generation_id,
            generation_path=generation_path,
            executable_path=executable,
            detection_model_path=detection,
            recognition_model_path=recognition,
            runtime_id=manifest["runtime_id"],
            model_pack_id=manifest["model_pack_id"],
            engine_version=manifest["engine_version"],
            manifest_sha256=manifest_sha256,
        )

    def _self_test(self, runtime: PaddleOcrRuntime) -> None:
        log_path = self._staging / f"self-test-{uuid4().hex}.log"
        succeeded = False
        try:
            with PaddleOcrSession(runtime, allowed_root=runtime.generation_path, log_path=log_path) as session:
                result = session.request("self_test", {}, timeout=120)
            if not isinstance(result, dict) or result.get("success") is not True:
                raise ValidationError(
                    "Local OCR self-test failed.",
                    error_code="knowledge_ocr_self_test_failed",
                )
            succeeded = True
        finally:
            if succeeded:
                log_path.unlink(missing_ok=True)


class PaddleOcrSession(AbstractContextManager["PaddleOcrSession"]):
    """One bounded stdio session owning one native model initialization."""

    def __init__(
        self,
        runtime: PaddleOcrRuntime,
        *,
        allowed_root: Path,
        log_path: Path,
    ) -> None:
        self._runtime = runtime
        self._allowed_root = allowed_root.resolve()
        self._log_path = log_path
        self._process: subprocess.Popen[bytes] | None = None
        self._stderr = None
        self._request_lock = threading.Lock()

    @property
    def pid(self) -> int | None:
        return self._process.pid if self._process is not None else None

    @property
    def runtime_descriptor(self) -> PaddleOcrRuntimeDescriptor:
        return self._runtime.descriptor

    def __enter__(self) -> PaddleOcrSession:
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        self._stderr = self._log_path.open("ab", buffering=0)
        try:
            self._process = subprocess.Popen(
                [str(self._runtime.executable_path), "--stdio"],
                cwd=self._runtime.generation_path,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=self._stderr,
                creationflags=_no_console_creationflags(),
            )
            version = self.request("version", {}, timeout=10)
            if (
                not isinstance(version, dict)
                or version.get("protocol_version") != NATIVE_OCR_PROTOCOL_VERSION
                or version.get("runtime_id") != self._runtime.runtime_id
            ):
                raise ValidationError(
                    "Local OCR worker is incompatible.",
                    error_code="knowledge_ocr_worker_incompatible",
                )
            initialized = self.request(
                "initialize",
                {
                    "model_pack_id": self._runtime.model_pack_id,
                    "detection_model_path": str(self._runtime.detection_model_path),
                    "recognition_model_path": str(self._runtime.recognition_model_path),
                },
                timeout=120,
            )
            if not isinstance(initialized, dict) or initialized.get("initialized") is not True:
                raise ValidationError(
                    "Local OCR models could not be initialized.",
                    error_code="knowledge_ocr_initialize_failed",
                )
            return self
        except BaseException:
            self.close()
            raise

    def __exit__(self, exc_type, exc, traceback) -> bool:
        if exc_type is None and self._process is not None and self._process.poll() is None:
            try:
                self.request("shutdown", {}, timeout=5)
            except Exception:
                pass
        self.close()
        return False

    def recognize(
        self,
        image_path: Path,
        *,
        output_path: Path | None = None,
        timeout: int = 300,
    ) -> dict[str, object]:
        image = image_path.resolve()
        try:
            image.relative_to(self._allowed_root)
        except ValueError as exc:
            raise ValidationError(
                "Local OCR input is outside the import staging area.",
                error_code="knowledge_ocr_input_outside_staging",
            ) from exc
        result = self.request(
            "recognize",
            {"image_path": str(image)},
            timeout=timeout,
        )
        payload = _normalized_ocr_result(result)
        if output_path is not None:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
        return payload

    def request(
        self,
        operation: str,
        arguments: dict[str, object],
        *,
        timeout: int,
    ) -> object:
        process = self._process
        if process is None or process.stdin is None or process.stdout is None:
            raise ValidationError(
                "Local OCR worker is not running.",
                error_code="knowledge_ocr_worker_unavailable",
            )
        request_id = uuid4().hex
        message = {
            "protocol_version": NATIVE_OCR_PROTOCOL_VERSION,
            "request_id": request_id,
            "operation": operation,
            "arguments": arguments,
        }
        with self._request_lock:
            _write_frame(process.stdin, message)
            response = _read_frame_with_poll(
                process,
                timeout=timeout,
            )
        if (
            not isinstance(response, dict)
            or response.get("protocol_version") != NATIVE_OCR_PROTOCOL_VERSION
            or response.get("request_id") != request_id
            or type(response.get("ok")) is not bool
        ):
            raise ValidationError(
                "Local OCR worker returned an invalid response.",
                error_code="knowledge_ocr_response_invalid",
            )
        if response["ok"] is not True:
            reason_code = response.get("reason_code")
            if not isinstance(reason_code, str) or not reason_code.startswith("knowledge_ocr_"):
                reason_code = "knowledge_ocr_worker_failed"
            raise ValidationError(
                "Local OCR operation failed.",
                error_code=reason_code,
                retryable=True,
            )
        if response.keys() != {"protocol_version", "request_id", "ok", "result"}:
            raise ValidationError(
                "Local OCR worker returned an invalid response.",
                error_code="knowledge_ocr_response_invalid",
            )
        return response["result"]

    def close(self) -> None:
        process = self._process
        self._process = None
        if process is not None:
            _stop_worker_process(process)
        if self._stderr is not None:
            try:
                self._stderr.close()
            except OSError:
                pass
            self._stderr = None


class PaddleOcrService:
    def __init__(self, deployment: PaddleOcrDeploymentService) -> None:
        self._deployment = deployment

    def is_ready(self) -> bool:
        return self._deployment.status_snapshot().state is PaddleOcrState.READY

    def runtime_descriptor(self) -> PaddleOcrRuntimeDescriptor:
        return self._deployment.open_runtime().descriptor

    def open_session(
        self,
        *,
        allowed_root: Path,
        log_path: Path,
    ) -> PaddleOcrSession:
        return PaddleOcrSession(
            self._deployment.open_runtime(),
            allowed_root=allowed_root,
            log_path=log_path,
        )

    def recognize(
        self,
        image_path: Path,
        *,
        output_path: Path,
        timeout: int = 300,
    ) -> dict[str, object]:
        with self.open_session(
            allowed_root=image_path.resolve().parent,
            log_path=output_path.with_suffix(".ocr.log"),
        ) as session:
            payload = session.recognize(
                image_path,
                output_path=output_path,
                timeout=timeout,
            )
        return payload


def _load_default_bundle_source(
    release_config: ReleaseConfig,
) -> PaddleOcrBundleSource | None:
    catalog = _load_packaged_catalog()
    if catalog is None:
        return None
    artifact_override = os.environ.get(_LOCAL_ARTIFACT_OVERRIDE_ENV, "").strip()
    if artifact_override:
        return LocalPaddleOcrBundleSource(catalog, Path(artifact_override))
    return ReleasePaddleOcrBundleSource(catalog, release_config)


def _load_packaged_catalog() -> PaddleOcrBundleCatalog | None:
    override = os.environ.get(_CATALOG_OVERRIDE_ENV, "").strip()
    path = Path(override) if override else package_root() / "resources" / "knowledge_ocr" / _CATALOG_RESOURCE_NAME
    if not path.is_file():
        return None
    try:
        return PaddleOcrBundleCatalog.from_payload(_bounded_json_file(path))
    except (OSError, TypeError, ValueError):
        return None


def _matches_catalog_artifact(path: Path, catalog: PaddleOcrBundleCatalog) -> bool:
    try:
        return (
            path.is_file()
            and path.stat().st_size == catalog.artifact_bytes
            and _sha256(path) == catalog.artifact_sha256
        )
    except OSError:
        return False


def _validate_runtime_manifest(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict) or payload.keys() != {
        "schema_version",
        "protocol_version",
        "runtime_id",
        "model_pack_id",
        "engine",
        "engine_version",
        "architecture",
        "executable",
        "models",
        "files",
    }:
        raise ValueError("Native OCR runtime manifest shape is invalid.")
    if payload.get("schema_version") != RUNTIME_MANIFEST_SCHEMA_VERSION:
        raise ValueError("Native OCR runtime manifest schema is incompatible.")
    if payload.get("protocol_version") != NATIVE_OCR_PROTOCOL_VERSION:
        raise ValueError("Native OCR runtime protocol is incompatible.")
    if payload.get("engine") != "paddle-inference" or payload.get("architecture") != "windows-x86_64":
        raise ValueError("Native OCR runtime identity is incompatible.")
    _bounded_identity(payload.get("runtime_id"))
    _bounded_identity(payload.get("model_pack_id"))
    _bounded_identity(payload.get("engine_version"))
    _relative_member(payload.get("executable"))
    models = payload.get("models")
    if not isinstance(models, dict) or models.keys() != {"detection", "recognition"}:
        raise ValueError("Native OCR model manifest is invalid.")
    _relative_member(models.get("detection"))
    _relative_member(models.get("recognition"))
    files = payload.get("files")
    if not isinstance(files, list) or not files or len(files) > 512:
        raise ValueError("Native OCR file manifest is invalid.")
    seen: set[str] = set()
    for item in files:
        if not isinstance(item, dict) or item.keys() != {"path", "bytes", "sha256"}:
            raise ValueError("Native OCR file manifest entry is invalid.")
        relative = _relative_member(item.get("path"))
        if relative == _RUNTIME_MANIFEST_NAME or relative in seen:
            raise ValueError("Native OCR file manifest contains a duplicate.")
        seen.add(relative)
        _positive_int(item.get("bytes"), allow_zero=True)
        _sha256_text(item.get("sha256"))
    if str(payload["executable"]) not in seen:
        raise ValueError("Native OCR executable is absent from the file manifest.")
    for model_path in models.values():
        prefix = f"{model_path.rstrip('/')}/"
        if not any(path.startswith(prefix) for path in seen):
            raise ValueError("Native OCR model files are absent from the manifest.")
    return payload


def _verify_runtime_files(root: Path, manifest: dict[str, object]) -> None:
    expected = {_RUNTIME_MANIFEST_NAME}
    for item in manifest["files"]:
        relative = str(item["path"])
        path = _resolve_member(root, relative)
        if (
            not path.is_file()
            or path.is_symlink()
            or path.stat().st_size != item["bytes"]
            or _sha256(path) != item["sha256"]
        ):
            raise ValueError("Native OCR runtime file integrity check failed.")
        expected.add(relative)
    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
    }
    if actual != expected:
        raise ValueError("Native OCR runtime contains unexpected files.")


def _normalized_ocr_result(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or value.keys() != {"regions"}:
        raise ValidationError(
            "Local OCR returned an invalid result.",
            error_code="knowledge_ocr_result_invalid",
        )
    regions = value.get("regions")
    if not isinstance(regions, list) or len(regions) > 20_000:
        raise ValidationError(
            "Local OCR returned an invalid result.",
            error_code="knowledge_ocr_result_invalid",
        )
    normalized: list[dict[str, object]] = []
    for region in regions:
        if not isinstance(region, dict) or region.keys() != {"text", "confidence", "polygon"}:
            raise ValidationError(
                "Local OCR returned an invalid result.",
                error_code="knowledge_ocr_result_invalid",
            )
        text = region.get("text")
        confidence = region.get("confidence")
        polygon = region.get("polygon")
        if (
            not isinstance(text, str)
            or len(text) > 32_000
            or not isinstance(confidence, (int, float))
            or isinstance(confidence, bool)
            or not 0 <= float(confidence) <= 1
            or not isinstance(polygon, list)
            or len(polygon) != 4
            or any(
                not isinstance(point, list)
                or len(point) != 2
                or any(not isinstance(coordinate, (int, float)) or isinstance(coordinate, bool) for coordinate in point)
                for point in polygon
            )
        ):
            raise ValidationError(
                "Local OCR returned an invalid result.",
                error_code="knowledge_ocr_result_invalid",
            )
        normalized.append(
            {
                "text": text,
                "confidence": float(confidence),
                "polygon": [[float(value) for value in point] for point in polygon],
            }
        )
    return {"protocol": NATIVE_OCR_PROTOCOL_VERSION, "pages": [{"regions": normalized}]}


def _write_frame(stream, payload: dict[str, object]) -> None:
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if not data or len(data) > MAX_PROTOCOL_MESSAGE_BYTES:
        raise ValidationError(
            "Local OCR request is outside the supported bound.",
            error_code="knowledge_ocr_request_too_large",
        )
    stream.write(struct.pack(">I", len(data)))
    stream.write(data)
    stream.flush()


def _read_frame_with_poll(
    process: subprocess.Popen[bytes],
    *,
    timeout: int,
) -> object:
    assert process.stdout is not None
    result_queue: queue.Queue[tuple[object | None, BaseException | None]] = queue.Queue(maxsize=1)

    def read() -> None:
        try:
            result_queue.put((_read_frame(process.stdout), None))
        except BaseException as exc:
            result_queue.put((None, exc))

    threading.Thread(target=read, name="xenix-ocr-response", daemon=True).start()
    deadline = time.monotonic() + max(1, timeout)
    while True:
        if process.poll() is not None and result_queue.empty():
            raise ValidationError(
                "Local OCR worker exited unexpectedly.",
                error_code="knowledge_ocr_worker_crashed",
                retryable=True,
            )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ValidationError(
                "Local OCR operation timed out.",
                error_code="knowledge_ocr_timeout",
                retryable=True,
            )
        try:
            value, error = result_queue.get(timeout=min(PROTOCOL_POLL_INTERVAL_SECONDS, remaining))
        except queue.Empty:
            continue
        if error is not None:
            raise ValidationError(
                "Local OCR worker returned an unreadable response.",
                error_code="knowledge_ocr_response_invalid",
            ) from error
        return value


def _read_frame(stream) -> object:
    header = _read_exact(stream, 4)
    length = struct.unpack(">I", header)[0]
    if length < 2 or length > MAX_PROTOCOL_MESSAGE_BYTES:
        raise ValueError("Native OCR response length is invalid.")
    return _bounded_json_object(_read_exact(stream, length).decode("utf-8"), max_bytes=length)


def _read_exact(stream, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = stream.read(remaining)
        if not chunk:
            raise EOFError("Native OCR worker closed its response stream.")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _stop_worker_process(process: subprocess.Popen[bytes]) -> None:
    try:
        if process.stdin is not None:
            process.stdin.close()
    except OSError:
        pass
    if process.poll() is None:
        try:
            process.terminate()
        except OSError:
            pass
    try:
        process.wait(timeout=PROCESS_TERMINATE_GRACE_SECONDS)
    except (OSError, subprocess.TimeoutExpired):
        if process.poll() is None:
            try:
                process.kill()
            except OSError:
                pass
        try:
            process.wait(timeout=PROCESS_TERMINATE_GRACE_SECONDS)
        except (OSError, subprocess.TimeoutExpired):
            pass
    for stream in (process.stdin, process.stdout):
        if stream is not None:
            try:
                stream.close()
            except OSError:
                pass


def _safe_extract_zip(archive: Path, destination: Path) -> None:
    root = destination.resolve()
    with ZipFile(archive) as package:
        if len(package.infolist()) > 1024:
            raise ValidationError(
                "Downloaded local OCR bundle contains too many entries.",
                error_code="knowledge_ocr_bundle_invalid",
            )
        for member in package.infolist():
            _validate_zip_member(member)
            target = (destination / member.filename).resolve()
            try:
                target.relative_to(root)
            except ValueError as exc:
                raise ValidationError(
                    "Downloaded local OCR bundle contains an unsafe path.",
                    error_code="knowledge_ocr_bundle_invalid",
                ) from exc
        package.extractall(destination)


def _validate_zip_member(member: ZipInfo) -> None:
    _relative_member(member.filename.rstrip("/"))
    unix_mode = member.external_attr >> 16
    if unix_mode and (unix_mode & 0o170000) == 0o120000:
        raise ValidationError(
            "Downloaded local OCR bundle contains a symbolic link.",
            error_code="knowledge_ocr_bundle_invalid",
        )


def _single_bundle_root(extracted: Path) -> Path:
    entries = list(extracted.iterdir())
    if len(entries) != 1 or not entries[0].is_dir() or entries[0].is_symlink():
        raise ValueError("Native OCR archive must contain one bundle directory.")
    return entries[0]


def _bounded_json_file(path: Path, *, max_bytes: int = MAX_STATUS_BYTES) -> object:
    with path.open("rb") as source:
        raw = source.read(max_bytes + 1)
    if not raw or len(raw) > max_bytes:
        raise ValueError("JSON file is outside the supported bound.")
    return _bounded_json_object(raw.decode("utf-8"), max_bytes=max_bytes)


def _bounded_json_object(raw: object, *, max_bytes: int) -> object:
    if not isinstance(raw, str) or not raw or len(raw.encode("utf-8")) > max_bytes:
        raise ValueError("JSON payload is outside the supported bound.")

    def reject_constant(value: str) -> None:
        raise ValueError(f"Unsupported JSON constant: {value}")

    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON keys are unsupported.")
            result[key] = value
        return result

    return json.loads(raw, parse_constant=reject_constant, object_pairs_hook=reject_duplicates)


def _write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as output:
        json.dump(payload, output, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, path)


def _resolve_member(root: Path, value: object) -> Path:
    relative = _relative_member(value)
    target = (root / Path(*PurePosixPath(relative).parts)).resolve()
    target.relative_to(root.resolve())
    return target


def _relative_member(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 512 or "\\" in value:
        raise ValueError("Native OCR member path is invalid.")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("Native OCR member path is invalid.")
    return path.as_posix()


def _safe_file_name(value: object) -> str:
    name = _bounded_identity(value)
    if Path(name).name != name or "/" in name or "\\" in name:
        raise ValueError("Native OCR artifact name is invalid.")
    return name


def _bounded_identity(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("Native OCR identity is invalid.")
    cleaned = value.strip()
    if not cleaned or len(cleaned) > 160 or any(ord(char) < 0x20 for char in cleaned):
        raise ValueError("Native OCR identity is invalid.")
    return cleaned


def _positive_int(value: object, *, allow_zero: bool = False) -> int:
    minimum = 0 if allow_zero else 1
    if type(value) is not int or value < minimum:
        raise ValueError("Native OCR numeric value is invalid.")
    return value


def _sha256_text(value: object) -> str:
    if not _is_sha256(value):
        raise ValueError("Native OCR digest is invalid.")
    return str(value)


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value) <= _SHA256_CHARS


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _generation_id(catalog: PaddleOcrBundleCatalog) -> str:
    identity = json.dumps(
        {
            "schema_version": 1,
            "runtime_id": catalog.runtime_id,
            "model_pack_id": catalog.model_pack_id,
            "artifact_sha256": catalog.artifact_sha256,
        },
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    return f"ocr-{hashlib.sha256(identity).hexdigest()[:32]}"


def _remove_private_tree(path: Path, *, root: Path) -> None:
    resolved = path.resolve()
    resolved.relative_to(root.resolve())
    if resolved == root.resolve():
        raise ValueError("Refusing to remove the native OCR root.")
    shutil.rmtree(resolved)


def _no_console_creationflags() -> int:
    if os.name != "nt":
        return 0
    return int(getattr(subprocess, "CREATE_NO_WINDOW", 0))


__all__ = [
    "LocalPaddleOcrBundleSource",
    "NATIVE_OCR_PROTOCOL_VERSION",
    "PaddleOcrBundleCatalog",
    "PaddleOcrBundleSource",
    "PaddleOcrDeploymentService",
    "PaddleOcrRuntime",
    "PaddleOcrRuntimeDescriptor",
    "PaddleOcrService",
    "PaddleOcrSession",
    "PaddleOcrState",
    "PaddleOcrStatus",
    "ReleasePaddleOcrBundleSource",
]
