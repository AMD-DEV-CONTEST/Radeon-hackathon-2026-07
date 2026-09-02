"""Linux production adapters for the clicked AMD three-second runner.

The module deliberately contains no daemon or polling loop.  Importing it and
calling :func:`create_runner` are CPU-only configuration operations.  ComfyUI
is started only when ``VerticalSliceRunner`` crosses its already-persisted
user-click and admission boundaries.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from fractions import Fraction
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import signal
import subprocess
import sys
import time
from types import ModuleType
from typing import Any
import urllib.error
import urllib.parse
import urllib.request
from uuid import UUID

from drama.flux2_reference import (
    load_flux2_dev_capability,
    load_flux2_workflow_templates,
)
from drama.h3.model_registry import load_h3_amd_capability
from drama.h3.prompt_renderer import H3PromptRenderer
from drama.h3.reference_binder import ApprovedH3Asset, bind_h3_references
from drama.h3.workflows import (
    H3StagedReference,
    build_competition_single_reference_comfy_api_workflow,
    build_h3_workflow,
)
from shared_contracts import H3SequencePlanV1


_GIB = 1024**3
_MEMORY_ADMISSION_MAX = 44 * _GIB
_FILE_CACHE_MAX = 32 * _GIB
_PVC_AVAILABLE_MIN = 5 * _GIB
_VRAM_IDLE_MAX = 1 * _GIB
_GPU_USE_IDLE_MAX = 5
POSIX_FADV_DONTNEED = getattr(os, "POSIX_FADV_DONTNEED", 4)
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_VIEW_ORDER = ("front_three_quarter",)
_PRODUCTION_VIEW_ORDER = ("front", "three_quarter_left", "profile_left")
_SAFE_REMOTE_SEGMENT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
_RUNNER_RELATIVE_PATH = "ops/amd/run-three-second-vertical-slice.py"
_RUNNER_MODULE_NAME = "_shidu_api_trusted_three_second_runner"
_FLUX_REQUIRED_NODES = frozenset(
    {"UNETLoader", "CLIPLoader", "LoadImage", "Flux2Scheduler", "SaveImage"}
)
_H3_REQUIRED_NODES = frozenset(
    {
        "MiniMaxH3ReferenceToVideo",
        "MiniMaxH3SigmaShift",
        "VAEDecodeAudio",
        "SaveVideo",
    }
)


class RuntimeWiringError(RuntimeError):
    """One production adapter could not prove its safety contract."""


class TerminalComfyWorkflowFailure(RuntimeWiringError):
    """Comfy history proves that a submitted workflow ended unsuccessfully."""

    known_terminal = True


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical_sha256(value: object) -> str:
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


def _json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeWiringError(f"{label} is unavailable or invalid JSON") from exc
    if type(value) is not dict or not all(type(key) is str for key in value):
        raise RuntimeWiringError(f"{label} must be a standard JSON object")
    return value


def _persistent_file(path: Path, root: Path, label: str) -> Path:
    if not path.is_absolute() or path.is_symlink():
        raise RuntimeWiringError(f"{label} must be a non-symlink persistent file")
    try:
        resolved_root = root.resolve(strict=True)
        resolved = path.resolve(strict=True)
        resolved.relative_to(resolved_root)
    except (OSError, ValueError) as exc:
        raise RuntimeWiringError(f"{label} is outside persistent authority") from exc
    if resolved != path or not resolved.is_file():
        raise RuntimeWiringError(f"{label} must be a canonical regular file")
    return resolved


def _runner_module() -> Any:
    release_value = os.environ.get("AMD_RELEASE_DIR")
    if not release_value or not Path(release_value).is_absolute():
        raise RuntimeWiringError("AMD_RELEASE_DIR must be an absolute release root")
    try:
        release_root = Path(release_value).resolve(strict=True)
    except OSError as exc:
        raise RuntimeWiringError("AMD_RELEASE_DIR is unavailable") from exc
    if not release_root.is_dir():
        raise RuntimeWiringError("AMD_RELEASE_DIR must resolve to a directory")

    manifest_path = release_root / "deploy" / "amd" / "release-manifest.json"
    runner_path = release_root.joinpath(*PurePosixPath(_RUNNER_RELATIVE_PATH).parts)
    for path, label in (
        (manifest_path, "release manifest"),
        (runner_path, "three-second runner"),
    ):
        if path.is_symlink():
            raise RuntimeWiringError(f"{label} must not be a symlink")
        try:
            resolved = path.resolve(strict=True)
            resolved.relative_to(release_root)
        except (OSError, ValueError) as exc:
            raise RuntimeWiringError(f"{label} is outside the release root") from exc
        if resolved != path or not resolved.is_file():
            raise RuntimeWiringError(f"{label} must be a canonical release file")

    manifest = _json_object(manifest_path, "release manifest")
    runtime = manifest.get("runtime")
    authority = runtime.get("competitionRunner") if type(runtime) is dict else None
    if type(authority) is not dict or set(authority) != {"relativePath", "sha256"}:
        raise RuntimeWiringError("release manifest runner authority is invalid")
    expected_sha256 = authority.get("sha256")
    if (
        authority.get("relativePath") != _RUNNER_RELATIVE_PATH
        or type(expected_sha256) is not str
        or _SHA256_RE.fullmatch(expected_sha256) is None
    ):
        raise RuntimeWiringError("release manifest runner authority is not pinned")
    try:
        source = runner_path.read_bytes()
    except OSError as exc:
        raise RuntimeWiringError("three-second runner is unreadable") from exc
    if hashlib.sha256(source).hexdigest() != expected_sha256:
        raise RuntimeWiringError("three-second runner SHA-256 does not match the release")

    existing = sys.modules.get(_RUNNER_MODULE_NAME)
    if (
        existing is not None
        and getattr(existing, "__file__", None) == str(runner_path)
        and getattr(existing, "__runner_sha256__", None) == expected_sha256
    ):
        return existing
    sys.modules.pop(_RUNNER_MODULE_NAME, None)
    module = ModuleType(_RUNNER_MODULE_NAME)
    module.__file__ = str(runner_path)
    module.__runner_sha256__ = expected_sha256
    sys.modules[_RUNNER_MODULE_NAME] = module
    try:
        exec(compile(source, str(runner_path), "exec"), module.__dict__)
    except Exception:
        sys.modules.pop(_RUNNER_MODULE_NAME, None)
        raise
    required = (
        "VerticalSliceRunner",
        "VerticalSliceRuntimeInputs",
        "FluxExecutionAuthority",
        "H3BuildAuthority",
        "MediaProbeSummary",
    )
    if any(getattr(module, name, None) is None for name in required):
        sys.modules.pop(_RUNNER_MODULE_NAME, None)
        raise RuntimeWiringError("three-second runner contract is incomplete")
    return module


def _scan_gpu_processes() -> tuple[dict[str, object], ...]:
    """Read Linux procfs without running recursive process discovery tools."""

    root = Path("/proc")
    if not root.is_dir():
        raise RuntimeWiringError("Linux procfs is unavailable")
    own = {os.getpid(), os.getppid()}
    found: list[dict[str, object]] = []
    for entry in root.iterdir():
        if not entry.name.isdigit() or int(entry.name) in own:
            continue
        try:
            command = (entry / "cmdline").read_bytes().replace(b"\0", b" ").decode(
                "utf-8", errors="replace"
            )
        except (OSError, PermissionError):
            continue
        lowered = command.casefold()
        residual = (
            ("comfyui" in lowered and "main.py" in lowered)
            or "run-h3-production-smoke" in lowered
            or "run-flux2" in lowered
            or (
                "creative-hub-dag-worker" in lowered
                and any(token in lowered for token in ("video-local", "--gpu-index"))
            )
        )
        if residual:
            found.append({"pid": int(entry.name), "command": command[:512]})
    return tuple(sorted(found, key=lambda value: int(value["pid"])))


def _rocm_snapshot(rocm_smi: Path = Path("/opt/rocm/bin/rocm-smi")) -> dict[str, int]:
    if not rocm_smi.is_file() or not os.access(rocm_smi, os.X_OK):
        raise RuntimeWiringError("rocm-smi is unavailable")
    completed = subprocess.run(
        [str(rocm_smi), "--showuse", "--showmeminfo", "vram", "--json"],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
        env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
    )
    if completed.returncode != 0:
        raise RuntimeWiringError("rocm-smi telemetry failed")
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeWiringError("rocm-smi returned invalid JSON") from exc
    values: dict[str, int | None] = {"use": None, "used": None, "total": None}

    def number(value: object) -> int | None:
        match = re.search(r"-?[0-9]+", str(value))
        return int(match.group()) if match else None

    def walk(value: object) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                normalized = str(key).casefold()
                if "gpu use" in normalized and "%" in normalized:
                    values["use"] = number(item)
                elif "vram total used memory" in normalized:
                    values["used"] = number(item)
                elif "vram total memory" in normalized:
                    values["total"] = number(item)
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(payload)
    if any(value is None for value in values.values()) or int(values["total"] or 0) <= 0:
        raise RuntimeWiringError("rocm-smi telemetry is incomplete")
    return {
        "usePercent": int(values["use"] or 0),
        "vramUsedBytes": int(values["used"] or 0),
        "vramTotalBytes": int(values["total"] or 0),
    }


@dataclass(slots=True)
class _ComfyProcessHandle:
    kind: str
    process: subprocess.Popen[bytes]
    log_handle: Any


class ProductionComfyProcessController:
    """Own exactly one loopback Comfy subprocess at a time."""

    def __init__(
        self,
        *,
        python_path: Path,
        comfy_root: Path,
        runtime_root: Path,
        port: int = 18188,
        process_scanner: Callable[[], tuple[dict[str, object], ...]] = _scan_gpu_processes,
        gpu_snapshot: Callable[[], Mapping[str, int]] = _rocm_snapshot,
    ) -> None:
        if port != 18188:
            raise RuntimeWiringError("competition Comfy must use loopback port 18188")
        comfy_posix = PurePosixPath(comfy_root.as_posix())
        runtime_posix = PurePosixPath(runtime_root.as_posix())
        if not comfy_posix.is_absolute() or not comfy_root.as_posix().startswith("/persistent/"):
            raise RuntimeWiringError("Comfy release must be on the persistent PVC")
        if not runtime_posix.is_absolute() or not runtime_root.as_posix().startswith("/workspace/"):
            raise RuntimeWiringError("Comfy runtime data must stay in /workspace")
        self.python_path = python_path
        self.comfy_root = comfy_root
        self.runtime_root = runtime_root
        self.port = port
        self.input_root = runtime_root / "vertical-slice" / "comfy-input"
        self.output_root = runtime_root / "vertical-slice" / "comfy-output"
        self.user_root = runtime_root / "vertical-slice" / "comfy-user"
        self.log_root = runtime_root / "vertical-slice" / "logs"
        self._scan = process_scanner
        self._gpu = gpu_snapshot
        self._active: _ComfyProcessHandle | None = None

    def command_for(self, kind: str, arguments: tuple[str, ...]) -> tuple[str, ...]:
        if kind not in {"flux", "h3"}:
            raise RuntimeWiringError("unknown Comfy process kind")
        fixed = ("--highvram", "--cache-none", "--reserve-vram", "2")
        if arguments not in {(), fixed}:
            raise RuntimeWiringError("unsafe Comfy runner arguments")
        return (
            str(self.python_path),
            str(self.comfy_root / "main.py"),
            "--listen",
            "127.0.0.1",
            "--port",
            str(self.port),
            "--disable-auto-launch",
            "--disable-all-custom-nodes",
            *fixed,
            "--input-directory",
            str(self.input_root),
            "--output-directory",
            str(self.output_root),
            "--user-directory",
            str(self.user_root),
            "--database-url",
            f"sqlite:///{self.user_root / 'comfyui.db'}",
        )

    def assert_gpu_idle(self, phase: str) -> None:
        if type(phase) is not str or not phase:
            raise RuntimeWiringError("GPU idle phase is required")
        residual = self._scan()
        if residual:
            raise RuntimeWiringError("residual FLUX, H3, ComfyUI, or GPU worker exists")
        snapshot = self._gpu()
        if (
            int(snapshot.get("usePercent", -1)) > _GPU_USE_IDLE_MAX
            or int(snapshot.get("vramUsedBytes", -1)) < 0
            or int(snapshot.get("vramUsedBytes", -1)) > _VRAM_IDLE_MAX
        ):
            raise RuntimeWiringError("GPU or VRAM is not idle")

    def start(self, kind: str, arguments: tuple[str, ...]) -> _ComfyProcessHandle:
        if self._active is not None:
            raise RuntimeWiringError("only one Comfy process may exist")
        if self._scan():
            raise RuntimeWiringError("residual GPU process appeared before Comfy start")
        snapshot = self._gpu()
        if (
            int(snapshot.get("usePercent", -1)) > _GPU_USE_IDLE_MAX
            or not 0 <= int(snapshot.get("vramUsedBytes", -1)) <= _VRAM_IDLE_MAX
        ):
            raise RuntimeWiringError("GPU ceased to be idle before Comfy start")
        main = self.comfy_root / "main.py"
        if not self.python_path.is_file() or not main.is_file():
            raise RuntimeWiringError("pinned Comfy runtime is unavailable")
        for directory in (
            self.input_root,
            self.output_root,
            self.user_root,
            self.log_root,
        ):
            directory.mkdir(parents=True, exist_ok=True)
        log_handle = (self.log_root / f"comfy-{kind}.log").open("ab", buffering=0)
        try:
            process = subprocess.Popen(
                self.command_for(kind, arguments),
                cwd=self.comfy_root,
                stdin=subprocess.DEVNULL,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                env={
                    **os.environ,
                    "PYTHONUTF8": "1",
                    "PYTHONIOENCODING": "utf-8",
                },
                start_new_session=True,
            )
        except Exception:
            log_handle.close()
            raise
        handle = _ComfyProcessHandle(kind=kind, process=process, log_handle=log_handle)
        self._active = handle
        return handle

    def stop(self, handle: _ComfyProcessHandle) -> None:
        if handle is not self._active:
            raise RuntimeWiringError("Comfy process handle is not owned by this controller")
        process = handle.process
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass

    def wait_exited(self, handle: _ComfyProcessHandle) -> None:
        if handle is not self._active:
            raise RuntimeWiringError("Comfy process handle is not owned by this controller")
        try:
            handle.process.wait(timeout=90)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(handle.process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            handle.process.wait(timeout=30)
        finally:
            handle.log_handle.close()
            self._active = None
        if handle.process.poll() is None:
            raise RuntimeWiringError("Comfy process did not exit")

    def assert_vram_idle(self) -> None:
        deadline = time.monotonic() + 90
        last: Mapping[str, int] | None = None
        while time.monotonic() <= deadline:
            last = self._gpu()
            if (
                int(last.get("usePercent", -1)) <= _GPU_USE_IDLE_MAX
                and 0 <= int(last.get("vramUsedBytes", -1)) <= _VRAM_IDLE_MAX
            ):
                return
            time.sleep(2)
        raise RuntimeWiringError(f"VRAM did not return to idle: {last!r}")

    def wait_for_gpu_activity(
        self,
        handle: _ComfyProcessHandle,
        *,
        kind: str,
        prompt_id: str,
    ) -> dict[str, object]:
        """Wait for observable AMD work without waiting for a FLUX output."""

        if (
            handle is not self._active
            or kind not in {"flux", "h3"}
            or handle.kind != kind
            or type(prompt_id) is not str
            or not prompt_id
        ):
            raise RuntimeWiringError("GPU activity proof authority is invalid")
        started = datetime.now(timezone.utc)
        deadline = time.monotonic() + 20 * 60
        peak_use = 0
        peak_vram = 0
        sample_count = 0
        while time.monotonic() <= deadline:
            if handle.process.poll() is not None:
                raise RuntimeWiringError(
                    "Comfy exited before GPU runtime proof was observed"
                )
            snapshot = self._gpu()
            use = int(snapshot.get("usePercent", -1))
            vram = int(snapshot.get("vramUsedBytes", -1))
            if use < 0 or vram < 0:
                raise RuntimeWiringError("rocm-smi activity sample is invalid")
            sample_count += 1
            peak_use = max(peak_use, use)
            peak_vram = max(peak_vram, vram)
            if use >= 10 or vram >= 2 * _GIB:
                observed = datetime.now(timezone.utc)
                return {
                    "schemaVersion": "amd.gpu-runtime-activity.v1",
                    "kind": kind,
                    "promptId": prompt_id,
                    "gpuActivityObserved": True,
                    "startedAt": started.isoformat(),
                    "observedAt": observed.isoformat(),
                    "sampleCount": sample_count,
                    "peakGpuUsePercent": peak_use,
                    "peakVramUsedBytes": peak_vram,
                }
            time.sleep(2)
        raise RuntimeWiringError("GPU activity was not observed before timeout")


def _default_request(
    base_url: str,
    method: str,
    path: str,
    payload: object | None,
    timeout: float,
) -> Any:
    data = None
    headers: dict[str, str] = {}
    if payload is not None:
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        urllib.parse.urljoin(base_url + "/", path.lstrip("/")),
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeWiringError(f"Comfy loopback request failed: {method} {path}") from exc
    if not body:
        return None
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeWiringError("Comfy returned invalid JSON") from exc


class LoopbackComfySession:
    def __init__(
        self,
        *,
        base_url: str,
        input_root: Path,
        output_root: Path,
        request: Callable[[str, str, object | None, float], Any] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        timeout_seconds: float = 6 * 60 * 60,
    ) -> None:
        parsed = urllib.parse.urlsplit(base_url)
        if (
            parsed.scheme != "http"
            or parsed.hostname != "127.0.0.1"
            or parsed.port != 18188
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise RuntimeWiringError("Comfy transport must be loopback 127.0.0.1:18188")
        self.base_url = "http://127.0.0.1:18188"
        self.input_root = input_root
        self.output_root = output_root
        self._request = request or (
            lambda method, path, payload, timeout: _default_request(
                self.base_url, method, path, payload, timeout
            )
        )
        self._sleep = sleep
        self._timeout = timeout_seconds
        self._submitted_queue_ids: dict[str, int] = {}

    def stage_input(self, local_path: Path, remote_name: str, sha256: str) -> None:
        remote = PurePosixPath(remote_name)
        if (
            remote.is_absolute()
            or "\\" in remote_name
            or any(
                part in {"", ".", ".."} or not _SAFE_REMOTE_SEGMENT_RE.fullmatch(part)
                for part in remote.parts
            )
            or remote.suffix.casefold() not in {".png", ".jpg", ".jpeg", ".webp"}
            or _SHA256_RE.fullmatch(sha256) is None
        ):
            raise RuntimeWiringError("Comfy staged input authority is unsafe")
        if not local_path.is_file() or _sha256_file(local_path) != sha256:
            raise RuntimeWiringError("Comfy staged input SHA mismatch")
        destination = self.input_root.joinpath(*remote.parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        partial = destination.with_name(destination.name + ".partial")
        shutil.copyfile(local_path, partial)
        if _sha256_file(partial) != sha256:
            partial.unlink(missing_ok=True)
            raise RuntimeWiringError("Comfy staged copy SHA mismatch")
        os.replace(partial, destination)

    @staticmethod
    def _metadata(entry: Mapping[str, Any]) -> Mapping[str, Any] | None:
        value = entry.get("extra_data")
        return value if isinstance(value, dict) else None

    @staticmethod
    def _metadata_matches(
        entry: Mapping[str, Any], required: Mapping[str, object]
    ) -> bool:
        metadata = LoopbackComfySession._metadata(entry)
        return metadata is not None and all(metadata.get(key) == value for key, value in required.items())

    def _history_entry(self, prompt_id: str) -> dict[str, Any] | None:
        root = self._request("GET", f"/history/{prompt_id}", None, 20)
        if not isinstance(root, dict):
            return None
        entry = root.get(prompt_id)
        return entry if isinstance(entry, dict) else None

    @staticmethod
    def _history_queue_id(
        prompt_id: str, entry: Mapping[str, Any]
    ) -> int | None:
        """Recover Comfy's durable numeric queue identity from history."""

        prompt = entry.get("prompt")
        if not isinstance(prompt, list) or len(prompt) < 2:
            return None
        queue_id = prompt[0]
        history_prompt_id = prompt[1]
        if (
            isinstance(queue_id, bool)
            or not isinstance(queue_id, int)
            or queue_id < 0
            or history_prompt_id != prompt_id
        ):
            raise RuntimeWiringError("Comfy history queue identity is invalid")
        return queue_id

    def _queue_entries(self) -> Iterable[tuple[str, Mapping[str, Any]]]:
        root = self._request("GET", "/queue", None, 20)
        if not isinstance(root, dict):
            raise RuntimeWiringError("Comfy queue response is invalid")
        for key in ("queue_running", "queue_pending"):
            values = root.get(key)
            if not isinstance(values, list):
                raise RuntimeWiringError("Comfy queue response is invalid")
            for value in values:
                if not isinstance(value, list) or len(value) < 4 or not isinstance(value[1], str):
                    raise RuntimeWiringError("Comfy queue entry is invalid")
                metadata = value[3]
                if isinstance(metadata, dict):
                    queue_id = value[0]
                    if isinstance(queue_id, bool) or not isinstance(queue_id, int):
                        raise RuntimeWiringError("Comfy queue number is invalid")
                    yield value[1], {"extra_data": metadata, "queueId": queue_id}

    def recover_submission(
        self,
        *,
        prompt_id: str | None,
        client_id: str,
        submission_nonce: str,
        required_metadata: dict[str, object],
    ) -> str | None:
        del client_id
        if required_metadata.get("submission_nonce") != submission_nonce:
            raise RuntimeWiringError("Comfy recovery metadata is inconsistent")
        if prompt_id is not None:
            entry = self._history_entry(prompt_id)
            if entry is not None:
                if not self._metadata_matches(entry, required_metadata):
                    raise RuntimeWiringError("persisted Comfy history metadata mismatch")
                queue_id = self._history_queue_id(prompt_id, entry)
                if queue_id is None:
                    raise RuntimeWiringError(
                        "persisted Comfy history has no queue identity"
                    )
                self._submitted_queue_ids[prompt_id] = queue_id
                return prompt_id
            matches = [
                current
                for current, entry in self._queue_entries()
                if current == prompt_id and self._metadata_matches(entry, required_metadata)
            ]
            return prompt_id if len(matches) == 1 else None

        matches = [
            current
            for current, entry in self._queue_entries()
            if self._metadata_matches(entry, required_metadata)
        ]
        history = self._request("GET", "/history?max_items=100", None, 30)
        if isinstance(history, dict):
            for current, entry in history.items():
                if (
                    isinstance(current, str)
                    and isinstance(entry, dict)
                    and self._metadata_matches(entry, required_metadata)
                ):
                    queue_id = self._history_queue_id(current, entry)
                    if queue_id is None:
                        raise RuntimeWiringError(
                            "persisted Comfy history has no queue identity"
                        )
                    self._submitted_queue_ids[current] = queue_id
                    matches.append(current)
        unique = tuple(dict.fromkeys(matches))
        if len(unique) > 1:
            raise RuntimeWiringError("Comfy recovery found duplicate submission identities")
        return unique[0] if unique else None

    def submit(
        self,
        workflow: dict[str, Any],
        *,
        client_id: str,
        submission_nonce: str,
        extra_data: dict[str, object],
    ) -> str:
        if extra_data.get("submission_nonce") != submission_nonce:
            raise RuntimeWiringError("Comfy submission metadata is inconsistent")
        response = self._request(
            "POST",
            "/prompt",
            {"prompt": workflow, "client_id": client_id, "extra_data": extra_data},
            60,
        )
        if (
            not isinstance(response, dict)
            or not isinstance(response.get("prompt_id"), str)
            or not response["prompt_id"]
            or response.get("node_errors") not in ({}, None)
        ):
            raise RuntimeWiringError("Comfy rejected the workflow")
        queue_id = response.get("number")
        if isinstance(queue_id, int) and not isinstance(queue_id, bool) and queue_id >= 0:
            self._submitted_queue_ids[response["prompt_id"]] = queue_id
        return response["prompt_id"]

    def queue_id_for_prompt(self, prompt_id: str) -> int:
        cached = self._submitted_queue_ids.get(prompt_id)
        if cached is not None:
            return cached
        matches = [
            int(entry["queueId"])
            for current, entry in self._queue_entries()
            if current == prompt_id
        ]
        if len(matches) == 1:
            self._submitted_queue_ids[prompt_id] = matches[0]
            return matches[0]
        if matches:
            raise RuntimeWiringError("Comfy queue identity is ambiguous")
        history = self._history_entry(prompt_id)
        if history is None:
            raise RuntimeWiringError("Comfy queue identity is unavailable")
        queue_id = self._history_queue_id(prompt_id, history)
        if queue_id is None:
            raise RuntimeWiringError("Comfy history has no queue identity")
        self._submitted_queue_ids[prompt_id] = queue_id
        return queue_id

    def submit_runtime_proof(
        self,
        workflow: dict[str, Any],
        *,
        client_id: str,
        submission_nonce: str,
        extra_data: dict[str, object],
    ) -> dict[str, object]:
        """Submit once and preserve Comfy's prompt and numeric queue identities."""

        if (
            extra_data.get("submission_nonce") != submission_nonce
            or extra_data.get("runtime_proof_only") is not True
        ):
            raise RuntimeWiringError("Comfy runtime-proof metadata is inconsistent")
        response = self._request(
            "POST",
            "/prompt",
            {"prompt": workflow, "client_id": client_id, "extra_data": extra_data},
            60,
        )
        queue_id = response.get("number") if isinstance(response, dict) else None
        if (
            not isinstance(response, dict)
            or not isinstance(response.get("prompt_id"), str)
            or not response["prompt_id"]
            or isinstance(queue_id, bool)
            or not isinstance(queue_id, int)
            or queue_id < 0
            or response.get("node_errors") not in ({}, None)
        ):
            raise RuntimeWiringError("Comfy rejected the runtime-proof workflow")
        self._submitted_queue_ids[response["prompt_id"]] = queue_id
        return {"promptId": response["prompt_id"], "queueId": queue_id}

    def wait_success(self, prompt_id: str) -> None:
        deadline = time.monotonic() + self._timeout
        while time.monotonic() <= deadline:
            entry = self._history_entry(prompt_id)
            if entry is not None:
                status = entry.get("status")
                if isinstance(status, dict) and status.get("completed") is True:
                    if status.get("status_str") != "success":
                        raise TerminalComfyWorkflowFailure("Comfy workflow failed")
                    return
            self._sleep(5)
        raise RuntimeWiringError("Comfy workflow timed out")

    def download(self, prompt_id: str, destination: Path) -> Path:
        entry = self._history_entry(prompt_id)
        outputs = entry.get("outputs") if isinstance(entry, dict) else None
        if not isinstance(outputs, dict):
            raise RuntimeWiringError("Comfy history has no output authority")
        expected_name = destination.name.removesuffix(".partial")
        expected_suffix = Path(expected_name).suffix.casefold()
        candidates: list[Path] = []
        for node in outputs.values():
            if not isinstance(node, dict):
                continue
            for values in node.values():
                if not isinstance(values, list):
                    continue
                for item in values:
                    if not isinstance(item, dict) or item.get("type") != "output":
                        continue
                    filename = item.get("filename")
                    subfolder = item.get("subfolder", "")
                    if not isinstance(filename, str) or PurePosixPath(filename).name != filename:
                        continue
                    subpath = PurePosixPath(str(subfolder))
                    if subpath.is_absolute() or ".." in subpath.parts or "\\" in str(subfolder):
                        continue
                    if Path(filename).suffix.casefold() != expected_suffix:
                        continue
                    candidate = self.output_root.joinpath(*subpath.parts, filename)
                    try:
                        resolved = candidate.resolve(strict=True)
                        resolved.relative_to(self.output_root.resolve(strict=True))
                    except (OSError, ValueError):
                        continue
                    if resolved.is_file():
                        candidates.append(resolved)
        if len(candidates) != 1:
            raise RuntimeWiringError("Comfy history does not identify exactly one output")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(candidates[0], destination)
        return destination

    def unload_models(self) -> None:
        self._request(
            "POST",
            "/free",
            {"unload_models": True, "free_memory": True},
            30,
        )


class LoopbackComfySessionFactory:
    def __init__(self, controller: ProductionComfyProcessController) -> None:
        self._controller = controller

    def create(self, kind: str, process_handle: _ComfyProcessHandle) -> LoopbackComfySession:
        if process_handle is not self._controller._active or process_handle.kind != kind:
            raise RuntimeWiringError("Comfy session process ownership mismatch")
        required = _FLUX_REQUIRED_NODES if kind == "flux" else _H3_REQUIRED_NODES
        session = LoopbackComfySession(
            base_url="http://127.0.0.1:18188",
            input_root=self._controller.input_root,
            output_root=self._controller.output_root,
        )
        deadline = time.monotonic() + 300
        last_error: Exception | None = None
        while time.monotonic() <= deadline:
            if process_handle.process.poll() is not None:
                raise RuntimeWiringError("Comfy process exited before readiness")
            try:
                info = session._request("GET", "/object_info", None, 20)
                if isinstance(info, dict) and required.issubset(info):
                    return session
                if isinstance(info, dict):
                    missing = sorted(required - set(info))
                    last_error = RuntimeWiringError(
                        "Comfy is missing required nodes: " + ", ".join(missing)
                    )
            except RuntimeWiringError as exc:
                last_error = exc
            time.sleep(2)
        raise RuntimeWiringError("Comfy did not become ready") from last_error


def _parse_key_values(path: Path) -> dict[str, int]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        result = {key: int(value) for key, value in (line.split() for line in lines)}
    except (OSError, ValueError) as exc:
        raise RuntimeWiringError(f"invalid cgroup authority: {path.name}") from exc
    return result


class CgroupMemoryAdmissionGate:
    def __init__(
        self,
        *,
        cgroup_root: Path = Path("/sys/fs/cgroup"),
        persistent_root: Path,
        available_bytes: Callable[[Path], int] = lambda path: shutil.disk_usage(path).free,
        process_scanner: Callable[[], tuple[dict[str, object], ...]] = _scan_gpu_processes,
    ) -> None:
        self._cgroup = cgroup_root
        self._persistent = persistent_root
        self._available = available_bytes
        self._scan = process_scanner

    def _integer(self, name: str) -> int:
        path = self._cgroup / name
        if path.is_symlink():
            raise RuntimeWiringError(f"unsafe cgroup authority: {name}")
        try:
            return int(path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError) as exc:
            raise RuntimeWiringError(f"invalid cgroup authority: {name}") from exc

    def capture_and_require_go(self, phase: str) -> dict[str, object]:
        if phase not in {"flux", "h3"}:
            raise RuntimeWiringError("unknown memory admission phase")
        current = self._integer("memory.current")
        maximum = self._integer("memory.max")
        swap_current = self._integer("memory.swap.current")
        swap_max = self._integer("memory.swap.max")
        stat = _parse_key_values(self._cgroup / "memory.stat")
        events_path = self._cgroup / "memory.events.local"
        events = _parse_key_values(events_path)
        file_cache = stat.get("file")
        if file_cache is None:
            raise RuntimeWiringError("cgroup memory.stat has no file cache authority")
        available = int(self._available(self._persistent))
        residual = self._scan()
        if current >= _MEMORY_ADMISSION_MAX:
            raise RuntimeWiringError("cgroup memory.current is not below 44 GiB")
        if file_cache > _FILE_CACHE_MAX:
            raise RuntimeWiringError("cgroup file cache has not recovered")
        if swap_current != 0 or swap_max != 0:
            raise RuntimeWiringError("cgroup swap must remain disabled")
        if available <= _PVC_AVAILABLE_MIN:
            raise RuntimeWiringError("persistent PVC free space is not above 5 GiB")
        if residual:
            raise RuntimeWiringError("residual FLUX, H3, ComfyUI, or GPU worker exists")
        events_text = events_path.read_bytes()
        return {
            "schemaVersion": "amd.runtime-memory-admission.v1",
            "phase": phase,
            "capturedAt": _utc_now(),
            "memoryCurrentBytes": current,
            "memoryMaxBytes": maximum,
            "memoryCurrentMaxExclusiveBytes": _MEMORY_ADMISSION_MAX,
            "fileCacheBytes": file_cache,
            "fileCacheMaxBytes": _FILE_CACHE_MAX,
            "memoryStat": stat,
            "memoryEventsLocal": events,
            "memoryEventsLocalSha256": hashlib.sha256(events_text).hexdigest(),
            "swapCurrentBytes": swap_current,
            "swapMaxBytes": swap_max,
            "pvcAvailableBytes": available,
            "pvcAvailableMinExclusiveBytes": _PVC_AVAILABLE_MIN,
            "residualGpuProcesses": [],
        }


class ExactPosixPageCacheReclaimer:
    def __init__(
        self,
        *,
        allowed_weights: tuple[tuple[str, str], ...],
        persistent_root: Path,
        advise: Callable[[int, int, int, int], None] | None = None,
        memory_snapshot: Callable[[], dict[str, int]] | None = None,
        wait_seconds: float = 120,
    ) -> None:
        self._allowed = allowed_weights
        self._persistent = persistent_root.resolve()
        self._advise = advise or self._native_advise
        self._snapshot = memory_snapshot or self._cgroup_snapshot
        self._wait = wait_seconds

    @staticmethod
    def _native_advise(descriptor: int, offset: int, length: int, advice: int) -> None:
        function = getattr(os, "posix_fadvise", None)
        if not callable(function):
            raise RuntimeWiringError("POSIX_FADV_DONTNEED is unavailable")
        function(descriptor, offset, length, advice)

    @staticmethod
    def _cgroup_snapshot() -> dict[str, int]:
        stat = _parse_key_values(Path("/sys/fs/cgroup/memory.stat"))
        try:
            current = int(Path("/sys/fs/cgroup/memory.current").read_text().strip())
        except (OSError, ValueError) as exc:
            raise RuntimeWiringError("cgroup memory snapshot is unavailable") from exc
        return {"memoryCurrentBytes": current, "fileCacheBytes": int(stat["file"])}

    def reclaim(self, exact_weights: tuple[tuple[str, str], ...]) -> dict[str, object]:
        if exact_weights != self._allowed:
            raise RuntimeWiringError("page-cache reclaim is not manifest-bound")
        before = self._snapshot()
        records: list[dict[str, object]] = []
        for raw_path, digest in exact_weights:
            path = Path(raw_path)
            if _SHA256_RE.fullmatch(digest) is None or path.is_symlink():
                raise RuntimeWiringError("page-cache reclaim authority is invalid")
            try:
                resolved = path.resolve(strict=True)
                resolved.relative_to(self._persistent)
            except (OSError, ValueError) as exc:
                raise RuntimeWiringError("page-cache reclaim path is outside PVC") from exc
            if resolved != path or not path.is_file():
                raise RuntimeWiringError("page-cache reclaim requires a canonical regular file")
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(path, flags)
            try:
                self._advise(descriptor, 0, 0, POSIX_FADV_DONTNEED)
            except OSError as exc:
                raise RuntimeWiringError("targeted POSIX_FADV_DONTNEED failed") from exc
            finally:
                os.close(descriptor)
            records.append(
                {"path": str(path), "sha256": digest, "sizeBytes": path.stat().st_size}
            )
        deadline = time.monotonic() + self._wait
        after = self._snapshot()
        while (
            self._wait > 0
            and (
                after["memoryCurrentBytes"] >= _MEMORY_ADMISSION_MAX
                or after["fileCacheBytes"] > _FILE_CACHE_MAX
            )
            and time.monotonic() < deadline
        ):
            time.sleep(1)
            after = self._snapshot()
        return {
            "schemaVersion": "amd.targeted-page-cache-reclaim.v1",
            "capturedAt": _utc_now(),
            "advice": "POSIX_FADV_DONTNEED",
            "files": records,
            "before": before,
            "after": after,
        }


def probe_h3_media(
    path: Path,
    *,
    command_runner: Callable[..., Any] = subprocess.run,
    ffprobe_path: str | None = None,
) -> Any:
    if not path.is_file():
        raise RuntimeWiringError("H3 output is unavailable for ffprobe")
    executable = ffprobe_path or os.environ.get("AMD_FFPROBE") or shutil.which("ffprobe")
    if not executable:
        raise RuntimeWiringError("ffprobe is unavailable")
    completed = command_runner(
        [
            executable,
            "-v",
            "error",
            "-count_frames",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(path),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=90,
    )
    if completed.returncode != 0:
        raise RuntimeWiringError("ffprobe failed")
    try:
        payload = json.loads(completed.stdout)
        streams = payload["streams"]
        format_value = payload["format"]
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeWiringError("ffprobe returned invalid JSON") from exc
    if not isinstance(streams, list) or not isinstance(format_value, dict):
        raise RuntimeWiringError("ffprobe returned invalid stream authority")
    video = [item for item in streams if isinstance(item, dict) and item.get("codec_type") == "video"]
    audio = [item for item in streams if isinstance(item, dict) and item.get("codec_type") == "audio"]
    subtitles = [item for item in streams if isinstance(item, dict) and item.get("codec_type") == "subtitle"]
    if len(video) != 1 or not audio:
        raise RuntimeWiringError("H3 output must contain one video and native audio")
    if subtitles:
        raise RuntimeWiringError("H3 output must not contain a subtitle stream")
    try:
        rate = Fraction(str(video[0]["avg_frame_rate"]))
        frames = int(video[0].get("nb_read_frames", video[0].get("nb_frames")))
        duration = float(format_value["duration"])
        format_name = str(format_value["format_name"])
    except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
        raise RuntimeWiringError("ffprobe media metrics are invalid") from exc
    if not 2.8 <= duration <= 3.5 or "mp4" not in format_name.casefold():
        raise RuntimeWiringError("ffprobe duration or container is invalid")
    if not 65 <= frames <= 90:
        raise RuntimeWiringError("ffprobe frame count seriously diverges from 73")
    if not Fraction(20, 1) <= rate <= Fraction(30, 1):
        raise RuntimeWiringError("ffprobe frame rate seriously diverges from 24 fps")
    if abs((frames / float(rate)) - duration) > 0.35:
        raise RuntimeWiringError("ffprobe frame metadata seriously diverges from duration")
    runner = _runner_module()
    return runner.MediaProbeSummary(
        duration_seconds=duration,
        fps=float(rate),
        frame_count=frames,
        video_streams=len(video),
        audio_streams=len(audio),
        subtitle_streams=len(subtitles),
        format_name=format_name,
    )


class PersistentH3AuthorityFactory:
    """Load a post-FLUX, append-only H3 authority envelope on first H3 use."""

    def __init__(self, *, manifest_path: Path, template_path: Path, persistent_root: Path) -> None:
        self._manifest_path = manifest_path
        self._template_path = template_path
        self._persistent_root = persistent_root

    def __call__(self, references: tuple[Any, ...]) -> Any:
        path = _persistent_file(self._manifest_path, self._persistent_root, "H3 runner authority")
        value = _json_object(path, "H3 runner authority")
        expected = {
            "schemaVersion",
            "capabilityManifestPath",
            "capabilityManifestSha256",
            "plan",
            "planSha256",
            "referenceArtifacts",
            "seed",
            "jobAuthorityDigest",
            "inputAuthorityDigest",
            "workflowRunId",
            "authoritySha256",
        }
        if (
            set(value) != expected
            or value["schemaVersion"] != "amd.h3-execution-authority.v1"
            or _SHA256_RE.fullmatch(str(value["jobAuthorityDigest"])) is None
            or _SHA256_RE.fullmatch(str(value["inputAuthorityDigest"])) is None
        ):
            raise RuntimeWiringError("H3 runner authority fields are not frozen")
        try:
            UUID(str(value["workflowRunId"]))
        except (TypeError, ValueError) as exc:
            raise RuntimeWiringError("H3 workflow run identity is invalid") from exc
        identity = dict(value)
        claimed = identity.pop("authoritySha256")
        if not isinstance(claimed, str) or claimed != _canonical_sha256(identity):
            raise RuntimeWiringError("H3 runner authority digest mismatch")
        capability_path = _persistent_file(
            Path(str(value["capabilityManifestPath"])),
            self._persistent_root,
            "H3 capability manifest",
        )
        if (
            not isinstance(value["capabilityManifestSha256"], str)
            or _sha256_file(capability_path) != value["capabilityManifestSha256"]
        ):
            raise RuntimeWiringError("H3 capability manifest SHA mismatch")
        loaded = load_h3_amd_capability(
            capability_path,
            workflow_path=self._template_path,
            verify_files=False,
        )
        plan_value = value["plan"]
        if type(plan_value) is not dict or value["planSha256"] != _canonical_sha256(plan_value):
            raise RuntimeWiringError("H3 plan digest mismatch")
        artifacts = value["referenceArtifacts"]
        if plan_value.get("schemaVersion") == "amd.competition-single-reference-h3-plan.v1":
            prompt = plan_value.get("prompt")
            imported = (
                plan_value.get("referenceProfile")
                == "competition-imported-single-view-v1"
            )
            if (
                set(plan_value)
                != {
                    "schemaVersion",
                    "referenceProfile",
                    "sourceMode",
                    "requiredImages",
                    "view",
                    "requestedDurationSeconds",
                    "frameCount",
                    "fps",
                    "prompt",
                    "promptSha256",
                }
                or plan_value.get("referenceProfile")
                not in {
                    "competition-imported-single-view-v1",
                    "competition-prompt-single-view-v1",
                }
                or plan_value.get("sourceMode")
                != ("preuploaded_imported" if imported else "prompt_synthesized")
                or plan_value.get("requiredImages") != 1
                or plan_value.get("view") != "front_three_quarter"
                or plan_value.get("requestedDurationSeconds") != 3.0
                or plan_value.get("frameCount") != 73
                or plan_value.get("fps") != 24
                or type(prompt) is not str
                or not prompt.strip()
                or hashlib.sha256(prompt.encode("utf-8")).hexdigest()
                != plan_value.get("promptSha256")
                or not isinstance(artifacts, list)
                or len(artifacts) != 1
                or len(references) != 1
                or references[0].view_name != "front_three_quarter"
                or (
                    imported
                    and (
                        getattr(references[0], "source_mode", None)
                        != "preuploaded_imported"
                        or getattr(references[0], "generated_by_current_flux", True)
                        is not False
                        or getattr(references[0], "flux_output_used", True) is not False
                    )
                )
            ):
                raise RuntimeWiringError(
                    "competition single-reference H3 plan is invalid"
                )
            item = artifacts[0]
            if type(item) is not dict or set(item) != {
                "viewName",
                "assetId",
                "artifactRef",
                "sha256",
                "remoteName",
                "compiledWorkflowSha256",
            }:
                raise RuntimeWiringError(
                    "competition H3 reference artifact fields are not frozen"
                )
            try:
                asset_id = UUID(str(item["assetId"]))
            except ValueError as exc:
                raise RuntimeWiringError("H3 reference asset id is invalid") from exc
            generated = references[0]
            if (
                item["viewName"] != "front_three_quarter"
                or item["sha256"] != generated.sha256
                or item["compiledWorkflowSha256"]
                != generated.compiled_workflow_sha256
                or not isinstance(item["artifactRef"], str)
                or not item["artifactRef"]
            ):
                raise RuntimeWiringError(
                    "competition H3 reference diverges from the imported asset"
                )
            staged_reference = H3StagedReference(
                asset_id=asset_id,
                sha256=item["sha256"],
                remote_name=str(item["remoteName"]),
            )
            seed = value["seed"]
            concrete = build_competition_single_reference_comfy_api_workflow(
                capability=loaded.capability,
                template_path=self._template_path,
                sequence_id=str(value["workflowRunId"]),
                prompt=prompt,
                prompt_sha256=str(plan_value["promptSha256"]),
                staged_reference=staged_reference,
                seed=seed,
            )
            runner = _runner_module()
            return runner.H3BuildAuthority(
                compiled=None,
                plan=plan_value,
                rendered=None,
                binding=None,
                capability=loaded.capability,
                template_path=self._template_path,
                staged_references=(staged_reference,),
                seed=seed,
                reference_profile=str(plan_value["referenceProfile"]),
                concrete=concrete,
            )
        try:
            plan = H3SequencePlanV1.model_validate(plan_value, strict=True)
        except ValueError as exc:
            raise RuntimeWiringError("H3 plan is invalid") from exc
        if (
            plan.requested_duration_seconds != 3.0
            or plan.frame_count != 73
            or plan.fps != 24
        ):
            raise RuntimeWiringError("H3 plan is not the three-second contract")
        if not isinstance(artifacts, list) or len(artifacts) != len(_PRODUCTION_VIEW_ORDER):
            raise RuntimeWiringError("H3 reference artifact authority is invalid")
        if tuple(item.view_name for item in references) != _PRODUCTION_VIEW_ORDER:
            raise RuntimeWiringError("H3 generated references are not canonical")
        approved: dict[UUID, ApprovedH3Asset] = {}
        staged: list[H3StagedReference] = []
        for view, generated, item in zip(
            _PRODUCTION_VIEW_ORDER, references, artifacts, strict=True
        ):
            if type(item) is not dict or set(item) != {
                "viewName",
                "assetId",
                "artifactRef",
                "sha256",
                "remoteName",
            }:
                raise RuntimeWiringError("H3 reference artifact fields are not frozen")
            try:
                asset_id = UUID(str(item["assetId"]))
            except ValueError as exc:
                raise RuntimeWiringError("H3 reference asset id is invalid") from exc
            if (
                item["viewName"] != view
                or item["sha256"] != generated.sha256
                or not isinstance(item["artifactRef"], str)
                or not item["artifactRef"]
            ):
                raise RuntimeWiringError("H3 reference authority diverges from FLUX output")
            approved[asset_id] = ApprovedH3Asset(
                asset_id=asset_id,
                artifact_ref=item["artifactRef"],
                sha256=item["sha256"],
                media_type="image",
            )
            staged.append(
                H3StagedReference(
                    asset_id=asset_id,
                    sha256=item["sha256"],
                    remote_name=str(item["remoteName"]),
                )
            )
        binding = bind_h3_references(plan, approved)
        rendered = H3PromptRenderer().render(plan, binding, loaded.capability)
        compiled = build_h3_workflow(plan, rendered, binding, loaded.capability)
        seed = value["seed"]
        if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= 2**63 - 1:
            raise RuntimeWiringError("H3 seed is invalid")
        runner = _runner_module()
        return runner.H3BuildAuthority(
            compiled=compiled,
            plan=plan,
            rendered=rendered,
            binding=binding,
            capability=loaded.capability,
            template_path=self._template_path,
            staged_references=tuple(staged),
            seed=seed,
        )


def _flux_generation_authority(click_path: Path, persistent_root: Path) -> dict[str, Any]:
    click = _json_object(click_path, "click authority")
    workflow_path = _persistent_file(
        Path(str(click.get("workflowPath", ""))), persistent_root, "click workflow"
    )
    workflow_sha = click.get("workflowSha256")
    if not isinstance(workflow_sha, str) or _sha256_file(workflow_path) != workflow_sha:
        raise RuntimeWiringError("click workflow SHA mismatch")
    workflow = _json_object(workflow_path, "click workflow")
    authority = workflow.get("fluxReferenceGeneration")
    if type(authority) is not dict or set(authority) != {
        "schemaVersion",
        "referenceProfile",
        "sourceMode",
        "requiredImages",
        "view",
        "prompt",
        "promptSha256",
        "seed",
        "workflowSha256",
        "generationInvocationCount",
        "technicalRetryLimit",
        "authoritySha256",
    }:
        raise RuntimeWiringError("FLUX generation authority fields are not frozen")
    identity = dict(authority)
    claimed = identity.pop("authoritySha256")
    if (
        authority["schemaVersion"]
        != "amd.flux-prompt-single-reference-generation.v1"
        or claimed != _canonical_sha256(identity)
        or authority["referenceProfile"]
        != "competition-prompt-single-view-v1"
        or authority["sourceMode"] != "prompt_synthesized"
        or authority["requiredImages"] != 1
        or authority["view"] != "front_three_quarter"
        or type(authority["prompt"]) is not str
        or not authority["prompt"].strip()
        or hashlib.sha256(authority["prompt"].encode("utf-8")).hexdigest()
        != authority["promptSha256"]
        or isinstance(authority["seed"], bool)
        or not isinstance(authority["seed"], int)
        or not 0 <= authority["seed"] < 2**64
        or _SHA256_RE.fullmatch(str(authority["workflowSha256"])) is None
        or authority["generationInvocationCount"] != 1
        or authority["technicalRetryLimit"] != 1
    ):
        raise RuntimeWiringError("FLUX generation authority is invalid")
    return dict(authority)


def create_runner(arguments: Any) -> Any:
    """Build the runner adapters without starting ComfyUI or touching the GPU."""

    runner = _runner_module()
    required = (
        "persistent_root",
        "click_authority",
        "checkpoint",
        "evidence_root",
        "output",
        "flux_manifest",
        "flux_workflow_root",
        "h3_manifest",
        "h3_template",
    )
    if any(not hasattr(arguments, name) for name in required):
        raise RuntimeWiringError("runner arguments are incomplete")
    persistent_root = Path(arguments.persistent_root).resolve()
    click_path = Path(arguments.click_authority).resolve()
    generation = _flux_generation_authority(click_path, persistent_root)
    try:
        loaded_flux = load_flux2_dev_capability(Path(arguments.flux_manifest), verify_files=False)
        templates = load_flux2_workflow_templates(
            Path(arguments.flux_workflow_root), loaded_flux.capability
        )
    except (OSError, ValueError) as exc:
        raise RuntimeWiringError("FLUX capability or workflow authority is invalid") from exc

    runtime_root = Path(os.environ.get("AMD_RUNTIME_ROOT", ""))
    python_path = Path(os.environ.get("AMD_ROCM_PYTHON", ""))
    configured_persistent = Path(os.environ.get("AMD_ROOT", ""))
    if configured_persistent != Path("/persistent/douyin-amd"):
        raise RuntimeWiringError("AMD_ROOT must be /persistent/douyin-amd")
    if os.name == "posix" and persistent_root != configured_persistent.resolve(strict=True):
        raise RuntimeWiringError("runner persistent root must equal AMD_ROOT")
    processes = ProductionComfyProcessController(
        python_path=python_path,
        comfy_root=Path(str(loaded_flux.manifest.comfy_release_root)),
        runtime_root=runtime_root,
    )
    flux_authority = runner.FluxExecutionAuthority(
        capability=loaded_flux.capability,
        templates=templates,
        model_root=str(loaded_flux.model_root),
        reference_profile=generation["referenceProfile"],
        source_mode=generation["sourceMode"],
        required_images=generation["requiredImages"],
        view=generation["view"],
        prompt=generation["prompt"],
        prompt_sha256=generation["promptSha256"],
        seed=generation["seed"],
        workflow_sha256=generation["workflowSha256"],
        generation_invocation_count=generation["generationInvocationCount"],
        technical_retry_limit=generation["technicalRetryLimit"],
    )
    if (
        flux_authority.workflow_sha256
        != loaded_flux.capability.workflow("text_to_image").sha256
    ):
        raise RuntimeWiringError("FLUX prompt authority is not pinned to the T2I workflow")
    exact_weights = flux_authority.exact_weight_authority()
    runtime_inputs = runner.VerticalSliceRuntimeInputs(
        persistent_root=persistent_root,
        click_authority_path=click_path,
        checkpoint_path=Path(arguments.checkpoint).resolve(),
        evidence_root=Path(arguments.evidence_root).resolve(),
        output_path=Path(arguments.output).resolve(),
    )
    return runner.VerticalSliceRunner(
        runtime_inputs=runtime_inputs,
        flux_authority=flux_authority,
        h3_authority_factory=PersistentH3AuthorityFactory(
            manifest_path=Path(arguments.h3_manifest).resolve(),
            template_path=Path(arguments.h3_template).resolve(),
            persistent_root=persistent_root,
        ),
        processes=processes,
        session_factory=LoopbackComfySessionFactory(processes),
        memory_gate=CgroupMemoryAdmissionGate(persistent_root=persistent_root),
        page_cache_reclaimer=ExactPosixPageCacheReclaimer(
            allowed_weights=exact_weights,
            persistent_root=persistent_root,
        ),
        media_probe=probe_h3_media,
    )


__all__ = [
    "CgroupMemoryAdmissionGate",
    "ExactPosixPageCacheReclaimer",
    "LoopbackComfySession",
    "LoopbackComfySessionFactory",
    "PersistentH3AuthorityFactory",
    "POSIX_FADV_DONTNEED",
    "ProductionComfyProcessController",
    "RuntimeWiringError",
    "create_runner",
    "probe_h3_media",
]
