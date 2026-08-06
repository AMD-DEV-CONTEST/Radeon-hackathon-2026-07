from __future__ import annotations

import copy
import hashlib
import json
import mimetypes
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Mapping, Sequence

from .files import atomic_write_bytes, atomic_write_text, sha256_file


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_REVISION = re.compile(r"^[0-9a-f]{40}$")
_SAFE_EXTENSION = frozenset(
    {".png", ".jpg", ".jpeg", ".webp", ".mp4", ".webm", ".wav", ".flac", ".mp3"}
)


class ComfyProductionError(ValueError):
    """Raised when a ComfyUI generation cannot be safely or truthfully admitted."""


class MediaKind(str, Enum):
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"


@dataclass(frozen=True)
class WorkflowBinding:
    logical_name: str
    node_id: str
    input_name: str

    def validate(self) -> None:
        if not all(
            isinstance(item, str) and item.strip()
            for item in (self.logical_name, self.node_id, self.input_name)
        ):
            raise ComfyProductionError("workflow bindings must be non-empty")


@dataclass(frozen=True)
class ModelRuntimeRef:
    project: str
    repository_url: str
    source_revision: str
    model_id: str
    model_revision: str | None
    source_license: str
    model_license: str
    license_locator: str
    commercial_use_allowed: bool | None
    weight_sha256: str | None = None

    def validate(self) -> None:
        if not _REVISION.fullmatch(self.source_revision):
            raise ComfyProductionError(f"{self.project}: source revision must be immutable")
        if self.model_revision is not None and not _REVISION.fullmatch(self.model_revision):
            raise ComfyProductionError(f"{self.project}: model revision must be immutable")
        if self.weight_sha256 is not None and not _SHA256.fullmatch(self.weight_sha256):
            raise ComfyProductionError(f"{self.project}: weight_sha256 is invalid")
        for name in (
            "project",
            "repository_url",
            "model_id",
            "source_license",
            "model_license",
            "license_locator",
        ):
            if not str(getattr(self, name)).strip():
                raise ComfyProductionError(f"{self.project}: {name} is required")


@dataclass(frozen=True)
class ComfyWorkflowContract:
    workflow_id: str
    media_kind: MediaKind
    workflow_source_url: str
    workflow_revision: str
    workflow_api_sha256: str
    bindings: tuple[WorkflowBinding, ...]
    output_node_ids: tuple[str, ...]
    models: tuple[ModelRuntimeRef, ...]
    executable_admission: bool
    manual_release_required: bool = True

    def validate(self) -> None:
        if not self.workflow_id.strip() or not self.workflow_source_url.startswith("https://"):
            raise ComfyProductionError("workflow identity and HTTPS source are required")
        if not _REVISION.fullmatch(self.workflow_revision):
            raise ComfyProductionError("workflow revision must be an immutable commit")
        if not _SHA256.fullmatch(self.workflow_api_sha256):
            raise ComfyProductionError("workflow_api_sha256 is invalid")
        if not self.bindings or not self.output_node_ids or not self.models:
            raise ComfyProductionError("bindings, output nodes, and models are required")
        for binding in self.bindings:
            binding.validate()
        logical = [item.logical_name for item in self.bindings]
        if len(logical) != len(set(logical)):
            raise ComfyProductionError("logical workflow bindings must be unique")
        if len(self.output_node_ids) != len(set(self.output_node_ids)):
            raise ComfyProductionError("output node IDs must be unique")
        for model in self.models:
            model.validate()
        if self.executable_admission and any(
            model.model_revision is None
            or model.weight_sha256 is None
            or model.commercial_use_allowed is not True
            for model in self.models
        ):
            raise ComfyProductionError(
                "executable workflows require pinned, hashed weights and affirmative commercial rights"
            )
        if not self.manual_release_required:
            raise ComfyProductionError("generated media must retain a manual release gate")


@dataclass(frozen=True)
class ComfyGenerationRequest:
    request_id: str
    values: Mapping[str, object]
    upload_paths: Mapping[str, str]
    output_dir: str
    rights_locator: str


@dataclass(frozen=True)
class ComfyGeneratedArtifact:
    artifact_id: str
    relative_path: str
    media_type: str
    content_sha256: str
    bytes: int
    source_node_id: str


@dataclass(frozen=True)
class ComfyGenerationReceipt:
    request_id: str
    workflow_id: str
    prompt_id: str
    workflow_api_sha256: str
    bound_request_sha256: str
    artifacts: tuple[ComfyGeneratedArtifact, ...]
    model_refs: tuple[ModelRuntimeRef, ...]
    rights_locator: str
    output_root: str
    elapsed_seconds: float
    external_publish_executed: bool = False
    human_release_required: bool = True
    human_release_completed: bool = False
    four_a_effect_proven: bool = False
    schema: str = "ProofLaunchComfyGenerationReceiptV1"


class ComfyUIProductionClient:
    """A thin, isolated client for the mature ComfyUI local workflow API."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8188",
        *,
        allowed_hosts: Sequence[str] = ("127.0.0.1", "localhost", "::1"),
        timeout_seconds: float = 1800,
        poll_interval_seconds: float = 1,
        max_output_bytes: int = 8 * 1024 * 1024 * 1024,
    ) -> None:
        parsed = urllib.parse.urlsplit(base_url)
        if parsed.scheme not in {"http", "https"} or parsed.hostname not in set(allowed_hosts):
            raise ComfyProductionError("ComfyUI endpoint host is not allowlisted")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ComfyProductionError("ComfyUI base URL cannot contain credentials or query state")
        if not 1 <= timeout_seconds <= 14_400:
            raise ComfyProductionError("timeout_seconds must be in [1, 14400]")
        if not 0.01 <= poll_interval_seconds <= 30:
            raise ComfyProductionError("poll_interval_seconds must be in [0.01, 30]")
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.poll_interval_seconds = poll_interval_seconds
        self.max_output_bytes = max_output_bytes

    def execute(
        self,
        contract: ComfyWorkflowContract,
        workflow_api_path: str | Path,
        request: ComfyGenerationRequest,
    ) -> ComfyGenerationReceipt:
        contract.validate()
        if not contract.executable_admission:
            raise ComfyProductionError("workflow has not passed executable admission")
        workflow_path = Path(workflow_api_path).resolve()
        if not workflow_path.is_file() or sha256_file(workflow_path) != contract.workflow_api_sha256:
            raise ComfyProductionError("workflow API file hash does not match the contract")
        try:
            workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise ComfyProductionError(f"workflow API JSON is invalid: {error}") from error
        if not isinstance(workflow, dict):
            raise ComfyProductionError("workflow API JSON must be an object")
        bound = copy.deepcopy(workflow)
        binding_by_name = {item.logical_name: item for item in contract.bindings}
        supplied = set(request.values) | set(request.upload_paths)
        unknown = supplied - set(binding_by_name)
        if unknown:
            raise ComfyProductionError(f"undeclared workflow values: {sorted(unknown)}")
        missing = set(binding_by_name) - supplied
        if missing:
            raise ComfyProductionError(f"required workflow values missing: {sorted(missing)}")
        for logical_name, value in request.values.items():
            self._set_binding(bound, binding_by_name[logical_name], value)
        for logical_name, source_path in request.upload_paths.items():
            uploaded_name = self._upload(Path(source_path))
            self._set_binding(bound, binding_by_name[logical_name], uploaded_name)

        root = Path(request.output_dir).resolve()
        if root.exists() and any(root.iterdir()):
            raise ComfyProductionError("ComfyUI output directory must be empty")
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        bound_sha256 = hashlib.sha256(
            json.dumps(bound, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        started = time.monotonic()
        try:
            submission = self._json_request(
                "/prompt",
                method="POST",
                payload={
                    "prompt": bound,
                    "client_id": f"prooflaunch-{request.request_id}",
                    "extra_data": {
                        "prooflaunch_request_id": request.request_id,
                        "workflow_api_sha256": contract.workflow_api_sha256,
                    },
                },
            )
            prompt_id = str(submission.get("prompt_id", "")).strip()
            if not prompt_id:
                raise ComfyProductionError(
                    f"ComfyUI rejected workflow: {submission.get('node_errors') or submission}"
                )
            history = self._wait_history(prompt_id, started)
            artifacts = self._download_outputs(
                history, contract.output_node_ids, root, prompt_id
            )
            if not artifacts:
                raise ComfyProductionError("ComfyUI completed without declared media outputs")
        except Exception:
            self._best_effort_interrupt()
            raise

        elapsed = round(time.monotonic() - started, 6)
        receipt = ComfyGenerationReceipt(
            request_id=request.request_id,
            workflow_id=contract.workflow_id,
            prompt_id=prompt_id,
            workflow_api_sha256=contract.workflow_api_sha256,
            bound_request_sha256=bound_sha256,
            artifacts=tuple(artifacts),
            model_refs=contract.models,
            rights_locator=request.rights_locator,
            output_root=str(root),
            elapsed_seconds=elapsed,
        )
        receipt_path = root / "comfy-generation-receipt.json"
        atomic_write_text(
            receipt_path,
            json.dumps(asdict(receipt), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        )
        receipt_path.chmod(0o600)
        return receipt

    @staticmethod
    def _set_binding(workflow: dict, binding: WorkflowBinding, value: object) -> None:
        node = workflow.get(binding.node_id)
        if not isinstance(node, dict) or not isinstance(node.get("inputs"), dict):
            raise ComfyProductionError(f"binding node missing: {binding.node_id}")
        if binding.input_name not in node["inputs"]:
            raise ComfyProductionError(
                f"binding input missing: {binding.node_id}.{binding.input_name}"
            )
        node["inputs"][binding.input_name] = value

    def _wait_history(self, prompt_id: str, started: float) -> Mapping[str, object]:
        while time.monotonic() - started <= self.timeout_seconds:
            payload = self._json_request(f"/history/{urllib.parse.quote(prompt_id)}")
            entry = payload.get(prompt_id) if isinstance(payload, dict) else None
            if isinstance(entry, dict):
                status = entry.get("status")
                if isinstance(status, dict) and status.get("status_str") == "error":
                    raise ComfyProductionError(f"ComfyUI workflow failed: {status}")
                if isinstance(entry.get("outputs"), dict):
                    return entry
            time.sleep(self.poll_interval_seconds)
        raise ComfyProductionError("ComfyUI workflow timed out")

    def _download_outputs(
        self,
        history: Mapping[str, object],
        output_nodes: Sequence[str],
        root: Path,
        prompt_id: str,
    ) -> list[ComfyGeneratedArtifact]:
        outputs = history.get("outputs")
        if not isinstance(outputs, dict):
            return []
        artifacts: list[ComfyGeneratedArtifact] = []
        for node_id in output_nodes:
            node = outputs.get(node_id)
            if not isinstance(node, dict):
                continue
            descriptors: list[Mapping[str, object]] = []
            for key in ("images", "gifs", "videos", "audio"):
                values = node.get(key)
                if isinstance(values, list):
                    descriptors.extend(item for item in values if isinstance(item, dict))
            for descriptor in descriptors:
                filename = str(descriptor.get("filename", ""))
                subfolder = str(descriptor.get("subfolder", ""))
                storage_type = str(descriptor.get("type", "output"))
                extension = Path(filename).suffix.lower()
                if Path(filename).name != filename or extension not in _SAFE_EXTENSION:
                    raise ComfyProductionError("ComfyUI returned an unsafe output filename")
                if subfolder and (Path(subfolder).is_absolute() or ".." in Path(subfolder).parts):
                    raise ComfyProductionError("ComfyUI returned an unsafe output subfolder")
                query = urllib.parse.urlencode(
                    {"filename": filename, "subfolder": subfolder, "type": storage_type}
                )
                temporary = root / f".comfy-download-{uuid.uuid4().hex}.part"
                downloaded_bytes, digest, media_type = self._stream_request_to_path(
                    f"/view?{query}", temporary
                )
                target = root / f"{len(artifacts) + 1:02d}-{digest[:16]}{extension}"
                if target.exists():
                    temporary.unlink(missing_ok=True)
                    raise ComfyProductionError("ComfyUI output target already exists")
                temporary.replace(target)
                target.chmod(0o600)
                artifacts.append(
                    ComfyGeneratedArtifact(
                        artifact_id=f"{prompt_id}:{node_id}:{len(artifacts) + 1}",
                        relative_path=target.name,
                        media_type=media_type or mimetypes.guess_type(filename)[0] or "application/octet-stream",
                        content_sha256=digest,
                        bytes=downloaded_bytes,
                        source_node_id=node_id,
                    )
                )
        return artifacts

    def _upload(self, path: Path) -> str:
        if not path.is_file():
            raise ComfyProductionError(f"upload source is missing: {path}")
        boundary = f"----prooflaunch-{uuid.uuid4().hex}"
        filename = f"{sha256_file(path)[:20]}{path.suffix.lower()}"
        media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="image"; filename="{filename}"\r\n'
            f"Content-Type: {media_type}\r\n\r\n"
        ).encode() + path.read_bytes() + (
            f"\r\n--{boundary}\r\n"
            'Content-Disposition: form-data; name="type"\r\n\r\ninput\r\n'
            f"--{boundary}--\r\n"
        ).encode()
        response = self._request(
            "/upload/image",
            method="POST",
            body=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        try:
            payload = json.loads(response.read().decode("utf-8"))
        finally:
            response.close()
        returned = str(payload.get("name", "")).strip()
        if not returned or Path(returned).name != returned:
            raise ComfyProductionError("ComfyUI upload returned an unsafe filename")
        return returned

    def _json_request(
        self,
        path: str,
        *,
        method: str = "GET",
        payload: object | None = None,
    ) -> dict:
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        response = self._request(
            path,
            method=method,
            body=body,
            headers={"Content-Type": "application/json"} if body is not None else {},
        )
        try:
            value = json.loads(response.read().decode("utf-8"))
        except json.JSONDecodeError as error:
            raise ComfyProductionError("ComfyUI returned invalid JSON") from error
        finally:
            response.close()
        if not isinstance(value, dict):
            raise ComfyProductionError("ComfyUI JSON response must be an object")
        return value

    def _bytes_request(self, path: str) -> tuple[bytes, str | None]:
        response = self._request(path)
        try:
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > self.max_output_bytes:
                raise ComfyProductionError("ComfyUI output exceeds size limit")
            body = response.read(self.max_output_bytes + 1)
            return body, response.headers.get_content_type()
        finally:
            response.close()

    def _stream_request_to_path(
        self, path: str, temporary: Path
    ) -> tuple[int, str, str | None]:
        if temporary.exists() or temporary.parent.resolve() != temporary.resolve().parent:
            raise ComfyProductionError("temporary output path is unsafe")
        response = self._request(path)
        content_type = response.headers.get_content_type()
        total = 0
        digest = hashlib.sha256()
        try:
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > self.max_output_bytes:
                raise ComfyProductionError("ComfyUI output exceeds size limit")
            with temporary.open("xb") as handle:
                while chunk := response.read(4 * 1024 * 1024):
                    total += len(chunk)
                    if total > self.max_output_bytes:
                        raise ComfyProductionError("ComfyUI output exceeds size limit")
                    handle.write(chunk)
                    digest.update(chunk)
                handle.flush()
                os.fsync(handle.fileno())
            if total == 0:
                raise ComfyProductionError("ComfyUI output is empty")
            return total, digest.hexdigest(), content_type
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        finally:
            response.close()

    def _request(
        self,
        path: str,
        *,
        method: str = "GET",
        body: bytes | None = None,
        headers: Mapping[str, str] | None = None,
    ):
        request = urllib.request.Request(
            f"{self.base_url}{path}", data=body, method=method, headers=dict(headers or {})
        )
        try:
            return urllib.request.urlopen(request, timeout=min(self.timeout_seconds, 120))
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as error:
            raise ComfyProductionError(f"ComfyUI request failed: {error}") from error

    def _best_effort_interrupt(self) -> None:
        try:
            response = self._request("/interrupt", method="POST", body=b"{}", headers={"Content-Type": "application/json"})
            response.close()
        except ComfyProductionError:
            pass
